/**
 * The parameterization half of CG Bond Interactions: the model card, the fit job, its result, and the
 * mapping's revision strip.
 *
 * A **parameterization** is a mapping's bonded terms together with the provenance of those terms, and it is
 * produced by a job of this panel's own. It makes no MD, so nothing here becomes a run: a run consumes the
 * revision this panel makes current and records which. The design is
 * `docs/design/2026-10-16-parameterization-and-new-run.md`, and the layout is the draft the owner approved,
 * `docs/design/prototypes/parameterization-and-new-run.html`.
 *
 * Every reading is taken from the routes and none is reconstructed here:
 *
 *   GET    /api/bonded-parameterizations/engines                      -> {engines: [{value, label, needs_reference}]}
 *   GET    /api/bonded-parameterizations?content_hash=&mapping_hash=  -> {summary, revisions, jobs}
 *   GET    /api/bonded-parameterizations/jobs?job_id=                 -> {jobs}   (polled while live)
 *   GET    /api/bonded-parameterizations/jobs?content_hash=           -> {jobs}   (a mapping's whole job history)
 *   POST   /api/bonded-parameterizations                              -> the job record
 *   POST   /api/bonded-parameterizations/jobs/<id>/cancel             -> the job record
 *   PATCH  /api/bonded-parameterizations/<content_hash>               -> the record
 *
 * Three rules this module exists to keep:
 *
 * 1. **A superseded answer never reaches the screen.** Every job the panel watches gets a generation token
 *    (`jobToken`), the token is re-checked after every await, and a mapping switch bumps it -- the same
 *    arrangement `run-view-monitor.js` uses for a superseded load. A poll that belongs to a job the reader has
 *    replaced is dropped, not painted. The two answers this module awaits itself -- queueing a fit, cancelling one
 *    -- are checked against `generation` for the same reason: their bodies belong to the model the reader has since
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
import { $, api, cachedApi, post, setText } from './shared.js';

/** Fast_Forward's own `-constraints` default, and this repository's convention. Stated so the field can show it. */
export const DEFAULT_CONSTRAINTS = 10000;
export const DEFAULT_TEMPERATURE = 300;
/** The cadence the job box polls at while a fit is queued or running: every few seconds, not every second. */
export const POLL_MS = 3000;

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
function termsOf(revision, mapping) {
  if (!revision || !revision.topology) return [];
  const declared = new Map();
  for (const row of revision.sources || []) if (row && row.id) declared.set(row.id, row.source);
  return parseTopology(revision.topology).map(row => ({
    ...row,
    editable: false,
    source: declared.get(row.id) || 'unrecorded',
  }));
}

export function setupParameterization({host, onTerms}) {
  const aaSelect = $('#bonded-aa-reference', host);
  const aaFacts = $('#bonded-aa-facts', host);
  const engineSelect = $('#bonded-engine', host);
  const engineNote = $('#bonded-engine-note', host);
  const mappingFacts = $('#bonded-mapping-facts', host);
  const modelSummary = $('#bonded-model-summary', host);
  const modelBadge = $('#bonded-model-badge', host);
  const threshold = $('#bonded-constraints-threshold', host);
  const thresholdNote = $('#bonded-constraints-note', host);
  const temperature = $('#bonded-temperature', host);
  const torsionModel = $('#bonded-torsion-model', host);
  const torsionScale = $('#bonded-torsion-scale', host);
  const torsionStatus = $('#bonded-torsion-status', host);
  const torsionSave = $('#bonded-save-torsion', host);
  const fitButton = $('#bonded-fit', host);
  const fitStatus = $('#bonded-fit-status', host);
  const jobBox = $('#bonded-job', host);
  const jobTitle = $('#bonded-job-title', host);
  const jobDetail = $('#bonded-job-detail', host);
  const jobStatus = $('#bonded-job-status', host);
  const jobBar = $('#bonded-job-bar', host);
  const jobSteps = $('#bonded-job-steps', host);
  const jobError = $('#bonded-job-error', host);
  const jobLog = $('#bonded-job-log', host);
  const cancelButton = $('#bonded-job-cancel', host);
  const resultBox = $('#bonded-result', host);
  const resultTitle = $('#bonded-result-title', host);
  const resultSummary = $('#bonded-result-summary', host);
  const resultBadge = $('#bonded-result-badge', host);
  const provenance = $('#bonded-result-provenance', host);
  const checksBox = $('#bonded-result-checks', host);
  const strip = $('#bonded-revisions', host);

  let mapping = null;
  let summary = null;
  let revisions = [];
  let engines = [];
  let enginesError = '';
  let references = [];
  let referencesError = '';
  let job = null;
  let busy = false;
  let generation = 0;
  let jobToken = 0;
  let timer = null;

  // --- readings ---------------------------------------------------------------------------------------------------

  const hash = () => (mapping && mapping.mapping_content_hash) || '';
  const currentNumber = () => (summary && summary.revision) ?? null;
  const currentRevision = () => revisions.find(item => item && item.revision === currentNumber()) || null;
  const engineLabel = value => (engines.find(item => item.value === value) || {}).label || value || 'fit';
  const pollMilliseconds = () => Number(window.__bondedPollMs) || POLL_MS;
  const visible = () => {
    const panel = host.closest('.panel') || host;
    return !panel.hidden && !document.hidden;
  };
  const date = iso => (typeof iso === 'string' ? iso.slice(0, 10) : '');
  const clock = iso => (typeof iso === 'string' ? iso.slice(11, 19) : '');

  function stopPolling() { clearTimeout(timer); timer = null; }

  // --- the model card ---------------------------------------------------------------------------------------------

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
    updateTorsion();
  }

  function fillOptions(fresh) {
    fillTorsion();
    // The threshold's unit and its default are stated where the field is: the value decides whether a fitted pair
    // becomes a constraint or a spring, so "10000" without them is a number about nothing.
    setText(thresholdNote, `default ${DEFAULT_CONSTRAINTS} kJ mol⁻¹ nm⁻² — above it a fitted pair is written as a`
      + ' constraint, below it as a spring.');
    if (!fresh) return;
    threshold.value = String(DEFAULT_CONSTRAINTS);
    temperature.value = String(DEFAULT_TEMPERATURE);
  }

  function renderModel() {
    const beads = (mapping && mapping.beads) || [];
    const physical = beads.filter(bead => !bead.virtual_site).length;
    setText(mappingFacts, mapping
      ? `${beads.length} beads · ${physical} physical · ${beads.length - physical} virtual sites`
        + `${(mapping.rings || []).length ? ` · ${(mapping.rings || []).length} rings` : ''}`
      : '');
    setText(modelSummary, !mapping
      ? 'Choose a mapping to read its revisions.'
      : !revisions.length
        ? 'No parameterization yet: a fit made here is stored as this mapping’s revision 1.'
        : `Revision ${currentNumber()} of ${revisions.length} is current; ${revisions.length - 1} earlier`
          + ` ${revisions.length === 2 ? 'revision is' : 'revisions are'} kept.`);
    setText(modelBadge, !mapping ? 'no mapping' : revisions.length ? `revision ${currentNumber()} · current` : 'no parameterization');
    if (revisions.length) modelBadge.dataset.status = 'completed';
    else delete modelBadge.dataset.status;
  }

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
  }

  function renderEngineNote() {
    const chosen = engines.find(engine => engine.value === engineSelect.value);
    // Every published engine reads an ensemble, so the note is one sentence; `needs_reference` is still read from the
    // route rather than assumed, because that is what decides whether the picker below is required.
    setText(engineNote, !engines.length
      ? (enginesError ? `The fitting engines could not be read: ${enginesError}` : 'Reading the fitting engines…')
      : !chosen ? 'Choose an engine.'
      : chosen.needs_reference
        ? 'This engine fits to an ensemble: it builds the mapped AA trajectory first — minutes of CPU, no MD — so it needs an AA reference.'
        : 'This engine reads the mapping alone: no AA reference and no frames.');
  }

  function renderReferences() {
    const chosen = aaSelect.value;
    aaSelect.replaceChildren();
    if (!references.length) {
      aaSelect.append(new Option(referencesError ? 'the reference list could not be read' : 'no completed AA-only run', ''));
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
    setText(aaFacts, `${chosen.id} · completed AA-only run${parts.length ? ' · ' + parts.join(' · ') : ''}`);
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

  /** How long the job has run, from its own timestamps -- a measurement, not an estimate.
   *
   * Recomputed on every poll, which is a few seconds apart: live enough for a step that lasts minutes, and it needs
   * no timer of its own. `took` once the record carries an end, `elapsed` while it does not.
   */
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

  /** The job's four steps by name, each saying whether it is behind the run, the one running, or still to come.
   *
   * The names come from the record's own `steps`, so this cannot list a step the job does not run; only the label's
   * capitalisation is the panel's. A completed job marks every step done, and a cancelled or failed one keeps the
   * steps it finished and the step it stopped in, which is what a reader diagnosing it needs to see.
   */
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
      // A bar that is a quarter full says nothing on its own; the step it is inside is the answer to "is it moving".
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
    if (!fresh || TERMINAL.has(job.status)) { stopPolling(); await readRecord(generation); return; }
    schedule(token);
  }

  function resume() {
    if (!job || !LIVE.has(job.status) || timer) return;
    schedule(jobToken);
  }
  document.addEventListener('visibilitychange', resume);
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
      // The same rule as a fit answer: a cancellation that lands after the reader switched models must not paint
      // the previous model's job onto this one's box.
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

  // --- the result card and the strip ------------------------------------------------------------------------------

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
    // The report's `disagreements` are the rows where the two verdicts differ, and it does not say which way:
    // naming a direction here would be a claim the check did not make.
    return `bonded-cross-check — ${rows.length} term${rows.length === 1 ? '' : 's'}${frames} against the`
      + ` equipartition estimate; ${disagreements.length} disagree on whether it is a constraint`;
  }

  function renderResult() {
    const revision = currentRevision();
    resultBox.hidden = !revision;
    provenance.replaceChildren();
    checksBox.replaceChildren();
    if (!revision) {
      setText(resultTitle, 'No revision yet');
      setText(resultSummary, '');
      return;
    }
    setText(resultTitle, `Revision ${revision.revision} · current`);
    const options = revision.options || {};
    const reference = revision.aa_reference || null;
    setText(resultSummary, `${number((summary && summary.terms) ?? 0)} terms · ${engineLabel(revision.engine)}`
      + `${reference ? ` · fitted against ${reference.run_id}` : ' · fitted from the mapping alone'}`);
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
      ...definition('AA reference', reference
        ? [reference.run_id, reference.temperature_k != null ? `${reference.temperature_k} K` : '',
           reference.production_ns != null ? `${reference.production_ns} ns` : ''].filter(Boolean).join(' · ')
        : 'none — this engine read the mapping alone'),
      ...definition('Terms', Object.entries(counts).length
        ? Object.entries(counts).filter(([kind]) => kind !== 'virtual_sitesn')
            .map(([kind, count]) => `${count} ${kind}`).join(' · ')
        : 'none recorded'),
      ...definition('Revision hash', (summary && summary.revision_sha256 || '').slice(0, 12) || 'not recorded'),
      ...definition('Fitted', date(revision.created_at) || 'not recorded'));
    const heading = document.createElement('strong');
    heading.textContent = 'Checks on this fit';
    const note = document.createElement('p');
    note.className = 'hint';
    note.textContent = 'Re-derivations of the terms beside them, run as part of this fit. A check that could not run'
      + ' is recorded with its reason and is not a failed fit.';
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

  function renderStrip() {
    strip.replaceChildren();
    if (!revisions.length) {
      const empty = document.createElement('li');
      empty.className = 'hint';
      empty.textContent = mapping
        ? 'This mapping has no revisions yet. A fit stores the first one.'
        : 'Choose a mapping to read its revisions.';
      strip.append(empty);
      return;
    }
    for (const revision of revisions) {
      const item = document.createElement('li');
      item.className = 'bonded-revision';
      item.dataset.revision = String(revision.revision);
      const isCurrent = revision.revision === currentNumber();
      item.dataset.current = String(isCurrent);
      if (isCurrent) item.setAttribute('aria-current', 'true');
      const number_ = document.createElement('span');
      number_.className = 'bonded-revision-number';
      number_.textContent = `r${revision.revision}`;
      const engine = document.createElement('span');
      engine.className = 'bonded-revision-engine';
      engine.textContent = engineLabel(revision.engine);
      const when = document.createElement('span');
      when.className = 'bonded-revision-date';
      when.textContent = date(revision.created_at) || 'no date recorded';
      const action = document.createElement('button');
      action.type = 'button';
      action.className = 'secondary bonded-make-current';
      action.dataset.revision = String(revision.revision);
      action.textContent = isCurrent ? 'current' : 'Make current';
      action.disabled = isCurrent;
      if (isCurrent) action.title = 'This revision is already current.';
      else action.onclick = () => makeCurrent(revision.revision);
      item.append(number_, engine, when, action);
      strip.append(item);
    }
  }

  async function makeCurrent(revision) {
    if (!mapping || revision === currentNumber()) return;
    if (!confirm(`Make revision ${revision} current for this mapping? A run queued after this consumes it;`
                 + ' runs already queued keep the revision they recorded.')) return;
    const token = generation;
    try {
      await api('/api/bonded-parameterizations/' + encodeURIComponent(hash()), {
        method: 'PATCH', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({current: revision, confirm: true}),
      });
      // `readRecord` drops a superseded answer; the sentence after it must be dropped with it.
      await readRecord(token);
      if (token === generation) setText(fitStatus, `Revision ${revision} is current.`);
    } catch (error) {
      if (token === generation) setText(fitStatus, `Revision ${revision} was not made current: ${error.message}`);
    }
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

  async function readReferences(token) {
    const query = mapping && mapping.molecule_id
      ? '?molecule_id=' + encodeURIComponent(mapping.molecule_id) : '';
    try {
      const answer = await cachedApi('/api/references' + query, {maxAge: 10000});
      if (token !== generation) return;
      references = (answer && answer.references) || [];
      referencesError = '';
    } catch (error) {
      if (token !== generation) return;
      references = [];
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
      setText(fitStatus, `This model’s parameterization could not be read: ${error.message}`);
      return;
    }
    if (token !== generation) return;
    summary = (answer && answer.summary) || null;
    revisions = (answer && answer.revisions) || [];
    renderModel();
    renderResult();
    renderStrip();
    updateFit();
    // `null` when the record carries no revision: the table then shows the mapping's own draft and says so,
    // where an empty list would read as a revision whose terms had all been removed.
    onTerms(currentRevision() ? termsOf(currentRevision(), mapping) : null);
    // A job the previous page left live is adopted rather than forgotten; a finished one stays on screen because
    // it is the record of how the revision above was made.
    const newest = ((answer && answer.jobs) || [])[0];
    if (newest && (!job || job.id !== newest.id)) watch(newest);
  }

  async function load(next) {
    const token = ++generation;
    stopPolling();
    jobToken += 1;
    const fresh = !mapping || !next
      || mapping.mapping_content_hash !== next.mapping_content_hash;
    mapping = next || null;
    summary = null;
    revisions = [];
    // A reference belongs to one molecule's AA runs, so another mapping's list must not survive the switch: the
    // request below is scoped to this mapping's molecule, and an old option could name a run of a different one.
    if (fresh) { references = []; referencesError = ''; }
    job = null;
    jobBox.hidden = true;
    resultBox.hidden = true;
    fillOptions(fresh);
    renderModel();
    renderResult();
    renderStrip();
    renderJob();
    onTerms(null);
    if (!mapping) {
      aaSelect.replaceChildren(new Option('Choose a mapping first', ''));
      setText(aaFacts, '');
      updateFit();
      return;
    }
    renderReferences();
    await Promise.all([readReferences(token), readRecord(token)]);
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
      // A queue answer that arrives after the reader moved on is about a model that is no longer on screen: dropping
      // it keeps this model's card, job box and poll its own. `updateFit` still restates the *current* panel's hint,
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

  engineSelect.onchange = () => { renderEngineNote(); updateFit(); };
  aaSelect.onchange = () => { renderReferenceFacts(); updateFit(); };
  torsionModel.onchange = () => updateTorsion();
  torsionScale.oninput = () => updateTorsion();
  fitButton.onclick = () => fit(engineSelect.value);
  cancelButton.onclick = () => cancel();
  torsionSave.onclick = () => saveTorsion();

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
      setText($('.bonded-panel-message', host), `Torsion model saved to ${saved.file}: runs queued from it refine this way.`);
    } catch (error) {
      setText($('.bonded-panel-message', host), error.message);
      updateTorsion();
    }
  }

  async function mount() {
    // Before the first mapping: with no engine read yet the Fit button says so and stays inert, rather than
    // offering a value the job would refuse.
    updateFit();
    await readEngines();
  }

  /** How many revisions this mapping holds: what a caller must say before deleting the mapping takes them. */
  function revisionCount() { return revisions.length; }

  /** Whether a fit of this mapping is in flight: deleting the mapping under it would leave the job writing to it. */
  function isBusy() { return busy || (job !== null && LIVE.has(job.status)); }

  return {mount, load, revisionCount, isBusy};
}
