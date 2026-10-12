import { $, $$, setText, api, post, cachedApi, invalidateResource } from './shared.js';
import { mountBondedPlot } from './bonded-plot.js';

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

const ordinaryKinds = new Set(Object.keys(FUNCTION_OPTIONS));
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
    editable: term.editable ?? ordinaryKinds.has(kind), function_options: options,
    parameter_labels: term.parameter_labels?.length ? [...term.parameter_labels] : [...(selected?.labels || [])]};
}

export function setupBondedWorkspace(mappingData, {loadMapping}) {
  const host = $('.bonded-workspace');
  if (!host || !mappingData) return;
  const mappingSelect = $('.bonded-mapping-select', host);
  const stateSelect = $('.bonded-state-select', host);
  const message = $('.bonded-panel-message', host);
  const nameInput = $('.bonded-state-name', host);
  const saveNew = $('.bonded-save-new', host);
  const automatic = $('.bonded-automatic', host);
  const createInteraction = $('.bonded-create-interaction', host);
  const shortRun = $('.bonded-short-run', host);
  const deleteState = $('.bonded-delete', host);
  const tableHost = $('.bonded-interaction-table', host);
  const selectionStatus = $('.bonded-selection-status', host);
  const plot = mountBondedPlot($('.bonded-plot', host), {
    onBeadSelection: selected => { selectedBeads = selected; renderState(); },
    onTermSelection: id => { selectedTermId = id; renderState(); },
    onPlotError: notice,
  });
  let states = [];
  let selectedState = null;
  let selectedMapping = null;
  let structure = null;
  let terms = [];
  let selectedBeads = [];
  let selectedTermId = '';
  let dirty = false;
  let generation = 0;
  let draftCounter = 0;

  function notice(text) { setText(message, text); }

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
      parameters: [formatNumber(distance(pair[0], pair[1])), '5000'], editable: true,
    }, `mapping:${index}`));
  }

  function updateControls() {
    createInteraction.disabled = selectedBeads.length !== 2 || !selectedMapping;
    saveNew.disabled = !selectedMapping || !terms.length || !dirty;
    deleteState.disabled = !selectedState;
    shortRun.disabled = !selectedState;
    setText(selectionStatus, selectedBeads.length ? `Selected beads: ${selectedBeads.join(' · ')}${selectedBeads.length === 2 ? ' · ready to create an interaction' : ''}` : 'Select up to two physical beads to create an interaction.');
  }

  function renderTable() {
    tableHost.replaceChildren();
    if (!terms.length) { tableHost.textContent = 'No bonded terms loaded.'; return; }
    const table = document.createElement('table');
    table.innerHTML = '<caption>Functions choose the potential form; bond lengths are derived from bead geometry and remain read-only.</caption><thead><tr><th>Kind</th><th>Beads</th><th>Function</th><th>Parameters</th></tr></thead>';
    const body = document.createElement('tbody');
    for (const term of terms) {
      const row = document.createElement('tr'); row.dataset.id = term.id; row.tabIndex = 0; row.setAttribute('aria-selected', String(term.id === selectedTermId));
      const kind = document.createElement('td'); kind.textContent = term.kind; row.append(kind);
      const beads = document.createElement('td'); beads.textContent = term.beads.join(' · '); row.append(beads);
      const functionCell = document.createElement('td');
      if (term.editable && term.function_options.length > 1) {
        const select = document.createElement('select'); select.setAttribute('aria-label', `${term.kind} ${term.beads.join(' ')} function`);
        for (const option of term.function_options) {
          const label = option.description ? `${option.label} — ${option.description}` : option.label;
          select.append(new Option(label, option.value));
        }
        select.value = term.function;
        select.onchange = () => {
          const selected = term.function_options.find(option => option.value === select.value) || optionsFor(term.kind).find(option => option.value === select.value);
          const old = [...term.parameters]; term.function = select.value; term.parameter_labels = [...(selected?.labels || [])];
          term.parameters = term.parameter_labels.map((_, index) => old[index] ?? ''); dirty = true; renderState();
        };
        functionCell.append(select);
      } else {
        const option = term.function_options[0];
        functionCell.textContent = option ? `${option.label}${option.description ? ` — ${option.description}` : ''}` : (term.function || '—');
      }
      row.append(functionCell);
      const parameters = document.createElement('td');
      if (term.editable) {
        const grid = document.createElement('div'); grid.className = 'bonded-parameter-row';
        for (const [index, value] of term.parameters.entries()) {
          const labelText = term.parameter_labels[index] || `Parameter ${index + 1}`;
          const label = document.createElement('label'); label.textContent = labelText;
          if (term.kind === 'bonds' && index === 0) {
            const output = document.createElement('output'); output.className = 'bonded-readonly-parameter';
            output.textContent = value; output.setAttribute('aria-label', `${term.kind} ${term.beads.join(' ')} ${labelText}`);
            label.append(output);
          } else {
            const input = document.createElement('input'); input.type = 'number'; input.step = 'any'; input.value = value;
            input.setAttribute('aria-label', `${term.kind} ${term.beads.join(' ')} ${labelText}`);
            input.oninput = () => { term.parameters[index] = input.value; dirty = true; updateControls(); };
            label.append(input);
          }
          grid.append(label);
        }
        parameters.append(grid);
      } else parameters.textContent = term.parameters?.join(' ') || 'Read-only';
      row.append(parameters);
      row.onclick = () => { selectedTermId = term.id; renderState(); };
      row.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectedTermId = term.id; renderState(); } };
      body.append(row);
    }
    table.append(body); tableHost.append(table);
  }

  function renderState() {
    renderTable();
    const geometry = beadGeometry(selectedMapping || {});
    plot.render({beads: geometry.beads, edges: geometry.edges, terms, selectedBeads, selectedTermId});
    if (selectedState) nameInput.value = selectedState.name || selectedState.current?.name || nameInput.value;
    updateControls();
  }

  async function loadStates(mapping, token) {
    // The candidate identity first: it names the saved file these states were fitted from, so
    // distinct candidates stay distinct even when their chemistry is identical. Only if that finds
    // nothing does it ask by chemistry -- a renamed candidate changes that hash and nothing else, and
    // this is what keeps its fitted work listed.
    const ask = async (params) => (params.mapping_hash || params.content_hash)
      ? await cachedApi('/api/bonded-states?' + new URLSearchParams({view: 'summary', ...params}), {maxAge: 10000})
      : {states: []};
    let response = await ask({mapping_hash: mapping?.mapping_hash});
    if (token !== generation) return;
    if (!(response.states || []).length && mapping?.mapping_content_hash) {
      response = await ask({content_hash: mapping.mapping_content_hash});
      if (token !== generation) return;
    }
    if (token !== generation) return;
    states = response.states || [];
    const selected = stateSelect.value;
    stateSelect.replaceChildren(new Option('Mapping draft · unsaved', ''));
    for (const state of states) stateSelect.append(new Option(`${state.name} · r${state.revision} · ${state.current?.status || 'unknown'}`, state.state_id));
    stateSelect.value = states.some(state => state.state_id === selected) ? selected : '';
  }

  async function draw(summary, mapping, token) {
    selectedState = null; selectedTermId = ''; selectedBeads = []; dirty = false;
    if (summary) {
      selectedState = await cachedApi('/api/bonded-states/' + encodeURIComponent(summary.state_id), {maxAge: 10000});
      if (token !== generation) return;
      const response = await cachedApi('/api/bonded-states/' + encodeURIComponent(summary.state_id) + '/interactions', {maxAge: 10000});
      if (token !== generation) return;
      terms = (response.interactions || []).map((term, index) => normalizeTerm(term, `${term.kind}:${index + 1}`));
      nameInput.value = selectedState.name || selectedState.current?.name || '';
    } else {
      terms = mappingTerms(mapping); nameInput.value = `${mapping.name || 'Mapping'} bonded draft`;
    }
    setText($('.bonded-state-summary', host), selectedState ? `Revision ${selectedState.revision} · ${selectedState.current.origin} · ${selectedState.current.status}` : 'Mapping draft · unsaved');
    renderState();
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
      await loadStates(mapping, token);
      if (token !== generation) return;
      await draw(states.find(state => state.state_id === stateSelect.value), mapping, token);
    } catch (error) { if (token === generation) { notice(error.message); terms = []; renderState(); } }
  }

  async function generateAutomatic() {
    if (!selectedMapping) return notice('Choose a mapping first.');
    automatic.disabled = true;
    try {
      const result = await post('/api/bonded-states/automatic', {mapping: selectedMapping});
      terms = (result.interactions || []).map((term, index) => normalizeTerm(term, `${term.kind}:${index + 1}`));
      selectedState = null; selectedTermId = ''; selectedBeads = []; dirty = true;
      setText($('.bonded-state-summary', host), 'Automatic draft · unsaved'); renderState();
      notice(result.diagnostics?.length ? result.diagnostics.join(' ') : 'Automatic bonded draft generated.');
    } catch (error) { notice(error.message); }
    finally { automatic.disabled = false; updateControls(); }
  }

  function createNewInteraction() {
    if (selectedBeads.length !== 2) return notice('Select exactly two physical beads first.');
    const pair = [...selectedBeads];
    if (terms.some(term => term.kind === 'bonds' && new Set(term.beads).size === 2 && term.beads.every(name => pair.includes(name)))) return notice('That bead pair already has a bond.');
    const geometry = beadGeometry(selectedMapping); const positions = new Map(geometry.beads.map(bead => [bead.name, bead.position]));
    const first = positions.get(pair[0]), second = positions.get(pair[1]);
    const distance = first && second ? Math.sqrt(first.reduce((sum, value, index) => sum + (value - second[index]) ** 2, 0)) : 0.3;
    const term = normalizeTerm({id: `draft:${++draftCounter}`, kind: 'bonds', beads: pair, function: '1', parameters: [formatNumber(distance), '5000'], editable: true}, `draft:${draftCounter}`);
    terms.push(term); selectedTermId = term.id; dirty = true; renderState(); notice(`Created a draft bond between ${pair.join(' and ')}.`);
  }

  async function saveDraft() {
    if (!selectedMapping || !terms.length) return;
    const interactions = terms.filter(term => ordinaryKinds.has(term.kind)).map(term => ({kind: term.kind, beads: term.beads, function: term.function, parameters: term.parameters}));
    const name = nameInput.value.trim() || `${selectedMapping.name || 'Mapping'} bonded state`;
    try {
      let response;
      const hasDraftTerms = terms.some(term => String(term.id).startsWith('draft:') || String(term.id).startsWith('mapping:'));
      if (!selectedState || hasDraftTerms) {
        response = await post('/api/bonded-states', {mapping: selectedMapping, name, kind: 'manual-edit', status: 'complete', interactions,
          source: {origin: 'manual-editor', parent_state_id: selectedState?.state_id || null, parent_revision: selectedState?.revision || null}});
      } else {
        const edits = terms.filter(term => term.editable && ordinaryKinds.has(term.kind)).map(term => ({id: term.id, function: term.function, parameters: term.parameters}));
        response = await api('/api/bonded-states/' + encodeURIComponent(selectedState.state_id), {method: 'PATCH', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({patch: {name, interaction_edits: edits}, expected_revision: selectedState.revision, in_place: false})});
      }
      invalidateResource('/api/bonded-states'); await refreshMapping(); stateSelect.value = response.state_id; stateSelect.dispatchEvent(new Event('change')); notice('New bonded state saved; source state unchanged.');
    } catch (error) { notice(error.message); }
  }

  mappingSelect.onchange = () => refreshMapping();
  stateSelect.onchange = () => { const token = ++generation; draw(states.find(state => state.state_id === stateSelect.value), selectedMapping, token).catch(error => { if (token === generation) notice(error.message); }); };
  automatic.onclick = () => generateAutomatic();
  createInteraction.onclick = () => createNewInteraction();
  saveNew.onclick = () => saveDraft();
  shortRun.onclick = async () => {
    if (!selectedState || !selectedMapping) return;
    try {
      const response = await post('/', {detergent: 'DDM', method: 'fast_forward', profile: 'draft-smoke', label: `Short bonded validation · ${selectedMapping.name}`,
        mapping_candidate: selectedMapping.file, bonded_state_id: selectedState.state_id, temporary_validation: true,
        aa_equil_ps: 10, aa_production_ps: 50, cg_equil_ps: 10, cg_production_ps: 100, temperature_k: 300, output_interval_ps: 1,
        cg_seed: Math.floor(Math.random() * 2147483646) + 1});
      notice(`Short validation queued: ${response.id}. Inspect it in Runs.`);
    } catch (error) { notice(error.message); }
  };
  deleteState.onclick = async () => {
    if (!selectedState || !confirm('Delete this bonded state? Referenced runs will block deletion.')) return;
    try {
      await api('/api/bonded-states/' + encodeURIComponent(selectedState.state_id), {method: 'DELETE', body: JSON.stringify({confirm: true}), headers: {'Content-Type': 'application/json'}});
      invalidateResource('/api/bonded-states'); await refreshMapping(); notice('Bonded state deleted.');
    } catch (error) { notice(error.message); }
  };

  async function mount() {
    const chosen = mappingSelect.value;
    mappingSelect.replaceChildren(...mappingData.candidates.filter(candidate => !candidate.error).map(candidate => new Option(candidate.name, candidate.file)));
    if (mappingData.candidates.some(candidate => candidate.file === chosen)) mappingSelect.value = chosen;
    if (!mappingSelect.value && mappingSelect.options.length) mappingSelect.selectedIndex = 0;
    await refreshMapping();
  }
  async function select(file) {
    // The catalog path, driven by whoever is handing a model over instead of by a click:
    // selecting the option is what a user picking it from the list does.
    if (![...mappingSelect.options].some(option => option.value === file)) return false;
    mappingSelect.value = file;
    await refreshMapping();
    return true;
  }
  return {mount, select};
}
