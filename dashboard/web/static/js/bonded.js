import { $, $$, setText, api, post, cachedApi, invalidateResource } from './shared.js';

// Bonded-state interaction rendering receives the current mapping catalog.
export function setupBondedWorkspace(mappingData, { onFit, loadMapping }) {
  const host = $('.bonded-workspace');
  if (!host || !mappingData) return;
  const mappingSelect = $('.bonded-mapping-select', host);
  const stateSelect = $('.bonded-state-select', host);
  const message = $('.bonded-panel-message', host);
  const editorPanel = $('.bonded-editor-panel', host);
  const parameterEditor = $('.bonded-parameter-editor', host);
  const nameInput = $('.bonded-state-name', host);
  const saveNew = $('.bonded-save-new', host);
  const revise = $('.bonded-revise', host);
  let states = [];
  let selectedState = null;
  let selectedMapping = null;
  let terms = [];
  let generation = 0;
  const notice = text => setText(message, text);

  function clearPreview() {
    $('.bonded-diagram', host).replaceChildren();
    $('.bonded-interaction-table', host).replaceChildren();
    $('.bonded-itp-preview', host).textContent = 'Loading bonded interaction preview…';
    parameterEditor.replaceChildren();
    editorPanel.hidden = true;
    saveNew.disabled = true;
    revise.disabled = true;
    $('.bonded-delete', host).disabled = true;
  }

  function selectedMappingHash(mapping) {
    return mapping?.mapping_hash || '';
  }

  async function loadStates(mappingHash, token) {
    if (!mappingHash) {
      states = [];
      stateSelect.replaceChildren(new Option('Mapping only · fit parameters', ''));
      return;
    }
    const query = new URLSearchParams({view: 'summary', mapping_hash: mappingHash});
    const response = await cachedApi('/api/bonded-states?' + query.toString(), {maxAge: 10000});
    if (token !== generation) return;
    states = response.states || [];
    const chosen = stateSelect.value;
    stateSelect.replaceChildren(new Option('Mapping only · fit parameters', ''));
    for (const state of states) {
      const status = state.current?.status || 'unknown';
      stateSelect.append(new Option(`${state.name} · r${state.revision} · ${status}`, state.state_id));
    }
    stateSelect.value = states.some(state => state.state_id === chosen) ? chosen : '';
  }

  function translateTerms(rawTerms, mapping) {
    const byIndex = new Map((mapping.beads || []).map((bead, index) => [index + 1, bead.name]));
    return rawTerms.map(term => {
      const indices = term.kind.startsWith('virtual_sites') ? (term.parents || []) : (term.indices || []);
      const beads = indices.map(index => byIndex.get(index) || term.beads?.[0] || String(index));
      return {...term, beads, topology_beads: term.beads || [], indices};
    });
  }

  function renderEditor() {
    parameterEditor.replaceChildren();
    if (!selectedState || !terms.length) {
      editorPanel.hidden = true;
      return;
    }
    editorPanel.hidden = false;
    nameInput.value = selectedState.name || selectedState.current?.name || '';
    for (const term of terms) {
      if (term.kind.startsWith('virtual_sites') || term.kind === 'constraints') continue;
      const row = document.createElement('div');
      row.className = 'bonded-parameter-row';
      const label = document.createElement('span');
      label.textContent = `${term.kind} · ${term.beads.join(' · ')}`;
      row.append(label);
      for (const [index, value] of (term.parameters || []).entries()) {
        const input = document.createElement('input');
        input.type = 'number'; input.step = 'any'; input.value = value;
        input.dataset.termId = term.id; input.dataset.parameterIndex = String(index);
        input.setAttribute('aria-label', `${term.kind} ${term.beads.join(' ')} parameter ${index + 1}`);
        row.append(input);
      }
      parameterEditor.append(row);
    }
  }

  function editedParameters() {
    const byId = new Map();
    $$('.bonded-parameter-row input', host).forEach(input => {
      const value = Number(input.value);
      if (!Number.isFinite(value)) throw new Error('Bonded parameters must be finite numbers');
      const values = byId.get(input.dataset.termId) || [];
      values[Number(input.dataset.parameterIndex)] = value;
      byId.set(input.dataset.termId, values);
    });
    return [...byId].map(([id, parameters]) => ({id, parameters}));
  }

  function renderDiagram(mapping, stateTerms, token) {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 960 620'); svg.classList.add('bonded-svg');
    const atoms = mappingData.molecule.atoms.filter(atom => atom.heavy);
    const xs = atoms.map(atom => atom.xyz[0]), ys = atoms.map(atom => atom.xyz[1]);
    const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
    const scale = Math.min(820 / (maxx - minx || 1), 500 / (maxy - miny || 1));
    const point = atom => ({x: 70 + (atom.xyz[0] - minx) * scale, y: 560 - (atom.xyz[1] - miny) * scale});
    const atomPos = new Map(atoms.map(atom => [atom.id, point(atom)]));
    for (const [a, b] of mappingData.molecule.bonds) {
      const p = atomPos.get(a), q = atomPos.get(b); if (!p || !q) continue;
      const line = document.createElementNS(ns, 'line');
      for (const [key, value] of Object.entries({x1: p.x, y1: p.y, x2: q.x, y2: q.y, class: 'aa-link'})) line.setAttribute(key, value);
      svg.append(line);
    }
    const centers = {};
    for (const bead of mapping.beads || []) {
      if (bead.virtual_site) continue;
      const points = bead.atoms.map(id => atomPos.get(id)).filter(Boolean);
      if (points.length) centers[bead.name] = {x: points.reduce((sum, p) => sum + p.x, 0) / points.length, y: points.reduce((sum, p) => sum + p.y, 0) / points.length};
    }
    for (const bead of (mapping.beads || []).filter(item => item.virtual_site)) {
      const points = bead.virtual_site.parents.map(name => centers[name]).filter(Boolean);
      if (points.length === 3) centers[bead.name] = {x: points.reduce((sum, p) => sum + p.x, 0) / 3, y: points.reduce((sum, p) => sum + p.y, 0) / 3};
    }
    const selected = id => {
      $$('.bonded-interaction-table tr', host).forEach(row => row.setAttribute('aria-selected', String(row.dataset.id === id)));
      $$('.cg-term', svg).forEach(element => element.classList.toggle('selected', element.dataset.id === id));
      const term = stateTerms.find(item => item.id === id);
      $$('.cg-node', svg).forEach(element => element.classList.toggle('selected', !!term?.beads.includes(element.dataset.bead)));
    };
    for (const term of stateTerms) {
      const points = term.beads.map(name => centers[name]).filter(Boolean); if (points.length < 2) continue;
      const line = document.createElementNS(ns, 'polyline'); line.setAttribute('points', points.map(item => `${item.x},${item.y}`).join(' ')); line.dataset.id = term.id; line.setAttribute('class', 'cg-term'); svg.append(line);
    }
    for (const [name, point] of Object.entries(centers)) {
      const circle = document.createElementNS(ns, 'circle'); circle.setAttribute('cx', point.x); circle.setAttribute('cy', point.y); circle.setAttribute('r', 18); circle.setAttribute('class', 'cg-node'); circle.dataset.bead = name; svg.append(circle);
      const text = document.createElementNS(ns, 'text'); text.setAttribute('x', point.x); text.setAttribute('y', point.y + 5); text.setAttribute('text-anchor', 'middle'); text.textContent = name; svg.append(text);
    }
    const legend = document.createElementNS(ns, 'text'); legend.setAttribute('x', '70'); legend.setAttribute('y', '30'); legend.setAttribute('class', 'bonded-legend'); legend.textContent = 'Grey: AA connectivity   Blue: bonded interaction   Red: selected term'; svg.append(legend);
    $('.bonded-diagram', host).replaceChildren(svg);
    const tableHost = $('.bonded-interaction-table', host); tableHost.replaceChildren();
    if (!stateTerms.length) tableHost.textContent = 'No bonded terms are available yet. Fit parameters or edit the mapping, then create a state revision.';
    else {
      const table = document.createElement('table'); table.innerHTML = '<caption>Click a term to highlight its beads</caption><thead><tr><th>Type</th><th>Beads</th><th>Function</th><th>Parameters</th></tr></thead>';
      const body = document.createElement('tbody');
      for (const term of stateTerms) {
        const row = document.createElement('tr'); row.dataset.id = term.id; row.tabIndex = 0;
        [term.kind, term.beads.join(' · '), term.function || '—', (term.parameters || []).join(' ') || '—'].forEach(value => { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); });
        row.onclick = () => selected(term.id); row.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selected(term.id); } }; body.append(row);
      }
      table.append(body); tableHost.append(table);
    }
    $('.bonded-itp-preview', host).textContent = selectedState?.current?.topology || `[ mapping-only preview ]\n; ${mapping.name}\n; Fit bonded parameters to generate a reusable ITP\n\n[ connections ]\n${(mapping.connections || []).map(pair => pair.join('  ')).join('\n')}`;
    renderEditor();
    if (token !== generation) clearPreview();
  }

  async function draw(stateSummary, mapping, token) {
    if (token !== generation) return;
    selectedState = null; terms = [];
    if (stateSummary) {
      selectedState = await cachedApi('/api/bonded-states/' + encodeURIComponent(stateSummary.state_id), {maxAge: 10000});
      if (token !== generation) return;
      const response = await cachedApi('/api/bonded-states/' + encodeURIComponent(stateSummary.state_id) + '/interactions', {maxAge: 10000});
      if (token !== generation) return;
      terms = translateTerms(response.interactions || [], mapping);
    } else terms = (mapping.connections || []).map((pair, index) => ({id: 'mapping:' + index, kind: 'bonds', beads: pair, function: '1', parameters: []}));
    if (token !== generation) return;
    renderDiagram(mapping, terms, token);
    $('.bonded-delete', host).disabled = !selectedState; saveNew.disabled = !selectedState; revise.disabled = !selectedState;
    setText($('.bonded-state-summary', host), selectedState ? `Revision ${selectedState.revision} · ${selectedState.current.origin} · ${selectedState.current.status}` : 'No bonded state selected; a run will fit parameters.');
  }

  async function refreshMapping() {
    const token = ++generation; clearPreview();
    try {
      const mapping = await loadMapping(mappingSelect.value);
      if (token !== generation || !mapping) return;
      selectedMapping = mapping;
      await loadStates(selectedMappingHash(mapping), token);
      if (token !== generation) return;
      await draw(states.find(state => state.state_id === stateSelect.value), mapping, token);
    } catch (error) { if (token === generation) { clearPreview(); notice(error.message); } }
  }

  async function saveState(inPlace) {
    if (!selectedState || !selectedMapping) return;
    const patch = {name: nameInput.value.trim() || selectedState.name, interaction_parameters: editedParameters()};
    const response = await api('/api/bonded-states/' + encodeURIComponent(selectedState.state_id), {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({patch, expected_revision: selectedState.revision, in_place: inPlace})});
    invalidateResource('/api/bonded-states'); await refreshMapping(); stateSelect.value = response.state_id; stateSelect.dispatchEvent(new Event('change'));
    notice(inPlace ? 'Bonded state revision saved.' : 'New bonded state saved; source state unchanged.');
  }

  mappingSelect.onchange = () => refreshMapping();
  stateSelect.onchange = () => { const token = ++generation; clearPreview(); draw(states.find(state => state.state_id === stateSelect.value), selectedMapping, token).catch(error => { if (token === generation) notice(error.message); }); };
  $('.bonded-load', host).onclick = () => refreshMapping();
  $('.bonded-create', host).onclick = async () => { try { const mapping = await loadMapping(mappingSelect.value); if (!mapping) throw new Error('Choose a mapping first.'); const state = await post('/api/bonded-states', {mapping, name: `${mapping.name} bonded state`, kind: 'mapping-only', status: 'incomplete'}); invalidateResource('/api/bonded-states'); await refreshMapping(); stateSelect.value = state.state_id; stateSelect.dispatchEvent(new Event('change')); notice('Created a mapping-only state. Fit parameters or edit it before reuse.'); } catch (error) { notice(error.message); } };
  $('.bonded-fit', host).onclick = () => onFit(mappingSelect.value).catch(error => notice(error.message));
  $('.bonded-short-run', host).onclick = async () => { try { const mapping = await loadMapping(mappingSelect.value); if (!mapping) throw new Error('Choose a mapping first.'); const response = await post('/', {detergent: 'DDM', method: 'fast_forward', profile: 'draft-smoke', label: `Short bonded validation · ${mapping.name}`, mapping_candidate: mapping.file, bonded_state_id: stateSelect.value || '', temporary_validation: true, aa_equil_ps: 10, aa_production_ps: 50, cg_equil_ps: 10, cg_production_ps: 100, temperature_k: 300, output_interval_ps: 1, cg_seed: Math.floor(Math.random() * 2147483646) + 1}); notice(`Short validation queued: ${response.id}. Inspect it in Runs.`); } catch (error) { notice(error.message); } };
  $('.bonded-delete', host).onclick = async () => { const id = stateSelect.value; if (!id || !confirm('Delete this bonded state? Referenced runs will block deletion.')) return; try { await api('/api/bonded-states/' + encodeURIComponent(id), {method: 'DELETE', body: JSON.stringify({confirm: true}), headers: {'Content-Type': 'application/json'}}); invalidateResource('/api/bonded-states'); await refreshMapping(); notice('Bonded state deleted.'); } catch (error) { notice(error.message); } };
  saveNew.onclick = () => saveState(false).catch(error => notice(error.message));
  revise.onclick = () => { if (confirm('Create a new revision of this bonded state?')) saveState(true).catch(error => notice(error.message)); };

  async function mount() {
    const chosen = mappingSelect.value;
    mappingSelect.replaceChildren(...mappingData.candidates.filter(candidate => !candidate.error).map(candidate => new Option(candidate.name, candidate.file)));
    if (mappingData.candidates.some(candidate => candidate.file === chosen)) mappingSelect.value = chosen;
    if (!mappingSelect.value && mappingSelect.options.length) mappingSelect.selectedIndex = 0;
    await refreshMapping();
  }
  return {mount};
}
