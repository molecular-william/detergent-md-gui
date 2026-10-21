/**
 * CG Bond Interactions: the mapping being described, its picture, and the terms of its current revision.
 *
 * The panel has two halves. This module owns the mapping selector, the bead geometry and the interactions
 * table; `bonded-parameterization.js` owns the model card, the fit job, the result and the revision strip, and
 * hands its terms here through `onTerms`. The split is the design's own: what is *read* about a model
 * (`/api/bonded-parameterizations`) is a different question from how its beads are drawn.
 *
 * The table is read-only, and that is a recorded decision rather than an oversight: no route in this slice writes a
 * revision's terms, so a parameter input here would be a control that cannot act — the failure this repository's
 * panels are not allowed to have. `docs/design/2026-10-16-parameterization-and-new-run.md` D7 records it, with the
 * route that would restore the old manual editor. The `source` column is what a reader needs instead — it says
 * which engine fitted each term, or that the mapping (a ring constraint, a virtual site), a hand edit recorded
 * elsewhere, or a geometry fallback produced it. Two kinds are not a draft at all and are marked as the reading they
 * are: a constraint's length and a virtual site's parents come from the mapping.
 */
import { $, setText, cachedApi, api, invalidateResource } from './shared.js';
import { mountBondedPlot } from './bonded-plot.js';
import { setupParameterization } from './bonded-parameterization.js';

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

const formatNumber = value => Number.isFinite(Number(value)) ? Number(value).toString() : '';

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
  const mappingSelect = $('#bonded-mapping-select', host);
  const deleteButton = $('#bonded-delete-parameterization', host);
  const message = $('.bonded-panel-message', host);
  const tableHost = $('.bonded-interaction-table', host);
  const selectionStatus = $('.bonded-selection-status', host);
  const plot = mountBondedPlot($('.bonded-plot', host), {
    onBeadSelection: selected => { selectedBeads = selected; renderState(); },
    onTermSelection: id => { selectedTermId = id; renderState(); },
    onPlotError: notice,
  });
  let selectedMapping = null;
  let structure = null;
  let terms = [];
  let selectedBeads = [];
  let selectedTermId = '';
  let generation = 0;

  const parameterization = setupParameterization({host, onTerms: revisionTerms => {
    // `null` is the mapping's own draft: a model with no revision still shows the connectivity its mapping
    // declares, and every row of it says where it came from rather than being presented as a fitted term.
    terms = revisionTerms ?? mappingTerms(selectedMapping || {});
    renderState();
  }});

  function notice(text) { setText(message, text); }

  /** Whether the selected catalogue entry is a saved mapping whose parameterization this panel may delete.
   *
   * The catalogue also lists CG compositions, addressed as `composition:<id>` rather than by a draft file name: they
   * carry no parameterization, and offering the button for one would be a control that cannot act.
   */
  function deletable() {
    const value = mappingSelect.value || '';
    if (!value || value.startsWith('composition:')) return false;
    return (mappingData.candidates || []).some(candidate => candidate.file === value && !candidate.error);
  }

  function updateDelete() {
    if (!deleteButton) return;
    const value = mappingSelect.value || '';
    const held = parameterization.revisionCount();
    const allowed = deletable() && held > 0;
    deleteButton.disabled = !allowed;
    deleteButton.title = !deletable() ? (value.startsWith('composition:')
      ? 'A CG composition carries no parameterization to delete.'
      : 'Choose a saved mapping first.')
      : held ? `Delete the parameterization of ${value}: ${held === 1 ? 'its single revision' : `its ${held} revisions`}`
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
    const file = mappingSelect.value || '';
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
    // The context route answers in nanometres and says which molecule it is, so the legacy-Angstrom branch below
    // fires only for the packaged reference: a candidate that names no molecule, or one whose context cannot be
    // read. Falling back to the old behaviour beats drawing nothing at all.
    const moleculeId = mapping?.molecule_id;
    if (!moleculeId) return mappingData.molecule;
    try {
      const payload = await cachedApi('/api/mappings/context?molecule_id=' + encodeURIComponent(moleculeId),
                                      {maxAge: 60000});
      return payload?.molecule || payload?.context || mappingData.molecule;
    } catch (error) {
      return mappingData.molecule;
    }
  }

  function structureAtoms() {
    const source = structure || mappingData.molecule;
    const atoms = source?.atoms || [];
    const legacyAngstrom = !source?.molecule_id && !source?.snapshot;
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
      const owners = new Map();
      for (const bead of mapping?.beads || []) for (const id of bead.atoms || []) owners.set(Number(id), bead.name);
      edges = (mappingData.molecule?.bonds || []).map(edge => Array.isArray(edge) ? edge : [edge.a, edge.b])
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
    const geometry = beadGeometry(selectedMapping || {});
    plot.render({beads: geometry.beads, edges: geometry.edges, terms, selectedBeads, selectedTermId,
                 beadAliases: revisionAliases(selectedMapping)});
    setText(selectionStatus, selectedBeads.length
      ? `Selected beads: ${selectedBeads.join(' · ')}`
      : 'Select a bead to read its name.');
  }

  async function refreshMapping() {
    const token = ++generation;
    try {
      const mapping = await loadMapping(mappingSelect.value);
      if (token !== generation || !mapping) return;
      selectedMapping = mapping;
      // Before anything is drawn from it: every geometry below is measured against this molecule's atoms.
      structure = await resolveStructure(mapping);
      if (token !== generation) return;
      // The model card, the job box, the result and the strip are read from the mapping's own
      // parameterization record; the terms come back through `onTerms` once that record has been read. The delete
      // button's state follows that record -- a model with no revisions has nothing for it to remove.
      await parameterization.load(mapping);
      updateDelete();
    } catch (error) {
      if (token === generation) { notice(error.message); terms = []; renderState(); }
    }
  }

  mappingSelect.onchange = () => { updateDelete(); refreshMapping(); };
  if (deleteButton) deleteButton.onclick = () => deleteParameterization();

  async function mount() {
    const chosen = mappingSelect.value;
    mappingSelect.replaceChildren(...mappingData.candidates.filter(candidate => !candidate.error).map(candidate => new Option(candidate.name, candidate.file)));
    if (mappingData.candidates.some(candidate => candidate.file === chosen)) mappingSelect.value = chosen;
    if (!mappingSelect.value && mappingSelect.options.length) mappingSelect.selectedIndex = 0;
    updateDelete();
    await parameterization.mount();
    await refreshMapping();
  }

  async function select(file) {
    // The catalog path, driven by whoever is handing a model over instead of by a click:
    // selecting the option is what a user picking it from the list does.
    if (![...mappingSelect.options].some(option => option.value === file)) return false;
    mappingSelect.value = file;
    updateDelete();
    await refreshMapping();
    return true;
  }
  return {mount, select};
}
