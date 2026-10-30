import { $, $$, storage, setText, notice, api, post, cachedApi, invalidateResource, guarded, DROP, panelIds } from './shared.js';
import { createGpuDevice } from './gpu-device.js';

//: `{workspace slug: extension}` -- the panels installed features bring for their own workspaces.
const extensions = new Map();

/**
 * Register the New run panel for one workspace a feature owns.
 *
 * The engine's panel below serves the single-molecule workspaces. A feature whose workspace has a form of its own
 * registers here when its module loads (`Feature.extension_modules`), and `createNewRun` uses
 * `extension.create(context)` instead of the engine panel when the page's workspace matches. The extension then
 * owns the form end to end -- the hook points the engine would otherwise reach itself:
 *
 *   * build/sync: read and write the controls the server rendered for it, and keep its review summary in step;
 *   * payload: turn the form into the job body its own adapter validates and queue it;
 *   * run-type change: a feature form with a run-type choice reacts to it (a form for one run type has none);
 *   * mount: fetch what the form needs and mark the panel ready.
 *
 * `context` is `{form, selectTab, refreshJobs, refreshStorage}`; the return value is the panel interface
 * (`mount`, `cloneRun`, `clearDeletedClone`, `setCloneSource`, `openComposition`).
 */
export function registerNewRunExtension(extension) {
  if (!extension || typeof extension !== 'object' || typeof extension.create !== 'function' || !extension.workspace) {
    throw new TypeError('registerNewRunExtension needs an object with {workspace, create(context)}');
  }
  if (extensions.has(extension.workspace) && extensions.get(extension.workspace) !== extension) {
    throw new Error(`two New run extensions claim the ${extension.workspace} workspace`);
  }
  extensions.set(extension.workspace, extension);
}

/**
 * Fill the review's detail host (`#readiness`) with one readiness answer's checks and blockers.
 *
 * That host is shell DOM: both New run panels report into it, on their own page. Its single writer is the engine's
 * panel module, so a feature's panel calls this rather than binding the host itself -- two modules that write one
 * rendered host is what `packages/core/tests/integration/test_rendered_hosts.py` fails on.
 */
export function writeReadiness(checks, blockers) {
  const panel = $('#readiness');
  panel.replaceChildren();
  for (const check of checks || []) {
    const row = document.createElement('div'); row.className = 'ready-check';
    const title = document.createElement('strong');
    title.textContent = `${check.ready ? 'Present' : 'Missing'} · ${check.label}`;
    const path = document.createElement('code'); path.textContent = check.path;
    const detail = document.createElement('p'); detail.className = 'hint'; detail.textContent = check.detail;
    row.append(title, path, detail); panel.append(row);
  }
  const list = document.createElement('ul');
  for (const blocker of blockers || []) { const li = document.createElement('li'); li.textContent = blocker; list.append(li); }
  panel.append(list);
}

async function preselectBondedMapping(file) {
  if (!file) return false;
  // The list is a fetch away and the panel mounts on the tab switch; waiting for the option is what keeps this
  // from selecting before there is anything to select.
  for (let attempt = 0; attempt < 120; ++attempt) {
    const picker = document.querySelector('#bonded-mapping-select');
    if (picker && [...picker.options].some(option => option.value === file)) {
      if (picker.value !== file) {
        picker.value = file;
        picker.dispatchEvent(new Event('change', {bubbles: true}));
      }
      return true;
    }
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  return false;
}

// Owns the persisted run form, inherited settings, and readiness checks.
//
// The panel is chosen on first use, not here. A feature's extension module is a dynamic import `boot` starts before
// it creates the panels, so it may finish registering after this factory has returned; "registered before any panel
// mounts" is the promise, not "before any panel is created". Every method resolves the panel on its first call.
export function createNewRun({ selectTab, refreshJobs, refreshStorage }) {
  const context = { form: $('#run-form'), selectTab, refreshJobs, refreshStorage };
  // The door's own address (`?mapping_candidate=`) is this module's to apply, not the New run panel's: a cold load
  // can open Bond Interactions directly, and on that page the New run panel is never mounted. The path is compared
  // with the sub-tab's own href -- the same source `bondedPanelHref` reads -- so the two cannot name different panels.
  const doorTab = document.querySelector(`nav.subtabs [data-tab="${panelIds()['bond-interactions']}"]`);
  const doorHref = doorTab?.getAttribute('href') || '';
  const doorMapping = doorHref && location.pathname === doorHref
    ? new URLSearchParams(location.search).get('mapping_candidate') : '';
  if (doorMapping) preselectBondedMapping(doorMapping);
  // Which form this is decided by the workspace the page was opened in, not by what is on it. The template renders
  // one fieldset or the other, and neither is a subset of the other: a feature form has no `run_type`, no `method`
  // and no reference select at all, so every AA statement below would throw on its first `form.elements.<name>`.
  // The extension is resolved here, above them, so the two panels cannot read each other's fields by accident.
  let panel = null;
  // The rendered workspace, not the URL: the front door `/` renders one without naming it in the path, so a path
  // segment would say "" there and build the engine form inside a feature's markup.
  const workspace = document.body.dataset.workspace || location.pathname.split('/').filter(Boolean)[0] || '';
  const resolve = () => panel || (panel = extensions.has(workspace)
    ? extensions.get(workspace).create(context)
    : createEngineNewRun(context));
  const delegate = name => (...args) => resolve()[name](...args);
  return { mount: delegate('mount'), cloneRun: delegate('cloneRun'), clearDeletedClone: delegate('clearDeletedClone'),
           setCloneSource: delegate('setCloneSource'), openComposition: delegate('openComposition') };
}

// The engine's own panel: the persisted form of the single-molecule workspaces.
function createEngineNewRun({ form, selectTab, refreshJobs, refreshStorage }) {
  const AA_FIELDS = ['aa_nvt_ps','aa_npt_ps','aa_production_ps','temperature_k','pressure_bar','output_interval_ps','box_nm','aa_seed','mdrun_ntomp','mdrun_ranks','mdrun_nb','mdrun_pme'];
  // The device is a setting of *this host*, not of the AA reference a run inherits: a reference run's GPU must not
  // be locked onto a new run, so this key is deliberately not in AA_FIELDS. It still has to travel as a setting
  // when a run is cloned, which is what this list is for.
  const GPU_FIELDS = ['mdrun_gpu'];
  const CG_FIELDS = ['cg_equil_ps','cg_production_ps','sasa_probe_nm','cg_seed'];
  //: The profile is the run type's own (`protocol.profile_for_run_type`): the panel offers no choice, sends no key, and
  //: asks `/api/defaults` and `/api/readiness` without one, so the durations it shows and the profile the run is
  //: stamped with come from one answer rather than from a control the panel would have to keep in step.
  // Persist all controls, including disabled values inherited from a reference.
  function formValues() { return Object.fromEntries([...form.elements].filter(el=>el.name).map(el=>[el.name,el.value])); }
  function saveForm() { storage.set('form',formValues()); }
  let referenceRecords = [], referenceGeneration = 0, lockedReference = null;
  let referencesLoaded=false, mappingsLoaded=false, mounted=false, mounting=null;
  // The shared cache drops a resource when something changes it elsewhere; these flags
  // remember that this module already fetched it, so they have to drop with it. Saving a
  // mapping draft in the Mappings workspace was the case that bit: the New-run
  // dropdown kept offering the list it had fetched before the save.
  document.addEventListener('dashboard:resources-changed', event => {
    const prefix = event.detail?.prefix || '';
    if (prefix.startsWith('/api/references')) { referencesLoaded = false; referenceRecords = []; }
    if (prefix.startsWith('/api/mappings')) mappingsLoaded = false;
  });
  let manualAA = storage.get('manual-aa-settings', {});
  let restoreManualAA=!!storage.get('form',{}).reference_run_id;
  function setCloneSource(id, message='') {
    form.elements.clone_of.value=id;
    setText($('#clone-notice'),message || (id ? `Cloning ${id}. Change settings below before starting.` : ''));
    $('#leave-clone').hidden=!id;
    storage.set('form',formValues());
  }
  async function validateCloneSource() {
    const id=form.elements.clone_of.value;
    if(!id)return true;
    try { await api(`/api/jobs/${encodeURIComponent(id)}`); }
    catch(error) {
      if(form.elements.clone_of.value!==id)return false;
      if(error.status!==404)throw error;
      setCloneSource('', `Clone source ${id} is no longer available. Your settings are kept; start a new run when ready.`);
      return false;
    }
    return form.elements.clone_of.value===id;
  }
  $('#leave-clone').onclick=()=>setCloneSource('', 'Your settings are kept for a new run.');
  let moleculeRecords = [], moleculesGeneration = 0;
  function showMolecule(record) {
    const panel=$('#molecule-details'); panel.replaceChildren();
    setText($('#run-molecule-summary'), record?.name || 'Select a molecule');
    setText($('#run-directory-summary'), record?.path || '—');
    if(!record){panel.textContent='Select an available molecule directory. Missing saved selections must be replaced explicitly.';return;}
    const title=document.createElement('strong'); title.textContent=record.valid?'Input files consistent':'Input files need attention'; panel.append(title);
    const info=document.createElement('p'); info.className='hint';
    info.textContent=record.valid?`${record.atom_count} atoms · ${record.metadata.force_field} · water: ${record.metadata.water_model} · charge: ${record.metadata.net_charge}`:record.path;
    panel.append(info);
    const list=document.createElement('ul');
    for(const name of Object.keys(record.sha256)){
      const item=document.createElement('li'); item.textContent=`${name} · ${record.sha256[name]?'present':'missing or unreadable'}`; list.append(item);
    }
    for(const issue of (record.capabilities?.[form.elements.run_type.value]?.blockers || record.blockers)){const item=document.createElement('li'); item.textContent=issue;list.append(item);}
    panel.append(list);
    if(record.inputs?.coordinate_format==='pdb'){
      const note=document.createElement('p'); note.className='hint';
      note.textContent='PDB → GRO automatically before simulation. The original PDB is preserved.'; panel.append(note);
    }
    if(record.metadata?.generated){
      const note=document.createElement('p'); note.className='hint';
      note.textContent=`metadata.json generated automatically. ${record.metadata.provenance}`; panel.append(note);
    }
  }
  async function loadMolecules() {
    const select=form.elements.molecule_id;
    ++readinessGeneration; $('#start-run').disabled=true;
    const chosen=select.value || savedForm?.molecule_id || savedForm?.detergent || 'DDM';
    const result=await guarded('molecules', () => cachedApi('/api/molecules',{maxAge:10000}));
    if(result===DROP)return;
    moleculeRecords=result.molecules;
    select.replaceChildren(new Option('Select a molecule directory',''));
    for(const record of moleculeRecords) select.append(new Option(`${record.name} · ${record.path}${record.valid?'':' · needs attention'}`,record.id));
    if(chosen&&!moleculeRecords.some(record=>record.id===chosen)) select.append(new Option(`Unavailable directory · ${chosen}`,chosen));
    select.value=chosen;
    showMolecule(moleculeRecords.find(record=>record.id===select.value));
    form.elements.detergent.value=select.value;
  }
  function syncRunSummary() {
    const runType=form.elements.run_type.value;
    const aaOnly=runType==='aa_only';
    const compositionOnly=runType==='cg_composition';
    const textFor=(field, fallback)=>field?.selectedOptions?.[0]?.textContent || fallback;
    setText($('#run-type-summary'), aaOnly?'AA-only run':'AA–CG run');
    setText($('#run-aa-summary'), aaOnly?'New AA reference':textFor(form.elements.reference_run_id,'New AA reference'));
    setText($('#run-mapping-summary'), aaOnly?'Not needed for AA-only':textFor(form.elements.mapping_candidate,'Select a mapping'));
    // Fitting is the run type's now (D1), not a per-run intent: an AA–CG run consumes its model's parameterization
    // when the mapping has one and fits in stage 3 when it does not (D5), a composition carries its own bonded
    // state, and an AA-only run never fits. There is no per-run state or workflow left to report, so this row says
    // which of those applies -- and for an AA–CG run it says what the `02 · CG MODEL` card above it describes,
    // rather than the flat "fitted by the run" the row used to claim for every run.
    //
    // The answer is read through `modelAnswer`, not held here: a mapping change makes the previous answer no answer
    // at all, and this row is refreshed on the picker's own `change` -- before the new readiness request is sent --
    // so reading a state without checking whose it is would print the previous mapping's model here.
    const choosingModel = form.elements.run_type.value==='aa_cg' && !!form.elements.mapping_candidate.value;
    const model = choosingModel ? modelAnswer() : null;
    setText($('#run-bonded-summary'), aaOnly?'Not needed'
      :compositionOnly?'From the composition'
      :model?.parameterized?'Used as-is · this run does not re-fit'
      :model?'Stage 3 fits it during the run'
      :choosingModel?'Not read yet — readiness has not answered for this mapping'
      :'Fitted from the AA reference by the run');
    const temp=form.elements.temperature_k.value || '—';
    const aa=form.elements.aa_production_ps.value || '—';
    const cg=form.elements.cg_production_ps.value || '—';
    const protocol=`${temp} K · ${form.elements.pressure_bar.value||'—'} bar · NVT ${form.elements.aa_nvt_ps.value||'—'} / NPT ${form.elements.aa_npt_ps.value||'—'} / production ${aa} ps`;
    setText($('#run-settings-summary'), aaOnly?protocol:`${protocol} · CG ${cg} ps`);
  }
  function syncRunType() {
    const runType=form.elements.run_type.value;
    const aaOnly=runType==='aa_only';
    const compositionOnly=runType==='cg_composition';
    $('#cg-inputs').classList.toggle('hidden',aaOnly);
    $$('.cg-setting').forEach(label=>label.classList.toggle('hidden',aaOnly));
    $('#execution-title').textContent=aaOnly?'AA run settings':compositionOnly?'CG composition settings':'Execution and CG inputs';
    setText($('#run-type-help'), aaOnly?'Standalone AA execution is selected. CG mapping and bonded controls are not needed.':compositionOnly?'Run a saved composition through CG simulation, assessment, and CG-only SASA.':'Choose the workflow before selecting CG-specific inputs.');
    $('#cg-inputs').querySelectorAll('input,select,button').forEach(control=>{control.disabled=aaOnly;});
    $$('.cg-setting').forEach(label=>label.querySelectorAll('input,select,button').forEach(control=>{control.disabled=aaOnly;}));
    applyReferenceSettings(aaOnly?null:referenceRecords.find(r=>r.id===form.elements.reference_run_id.value));
    $('#start-run').textContent=aaOnly?'Start AA run':compositionOnly?'Start CG composition run':'Start AA–CG run';
    $('#molecule-panel').classList.toggle('hidden', compositionOnly);
    $('#composition-run-selector').classList.toggle('hidden', !compositionOnly);
    $('#run-mapping').closest('label').classList.toggle('hidden', compositionOnly);
    $('#reference-run').closest('label').classList.toggle('hidden', compositionOnly);
    form.elements.molecule_id.disabled = compositionOnly;
    form.elements.molecule_id.required = !compositionOnly;
    form.elements.composition_id.disabled = !compositionOnly;
    form.elements.composition_id.required = compositionOnly;
    showMolecule(moleculeRecords.find(record=>record.id===form.elements.molecule_id.value));
    renderModelCard(modelState);
    if(mounted)loadStageDefaults().catch(error=>setText($('#defaults-source'),error.message));
    syncRunSummary();
    storage.set('form',formValues());
    refreshReadiness();
  }
  async function updateMolecule() {
    const record=moleculeRecords.find(record=>record.id===form.elements.molecule_id.value);
    form.elements.detergent.value=record?.id || '';
    form.elements.mapping_candidate.value='';
    showMolecule(record);
    loadReferences().catch(error=>setText($('#reference-help'),error.message));
    try { await loadRunMappings(); }
    catch (error) { setText($('#readiness'), error.message); }
    storage.set('form',formValues());
    refreshReadiness();
  }
  $('#refresh-molecules').onclick=()=>{invalidateResource('/api/molecules'); invalidateResource('/api/references'); mount().catch(error=>setText($('#molecule-details'),error.message));};
  form.elements.molecule_id.addEventListener('change',updateMolecule);
  form.elements.run_type.addEventListener('change',syncRunType);
  for (const input of [form.elements.mapping_candidate, form.elements.reference_run_id, form.elements.temperature_k, form.elements.aa_production_ps, form.elements.cg_production_ps]) {
    input?.addEventListener('input', syncRunSummary);
    input?.addEventListener('change', syncRunSummary);
  }
  async function loadReferences() {
    const select = form.elements.reference_run_id;
    const chosen = select.value || (!referencesLoaded && savedForm?.reference_run_id) || '';
    const result = await guarded('references', () => cachedApi('/api/references?'+new URLSearchParams({molecule_id:form.elements.molecule_id.value}),{maxAge:10000}));
    if(result===DROP)return;
    referencesLoaded=true; referenceRecords=result.references;
    select.replaceChildren(new Option('Run a new AA reference', ''));
    for (const reference of result.references) { const option=new Option(`${reference.label} · ${reference.settings?.aa_production_ps ?? 'unknown'} ps · ${reference.id}`, reference.id); option.dataset.settings=JSON.stringify(reference.settings||{}); select.append(option); }
    select.value = result.references.some(reference => reference.id === chosen) ? chosen : '';
    applyReferenceSettings(form.elements.run_type.value==='aa_only'?null:result.references.find(reference => reference.id === select.value));
    syncRunSummary();
    // The options exist now, so a model that pins the source can take it: readiness may well have answered first.
    if (enforceModelReferenceLock()) refreshReadiness();
    storage.set('form', formValues());
  }
  function applyReferenceSettings(reference) {
    const locked=!!reference;
    if(locked && !lockedReference) {
      if(!restoreManualAA || !Object.keys(manualAA).length){
        manualAA=Object.fromEntries(AA_FIELDS.map(key=>[key,form.elements[key].value]));
        storage.set('manual-aa-settings',manualAA);
      }
      restoreManualAA=false;
    }
    for (const key of AA_FIELDS) {
      const input=form.elements[key];
      if (locked && reference.settings?.[key] != null) input.value=reference.settings[key];
      if (!locked && lockedReference && manualAA[key] != null) input.value=manualAA[key];
      input.disabled=locked; input.closest('label')?.classList.toggle('inherited-setting',locked);
      input.closest('label')?.querySelectorAll('.use-default').forEach(button=>{button.disabled=locked;});
    }
    lockedReference=reference?.id || null;
    $('#delete-reference').hidden=!locked;
    setText($('#reference-help'), locked ? 'AA protocol, temperature and output interval are inherited and locked. CG runs share this source trajectory; execution does not establish convergence.' : 'A new AA simulation runs first as a separate job. Compatible completed AA-only references are shared without trajectory copies.');
    syncRunSummary();
  }
  //: The run the mapping's own parameterization pinned the AA source to, and the mapping whose model did it.
  let referencePin = null;
  let pinnedMapping = null;

  /** Hand the AA settings back to the reader, and forget the pin.
   *
   * The pin belongs to one mapping's model. Releasing it clears the source it chose -- unless the reader had picked
   * that same run by hand -- so the next model's run has an AA half of its own rather than inheriting one nobody asked
   * for, which would be the same silent substitution in the other direction.
   */
  function releaseReferencePin() {
    const select = form.elements.reference_run_id;
    if (!referencePin) return false;
    if (select.value === referencePin) select.value = '';
    referencePin = null;
    pinnedMapping = null;
    select.disabled = false;
    select.dataset.locked = '';
    select.closest('label')?.classList.remove('inherited-setting');
    applyReferenceSettings(referenceRecords.find(record => record.id === select.value) || null);
    return true;
  }

  /** Pin the AA source to the run this mapping's parameterization was fitted against, and say why.
   *
   * A parameterization is a fit to one ensemble: its current revision records `aa_reference.run_id`, and the terms are
   * only as good as that run is. A picker that could point somewhere else would run the model outside the ensemble it
   * was fitted to, silently, so the model chooses the source here. `applyReferenceSettings` then fills the AA settings
   * from that run's own record and locks them -- those numbers are what the reference ran at, and a run that consumes a
   * reference does not re-run its AA half at new ones.
   *
   * An unparameterized mapping keeps the ordinary picker: its run fits in stage 3, and its AA half is its own.
   *
   * A null answer is *not* an instruction to unlock. The panel clears its answer whenever it re-asks (`refreshReadiness`)
   * and the pin would drop and return on every question, which is a loop rather than a state; the pin is released when
   * the mapping on the picker changes, which is the only thing that can make it belong to a different model.
   * Returns whether the source on the form changed, so the caller can re-ask readiness about it.
   */
  function enforceModelReferenceLock() {
    const select = form.elements.reference_run_id;
    const state = modelAnswer();
    if (!state) return false;
    if (!state.parameterized || !state.aa_reference?.run_id) return releaseReferencePin();
    const wanted = state.aa_reference.run_id;
    const before = select.value;
    const option = Array.from(select.options).find(item => item.value === wanted);
    if (!option) {
      // The model names a run this list does not offer. Locking to something else would be a different model, so the
      // panel says which run is missing rather than choosing for the reader.
      releaseReferencePin();
      setText($('#reference-help'), `This mapping was fitted against ${wanted}, which is not offered as an AA source here. The run needs that source to reuse the model.`);
      return select.value !== before;
    }
    if (referencePin !== wanted) {
      referencePin = wanted;
      pinnedMapping = mappingChoice();
      select.value = wanted;
      applyReferenceSettings(referenceRecords.find(record => record.id === wanted) || null);
    }
    select.disabled = true;
    select.dataset.locked = 'parameterization';
    select.closest('label')?.classList.add('inherited-setting');
    // The delete button belongs to a source the reader chose; deleting the run a current parameterization was fitted
    // against would leave the model resting on a run that is gone.
    $('#delete-reference').hidden = true;
    setText($('#reference-help'), `Locked to ${option.textContent}: this mapping's bond interactions were fitted against that run, and the AA settings below are that run's own. A different source would run the model outside the ensemble it was fitted to; the model itself is chosen in CG Bond Interactions.`);
    syncRunSummary();
    return select.value !== before;
  }

  async function loadRunMappings() {
    const select = form.elements.mapping_candidate;
    const chosen = select.value || (!mappingsLoaded && savedForm?.mapping_candidate) || '';
    const moleculeId = form.elements.molecule_id.value;
    const query = moleculeId ? `&molecule_id=${encodeURIComponent(moleculeId)}` : '';
    const result = await cachedApi(`/api/mappings?view=summary${query}`,{maxAge:10000});
    mappingsLoaded=true;
    // Only a mapping a run can reuse is offered. `validation.can_reuse` is the verdict `draft.load` refuses on
    // (`models/mappings/verdict.RULES['can_reuse']`), so the picker cannot list a candidate the queue would reject,
    // and the browser does not restate a rule the store owns. A candidate with no verdict -- one whose file does not
    // parse -- has no `can_reuse` and is not offered either.
    const usable = result.candidates.filter(candidate => candidate.validation?.can_reuse === true);
    select.replaceChildren(new Option(usable.length ? 'Select a saved mapping'
      : 'No saved mapping can be run for this molecule', ''));
    for (const candidate of usable) {
      select.append(new Option(`${candidate.name} · ${candidate.file}`, candidate.file));
    }
    // A remembered choice that cannot be run is not a selection: it is left unselected rather than shown as an
    // option the reader must read past, and readiness asks about no mapping until one is chosen.
    select.value = usable.some(candidate => candidate.file === chosen) ? chosen : '';
    refreshReadiness();

  }
  // The `02 · CG MODEL` card ------------------------------------------------------------------------------------
  //
  // D5 of `docs/design/2026-10-16-parameterization-and-new-run.md`: a run consumes a *model* -- a mapping with its
  // parameterization -- and never re-fits a parameterized one. So the panel states, before the run is started, which
  // parameterization it will use; and when the model carries none it says the run fits in stage 3 and records that
  // it did, rather than leaving a reader to guess from a stage name.
  //
  // Three rules shape it:
  //
  // * **The run type's words, not the panel's.** `readiness()['parameterization']` carries `statement`, the sentence
  //   `adapters/cg.py` keeps beside the code that keeps the promise; the card renders it for the unparameterized
  //   state rather than composing a parallel claim that could drift from the pipeline.
  // * **It never touches `#start-run`.** An absent parameterization is a state, not a blocker -- the run fits it --
  //   so the only thing allowed to disable Start is `ready.ready`.
  // * **It is built here, in a container the markup already has.** `dashboard.html` belongs to the panel's own
  //   layout, and the card lives inside `#cg-inputs`, under the mapping picker it describes. Its classes are the
  //   house ones (`.card`, `.eyebrow`, `.review-grid`, `.hint`, `.button.secondary`), so it needs no stylesheet.
  //
  // The link is addressed the way this app addresses a panel: the sub-tab row already carries the panel's own route
  // (`sections.py` writes the href), so the card reads it from there instead of restating a URL, and names the
  // mapping with the query key the rest of the app uses for one (`mapping_candidate`).
  let modelState = null;
  // The answer, and the mapping it answers about. The two travel together because the card's heading and the
  // card's numbers have to come from one response: a mapping change makes the previous answer meaningless, and a
  // state kept without its mapping is what paints the old revision under the new name.
  const mappingChoice = () => form.elements.mapping_candidate?.value || '';
  /** The answer, if it is still about the mapping on the picker; `null` otherwise. */
  function modelAnswer() {
    return modelState && modelState.mapping === mappingChoice() ? modelState.state : null;
  }
  function bondedPanelHref(mapping) {
    const tab = document.querySelector(`nav.subtabs [data-tab="${panelIds()['bond-interactions']}"]`);
    const href = tab?.getAttribute('href');
    if (!href) return '';
    return mapping ? `${href}?${new URLSearchParams({mapping_candidate: mapping})}` : href;
  }
  function ensureModelCard() {
    let card = form.querySelector('.cg-model');
    if (card) return card;
    const anchor = form.elements.mapping_candidate?.closest('label');
    if (!anchor) return null;
    card = document.createElement('section');
    card.className = 'card cg-model';
    card.setAttribute('aria-label', '02 · CG Model');
    // Fixed markup and every value written by `textContent` below: nothing here interpolates a name, a path or a
    // sentence the server sent, so a mapping called `<b>` stays a mapping called `<b>`.
    card.innerHTML = '<span class="eyebrow">02 · CG MODEL</span>'
      + '<h3 data-cg-model="name">Select a mapping</h3>'
      + '<dl class="review-grid" data-cg-model="terms">'
      + '<dt>Parameterization</dt><dd data-cg-model="parameterization">—</dd>'
      + '<dt>Fitted with</dt><dd data-cg-model="engine">—</dd>'
      + '<dt>Torsion model</dt><dd data-cg-model="torsion">—</dd>'
      + '<dt>AA reference</dt><dd data-cg-model="reference">—</dd>'
      + '</dl>'
      + '<p class="hint" data-cg-model="statement"></p>'
      + '<div class="toolbar"><a class="button secondary" data-cg-model="open"></a></div>';
    anchor.insertAdjacentElement('afterend', card);
    // The door is the card's own control; its click is answered by `followBondedLink` below, which is what makes
    // the panel open on the mapping this card describes.
    card.querySelector('[data-cg-model="open"]').onclick = followBondedLink;
    return card;
  }
  function modelField(card, name, text) {
    const node = card.querySelector(`[data-cg-model="${name}"]`);
    if (node && text !== undefined) node.textContent = text;
    return node;
  }
  // The AA reference as the revision records it: the run id a reader can look up, and the ensemble it was measured
  // on. `null` is a fact about how a revision was produced (one stored before the reference-free engine was removed
  // read no AA frames at all), not a missing field.
  function describeReference(reference) {
    if (!reference) return 'none — this parameterization read no AA reference';
    const parts = [reference.run_id || 'unnamed reference'];
    if (reference.temperature_k != null) parts.push(`${reference.temperature_k} K`);
    if (reference.production_ns != null) parts.push(`${reference.production_ns} ns`);
    return parts.join(' · ');
  }
  function renderModelCard(answer) {
    const card = ensureModelCard();
    if (!card) return;
    // Only the AA–CG branch has a model to describe, and only once a mapping is chosen: an empty picker has no
    // parameterization to state, and a composition carries its own bonded terms rather than a mapping's. The answer
    // must also be *this* mapping's -- an answer about the mapping that was on the picker a moment ago is not.
    const state = answer && answer.mapping === mappingChoice() ? answer.state : null;
    const shown = form.elements.run_type.value === 'aa_cg' && !!mappingChoice() && !!state;
    card.hidden = !shown;
    if (!shown) { clearModelCard(card); return; }
    modelField(card, 'name', form.elements.mapping_candidate.selectedOptions?.[0]?.textContent?.trim() || mappingChoice());
    const terms = card.querySelector('[data-cg-model="terms"]');
    if (terms) terms.hidden = !state.parameterized;
    if (state.parameterized) {
      modelField(card, 'parameterization', `revision ${state.revision} · ${state.terms} bonded terms`);
      modelField(card, 'engine', state.engine_label || state.engine || 'unknown engine');
      modelField(card, 'torsion', state.torsion_model || 'not recorded');
      modelField(card, 'reference', describeReference(state.aa_reference));
    } else {
      // No provenance is claimed where there is none: the rows belong to the parameterized state.
      modelField(card, 'parameterization', '—');
      modelField(card, 'engine', '—');
      modelField(card, 'torsion', '—');
      modelField(card, 'reference', '—');
    }
    // Both honest states end in the run type's own sentence -- it is the sentence `adapters/cg.py` keeps beside the
    // code that keeps the promise, and a second wording here would be a claim the panel does not own.
    modelField(card, 'statement', state.statement || '');
    const open = card.querySelector('[data-cg-model="open"]');
    if (open) {
      open.textContent = state.parameterized ? 'Open in CG Bond Interactions'
                                             : 'Parameterize first in CG Bond Interactions…';
      const href = bondedPanelHref(mappingChoice());
      if (href) open.setAttribute('href', href); else open.removeAttribute('href');
      // Optional, not required: an unparameterized model still starts a run, so the door says so rather than
      // reading as the only way forward.
      open.title = state.parameterized
        ? 'Open this mapping in CG Bond Interactions, where its revisions are fitted and kept.'
        : 'Optional: this run fits the model in stage 3. This opens the mapping where it can be fitted first.';
    }
  }
  // Hiding the card is not enough. Its rows are what a hidden element still holds, and the next render is a fetch
  // away; so the previous mapping's revision, engine and torsion model are removed with the answer they came from
  // rather than left for a reader -- or a test -- to find under the new mapping's name.
  function clearModelCard(card) {
    modelField(card, 'name', 'Select a mapping');
    for (const name of ['parameterization', 'engine', 'torsion', 'reference']) modelField(card, name, '—');
    modelField(card, 'statement', '');
    const terms = card.querySelector('[data-cg-model="terms"]');
    if (terms) terms.hidden = true;
    const open = card.querySelector('[data-cg-model="open"]');
    if (open) { open.removeAttribute('href'); open.removeAttribute('title'); open.textContent = ''; }
  }

  // The door into CG Bond Interactions, and the half of it an address cannot carry on its own ---------------------
  //
  // The two panels are one document (`tabs.js` switches them in place), and the bonded panel's picker is filled by
  // `mappings.js` after the switch -- so the query key on the href names the mapping but nothing has read it. The
  // card's owner finishes the job: it selects the option and fires `change`, which is exactly what a reader
  // picking it from that list does, so the panel opens on the mapping the card describes rather than on whichever
  // candidate happens to be first. A cold load of the same address -- a copied link, a new tab -- reads the key at
  // start-up, so both doors land in the same place.
  function followBondedLink(event) {
    const file = mappingChoice();
    if (!file) return;
    // A modifier-click is the browser's to answer: the address it opens carries the same key, and the reader above
    // picks it up on that page.
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    selectTab(panelIds()['bond-interactions']);
    // The address follows the panel the reader is now on, and names the mapping they followed.
    const href = bondedPanelHref(file);
    if (href) history.replaceState(null, '', href);
    preselectBondedMapping(file);
  }

  const gpuDevice = createGpuDevice({
    select: $('#run-gpu-device'),
    note: $('#run-gpu-note'),
    ranks: () => form.elements.mdrun_ranks?.value,
    saved: () => storage.get('form', {}).mdrun_gpu,
  });
  // Ranks share the one device, so the note is repainted when the rank count moves rather than only on load.
  form.elements.mdrun_ranks?.addEventListener('input', () => gpuDevice.refresh());

  let stageDefaults;
  // The force fields come from the registry, so the panel offers what the server can actually run rather than a
  // copy of the list held here. Choosing one moves the temperature to the value that entry's parameterisation
  // assumes: the temperature belongs to the force field, and the field stays editable afterwards.
  function fillForceFields(entries) {
    const select = form.elements.force_field;
    if (!select || !Array.isArray(entries) || !entries.length) return;
    const chosen = select.value || stageDefaults?.values?.force_field;
    select.replaceChildren(...entries.map(entry =>
      new Option(`${entry.label} · ${entry.temperature_k} K · ${String(entry.water).toUpperCase()}`, entry.name)));
    select.value = entries.some(entry => entry.name === chosen) ? chosen : entries[0].name;
    select.onchange = () => {
      const entry = entries.find(candidate => candidate.name === select.value);
      if (entry) form.elements.temperature_k.value = entry.temperature_k;
      syncRunSummary(); refreshReadiness(); storage.set('form', formValues());
    };
  }
  async function loadStageDefaults() {
    const run_type=form.elements.run_type.value;
    const result=await cachedApi('/api/defaults?' + new URLSearchParams({run_type}));
    // The answer is dropped if the run type on the form is no longer the one asked about: the route answers with the
    // run type's own profile's durations, so the run type is the whole question.
    if(run_type!==form.elements.run_type.value)return;
    stageDefaults = result;
    fillForceFields(result.force_fields);
    for (const [field, value] of Object.entries(stageDefaults.values)) {
      const input = form.elements[field];
      if (input && !input.value) input.value = value;
    }
    setText($('#defaults-source'), 'Defaults from ' + Object.values(stageDefaults.sources).join(' · '));
    syncRunSummary();
    storage.set('form', formValues());
  }
  const savedForm = storage.get('form', {});
  for (const input of [...form.elements].filter(el=>el.name)) {
    if (savedForm[input.name] !== undefined) input.value = savedForm[input.name];
    input.addEventListener('input', () => storage.set('form', formValues()));
  }
  let defaultsLoading;
  setText($('#clone-notice'),form.elements.clone_of.value?`Cloning ${form.elements.clone_of.value}. Change settings below before starting.`:'');
  $('#leave-clone').hidden=!form.elements.clone_of.value;
  for (const button of $$('.use-default')) button.addEventListener('click', async () => {
    try {
      defaultsLoading ||= loadStageDefaults(); await defaultsLoading; defaultsLoading = null;
      const field = button.dataset.field; form.elements[field].value = stageDefaults.values[field];
      gpuDevice.refresh();
      syncRunSummary(); refreshReadiness();
      storage.set('form', formValues());
    } catch (error) { notice(error.message); }
  });

  let readinessGeneration = 0, readinessTimer, readinessController;
  function refreshReadiness() {
    ++readinessGeneration;
    clearTimeout(readinessTimer);readinessController?.abort();
    // Everything on screen is about the inputs as they were when the question was asked, and the question is about
    // to be asked again. Until it answers there is no answer: clearing it here -- and re-rendering from nothing --
    // is what keeps the previous mapping's revision, engine and torsion model from being painted beside the new
    // mapping's name (and read by `#run-bonded-summary`) while the new answer is in flight, or forever when the
    // request fails.
    modelState = null;
    renderModelCard(null);
    // The pin outlives a re-asked question but not a different mapping: it belongs to one model's fit.
    if (referencePin && pinnedMapping !== mappingChoice()) releaseReferencePin();
    syncRunSummary();
    $('#start-run').disabled=true;
    if($('#'+panelIds()['new-run']).hidden || !mounted || mounting)return;
    readinessTimer=setTimeout(()=>checkReadiness(readinessGeneration),150);
  }
  async function checkReadiness(generation) {
    readinessController=new AbortController();
    $('#start-run').disabled = true;
    const compositionOnly=form.elements.run_type.value==='cg_composition';
    const selectedMolecule=moleculeRecords.find(record=>record.id===form.elements.molecule_id.value);
    syncRunSummary();
    const run_type=form.elements.run_type.value;
    if(!compositionOnly && !selectedMolecule){const message='Select an available molecule directory before starting.';setText($('#readiness'),message);setText($('#launch-blocker'),message);setText($('#review-status'),'Action required');$('#review-status').dataset.ready='false';return;}
    try {
      const query={run_type,molecule_id:form.elements.molecule_id.value, detergent:form.elements.detergent.value};
      if(run_type==='aa_cg')Object.assign(query,{method:form.elements.method.value,mapping_candidate:form.elements.mapping_candidate.value,reference_run_id:form.elements.reference_run_id.value});
      if(run_type==='cg_composition')Object.assign(query,{composition_id:form.elements.composition_id.value});
      const ready = await api('/api/readiness?' + new URLSearchParams(query),{signal:readinessController.signal});
      if (generation !== readinessGeneration) return;
      if(ready.molecule) showMolecule(ready.molecule);
      // The card states what the run will consume before it starts, from the run type's own answer. It is read here
      // -- where the answer the panel is about to trust arrives -- so the card and the Start button cannot disagree
      // about which model this run is, and it is *not* read from `ready.ready`: a model with no parameterization is
      // still runnable, and the card must not be able to hold the button disabled.
      //
      // The answer is kept with the mapping the question named rather than with whatever is on the picker now, so a
      // card can never be rendered from an answer about another mapping.
      modelState = {mapping: run_type === 'aa_cg' ? (query.mapping_candidate || '') : '',
                    state: ready.parameterization || null};
      renderModelCard(modelState);
      // The source the model was fitted against, applied here -- where the answer the panel is about to trust arrives,
      // the same place the card is drawn from. A source it changed is re-asked about, because readiness was answered
      // about the one on the form when the question went out.
      if (enforceModelReferenceLock()) { refreshReadiness(); return; }
      // The review's own `Bonded fit` row reads the same state, so it is refreshed with the card rather than only at
      // the start of the next check.
      syncRunSummary();
      writeReadiness(ready.checks, ready.blockers);
      setText($('#review-status'), ready.ready ? 'Inputs ready' : (ready.blockers?.length ? 'Action required' : 'Not ready'));
      $('#review-status').dataset.ready=String(!!ready.ready);
      setText($('#launch-blocker'),ready.ready?'':ready.blockers?.[0]||'Inputs are not ready.');
      $('#start-run').disabled = !ready.ready;
    } catch (error) { if(generation!==readinessGeneration || error.name==='AbortError')return;setText($('#readiness'), error.message);setText($('#launch-blocker'),error.message); setText($('#review-status'),'Readiness unavailable'); $('#review-status').dataset.ready='false'; }
  }
  for (const input of [form.elements.detergent, form.elements.method, form.elements.mapping_candidate, form.elements.composition_id]) input.addEventListener('change', refreshReadiness);
  form.elements.reference_run_id.addEventListener('change', syncRunSummary);
  for (const input of [form.elements.temperature_k, form.elements.aa_production_ps, form.elements.cg_production_ps]) input.addEventListener('input', syncRunSummary);
  form.elements.mapping_candidate.addEventListener('change', () => storage.set('form', formValues()));
  form.elements.reference_run_id.addEventListener('change', () => {
    const id=form.elements.reference_run_id.value;
    const reference=referenceRecords.find(r=>r.id===id);
    applyReferenceSettings(reference); storage.set('form', formValues()); refreshReadiness();
  });
  $('#delete-reference').onclick=async () => {
    const id=form.elements.reference_run_id.value; if(!id) return;
    if(!window.confirm('Delete this AA reference source run and its simulation files? This cannot be undone.')) return;
    try { await api('/api/jobs/'+encodeURIComponent(id),{method:'DELETE'}); if(form.elements.clone_of.value===id)setCloneSource('', 'Clone source deleted. Your settings are kept for a new run.'); form.elements.reference_run_id.value=''; applyReferenceSettings(null); invalidateResource('/api/references');invalidateResource('/api/storage');await loadReferences(); notice('AA reference source deleted.'); }
    catch(error) { notice(error.message); }
  };
  form.addEventListener('submit', async event => {
    event.preventDefault(); $('#start-run').disabled = true;
    try {
      if(!await validateCloneSource())return;
      const data=formValues();
      const fields=data.run_type==='aa_only'?[...AA_FIELDS,...GPU_FIELDS]:[...AA_FIELDS,...GPU_FIELDS,...CG_FIELDS];
      if(data.run_type==='aa_only')for(const key of ['method','mapping_candidate','reference_run_id',...CG_FIELDS])delete data[key];
      delete data.aa_equil_ps;
      if(data.clone_of) {
        data.settings=Object.fromEntries(fields.filter(k=>data[k] !== '' && data[k] != null).map(k=>[k,data[k]]));
        try { await post(`/api/jobs/${data.clone_of}/clone`,data); }
        catch(error) { if(error.status===404 && !await validateCloneSource())return; throw error; }
      }
      else await post('/',data);
      invalidateResource('/api/references');invalidateResource('/api/storage');
      setCloneSource(''); notice('Run queued.'); selectTab('runs'); await refreshJobs(); }
    catch (error) { notice(error.message); }
    finally { refreshReadiness(); }
  });
  async function mount() {
    if(mounting)return mounting;
    $('#'+panelIds()['new-run']).setAttribute('aria-busy','true');$('#start-run').disabled=true;
    mounting=(async()=>{
      await validateCloneSource();
      await Promise.all([loadMolecules(),loadStageDefaults()]);
      // The device list and the readiness note arrive after the form's own answers: a probe of the host is not
      // something the panel's molecule picker waits on, and the note is a status line, not a gate.
      gpuDevice.load();
      await loadRunMappings();
      const modelCatalog=await cachedApi('/api/cg-models?view=summary',{maxAge:10000});
      form.elements.composition_id.replaceChildren(new Option('Select a saved composition',''));
      for(const item of (modelCatalog.models||[]).filter(item=>item.kind==='composition')) form.elements.composition_id.append(new Option(`${item.name} · ${item.status}`,item.id));
      await loadReferences();
      mounted=true;
      syncRunType();syncRunSummary();
      refreshStorage();
    })();
    try {await mounting;}
    finally {mounting=null;$('#'+panelIds()['new-run']).setAttribute('aria-busy','false');refreshReadiness();}
  }
  document.addEventListener('dashboard:tab',event=>{
    if(event.detail.id!==panelIds()['new-run']){++readinessGeneration;clearTimeout(readinessTimer);readinessController?.abort();}
  });


  async function cloneRun(source) {
    selectTab('new');
    applyReferenceSettings(null);
    for (const [key,value] of Object.entries({...source.settings,run_type:source.run_type || 'aa_cg',detergent:source.detergent,molecule_id:source.molecule_id || source.detergent,method:source.run_type==='aa_only'?form.elements.method.value:source.method,mapping_candidate:source.mapping_candidate || '',label:(source.label || source.id)+' copy',clone_of:source.id,reference_run_id:source.reference_run_id || ''})) {
      if (form.elements[key]) form.elements[key].value = value;
    }
    setCloneSource(source.id);syncRunType();
    await mount();
    // The device options come from the host, so a clone's own index can only be applied once they exist.
    const gpu = source.settings?.mdrun_gpu;
    if (gpu != null && [...(form.elements.mdrun_gpu?.options || [])].some(option => option.value === String(gpu))) {
      form.elements.mdrun_gpu.value = String(gpu);
    }
    gpuDevice.refresh();
    await loadMolecules(); await loadRunMappings(); await loadReferences(); refreshReadiness();
  }

  function clearDeletedClone(id) {
    if (form.elements.clone_of.value === id) setCloneSource('', 'Clone source deleted. Your settings are kept for a new run.');
  }

  async function openComposition(compositionId) {
    await mount();
    form.elements.run_type.value='cg_composition';
    form.elements.composition_id.value=compositionId;
    syncRunType();
    refreshReadiness();
  }

  return { mount, cloneRun, clearDeletedClone, setCloneSource, openComposition };
}
