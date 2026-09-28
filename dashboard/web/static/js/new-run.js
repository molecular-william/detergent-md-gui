import { $, $$, storage, setText, notice, api, post, cachedApi, invalidateResource, guarded, DROP } from './shared.js';

// Owns the persisted run form, inherited settings, and readiness checks.
export function createNewRun({ selectTab, refreshJobs, refreshStorage }) {
  const form = $('#run-form');
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
  async function loadStageDefaults() {
    const profile = form.elements.profile.value;
    const run_type=form.elements.run_type.value;
    const result=await cachedApi('/api/defaults?' + new URLSearchParams({profile,run_type}));
    if(run_type!==form.elements.run_type.value || profile!==form.elements.profile.value)return;
    stageDefaults = result;
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
    if($('#new').hidden || !mounted || mounting)return;
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
    $('#new').setAttribute('aria-busy','true');$('#start-run').disabled=true;
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
    finally {mounting=null;$('#new').setAttribute('aria-busy','false');refreshReadiness();}
  }
  document.addEventListener('dashboard:tab',event=>{
    if(event.detail.id!=='new'){++readinessGeneration;clearTimeout(readinessTimer);readinessController?.abort();}
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
