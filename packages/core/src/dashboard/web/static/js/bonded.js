/**
 * CG Bond Interactions: the model being described, its picture, and the terms of the parameterization that is shown.
 *
 * The panel has two halves. This module owns the molecule selector, the one parameterization selector, the bead
 * geometry and the interactions table; `bonded-parameterization.js` owns the model card's state (which revision is
 * shown, and which is current), the fit job, the result and the revision strip, and hands its terms here through
 * `onTerms`. The split is the design's own: what is *read* about a model (`/api/bonded-parameterizations`) is a
 * different question from how its beads are drawn.
 *
 * The selector is display-only. Its options are the chosen molecule's saved mappings grouped by mapping -- each
 * mapping's revisions, or its draft connectivity when it has none -- plus the published reference when the route
 * offers one. Choosing an option reads that mapping's parameterization and shows the chosen revision; it never
 * changes the revision a run consumes, which is the separate **Make current** action.
 *
 * The table is read-only, and that is a recorded decision rather than an oversight: no route in this slice writes a
 * revision's terms, so a parameter input here would be a control that cannot act — the failure this repository's
 * panels are not allowed to have. `docs/design/2026-10-16-parameterization-and-new-run.md` D7 records it, with the
 * route that would restore the old manual editor. The `source` column is what a reader needs instead — it says
 * which engine fitted each term, or that the mapping (a ring constraint, a virtual site), a hand edit recorded
 * elsewhere, or a geometry fallback produced it. Two kinds are not a draft at all and are marked as the reading they
 * are: a constraint's length and a virtual site's parents come from the mapping.
 */
import { $, setText, cachedApi, api, invalidateResource, CATALOGUE_MAX_AGE } from './shared.js';
import { mountBondedPlot } from './bonded-plot.js';
import { setupParameterization, parseTopology } from './bonded-parameterization.js';

const FUNCTION_OPTIONS = {
  bonds: {1: {description: 'Harmonic', labels: ['length (nm)', 'force (kJ mol^-1 nm^-2)']}},
  angles: {
    1: {description: 'Harmonic', labels: ['angle (deg)', 'force (kJ mol^-1 rad^-2)']},
    2: {description: 'GROMOS-96 cosine', labels: ['angle (deg)', 'force (kJ mol^-1)']},
    10: {description: 'Restricted bending', labels: ['angle (deg)', 'force (kJ mol^-1)']},
  },
  dihedrals: {
    1: {description: 'Proper periodic', labels: ['phase (deg)', 'force (kJ mol^-1)', 'multiplicity']},
    2: {description: 'Improper harmonic', labels: ['phase (deg)', 'force (kJ mol^-1 rad^-2)']},
    9: {description: 'Proper periodic multi-term', labels: ['phase (deg)', 'force (kJ mol^-1)', 'multiplicity']},
  },
};

/** The molecule select's group for CG compositions: not a molecule, so it cannot come from `/api/molecules`. */
const COMPOSITIONS = '__compositions__';

const formatNumber = value => Number.isFinite(Number(value)) ? Number(value).toString() : '';
const date = iso => (typeof iso === 'string' ? iso.slice(0, 10) : '');

/** A display option's value: a revision of a saved mapping, or a model that carries no revision. */
function optionValue(file, revision) {
  return revision === null || revision === undefined ? `draft:${file}` : `revision:${file}:${revision}`;
}

/** The mapping file and the revision (or `null`) an option value names. */
function optionTarget(value) {
  const text = String(value || '');
  if (text.startsWith('revision:')) {
    const rest = text.slice('revision:'.length);
    const cut = rest.lastIndexOf(':');
    const revision = Number(rest.slice(cut + 1));
    return {file: rest.slice(0, cut), revision: Number.isInteger(revision) ? revision : null};
  }
  return {file: text.startsWith('draft:') ? text.slice('draft:'.length) : text, revision: null};
}

function optionsFor(kind) {
  return Object.entries(FUNCTION_OPTIONS[kind] || {}).map(([value, spec]) => ({
    value, label: `Function ${value}`, description: spec.description, labels: spec.labels,
  }));
}

function normalizeTerm(term, fallbackId) {
  const kind = term.kind || 'bonds';
  const functionValue = String(term.function || '1');
  const options = term.function_options?.length ? term.function_options.map(option => ({
    value: String(option.value), label: option.label, description: option.description || '', labels: option.parameter_labels || [],
  })) : optionsFor(kind);
  const selected = options.find(option => option.value === functionValue) || options[0];
  return {...term, id: term.id || fallbackId, kind, beads: [...(term.beads || [])],
    function: functionValue, parameters: [...(term.parameters || [])],
    editable: term.editable ?? false, function_options: options, source: term.source || 'unrecorded',
    parameter_labels: term.parameter_labels?.length ? [...term.parameter_labels] : [...(selected?.labels || [])]};
}

/** `Function 10 — Restricted bending`, or the section's own answer where it has no potential. */
function functionSentence(term) {
  const spec = FUNCTION_OPTIONS[term.kind]?.[term.function];
  if (spec) return `${term.function} — ${spec.description}`;
  if (term.kind === 'constraints') return '1 — rigid constraint, no potential';
  if (term.kind === 'virtual_sitesn') return `${term.function} — virtual site`;
  return term.function || '—';
}

/** The parameters in their own units, taken from the function's label list where it has one. */
function parameterSentence(term) {
  if (term.kind === 'virtual_sitesn') {
    return (term.parents || []).length ? `parents ${term.parents.join(' · ')}` : 'no parents recorded';
  }
  const labels = term.parameter_labels || [];
  if (!term.parameters.length) return '—';
  const parts = term.parameters.map((value, index) => {
    if (term.kind === 'constraints' && index === 0) return `${value} nm`;
    return labels[index] ? `${value} ${labels[index].replace(/^.*\((.*)\)$/, '$1')}` : String(value);
  });
  return parts.join(' · ');
}

export function setupBondedWorkspace(mappingData, {loadMapping}) {
  const host = $('.bonded-workspace');
  if (!host || !mappingData) return;
  const moleculeSelect = $('#bonded-molecule-select', host);
  const displaySelect = $('#bonded-parameterization-display', host);
  //: The hidden bridge the New run door drives: `new-run.js` preselects a saved mapping by setting its value and
  //: dispatching `change`. The visible selector is `displaySelect`; this element carries no state of its own.
  //: ponytail: kept because `new-run.js` and three test modules outside this lane address it; delete it with them.
  const bridgeSelect = $('#bonded-mapping-select', host);
  const deleteButton = $('#bonded-delete-parameterization', host);
  const message = $('.bonded-panel-message', host);
  const modelCard = $('.bonded-model', host);
  const tableHost = $('.bonded-interaction-table', host);
  const selectionStatus = $('.bonded-selection-status', host);
  const plot = mountBondedPlot($('.bonded-plot', host), {
    onBeadSelection: selected => { selectedBeads = selected; renderState(); },
    onTermSelection: id => { selectedTermId = id; renderState(); },
    onPlotError: notice,
  });
  let selectedMapping = null;
  let candidates = [];
  let reference = null;
  //: Each saved mapping's own parameterization record, read to label its options: the display selector has to name
  //: every mapping's revisions, not only the shown mapping's.
  let modelRecords = new Map();
  let structure = null;
  let geometryNotice = '';
  let terms = [];
  let selectedBeads = [];
  let selectedTermId = '';
  let generation = 0;
  let optionsGeneration = 0;

  const parameterization = setupParameterization({
    host,
    onTerms: revisionTerms => {
      // `null` is the mapping's own draft: a model with no revision still shows the connectivity its mapping
      // declares, and every row of it says where it came from rather than being presented as a fitted term.
      // A published reference is different in kind: its terms are the ITP it transcribed, marked as that reading.
      // A draft's distances are measured from the molecule's atoms, so without them there is no honest row.
      terms = selectedMapping?.read_only ? referenceTerms(selectedMapping)
        : revisionTerms ?? (structure ? mappingTerms(selectedMapping || {}) : []);
      renderState();
    },
    // A record the model card re-read (a fit finished, a revision became current, a parameterization was deleted)
    // relabels the selector's options: they state which revision is current, and a new one must appear there.
    onRecord: record => {
      if (record?.mapping?.file) modelRecords.set(record.mapping.file, record);
      fillDisplay();
      syncDisplay();
      fillBridge();
    },
  });

  function notice(text) { setText(message, text); }

  /** Whether the shown model is a saved mapping whose parameterization this panel may delete.
   *
   * The catalogue also lists CG compositions, addressed as `composition:<id>` rather than by a draft file name, and a
   * molecule's published reference, addressed as `reference:<molecule>`. Neither carries a parameterization, and
   * offering the button for one would be a control that cannot act.
   */
  function deletable() {
    return !!(selectedMapping && !selectedMapping.read_only
      && !String(selectedMapping.file || '').startsWith('composition:'));
  }

  function updateDelete() {
    if (!deleteButton) return;
    const file = selectedMapping?.file || '';
    const held = parameterization.revisionCount();
    const allowed = deletable() && held > 0;
    deleteButton.disabled = !allowed;
    deleteButton.title = selectedMapping?.read_only
      ? 'The published reference carries no parameterization to delete.'
      : file.startsWith('composition:')
        ? 'A CG composition carries no parameterization to delete.'
        : !deletable() ? 'Choose a saved mapping first.'
        : held ? `Delete the parameterization of ${file}: ${held === 1 ? 'its single revision' : `its ${held} revisions`}`
        : 'This model has no parameterization to delete.';
  }

  /** Delete the selected model's parameterization, and say what went with it.
   *
   * The saved mapping is not this control's to delete: the panel reads models and the editor owns the catalogue, so
   * what goes is what this panel is about -- the revisions, the fits that produced them, the frames those fits built
   * and the reference histograms recorded with them. The warning says exactly that, because the reader's only
   * protection before an irreversible click is the truth about what the click removes. Runs that already recorded a
   * revision keep their own copy, which is what makes it safe to offer here at all.
   */
  async function deleteParameterization() {
    const file = selectedMapping?.file || '';
    if (!deletable()) return notice('No saved mapping is selected.');
    const count = parameterization.revisionCount();
    if (!count) return notice('This model has no parameterization to delete.');
    if (parameterization.isBusy()) {
      return notice('A fit of this model is running: cancel it before deleting the parameterization.');
    }
    const hash = parameterization.contentHash();
    if (!hash) return notice('This model has no parameterization to delete.');
    // The revision *number*, not the revision: the route compares it against the record it is about to remove.
    const current = parameterization.currentRevisionNumber();
    const holds = count === 1 ? 'Its single bond interaction revision goes with it'
      : `Its ${count} bond interaction revisions go with it`;
    const agreed = window.confirm(
      `Delete the parameterization of ${file}?\n\n${holds}, along with the fit jobs and staged frames built for `
      + 'them, and the reference histograms they recorded. The saved mapping itself is not touched.\n\n'
      + 'Runs that already recorded these terms keep their own copy.');
    if (!agreed) return;
    let answer;
    try {
      answer = await api('/api/bonded-parameterizations/' + encodeURIComponent(hash), {
        method: 'DELETE', headers: {'Content-Type': 'application/json'},
        // The revision the panel was showing: a record that moved on since answers 409 instead of losing newer work.
        body: JSON.stringify({confirm: true, revision: current}),
      });
    } catch (error) {
      return notice(`The parameterization was not deleted: ${error.message}`);
    }
    const removed = (answer && answer.revisions) || [];
    const jobs = (answer && answer.jobs) || [];
    const fate = removed.length
      ? `${removed.length === 1 ? 'its single bond interaction revision' : `its ${removed.length} bond interaction revisions`} went`
      : 'it held no revisions';
    const built = jobs.length ? ` and ${jobs.length === 1 ? 'the fit that built it' : `the ${jobs.length} fits that built them`}` : '';
    // The catalogue is untouched, so neither it nor the selection is re-read: only this model's own record changed.
    invalidateResource('/api/bonded-parameterizations');
    // Stated before the reload, so a panel that fails to re-read still tells the reader what happened.
    notice(`Parameterization deleted: ${fate}${built}. The saved mapping ${file} is untouched.`);
    updateDelete();
    try {
      await parameterization.load(selectedMapping);
    } catch (error) {
      notice(`Parameterization deleted: ${fate}${built}. The saved mapping ${file} is untouched. `
        + `The panel could not be re-read: ${error.message}`);
    }
  }

  async function resolveStructure(mapping) {
    // A candidate names the molecule it maps, and the panel must draw *that* molecule. Reading one structure for
    // every candidate drew sucrose's beads on DDM's atoms, because the same atom id is a different atom in another
    // molecule -- a candidate that maps 23 atoms cannot be measured against an 81-atom reference.
    //
    // There is no fallback: a model with no molecule, a context route that fails, or a context answer with no atoms
    // means the diagram is not drawn. Substituting the packaged molecule would draw another molecule's atoms and
    // bonds under this model's bead names -- the wrong picture presented as this one.
    if (mapping?.molecule?.atoms?.length) return mapping.molecule;   // a composition's own synthesized geometry
    const moleculeId = mapping?.molecule_id;
    if (!moleculeId) {
      throw new Error('This model names no molecule, so its beads cannot be placed on any atoms');
    }
    let payload;
    try {
      payload = await cachedApi('/api/mappings/context?molecule_id=' + encodeURIComponent(moleculeId),
                                {maxAge: 60000});
    } catch (error) {
      throw new Error(`the coordinates of ${moleculeId} could not be read (${error.message})`);
    }
    const structure = payload?.molecule || payload?.context;
    if (!structure || !(structure.atoms || []).length) {
      throw new Error(`the route returned no coordinates for ${moleculeId}`);
    }
    return structure;
  }

  function structureAtoms() {
    const atoms = structure?.atoms || [];
    const legacyAngstrom = !structure?.molecule_id && !structure?.snapshot;
    const factor = legacyAngstrom ? 0.1 : 1;
    return new Map(atoms.map(atom => [Number(atom.id), {...atom, xyz: (atom.xyz || [0, 0, 0]).map(value => Number(value) * factor)}]));
  }

  function beadGeometry(mapping) {
    const atoms = structureAtoms();
    const centers = new Map();
    for (const bead of mapping?.beads || []) {
      if (bead.virtual_site) continue;
      const points = (bead.atoms || []).map(id => atoms.get(Number(id))?.xyz).filter(Boolean);
      if (points.length) centers.set(bead.name, points[0].map((_, index) => points.reduce((sum, point) => sum + point[index], 0) / points.length));
    }
    for (const bead of mapping?.beads || []) {
      if (!bead.virtual_site) continue;
      const points = (bead.virtual_site.parents || []).map(name => centers.get(name)).filter(Boolean);
      if (points.length) centers.set(bead.name, points[0].map((_, index) => points.reduce((sum, point) => sum + point[index], 0) / points.length));
    }
    const physical = new Set((mapping?.beads || []).filter(bead => !bead.virtual_site).map(bead => bead.name));
    let edges = (mapping?.connections || []).map(pair => [...pair]);
    if (!edges.length) {
      // The molecule the mapping names, never the packaged one: a bond between atom ids of another molecule would
      // draw a connectivity this model does not have.
      const owners = new Map();
      for (const bead of mapping?.beads || []) for (const id of bead.atoms || []) owners.set(Number(id), bead.name);
      edges = (structure?.bonds || []).map(edge => Array.isArray(edge) ? edge : [edge.a, edge.b])
        .map(([first, second]) => [owners.get(Number(first)), owners.get(Number(second))])
        .filter(([first, second]) => first && second && first !== second && physical.has(first) && physical.has(second));
    }
    return {beads: [...centers].map(([name, position]) => {
      const definition = (mapping?.beads || []).find(bead => bead.name === name) || {};
      return {name, position, size: definition.size || 'R', type: definition.type || 'Unspecified',
        virtual_site: definition.virtual_site};
    }), edges};
  }

  /** A revision's bead names, as the scene's: `B01` is the first bead of the mapping, virtual sites included.
   *
   * The names are the exported topology's, not the mapping's (`mappings/exports.py` writes `B{i+1:02d}` over the
   * mapping's bead list), so the two vocabularies have to be joined somewhere. Here, once, rather than in the plot:
   * the table goes on showing what the revision says, which is what a reader compares against the `.itp`.
   */
  function revisionAliases(mapping) {
    return new Map((mapping?.beads || []).map((bead, index) => [`B${String(index + 1).padStart(2, '0')}`, bead.name]));
  }

  /** A published reference's own ITP, read the way a revision's is and marked as the transcription it is.
   *
   * The reference model states `read_only` and a topology; it states no revision, so nothing in the panel may claim
   * an engine fitted it. `parseTopology` is the same reader a revision uses, which is what lets its `B01..` names be
   * aliased to the mapping's own by `revisionAliases` in the scene and compared against the `.itp` in the table.
   */
  function referenceTerms(mapping) {
    return parseTopology(mapping?.topology).map(term =>
      normalizeTerm({...term, editable: false, source: 'martini-reference'}, term.id));
  }

  /** The mapping's own connectivity, for a model that has no revision: a start, not a fitted result. */
  function mappingTerms(mapping) {
    const geometry = beadGeometry(mapping);
    const positions = new Map(geometry.beads.map(bead => [bead.name, bead.position]));
    const distance = (first, second) => {
      const a = positions.get(first), b = positions.get(second);
      if (!a || !b) return 0.3;
      return Math.sqrt(a.reduce((sum, value, index) => sum + (value - b[index]) ** 2, 0));
    };
    return (mapping?.connections || geometry.edges).map((pair, index) => normalizeTerm({
      id: `mapping:${index}`, kind: 'bonds', beads: pair, function: '1',
      parameters: [formatNumber(distance(pair[0], pair[1])), '5000'], editable: false, source: 'mapping',
    }, `mapping:${index}`));
  }

  function renderTable() {
    tableHost.replaceChildren();
    if (!terms.length) {
      tableHost.textContent = 'No bonded terms loaded.';
      return;
    }
    const table = document.createElement('table');
    table.innerHTML = '<caption>Kind names the GROMACS topology section; function is its potential form; source is where the term came from. Constraints and virtual-site parents are readings, not a draft.</caption>'
      + '<thead><tr><th>Kind</th><th>Beads</th><th>Function</th><th>Parameters</th><th>Source</th></tr></thead>';
    const body = document.createElement('tbody');
    for (const term of terms) {
      const row = document.createElement('tr');
      row.dataset.id = term.id;
      row.tabIndex = 0;
      row.setAttribute('aria-selected', String(term.id === selectedTermId));
      // A constraint's length is the mapping's ring target and a virtual site's parents are the mapping's own
      // beads: both are stated read-only, the way this panel stated them before it gained a `source` column.
      const reading = term.kind === 'constraints' || term.kind === 'virtual_sitesn';
      for (const [text, className] of [[term.kind, ''], [term.beads.join(' · '), ''],
                                       [functionSentence(term), ''],
                                       [parameterSentence(term), reading ? 'bonded-readonly-parameter' : ''],
                                       [term.source || 'unrecorded', 'bonded-source']]) {
        const cell = document.createElement('td');
        cell.textContent = text;
        if (className) cell.className = className;
        if (className === 'bonded-readonly-parameter') {
          cell.title = term.kind === 'constraints'
            ? 'read-only: this constraint’s length is the mapping’s own ring target'
            : 'read-only: these parents are the mapping’s own beads';
        }
        row.append(cell);
      }
      row.onclick = () => { selectedTermId = term.id; renderState(); };
      row.onkeydown = event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectedTermId = term.id; renderState(); }
      };
      body.append(row);
    }
    table.append(body);
    tableHost.append(table);
  }

  function renderState() {
    renderTable();
    if (!structure) {
      // No atoms, no scene: an empty figure and the reason, never another molecule's geometry under these names.
      plot.render({beads: [], edges: [], terms: [], selectedBeads, selectedTermId, beadAliases: new Map()});
      setText(selectionStatus, geometryNotice || 'Select a bead to read its name.');
      return;
    }
    const geometry = beadGeometry(selectedMapping || {});
    plot.render({beads: geometry.beads, edges: geometry.edges, terms, selectedBeads, selectedTermId,
                 beadAliases: revisionAliases(selectedMapping)});
    setText(selectionStatus, selectedBeads.length
      ? `Selected beads: ${selectedBeads.join(' · ')}`
      : 'Select a bead to read its name.');
  }

  /** The molecule select: every all-atom molecule the catalogue offers, plus CG compositions as one last group. */
  async function fillMolecules() {
    let list = [];
    try {
      // The shell's own cache key: a panel mount must be a reuse of the catalogue the shell warmed, not a new read.
      const answer = await cachedApi('/api/molecules', {maxAge: CATALOGUE_MAX_AGE});
      list = (answer.molecules || []).filter(record => record.kind !== 'cg');
    } catch (error) { list = []; }
    const options = list.map(record => new Option(record.name || record.id, record.id));
    // Compositions are CG models, not molecules, so they are not in `/api/molecules`: offered only where the
    // catalogue holds one, and last, because they are a different kind of thing rather than another molecule.
    if ((mappingData.candidates || []).some(candidate => String(candidate.file || '').startsWith('composition:'))) {
      options.push(new Option('CG compositions', COMPOSITIONS));
    }
    const previous = moleculeSelect.value;
    moleculeSelect.replaceChildren(...options);
    const named = (mappingData.candidates || []).find(candidate => candidate.molecule_id);
    const preferred = named ? named.molecule_id : list[0]?.id;
    if ([...moleculeSelect.options].some(option => option.value === previous)) moleculeSelect.value = previous;
    else if ([...moleculeSelect.options].some(option => option.value === preferred)) moleculeSelect.value = preferred;
    else if (moleculeSelect.options.length) moleculeSelect.selectedIndex = 0;
  }

  /** Each saved mapping's parameterization record: the selector names every revision, not only the shown mapping's. */
  async function readRecords(list) {
    // ponytail: one full record read per saved mapping, because the selector must label every revision and the route
    // answers one record at a time. A bulk summary route would trim the payloads if a molecule ever carries many.
    const records = new Map();
    await Promise.all(list.map(async candidate => {
      const params = new URLSearchParams();
      // The content identity first: it is what a revision is addressed by, and a rename keeps it.
      if (candidate.mapping_content_hash) params.set('content_hash', candidate.mapping_content_hash);
      if (candidate.mapping_hash) params.set('mapping_hash', candidate.mapping_hash);
      if (![...params].length) return;
      try {
        records.set(candidate.file, await api('/api/bonded-parameterizations?' + params));
      } catch (error) {
        // The options still list the mapping; its label says the record could not be read rather than claiming a draft.
        records.set(candidate.file, {error: error.message, summary: null, revisions: []});
      }
    }));
    return records;
  }

  /** The one display selector: every revision of every saved mapping, grouped by mapping. */
  function fillDisplay() {
    const wanted = displaySelect.value;
    const groups = [];
    for (const candidate of candidates) {
      const record = modelRecords.get(candidate.file);
      const revisions = [...(record?.revisions || [])].sort((first, second) => second.revision - first.revision);
      const current = record?.summary?.revision ?? null;
      const name = candidate.name || candidate.file;
      const group = document.createElement('optgroup');
      group.label = name;
      if (revisions.length) {
        for (const item of revisions) {
          group.append(new Option(`${name} · Revision ${item.revision} · `
            + `${item.revision === current ? 'current' : 'earlier'} · ${item.engine || 'fit'} · `
            + `${date(item.created_at) || 'no date recorded'}`, optionValue(candidate.file, item.revision)));
        }
      } else {
        group.append(new Option(record?.error ? 'Revisions could not be read'
          : 'Draft mapping connectivity (no parameterization)', optionValue(candidate.file, null)));
      }
      groups.push(group);
    }
    if (reference) {
      const group = document.createElement('optgroup');
      group.label = 'Published Martini 3 reference';
      group.append(new Option(
        `Martini 3 reference · ${reference.reference_entry || reference.molecule_id} (read-only)`,
        optionValue(reference.file, null)));
      groups.push(group);
    }
    if (!groups.length) {
      displaySelect.replaceChildren(new Option(moleculeSelect.value === COMPOSITIONS
        ? 'No saved CG compositions yet'
        : `No saved mapping for ${moleculeSelect.value || 'this molecule'} yet`, ''));
      return;
    }
    displaySelect.replaceChildren(...groups);
    const values = [...displaySelect.options].map(option => option.value);
    displaySelect.value = values.includes(wanted) ? wanted : defaultOptionValue();
  }

  /** What the selector answers when nothing is chosen: the first mapping's current revision, else its draft, else the
   * reference when it is the only option. It only reads -- a mount must never make a revision current. */
  function defaultOptionValue() {
    const first = candidates[0];
    if (first) {
      const record = modelRecords.get(first.file);
      const number = record?.summary?.revision ?? null;
      if (record?.revisions?.some(item => item.revision === number)) return optionValue(first.file, number);
      return optionValue(first.file, null);
    }
    return reference ? optionValue(reference.file, null) : '';
  }

  /** Point the selector at the revision the model card is actually showing (a load may have fallen back to current). */
  function syncDisplay() {
    if (!selectedMapping?.file) return;
    const shown = parameterization.shownRevision();
    const wanted = optionValue(selectedMapping.file, shown ? shown.revision : null);
    if ([...displaySelect.options].some(option => option.value === wanted)) displaySelect.value = wanted;
  }

  /** The hidden bridge's options: one per model a door can name, so `new-run.js` can wait for its own file. */
  function fillBridge() {
    if (!bridgeSelect) return;
    const options = candidates.map(candidate => new Option(candidate.name || candidate.file, candidate.file));
    if (reference) {
      options.push(new Option(reference.name || `Published reference · ${reference.molecule_id}`, reference.file));
    }
    bridgeSelect.replaceChildren(...options);
    if (selectedMapping?.file && options.some(option => option.value === selectedMapping.file)) {
      bridgeSelect.value = selectedMapping.file;
    }
  }

  /** The selected molecule's saved mappings and each one's parameterization record, then its published reference. */
  async function fillMappings(molecule) {
    const token = ++optionsGeneration;
    let list = [];
    if (molecule === COMPOSITIONS) {
      list = (mappingData.candidates || []).filter(candidate =>
        String(candidate.file || '').startsWith('composition:') && !candidate.error);
    } else if (molecule) {
      try {
        // Asked of the route, not filtered from a catalogue already in memory: the route holds both the molecule and
        // its snapshot, and a summary row does not have to carry `molecule_id` for this panel to work.
        const answer = await cachedApi(
          '/api/mappings?view=summary&molecule_id=' + encodeURIComponent(molecule), {maxAge: CATALOGUE_MAX_AGE});
        list = (answer.candidates || []).filter(candidate => !candidate.error && candidate.file);
      } catch (error) { list = []; }
    }
    let published = null;
    if (molecule && molecule !== COMPOSITIONS) {
      try {
        // A 404 is "this molecule has no published entry", which is an answer and not a failure to report.
        const answer = await cachedApi(
          '/api/mappings/reference/' + encodeURIComponent(molecule), {maxAge: CATALOGUE_MAX_AGE});
        published = answer?.model || null;
      } catch (error) { published = null; }
    }
    const records = await readRecords(list);
    if (token !== optionsGeneration) return false;
    candidates = list;
    reference = published;
    modelRecords = records;
    fillDisplay();
    fillBridge();
    return true;
  }

  /** Load and show one model. `revision` is the revision the selector asked for; `null` is its draft or a reference. */
  async function loadShown(file, revision) {
    const token = ++generation;
    // The switch is busy from the click, not from the panel load: the selector already shows the new model while the
    // catalogue answer is still in flight, so anything acting on the old panel's contents would act on a model that is
    // no longer selected. The model card, not the whole panel, is the region a switch repaints.
    modelCard.setAttribute('aria-busy', 'true');
    try {
      const mapping = await loadMapping(file);
      if (token !== generation) return;
      selectedMapping = mapping || null;
      geometryNotice = '';
      if (!mapping) {
        // A molecule with no saved model (or no composition) is a normal state: the table and the scene must not keep
        // showing the previous molecule's model while the card says there is nothing selected.
        structure = null;
        await parameterization.load(null);
        updateDelete();
        fillBridge();
        notice(moleculeSelect?.value === COMPOSITIONS ? 'No CG composition is selected.'
          : `No saved mapping for ${moleculeSelect?.value || 'this molecule'} yet.`);
        renderState();
        return;
      }
      // Before anything is drawn from it: every geometry below is measured against this molecule's atoms. A geometry
      // that cannot be read is stated, not replaced by the packaged molecule's.
      try {
        structure = await resolveStructure(mapping);
      } catch (error) {
        structure = null;
        geometryNotice = error.message;
      }
      if (token !== generation) return;
      // The model card, the job box, the result and the strip are read from the mapping's own
      // parameterization record; the terms come back through `onTerms` once that record has been read. The delete
      // button's state follows that record -- a model with no revisions has nothing for it to remove.
      await parameterization.load(mapping, {shown: revision});
      updateDelete();
      syncDisplay();
      fillBridge();
      notice(geometryNotice ? `The diagram is not drawn: ${geometryNotice}.` : '');
    } catch (error) {
      if (token === generation) {
        notice(error.message); selectedMapping = null; structure = null; terms = []; renderState();
      }
    } finally {
      // A superseded switch must not report the newer one idle: only the current generation owns the state.
      if (token === generation) modelCard.setAttribute('aria-busy', 'false');
    }
  }

  /** The selector's choice, applied. A revision of the mapping already shown is display-only: it reads no route and
   * changes nothing a run consumes. */
  async function showOption(value) {
    const target = optionTarget(value);
    if (!target.file) return;
    if (selectedMapping?.file === target.file) {
      if (target.revision !== null) {
        parameterization.show(target.revision);
        syncDisplay();
      }
      return;
    }
    await loadShown(target.file, target.revision);
  }

  if (displaySelect) displaySelect.onchange = () => showOption(displaySelect.value);
  if (bridgeSelect) bridgeSelect.onchange = () => select(bridgeSelect.value);
  if (moleculeSelect) moleculeSelect.onchange = async () => {
    await fillMappings(moleculeSelect.value);
    if (displaySelect.value) await showOption(displaySelect.value);
    else await loadShown('');
  };
  if (deleteButton) deleteButton.onclick = () => deleteParameterization();

  async function mount() {
    // One model load at mount: the selects are set and their options filled here, and `showOption` below loads the
    // model once. A `change` event dispatched at mount would load a second time for no reader-visible gain.
    modelCard.setAttribute('aria-busy', 'true');
    try {
      await fillMolecules();
      await fillMappings(moleculeSelect.value);
      updateDelete();
      await parameterization.mount();
      if (displaySelect.value) await showOption(displaySelect.value);
      else await loadShown('');
    } finally {
      // `loadShown` reports its own switch idle; a mount that failed before reaching it must not leave the card busy.
      if (!selectedMapping) modelCard.setAttribute('aria-busy', 'false');
    }
  }

  async function select(file) {
    // The catalog path, driven by whoever is handing a model over instead of by a click:
    // selecting the option is what a user picking it from the list does.
    if (!file) return false;
    const listed = () => candidates.some(candidate => candidate.file === file)
      || !!(reference && reference.file === file);
    if (!listed()) {
      if (file.startsWith('composition:')) {
        // A composition belongs to the catalogue's last group rather than to a molecule.
        if ([...moleculeSelect.options].some(option => option.value === COMPOSITIONS)) {
          moleculeSelect.value = COMPOSITIONS;
          await fillMappings(COMPOSITIONS);
        }
      } else if (file.startsWith('reference:')) {
        const molecule = file.slice('reference:'.length);
        if ([...moleculeSelect.options].some(option => option.value === molecule)) {
          moleculeSelect.value = molecule;
          await fillMappings(molecule);
        }
      } else {
        // A saved mapping names the molecule it maps, but a door's address carries only the file. Read the mapping
        // once (the same cached read `loadShown` will reuse) and move the molecule select to its own.
        let candidate = null;
        try { candidate = await loadMapping(file); } catch (error) { candidate = null; }
        const molecule = candidate?.molecule_id;
        if (molecule && [...moleculeSelect.options].some(option => option.value === molecule)) {
          moleculeSelect.value = molecule;
          await fillMappings(molecule);
        }
      }
    }
    if (!listed()) return false;
    const record = modelRecords.get(file);
    const revision = record?.revisions?.length ? (record.summary?.revision ?? null) : null;
    await loadShown(file, revision);
    return true;
  }
  return {mount, select};
}
