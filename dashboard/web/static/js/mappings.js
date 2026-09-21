import { $, $$, storage, setText, api, post, downloadBlob, cachedApi, invalidateResource } from './shared.js';
import { setupBondedWorkspace } from './bonded.js';
import { createEditor, toggleAtom, clearSelection, groupAtoms } from './mapping-state.js';
import { mountDiagram } from './mapping-diagram.js';
import { MappingPanel } from './mapping-panel.js';

// Candidate edits, local drafts, validation and exports stay inside this workspace.
export function createMappings({ onFit }) {
  function renderRegistryList(selector, items, formatter) {
    const list = $(selector); if (!list) return; list.replaceChildren();
    if (!items?.length) {
      list.append(Object.assign(document.createElement('li'), {textContent: 'None indexed yet', className: 'hint'}));
      return;
    }
    for (const item of items) {
      const li = document.createElement('li');
      li.textContent = typeof item === 'string' ? item : formatter(item);
      list.append(li);
    }
  }

  async function loadModelRegistry() {
    const [index, refs, frags, comps] = await Promise.all([
      cachedApi('/api/reference-index', {maxAge: 10000}),
      cachedApi('/api/model-references', {maxAge: 10000}),
      cachedApi('/api/model-fragments', {maxAge: 10000}),
      cachedApi('/api/compositions', {maxAge: 10000}),
    ]);
    const sourceRows = (index.sources || []).map(item =>
      `${item.path} · rank ${item.rank} · ${String(item.sha256).slice(0, 8)}…`);
    const registeredRows = refs.references.map(item =>
      `${item.name} · ${item.force_field?.name || 'unknown FF'} · ${item.evidence_status}`);
    renderRegistryList('#model-references', [...sourceRows, ...registeredRows], item => String(item));
    renderRegistryList('#model-fragments', frags.fragments, item =>
      `${item.name} · ${item.model_kind || 'fragment'}`);
    renderRegistryList('#model-compositions', comps.compositions, item =>
      `${item.snapshot?.name || item.id} · ${item.validation?.ok ? 'valid' : 'invalid'}`);
    const records = (index.records || []).length;
    const diags = (index.diagnostics || []).length;
    setText($('#model-registry-message'),
      `Indexed ${index.sources?.length || 0} reference sources · ${records} fragment records · ${diags} diagnostics · ${refs.references.length} registered references.`);
  }

  const mappingData = {candidates: []};
  let moleculeEditor = null;
  let moleculeDiagram = null;

  function editorStorageKey(context) {
    if (!context?.molecule_id || !context?.snapshot?.snapshot_sha256) return null;
    return `mapping.v3.${context.molecule_id}.${context.snapshot.snapshot_sha256}`;
  }
  function persistEditor() {
    if (!moleculeEditor) return;
    const key = editorStorageKey(moleculeEditor.context);
    if (key) storage.set(key, moleculeEditor.candidate);
  }

  if ($('#create-candidate')) $('#create-candidate').disabled = true;
  if ($('#generate-automatic')) $('#generate-automatic').disabled = true;

  async function loadMapping(file) {
    if (!file) return null;
    return cachedApi('/api/mappings/' + encodeURIComponent(file), {maxAge: 10000});
  }

  let bondedWorkspace;

  const panels = [];

  document.addEventListener('click', event => {
    if (event.target.id !== 'create-candidate' || !mappingData) return;
    const base = {name: 'New candidate', beads: []};
    ensureMappingPanel();
    panels[0]?.loadData(base);
    setText($('#automatic-message'), 'New candidate ready. Add beads and atom assignments, then save candidate.');
  });

  document.addEventListener('click', async event => {
    if (event.target.id !== 'generate-automatic') return;
    const b = event.target; b.disabled = true;
    try {
      const r = await post('/api/mappings/automatic', {});
      const saved = await post('/api/mappings/drafts', r.candidate);
      invalidateResource('/api/mappings');
      mappingData.candidates.push(saved);
      ensureMappingPanel();
      panels.forEach(p => p.fillOptions());
      panels[0].load(saved.file);
      setText($('#automatic-message'), 'Generated a sugar-first DDM draft: canonical fragments, scaled ring constraints and virtual sites. Review linkage chemistry and screen against AA.');
    } catch (e) { setText($('#automatic-message'), e.message); }
    finally { b.disabled = false; }
  });

  function ensureMappingPanel() {
    if (!panels.length) {
      $('#comparison').replaceChildren();
      panels.push(new MappingPanel({index: 0, mappingData, loadMapping, panels}));
    }
  }

  function editorMessage(message) { setText($('#mapping-editor-status'), message); }
  function editorSelection() { setText($('#mapping-selection-count'), `${moleculeEditor?.selectedAtoms.size || 0} heavy atoms selected`); }

  async function loadMoleculeEditor(moleculeId) {
    if (!moleculeId) { editorMessage('Select a molecule to begin.'); return; }
    const generation = (loadMoleculeEditor.generation || 0) + 1; loadMoleculeEditor.generation = generation;
    if (moleculeDiagram) moleculeDiagram.destroy(); moleculeDiagram = null; moleculeEditor = null;
    editorMessage(`Loading ${moleculeId}…`);
    try {
      const [source, catalogue] = await Promise.all([
        cachedApi('/api/mappings/context?molecule_id=' + encodeURIComponent(moleculeId), {maxAge: 10000}),
        cachedApi('/api/mappings?molecule_id=' + encodeURIComponent(moleculeId) + '&view=summary', {maxAge: 10000}),
      ]);
      if (generation !== loadMoleculeEditor.generation) return;
      if (!source?.context || !source?.scene) { editorMessage('Server did not return a mapping context; reload the page.'); return; }
      const key = editorStorageKey(source.context);
      const recovered = key ? storage.get(key) : null;
      const candidate = recovered?.molecule_snapshot?.snapshot_sha256 === source.context.snapshot.snapshot_sha256
        ? recovered
        : (catalogue.candidates?.[0] ? await loadMapping(catalogue.candidates[0].file) : null);
      moleculeEditor = createEditor(source.context, candidate);
      moleculeDiagram = mountDiagram($('#mapping-editor-diagram'), source.scene, source.context, id => {
        toggleAtom(moleculeEditor, id); persistEditor(); editorSelection();
        moleculeDiagram.update(moleculeEditor.candidate, moleculeEditor.selectedAtoms, moleculeEditor.selectedBeads);
      });
      moleculeDiagram.update(moleculeEditor.candidate, moleculeEditor.selectedAtoms, moleculeEditor.selectedBeads);
      $('#mapping-editor-name').value = moleculeEditor.candidate.name || 'New mapping'; editorSelection();
      editorMessage(`${source.context.name || moleculeId} loaded · ${source.context.atoms.length} atoms · ${source.context.source_quality.bond_order} bond graph`);
      const filter = $('#mapping-candidate-filter');
      filter.replaceChildren(new Option('New local draft', ''));
      for (const item of catalogue.candidates || []) filter.append(new Option(item.name, item.file));
    } catch (error) { editorMessage(error.message); }
  }

  function makeDialog(title, submitText, fields = []) {
    const dialog = document.createElement('dialog'); dialog.setAttribute('aria-label', title);
    const form = document.createElement('form'); form.method = 'dialog';
    const heading = document.createElement('h3'); heading.textContent = title; form.append(heading);
    for (const field of fields) {
      const label = document.createElement('label'); label.textContent = field.label;
      const input = document.createElement('input'); input.name = field.name; input.value = field.value || '';
      label.append(input); form.append(label);
    }
    const actions = document.createElement('div'); actions.className = 'toolbar';
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel';
    cancel.onclick = () => dialog.close('cancel');
    const submit = document.createElement('button'); submit.type = 'submit'; submit.textContent = submitText;
    actions.append(cancel, submit); form.append(actions); dialog.append(form);
    document.body.append(dialog);
    dialog.addEventListener('close', () => dialog.remove(), {once: true});
    dialog.showModal();
    return {dialog, form};
  }

  function setupMoleculeEditorControls() {
    const moleculeSelect = $('#mapping-molecule'); if (!moleculeSelect || moleculeSelect.dataset.ready) return; moleculeSelect.dataset.ready = 'true';
    $('#clear-selection').onclick = () => {
      if (!moleculeEditor) return;
      clearSelection(moleculeEditor); persistEditor(); editorSelection();
      moleculeDiagram?.update(moleculeEditor.candidate, moleculeEditor.selectedAtoms, moleculeEditor.selectedBeads);
    };
    $('#mapping-editor-diagram').addEventListener('click', event => {
      const bead = event.target.closest('[data-bead-name]'); if (!bead || !moleculeEditor) return;
      const name = bead.dataset.beadName;
      if (moleculeEditor.selectedBeads.has(name)) moleculeEditor.selectedBeads.delete(name);
      else moleculeEditor.selectedBeads.add(name);
      persistEditor();
      moleculeDiagram?.update(moleculeEditor.candidate, moleculeEditor.selectedAtoms, moleculeEditor.selectedBeads);
      editorSelection();
    });
    $('#mapping-editor-name').oninput = event => { if (moleculeEditor) { moleculeEditor.candidate.name = event.target.value; moleculeEditor.dirty = true; persistEditor(); } };
    moleculeSelect.onchange = () => loadMoleculeEditor(moleculeSelect.value);
    $('#mapping-candidate-filter').onchange = async event => {
      if (!event.target.value) return loadMoleculeEditor(moleculeSelect.value);
      const candidate = await loadMapping(event.target.value);
      if (!candidate || candidate.molecule_id !== moleculeEditor?.context.molecule_id) return;
      moleculeEditor = createEditor(moleculeEditor.context, candidate);
      moleculeDiagram?.update(moleculeEditor.candidate, moleculeEditor.selectedAtoms, moleculeEditor.selectedBeads);
      $('#mapping-editor-name').value = candidate.name;
    };
    $('#group-into-bead').onclick = () => {
      if (!moleculeEditor?.selectedAtoms.size) return editorMessage('Select one or more heavy atoms first.');
      const modal = makeDialog('Create bead', 'Create bead', [{name: 'name', label: 'Bead name', value: `B${(moleculeEditor.candidate.beads.length + 1).toString().padStart(2, '0')}`}]);
      modal.form.addEventListener('submit', event => {
        event.preventDefault();
        const name = new FormData(modal.form).get('name');
        try {
          const size = moleculeEditor.selectedAtoms.size >= 4 ? 'R' : moleculeEditor.selectedAtoms.size === 3 ? 'S' : 'T';
          const result = groupAtoms(moleculeEditor, moleculeEditor.selectedAtoms, {name, size, type: null});
          if (result?.requiresConfirmation) {
            modal.dialog.close();
            const confirm = makeDialog('Move assigned atoms', 'Confirm move');
            confirm.form.insertAdjacentHTML('afterbegin', `<p>Atoms already belong to ${result.prior.join(', ')}. Move them?</p>`);
            confirm.form.addEventListener('submit', event2 => {
              event2.preventDefault();
              groupAtoms(moleculeEditor, moleculeEditor.selectedAtoms, {name, size, type: null}, {confirmed: true});
              persistEditor();
              moleculeDiagram?.update(moleculeEditor.candidate, moleculeEditor.selectedAtoms, moleculeEditor.selectedBeads);
              editorSelection(); confirm.dialog.close();
            });
            return;
          }
          persistEditor();
          moleculeDiagram?.update(moleculeEditor.candidate, moleculeEditor.selectedAtoms, moleculeEditor.selectedBeads);
          editorSelection(); modal.dialog.close();
        } catch (error) { editorMessage(error.message); }
      });
    };
    $('#suggest-bead').onclick = async () => {
      if (!moleculeEditor?.selectedAtoms.size) return editorMessage('Select atoms before requesting a suggestion.');
      try {
        const result = await post('/api/mappings/suggest-bead', {molecule_id: moleculeEditor.context.molecule_id, molecule_snapshot: moleculeEditor.context.snapshot, atom_ids: [...moleculeEditor.selectedAtoms]});
        setText($('#mapping-suggestion'), result.suggestions?.map(item => `${item.size}/${item.type || 'review'} · ${item.confidence} · ${item.reason}`).join('\n') || result.warnings?.join(' '));
      } catch (error) { editorMessage(error.message); }
    };
    $('#ring-site-preview').onclick = async () => {
      if (!moleculeEditor) return;
      const parents = [...moleculeEditor.selectedBeads];
      if (parents.length !== 3) return editorMessage('Select three beads for TC4 preview.');
      try {
        const result = await post('/api/mappings/ring-site/preview', {molecule_id: moleculeEditor.context.molecule_id, molecule_snapshot: moleculeEditor.context.snapshot, mapping: moleculeEditor.candidate, parents});
        setText($('#mapping-suggestion'), `${result.bead.name} TC4${result.warnings?.length ? ' · warning: ' + result.warnings.map(item => item.message).join(' ') : ''}`);
      } catch (error) { editorMessage(error.message); }
    };
    $('#save-mapping-editor').onclick = async () => {
      if (!moleculeEditor) return;
      try {
        const saved = await post('/api/mappings/drafts', moleculeEditor.candidate);
        editorMessage(`Saved ${saved.name} as a new candidate.`);
        invalidateResource('/api/mappings');
      } catch (error) { editorMessage(error.message); }
    };
    $('#generate-automatic-preview').onclick = async () => {
      if (!moleculeEditor) return;
      const button = $('#generate-automatic-preview'); button.disabled = true;
      try {
        const result = await post('/api/mappings/automatic/preview', {molecule_id: moleculeEditor.context.molecule_id, molecule_snapshot: moleculeEditor.context.snapshot});
        const output = $('#mapping-automatic-preview'); output.hidden = false;
        $('#discard-automatic-preview').hidden = false;
        output.textContent = result.available ? JSON.stringify(result.candidate, null, 2) : `Automatic unavailable: ${(result.reasons || []).join(' ')}`;
      } catch (error) { editorMessage(error.message); }
      finally { button.disabled = false; }
    };
    $('#discard-automatic-preview').onclick = () => { $('#mapping-automatic-preview').hidden = true; $('#discard-automatic-preview').hidden = true; };
  }

  async function loadMoleculeList() {
    const select = $('#mapping-molecule'); if (!select || select.options.length) return;
    const result = await cachedApi('/api/molecules', {maxAge: 10000});
    select.replaceChildren();
    for (const item of result.molecules || []) select.append(new Option(item.name || item.id, item.id));
    if (select.options.length) { select.value = select.options[0].value; await loadMoleculeEditor(select.value); }
  }

  async function mount(id = 'mappings') {
    const section = $('#' + id); section.setAttribute('aria-busy', 'true');
    if (id === 'mappings' && !panels.length) setText($('#comparison'), 'Loading mapping catalogue…');
    try {
      const [catalogue, legacy] = await Promise.all([
        cachedApi('/api/mappings?view=summary', {maxAge: 10000}),
        cachedApi('/api/mappings/context'),
      ]);
      Object.assign(mappingData, catalogue, legacy);
      if (id === 'mappings') { setupMoleculeEditorControls(); await loadMoleculeList(); }
      if ($('#create-candidate')) $('#create-candidate').disabled = false;
      if ($('#generate-automatic')) $('#generate-automatic').disabled = false;
      if (id === 'bonded') {
        bondedWorkspace ||= setupBondedWorkspace(mappingData, {onFit, loadMapping});
        await bondedWorkspace.mount();
      } else {
        loadModelRegistry().catch(error => setText($('#model-registry-message'), `Registry unavailable: ${error.message}`));
        if (mappingData.candidates.length || panels.length) {
          ensureMappingPanel();
          panels.forEach(panel => panel.fillOptions());
        } else setText($('#comparison'), 'No mapping candidates are available.');
      }
    } catch (error) {
      setText(id === 'bonded' ? $('.bonded-panel-message') : $('#comparison'), `Could not load mappings: ${error.message}`);
    } finally { section.setAttribute('aria-busy', 'false'); }
  }
  return {mount};
}