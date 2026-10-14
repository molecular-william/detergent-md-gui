import { $, $$, storage, setText, notice, api, post, cachedApi, invalidateResource, guarded, DROP, panelIds } from './shared.js';
import { BEAD_FAMILY_PARAMETERS, BEAD_RADIUS_PARAMETERS, applyBeadRadii, renderBeadLegend } from './ngl-beads.js';

//: The workspace whose New Run panel this module's pdc mode serves.
const PDC_WORKSPACE = 'protein-detergent';

// Owns the persisted run form, inherited settings, and readiness checks.
export function createNewRun({ selectTab, refreshJobs, refreshStorage }) {
  const form = $('#run-form');
  // Which form this is decided by the workspace the page was opened in, not by what is on it. The template renders
  // one fieldset or the other, and neither is a subset of the other: the pdc panel has no `run_type`, no `method`
  // and no reference select at all, so every AA statement below would throw on its first `form.elements.<name>`.
  // The branch is here, above them, so the two panels cannot read each other's fields by accident.
  if ((location.pathname.split('/').filter(Boolean)[0] || '') === PDC_WORKSPACE) {
    return createPdcNewRun({ form, selectTab, refreshJobs });
  }
  const AA_FIELDS = ['aa_nvt_ps','aa_npt_ps','aa_production_ps','temperature_k','pressure_bar','output_interval_ps','box_nm','aa_seed','mdrun_ntomp','mdrun_ranks','mdrun_nb','mdrun_pme'];
  const CG_FIELDS = ['cg_equil_ps','cg_production_ps','sasa_probe_nm','cg_seed'];
  // Persist all controls, including disabled values inherited from a reference.
  function formValues() { return Object.fromEntries([...form.elements].filter(el=>el.name).map(el=>[el.name,el.value])); }
  function saveForm() { storage.set('form',formValues()); }
  let referenceRecords = [], referenceGeneration = 0, lockedReference = null;
  let referencesLoaded=false, mappingsLoaded=false, statesLoaded=false, mounted=false, mounting=null;
  // The shared cache drops a resource when something changes it elsewhere; these flags
  // remember that this module already fetched it, so they have to drop with it. Saving a
  // bonded state in the CG Bond Interactions tab was the case that bit: the New-run
  // dropdown kept offering the list it had fetched before the save.
  document.addEventListener('dashboard:resources-changed', event => {
    const prefix = event.detail?.prefix || '';
    if (prefix.startsWith('/api/bonded-states')) statesLoaded = false;
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
    const aaOnly=form.elements.run_type.value==='aa_only';
    const textFor=(field, fallback)=>field?.selectedOptions?.[0]?.textContent || fallback;
    setText($('#run-type-summary'), aaOnly?'AA-only run':'AA–CG run');
    setText($('#run-aa-summary'), aaOnly?'New AA reference':textFor(form.elements.reference_run_id,'New AA reference'));
    setText($('#run-mapping-summary'), aaOnly?'Not needed for AA-only':textFor(form.elements.mapping_candidate,'Select a mapping'));
    const intent=form.elements.bonded_intent.value;
    setText($('#run-bonded-summary'), aaOnly?'Not needed':intent==='reuse_state'?textFor(form.elements.bonded_state_id,'Select a bonded state'):intent==='fit_only'?'Fit, then stop for review':'Fit, then simulate');
    const temp=form.elements.temperature_k.value || '—';
    const aa=form.elements.aa_production_ps.value || '—';
    const cg=form.elements.cg_production_ps.value || '—';
    const protocol=`${temp} K · ${form.elements.pressure_bar.value||'—'} bar · NVT ${form.elements.aa_nvt_ps.value||'—'} / NPT ${form.elements.aa_npt_ps.value||'—'} / production ${aa} ps`;
    setText($('#run-settings-summary'), aaOnly?protocol:`${protocol} · CG ${cg} ps`);
  }
  function syncRunType() {
    const aaOnly=form.elements.run_type.value==='aa_only';
    const compositionOnly=form.elements.run_type.value==='cg_composition';
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
    $('#run-bonded-state').closest('label').classList.toggle('hidden', compositionOnly);
    $('#reference-run').closest('label').classList.toggle('hidden', compositionOnly);
    form.elements.molecule_id.disabled = compositionOnly;
    form.elements.molecule_id.required = !compositionOnly;
    form.elements.composition_id.disabled = !compositionOnly;
    form.elements.composition_id.required = compositionOnly;
    showMolecule(moleculeRecords.find(record=>record.id===form.elements.molecule_id.value));
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
  for (const input of [form.elements.mapping_candidate, form.elements.bonded_state_id, form.elements.bonded_intent, form.elements.reference_run_id, form.elements.temperature_k, form.elements.aa_production_ps, form.elements.cg_production_ps]) {
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
  async function loadRunMappings() {
    const select = form.elements.mapping_candidate;
    const chosen = select.value || (!mappingsLoaded && savedForm?.mapping_candidate) || '';
    const moleculeId = form.elements.molecule_id.value;
    const query = moleculeId ? `&molecule_id=${encodeURIComponent(moleculeId)}` : '';
    const result = await cachedApi(`/api/mappings?view=summary${query}`,{maxAge:10000});
    mappingsLoaded=true;
    select.replaceChildren(new Option('Select a saved mapping', ''));
    for (const candidate of result.candidates) {
      const issues = candidate.validation?.issues || [];
      const option = new Option(`${candidate.name} · ${candidate.file}${issues.length ? ' · needs repair' : ''}`, candidate.file);
      option.disabled = !!candidate.error;
      select.append(option);
    }
    if (chosen && !result.candidates.some(c => c.file === chosen)) {
      select.append(new Option(`Unavailable candidate · ${chosen} — choose another mapping`, chosen));
    }
    select.value = chosen;
    if (chosen && form.elements.profile.value === 'standard') {
      form.elements.profile.value = 'draft-smoke';
    }
    refreshReadiness();

  }
  async function loadRunBondedStates() {
    const select=form.elements.bonded_state_id;if(!select)return;
    const chosen=select.value||(!statesLoaded&&savedForm?.bonded_state_id)||'';const result=await cachedApi('/api/bonded-states?view=summary',{maxAge:10000});statesLoaded=true;select.replaceChildren(new Option('Fit bonded parameters during this run',''));
    for(const state of result.states||[]) { const option=new Option(`${state.name} · r${state.revision} · ${state.current.status}`,state.state_id);option.disabled=state.current.status!=='complete';select.append(option); }
    select.value=chosen;setText($('#bonded-run-help'),chosen?'This run will reuse the selected immutable bonded-state revision.':'No state selected: fit bonded parameters during this run.');
  }
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
    const profile = form.elements.profile.value;
    const run_type=form.elements.run_type.value;
    const result=await cachedApi('/api/defaults?' + new URLSearchParams({profile,run_type}));
    if(run_type!==form.elements.run_type.value || profile!==form.elements.profile.value)return;
    stageDefaults = result;
    fillForceFields(result.force_fields);
    for (const [field, value] of Object.entries(stageDefaults.values)) {
      const input = form.elements[field];
      if (input && !input.value) { input.value = value; input.dataset.defaultProfile = profile; }
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
      const field = button.dataset.field; form.elements[field].value = stageDefaults.values[field]; form.elements[field].dataset.defaultProfile = stageDefaults.profile;
      syncRunSummary(); refreshReadiness();
      storage.set('form', formValues());
    } catch (error) { notice(error.message); }
  });

  let readinessGeneration = 0, readinessTimer, readinessController;
  function refreshReadiness() {
    ++readinessGeneration;
    clearTimeout(readinessTimer);readinessController?.abort();
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
      if(run_type==='aa_cg')Object.assign(query,{method:form.elements.method.value,profile:form.elements.profile.value,mapping_candidate:form.elements.mapping_candidate.value,reference_run_id:form.elements.reference_run_id.value});
      if(run_type==='cg_composition')Object.assign(query,{composition_id:form.elements.composition_id.value});
      const ready = await api('/api/readiness?' + new URLSearchParams(query),{signal:readinessController.signal});
      if (generation !== readinessGeneration) return;
      if(ready.molecule) showMolecule(ready.molecule);
      const panel = $('#readiness'); panel.replaceChildren();
      setText($('#review-status'), ready.ready ? 'Inputs ready' : (ready.blockers?.length ? 'Action required' : 'Not ready'));
      $('#review-status').dataset.ready=String(!!ready.ready);
      setText($('#launch-blocker'),ready.ready?'':ready.blockers?.[0]||'Inputs are not ready.');
      for (const check of ready.checks) {
        const row = document.createElement('div'); row.className = 'ready-check';
        const title = document.createElement('strong'); title.textContent = `${check.ready ? 'Present' : 'Missing'} · ${check.label}`;
        const path = document.createElement('code'); path.textContent = check.path;
        const detail = document.createElement('p'); detail.className = 'hint'; detail.textContent = check.detail;
        row.append(title, path, detail); panel.append(row);
      }
      const blockers = document.createElement('ul');
      for (const blocker of ready.blockers) { const li = document.createElement('li'); li.textContent = blocker; blockers.append(li); }
      panel.append(blockers); $('#start-run').disabled = !ready.ready;
    } catch (error) { if(generation!==readinessGeneration || error.name==='AbortError')return;setText($('#readiness'), error.message);setText($('#launch-blocker'),error.message); setText($('#review-status'),'Readiness unavailable'); $('#review-status').dataset.ready='false'; }
  }
  for (const input of [form.elements.detergent, form.elements.method, form.elements.profile, form.elements.mapping_candidate, form.elements.composition_id]) input.addEventListener('change', refreshReadiness);
  form.elements.bonded_state_id.addEventListener('change', syncRunSummary);
  form.elements.reference_run_id.addEventListener('change', syncRunSummary);
  form.elements.bonded_intent.addEventListener('change', syncRunSummary);
  for (const input of [form.elements.temperature_k, form.elements.aa_production_ps, form.elements.cg_production_ps]) input.addEventListener('input', syncRunSummary);
  form.elements.mapping_candidate.addEventListener('change', () => {
    if (form.elements.mapping_candidate.value && form.elements.profile.value === 'standard') {
      form.elements.profile.value = 'draft-smoke';
      refreshReadiness();
    }
    storage.set('form', formValues());
  });
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
  form.elements.profile.addEventListener('change',()=>{ for(const key of ['cg_equil_ps','cg_production_ps']) form.elements[key].value=''; loadStageDefaults().catch(error=>notice(error.message)); });
  form.addEventListener('submit', async event => {
    event.preventDefault(); $('#start-run').disabled = true;
    try {
      if(!await validateCloneSource())return;
      const data=formValues();
      const fields=data.run_type==='aa_only'?AA_FIELDS:[...AA_FIELDS,...CG_FIELDS];
      if(data.run_type==='aa_only')for(const key of ['method','profile','mapping_candidate','bonded_state_id','bonded_intent','reference_run_id',...CG_FIELDS])delete data[key];
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
      await Promise.all([loadMolecules(),loadStageDefaults(),loadRunBondedStates()]);
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
    for (const [key,value] of Object.entries({...source.settings,run_type:source.run_type || 'aa_cg',detergent:source.detergent,molecule_id:source.molecule_id || source.detergent,method:source.run_type==='aa_only'?form.elements.method.value:source.method,profile:source.run_type==='aa_only'?form.elements.profile.value:source.profile || 'standard',mapping_candidate:source.mapping_candidate || '',bonded_state_id:source.bonded_state_id || '',bonded_intent:source.bonded_intent || 'fit_and_simulate',label:(source.label || source.id)+' copy',clone_of:source.id,reference_run_id:source.reference_run_id || ''})) {
      if (form.elements[key]) form.elements[key].value = value;
    }
    setCloneSource(source.id);syncRunType();
    await mount();
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


// The protein-detergent workspace's New Run panel ---------------------------------------------------------------
//
// `dashboard.html` renders this fieldset only for the workspace whose pipeline it describes, so this function is the
// whole of the panel's pdc mode: there is no AA reference, no method and no bonded fit to hide, because nothing
// rendered one. Every control it reads is a name `execution/adapters/pdc.py` accepts -- its `validate_payload` and
// `SETTING_SPECS` are the authority for the spelling, and a control whose value no stage consumes is a control that
// lies.
//
// One house rule shapes how it reaches the DOM. The id contract (`tests/dashboard/integration/test_dom_ids.py`)
// requires every id a module names in a selector to be rendered on the detergent-validation page too, and this
// fieldset is not rendered there -- so the panel's own controls are read through `form.elements` and its status
// lines through `new-pdc-` class hooks, and the only ids it names are the ones both variants carry (`#run-form`,
// `#start-run`, `#review-status`, `#launch-blocker`, `#readiness`).
function createPdcNewRun({ form, selectTab, refreshJobs }) {
  const field = name => form.elements[name];
  const pdcNode = selector => form.querySelector(selector);
  const summary = key => form.querySelector(`[data-new-summary="${key}"]`);
  const say = (selector, text) => { const target = pdcNode(selector); if (target) setText(target, text); };
  const saved = () => storage.get('pdc-form', {}) || {};
  // The adapter's own names, so a field left empty is omitted and the adapter's default stands rather than a 0.
  const NUMBERS = ['aggregation_number', 'pdc_assessment_ns', 'pdc_extension_ns', 'pdc_seed', 'salt_molar',
                   'box_margin_nm', 'initial_z_nm', 'contact_nm', 'selection_threshold_fraction',
                   'snapshot_interval_ns', 'snapshot_cap'];
  // The catalogue publishes the settings under the builders' names; the panel's controls carry the pipeline's.
  const DEFAULT_ALIASES = {assessment_ns: 'pdc_assessment_ns', extension_ns: 'pdc_extension_ns',
                           placement_mode: 'pdc_placement_mode'};
  let catalogue = null, detergents = [], chosen = new Map();
  let mounted = false, mounting = null, generation = 0;
  // The coverage estimate is the server's answer. `estimateState` is the last one rendered; `estimateRequest`
  // numbers the questions asked, so the answer to an older question can be recognised and dropped rather than put
  // on screen -- a reader moving the count must not see a slow earlier answer land on a newer question.
  let estimateState = {kind: 'idle', summary: '', body: null, reason: ''};
  let estimateRequest = 0;

  // Which generator places the detergents, and it is a choice a reader can see: `lattice` initialises a
  // pre-assembled micelle around the protein (CHARMM-GUI's Micelle Builder), so the belt is exactly the count
  // that was asked for; `self-assembly` places that many at random and lets CG MD settle the belt (MemProtMD's
  // route). The adapter's own default is the pre-assembled one and the select leads with it.
  const PREASSEMBLED = 'lattice';
  const placementMode = () => field('pdc_placement_mode')?.value || PREASSEMBLED;
  const preassembled = () => placementMode() === PREASSEMBLED;
  // Today's date as YYYYMMDD: the seed a build falls back to. It makes a build reproducible and two of a day's
  // builds comparable without anyone choosing a number, and it sits inside the adapter's own range.
  function todaySeed() {
    const now = new Date();
    return Number(`${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`);
  }

  const detergent = () => chosen.get(field('molecule_id').value) || null;
  const templateEntry = () => (catalogue?.templates || []).find(item => item.id === field('template').value) || null;
  // The protein entry and the chains it declares: a deposited OPM entry can be an assembly (1AT9 is a trimer), and
  // the catalogue is where that list is read. Absent `chains` means the entry states none, which is not the same as
  // an empty selection -- the whole structure is simulated, as it was before the picker existed.
  const proteinEntry = () => (catalogue?.proteins || []).find(item => item.id === field('protein').value) || null;
  const chainEntries = () => proteinEntry()?.chains || [];
  // The subunit ticks: one checkbox per declared chain, each carrying the chain id as its value. Read through
  // `form.elements` rather than a pdc-only id, because `test_dom_ids.py` renders only `/` and a panel-only id must
  // not appear in a selector. A ticked box is part of the selection; none ticked is the empty selection the gate
  // refuses rather than a run with nothing to build.
  const chainBoxes = () => [...form.elements].filter(el => el.name === 'protein_chains');
  const selectedChains = () => chainBoxes().filter(el => el.checked).map(el => el.value);
  const backmapping = () => !!field('backmap')?.checked;
  // The select's option value is the catalogue entry's id (`DDM:DDM`), which is what the Complexes panel's own picker
  // carries; what a run is *prepared* with is the template file, and `pdc.prepare`/`pdc.readiness` resolve that path
  // against the project root. So the path travels from the entry, never from the option's value.
  const templatePath = () => templateEntry()?.template || '';

  function store() {
    storage.set('pdc-form', Object.fromEntries([...form.elements].filter(el => el.name).map(el => [el.name, el.value])));
  }

  function describeProtein(entry) {
    const thickness = entry.half_thickness_nm != null ? `half-thickness ${entry.half_thickness_nm} nm`
                                                      : 'no membrane annotation';
    return `${entry.name} · ${entry.source} · ${thickness}`;
  }

  function describeDetergent() {
    const item = detergent();
    say('.new-pdc-detergent', item
      ? `${item.name} · filed under ${item.registry_name}`
      : 'No molecule in molecules/ is in detergents.json, so there is nothing this panel can build a belt from.');
  }

  function describeTemplate() {
    const item = templateEntry();
    const parts = item ? [...item.limitations] : [];
    if (item && !item.files_present) parts.push('a build from it would stop at validation rather than later');
    say('.new-pdc-limitation', parts.join(' · '));
  }

  async function loadCatalogue() {
    if (catalogue) return catalogue;
    catalogue = await cachedApi('/api/pdc/catalog', {maxAge: 60000});
    const templates = catalogue.templates || [], proteins = catalogue.proteins || [];
    const templateSelect = field('template'), proteinSelect = field('protein');
    const wantedTemplate = templateSelect.value || saved().template || '';
    const wantedProtein = proteinSelect.value || saved().protein || '';
    templateSelect.replaceChildren(...(templates.length
      ? templates.map(item => new Option(`${item.name} · ${item.registered_type || 'unregistered'}`, item.id))
      : [new Option('No detergent template is registered', '')]));
    if ([...templateSelect.options].some(option => option.value === wantedTemplate)) templateSelect.value = wantedTemplate;
    // An empty micelle is in scope, so the list leads with the absence of a protein.
    proteinSelect.replaceChildren(new Option('No protein · empty micelle', ''),
      ...proteins.map(item => new Option(describeProtein(item), item.id)));
    if ([...proteinSelect.options].some(option => option.value === wantedProtein)) proteinSelect.value = wantedProtein;
    describeTemplate();
    return catalogue;
  }

  async function loadDetergents() {
    const select = field('molecule_id');
    const wanted = select.value || saved().molecule_id || '';
    const payload = await guarded('detergents', () => cachedApi('/api/detergents', {maxAge: 10000}));
    if (payload === DROP) return;
    detergents = payload.detergents || [];
    chosen = new Map(detergents.map(item => [item.id, item]));
    select.replaceChildren(new Option(detergents.length ? 'Select a detergent' : 'No detergent from the registry', ''),
      ...detergents.map(item => new Option(`${item.name} · ${item.registry_name}`, item.id)));
    select.value = chosen.has(wanted) ? wanted : (detergents[0]?.id || '');
    describeDetergent();
  }

  async function loadMappings() {
    const select = field('mapping_candidate');
    const molecule = field('molecule_id').value;
    const wanted = select.value || saved().mapping_candidate || '';
    if (!molecule) { select.replaceChildren(new Option('Choose a detergent first', '')); return; }
    select.replaceChildren(new Option('Looking for saved mappings…', ''));
    let candidates = [];
    try {
      const result = await cachedApi(`/api/mappings?view=summary&molecule_id=${encodeURIComponent(molecule)}`,
                                     {maxAge: 10000});
      candidates = result.candidates || [];
    } catch (error) {
      select.replaceChildren(new Option('The mapping list could not be read', ''));
      return;
    }
    select.replaceChildren(new Option(candidates.length ? 'No mapping: a build records centres-only' : 'No saved mapping for this detergent', ''),
      ...candidates.map(candidate => {
        const option = new Option(`${candidate.name} · ${candidate.file}`, candidate.file);
        option.disabled = !!candidate.error;
        return option;
      }));
    select.value = mappingFor(molecule, wanted, candidates);
  }

  // Which mapping the panel hands the form, and therefore the preview and the run: the detergent's own first saved
  // mapping, so the picture is made of the beads that mapping declares. It reached the writer as a centres-only
  // frame until 2026-10-14 -- one point per detergent, no moleculetype, hence no types -- which is why every bead
  // on this detergent's preview came back `family not stated`; the frame the reader asked to see carrying its own
  // families is the mapping's beads, and a build with no mapping is a real build rather than the default.
  //
  // A reader who chooses it means it, so the choice is remembered per detergent (`'none'` for the centres-only
  // option) and never defaulted over -- including when the reader moves to another detergent, whose own first
  // mapping is then the default in its turn.
  const MAPPING_NONE = 'none';
  const mappingChoices = () => storage.get('pdc-mapping-choice', {}) || {};
  function mappingFor(molecule, remembered, candidates) {
    if (remembered && candidates.some(candidate => candidate.file === remembered)) return remembered;
    const chosen = mappingChoices()[molecule];
    if (chosen !== undefined) {
      return chosen !== MAPPING_NONE && candidates.some(candidate => candidate.file === chosen) ? chosen : '';
    }
    const usable = candidates.find(candidate => !candidate.error);
    return usable ? usable.file : '';
  }
  function rememberMapping() {
    storage.set('pdc-mapping-choice',
                {...mappingChoices(), [field('molecule_id').value]: field('mapping_candidate').value || MAPPING_NONE});
  }

  function fillDefaults() {
    const defaults = catalogue?.defaults || {};
    for (const [key, value] of Object.entries(defaults)) {
      const input = field(DEFAULT_ALIASES[key] || key);
      if (input && input.value === '') input.value = value;
    }
  }

  // Which subunits the run simulates. The build, the estimate and the back-map all take the file, so the selection
  // has to reach all three -- a picker that does not move the estimate would describe a different structure than the
  // one simulated, which is the defect this guards against. The default is every chain the entry declares.
  function describeChains() {
    const chains = chainEntries(), chosen = selectedChains(), hasProtein = !!field('protein').value;
    if (!hasProtein) { say('.new-pdc-subunits-note', ''); return; }
    say('.new-pdc-subunits-note', chains.length
      ? `${chosen.length} of ${chains.length} subunits selected`
        + (chosen.length ? `: ${chosen.join(', ')}` : ' — choose at least one')
        + '. The build, the estimate and the back-map all use this selection.'
      : 'This entry states no chains, so the whole structure is simulated.');
  }

  function syncChains() {
    const block = pdcNode('.new-pdc-subunits'), list = pdcNode('.new-pdc-chain-list');
    if (!block || !list) return;
    const chains = chainEntries(), hasProtein = !!field('protein').value;
    // A tick on a chain this entry still has keeps its place; a newly chosen entry defaults to every chain, so the
    // default run is still the whole file.
    const keep = new Set(selectedChains());
    block.hidden = !(hasProtein && chains.length);
    list.replaceChildren(...chains.map(chain => {
      const label = document.createElement('label');
      label.className = 'new-pdc-chain';
      const box = document.createElement('input');
      box.type = 'checkbox'; box.name = 'protein_chains'; box.value = chain;
      box.checked = keep.size ? keep.has(chain) : true;
      const text = document.createElement('span'); text.textContent = chain;
      label.append(box, text);
      return label;
    }));
    describeChains();
  }

  // The count is an input in both modes -- it is the belt's size with a protein and the micelle's without -- and
  // what changes with the protein choice is what is worth reading beside it. The estimate is the server's to size
  // and the experimental number is the registry's own; neither is computed here.
  function syncSummary() {
    const item = detergent(), hasProtein = !!field('protein').value;
    const count = field('aggregation_number').value || '—';
    const mapping = field('mapping_candidate');
    setText(summary('detergent'), item ? item.name : 'Select a detergent');
    setText(summary('mapping'), mapping.value
      ? (mapping.selectedOptions[0]?.textContent || mapping.value) : 'None: centres-only recorded');
    setText(summary('protein'), hasProtein
      ? (field('protein').selectedOptions[0]?.textContent || field('protein').value) : 'none · empty micelle');
    const chains = chainEntries(), chosen = selectedChains();
    setText(summary('subunits'), !hasProtein ? 'n/a · empty micelle'
      : chains.length ? `${chosen.length}/${chains.length} · ${chosen.join(', ') || 'none'}`
      : 'whole structure');
    setText(summary('count'), String(count));
    setText(summary('sampling'), `${field('pdc_assessment_ns').value || '—'} ns assessment · `
      + `${field('pdc_extension_ns').value || '—'} ns extension`);
    const belt = pdcNode('.new-pdc-belt-block'), empty = pdcNode('.new-pdc-empty-block');
    if (belt) belt.hidden = !hasProtein;
    if (empty) empty.hidden = hasProtein;
    say('.new-pdc-count-label', hasProtein ? 'Detergents in the belt' : 'Detergents in the micelle');
    say('.new-pdc-config-title', hasProtein ? 'Detergent belt and sampling' : 'Micelle and sampling');
    say('.new-pdc-estimate-label', hasProtein ? 'Estimate' : 'Experiments');
    say('.new-pdc-workflow-note', hasProtein
      ? "With a protein, steps 3 and 5 use the protein's hydrophobic surface."
      : "Empty micelle: step 3 is the micelle on its own, and step 5's protein clause does not apply.");
    pdcNode('.new-pdc-selfassembly')?.classList.toggle('optional', !hasProtein);
    // The choice has to mean something on the screen, so the strip, the count's own note and the review all say
    // which style is in force. A pre-assembled belt is the count asked for; a self-assembled one starts there.
    const pre = preassembled();
    say('.new-pdc-placement-note', pre
      ? 'Pre-assembled micelle (CHARMM-GUI style): the detergents are initialised in a micelle structure, so the '
        + (hasProtein ? 'belt is exactly the count you ask for.' : 'micelle is exactly the count you ask for.')
      : 'Self-assembly (MemProtMD): the detergents start at random and CG MD settles the '
        + (hasProtein ? 'belt, so the count is where the belt starts rather than where it ends.'
                      : 'micelle, so the count is where the micelle starts rather than where it ends.'));
    const step = pdcNode('.new-pdc-selfassembly');
    if (step) {
      step.querySelector('strong').textContent = pre ? (hasProtein ? '3 · Place the belt' : '3 · Build the micelle')
                                                     : '3 · Self-assemble';
      step.querySelector('span').textContent = pre
        ? (hasProtein
            ? "Detergent molecules are initialised as a pre-assembled micelle around the protein: the belt is "
              + "exactly the count you ask for, as CHARMM-GUI's Micelle Builder builds it."
            : "The micelle is initialised pre-assembled with exactly the count you ask for, as CHARMM-GUI's Micelle "
              + 'Builder builds it.')
        : (hasProtein
            ? 'Detergents are placed at random around the protein, then CG MD lets the belt find its own '
              + "arrangement — MemProtMD's self-assembly route. The count is where the belt starts, not where it ends."
            : "The detergents start at random, then CG MD settles the micelle — MemProtMD's self-assembly route.");
    }
    say('.new-pdc-estimate-note', pre
      ? (hasProtein
          ? `Pre-assembled micelle: the belt is exactly the ${count} detergents you ask for. The coverage number is `
            + "a flat-area sizing of that input; the run's own assessment, not this panel, decides whether a micelle formed."
          : `Pre-assembled micelle: the micelle is initialised with exactly the ${count} detergents you ask for.`)
      : (hasProtein
          ? `Self-assembly: the belt starts from ${count} detergents placed at random and CG MD settles it, so the `
            + "final belt size is the MD's to decide. The coverage number sizes the starting count."
          : `Self-assembly: the ${count} detergents start at random and CG MD settles the micelle.`));
    setText(summary('placement'), pre ? 'Pre-assembled micelle · CHARMM-GUI' : 'Self-assembly · MemProtMD');
    setText(summary('seed'), field('pdc_seed').value || 'not set — the run cannot start');
    // What the run will and will not produce, stated in the review so a reader cannot mistake a run without
    // back-mapping for one with it. The workflow strip's own step says the same.
    const backmap = backmapping();
    setText(summary('backmap'), backmap
      ? 'CG2AT2 to atomistic (−o align)'
      : 'off — the run stops coarse-grained, with no atomistic structure produced');
    say('.new-pdc-backmap-note', backmap
      ? 'On: the extended CG state is converted to atomistic with CG2AT2 (-o align).'
      : 'Off: the back-map stage records skipped and the run stops coarse-grained, with no atomistic structure produced.');
    const backStep = pdcNode('.new-pdc-backmap-step');
    if (backStep) {
      backStep.querySelector('strong').textContent = backmap ? '6 · Extend, then back-map' : '6 · Extend (no back-map)';
      backStep.querySelector('span').textContent = backmap
        ? 'Continuation from the surviving checkpoint, then CG2AT2 with -o align: the final CG state becomes atomistic.'
        : 'Continuation from the surviving checkpoint only. Back-mapping is switched off, so the run stops '
          + 'coarse-grained and produces no atomistic structure.';
    }
    const number = item && item.aggregation_number != null ? String(item.aggregation_number) : null;
    // The estimate is the server's: the review shows the answer the route gave (or its refusal), and with no
    // protein there is no slab to size, so the detergent's own measured micelle size stands instead.
    setText(summary('estimate'), hasProtein
      ? (estimateState.summary || '—')
      : `experimental aggregation number ${number ?? 'not recorded yet'}`);
    say('.new-pdc-empty-number', number ?? '— not recorded yet');
    say('.new-pdc-empty-count', String(count));
  }

  // The coverage estimate the plan asks for, rendered from the route's answer rather than computed here: the
  // numbers, the method the route states and its caveat, or -- when the route refuses -- the route's own reason.
  // No arithmetic of the panel's own reaches the screen: `fraction`, `needed` and the areas are the server's, and
  // all this does is format them. The two initialisation styles keep their own sentences (`.new-pdc-estimate-note`,
  // set in `syncSummary`), so a pre-assembled belt still *is* the count and a self-assembled one still starts there.
  function renderEstimate() {
    const verdict = pdcNode('.new-pdc-verdict'), table = pdcNode('.new-pdc-estimate-table');
    const state = estimateState;
    if (state.kind === 'answer') {
      const body = state.body;
      const fraction = Number(body.fraction);
      const percent = Math.round(fraction * 100);
      const enough = fraction >= 1;
      if (verdict) {
        verdict.className = `new-pdc-verdict ${enough ? 'enough' : 'short'}`;
        verdict.textContent = enough
          ? `${body.requested} detergents cover the apolar slab (${percent}%).`
          : `${body.requested} detergents cover about ${percent}% of the apolar slab.`;
      }
      say('.new-pdc-shortfall', enough ? ''
        : `The estimate asks for about ${Math.round(body.needed)}; below that, expect bare patches rather than a belt.`);
      say('.new-pdc-apolar', `${Number(body.apolar_area_nm2).toFixed(1)} nm²`);
      say('.new-pdc-head', `${Number(body.head_area_nm2).toFixed(3)} nm²`);
      say('.new-pdc-need', `${Math.round(body.needed)} detergents`);
      say('.new-pdc-have', `${(fraction * 100).toFixed(1)}%`);
      say('.new-pdc-method', body.method || '');
      say('.new-pdc-caveat', body.caveat || '');
      if (table) table.hidden = false;
      return;
    }
    // A refusal states the server's reason and nothing else: no number is shown beside it, so the box can never be
    // read as a sizing the panel worked out, and it is never left blank.
    if (verdict) {
      verdict.className = state.kind === 'refused' ? 'new-pdc-verdict refused' : 'new-pdc-verdict';
      verdict.textContent = state.kind === 'refused' ? state.reason
        : state.kind === 'loading' ? 'Sizing the belt from the protein’s transmembrane slab…'
        : 'Choose a protein and a detergent to size the belt.';
    }
    say('.new-pdc-shortfall', '');
    say('.new-pdc-method', '');
    say('.new-pdc-caveat', '');
    if (table) table.hidden = true;
  }

  // One question, one request: which protein, which detergent, how many. The question is numbered, and an answer
  // whose number is no longer the latest is dropped -- that is what keeps a slow earlier request from overwriting
  // the answer to a later one while the reader moves the count.
  async function loadEstimate() {
    const entry = field('protein').value, molecule = field('molecule_id').value;
    const mine = ++estimateRequest;
    if (!entry || !molecule) {
      estimateState = {kind: 'idle', summary: '', body: null, reason: ''};
      renderEstimate(); syncSummary();
      return;
    }
    // The estimate must describe what will be simulated, so the same subunit selection goes with the question. An
    // entry that declares chains but has none chosen is a run that cannot start; there is no honest slab to size.
    const chains = selectedChains();
    if (chainEntries().length && !chains.length) {
      estimateState = {kind: 'idle', summary: '', body: null, reason: ''};
      renderEstimate(); syncSummary();
      return;
    }
    estimateState = {kind: 'loading', summary: 'Sizing…', body: null, reason: ''};
    renderEstimate(); syncSummary();
    const query = new URLSearchParams({molecule_id: molecule, aggregation_number: field('aggregation_number').value});
    // Only a whole-file run omits this: a present selection is always sent, so the numbers beside it are the ones
    // for the structure the run will build.
    if (chains.length) query.set('chains', chains.join(','));
    // A catalogue id can be an absolute path (an imported structure lives outside the repository), and the route
    // reads such a path with its leading slash stripped: `catalogue_protein` compares both sides without one. That
    // is also the only spelling that answers directly -- a percent-encoded leading slash decodes to `//` in the
    // path, and the server answers that with a redirect rather than the estimate.
    const entry_id = String(entry).replace(/^\/+/, '');
    let response, body = {};
    try {
      response = await fetch(`/api/pdc/proteins/${encodeURIComponent(entry_id)}/encapsulation?${query}`);
      body = await response.json().catch(() => ({}));
    } catch (error) {
      if (mine !== estimateRequest) return;
      estimateState = {kind: 'refused', summary: 'estimate unavailable', body: null,
                       reason: 'The estimate could not be read: the coordinator did not answer.'};
      renderEstimate(); syncSummary();
      return;
    }
    if (mine !== estimateRequest) return;
    if (!response.ok) {
      const reason = body.error || `the estimate was refused (status ${response.status})`;
      estimateState = {kind: 'refused', summary: reason, body: null, reason};
    } else {
      estimateState = {kind: 'answer', body,
                       summary: `about ${Math.round(Number(body.fraction) * 100)}% of the apolar slab`, reason: ''};
    }
    renderEstimate(); syncSummary();
  }

  // What the panel can see and the server cannot: a build places detergents at random, so a run with no seed is not
  // comparable with another and the pipeline requires one. Saying so here is the difference between a disabled button
  // and a button that lies.
  function gate() {
    if (!field('molecule_id').value) {
      return 'Choose a detergent: this panel offers only what detergents.json files, and molecules/ has none of them.';
    }
    if (!field('template').value) return 'Choose a detergent template: the build places the detergent the template names.';
    // Which subunits is a choice the run has to carry: with none chosen there is no protein to build, and the
    // estimate beside it would describe a structure nobody asked for.
    if (field('protein').value && chainEntries().length && !selectedChains().length) {
      return 'Choose at least one subunit: the build, the estimate and the back-map all use this selection.';
    }
    if (!String(field('pdc_seed').value || '').trim()) {
      return 'Choose a random seed. Detergents are placed at random, so a build with no seed cannot be compared with another.';
    }
    return '';
  }

  async function checkReadiness() {
    const mine = ++generation;
    $('#start-run').disabled = true;
    syncSummary();
    const blocker = gate();
    if (blocker) {
      setText($('#review-status'), 'Action required'); $('#review-status').dataset.ready = 'false';
      setText($('#readiness'), blocker); setText($('#launch-blocker'), blocker);
      return;
    }
    const query = new URLSearchParams({run_type: 'pdc', molecule_id: field('molecule_id').value,
                                       protein: field('protein').value || '', template: templatePath()});
    try {
      const ready = await api('/api/readiness?' + query);
      if (mine !== generation) return;
      const panel = $('#readiness'); panel.replaceChildren();
      setText($('#review-status'), ready.ready ? 'Inputs ready' : (ready.blockers?.length ? 'Action required' : 'Not ready'));
      $('#review-status').dataset.ready = String(!!ready.ready);
      setText($('#launch-blocker'), ready.ready ? '' : (ready.blockers?.[0] || 'Inputs are not ready.'));
      for (const check of ready.checks || []) {
        const row = document.createElement('div'); row.className = 'ready-check';
        const title = document.createElement('strong');
        title.textContent = `${check.ready ? 'Present' : 'Missing'} · ${check.label}`;
        const path = document.createElement('code'); path.textContent = check.path;
        const detail = document.createElement('p'); detail.className = 'hint'; detail.textContent = check.detail;
        row.append(title, path, detail); panel.append(row);
      }
      const reasons = document.createElement('ul');
      for (const reason of ready.blockers || []) { const li = document.createElement('li'); li.textContent = reason; reasons.append(li); }
      panel.append(reasons);
      $('#start-run').disabled = !ready.ready;
    } catch (error) {
      if (mine !== generation) return;
      setText($('#readiness'), error.message); setText($('#launch-blocker'), error.message);
      setText($('#review-status'), 'Readiness unavailable'); $('#review-status').dataset.ready = 'false';
    }
  }

  // The same route the Complexes panel drives, and its honesty: an import reports the half-thickness it found, or
  // says plainly that the file states no membrane. A structure already here is answered from disk, so a second
  // import is a question about a file rather than a second download.
  async function importStructure() {
    const input = field('pdbid'), button = pdcNode('.new-pdc-import-button');
    const pdbid = String(input?.value || '').trim();
    if (!pdbid) return;
    if (button) button.disabled = true;
    say('.new-pdc-import-status', `Fetching ${pdbid} from OPM…`);
    let response, body = {};
    try {
      response = await fetch('/api/pdc/proteins/import', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({pdbid})});
      body = await response.json().catch(() => ({}));
    } catch (error) {
      if (button) button.disabled = false;
      say('.new-pdc-import-status', 'The import could not be read: the coordinator did not answer.');
      return;
    }
    if (button) button.disabled = false;
    if (!response.ok) { say('.new-pdc-import-status', `That import was refused: ${body.error || response.status}`); return; }
    invalidateResource('/api/pdc/catalog');
    catalogue = null;
    await loadCatalogue();
    const entry = (catalogue.proteins || []).find(item => item.name === body.pdbid);
    if (entry) field('protein').value = entry.id;
    if (input) input.value = '';
    say('.new-pdc-import-status', body.already_present
      ? `${body.pdbid} was already here; the list now offers it.`
      : `Imported ${body.pdbid}` + (body.half_thickness_nm != null
          ? ` — its file states a ${body.half_thickness_nm} nm half-thickness.`
          : ' — its file states no membrane, so the build would use the protein-extent box.'));
    syncChains(); syncSummary(); loadEstimate(); checkReadiness(); renderPreviewState();
  }

  // The system preview -----------------------------------------------------------------------------------------
  //
  // The card at the head of the right column, and the one rule that shapes it: **the picture is asked for**. The
  // build's own placement step is not free -- martinize2 is seconds -- so it is not streamed on every keystroke. The
  // reader presses *Derive the preview*; a change to the protein, the subunit ticks or the mapping marks the frame
  // stale rather than redrawing it, because those three decide what would be coarse-grained; and the count, the
  // style, the seed and the box margins re-derive, because the coarse-grained protein is cached on the server and
  // those cost milliseconds. The cache is keyed there by the protein's bytes, the selection and the tool, so the
  // three expensive inputs and no others invalidate it.
  //
  // What is drawn is the server's answer and nothing of this file's: `pdb`, `basis` and `cost` are rendered as they
  // arrive, so the picture and the numbers beside it are one record and the panel never repeats the arithmetic. The
  // bead radii are not this file's either -- `ngl-beads.js` is the one table and the one call, and the file's
  // element column is where each bead's own size class arrives -- so the only number the card owns is the scale it
  // reads them at, which is why `PREVIEW_BEAD_SCALE` is here rather than in the table.
  //: `0.3` -- the model's own radius times this, for reading. This preview drew its beads twice the model's size
  //: until 2026-10-14, when the user reported them too big and they went to half; the same day's second report put
  //: them at 0.3, which is 0.792 / 0.690 / 0.573 A for an R, S and T bead. The radii themselves are the table's, so
  //: a multiplier here is the one number a reader would have to be told about to read a bead's size.
  const PREVIEW_BEAD_SCALE = 0.3;
  const previewNode = selector => pdcNode(`.new-pdc-preview ${selector}`);
  const sayPreview = (selector, text) => { const target = previewNode(selector); if (target) setText(target, text); };
  let previewFrame = null, previewRequest = 0, previewTimer;
  // The stage lives on the host element, the way `pdc.js` keeps its own (`viewer.pdcStage`): one owner, and a test
  // or a console can reach the thing that is drawn without a hook this module would have to publish.
  const previewStage = () => previewNode('.new-pdc-preview-viewer')?.previewStage || null;

  function previewInputs() {
    return {protein: field('protein').value || '', chains: selectedChains(),
            mapping: field('mapping_candidate').value || '', molecule: field('molecule_id').value || '',
            template: templatePath(), count: field('aggregation_number').value || '',
            mode: placementMode(), seed: field('pdc_seed').value || '',
            margin: field('box_margin_nm').value || '', initial_z: field('initial_z_nm').value || ''};
  }
  // What would be coarse-grained, or drawn from another mapping: a change to one of these is a different question,
  // and the frame on screen is no longer this form's. Everything the reader can still move without new
  // coarse-graining re-derives instead.
  const previewExpensive = inputs => `${inputs.protein}|${inputs.chains.join(',')}|${inputs.mapping}|${inputs.molecule}`;
  const previewCheap = inputs => [inputs.count, inputs.mode, inputs.seed, inputs.margin, inputs.initial_z,
                                  inputs.template].join('|');

  function seconds(value) {
    const count = Number(value) || 0;
    return `${count >= 1 ? count.toFixed(1) : count.toFixed(3)} s`;
  }
  const kilobytes = bytes => `${Math.max(1, Math.round((Number(bytes) || 0) / 1024))} KB`;

  function describeFrame(basis) {
    const protein = basis?.protein
      ? `${basis.protein}${(basis.chains || []).length ? ` chains ${basis.chains.join('+')}` : ''}`
      : 'no protein (empty micelle)';
    const style = basis?.placement_mode === 'self-assembly' ? 'self-assembly' : 'pre-assembled micelle';
    return `${protein} · ${style} · ${basis?.aggregation_number} detergents · seed ${basis?.seed}`;
  }

  // The cost sentence is the server's own measurement, not the plan's headline: the numbers a reader sees are the
  // ones this derive paid. What the coarse-graining is (and that it is cached) is stated in the card's disclosure,
  // where it belongs, so the row can stay a measurement.
  function costSentence(cost, basis) {
    const placement = `placement ${seconds(cost.placement_seconds)}`;
    const mapping = cost.detergent_seconds ? ` · mapping to beads ${seconds(cost.detergent_seconds)}` : '';
    if (!basis?.protein_beads) return `no coarse-graining — the micelle is placed directly: ${placement}${mapping}`;
    return cost.cg_cached
      ? `the coarse-grained protein was already cached (${kilobytes(cost.cg_bytes)}) · ${placement}${mapping}`
      : `martinize2 ${seconds(cost.coarse_graining_seconds)} (${basis.protein_beads} beads) · ${placement}${mapping}`;
  }

  function keptSentence(cost, basis) {
    return basis?.protein_beads
      ? `the coarse-grained protein, in this workspace's preview/cg/${cost.cg_key} (${kilobytes(cost.cg_bytes)}); `
        + 'the frames are not kept — a run re-derives its own snapshot'
      : 'nothing: an empty micelle coarse-grains nothing, and the frames are not kept';
  }

  function renderPreviewState() {
    const state = previewNode('.new-pdc-preview-state');
    if (!state || !previewFrame) return;
    const stale = previewExpensive(previewFrame.inputs) !== previewExpensive(previewInputs());
    state.classList.toggle('stale', stale);
    if (previewFrame.refused) {
      state.textContent = stale
        ? 'The protein, the subunits or the mapping have changed since this refusal — derive it again.'
        : (previewFrame.unreadable
            ? 'No answer came back to read; the sentence above says so.'
            : 'The build refuses these inputs; the sentence above is its own.');
      return;
    }
    state.textContent = stale
      ? 'The protein, the subunits or the mapping have changed since this frame was derived — derive it again.'
      : (previewCheap(previewFrame.inputs) !== previewCheap(previewInputs())
          ? 'Derived for the inputs below; the count, the style, the seed or the box have moved since.'
          : 'Derived for the inputs on this form.');
  }

  function previewQuery(inputs) {
    const query = new URLSearchParams({template: inputs.template, molecule_id: inputs.molecule,
                                       aggregation_number: inputs.count, placement_mode: inputs.mode,
                                       pdc_seed: inputs.seed});
    // A catalogue id can be an absolute path for an imported structure, and the route reads such a path with its
    // leading slash stripped -- the same spelling the estimate's own call uses.
    if (inputs.protein) query.set('protein', String(inputs.protein).replace(/^\/+/, ''));
    if (inputs.chains.length) query.set('chains', inputs.chains.join(','));
    if (inputs.mapping) query.set('mapping_candidate', inputs.mapping);
    if (inputs.margin) query.set('box_margin_nm', inputs.margin);
    if (inputs.initial_z) query.set('initial_z_nm', inputs.initial_z);
    return query;
  }

  function showPreviewFrame(pdb) {
    const host = previewNode('.new-pdc-preview-viewer');
    if (!host || typeof NGL === 'undefined') return;
    // The stage is built the moment there is something to draw, and asked to resize on a tab show and a window
    // change: NGL sizes its drawing buffer when the stage is built and only recomputes it when asked, so a stage
    // built at one width keeps that buffer inside a host that later grows.
    if (!host.previewStage) host.previewStage = new NGL.Stage(host, {backgroundColor: 'white'});
    const stage = host.previewStage;
    stage.removeAllComponents();
    // The guess is off, not optional. A coarse-grained bead has no element and no covalent radius, so NGL's
    // distance-based `inferBonds` draws head beads onto tail beads -- measured in `pdc.js` at 90 bonds on a frame
    // the model bonds 60 ways. The file carries the model's own bonds as CONECT records whenever the build has a
    // mapping; when it carries none (a centres-only build, one bead per molecule) there is no bond to draw at all.
    stage.loadFile(new Blob([pdb], {type: 'text/plain'}), {ext: 'pdb', inferBonds: 'none'}).then(component => {
      applyBeadRadii(component.structure, {scale: PREVIEW_BEAD_SCALE});
      // Both of the module's answers go on the one representation: the radius each bead's own size class gives it,
      // and the colour its own type family gives it -- `BEAD_FAMILY_PARAMETERS` colours from the family code the
      // writer put in the file's b-factor column, over a fixed domain so a bead's colour is its family's.
      component.addRepresentation('ball+stick', {...BEAD_RADIUS_PARAMETERS, ...BEAD_FAMILY_PARAMETERS});
      component.autoView();
      stage.handleResize();
    }).catch(error => sayPreview('.new-pdc-preview-basis',
                                 `The frame the server sent could not be drawn: ${error.message || error}`));
  }

  function renderPreviewFrame(body) {
    const basis = body.basis || {}, cost = body.cost || {}, box = basis.box_nm || [];
    const viewer = previewNode('.new-pdc-preview-viewer'), refusal = previewNode('.new-pdc-preview-refusal');
    if (refusal) { refusal.hidden = true; refusal.textContent = ''; }
    if (viewer) viewer.hidden = false;
    showPreviewFrame(body.pdb || '');
    sayPreview('.new-pdc-preview-basis', `Placement for ${describeFrame(basis)} · `
      + `${Number(basis.beads).toLocaleString()} beads · box ${box.map(value => Number(value).toFixed(2)).join(' × ')} nm `
      + '· before any dynamics, so no solvent and no ions'
      + (basis.clearance_nm != null ? ` · clearance from the protein ${Number(basis.clearance_nm).toFixed(3)} nm` : ''));
    sayPreview('.new-pdc-preview-from', describeFrame(basis));
    sayPreview('.new-pdc-preview-beads', `${Number(basis.beads).toLocaleString()} beads `
      + `(${kilobytes((body.pdb || '').length)} of PDB) · `
      + (basis.detergent_representation === 'one centre per molecule'
          ? 'one centre per detergent: this build records no bead model'
          : "the mapping's beads, bonded the model's way"));
    sayPreview('.new-pdc-preview-box', `${box.map(value => Number(value).toFixed(2)).join(' × ')} nm — the box the build `
      + 'writes, before equilibration changes it'
      + (basis.band_radius_nm ? ` · the belt is a band of radius ${Number(basis.band_radius_nm).toFixed(2)} nm in the membrane plane` : ''));
    sayPreview('.new-pdc-preview-cost', costSentence(cost, basis));
    sayPreview('.new-pdc-preview-kept', keptSentence(cost, basis));
    renderPreviewState();
  }

  // The card's own sentence about why it has no picture. A refusal names the step that refused when the answer says
  // which one; an answer that never arrived, or that a browser cannot parse, is not a refusal at all -- those callers
  // pass their own headline rather than have the card claim the builder refused something it was never asked about.
  function refusalHeadline(body) {
    const step = body?.step;
    return `No picture: ${step ? `the ${step} step refuses` : 'the builder refuses'} these inputs. `
      + 'Its own reason is:';
  }

  // A refusal the builder sent with no sentence of its own. It is still a refusal, and the one thing the answer does
  // say is which step refused, so the card says that step. The phrase it used to fall back on -- "the build gave no
  // reason" -- named nothing and cited no gate, which is how the user's 4iar refusal arrived with no reason in it.
  function reasonlessRefusal(body) {
    const step = body?.step;
    return step ? `the ${step} step refused these inputs and named no reason of its own`
                : 'the build refused these inputs and named no reason of its own';
  }

  function renderPreviewRefusal(reason, body, headline) {
    const basis = body?.basis || {}, cost = body?.cost || {};
    const viewer = previewNode('.new-pdc-preview-viewer'), refusal = previewNode('.new-pdc-preview-refusal');
    // The canvas belongs to NGL, not to this card: only its components are dropped, so a later frame still has
    // somewhere to draw. Emptying the host is what detaches it, and then no frame can be drawn again.
    previewStage()?.removeAllComponents();
    if (viewer) viewer.hidden = true;
    if (refusal) {
      refusal.hidden = false;
      // The builder's own sentence, and the scope it belongs to: a refusal from the sphere is not a verdict on the
      // protein, because the protein file's own membrane statement is what decides which shape is placed.
      const sphere = !!basis.protein && basis.placement_shape === 'sphere';
      refusal.textContent = (headline || refusalHeadline(body)) + ` ${reason}`
        + (sphere ? ' — this placement is the sphere about the protein’s centroid, the shape a build takes when the '
            + 'protein’s file states no membrane; a file that states one is placed as a band in the membrane plane '
            + 'instead.' : '');
    }
    sayPreview('.new-pdc-preview-basis', 'No picture: the sentence above is the builder’s own, and nothing was drawn.');
    sayPreview('.new-pdc-preview-from', basis.template ? describeFrame(basis) : '—');
    sayPreview('.new-pdc-preview-beads', '—');
    sayPreview('.new-pdc-preview-box', '—');
    sayPreview('.new-pdc-preview-cost', costSentence(cost, basis));
    sayPreview('.new-pdc-preview-kept', keptSentence(cost, basis));
    renderPreviewState();
  }

  async function derivePreview() {
    const inputs = previewInputs();
    const mine = ++previewRequest;
    const state = previewNode('.new-pdc-preview-state');
    if (state) { state.classList.remove('stale'); setText(state, 'Deriving the placement…'); }
    let response, body = {};
    try {
      response = await fetch('/api/pdc/preview/placement?' + previewQuery(inputs));
    } catch (error) {
      if (mine !== previewRequest) return;
      previewFrame = {inputs, refused: true, unreadable: true};
      renderPreviewRefusal('the coordinator did not answer, so there is nothing to draw.', null,
                           'No picture: the preview request failed.');
      return;
    }
    // The answer is read as text and parsed here, rather than through `response.json().catch(() => ({}))`. That
    // catch turned a body this panel cannot read into `{}`, and an empty object has no `valid` -- so the card
    // rendered it as "the builder refuses these inputs" with the missing-reason fallback, which is exactly what the
    // user's 4iar refusal said. A real cause: Python's `json.dumps` writes a float `nan` as the bare token `NaN`,
    // which a browser's `JSON.parse` refuses (it is not JSON), and the preview's answer carried a `nan` clearance
    // because a coarse-grained bead had no position. An unreadable answer is not a verdict on these inputs.
    let unreadable = null;
    try {
      const parsed = JSON.parse(await response.text());
      body = parsed && typeof parsed === 'object' ? parsed : {};
    } catch (error) {
      unreadable = error;
    }
    // An answer to an older question is dropped rather than put on screen: the reader may have moved the count
    // while the coarse-graining ran, and a slow earlier frame landing on a newer question is how a panel lies.
    if (mine !== previewRequest) return;
    if (unreadable) {
      previewFrame = {inputs, refused: true, unreadable: true};
      renderPreviewRefusal(`the server's reply (status ${response.status}) is not JSON this panel can parse, so it `
        + 'is no verdict on these inputs and nothing was drawn.', null,
        'No picture: the answer could not be read.');
      return;
    }
    if (!response.ok) {
      previewFrame = {inputs, refused: true};
      renderPreviewRefusal(body.error || `the preview was refused (status ${response.status}).`, null);
      return;
    }
    previewFrame = {inputs, refused: !body.valid};
    if (body.valid) renderPreviewFrame(body);
    else renderPreviewRefusal((body.reasons || []).join(' ') || reasonlessRefusal(body), body);
  }

  // A cheap change re-derives once a frame exists, debounced so a typed count is one request. An expensive change
  // never does: it is the step the reader is asked to pay for, so it marks the frame stale and says so.
  function previewMoved() {
    renderPreviewState();
    if (!previewFrame) return;
    clearTimeout(previewTimer);
    previewTimer = setTimeout(derivePreview, 250);
  }

  field('molecule_id').addEventListener('change', () => {
    describeDetergent(); store(); renderPreviewState();
    loadMappings().then(() => { syncSummary(); loadEstimate(); return checkReadiness(); }).catch(error => say('.new-pdc-detergent', error.message));
  });
  field('template').addEventListener('change', () => { describeTemplate(); store(); syncSummary(); checkReadiness(); previewMoved(); });
  field('protein').addEventListener('change', () => { syncChains(); store(); syncSummary(); loadEstimate(); checkReadiness(); renderPreviewState(); });
  // The subunit ticks are rebuilt whenever the chosen entry changes, so the listener sits on the group that holds
  // them: a per-box handler would be lost with the box it was bound to. Every tick is a change to the question the
  // estimate answers, so the route is asked again and the numbers move with the choice.
  pdcNode('.new-pdc-chain-list')?.addEventListener('change', () => {
    describeChains(); store(); syncSummary(); loadEstimate(); checkReadiness(); renderPreviewState();
  });
  field('mapping_candidate').addEventListener('change', () => { rememberMapping(); store(); syncSummary(); loadEstimate(); checkReadiness(); renderPreviewState(); });
  // Every number the adapter reads. `input` keeps the summary and the gate current while a value is typed -- a
  // number input fires `change` only on blur, so a gate that listened for that alone would leave the reader looking
  // at a blocker they had already cleared (and one readiness fetch per keystroke is noise, so it is debounced);
  // `change` settles it at once when the field is left.
  for (const name of NUMBERS) {
    const input = field(name);
    if (!input) continue;
    input.addEventListener('input', () => { syncSummary(); store(); refreshReadinessSoon(); });
    input.addEventListener('change', () => { syncSummary(); store(); checkReadiness(); });
  }
  field('aggregation_number').addEventListener('input', loadEstimate);
  field('pdc_placement_mode')?.addEventListener('change', () => { store(); syncSummary(); checkReadiness(); previewMoved(); });
  field('backmap')?.addEventListener('change', () => { store(); syncSummary(); checkReadiness(); });
  pdcNode('.new-pdc-import-button')?.addEventListener('click', importStructure);
  // The preview's own cheap inputs: each of these re-derives a frame that already exists, and the exchange rate is
  // the cache -- the coarse-grained protein is not rebuilt -- which is why these move and the three expensive ones
  // only mark the frame stale.
  field('aggregation_number').addEventListener('input', previewMoved);
  for (const name of ['pdc_seed', 'box_margin_nm', 'initial_z_nm']) field(name)?.addEventListener('input', previewMoved);
  pdcNode('.new-pdc-preview-derive')?.addEventListener('click', derivePreview);
  // NGL sizes its drawing buffer when the stage is built and only recomputes it when asked, so a card that comes
  // back into view -- or a window that grows -- asks. Measured in the mock: a stage built at one width kept a 548 px
  // buffer inside a 759 px host until it was asked to resize.
  window.addEventListener('resize', () => previewStage()?.handleResize());
  document.addEventListener('dashboard:tab', event => {
    if (event.detail?.id === panelIds()['new-run']) previewStage()?.handleResize();
  });
  field('pdbid')?.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); importStructure(); }
  });

  let readinessTimer;
  function refreshReadinessSoon() { clearTimeout(readinessTimer); readinessTimer = setTimeout(checkReadiness, 250); }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    $('#start-run').disabled = true;
    try {
      if (gate()) return;
      const payload = {run_type: 'pdc', molecule_id: field('molecule_id').value,
                       template: templatePath(), protein: field('protein').value || null,
                       label: field('label').value || ''};
      if (field('mapping_candidate').value) payload.mapping_candidate = field('mapping_candidate').value;
      // Which subunits the build prepares the protein from, and whether the run ends atomistic: both are settings
      // the adapter reads, sent only when they mean something -- an empty micelle has no chains to select, and the
      // back-map choice is always stated so a run without it cannot be read as a run with it.
      const chains = selectedChains();
      if (field('protein').value && chains.length) payload.protein_chains = chains;
      payload.backmap = backmapping();
      // The style is a choice the adapter reads through its own placement-mode alias, so it travels under the
      // panel's spelling (`pdc_placement_mode`) exactly as the seed does.
      payload.pdc_placement_mode = placementMode();
      for (const key of NUMBERS) {
        const value = field(key)?.value;
        if (value !== '' && value != null) payload[key] = Number(value);
      }
      await post('/', payload);
      notice('Run queued.');
      selectTab(panelIds().runs);
      if (refreshJobs) await refreshJobs();
    } catch (error) {
      notice(error.message);
    } finally {
      checkReadiness();
    }
  });

  async function mount() {
    if (mounting) return mounting;
    $('#' + panelIds()['new-run']).setAttribute('aria-busy', 'true');
    $('#start-run').disabled = true;
    mounting = (async () => {
      const remembered = saved();
      // The legend the beads are decoded with, filled from `ngl-beads.js`'s one family table at mount.
      renderBeadLegend(pdcNode('.new-pdc-preview .bead-legend'));
      await Promise.all([loadCatalogue(), loadDetergents()]);
      for (const input of [...form.elements].filter(el => el.name)) {
        if (input.value === '' && remembered[input.name] !== undefined && input.tagName !== 'SELECT') {
          input.value = remembered[input.name];
        }
      }
      fillDefaults();
      // The seed defaults to today's date: the adapter requires one, the control sits in a collapsed block, and a
      // build with no seed cannot be compared with another. Cleared by hand it stays empty and the gate names it.
      const seedInput = field('pdc_seed');
      if (seedInput && seedInput.value === '') seedInput.value = String(todaySeed());
      syncChains();
      await loadMappings();
      mounted = true;
      syncSummary();
      loadEstimate();
      checkReadiness();
    })();
    try { await mounting; }
    finally { mounting = null; $('#' + panelIds()['new-run']).setAttribute('aria-busy', 'false'); }
  }

  return {
    mount,
    // The other workspace's controls are not on this page, and a run of this pipeline is not filled in from an
    // existing run yet. Both say so where the click lands rather than doing nothing.
    cloneRun: async () => {
      selectTab(panelIds()['new-run']);
      notice('Cloning is not built for a protein-detergent run: this panel configures one from its own inputs.');
    },
    clearDeletedClone: () => {},
    setCloneSource: () => {},
    openComposition: () => {},
  };
}
