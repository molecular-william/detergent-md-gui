import { $, storage, setText, post, cachedApi, invalidateResource, guarded, DROP, api, notice, panelIds } from './shared.js';
import { setupBondedWorkspace } from './bonded.js';
import { createEditor, toggleAtom, clearSelection, clearMapping, groupAtoms, addBead, renameBead, removeBead } from './mapping-state.js';
import { mountOverlay3d } from './mapping-ngl.js';

// Candidate edits and local drafts stay inside this workspace.
export function createMappings() {
  const mappingData = {candidates: [], bead_types: []};
  let moleculeEditor = null;
  let moleculeOverlay = null;

  function editorStorageKey(context) {
    if (!context?.molecule_id || !context?.snapshot?.snapshot_sha256) return null;
    return `mapping.v3.${context.molecule_id}.${context.snapshot.snapshot_sha256}`;
  }
  function persistEditor() {
    if (!moleculeEditor) return;
    const key = editorStorageKey(moleculeEditor.context);
    if (key) storage.set(key, moleculeEditor.candidate);
  }

  // Whether the 3D view numbers the heavy atoms. One key rather than one per molecule: it is a reading aid, so it
  // follows the reader rather than the molecule, and a molecule switch must not silently turn it back on.
  function atomLabelsWanted() { return storage.get('mappingAtomLabels', true) !== false; }
  function setAtomLabels(visible) {
    storage.set('mappingAtomLabels', visible);
    // The overlay redraws the structure it already holds, so this costs no request and the second half of the
    // panel's own view does not blink.
    if (moleculeOverlay) moleculeOverlay.setLabels(visible);
  }
  function restoreAtomLabels() {
    const box = $('#mapping-atom-labels');
    const wanted = atomLabelsWanted();
    if (box) box.checked = wanted;
    // Called before the first draw, so this only records the choice; the overlay applies it when the structure
    // arrives. That is what makes a reloaded page come up numbered, or not, without a second request.
    if (moleculeOverlay) moleculeOverlay.setLabels(wanted);
    return wanted;
  }

  async function loadMapping(file) {
    if (!file) return null;
    if (file.startsWith('composition:')) {
      const detail = await cachedApi('/api/cg-models/composition/' + encodeURIComponent(file.slice('composition:'.length)), {maxAge: 10000});
      const mapping = detail.mapping || {};
      const atoms = (mapping.beads || []).map((bead, index) => ({id: index + 1, name: bead.name, xyz: [index * 0.1, 0, 0]}));
      return {...mapping, file, molecule: {atoms, bonds: (mapping.connections || []).map(([a, b]) => ({a: (mapping.beads || []).findIndex(item => item.name === a) + 1, b: (mapping.beads || []).findIndex(item => item.name === b) + 1}))}, composition: detail};
    }
    return cachedApi('/api/mappings/' + encodeURIComponent(file), {maxAge: 10000});
  }

  let bondedWorkspace;

  function renderWarnings() {
    // A candidate can be mapped and still be an admission -- a ring the templates do not cover, or a
    // fragment that could not be typed by chemistry. The interface says so instead of leaving it in JSON.
    const target = $('#mapping-editor-warnings');
    if (!target) return;
    const warnings = moleculeEditor?.candidate?.warnings || [];
    target.textContent = warnings.length ? `Unvalidated mapping: ${warnings.join(' ')}` : '';
    target.hidden = !warnings.length;
  }
  function editorMessage(message) { setText($('#mapping-editor-status'), message); renderWarnings(); }
  function editorSelection() { setText($('#mapping-selection-count'), `${moleculeEditor?.selectedAtoms.size || 0} heavy atoms selected`); }

  function updateBeadField(index, field, value) {
    const bead = moleculeEditor?.candidate.beads[index];
    if (!bead) return;
    if (field === 'name') {
      try { renameBead(moleculeEditor, bead.name, value); }
      catch (error) { editorMessage(error.message); return; }
    } else if (field === 'atoms') {
      if (bead.virtual_site) bead.virtual_site.parents = value.trim().split(/[\s,]+/).filter(Boolean);
      else bead.atoms = value.trim() ? value.trim().split(/[\s,]+/).map(Number) : [];
    } else bead[field] = value;
    moleculeEditor.dirty = true;
    persistEditor(); editorSelection(); validateEditor();
  }

  function selectBead(name) {
    // One row at a time, and it is what the buttons below the table act on. Clicking the selected row again drops
    // the selection, so a reader is never stuck holding one they cannot put down.
    if (!moleculeEditor) return;
    moleculeEditor.selectedBead = moleculeEditor.selectedBead === name ? null : name;
    persistEditor(); renderEditor();
  }

  function updateBeadButtons() {
    const remove = $('#delete-selected-bead');
    if (remove) remove.disabled = !moleculeEditor?.selectedBead;
  }

  let editorGeneration = 0;

  function renderBeadRows() {
    const table = $('#mapping-bead-rows');
    if (!table) return;
    table.replaceChildren();
    for (const [index, bead] of (moleculeEditor?.candidate.beads || []).entries()) {
      const row = document.createElement('tr');
      const chosen = moleculeEditor?.selectedBead === bead.name;
      row.classList.toggle('selected', chosen);
      row.setAttribute('aria-selected', String(chosen));
      row.addEventListener('click', () => selectBead(bead.name));
      const fields = ['name', 'size', 'type', 'atoms'];
      for (const field of fields) {
        const cell = document.createElement('td');
        const input = field === 'size' || field === 'type' ? document.createElement('select') : document.createElement('input');
        input.setAttribute('aria-label', `Bead ${index + 1} ${field}`);
        if (field === 'size') for (const size of ['R', 'S', 'T']) input.append(new Option(size, size));
        if (field === 'type') {
          input.append(new Option('Choose type', ''));
          for (const item of mappingData.bead_types || []) input.append(new Option(item.type, item.type));
          if (bead.type && !Array.from(input.options).some(option => option.value === bead.type)) input.append(new Option(`${bead.type} · unsupported`, bead.type));
          const selected = (mappingData.bead_types || []).find(item => item.type === bead.type);
          input.title = selected?.description || bead.type || 'Choose a Martini bead type';
        }
        if (field === 'atoms') input.className = 'atoms-input';
        input.value = field === 'atoms' && bead.virtual_site ? bead.virtual_site.parents.join(' ') : field === 'atoms' ? bead.atoms.join(' ') : (bead[field] || '');
        if (bead.virtual_site && ['size', 'type'].includes(field)) input.disabled = true;
        input.addEventListener(field === 'size' || field === 'type' ? 'change' : 'input', () => updateBeadField(index, field, input.value));
        cell.append(input); row.append(cell);
      }
      const cell = document.createElement('td');
      const removeButton = document.createElement('button');
      removeButton.type = 'button'; removeButton.className = 'secondary'; removeButton.textContent = '×';
      removeButton.setAttribute('aria-label', `Remove bead ${bead.name}`);
      removeButton.onclick = () => {
        try { removeBead(moleculeEditor, bead.name); renderEditor(); }
        catch (error) { editorMessage(error.message); }
      };
      cell.append(removeButton); row.append(cell); table.append(row);
    }
  }

  function renderValidation(result) {
    if (!result) return;
    setText($('#mapping-validation-summary'), `${result.covered}/${result.heavy_atoms} heavy atoms · ${result.bead_count} beads · nominal ${result.represented_atoms} atoms · difference ${result.mismatch > 0 ? '+' : ''}${result.mismatch}`);
    const issues = $('#mapping-validation-issues'); issues.replaceChildren();
    for (const item of result.issues || []) { const li = document.createElement('li'); li.textContent = item.message; issues.append(li); }
    if (!result.issues?.length) { const li = document.createElement('li'); li.textContent = 'Structural checks passed. Bead chemistry and physical behaviour still need review.'; issues.append(li); }
    const save = $('#save-mapping-editor');
    if (save) save.disabled = !result.can_save || !!result.duplicate_file;
    setText($('#automatic-message'), result.duplicate_file ? `This mapping already exists as ${result.duplicate_file}. Change the assignments before saving a new draft.` : '');
  }

  async function validateEditor() {
    if (!moleculeEditor) return;
    try {
      // One check per editor: a slower earlier answer is not rendered over a newer one.
      const result = await guarded('mapping-validation', () => post('/api/mappings/validate', moleculeEditor.candidate));
      if (result === DROP) return;
      renderValidation(result);
    } catch (error) { editorMessage(error.message); }
  }

  function renderEditor() {
    if (!moleculeEditor) return;
    $('#mapping-editor-name').value = moleculeEditor.candidate.name || 'New mapping';
    renderBeadRows(); editorSelection(); updateBeadButtons();
    // The 3D view redraws only when the assignment itself changed, so this costs a request on an edit and nothing
    // on a refresh -- which is what lets it be called from every render rather than from the places that edit.
    if (moleculeOverlay) moleculeOverlay.update(moleculeEditor.candidate);
    // A local draft has nothing to overwrite or delete; both buttons act on a saved candidate. Saying so costs one
    // attribute and saves the report this panel keeps producing: a control that does nothing when pressed, with no
    // reason anywhere on the page. A saved candidate has to be scoped to this molecule and built from this snapshot
    // before it is offered at all, so "no candidate" is a normal state, not a broken one.
    const saved = !!moleculeEditor.candidate.file;
    for (const id of ['#delete-mapping', '#save-mapping-inplace']) {
      const button = $(id); if (button) button.disabled = !saved;
    }
    const remove = $('#delete-mapping');
    if (remove) {
      remove.title = saved
        ? `Delete the saved candidate ${moleculeEditor.candidate.file}`
        : 'Nothing to delete yet: the editor holds a local draft. Save it as a new candidate first.';
    }
    persistEditor();
    validateEditor();
  }

  async function loadMoleculeEditor(moleculeId) {
    if (!moleculeId) { editorMessage('Select a molecule to begin.'); return; }
    const generation = ++editorGeneration;
    // The editor is the two panels a molecule load replaces -- the bead table and the drawn overlay. Until the load
    // answers, they still hold the previously selected molecule, so the workspace says it is busy rather than
    // letting a reader (or a test) act on a model that is no longer selected.
    const workspace = $('.molecule-mapping-workspace');
    workspace?.setAttribute('aria-busy', 'true');
    moleculeEditor = null;
    // A stage holds a WebGL context and browsers cap how many exist, so the 3D view is disposed before this one is replaced.
    if (moleculeOverlay) moleculeOverlay.destroy(); moleculeOverlay = null;
    editorMessage(`Loading ${moleculeId}…`);
    try {
      // Keyed by molecule: a switch supersedes the load in flight, so the state assignment
      // below only happens for the molecule that is still selected.
      const loaded = await guarded(`molecule-editor:${moleculeId}`, () => Promise.all([
        cachedApi('/api/mappings/context?molecule_id=' + encodeURIComponent(moleculeId), {maxAge: 10000}),
        cachedApi('/api/mappings?molecule_id=' + encodeURIComponent(moleculeId) + '&view=summary', {maxAge: 10000}),
      ]));
      if (loaded === DROP) return;
      const [source, catalogue] = loaded;
      if (!source?.context) { editorMessage('Server did not return a mapping context; reload the page.'); return; }
      mappingData.candidates = catalogue.candidates || [];
      mappingData.bead_types = source.bead_types || catalogue.bead_types || [];
      const key = editorStorageKey(source.context);
      const recovered = key ? storage.get(key) : null;
      const candidate = recovered?.molecule_snapshot?.snapshot_sha256 === source.context.snapshot.snapshot_sha256
        ? recovered
        : (catalogue.candidates?.[0] ? await loadMapping(catalogue.candidates[0].file) : null);
      moleculeEditor = createEditor(source.context, candidate);
      // A bead ticked in the overlay is the same edit as one picked before it: the callback calls the editor rather
      // than keeping a selection of its own.
      moleculeOverlay = mountOverlay3d($('#mapping-editor-overlay3d'), source.context, id => {
        toggleAtom(moleculeEditor, id); persistEditor(); editorSelection();
      });
      // The reader's choice of numbers is restored onto the fresh overlay before the first draw, so a reloaded page
      // comes up the way it was left without a second request to undo a default.
      restoreAtomLabels();
      renderEditor();
      
      editorMessage(`${source.context.name || moleculeId} loaded · ${source.context.atoms.length} atoms · ${source.context.source_quality.bond_order} bond graph`);
      const filter = $('#mapping-candidate-filter');
      // A molecule with no saved candidate is a normal state, not a broken one: a candidate is offered only when it
      // is scoped to this molecule and built from this snapshot. Say so here, where the choice is made, instead of
      // leaving a bare "New local draft" that looks like the list failed to load.
      filter.replaceChildren(new Option(catalogue.candidates?.length
        ? 'New local draft'
        : 'New local draft — no saved mapping for this molecule yet', ''));
      for (const item of catalogue.candidates || []) filter.append(new Option(item.name, item.file));
      if (candidate?.file) filter.value = candidate.file;
    } catch (error) { editorMessage(error.message); }
    finally { if (generation === editorGeneration) workspace?.setAttribute('aria-busy', 'false'); }
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
    $('#mapping-editor-name').oninput = event => { if (moleculeEditor) { moleculeEditor.candidate.name = event.target.value; moleculeEditor.dirty = true; persistEditor(); validateEditor(); } };
    moleculeSelect.onchange = () => loadMoleculeEditor(moleculeSelect.value);
    $('#mapping-candidate-filter').onchange = async event => {
      if (!event.target.value) return loadMoleculeEditor(moleculeSelect.value);
      const candidate = await loadMapping(event.target.value);
      if (!candidate || candidate.molecule_id !== moleculeEditor?.context.molecule_id) return;
      moleculeEditor = createEditor(moleculeEditor.context, candidate);
      renderEditor();
    };
    $('#add-bead').onclick = () => {
      if (!moleculeEditor) { editorMessage('Select a molecule to begin.'); return; }
      try { addBead(moleculeEditor); persistEditor(); renderEditor(); }
      catch (error) { editorMessage(error.message); }
    };
    $('#delete-selected-bead').onclick = () => {
      const name = moleculeEditor?.selectedBead;
      if (!name) { editorMessage('Select a bead row first.'); return; }
      try { removeBead(moleculeEditor, name); persistEditor(); renderEditor(); }
      catch (error) { editorMessage(error.message); }
    };
    // The numbering toggle beside the bead table. It redraws nothing and fetches nothing: the atoms the numbers
    // hang on are already in the view, so this only adds or removes the representation drawn over them.
    restoreAtomLabels();
    const atomLabels = $('#mapping-atom-labels');
    if (atomLabels) atomLabels.onchange = () => setAtomLabels(atomLabels.checked);
    $('#clear-all-mapping').onclick = () => {
      if (!moleculeEditor || !window.confirm('Remove every bead assignment from this local draft?')) return;
      clearMapping(moleculeEditor); renderEditor(); editorMessage('All bead assignments cleared from the local draft.');
    };
    $('#delete-mapping').onclick = async () => {
      const file = moleculeEditor?.candidate?.file;
      if (!file) return editorMessage('This is a local draft; there is no saved mapping to delete.');
      // The rule the route implements, stated before it acts: a mapping's bond interactions go with it unless another
      // saved mapping still carries the same content hash, and the fit jobs and staged frames built for it go as well.
      // The wording this replaced said the bonded states were *not* deleted, which was the opposite of what
      // `mappings.delete_draft` does -- and it is the one sentence a reader has before an irreversible click.
      if (!window.confirm(`Delete ${file}?\n\nIts bond interactions are deleted with it, along with the fit jobs and `
                          + 'staged frames built for it. Runs that already recorded those terms keep them.')) return;
      try {
        const answer = await api('/api/mappings/drafts/' + encodeURIComponent(file), {method: 'DELETE'});
        invalidateResource('/api/mappings');
        await loadMoleculeEditor(moleculeSelect.value);
        // What went with it is the route's report, not a guess: a shared copy keeps the revisions and the answer names it.
        const report = (answer && answer.parameterization) || {};
        const removed = (report.revisions || []).length;
        const kept = Array.isArray(report.retained_by) ? report.retained_by : [];
        notice(kept.length ? `Mapping deleted; its bond interactions are kept, held by ${kept.join(', ')}.`
          : removed ? `Mapping deleted, and its ${removed === 1 ? '1 bond interaction revision'
                                                            : `${removed} bond interaction revisions`} with it.`
          : 'Mapping deleted.');
      } catch (error) { editorMessage(error.message); }
    };
    $('#save-mapping-inplace').onclick = async () => {
      if (!moleculeEditor) return;
      try {
        const result = await post('/api/mappings/drafts', {...moleculeEditor.candidate, in_place: true});
        invalidateResource('/api/mappings');
        await loadMoleculeEditor(moleculeSelect.value);
        notice(`Mapping saved in place as ${result.file}.`);
      } catch (error) { editorMessage(error.message); }
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
              renderEditor(); confirm.dialog.close();
            });
            return;
          }
          renderEditor(); modal.dialog.close();
        } catch (error) { editorMessage(error.message); }
      });
    };
    $('#save-mapping-editor').onclick = async () => {
      if (!moleculeEditor) return;
      try {
        const saved = await post('/api/mappings/drafts', moleculeEditor.candidate);
        mappingData.candidates = [...mappingData.candidates.filter(item => item.file !== saved.file), saved];
        $('#mapping-candidate-filter').append(new Option(saved.name, saved.file));
        $('#mapping-candidate-filter').value = saved.file;
        moleculeEditor = createEditor(moleculeEditor.context, saved);
        renderEditor();
        editorMessage(`Saved ${saved.name} as a new candidate.`);
        invalidateResource('/api/mappings');
      } catch (error) {
        editorMessage(error.message);
        // One content identity is one model: the store refused a second copy and named the mapping that holds it, so
        // open that one rather than leaving the reader with a sentence and no way to reach what it names.
        const select = $('#mapping-candidate-filter');
        if (error.status === 409 && error.existing && [...select.options].some(option => option.value === error.existing)) {
          select.value = error.existing;
          select.dispatchEvent(new Event('change'));
        }
      }
    };
    $('#generate-automatic').onclick = async () => {
      if (!moleculeEditor) return;
      const button = $('#generate-automatic'); button.disabled = true;
      try {
        const result = await post('/api/mappings/automatic/preview', {molecule_id: moleculeEditor.context.molecule_id, molecule_snapshot: moleculeEditor.context.snapshot});
        if (!result.available) throw new Error(`Automatic candidate unavailable: ${(result.reasons || []).join(' ')}`);
        moleculeEditor.candidate = result.candidate;
        renderWarnings();
        clearSelection(moleculeEditor); renderEditor();
        editorMessage('Generated an automatic candidate for local review.');
      } catch (error) { editorMessage(error.message); }
      finally { button.disabled = false; }
    };
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
    try {
      const [catalogue, legacy, cgCatalogue] = await Promise.all([
        cachedApi('/api/mappings?view=summary', {maxAge: 10000}),
        cachedApi('/api/mappings/context'),
        cachedApi('/api/cg-models?view=summary', {maxAge: 10000}),
      ]);
      Object.assign(mappingData, catalogue, legacy);
      mappingData.candidates = [...(mappingData.candidates || []), ...(cgCatalogue.models || []).filter(item => item.kind === 'composition').map(item => ({file: `composition:${item.id}`, name: `${item.name} · Composition`, status: item.status}))];
      if (id === panelIds()['bead-assignment']) { setupMoleculeEditorControls(); await loadMoleculeList(); }
      if (id === panelIds()['bond-interactions']) {
        bondedWorkspace ||= setupBondedWorkspace(mappingData, {loadMapping});
        await bondedWorkspace.mount();
      }
    } catch (error) {
      setText(id === panelIds()['bond-interactions'] ? $('.bonded-panel-message') : $('#mapping-editor-status'), `Could not load mappings: ${error.message}`);
    } finally { section.setAttribute('aria-busy', 'false'); }
  }

  async function openBondedModel(model) {
    // Hand a saved composition to the CG Bond Interactions tab. It is the same catalog the
    // tab's own selector reads, so the model is selected rather than a second copy injected.
    if (!model || model.id === undefined) return false;
    await mount('bonded');
    return bondedWorkspace ? bondedWorkspace.select(`composition:${model.id}`) : false;
  }
  return {mount, openBondedModel};
}
