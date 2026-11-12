/**
 * The parameterization half of CG Bond Interactions: one pane's model state, and the panel's one fit card.
 *
 * The panel has two comparison panes, and each is a whole model workspace: `setupPane` owns one pane's record
 * (which revision is shown, which is current), its terms save and its Make current. `setupFitCard` owns the merged
 * "Model and fit" card above both panes -- the fit target's molecule/mapping selects, the AA reference, the engine,
 * the threshold and temperature, the mapping's torsion model, the fit job and the result -- and it exists once.
 *
 * A **parameterization** is a mapping's bonded terms together with the provenance of those terms, and it is
 * produced by a job of this panel's own. It makes no MD, so nothing here becomes a run: a run consumes the
 * revision this panel makes current and records which. The design is
 * `docs/design/2026-10-16-parameterization-and-new-run.md`.
 *
 * **Shown is not current.** `shownRevision()` is the display-only choice a pane's selector makes: it drives
 * `termsOf`, the result card and the scene, and reading it reads no route and writes nothing. `currentRevision()` is
 * what a run consumes. **Save in place** rewrites the shown revision only while it is current *and* the server's
 * `edit_gate` allows it; **Save as new** appends a clone and makes it current; both are POSTs to the terms route.
 * The gate is the server's answer (`save_in_place`, `save_in_place_reason`, `parameters_editable`), never re-derived
 * here: a fresh fit's first edit is Save as new, and a `martini-reference` transcription is read-only.
 *
 * Every reading is taken from the routes and none is reconstructed here:
 *
 *   GET    /api/molecules                                              -> {molecules}      (the fit target)
 *   GET    /api/mappings?view=summary&molecule_id=                     -> {candidates}     (its saved mappings)
 *   GET    /api/mappings/<file>                                        -> the candidate snapshot
 *   GET    /api/bonded-parameterizations/engines                      -> {engines: [{value, label, needs_reference}]}
 *   GET    /api/bonded-parameterizations?content_hash=&mapping_hash=  -> {summary, revisions, jobs}
 *   GET    /api/bonded-parameterizations/jobs?job_id=                 -> {jobs}   (polled while live)
 *   POST   /api/bonded-parameterizations                              -> the job record
 *   POST   /api/bonded-parameterizations/jobs/<id>/cancel             -> the job record
 *   POST   /api/bonded-parameterizations/<content_hash>/terms         -> the record (in_place / new)
 *   PATCH  /api/bonded-parameterizations/<content_hash>               -> the record
 *
 * Three rules this module exists to keep:
 *
 * 1. **A superseded answer never reaches the screen.** Every job the panel watches gets a generation token
 *    (`jobToken`), the token is re-checked after every await, and a fit-target switch bumps it -- the same
 *    arrangement `run-view-monitor.js` uses for a superseded load. A poll that belongs to a job the reader has
 *    replaced is dropped, not painted. The two answers this module awaits itself -- queueing a fit, cancelling one
 *    -- are checked against `generation` for the same reason: their bodies belong to the target the reader has since
 *    left, and painting them here would put one model's job on another model's card.
 * 2. **Polling stops.** It stops when the job reaches a terminal status (`completed`, `failed`, `cancelled`),
 *    and it stops while the panel is off screen -- `visible()` reads the section's own `hidden` attribute and
 *    the page's, exactly as `runs.js` does before each fetch, and a `visibilitychange` / `dashboard:tab`
 *    listener resumes it when the reader comes back to a job that is still live.
 * 3. **A failure is shown as what it recorded.** A job whose record carries `failed` is rendered with its
 *    `error` and its `log_tail`; "failed" on its own is not a report.
 *
 * `window.__bondedPollMs` is the one test seam: the browser tier sets the cadence to a few hundred
 * milliseconds, and one test in that tier runs the default, so the default cannot rot unnoticed.
 */
import { $, api, cachedApi, post, setText, liveVisible, whenLive, CATALOGUE_MAX_AGE } from './shared.js';

/** Fast_Forward's own `-constraints` default, and this repository's convention. Stated so the field can show it. */
export const DEFAULT_CONSTRAINTS = 10000;
export const DEFAULT_TEMPERATURE = 300;
/** The cadence the job box polls at while a fit is queued or running: every few seconds, not every second. */
export const POLL_MS = 3000;
/** What a published reference is, in the server's own terms: it carries no revision, so no route answers this. */
export const REFERENCE_REASON = 'The published Martini 3 reference is read-only; a CG run consumes it directly.';

const LIVE = new Set(['queued', 'running']);
const TERMINAL = new Set(['completed', 'failed', 'cancelled']);
const TORSION_MODELS = new Set(['legacy', 'circular-harmonic']);
/** The GROMACS sections a bonded term lives in, and how many atoms each names before its function. */
const SECTION_WIDTHS = {bonds: 2, angles: 3, dihedrals: 4, constraints: 2};
const CHECK_NAMES = ['dihedral-fit', 'bonded-cross-check'];
const number = value => Number(value).toLocaleString('en-GB');

/**
 * Parse a GROMACS ITP into the rows the interactions table shows.
 *
 * This mirrors `models/bonded.parse_interactions`, which is what the store reads when it computes a
 * revision's `sources`: the two must agree on `id` (`kind:n`) or the source column would answer for the
 * wrong term. Atom names are read from the `[ atoms ]` section, which is the only place the revision's
 * topology states them.
 */
export function parseTopology(topology) {
  const names = new Map();
  const rows = [];
  const counts = {};
  let section = null;
  for (const raw of String(topology || '').split('\n')) {
    const line = raw.split(';')[0].trim();
    if (!line || line.startsWith('#')) continue;
    if (line.startsWith('[') && line.endsWith(']')) { section = line.slice(1, -1).trim().toLowerCase(); continue; }
    const fields = line.split(/\s+/);
    if (section === 'atoms') {
      const index = Number(fields[0]);
      if (fields.length >= 5 && Number.isFinite(index)) names.set(index, fields[4]);
      continue;
    }
    if (section === 'virtual_sitesn') {
      const site = Number(fields[0]);
      if (fields.length < 3 || !Number.isFinite(site)) continue;
      counts[section] = (counts[section] || 0) + 1;
      rows.push({id: `${section}:${counts[section]}`, kind: section,
                 beads: [names.get(site) ?? String(site)], function: fields[1], parameters: [],
                 parents: fields.slice(2).map(value => names.get(Number(value)) ?? value)});
      continue;
    }
    const width = SECTION_WIDTHS[section];
    if (!width || fields.length < width + 1) continue;
    const indices = fields.slice(0, width).map(Number);
    if (indices.some(value => !Number.isFinite(value))) continue;
    counts[section] = (counts[section] || 0) + 1;
    rows.push({id: `${section}:${counts[section]}`, kind: section,
               beads: indices.map(index => names.get(index) ?? String(index)),
               function: fields[width], parameters: fields.slice(width + 1)});
  }
  return rows;
}

/**
 * A revision's terms, each carrying the `source` the store computed for it.
 *
 * The store's `sources` list is keyed by the same ids `parseTopology` produces, because both sides number a
 * section's terms in the order the topology states them. A term with no row says `unrecorded` and nothing else: the
 * engine's name is a claim the record did not make, and inventing one here would hide exactly the case the column
 * exists for (a revision written before the column existed).
 */
function termsOf(revision) {
  if (!revision || !revision.topology) return [];
  const declared = new Map();
  for (const row of revision.sources || []) if (row && row.id) declared.set(row.id, row.source);
  // The editable flag, the function labels and the parameter labels are bonded.js's (it owns FUNCTION_OPTIONS);
  // this reader only adds the source the store computed. Keeping the function table out of here avoids a circular
  // import and a second copy of it.
  return parseTopology(revision.topology).map(row => ({
    ...row,
    source: declared.get(row.id) || 'unrecorded',
  }));
}

const sourceLabel = value => ({'martini-reference': 'Martini 3 reference transcription'})[value] || value || 'fit';

/**
 * One pane's state: the mapping it shows, which revision is shown, and the server's edit gate for it.
 *
 * The pane reads a mapping's whole record (summary, revisions) and hands its shown revision's terms to `onTerms`;
 * it owns Make current, both terms-save buttons and the record's status. It reports every write through `onChanged`
 * so the host can reload the *other* pane when it shows the same mapping, and it never touches the fit card.
 */
export function setupPane({root, suffix, onTerms, onRecord, onChanged = () => {}, fitBusy = () => false}) {
  const id = name => root.querySelector('#' + name + suffix);
  const mappingFacts = id('bonded-mapping-facts');
  const modelSummary = id('bonded-model-summary');
  const modelBadge = id('bonded-model-badge');
  const shownStatus = id('bonded-shown-status');
  const makeCurrentButton = id('bonded-make-current');
  let mapping = null;
  let summary = null;
  let revisions = [];
  let readOnly = false;
  //: The revision the pane *shows*, which need not be the one a run consumes. `null` means "follow current".
  let shownRevisionNumber = null;
  let generation = 0;

  // --- readings ---------------------------------------------------------------------------------------------------

  const hash = () => (mapping && mapping.mapping_content_hash) || '';
  const currentNumber = () => (summary && summary.revision) ?? null;
  const currentRevision = () => revisions.find(item => item && item.revision === currentNumber()) || null;
  const shownRevision = () => revisions.find(item => item && item.revision === shownRevisionNumber)
    || (shownRevisionNumber === null ? currentRevision() : null);
  /** Whether Save in place can act: the shown revision is current *and* the server's gate allows it. */
  const canSaveInPlace = () => !readOnly && !!shownRevision()
    && shownRevision().revision === currentNumber() && shownRevision().save_in_place === true;
  const shownFile = () => (mapping && mapping.file) || '';
  const contentHash = () => hash() || (summary && summary.mapping_content_hash) || '';

  /** The server's sentence for why this pane's save controls cannot act, or `''` when one can. */
  function gateReason() {
    if (readOnly) return REFERENCE_REASON;
    if (!mapping) return 'Choose a model to read its terms.';
    const shown = shownRevision();
    if (!shown) return 'This model has no stored revision: its rows are the mapping\'s draft connectivity and cannot be saved here.';
    if (shown.revision !== currentNumber()) {
      return `Revision ${shown.revision} is earlier: Save in place writes the revision a run consumes. Make it current `
        + 'first, or use Save as new.';
    }
    if (shown.save_in_place !== true) {
      return shown.save_in_place_reason || `Revision ${shown.revision} cannot be saved in place.`;
    }
    return '';
  }

  // --- the model card ---------------------------------------------------------------------------------------------

  function renderModel() {
    const beads = (mapping && mapping.beads) || [];
    const physical = beads.filter(bead => !bead.virtual_site).length;
    setText(mappingFacts, mapping
      ? `${beads.length} beads · ${physical} physical · ${beads.length - physical} virtual sites`
        + `${(mapping.rings || []).length ? ` · ${(mapping.rings || []).length} rings` : ''}`
      : '');
    if (readOnly) {
      // The pane's own sentence, not a badge alone: a reader must learn both what this is and what cannot be done
      // with it before the disabled controls read as a fault.
      const entry = mapping?.reference_entry;
      setText(modelSummary, `The published Martini 3 reference${entry ? ` (${entry})` : ''} is a transcription`
        + ' of an upstream ITP; it cannot be re-parameterized here.');
      setText(modelBadge, 'published reference');
      modelBadge.dataset.status = 'completed';
      return;
    }
    const shown = shownRevision();
    const isCurrent = !!(shown && shown.revision === currentNumber());
    setText(modelSummary, !mapping
      ? 'Choose a mapping to read its revisions.'
      : !revisions.length
        ? 'No parameterization yet: a fit made here is stored as this mapping’s revision 1.'
        : isCurrent
          ? `Showing revision ${shown.revision}, the revision a run consumes.`
            + (revisions.length > 1 ? ' An earlier revision can be viewed without changing what a run uses.' : '')
          : `Showing revision ${shown.revision} (earlier). Runs still consume revision ${currentNumber()};`
            + ' this one is not what a new run would use until it is made current.');
    setText(modelBadge, !mapping ? 'no mapping'
      : !revisions.length ? 'no parameterization'
      : shown ? `revision ${shown.revision} · ${isCurrent ? 'current' : 'earlier'}` : 'no parameterization');
    if (revisions.length) modelBadge.dataset.status = 'completed';
    else delete modelBadge.dataset.status;
  }

  /** The one mutating control, and it names the revision the pane shows rather than the one it happens to hold. */
  function syncMakeCurrent() {
    if (!makeCurrentButton) return;
    const shown = shownRevision();
    const isCurrent = !!(shown && shown.revision === currentNumber());
    makeCurrentButton.disabled = readOnly || !mapping || !shown || isCurrent;
    makeCurrentButton.title = readOnly
      ? 'The published reference is read-only: it cannot be made current.'
      : !shown ? 'Choose a parameterization revision first.'
      : isCurrent ? 'The shown revision is already the one a run consumes.'
      : 'Make the shown revision the one a run consumes. Nothing is rewritten: every revision stays.';
  }

  async function makeCurrent() {
    const revision = shownRevision();
    if (!mapping || !revision || revision.revision === currentNumber()) return;
    if (!confirm(`Make revision ${revision.revision} current for this mapping? A run queued after this consumes it;`
                 + ' runs already queued keep the revision they recorded.')) return;
    const token = generation;
    try {
      await api('/api/bonded-parameterizations/' + encodeURIComponent(hash()), {
        method: 'PATCH', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({current: revision.revision, confirm: true}),
      });
      // `readRecord` drops a superseded answer; the sentence after it must be dropped with it.
      await readRecord(token);
      if (token !== generation) return;
      setText(shownStatus, `Revision ${revision.revision} is current.`);
      onChanged({file: shownFile(), contentHash: contentHash()});
    } catch (error) {
      if (token !== generation) return;
      setText(shownStatus, `Revision ${revision.revision} was not made current: ${error.message}`);
    }
  }

  // --- reading the record -----------------------------------------------------------------------------------------

  async function readRecord(token) {
    if (!mapping || readOnly) return;
    const params = new URLSearchParams();
    if (mapping.mapping_content_hash) params.set('content_hash', mapping.mapping_content_hash);
    if (mapping.mapping_hash) params.set('mapping_hash', mapping.mapping_hash);
    let answer;
    try {
      answer = await api('/api/bonded-parameterizations?' + params);
    } catch (error) {
      if (token !== generation) return;
      setText(shownStatus, `This model’s parameterization could not be read: ${error.message}`);
      return;
    }
    if (token !== generation) return;
    summary = (answer && answer.summary) || null;
    revisions = (answer && answer.revisions) || [];
    // The shown revision is this pane's own display state: an answer that does not carry it (a fresh read after a
    // model switch, a revision deleted elsewhere) falls back to the one a run consumes.
    if (shownRevisionNumber === null || !revisions.some(item => item.revision === shownRevisionNumber)) {
      shownRevisionNumber = currentNumber();
    }
    renderModel();
    syncMakeCurrent();
    // `null` when the record carries no revision: the table then shows the mapping's own draft and says so,
    // where an empty list would read as a revision whose terms had all been removed. Only the shown revision is
    // handed over: the table and the scene are never a second opinion about what is current.
    onTerms(shownRevision() ? termsOf(shownRevision()) : null);
    // The selector labels state which revision is current and which earlier, so the record's own answer is what
    // relabels them -- after a fit, a make-current or a delete.
    if (onRecord) onRecord({mapping, summary, revisions});
  }

  async function load(next, {shown} = {}) {
    const token = ++generation;
    mapping = next || null;
    readOnly = !!(mapping && mapping.read_only);
    summary = null;
    revisions = [];
    // The revision the caller asked to see. `null`/omitted means "this model's current one"; a read that cannot find
    // the requested number falls back to current rather than showing nothing.
    shownRevisionNumber = shown === undefined || shown === null ? null : Number(shown);
    setText(shownStatus, '');
    renderModel();
    syncMakeCurrent();
    onTerms(null);
    if (!mapping) {
      if (onRecord) onRecord({mapping: null, summary: null, revisions: []});
      return;
    }
    if (readOnly) return;
    await readRecord(token);
  }

  /** Show one revision of the mapping already loaded, without reading a route and without changing current. */
  function show(revision) {
    if (!mapping || readOnly) return false;
    const wanted = revisions.find(item => item.revision === Number(revision));
    shownRevisionNumber = wanted ? wanted.revision : currentNumber();
    setText(shownStatus, '');
    renderModel();
    syncMakeCurrent();
    // The table and the scene follow the shown revision, never `summary.revision`.
    onTerms(shownRevision() ? termsOf(shownRevision()) : null);
    return true;
  }

  /**
   * Save edited terms. `in_place` rewrites the current revision; `new` clones the shown one and makes it current.
   *
   * The server owns the gate; the checks here are immediate UX and quote its answer rather than restating a rule.
   * ponytail: no browser confirmation for terms. The button acts and the result/status says what changed (the same
   * unconditional `confirm: true` the in-place payload carries). A reader who wants a dialog can add it at this call.
   */
  async function saveTerms({mode, edits}) {
    if (mode === 'in_place' && readOnly) throw new Error(REFERENCE_REASON);
    if (mode === 'in_place' && !canSaveInPlace()) throw new Error(gateReason());
    const shown = shownRevision();
    if (!shown) throw new Error('This model has no stored revision to save');
    if (mode === 'new' && shown.parameters_editable === false) throw new Error(gateReason());
    if (!hash()) throw new Error('Choose a saved mapping first');
    const body = {mode, revision: shown.revision,
                  expected_revision: Number((summary && summary.revision) || 0),
                  terms: edits};
    if (mode === 'in_place') body.confirm = true;
    if (!shown.sha256) throw new Error('Reload the revision before saving: its digest was not read');
    body.expected_sha256 = shown.sha256;
    const record = await post('/api/bonded-parameterizations/' + encodeURIComponent(hash()) + '/terms', body);
    // The answer is the stored record; the pane reloads through the route it already reads (the record is the
    // answer, not the route's echo of it).
    return {record, revision: record.revision, file: (mapping && mapping.file) || ''};
  }

  // --- wiring -----------------------------------------------------------------------------------------------------

  if (makeCurrentButton) makeCurrentButton.onclick = () => makeCurrent();

  return {load, show, saveTerms, makeCurrent, revisionCount: () => revisions.length,
          isBusy: () => fitBusy(shownFile()) || fitBusy(contentHash()),
          contentHash, currentRevisionNumber: currentNumber, shownRevision,
          canSaveInPlace, gateReason, file: shownFile, readOnly: () => readOnly,
          renderModel, syncMakeCurrent};
}

/**
 * The merged "Model and fit" card: the fit target (molecule + its mapping), the AA reference and engine, the four
 * fit options, the mapping's torsion model, the job and its result.
 *
 * It exists once for the whole panel. The panes below only read records; a fit belongs to the mapping this card
 * names, and when the job completes `onFitted` tells the host which panes to reload.
 */
export function setupFitCard({loadMapping, onFitted = () => {}, onMessage = () => {}}) {
  const moleculeSelect = $('#bonded-fit-molecule');
  const mappingSelect = $('#bonded-fit-mapping');
  const mappingNote = $('#bonded-fit-mapping-note');
  const aaSelect = $('#bonded-aa-reference');
  const aaFacts = $('#bonded-aa-facts');
  const engineSelect = $('#bonded-engine');
  const engineNote = $('#bonded-engine-note');
  const threshold = $('#bonded-constraints-threshold');
  const thresholdNote = $('#bonded-constraints-note');
  const temperature = $('#bonded-temperature');
  const torsionModel = $('#bonded-torsion-model');
  const torsionScale = $('#bonded-torsion-scale');
  const torsionStatus = $('#bonded-torsion-status');
  const torsionSave = $('#bonded-save-torsion');
  const torsionInfo = $('#bonded-torsion-info');
  const torsionTip = $('#bonded-torsion-tip');
  const fitButton = $('#bonded-fit');
  const fitStatus = $('#bonded-fit-status');
  const jobBox = $('#bonded-job');
  const jobTitle = $('#bonded-job-title');
  const jobDetail = $('#bonded-job-detail');
  const jobStatus = $('#bonded-job-status');
  const jobBar = $('#bonded-job-bar');
  const jobSteps = $('#bonded-job-steps');
  const jobError = $('#bonded-job-error');
  const jobLog = $('#bonded-job-log');
  const cancelButton = $('#bonded-job-cancel');
  const resultBox = $('#bonded-result');
  const resultTitle = $('#bonded-result-title');
  const resultSummary = $('#bonded-result-summary');
  const resultBadge = $('#bonded-result-badge');
  const provenance = $('#bonded-result-provenance');
  const checksBox = $('#bonded-result-checks');
  if (!moleculeSelect || !fitButton) return {mount: async () => {}, isFitting: () => false};

  let molecule = '';
  let candidates = [];
  let selectedFile = '';
  let mapping = null;
  let summary = null;
  let revisions = [];
  let engines = [];
  let enginesError = '';
  let references = [];
  let referencesError = '';
  //: Completed AA-only runs the route refused to offer, with the reason. Named rather than hidden: a copied-in run
  //: that fails verification is the case this exists for, and an empty list alone says nothing about it.
  let unavailableReferences = [];
  let job = null;
  let busy = false;
  let shownRevisionNumber = null;
  let generation = 0;
  let jobToken = 0;
  let timer = null;

  const hash = () => (mapping && mapping.mapping_content_hash) || '';
  const currentNumber = () => (summary && summary.revision) ?? null;
  const currentRevision = () => revisions.find(item => item && item.revision === currentNumber()) || null;
  const shownRevision = () => revisions.find(item => item && item.revision === shownRevisionNumber)
    || (shownRevisionNumber === null ? currentRevision() : null);
  const engineLabel = value => (engines.find(item => item.value === value) || {}).label
    || sourceLabel(value);
  const pollMilliseconds = () => Number(window.__bondedPollMs) || POLL_MS;
  const visible = () => {
    const panel = fitButton.closest('.panel') || fitButton;
    return !panel.hidden && liveVisible();
  };
  const date = iso => (typeof iso === 'string' ? iso.slice(0, 10) : '');
  const clock = iso => (typeof iso === 'string' ? iso.slice(11, 19) : '');

  function stopPolling() { clearTimeout(timer); timer = null; }

  // --- the fit target ---------------------------------------------------------------------------------------------

  /** Every AA molecule the catalogue offers: a CG composition cannot be fitted, so it is not offered here. */
  async function fillMolecules() {
    let list = [];
    try {
      const answer = await cachedApi('/api/molecules', {maxAge: CATALOGUE_MAX_AGE});
      list = (answer.molecules || []).filter(record => record.kind !== 'cg');
    } catch (error) { list = []; }
    const previous = moleculeSelect.value;
    moleculeSelect.replaceChildren(...list.map(record => new Option(record.name || record.id, record.id)));
    if ([...moleculeSelect.options].some(option => option.value === previous)) moleculeSelect.value = previous;
    else if (moleculeSelect.options.length) moleculeSelect.selectedIndex = 0;
    molecule = moleculeSelect.value;
  }

  /** The chosen molecule's saved mappings, and the fit target's own record. One mapping is implied, not hidden. */
  async function fillMappings(nextMolecule) {
    // An AA reference belongs to one molecule's runs: another molecule's list must not survive the switch, and a
    // run of the previous molecule must not stay chosen for this one.
    const switched = (nextMolecule || '') !== molecule;
    molecule = nextMolecule || '';
    if (switched) {
      references = [];
      referencesError = '';
      unavailableReferences = [];
      aaSelect.replaceChildren(new Option('Reading the AA references…', ''));
    }
    let list = [];
    if (molecule) {
      try {
        const answer = await cachedApi(
          '/api/mappings?view=summary&molecule_id=' + encodeURIComponent(molecule), {maxAge: CATALOGUE_MAX_AGE});
        list = (answer.candidates || []).filter(candidate => !candidate.error && candidate.file);
      } catch (error) { list = []; }
    }
    candidates = list;
    const previous = selectedFile;
    mappingSelect.replaceChildren(...list.map(candidate =>
      new Option(candidate.name || candidate.file, candidate.file)));
    const label = mappingSelect.closest('label');
    if (label) label.hidden = list.length <= 1;
    if (list.some(candidate => candidate.file === previous)) mappingSelect.value = previous;
    else if (list.length) mappingSelect.value = list[0].file;
    const chosen = list.find(candidate => candidate.file === mappingSelect.value);
    setText(mappingNote, !list.length
      ? `No saved mapping for ${molecule || 'this molecule'} yet: a fit belongs to one saved mapping.`
      : list.length === 1
        ? `Mapping to fit: ${chosen ? chosen.name || chosen.file : list[0].name || list[0].file}.`
        : 'The fit is stored in the mapping you choose above.');
    await loadTarget(mappingSelect.value);
  }

  /** Read the chosen mapping's own candidate, its parameterization record and its AA references. */
  async function loadTarget(file) {
    const token = ++generation;
    stopPolling();
    jobToken += 1;
    const previous = (mapping && mapping.mapping_content_hash) || '';
    selectedFile = file || '';
    mapping = null;
    summary = null;
    revisions = [];
    shownRevisionNumber = null;
    job = null;
    jobBox.hidden = true;
    resultBox.hidden = true;
    renderJob();
    renderResult();
    setText(fitStatus, '');
    if (!selectedFile) {
      references = [];
      referencesError = '';
      unavailableReferences = [];
      aaSelect.replaceChildren(new Option('Choose a mapping first', ''));
      setText(aaFacts, '');
      fillTorsion();
      updateTorsion();
      updateFit();
      return;
    }
    let candidate;
    try {
      candidate = await loadMapping(selectedFile);
    } catch (error) {
      if (token !== generation) return;
      fillTorsion();
      updateTorsion();
      setText(fitStatus, `The mapping could not be read: ${error.message}`);
      updateFit();
      return;
    }
    if (token !== generation) return;
    mapping = candidate || null;
    // The threshold and temperature are the fit's settings and start from their defaults on a new target, as they
    // always have: they are not a property the mapping carries.
    if (!previous || (mapping && mapping.mapping_content_hash !== previous)) {
      threshold.value = String(DEFAULT_CONSTRAINTS);
      temperature.value = String(DEFAULT_TEMPERATURE);
    }
    fillTorsion();
    updateTorsion();
    await Promise.all([readReferences(molecule, token), readRecord(token)]);
    updateFit();
  }

  // --- the torsion model, a property of the mapping ---------------------------------------------------------------

  /**
   * What this mapping says now: `legacy` is the default when the mapping's own options state nothing.
   *
   * The two controls are the mapping's property as much as the fit's: `bonded.refine` reads them out of the
   * mapping's `model.json` in stage 3, so the pair chosen here is both what this fit uses and what
   * "Save to mapping" writes into the file a run is queued from.
   */
  function storedTorsion() {
    const options = (mapping && mapping.bonded_options) || {};
    const model = options.torsion_model === 'circular-harmonic' ? 'circular-harmonic' : 'legacy';
    return {torsion_model: model,
            torsion_scale: model === 'circular-harmonic' ? Number(options.torsion_scale ?? 1) : null};
  }
  function chosenTorsion() {
    const model = TORSION_MODELS.has(torsionModel.value) ? torsionModel.value : 'legacy';
    return {torsion_model: model,
            torsion_scale: model === 'circular-harmonic' ? Number(torsionScale.value) : null};
  }
  function torsionSentence(options) {
    return options.torsion_model === 'circular-harmonic'
      ? `stage 3 fits every torsion to the AA distribution at stiffness ${options.torsion_scale}`
      : 'stage 3 keeps the periodic torsions the fit recorded';
  }
  function updateTorsion() {
    const stored = storedTorsion();
    const chosen = chosenTorsion();
    torsionModel.disabled = !mapping;
    torsionScale.disabled = !mapping || chosen.torsion_model !== 'circular-harmonic';
    const changed = chosen.torsion_model !== stored.torsion_model
      || (chosen.torsion_scale ?? null) !== (stored.torsion_scale ?? null);
    torsionSave.disabled = !mapping || !changed;
    setText(torsionStatus, !mapping
      ? 'Choose a mapping to read its torsion model.'
      : changed
        ? `Unsaved: ${torsionSentence(chosen)}. Save it to the mapping to use it there.`
        : `This mapping: ${torsionSentence(stored)}.`);
  }
  function fillTorsion() {
    const stored = storedTorsion();
    torsionModel.value = stored.torsion_model;
    torsionScale.value = stored.torsion_scale ?? 1;
  }

  /** The torsion explainer: one (i) control; Escape and a click outside the help close it. */
  function closeTorsionTip() {
    if (!torsionTip) return;
    torsionTip.classList.remove('is-open');
    torsionInfo?.setAttribute('aria-expanded', 'false');
  }
  if (torsionInfo && torsionTip) {
    torsionInfo.onclick = event => {
      event.stopPropagation();
      const open = !torsionTip.classList.contains('is-open');
      torsionTip.classList.toggle('is-open', open);
      torsionInfo.setAttribute('aria-expanded', String(open));
    };
    document.addEventListener('keydown', event => { if (event.key === 'Escape') closeTorsionTip(); });
    document.addEventListener('click', event => {
      if (!event.target.closest('.bonded-torsion-help')) closeTorsionTip();
    });
  }

  /**
   * Saving is an in-place rewrite of the saved candidate, the same write the mapping editor's own in-place save
   * makes: the file keeps its identity (so a run's recorded `mapping_candidate` still names this mapping) and its
   * content changes, which is what makes the switch reach the runs that follow it.
   */
  async function saveTorsion() {
    if (!mapping) return;
    const chosen = chosenTorsion();
    // The scale key is left out rather than sent as null: the model's validator reads a present `torsion_scale`
    // under either model, and refuses one it cannot use.
    const options = chosen.torsion_scale === null ? {torsion_model: chosen.torsion_model} : chosen;
    torsionSave.disabled = true;
    try {
      const saved = await post('/api/mappings/drafts', {...mapping, bonded_options: options, in_place: true});
      Object.assign(mapping, saved);
      updateTorsion();
      onMessage(`Torsion model saved to ${saved.file}: runs queued from it refine this way.`);
    } catch (error) {
      onMessage(error.message);
      updateTorsion();
    }
  }

  // --- the engines, the AA reference and the four options ---------------------------------------------------------

  function renderEngines() {
    const chosen = engineSelect.value;
    engineSelect.replaceChildren();
    // The requirement travels on the option as well as in the note under the select: which engines fit to an
    // ensemble is a fact about them, and a reader scanning the list should not have to click each one to learn it.
    for (const engine of engines) {
      const suffix = engine.needs_reference ? ' · needs an AA reference' : ' · reads the mapping alone';
      engineSelect.append(new Option(`${engine.label || engine.value}${suffix}`, engine.value));
    }
    if (engines.some(engine => engine.value === chosen)) engineSelect.value = chosen;
    else if (engines.length) engineSelect.value = engines[0].value;
    renderEngineNote();
    syncThreshold();
  }

  function renderEngineNote() {
    const chosen = engines.find(engine => engine.value === engineSelect.value);
    setText(engineNote, !engines.length
      ? (enginesError ? `The fitting engines could not be read: ${enginesError}` : 'Reading the fitting engines…')
      : !chosen ? 'Choose an engine.'
      : chosen.needs_reference
        ? 'This engine fits to an ensemble: it builds the mapped AA trajectory first — minutes of CPU, no MD — so it needs an AA reference.'
        : 'This engine reads the mapping alone: no AA reference and no frames.');
  }

  /** The threshold is Fast-Forward's own knob: Bartender fits its own bond terms and never reads it. */
  function syncThreshold() {
    const chosen = engines.find(engine => engine.value === engineSelect.value);
    const bartender = !!(chosen && chosen.value === 'bartender');
    threshold.disabled = bartender;
    setText(thresholdNote, bartender
      ? 'not used by Bartender: it fits its own bond terms, and the threshold applies to Fast-Forward.'
      : `default ${DEFAULT_CONSTRAINTS} kJ mol⁻¹ nm⁻² — above it a fitted pair is written as a`
        + ' constraint, below it as a spring.');
  }

  /**
   * The AA reference's own temperature, when it recorded a usable one: a fit against a 310 K ensemble is a 310 K
   * fit, so the field follows the reference rather than sitting at 300. A value the reader typed before the list
   * arrived is theirs and is kept -- the initial render only fills a field still at `DEFAULT_TEMPERATURE`, while a
   * reference the reader picks explicitly always syncs.
   */
  function syncTemperature(reference, {force = false} = {}) {
    const kelvin = Number(((reference && reference.settings) || {}).temperature_k);
    if (!Number.isFinite(kelvin) || kelvin <= 0) return;
    if (!force && temperature.value !== String(DEFAULT_TEMPERATURE)) return;
    temperature.value = String(kelvin);
  }

  function renderReferences() {
    const chosen = aaSelect.value;
    aaSelect.replaceChildren();
    if (!references.length) {
      const why = referencesError ? 'the reference list could not be read'
        : unavailableReferences.length ? `no usable AA reference — ${unavailableReferences[0].reason}`
        : 'no completed AA-only run';
      aaSelect.append(new Option(why, ''));
    } else {
      aaSelect.append(new Option('Choose an AA reference…', ''));
      for (const reference of references) {
        aaSelect.append(new Option(`${reference.label || reference.id} · ${reference.id}`, reference.id));
      }
      // One candidate is the choice: a model whose reference is the only completed AA run of its molecule
      // should not need a second click to name it. More than one stays unanswered rather than guessed.
      aaSelect.value = references.some(item => item.id === chosen)
        ? chosen : (references.length === 1 ? references[0].id : '');
    }
    // The reference this render chose without being asked (the only one) sets the temperature; one the reader had
    // already chosen keeps whatever it did when it was chosen.
    if (references.length === 1 && aaSelect.value === references[0].id) syncTemperature(references[0]);
    renderReferenceFacts();
  }

  function renderReferenceFacts() {
    const chosen = references.find(reference => reference.id === aaSelect.value);
    if (referencesError) { setText(aaFacts, `The AA reference list could not be read: ${referencesError}`); return; }
    if (!chosen) { setText(aaFacts, references.length ? 'No AA reference chosen — an engine that fits to an ensemble needs one.' : 'No completed AA-only run is available to fit against.'); return; }
    const settings = chosen.settings || {};
    const parts = [];
    if (settings.temperature_k != null) parts.push(`${settings.temperature_k} K`);
    if (settings.aa_production_ps != null) parts.push(`${number(Number(settings.aa_production_ps) / 1000)} ns of production`);
    if (chosen.frames != null) parts.push(`${number(chosen.frames)} frames`);
    const warnings = chosen.warnings || [];
    const provenance = warnings.length
      ? ` · provenance not re-checked here: ${warnings.length} source${warnings.length === 1 ? '' : 's'} not on this machine`
      : '';
    setText(aaFacts, `${chosen.id} · completed AA-only run${parts.length ? ' · ' + parts.join(' · ') : ''}${provenance}`);
  }

  function updateFit() {
    const chosen = engines.find(engine => engine.value === engineSelect.value);
    const needsReference = !!(chosen && chosen.needs_reference);
    fitButton.disabled = busy || !mapping || !chosen || (needsReference && !aaSelect.value);
    if (busy) return;
    setText(fitStatus, !mapping ? 'Choose a mapping first — a fit belongs to one saved candidate.'
      : !engines.length ? (enginesError ? `The fitting engines could not be read: ${enginesError}` : 'Reading the fitting engines…')
      : !chosen ? 'Choose an engine.'
      : needsReference && !aaSelect.value ? 'Choose an AA reference: this engine fits to its ensemble.'
      : '');
  }

  // --- the job box ------------------------------------------------------------------------------------------------

  /** How long the job has run, from its own timestamps -- a measurement, not an estimate. */
  function elapsedText(record) {
    if (!record || !record.started_at) return '';
    const start = Date.parse(record.started_at);
    const end = record.ended_at ? Date.parse(record.ended_at) : Date.now();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return '';
    const seconds = Math.round((end - start) / 1000);
    const minutes = Math.floor(seconds / 60);
    const rest = String(seconds % 60).padStart(2, '0');
    return `${record.ended_at ? 'took' : 'elapsed'} ${minutes}:${rest}`;
  }

  /** The job's four steps by name, each saying whether it is behind the run, the one running, or still to come. */
  function renderSteps() {
    if (!jobSteps) return;
    const names = job && job.steps && job.steps.length ? job.steps
      : ['mapped frames', 'fit', 'checks', 'save'];
    const done = new Set((job && job.completed_steps) || []);
    const current = job ? job.step : null;
    jobSteps.replaceChildren(...names.map(name => {
      const item = document.createElement('li');
      item.textContent = name.charAt(0).toUpperCase() + name.slice(1);
      const state = done.has(name) || (job && job.status === 'completed') ? 'done'
        : name === current && job && LIVE.has(job.status) ? 'current' : 'pending';
      item.dataset.state = state;
      item.title = state === 'current' ? `Running: ${name}` : state === 'done' ? `Finished: ${name}` : `Not started: ${name}`;
      if (state === 'current') item.setAttribute('aria-current', 'step');
      return item;
    }));
  }

  function renderJob() {
    jobBox.hidden = !job;
    if (!job) return;
    const progress = job.progress || {};
    const total = Number(progress.total ?? (job.steps || []).length) || 4;
    const done = Number(progress.done ?? 0);
    setText(jobStatus, job.status || 'queued');
    jobStatus.dataset.status = job.status || 'queued';
    setText(jobTitle, job.status === 'completed' ? `Completed — revision ${job.revision ?? 'stored'}`
      : job.status === 'failed' ? 'Failed'
      : job.status === 'cancelled' ? 'Cancelled'
      : job.status === 'running' ? `Fitting · ${done} of ${total}${job.step ? ' · ' + job.step : ''}`
      : `Queued · ${engineLabel(job.engine)}`);
    setText(jobDetail, [progress.detail || '', engineLabel(job.engine),
                        job.started_at ? `started ${clock(job.started_at)}` : '',
                        job.ended_at ? `ended ${clock(job.ended_at)}` : '',
                        elapsedText(job)].filter(Boolean).join(' · '));
    const meter = jobBar.parentElement;
    if (meter) {
      meter.setAttribute('aria-valuenow', String(done));
      meter.setAttribute('aria-valuemax', String(total));
      meter.setAttribute('aria-valuetext', job.step && LIVE.has(job.status)
        ? `${done} of ${total} · ${job.step}` : `${done} of ${total} steps`);
    }
    jobBar.style.width = `${Math.max(0, Math.min(100, Math.round((done / total) * 100)))}%`;
    renderSteps();
    // A failed job is reported as the two things it recorded: what went wrong, and the tail of its own log.
    const failure = job.status === 'failed'
      ? `The fit failed: ${job.error || 'its record carries no error'}`
      : '';
    jobError.hidden = !failure;
    setText(jobError, failure);
    const tail = String(job.log_tail || '').trim();
    jobLog.hidden = !tail;
    setText(jobLog, tail);
    const live = LIVE.has(job.status);
    cancelButton.hidden = !live;
    cancelButton.disabled = !live;
  }

  function watch(record) {
    job = record;
    jobToken += 1;
    renderJob();
    schedule(jobToken);
  }

  function schedule(token) {
    clearTimeout(timer);
    timer = null;
    if (token !== jobToken || !job || !LIVE.has(job.status)) return;
    if (!visible()) return;                       // resumed by `resume` when the reader comes back to it
    timer = setTimeout(() => poll(token), pollMilliseconds());
  }

  async function poll(token) {
    timer = null;
    if (token !== jobToken || !job || !LIVE.has(job.status)) return;
    if (!visible()) return;
    let answer;
    try {
      // By the job's own id, not the mapping's hash: the hash used to be the question, and a job whose identity had
      // moved answered nothing at all -- the box kept the record it queued and sat on `queued` with no explanation.
      answer = await api('/api/bonded-parameterizations/jobs?job_id=' + encodeURIComponent(job.id));
    } catch (error) {
      // A poll that cannot read does not invent a failure: the box keeps the state it has and asks again.
      if (token === jobToken) schedule(token);
      return;
    }
    if (token !== jobToken) return;               // superseded: this answer is about a job that was replaced
    const fresh = (answer.jobs || []).find(item => item && item.id === job.id);
    if (fresh) job = fresh;
    renderJob();
    if (!fresh || TERMINAL.has(job.status)) {
      stopPolling();
      // A fit the reader queued is shown when it lands: the new revision is what the fit produced, and leaving the
      // selector on the previous revision would show the outcome beside an older result.
      const completed = Number(job.revision);
      const finished = job.status === 'completed' && job.revision != null && Number.isInteger(completed);
      if (finished) shownRevisionNumber = completed;
      await readRecord(generation);
      // The panes are independent readers: reload the ones showing the mapping this job fitted. The card's own
      // record is the one above, already re-read.
      if (finished) onFitted({file: selectedFile, contentHash: hash(), revision: completed});
      return;
    }
    schedule(token);
  }

  function resume() {
    if (!job || !LIVE.has(job.status) || timer) return;
    schedule(jobToken);
  }
  whenLive(resume);
  document.addEventListener('dashboard:tab', resume);

  async function cancel() {
    if (!job) return;
    if (!confirm(`Cancel fit ${job.id}? A tool it is running is stopped, and no revision is stored.`)) return;
    cancelButton.disabled = true;
    const token = generation;
    try {
      const stopped = await post('/api/bonded-parameterizations/jobs/' + encodeURIComponent(job.id) + '/cancel', {});
      jobToken += 1;
      stopPolling();
      // The same rule as a fit answer: a cancellation that lands after the reader switched targets must not paint
      // the previous target's job onto this one's box.
      if (token !== generation) return;
      if (stopped && stopped.id === job.id) job = stopped;
      renderJob();
      // The record is the answer, not the route's echo of it: re-read what the job actually stored.
      await readRecord(token);
    } catch (error) {
      if (token !== generation) return;
      setText(jobDetail, `The fit was not cancelled: ${error.message}`);
      cancelButton.disabled = false;
    }
  }

  // --- the result card --------------------------------------------------------------------------------------------

  function definition(label, value) {
    const term = document.createElement('dt');
    term.textContent = label;
    const detail = document.createElement('dd');
    detail.textContent = value;
    return [term, detail];
  }

  function ensembleSentence(revision) {
    const ensemble = revision.ensemble || {};
    if (ensemble.frames === null || ensemble.frames === undefined) {
      return 'this engine read no AA frames, so there is no ensemble behind these terms';
    }
    return `${number(ensemble.frames)} mapped AA frames`
      + `${ensemble.trajectory ? ` from ${ensemble.trajectory}` : ''}`;
  }

  function checkSentence(name, report) {
    if (report === null || report === undefined) return `${name} — not run`;
    if (report.error) return `${name} — could not run: ${report.error}`;
    const rows = Array.isArray(report.rows) ? report.rows : [];
    const disagreements = Array.isArray(report.disagreements) ? report.disagreements : [];
    const frames = report.frames_measured != null ? ` over ${number(report.frames_measured)} frames` : '';
    if (name === 'dihedral-fit') {
      return `dihedral-fit — ${rows.length} declared torsion${rows.length === 1 ? '' : 's'}${frames},`
        + ` chosen by ${report.criterion || 'its criterion'}; ${disagreements.length} disagree on multiplicity`;
    }
    return `bonded-cross-check — ${rows.length} term${rows.length === 1 ? '' : 's'}${frames} against the`
      + ` equipartition estimate; ${disagreements.length} disagree on whether it is a constraint`;
  }

  /** The interaction count a revision's own `terms` states: what the result card prints as "34 terms". */
  function totalTerms(revision) {
    return Object.entries((revision && revision.terms) || {})
      .filter(([kind]) => kind !== 'virtual_sitesn')
      .reduce((total, [, count]) => total + (Number(count) || 0), 0);
  }

  function renderResult() {
    const revision = shownRevision();
    resultBox.hidden = !revision;
    provenance.replaceChildren();
    checksBox.replaceChildren();
    if (!revision) {
      setText(resultTitle, 'No revision yet');
      setText(resultSummary, '');
      return;
    }
    const isCurrent = revision.revision === currentNumber();
    setText(resultTitle, `Revision ${revision.revision} · ${isCurrent ? 'current' : 'earlier, shown'}`);
    const options = revision.options || {};
    const reference = revision.aa_reference || null;
    const transcription = revision.engine === 'martini-reference';
    setText(resultSummary, `${number(totalTerms(revision))} terms · ${engineLabel(revision.engine)}`
      + (transcription
        ? ` · seeded from the published reference${(revision.transcription || {}).entry ? ` ${revision.transcription.entry}` : ''}`
        : reference ? ` · fitted against ${reference.run_id}` : ' · fitted from the mapping alone'));
    setText(resultBadge, 'saved');
    resultBadge.dataset.status = 'completed';
    const counts = revision.terms || {};
    provenance.append(...definition('Engine', engineLabel(revision.engine)),
      ...definition('Ensemble', ensembleSentence(revision)),
      ...definition('Constraint threshold',
        `${options.constraints_threshold} kJ mol⁻¹ nm⁻² — above it a fitted pair is written as a constraint, below it as a spring`),
      ...definition('Fit temperature',
        `${options.temperature_k} K${revision.temperature_source ? ` (${revision.temperature_source})` : ''}`),
      ...definition('Torsion model', options.torsion_model === 'circular-harmonic'
        ? `circular-harmonic · stiffness scale ${options.torsion_scale}`
        : 'legacy — the periodic fit as recorded'),
      ...definition('AA reference', transcription
        ? (reference
          ? `${reference.run_id} · inherited for a run's source; these terms were not fitted against it`
          : 'none — a CG run cannot pin its source until this mapping is fitted')
        : reference
          ? [reference.run_id, reference.temperature_k != null ? `${reference.temperature_k} K` : '',
             reference.production_ns != null ? `${reference.production_ns} ns` : ''].filter(Boolean).join(' · ')
          : 'none — this engine read the mapping alone'),
      ...definition('Terms', Object.entries(counts).length
        ? Object.entries(counts).filter(([kind]) => kind !== 'virtual_sitesn')
            .map(([kind, count]) => `${count} ${kind}`).join(' · ')
        : 'none recorded'),
      // The summary carries the current revision's hash only: printing it beside an earlier revision would name a
      // different record, so the row is a statement about what the answer holds rather than a claim about this one.
      ...definition('Revision hash', isCurrent
        ? ((summary && summary.revision_sha256 || '').slice(0, 12) || 'not recorded')
        : 'not carried for an earlier revision'),
      ...definition('Fitted', date(revision.created_at) || 'not recorded'));
    const heading = document.createElement('strong');
    heading.textContent = 'Checks recorded with this revision';
    const note = document.createElement('p');
    note.className = 'hint';
    note.textContent = 'Re-derivations recorded with the terms. A check that could not run is recorded with its'
      + ' reason and is not a failed fit; a hand-edited or transcribed revision carries none.';
    const list = document.createElement('ul');
    list.className = 'bonded-checks-list';
    const checks = revision.checks || {};
    for (const name of CHECK_NAMES) {
      const item = document.createElement('li');
      item.textContent = checkSentence(name, checks[name]);
      list.append(item);
    }
    checksBox.append(heading, note, list);
  }

  // --- reading the record, and fitting ----------------------------------------------------------------------------

  async function readEngines() {
    try {
      const answer = await api('/api/bonded-parameterizations/engines');
      engines = (answer && answer.engines) || [];
      enginesError = '';
    } catch (error) {
      engines = [];
      enginesError = error.message;
    }
    renderEngines();
    updateFit();
  }

  async function readReferences(targetMolecule, token) {
    const query = targetMolecule ? '?molecule_id=' + encodeURIComponent(targetMolecule) : '';
    try {
      const answer = await cachedApi('/api/references' + query, {maxAge: 10000});
      if (token !== generation) return;
      references = (answer && answer.references) || [];
      unavailableReferences = (answer && answer.unavailable) || [];
      referencesError = '';
    } catch (error) {
      if (token !== generation) return;
      references = [];
      unavailableReferences = [];
      referencesError = error.message;
    }
    renderReferences();
    updateFit();
  }

  async function readRecord(token) {
    if (!mapping) return;
    const params = new URLSearchParams();
    if (mapping.mapping_content_hash) params.set('content_hash', mapping.mapping_content_hash);
    if (mapping.mapping_hash) params.set('mapping_hash', mapping.mapping_hash);
    let answer;
    try {
      answer = await api('/api/bonded-parameterizations?' + params);
    } catch (error) {
      if (token !== generation) return;
      setText(jobDetail, `This model’s parameterization could not be read: ${error.message}`);
      return;
    }
    if (token !== generation) return;
    summary = (answer && answer.summary) || null;
    revisions = (answer && answer.revisions) || [];
    if (shownRevisionNumber === null || !revisions.some(item => item.revision === shownRevisionNumber)) {
      shownRevisionNumber = currentNumber();
    }
    renderResult();
    updateFit();
    // A job the previous page left live is adopted rather than forgotten; a finished one stays on screen because
    // it is the record of how the revision above was made.
    const newest = ((answer && answer.jobs) || [])[0];
    if (newest && (!job || job.id !== newest.id)) watch(newest);
  }

  function readOptions() {
    const values = {
      constraints_threshold: Number(threshold.value),
      temperature_k: Number(temperature.value),
      torsion_model: chosenTorsion().torsion_model,
    };
    if (!Number.isFinite(values.constraints_threshold) || values.constraints_threshold <= 0) {
      setText(fitStatus, 'The constraint threshold must be a positive number of kJ mol⁻¹ nm⁻².');
      return null;
    }
    if (!Number.isFinite(values.temperature_k) || values.temperature_k <= 0) {
      setText(fitStatus, 'The fit temperature must be a positive number of kelvin.');
      return null;
    }
    // The scale travels only with the model that uses it: the store's own validator refuses a scale under
    // `legacy`, so sending one would be a request the route answers 400 to.
    if (values.torsion_model === 'circular-harmonic') {
      const scale = Number(torsionScale.value);
      if (!Number.isFinite(scale) || scale < 0.1 || scale > 3) {
        setText(fitStatus, 'The torsion stiffness scale must be between 0.1 and 3.');
        return null;
      }
      values.torsion_scale = scale;
    }
    return values;
  }

  async function fit(engine) {
    if (!mapping) return setText(fitStatus, 'Choose a mapping first — a fit belongs to one saved candidate.');
    const options = readOptions();
    if (!options) return;
    const chosen = engines.find(item => item.value === engine);
    if (!chosen) return setText(fitStatus, 'Choose an engine first.');
    const body = {mapping, engine: chosen.value, options};
    if (chosen.needs_reference) {
      if (!aaSelect.value) return setText(fitStatus, 'Choose an AA reference: this engine fits to its ensemble.');
      body.aa_reference = aaSelect.value;
    }
    busy = true;
    updateFit();
    setText(fitStatus, `Queueing a ${chosen.label || chosen.value} fit of ${mapping.name || mapping.file}…`);
    const token = generation;
    try {
      const started = await post('/api/bonded-parameterizations', body);
      busy = false;
      // A queue answer that arrives after the reader moved on is about a target that is no longer on screen: dropping
      // it keeps this target's card, job box and poll its own. `updateFit` still restates the *current* panel's hint,
      // because `busy` was set here and only this answer clears it.
      if (token !== generation) { updateFit(); return; }
      setText(fitStatus, '');
      watch(started);
      updateFit();
    } catch (error) {
      busy = false;
      if (token !== generation) { updateFit(); return; }
      // `updateFit` first: it restates the panel's own hint, so an error written before it would be erased.
      updateFit();
      setText(fitStatus, `The fit was not queued: ${error.message}`);
    }
  }

  // --- wiring -----------------------------------------------------------------------------------------------------

  engineSelect.onchange = () => { renderEngineNote(); syncThreshold(); updateFit(); };
  aaSelect.onchange = () => {
    syncTemperature(references.find(reference => reference.id === aaSelect.value), {force: true});
    renderReferenceFacts();
    updateFit();
  };
  torsionModel.onchange = () => updateTorsion();
  torsionScale.oninput = () => updateTorsion();
  torsionSave.onclick = () => saveTorsion();
  fitButton.onclick = () => fit(engineSelect.value);
  cancelButton.onclick = () => cancel();
  moleculeSelect.onchange = () => { fillMappings(moleculeSelect.value).catch(error => setText(fitStatus, error.message)); };
  mappingSelect.onchange = () => { loadTarget(mappingSelect.value).catch(error => setText(fitStatus, error.message)); };

  async function mount() {
    updateFit();
    fillTorsion();
    updateTorsion();
    await readEngines();
    await fillMolecules();
    if (moleculeSelect.value) await fillMappings(moleculeSelect.value);
  }

  /** Re-read the fit target's record after another pane saved, made current or deleted it. */
  async function refresh(change = {}) {
    if (!mapping) return;
    const file = change?.file || '';
    const content = change?.contentHash || '';
    if (!((file && file === selectedFile) || (content && content === hash()))) return;
    // A pane's write is an external change to this record: follow the revision it made current, rather than pinning
    // the card to a revision the write may have just demoted to "earlier".
    shownRevisionNumber = null;
    await readRecord(generation);
  }

  /** Whether a fit of this mapping is in flight: deleting the parameterization under it would race the job. */
  function isFitting(file) {
    if (!file) return busy || !!(job && LIVE.has(job.status));
    return (busy || !!(job && LIVE.has(job.status)))
      && (file === selectedFile || file === hash());
  }

  return {mount, isFitting, refresh};
}
