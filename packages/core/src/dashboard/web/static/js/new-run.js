import { $, $$, storage, setText, notice, api, post, cachedApi, CATALOGUE_MAX_AGE, invalidateResource, guarded, DROP, panelIds } from './shared.js';
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

//: The AA run's three dynamics stages, in the order they run. Each has its own duration, timestep, neighbour-list
//: rebuild cadence and Verlet buffer tolerance inside its own stage editor (`#stage-aa-<stage>`).
const AA_STAGES = ['nvt', 'npt', 'production'];

//: The CG run's three legs. Minimisation states a step cap; the two dynamics legs state a duration, a timestep and a
//: neighbour-list cadence. Each editor's facts host is `<host>-facts`.
const CG_STAGES = [
  {host: 'stage-cg-minimization', steps: 'cg_minimization_steps', nstlist: 'cg_minimization_nstlist'},
  {host: 'stage-cg-equilibration', ps: 'cg_equil_ps', dt: 'cg_equil_dt_fs', nstlist: 'cg_equil_nstlist'},
  {host: 'stage-cg-production', ps: 'cg_production_ps', dt: 'cg_production_dt_fs', nstlist: 'nstlist'},
];

//: Every control whose change moves a stage's facts line or the run summary: each AA stage's duration, timestep and
//: neighbour list, and the CG legs' duration, timestep, neighbour list, step cap and the rest of their new settings --
//: a Verlet tolerance or coupling time changes no fact, but it is persisted and refreshed like the numbers it sits by.
const STAGE_SUMMARY_FIELDS = [
  ...AA_STAGES.flatMap(stage => [`aa_${stage}_ps`, `aa_${stage}_dt_fs`, `aa_${stage}_nstlist`]),
  'cg_minimization_steps', 'cg_minimization_nstlist', 'cg_minimization_verlet_buffer_tolerance',
  'cg_equil_ps', 'cg_equil_dt_fs', 'cg_equil_nstlist', 'cg_equil_verlet_buffer_tolerance',
  'cg_equil_tau_t', 'cg_equil_tau_p', 'cg_equil_compressibility',
  'cg_production_ps', 'cg_production_dt_fs', 'nstlist',
];

/** One stage control's number, or null when the control is absent or empty (the pdc form has none of these). */
function stageNumber(form, name) {
  const raw = form?.elements?.[name]?.value;
  const text = String(raw ?? '').trim();
  if (text === '') return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

/** A number grouped as the approved design prints it: thousands separated by a space (`50 000`). */
const groupedNumber = number => number.toLocaleString('en-GB').replace(/,/g, ' ');

/**
 * Write each stage editor's facts line: its duration, timestep, the step count they imply and its neighbour-list
 * cadence -- or, for CG minimisation, its step cap and neighbour list. A collapsed stage still says what it holds. A
 * part whose control is empty is omitted, and a page with none of these elements (the pdc form) is answered without
 * touching anything.
 */
function syncStageSummaries(form) {
  if (!form) return;
  for (const stage of AA_STAGES) {
    const host = document.getElementById(`stage-aa-${stage}-facts`);
    if (!host) continue;
    const ps = stageNumber(form, `aa_${stage}_ps`);
    const dt = stageNumber(form, `aa_${stage}_dt_fs`);
    const nstlist = stageNumber(form, `aa_${stage}_nstlist`);
    const parts = [];
    if (ps !== null) parts.push(`${groupedNumber(ps)} ps`);
    if (dt !== null) parts.push(`${groupedNumber(dt)} fs`);
    if (ps !== null && dt !== null && dt > 0) parts.push(`${groupedNumber(Math.round(ps / (dt / 1000)))} steps`);
    if (nstlist !== null) parts.push(`nstlist ${groupedNumber(nstlist)}`);
    host.textContent = parts.join(' · ');
  }
  for (const stage of CG_STAGES) {
    const host = document.getElementById(`${stage.host}-facts`);
    if (!host) continue;
    const ps = stageNumber(form, stage.ps);
    const dt = stageNumber(form, stage.dt);
    const steps = stageNumber(form, stage.steps);
    const nstlist = stageNumber(form, stage.nstlist);
    const parts = [];
    if (ps !== null) parts.push(`${groupedNumber(ps)} ps`);
    if (dt !== null) parts.push(`${groupedNumber(dt)} fs`);
    if (ps !== null && dt !== null && dt > 0) parts.push(`${groupedNumber(Math.round(ps / (dt / 1000)))} steps`);
    if (steps !== null) parts.push(`${groupedNumber(steps)} steps`);
    if (nstlist !== null) parts.push(`nstlist ${groupedNumber(nstlist)}`);
    host.textContent = parts.join(' · ');
  }
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
  // one fieldset or the other, and neither is a subset of the other: a feature form has no `run_type` and no
  // parameterization select at all, so every AA statement below would throw on its first `form.elements.<name>`.
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
//
// Two run types, and one parameterization selector. A CG run consumes a model -- a saved mapping's revision, or the
// molecule's published Martini 3 reference -- and never fits one; an AA run publishes the reference such a fit is
// made against. The old combined type, the per-run method and the AA-reference picker are gone: the revision records
// the reference it was fitted to, so the form states it read-only and cannot point a model outside its ensemble.
function createEngineNewRun({ form, selectTab, refreshJobs, refreshStorage }) {
  // The atomistic half's fields. They travel in a CG run too -- the adapter mirrors a few into the CG dialect and
  // records the rest as the reference's provenance -- but only an AA run shows them.
  // Each stage's duration, timestep, neighbour-list rebuild cadence and Verlet buffer tolerance. The timestep changes
  // the step count, not the duration; the stage editor's facts line states both. The thermostat (every stage) and,
  // where the stage couples pressure, the barostat are per stage; the hydrogen-mass factor is one for the whole run.
  const AA_COUPLING_FIELDS = [
    'aa_nvt_tcoupl','aa_nvt_tau_t',
    'aa_npt_tcoupl','aa_npt_tau_t','aa_npt_pcoupl','aa_npt_pcoupltype','aa_npt_tau_p','aa_npt_compressibility',
    'aa_production_tcoupl','aa_production_tau_t','aa_production_pcoupl','aa_production_pcoupltype',
    'aa_production_tau_p','aa_production_compressibility'];
  const AA_FIELDS = ['aa_nvt_ps','aa_npt_ps','aa_production_ps',
    'aa_nvt_dt_fs','aa_npt_dt_fs','aa_production_dt_fs',
    'aa_nvt_nstlist','aa_npt_nstlist','aa_production_nstlist',
    'aa_nvt_verlet_buffer_tolerance','aa_npt_verlet_buffer_tolerance','aa_production_verlet_buffer_tolerance',
    'mass_repartition_factor',...AA_COUPLING_FIELDS,
    'temperature_k','pressure_bar','output_interval_ps','box_nm','aa_seed','mdrun_ntomp','mdrun_ranks','mdrun_nb','mdrun_pme','constraints'];
  // The device and the checkpoint cadence are settings of *this host and run*, not of the AA reference a run
  // inherits: they travel with a clone and through a preset, and they are never inherited from a reference record.
  const GPU_FIELDS = ['mdrun_gpu','mdrun_cpt'];
  // The execution additions and the box shape describe how this run executes and what box it builds.
  const RUN_FIELDS = ['box_shape','mdrun_pmefft','mdrun_update','mdrun_tunepme'];
  // The CG production options the Other run options fold offers. Each has a `SETTING_SPECS` bound and is written into
  // `cg-production-v1`; the equilibration leg keeps its own reviewed values. `nstxtcout` and `rlist` have no default,
  // so an empty control leaves GROMACS' own rule (the ps interval and the Verlet buffer) in force. The ten stage-leg
  // numbers are the editors' own fields; a reference and a composition post them too, because their adapters run the
  // same three legs.
  const CG_PRODUCTION_FIELDS = ['nstlog','nstenergy','nstxtcout','xtc_precision','nstcomm','nstlist',
    'verlet_buffer_tolerance','rlist','rcoulomb','rvdw','tau_t','tau_p','compressibility'];
  const CG_STAGE_FIELDS = ['cg_minimization_steps','cg_minimization_nstlist','cg_minimization_verlet_buffer_tolerance',
    'cg_equil_dt_fs','cg_equil_nstlist','cg_equil_verlet_buffer_tolerance','cg_equil_tau_t','cg_equil_tau_p',
    'cg_equil_compressibility','cg_production_dt_fs'];
  const CG_FIELDS = ['cg_equil_ps','cg_production_ps','sasa_probe_nm','cg_seed',
    ...CG_PRODUCTION_FIELDS, ...CG_STAGE_FIELDS];
  // The published sugar reference's own vocabulary (`validation ... sugar_cg.SETTING_SPECS`) plus the production and
  // stage-leg overrides its three legs run: a reference run advertises those, and none of the AA half's settings, so
  // the form posts only what that adapter reads.
  const REFERENCE_FIELDS = ['sugar_entry','cg_equil_ps','cg_production_ps','temperature_k','cg_seed',
    'output_interval_ps','mdrun_ntomp','mdrun_ranks','mdrun_gpu','mdrun_cpt','mdrun_nb','mdrun_pme',
    ...CG_PRODUCTION_FIELDS, ...CG_STAGE_FIELDS];
  // A composition is a CG molecule with a *derived* model, so its settings are the CG dialect without the AA half's
  // durations, the sugar entry or the force field (`execution/adapters/composition.py:SETTING_SPECS`). The form posts
  // only these keys, and a `cg` preset fills the ones it carries.
  const COMPOSITION_FIELDS = ['cg_equil_ps','cg_production_ps','cg_seed','temperature_k','output_interval_ps',
    'mdrun_ntomp','mdrun_ranks','mdrun_gpu','mdrun_cpt','mdrun_nb','mdrun_pme','mdrun_pmefft','mdrun_update',
    'mdrun_tunepme', ...CG_PRODUCTION_FIELDS, ...CG_STAGE_FIELDS];
  // The topology choice is the AA leg's: a CG run consumes a reference that already ran.
  const AA_TOPOLOGY_FIELDS = ['vsite'];
  const AA_ONLY_FIELDS = [...AA_FIELDS, ...GPU_FIELDS, ...RUN_FIELDS, 'force_field', ...AA_TOPOLOGY_FIELDS];
  const REVISION_FIELDS = [...AA_FIELDS, ...GPU_FIELDS, ...RUN_FIELDS, ...CG_FIELDS, 'force_field'];
  // Which controls each run type/kind shows. The hidden ones keep their values -- the payload is filtered by
  // `fieldsFor` rather than by visibility -- because a preset and a clone must not lose a setting to a toggle.
  const AA_SAMPLING = ['aa_nvt_ps','aa_npt_ps','aa_production_ps',
    'aa_nvt_dt_fs','aa_npt_dt_fs','aa_production_dt_fs',
    'aa_nvt_nstlist','aa_npt_nstlist','aa_production_nstlist',
    'aa_nvt_verlet_buffer_tolerance','aa_npt_verlet_buffer_tolerance','aa_production_verlet_buffer_tolerance',
    'constraints'];
  const AA_BUILD = ['pressure_bar','box_nm','box_shape','aa_seed'];
  const REFERENCE_HIDES = ['force_field','sasa_probe_nm'];
  const NO_STORED_COORDINATES = 'this parameterization records no starting coordinates; choose Re-map the AA reference';

  // Persist all controls, including hidden ones inherited from a preset. The run label is suggested until the reader
  // types one; a typed label is persisted and posted, a suggested one is neither.
  let labelEdited = !!storage.get('form', {}).label;
  function formValues() {
    const values = Object.fromEntries([...form.elements].filter(el => el.name).map(el => [el.name, el.value]));
    // Dropping a label nobody typed is what keeps a suggestion from becoming the reader's own value on reload.
    if (!labelEdited) delete values.label;
    return values;
  }

  // The clone ----------------------------------------------------------------------------------------------------
  let pendingModel = null, pendingApplied = false, modelTouched = false;
  function setCloneSource(id, message='') {
    form.elements.clone_of.value = id;
    setText($('#clone-notice'), message || (id ? `Cloning ${id}. Change settings below before starting.` : ''));
    $('#leave-clone').hidden = !id;
    storage.set('form', formValues());
  }
  async function validateCloneSource() {
    const id = form.elements.clone_of.value;
    if (!id) return true;
    try {
      const source = await api(`/api/jobs/${encodeURIComponent(id)}`);
      if (form.elements.clone_of.value !== id) return false;
      // The record names the model the run consumed. On a reloaded clone the reader never saw the source, so its
      // model is the one the form should show; a choice the reader made since outranks it (`modelTouched`).
      if (!modelTouched && !pendingModel) {
        pendingModel = source.parameterization
          || (source.mapping_candidate ? {kind: 'revision', mapping_candidate: source.mapping_candidate} : null);
      }
      return true;
    } catch (error) {
      if (form.elements.clone_of.value !== id) return false;
      if (error.status !== 404) throw error;
      setCloneSource('', `Clone source ${id} is no longer available. Your settings are kept; start a new run when ready.`);
      return false;
    }
  }
  $('#leave-clone').onclick = () => setCloneSource('', 'Your settings are kept for a new run.');

  // The molecule input check --------------------------------------------------------------------------------------
  let moleculeRecords = [];
  //: The saved compositions, as `/api/cg-models` lists them: CG molecules with a derived parameterization. They are
  //: selectable molecules here, and they have no `molecules/` folder, so nothing may inspect them as an AA source.
  let compositionRecords = [];
  const compositionFor = id => compositionRecords.find(record => record.molecule_id === id) || null;
  // Which molecule's input block the reader left open. `showMolecule` re-renders on every molecule selection and
  // every readiness answer, so the open state is kept here rather than left to the <details> element.
  const inputsOpen = new Map();
  let inputsKey = '';
  $('#molecule-inputs')?.addEventListener('toggle', () => {
    if (inputsKey) inputsOpen.set(inputsKey, $('#molecule-inputs').open);
  });

  // The input check: one folded line whose summary carries the verdict and the molecule's facts, with the file
  // list, blockers and notes inside. Closed by default, and each molecule remembers the reader's own state.
  function showMolecule(record) {
    const details = $('#molecule-inputs'), status = $('#molecule-inputs-status'), panel = $('#molecule-details');
    if (!details || !status || !panel) return;
    inputsKey = record?.id || '';
    const open = inputsOpen.get(inputsKey) ?? false;
    if (details.open !== open) details.open = open;
    details.querySelector('.status-dot').dataset.state = !record ? 'pending' : record.valid ? 'ok' : 'warn';
    status.replaceChildren();
    setText($('#run-molecule-summary'), record?.name || 'Select a molecule');
    if (!record) {
      const title = document.createElement('strong'); title.textContent = 'Select a molecule directory'; status.append(title);
      panel.textContent = 'Select an available molecule directory. Missing saved selections must be replaced explicitly.';
      syncVirtualSites(null);
      return;
    }
    const title = document.createElement('strong'); title.textContent = record.valid ? 'Input files consistent' : 'Input files need attention'; status.append(title);
    // Every valid molecule is an AA source, so the atomistic capability is the one both run types check.
    const issues = record.capabilities?.aa_only?.blockers || record.blockers || [];
    const facts = document.createElement('span'); facts.className = 'hint';
    facts.textContent = record.valid ? ` · ${record.atom_count} atoms · ${record.metadata.force_field} · water: ${record.metadata.water_model} · charge: ${record.metadata.net_charge}` : ` · ${issues[0] || record.path}`;
    status.append(facts);
    const list = document.createElement('ul');
    panel.replaceChildren(list);
    for (const name of Object.keys(record.sha256)) {
      const item = document.createElement('li'); item.textContent = `${name} · ${record.sha256[name] ? 'present' : 'missing or unreadable'}`; list.append(item);
    }
    for (const issue of issues) { const item = document.createElement('li'); item.textContent = issue; list.append(item); }
    if (record.inputs?.coordinate_format === 'pdb') {
      const note = document.createElement('p'); note.className = 'hint';
      note.textContent = 'PDB → GRO automatically before simulation. The original PDB is preserved.'; panel.append(note);
    }
    if (record.metadata?.generated) {
      const note = document.createElement('p'); note.className = 'hint';
      note.textContent = `metadata.json generated automatically. ${record.metadata.provenance}`; panel.append(note);
    }
    syncVirtualSites(record);
  }

  // MkVsites derivation: a read-only parameter report for the selected molecule. The panel is inside the folded
  // input check and keeps its last report while the same molecule is selected, so a readiness refresh does not wipe
  // what the reader just asked for.
  let vsiteMolecule = null;
  function syncVirtualSites(record) {
    const panel = $('#molecule-vsites');
    if (!panel) return;
    const id = record?.valid && record.kind !== 'cg' ? record.id : '';
    if (id !== vsiteMolecule) {
      vsiteMolecule = id;
      $('#vsite-report')?.replaceChildren();
      setText($('#vsite-status'), '');
    }
    panel.hidden = !id;
    const button = $('#derive-vsites');
    if (button) button.disabled = false;
  }
  function forceFieldText(report) {
    const ff = report.forcefield || {};
    const sections = [
      ['ffbonded.itp — constraints', 'constraints'],
      ['ffbonded.itp — angle constraints', 'angle_constraints'],
      ['ffnonbonded.itp — dummy masses', 'dummy_masses'],
      ['atomtypes.atp — dummy types', 'atomtypes'],
      ['aminoacids.vsd — constructions', 'vsd'],
    ];
    return sections.filter(([, key]) => (ff[key] || []).length)
      .map(([title, key]) => `# ${title}\n${ff[key].join('\n')}`).join('\n\n');
  }
  function renderVirtualSites(report) {
    const host = $('#vsite-report');
    if (!host) return;
    host.replaceChildren();
    const vsites = report.vsites || [], angles = report.angle_constraints || [], diagnostics = report.diagnostics || [];
    const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
    setText($('#vsite-status'), [
      plural(vsites.length, 'vsite type', 'vsite types'),
      plural(angles.length, 'OH angle constraint', 'OH angle constraints'),
      ...(diagnostics.length ? [plural(diagnostics.length, 'diagnostic', 'diagnostics')] : []),
    ].join(' · '));
    if (!vsites.length && !angles.length) {
      const message = document.createElement('p'); message.className = 'hint';
      message.textContent = 'No MkVsites construct was derivable from this topology.';
      host.append(message);
    } else {
      const snippets = document.createElement('details');
      const summary = document.createElement('summary'); summary.textContent = 'Force-field snippets';
      const pre = document.createElement('pre'); pre.textContent = forceFieldText(report);
      snippets.append(summary, pre); host.append(snippets);
    }
    if (diagnostics.length) {
      const details = document.createElement('details');
      const summary = document.createElement('summary'); summary.textContent = 'Diagnostics';
      const list = document.createElement('ul');
      for (const item of diagnostics) {
        const row = document.createElement('li');
        row.textContent = `${item.level || 'note'}: ${item.message || item}`;
        list.append(row);
      }
      details.append(summary, list); host.append(details);
    }
    const raw = document.createElement('details');
    const rawSummary = document.createElement('summary'); rawSummary.textContent = 'Raw report';
    const rawPre = document.createElement('pre'); rawPre.textContent = JSON.stringify(report, null, 2);
    raw.append(rawSummary, rawPre); host.append(raw);
  }
  $('#derive-vsites')?.addEventListener('click', async () => {
    const id = form.elements.molecule_id.value;
    const button = $('#derive-vsites');
    if (!id || !button) return;
    button.disabled = true;
    setText($('#vsite-status'), 'Deriving…');
    $('#vsite-report')?.replaceChildren();
    try {
      renderVirtualSites(await post(`/api/molecules/${encodeURIComponent(id)}/virtual-sites`, {}));
    } catch (error) {
      setText($('#vsite-status'), error.message);
    } finally {
      button.disabled = false;
    }
  });

  // A composition is a CG molecule, not a folder: it has no AA topology to check and no AA stage to run. The same
  // folded block reports that, in the place the reader looks for the input verdict.
  function showCompositionModel(model) {
    const details = $('#molecule-inputs'), status = $('#molecule-inputs-status'), panel = $('#molecule-details');
    if (!details || !status || !panel) return;
    inputsKey = 'composition:' + model.id;
    const open = inputsOpen.get(inputsKey) ?? false;
    if (details.open !== open) details.open = open;
    details.querySelector('.status-dot').dataset.state = 'ok';
    status.replaceChildren();
    setText($('#run-molecule-summary'), model.molecule_name || model.name || model.molecule_id);
    const title = document.createElement('strong'); title.textContent = 'No AA inputs: derived CG model';
    const facts = document.createElement('span'); facts.className = 'hint';
    facts.textContent = ` · ${model.molecule_name || model.name} · ${model.status || 'candidate-unvalidated'}`;
    status.append(title, facts);
    const note = document.createElement('p'); note.className = 'hint';
    const revision = model.parameterization?.revision ?? 0;
    note.textContent = revision
      ? `This run reads the composition's own immutable geometry and parameterization revision ${revision} (its `
        + 'bonded terms were edited in Combinations). There is no AA stage, no mapping and no fit.'
      : "This run reads the composition's own immutable topology and coordinates. There is no AA "
        + 'stage, no mapping and no fit; the parameterization is derived from the recipe and the head reference.';
    panel.replaceChildren(note);
    syncVirtualSites(null);
  }

  // The run label ------------------------------------------------------------------------------------------------
  //
  // `[molecule]-[AA|CG]-[length]ns-[YYYYMMDD]`, suggested until the reader types one. The length is the total
  // simulated time for the run: NVT + NPT + production for an AA run, equilibration + production for a CG run (the
  // published reference's own durations when that is the model), rounded to 0.1 ns and printed without a trailing
  // `.0`, which is the format the server's fallback uses for an empty label.
  const labelInput = form.elements.label;
  function localDate() {
    const now = new Date();
    return `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`;
  }
  function labelLength() {
    const runType = form.elements.run_type.value, value = name => Number(form.elements[name]?.value);
    const ps = runType === 'aa_only' ? value('aa_nvt_ps') + value('aa_npt_ps') + value('aa_production_ps')
                                     : value('cg_equil_ps') + value('cg_production_ps');
    return Number.isFinite(ps) && ps > 0 ? Math.round(ps / 100) / 10 : null;
  }
  function suggestedLabel() {
    const id = form.elements.molecule_id.value;
    const model = compositionFor(id);
    const name = (model?.molecule_name || model?.name
      || moleculeRecords.find(record => record.id === id)?.name || id || '').trim().replace(/\s+/g, '-');
    if (!name) return '';
    const tag = form.elements.run_type.value === 'aa_only' ? 'AA' : 'CG';
    const length = labelLength();
    return [name, tag, ...(length == null ? [] : [`${length}ns`]), localDate()].join('-');
  }
  function updateSuggestedLabel() {
    if (labelEdited) return;
    const suggestion = suggestedLabel();
    if (suggestion) labelInput.value = suggestion;
  }
  labelInput?.addEventListener('input', () => { labelEdited = true; syncRunSummary(); });
  $('#suggest-label').onclick = () => { labelEdited = false; updateSuggestedLabel(); syncRunSummary(); storage.set('form', formValues()); };

  // The one model selector ---------------------------------------------------------------------------------------
  //
  // A CG run consumes one parameterization of the selected molecule -- a saved mapping's revision, or its published
  // Martini 3 reference. The options are grouped by mapping and carry each revision's engine and date, so one select
  // answers "which model, which revision". The route shapes are the Bond Interactions panel's own, so the two panels
  // name the same models from the same answers.
  const parameterizationSelect = $('#run-parameterization');
  const startingSelect = $('#starting-coordinates');
  let modelCatalog = [], modelsGeneration = 0;
  const selectedModel = () => modelCatalog.find(model => model.key === parameterizationSelect?.value) || null;

  function optionKey(file, revision) {
    return revision === null || revision === undefined ? `draft:${file}` : `revision:${file}:${revision}`;
  }
  function hasCoordinates(revision) {
    return !!(revision?.coordinates && Array.isArray(revision.coordinates.files) && revision.coordinates.files.length);
  }
  /** The model a run record names, matched against what the catalogue holds. `null` when it is not offered. */
  function matchModel(catalog, wanted) {
    if (!wanted) return null;
    if (wanted.kind === 'reference') return catalog.find(model => model.kind === 'reference') || null;
    if (wanted.kind === 'composition') {
      return catalog.find(model => model.kind === 'composition'
        && model.id === (wanted.composition_id || wanted.id)) || null;
    }
    const file = wanted.mapping_candidate || wanted.mapping;
    if (!file) return null;
    const revision = wanted.revision == null ? null : Number(wanted.revision);
    return catalog.find(model => model.kind === 'revision' && model.file === file
                                 && (revision === null ? model.current : model.revision === revision))
        || catalog.find(model => model.kind === 'draft' && model.file === file)
        || null;
  }
  /** What the select answers when nothing is chosen: the first mapping's current revision, else its draft, else the
   * published reference. It only reads -- a mount must never make a revision current. */
  function defaultModel(catalog) {
    return catalog.find(model => model.current) || catalog.find(model => model.kind === 'draft')
        || catalog.find(model => model.kind === 'reference') || null;
  }

  async function loadParameterizations() {
    const generation = ++modelsGeneration;
    const molecule = form.elements.molecule_id.value;
    // The choice is captured before the options are replaced: a refresh of the same molecule must not move the
    // reader's selection back to the first mapping's current revision.
    const wanted = parameterizationSelect?.value || '';
    modelCatalog = [];
    if (!molecule) {
      parameterizationSelect?.replaceChildren(new Option('Select a molecule first', ''));
      applyModel();
      return;
    }
    // A composition's model is derived, not looked up in the mapping store: it is the one the catalog lists for this
    // CG molecule, so the selector has exactly one option and no fetch.
    const composition = compositionFor(molecule);
    if (composition) { fillCompositionModel(composition); return; }
    parameterizationSelect?.replaceChildren(new Option('Reading this molecule\'s parameterizations…', ''));
    let candidates = [];
    try {
      const answer = await cachedApi('/api/mappings?view=summary&molecule_id=' + encodeURIComponent(molecule),
                                     {maxAge: CATALOGUE_MAX_AGE});
      candidates = (answer.candidates || []).filter(candidate => !candidate.error && candidate.file);
    } catch (error) {
      candidates = [];
    }
    const records = new Map();
    await Promise.all(candidates.map(async candidate => {
      const query = new URLSearchParams();
      if (candidate.mapping_content_hash) query.set('content_hash', candidate.mapping_content_hash);
      if (candidate.mapping_hash) query.set('mapping_hash', candidate.mapping_hash);
      if (![...query].length) { records.set(candidate.file, {revisions: []}); return; }
      try {
        records.set(candidate.file, await api('/api/bonded-parameterizations?' + query));
      } catch (error) {
        // The mapping is still offered; its option says the record could not be read rather than claiming a draft.
        records.set(candidate.file, {error: error.message, revisions: []});
      }
    }));
    let reference = null;
    try {
      // A 404 is "this molecule has no published entry", which is an answer and not a failure to report.
      reference = (await cachedApi('/api/mappings/reference/' + encodeURIComponent(molecule),
                                   {maxAge: CATALOGUE_MAX_AGE}))?.model || null;
    } catch (error) {
      reference = null;
    }
    if (generation !== modelsGeneration || molecule !== form.elements.molecule_id.value) return;
    fillModels(candidates, records, reference, wanted);
  }

  /** The composition's current parameterization: revision 0 (the derived model), or a revision edited in Combinations. */
  function fillCompositionModel(model) {
    const key = `composition:${model.id}`;
    const parameterization = model.parameterization || {};
    const revision = parameterization.revision ?? 0;
    const base = parameterization.base || (revision ? 'edited' : 'derived');
    const source = parameterization.source ? ` · ${parameterization.source}` : '';
    const head = model.head_molecule_id ? ` · links to ${model.head_molecule_id}` : '';
    const label = `${base} · revision ${revision} · composition recipe${source}${head}`;
    const group = document.createElement('optgroup');
    group.label = 'Derived composition';
    const option = new Option(label, key);
    option.dataset.kind = 'composition';
    option.dataset.coordinates = 'none';
    group.append(option);
    parameterizationSelect?.replaceChildren(group);
    modelCatalog = [{key, kind: 'composition', id: model.id, moleculeId: model.molecule_id,
                     name: model.molecule_name || model.name, model: parameterization,
                     head_molecule_id: model.head_molecule_id, current: true, hasCoordinates: false,
                     revisionRecord: null}];
    // A clone of a composition run names the same composition; a saved form names whichever model it recorded.
    const pending = matchModel(modelCatalog, pendingModel);
    if (pending) pendingApplied = true;
    if (parameterizationSelect) parameterizationSelect.value = key;
    pendingModel = null;
    applyModel();
  }

  function fillModels(candidates, records, reference, wanted = '') {
    const catalog = [], groups = [];
    for (const candidate of candidates) {
      const record = records.get(candidate.file);
      const name = candidate.name || candidate.file;
      const revisions = [...(record?.revisions || [])].sort((first, second) => second.revision - first.revision);
      const current = record?.summary?.revision ?? null;
      const group = document.createElement('optgroup');
      group.label = name;
      if (revisions.length) {
        for (const item of revisions) {
          const option = new Option(`${name} · Revision ${item.revision} · `
            + `${item.revision === current ? 'current' : 'earlier'} · ${item.engine || 'fit'} · `
            + `${String(item.created_at || '').slice(0, 10) || 'no date recorded'}`, optionKey(candidate.file, item.revision));
          option.dataset.kind = 'revision';
          option.dataset.mapping = candidate.file;
          option.dataset.revision = String(item.revision);
          option.dataset.coordinates = hasCoordinates(item) ? 'stored' : 'none';
          catalog.push({key: option.value, kind: 'revision', file: candidate.file, name, revision: item.revision,
                        current: item.revision === current, hasCoordinates: hasCoordinates(item), revisionRecord: item});
          group.append(option);
        }
      } else {
        const option = new Option(record?.error ? 'Revisions could not be read'
          : 'Draft mapping connectivity (no parameterization)', optionKey(candidate.file, null));
        option.dataset.kind = 'draft';
        option.dataset.mapping = candidate.file;
        option.dataset.coordinates = 'none';
        catalog.push({key: option.value, kind: 'draft', file: candidate.file, name, revision: null,
                      current: false, hasCoordinates: false, revisionRecord: null});
        group.append(option);
      }
      groups.push(group);
    }
    if (reference) {
      const entry = reference.reference_entry || reference.molecule_id;
      const key = `reference:${reference.molecule_id || form.elements.molecule_id.value}`;
      const group = document.createElement('optgroup');
      group.label = 'Published Martini 3 reference';
      const option = new Option(`Martini 3 reference · ${entry}`, key);
      option.dataset.kind = 'reference';
      option.dataset.entry = entry;
      option.dataset.coordinates = 'none';
      catalog.push({key, kind: 'reference', file: reference.file, name: option.text, entry, revision: null,
                    current: false, hasCoordinates: false, revisionRecord: null, model: reference});
      group.append(option);
      groups.push(group);
    }
    modelCatalog = catalog;
    if (!groups.length) {
      parameterizationSelect?.replaceChildren(new Option('No saved parameterization for this molecule', ''));
    } else {
      parameterizationSelect?.replaceChildren(...groups);
      const pending = matchModel(catalog, pendingModel);
      if (pending) pendingApplied = true;
      const restore = catalog.find(model => model.key === wanted) || pending || defaultModel(catalog);
      parameterizationSelect.value = restore ? restore.key : '';
    }
    pendingModel = null;
    applyModel();
  }

  /** The model's kind, which decides the defaults, the settings the form posts, and which fields it shows. */
  function currentKind() {
    if (form.elements.run_type.value === 'aa_only') return 'aa_only';
    const model = selectedModel();
    if (model?.kind === 'reference') return 'reference';
    if (model?.kind === 'composition') return 'composition';
    return 'revision';
  }
  /** The `parameterization` object the payload and the readiness question both use, so they cannot disagree. */
  function parameterizationPayload() {
    const model = selectedModel();
    if (model?.kind === 'reference') return {kind: 'reference', sugar_entry: model.entry};
    if (model?.kind === 'composition') {
      // The revision is the model the panel showed: a run names it, so a later edit cannot change what this run
      // consumes. The catalogue's row carries the current revision; revision 0 is the derived model.
      return {kind: 'composition', composition_id: model.id,
              composition_revision: model.model?.revision ?? 0};
    }
    return {kind: 'revision',
            mapping_candidate: model?.file || '',
            revision: model?.revision ?? null,
            starting_coordinates: startingSelect?.value || 'stored'};
  }

  // The review's rows -------------------------------------------------------------------------------------------
  function describeAaSource() {
    if (form.elements.run_type.value === 'aa_only') return 'this run';
    const model = selectedModel();
    if (model?.kind === 'reference') return 'no AA stage';
    if (model?.kind === 'composition') return 'no AA stage';
    if (model?.kind !== 'revision') return 'no parameterization selected';
    // The revision records the run it was fitted against: the source is a fact of the model, not a form choice.
    const reference = model.revisionRecord?.aa_reference || {};
    if (!reference.run_id) return 'no AA reference recorded';
    const parts = [reference.run_id];
    if (reference.temperature_k != null) parts.push(`${reference.temperature_k} K`);
    if (reference.production_ns != null) parts.push(`${reference.production_ns} ns`);
    return parts.join(' · ');
  }
  function describeCoordinates() {
    if (form.elements.run_type.value === 'aa_only') return 'this run';
    const model = selectedModel();
    if (model?.kind === 'reference') return 'Mapped AA geometry';
    if (model?.kind === 'composition') return "the composition's own geometry";
    if (model?.kind === 'revision') return model.hasCoordinates ? `stored · revision ${model.revision}` : 're-map the AA reference';
    if (model?.kind === 'draft') return 'no parameterization';
    return '—';
  }
  function lengthSentence() {
    const toNs = value => {
      const ps = Number(value);
      return Number.isFinite(ps) ? Math.round(ps / 100) / 10 : null;
    };
    const total = labelLength();
    if (total == null) return '—';
    if (form.elements.run_type.value === 'aa_only') {
      const leg = name => toNs(form.elements[name]?.value);
      const [nvt, npt, production] = ['aa_nvt_ps', 'aa_npt_ps', 'aa_production_ps'].map(leg);
      return [nvt, npt, production].some(value => value == null) ? `${total} ns total`
        : `${total} ns total · ${nvt} ns NVT + ${npt} ns NPT + ${production} ns production`;
    }
    const equil = toNs(form.elements.cg_equil_ps?.value), production = toNs(form.elements.cg_production_ps?.value);
    return equil == null || production == null ? `${total} ns total`
      : `${total} ns total · ${equil} ns equilibration + ${production} ns production`;
  }
  function syncRunSummary() {
    const runType = form.elements.run_type.value, aaOnly = runType === 'aa_only';
    const model = selectedModel();
    const moleculeId = form.elements.molecule_id.value;
    const moleculeName = compositionFor(moleculeId)?.molecule_name
      || moleculeRecords.find(record => record.id === moleculeId)?.name || moleculeId || 'Select a molecule';
    setText($('#run-type-summary'), aaOnly ? 'AA run' : 'CG run');
    setText($('#run-molecule-summary'), moleculeName);
    setText($('#run-parameterization-summary'), aaOnly ? 'not needed'
      : model ? parameterizationSelect.selectedOptions?.[0]?.textContent?.trim() || model.key : 'Select a parameterization');
    setText($('#run-aa-summary'), describeAaSource());
    setText($('#run-coordinates-summary'), describeCoordinates());
    setText($('#run-length-summary'), lengthSentence());
    updateSuggestedLabel();
    setText($('#run-label-summary'), labelInput?.value || '');
    renderDoor();
  }

  // The starting-coordinate choice, and the AA source, are the revision kind's own --------------------------------
  function syncStartingCoordinates() {
    const field = $('#starting-coordinates-field');
    const model = selectedModel();
    const revisionKind = form.elements.run_type.value === 'cg' && model?.kind === 'revision';
    if (field) field.classList.toggle('hidden', !revisionKind);
    if (!revisionKind) return;
    const storedOption = startingSelect?.options[0];
    if (storedOption) {
      storedOption.textContent = model.hasCoordinates ? 'Stored with this parameterization · default'
        : 'Stored with this parameterization · no coordinates recorded';
      storedOption.disabled = !model.hasCoordinates;
    }
    // A revision that predates the coordinates record cannot start from it: the default moves to the choice that can
    // run rather than leaving Start blocked by a value the reader never picked.
    if (!model.hasCoordinates) startingSelect.value = 'remap';
    else if (!startingSelect.value) startingSelect.value = 'stored';
    renderStartingNote();
  }
  function renderStartingNote() {
    const note = $('#starting-coordinates-note');
    if (!note) return;
    const model = selectedModel();
    if (form.elements.run_type.value !== 'cg' || model?.kind !== 'revision') { note.textContent = ''; return; }
    if (!model.hasCoordinates) { note.textContent = NO_STORED_COORDINATES; return; }
    note.textContent = startingSelect.value === 'remap'
      ? `This run re-maps the AA reference the fit measured and produces the mapped trajectory; mapping-consistency and overlap analyses become available.`
      : `The fit saved its starting frame with revision ${model.revision}; this run starts from it without re-reading the AA trajectory.`;
  }

  // Which controls this run type and kind show ----------------------------------------------------------------
  function syncVisibility() {
    const runType = form.elements.run_type.value, aaOnly = runType === 'aa_only';
    const kind = currentKind(), reference = !aaOnly && kind === 'reference';
    const composition = !aaOnly && kind === 'composition';
    // A reference or a composition is a read-only model with no atomistic half, so the AA-only settings and the
    // force-field choice (which neither adapter advertises) are out of the form.
    const derived = reference || composition;
    $('#cg-inputs').classList.toggle('hidden', aaOnly);
    $$('.cg-setting').forEach(label => label.classList.toggle('hidden', aaOnly));
    // The stage editors are the atomistic leg's own shells: a CG run consumes a reference that already ran and must
    // not show three empty AA stages.
    $$('.aa-setting').forEach(element => element.classList.toggle('hidden', !aaOnly));
    $$('.aa-cg-setting').forEach(section => section.classList.toggle('hidden', aaOnly || reference));
    const hidden = new Set();
    if (!aaOnly) AA_SAMPLING.forEach(name => hidden.add(name));
    if (!aaOnly) AA_BUILD.forEach(name => hidden.add(name));
    if (derived) REFERENCE_HIDES.forEach(name => hidden.add(name));
    for (const name of [...AA_SAMPLING, ...AA_BUILD, ...REFERENCE_HIDES]) {
      const label = form.elements[name]?.closest('label');
      if (label) label.classList.toggle('hidden', hidden.has(name));
    }
    const constraints = $('#new-constraints-group');
    if (constraints) constraints.classList.toggle('hidden', !aaOnly);
    setText($('#new-ensemble-title'), aaOnly ? 'Ensemble and box' : 'Ensemble');
    setText($('#execution-title'), aaOnly ? 'AA run settings' : reference ? 'CG reference run settings'
      : composition ? 'CG composition run settings' : 'CG run settings');
    setText($('#run-type-help'), aaOnly
      ? 'Standalone AA execution is selected. It publishes a reference a CG parameterization can later be fitted against; the CG model controls are not needed.'
      : composition
        ? 'CG-only run of a saved composition. Its model is derived from the tail recipe and the head reference terms; there is no AA stage, no fit and no AA reference distribution to score against.'
        : reference
          ? 'CG-only run from the published Martini 3 sugar reference. The AA coordinates place the beads; there is no AA stage, mapping comparison or fit.'
          : 'A CG run consumes an existing parameterization of this molecule. It does not run an AA simulation; the parameterization names the AA reference it was fitted against.');
    setText($('#start-run'), aaOnly ? 'Start AA run' : 'Start CG run');
  }

  // The door into CG Bond Interactions ---------------------------------------------------------------------------
  //
  // The two panels are one document (`tabs.js` switches them in place), and the bonded panel's hidden bridge is
  // filled after that switch -- so the address names the mapping but nothing has read it. The door finishes the job:
  // it selects the option and fires `change`, which is what a reader picking it from that list does.
  function bondedPanelHref(mapping) {
    const tab = document.querySelector(`nav.subtabs [data-tab="${panelIds()['bond-interactions']}"]`);
    const href = tab?.getAttribute('href');
    if (!href) return '';
    return mapping ? `${href}?${new URLSearchParams({mapping_candidate: mapping})}` : href;
  }
  function renderDoor() {
    const door = $('#open-bonded');
    if (!door) return;
    const model = selectedModel();
    // The bonded panel addresses a composition as `composition:<id>`; a revision by its mapping file; a published
    // reference has no saved model to open.
    const mapping = form.elements.run_type.value === 'cg' && model
      ? (model.kind === 'composition' ? `composition:${model.id}`
        : model.kind === 'reference' ? '' : model.file)
      : '';
    const href = bondedPanelHref(mapping);
    if (href) door.setAttribute('href', href); else door.removeAttribute('href');
    door.dataset.mapping = mapping;
    door.title = mapping
      ? 'Open this model in CG Bond Interactions, where its revisions are fitted and kept.'
      : 'Open CG Bond Interactions; a published reference is shown there read-only.';
  }
  function followBondedLink(event) {
    const mapping = $('#open-bonded')?.dataset.mapping || '';
    // A modifier-click is the browser's to answer: the address it opens carries the same key.
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    selectTab(panelIds()['bond-interactions']);
    const href = bondedPanelHref(mapping);
    if (href) history.replaceState(null, '', href);
    if (mapping) preselectBondedMapping(mapping);
  }
  $('#open-bonded')?.addEventListener('click', followBondedLink);

  // A model change is a new run's model: its defaults, its coordinates, its review row and its readiness ----------
  let lastKind = null;
  function applyModel() {
    if (startingSelect) startingSelect.value = 'stored';
    syncModel();
  }
  function syncModel() {
    const kind = currentKind();
    const previous = lastKind;
    const changed = previous !== null && kind !== previous;
    lastKind = kind;
    syncVisibility();
    syncStartingCoordinates();
    syncRunSummary();
    syncStageSummaries(form);
    storage.set('form', formValues());
    // A kind change is new defaults. The mount's own call covers the kind the form opened on, and an equal request
    // shares that fetch; gating on `mounted` instead lost the change of a molecule chosen while the panel was still
    // mounting, leaving the opened kind's defaults in place.
    if (changed || kind === 'reference' || previous === 'reference') {
      loadStageDefaults(kind === 'reference' || previous === 'reference')
        .catch(error => setText($('#defaults-source'), error.message));
    }
    refreshReadiness();
  }
  parameterizationSelect?.addEventListener('change', () => { modelTouched = true; applyModel(); });
  startingSelect?.addEventListener('change', () => {
    renderStartingNote();
    syncRunSummary();
    refreshReadiness();
    storage.set('form', formValues());
  });

  // The run type's own defaults: the durations and choices the run is stamped with.
  async function loadStageDefaults(force = false) {
    const runType = form.elements.run_type.value;
    const kind = currentKind();
    const query = new URLSearchParams({run_type: runType});
    // The reference and composition kinds are different adapters with different defaults; the revision kind's are
    // already `cg`'s. `/api/defaults` reads this before a payload exists.
    if (runType === 'cg' && (kind === 'reference' || kind === 'composition')) query.set('parameterization_kind', kind);
    const result = await cachedApi('/api/defaults?' + query);
    // The answer is dropped if the form now asks about another run type or kind: both decide which values it holds.
    if (runType !== form.elements.run_type.value || kind !== currentKind()) return;
    stageDefaults = result;
    fillForceFields(result.force_fields);
    attachHelpIcons(result.help);
    for (const [field, value] of Object.entries(result.values)) {
      const input = form.elements[field];
      if (input && (force || !input.value)) input.value = value;
    }
    setText($('#defaults-source'), 'Defaults from ' + Object.values(stageDefaults.sources).join(' · '));
    syncStageSummaries(form);
    syncRunSummary();
    storage.set('form', formValues());
  }

  // The molecule picker -----------------------------------------------------------------------------------------
  async function loadMolecules() {
    const select = form.elements.molecule_id;
    ++readinessGeneration; $('#start-run').disabled = true;
    const chosen = select.value || savedForm?.molecule_id || savedForm?.detergent || 'DDM';
    const result = await guarded('molecules', () => cachedApi('/api/molecules', {maxAge: CATALOGUE_MAX_AGE}));
    if (result === DROP) return;
    moleculeRecords = result.molecules;
    // A saved composition is a CG molecule with a derived parameterization. It is offered here as a molecule -- the
    // CG run dispatches to the composition adapter -- and it is not an `molecules/` folder, so it stays out of the
    // atomistic list below.
    try {
      const answer = await cachedApi('/api/cg-models?view=summary', {maxAge: CATALOGUE_MAX_AGE});
      compositionRecords = (answer.models || []).filter(model => model.kind === 'composition' && model.parameterization);
    } catch (error) { compositionRecords = []; }
    // This form builds an AA reference or a CG model. A CG-only molecule folder (`kind: 'cg'`) is a pdc detergent,
    // and offering it here would offer a run no adapter accepts.
    const atomistic = moleculeRecords.filter(record => record.kind !== 'cg');
    select.replaceChildren(new Option('Select a molecule directory', ''));
    for (const record of atomistic) select.append(new Option(`${record.name} · ${record.path}${record.valid ? '' : ' · needs attention'}`, record.id));
    if (compositionRecords.length) {
      const group = document.createElement('optgroup');
      group.label = 'CG molecules · composition';
      for (const model of compositionRecords) {
        group.append(new Option(`${model.molecule_name || model.name} · composition · ${model.status || 'candidate-unvalidated'}`,
                                model.molecule_id));
      }
      select.append(group);
    }
    const known = atomistic.some(record => record.id === chosen)
      || compositionRecords.some(model => model.molecule_id === chosen);
    if (chosen && !known) select.append(new Option(`Unavailable directory · ${chosen}`, chosen));
    select.value = chosen;
    const model = compositionFor(select.value);
    if (model) showCompositionModel(model); else showMolecule(moleculeRecords.find(record => record.id === select.value));
    form.elements.detergent.value = select.value;
  }
  async function updateMolecule() {
    const id = form.elements.molecule_id.value;
    const record = moleculeRecords.find(record => record.id === id);
    const model = compositionFor(id);
    form.elements.detergent.value = record?.id || model?.molecule_id || '';
    if (model) showCompositionModel(model); else showMolecule(record);
    // The label names the molecule, so it is refreshed before the parameterization fetch rather than after it.
    syncRunSummary();
    try { await loadParameterizations(); }
    catch (error) { setText($('#readiness'), error.message); }
    storage.set('form', formValues());
    refreshReadiness();
  }
  $('#refresh-molecules').onclick = () => {
    invalidateResource('/api/molecules');
    invalidateResource('/api/mappings');
    // A composition saved in Combinations is a molecule here, so refreshing this picker reads that catalogue too.
    invalidateResource('/api/cg-models');
    mount().catch(error => setText($('#molecule-details'), error.message));
  };
  form.elements.molecule_id.addEventListener('change', updateMolecule);

  // The run type's own switch, and its presets ---------------------------------------------------------------
  async function syncRunType(forceDefaults = false) {
    // A composition is a CG molecule only. Switching to an AA run while one is selected would queue an atomistic
    // run for an id that no `molecules/` folder has, so the picker moves to an atomistic molecule first.
    if (form.elements.run_type.value === 'aa_only' && compositionFor(form.elements.molecule_id.value)) {
      const first = moleculeRecords.find(record => record.kind !== 'cg');
      form.elements.molecule_id.value = first?.id || '';
      await updateMolecule();
    }
    const kind = currentKind();
    const previous = lastKind;
    lastKind = kind;
    syncVisibility();
    syncStartingCoordinates();
    syncRunSummary();
    syncStageSummaries(form);
    storage.set('form', formValues());
    // The reference kind is the published sugar run: its durations are that adapter's, so entering or leaving it
    // replaces the durations the form was showing. AA and CG share their own fields, so switching between them keeps
    // the reader's values, which is what the AA half of a CG run is filled from.
    const force = forceDefaults || kind === 'reference' || previous === 'reference';
    if (force || mounted) {
      loadStageDefaults(force)
        .then(() => applyDefaultPreset())
        .catch(error => setText($('#defaults-source'), error.message));
    }
    refreshReadiness();
  }
  form.elements.run_type.addEventListener('change', () => syncRunType());

  // The GPU device control: the host's options, and the note about a busy device.
  const gpuDevice = createGpuDevice({
    select: $('#run-gpu-device'),
    note: $('#run-gpu-note'),
    ranks: () => form.elements.mdrun_ranks?.value,
    saved: () => storage.get('form', {}).mdrun_gpu,
  });
  form.elements.mdrun_ranks?.addEventListener('input', () => gpuDevice.refresh());

  let stageDefaults;
  // The force fields come from the registry, so the panel offers what the server can actually run rather than a copy
  // of the list held here. Choosing one moves the temperature to the value that entry's parameterisation assumes.
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
  // The info buttons: one accessible control per setting the server sent help for, and no help text in this file or
  // in the template. The button is focusable, `aria-describedby` names its tooltip, the tooltip shows on hover or
  // keyboard focus (CSS) and on a click for touch, and Escape closes it.
  const HELP_ATTACHED = new Set();
  function closeHelpTips() {
    $$('.setting-tip.is-open').forEach(tip => tip.classList.remove('is-open'));
    const active = document.activeElement;
    if (active?.classList?.contains('info-btn')) active.blur();
  }
  function attachHelpIcons(help) {
    if (!help || typeof help !== 'object') return;
    for (const [name, text] of Object.entries(help)) {
      if (HELP_ATTACHED.has(name) || !text) continue;
      const input = form.elements[name];
      const label = input?.closest?.('label');
      if (!label) continue;
      const wrap = document.createElement('span'); wrap.className = 'field-help';
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'info-btn'; button.textContent = 'i';
      button.setAttribute('aria-label', `About ${input.name.replace(/_/g, ' ')}`);
      const tip = document.createElement('span');
      tip.className = 'setting-tip'; tip.id = `setting-help-${name}`; tip.setAttribute('role', 'tooltip');
      tip.textContent = text;
      button.setAttribute('aria-describedby', tip.id);
      button.addEventListener('click', event => {
        event.preventDefault(); event.stopPropagation();
        const wasOpen = tip.classList.contains('is-open');
        closeHelpTips();
        if (!wasOpen) tip.classList.add('is-open');
      });
      wrap.append(button, tip);
      const control = label.querySelector('.setting-control');
      if (control) control.before(wrap); else label.append(wrap);
      HELP_ATTACHED.add(name);
    }
  }
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeHelpTips(); });
  document.addEventListener('click', event => { if (!event.target.closest?.('.field-help')) closeHelpTips(); });

  const savedForm = storage.get('form', {});
  for (const input of [...form.elements].filter(el => el.name)) {
    if (savedForm[input.name] !== undefined) input.value = savedForm[input.name];
    input.addEventListener('input', () => storage.set('form', formValues()));
  }
  // A collapsed stage still says what it holds: the facts line follows its duration, timestep, neighbour list and
  // (CG minimisation) step cap, and the first paint states the restored numbers before `/api/defaults` answers. The
  // summary and the stored form move with it, so a stage number is persisted like any other setting.
  for (const name of STAGE_SUMMARY_FIELDS) {
    form.elements[name]?.addEventListener('input', () => {
      syncStageSummaries(form); syncRunSummary(); storage.set('form', formValues());
    });
  }
  syncStageSummaries(form);
  // A form saved before the split names the retired `aa_cg` (or `sugar_cg`/`cg_composition`). The select has no such
  // option, so it reads ""; the CG run is the one that kept that workflow.
  if (![...form.elements.run_type.options].some(option => option.value === form.elements.run_type.value)) {
    form.elements.run_type.value = 'cg';
  }

  // Named stage-setting presets ----------------------------------------------------------------------------------
  //
  // The store is the workspace's (`models/setting_presets.py`, `/api/setting-presets`). A preset is the numeric and
  // choice settings of one run type: loading one never changes the molecule, the parameterization or the label. A
  // clone outranks the run type's default, which `applyDefaultPreset` honours.
  let presets = [], appliedPreset = null, presetsGeneration = 0;
  function presetFields(runType = form.elements.run_type.value, kind = currentKind()) {
    if (runType === 'aa_only') return AA_ONLY_FIELDS;
    if (kind === 'reference') return REFERENCE_FIELDS;
    if (kind === 'composition') return COMPOSITION_FIELDS;
    return REVISION_FIELDS;
  }
  function currentStageSettings() {
    const settings = {};
    for (const key of presetFields()) {
      if (key === 'sugar_entry') {
        const model = selectedModel();
        if (model?.kind === 'reference' && model.entry) settings.sugar_entry = model.entry;
        continue;
      }
      const control = form.elements[key];
      if (!control || control.value === '' || control.value == null) continue;
      settings[key] = control.value;
    }
    return settings;
  }
  function renderPresetMarker() {
    const isDefault = !!presets.find(preset => preset.id === appliedPreset?.id)?.is_default;
    setText($('#preset-marker'), appliedPreset ? `Applied preset: ${appliedPreset.name}${isDefault ? ' · default' : ''}` : '');
    setText($('#run-preset-summary'), appliedPreset ? `${appliedPreset.name}${isDefault ? ' · default' : ''}` : 'Profile defaults');
  }
  function renderPresetOptions() {
    const select = $('#preset-select'), chosen = appliedPreset?.id || '';
    select.replaceChildren(new Option('Profile defaults (no preset)', ''));
    for (const preset of presets) select.append(new Option(`${preset.name}${preset.is_default ? ' · default' : ''}`, preset.id));
    select.value = presets.some(preset => preset.id === chosen) ? chosen : '';
    if (!select.value) appliedPreset = null;
    renderPresetMarker();
  }
  async function loadPresets(runType = form.elements.run_type.value) {
    const generation = ++presetsGeneration;
    try {
      const answer = await api('/api/setting-presets?' + new URLSearchParams({run_type: runType}));
      if (generation !== presetsGeneration || runType !== form.elements.run_type.value) return null;
      presets = answer.presets || [];
      renderPresetOptions();
      return answer;
    } catch (error) { notice(error.message); return null; }
  }
  /** Fill the stage settings from a preset. The select and a reference's entry are the model's, not a preset's. */
  function applyPreset(preset) {
    const settings = preset?.settings || {};
    for (const key of presetFields()) {
      if (key === 'sugar_entry' || !(key in settings)) continue;
      const control = form.elements[key];
      if (!control || control.disabled) continue;
      // A stored value the form cannot offer -- a GPU this host lost -- is skipped rather than blanking the control.
      if (control.tagName === 'SELECT' && ![...control.options].some(option => option.value === String(settings[key]))) continue;
      control.value = settings[key];
    }
    appliedPreset = {id: preset.id, name: preset.name};
    const select = $('#preset-select');
    if ([...select.options].some(option => option.value === preset.id)) select.value = preset.id;
    renderPresetMarker();
    gpuDevice.refresh();
    syncStageSummaries(form);
    syncRunSummary();
    refreshReadiness();
    storage.set('form', formValues());
  }
  /** Apply the run type's default on mount and on a run-type change. A clone's own settings outrank it. */
  async function applyDefaultPreset() {
    const answer = await loadPresets();
    if (!answer) return;
    if (form.elements.clone_of.value) return;
    const preset = (answer.presets || []).find(item => item.id === answer.default);
    if (!preset) { appliedPreset = null; renderPresetMarker(); return; }
    applyPreset(preset);
  }
  $('#preset-load').onclick = () => {
    const preset = presets.find(item => item.id === $('#preset-select').value);
    if (preset) applyPreset(preset);
  };
  $('#preset-save').onclick = async () => {
    const runType = form.elements.run_type.value;
    const selected = presets.find(item => item.id === $('#preset-select').value);
    const name = window.prompt('Name this preset', selected?.name || '');
    if (name === null) return;
    if (!name.trim()) { notice('A preset needs a name.'); return; }
    try {
      const answer = await post('/api/setting-presets', {name: name.trim(), run_type: runType, settings: currentStageSettings()});
      appliedPreset = {id: answer.preset.id, name: answer.preset.name};
      await loadPresets(runType);
      notice(`Preset ${answer.preset.name} saved.`);
    } catch (error) { notice(error.message); }
  };
  $('#preset-default').onclick = async () => {
    const preset = presets.find(item => item.id === $('#preset-select').value);
    if (!preset) { notice('Select a preset to make it the default.'); return; }
    try {
      await api(`/api/setting-presets/${encodeURIComponent(preset.id)}`,
        {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({is_default: true})});
      await loadPresets(form.elements.run_type.value);
      notice(`${preset.name} is the ${form.elements.run_type.value} default.`);
    } catch (error) { notice(error.message); }
  };
  $('#preset-delete').onclick = async () => {
    const preset = presets.find(item => item.id === $('#preset-select').value);
    if (!preset) { notice('Select a preset to delete.'); return; }
    if (!window.confirm(`Delete the preset “${preset.name}”?`)) return;
    try {
      await api(`/api/setting-presets/${encodeURIComponent(preset.id)}`, {method: 'DELETE'});
      if (appliedPreset?.id === preset.id) appliedPreset = null;
      await loadPresets(form.elements.run_type.value);
      notice(`Preset ${preset.name} deleted.`);
    } catch (error) { notice(error.message); }
  };

  let defaultsLoading;
  setText($('#clone-notice'), form.elements.clone_of.value ? `Cloning ${form.elements.clone_of.value}. Change settings below before starting.` : '');
  $('#leave-clone').hidden = !form.elements.clone_of.value;
  for (const button of $$('.use-default')) button.addEventListener('click', async () => {
    try {
      defaultsLoading ||= loadStageDefaults(); await defaultsLoading; defaultsLoading = null;
      const field = button.dataset.field;
      if (form.elements[field] && stageDefaults.values[field] !== undefined) form.elements[field].value = stageDefaults.values[field];
      gpuDevice.refresh();
      syncStageSummaries(form);
      syncRunSummary(); refreshReadiness();
      storage.set('form', formValues());
    } catch (error) { notice(error.message); }
  });
  // A seed is generated, not defaulted: an integer from 1 through today's date, which is the one value a default
  // cannot supply. The generic `.use-default` handler stays off these two buttons; they carry no such class.
  function generateSeed(button, field) {
    button?.addEventListener('click', () => {
      const input = form.elements[field];
      if (!input) return;
      input.value = String(1 + Math.floor(Math.random() * Number(localDate())));
      syncRunSummary(); refreshReadiness(); storage.set('form', formValues());
    });
  }
  generateSeed($('#generate-aa-seed'), 'aa_seed');
  generateSeed($('#generate-cg-seed'), 'cg_seed');

  // Readiness ---------------------------------------------------------------------------------------------------
  let readinessGeneration = 0, readinessTimer, readinessController;
  function refreshReadiness() {
    ++readinessGeneration;
    clearTimeout(readinessTimer); readinessController?.abort();
    // Everything on screen is about the inputs as they were when the question was asked, and the question is about
    // to be asked again. Until it answers there is no answer, so Start is held.
    syncRunSummary();
    $('#start-run').disabled = true;
    if ($('#' + panelIds()['new-run']).hidden || !mounted || mounting) return;
    readinessTimer = setTimeout(() => checkReadiness(readinessGeneration), 150);
  }
  async function checkReadiness(generation) {
    readinessController = new AbortController();
    $('#start-run').disabled = true;
    const runType = form.elements.run_type.value;
    // A composition names its own molecule, which is not a directory: the row the catalogue listed is the check.
    const selectedMolecule = moleculeRecords.find(record => record.id === form.elements.molecule_id.value)
      || compositionFor(form.elements.molecule_id.value);
    syncRunSummary();
    if (!selectedMolecule) {
      const message = 'Select an available molecule directory before starting.';
      setText($('#readiness'), message); setText($('#launch-blocker'), message);
      setText($('#review-status'), 'Action required'); $('#review-status').dataset.ready = 'false';
      return;
    }
    try {
      const query = {run_type: runType, molecule_id: form.elements.molecule_id.value, detergent: form.elements.detergent.value};
      // A CG run's question is not only the molecule: the model it will consume is part of it, in the same shape the
      // queue route accepts. Asking without it would answer about no model at all.
      if (runType === 'cg') query.parameterization = JSON.stringify(parameterizationPayload());
      const ready = await api('/api/readiness?' + new URLSearchParams(query), {signal: readinessController.signal});
      if (generation !== readinessGeneration) return;
      if (ready.molecule) showMolecule(ready.molecule);
      syncRunSummary();
      writeReadiness(ready.checks, ready.blockers);
      setText($('#review-status'), ready.ready ? 'Inputs ready' : (ready.blockers?.length ? 'Action required' : 'Not ready'));
      $('#review-status').dataset.ready = String(!!ready.ready);
      setText($('#launch-blocker'), ready.ready ? '' : ready.blockers?.[0] || 'Inputs are not ready.');
      $('#start-run').disabled = !ready.ready;
    } catch (error) {
      if (generation !== readinessGeneration || error.name === 'AbortError') return;
      setText($('#readiness'), error.message); setText($('#launch-blocker'), error.message);
      setText($('#review-status'), 'Readiness unavailable'); $('#review-status').dataset.ready = 'false';
    }
  }
  form.elements.temperature_k?.addEventListener('input', () => { syncRunSummary(); storage.set('form', formValues()); });
  form.elements.temperature_k?.addEventListener('input', refreshReadiness);

  // Submission --------------------------------------------------------------------------------------------------
  /** The settings one kind of run posts: its own vocabulary, and nothing a retired form still carried. */
  function fieldsFor(runType, kind) {
    if (runType === 'aa_only') return AA_ONLY_FIELDS;
    if (kind === 'reference') return REFERENCE_FIELDS;
    if (kind === 'composition') return COMPOSITION_FIELDS;
    return REVISION_FIELDS;
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); $('#start-run').disabled = true;
    try {
      if (!await validateCloneSource()) return;
      const runType = form.elements.run_type.value, kind = currentKind();
      const values = formValues();
      const fields = fieldsFor(runType, kind);
      const settings = Object.fromEntries(fields.filter(key => values[key] !== '' && values[key] != null)
        .map(key => [key, values[key]]));
      // A reference run's entry is a choice of the sugar adapter, carried in settings where its readiness reads it
      // and inside `parameterization` where the run records it. A revision payload never carries `sugar_entry`.
      if (runType === 'cg' && kind === 'reference' && selectedModel()?.entry) settings.sugar_entry = selectedModel().entry;
      const data = {run_type: runType, molecule_id: form.elements.molecule_id.value,
                    detergent: form.elements.detergent.value, label: values.label || '',
                    clone_of: form.elements.clone_of.value};
      if (appliedPreset) data.settings_preset = {id: appliedPreset.id, name: appliedPreset.name};
      if (!data.clone_of) {
        if (runType === 'cg') data.parameterization = parameterizationPayload();
        Object.assign(data, settings);
        await post('/', data);
      } else {
        // A clone keeps the source's model unless the reader changed it. When the source's model could not be read,
        // the payload names none and the clone route reuses the record's own -- a clone must not swap the model for
        // whichever one the form defaulted to.
        data.settings = settings;
        if (runType === 'cg' && (modelTouched || pendingApplied)) {
          data.parameterization = parameterizationPayload();
          // The route reuses the source's mapping snapshot while the payload names the same mapping; naming a
          // different one is what tells it to load the new model's snapshot instead. A composition has no mapping
          // snapshot, and admission refuses a composition run that names a mapping candidate.
          if (kind === 'revision' && selectedModel()?.file) data.mapping_candidate = selectedModel().file;
        }
        try { await post(`/api/jobs/${encodeURIComponent(data.clone_of)}/clone`, data); }
        catch (error) { if (error.status === 404 && !await validateCloneSource()) return; throw error; }
      }
      invalidateResource('/api/references'); invalidateResource('/api/storage');
      setCloneSource(''); notice('Run queued.'); selectTab('runs'); await refreshJobs();
    } catch (error) { notice(error.message); }
    finally { refreshReadiness(); }
  });

  // Mount -------------------------------------------------------------------------------------------------------
  let mounted = false, mounting = null;
  async function mount() {
    if (mounting) return mounting;
    $('#' + panelIds()['new-run']).setAttribute('aria-busy', 'true');
    $('#start-run').disabled = true;
    // A clone's record names the model it consumed, and the form must show it before the reader changes it.
    if (!pendingModel && !modelTouched) await validateCloneSource();
    mounting = (async () => {
      await loadMolecules();
      await loadParameterizations();
      await loadStageDefaults(currentKind() === 'reference' && !form.elements.clone_of.value);
      gpuDevice.load();
      // The device list and the readiness note arrive after the form's own answers: a probe of the host is not
      // something the panel's molecule picker waits on, and the note is a status line, not a gate.
      await applyDefaultPreset();
      mounted = true;
      lastKind = currentKind();
      syncVisibility(); syncStartingCoordinates(); syncRunSummary();
      refreshStorage();
    })();
    try { await mounting; }
    finally { mounting = null; $('#' + panelIds()['new-run']).setAttribute('aria-busy', 'false'); refreshReadiness(); }
  }
  document.addEventListener('dashboard:tab', event => {
    if (event.detail.id !== panelIds()['new-run']) {
      ++readinessGeneration; clearTimeout(readinessTimer); readinessController?.abort();
    }
  });

  async function cloneRun(source) {
    selectTab('new');
    // The source's label is a choice already made, and the source's settings outrank the run type's default preset:
    // a clone keeps what it was cloned from until the reader loads a preset or edits a setting.
    labelEdited = true; appliedPreset = null; modelTouched = false; pendingApplied = false;
    pendingModel = source.parameterization
      || (source.mapping_candidate ? {kind: 'revision', mapping_candidate: source.mapping_candidate} : null);
    for (const [key, value] of Object.entries({...(source.settings || {}),
        run_type: source.run_type === 'aa_only' ? 'aa_only' : 'cg',
        molecule_id: source.molecule_id || source.detergent,
        detergent: source.detergent || source.molecule_id,
        label: (source.label || source.id) + ' copy',
        clone_of: source.id})) {
      if (form.elements[key]) form.elements[key].value = value;
    }
    setCloneSource(source.id); syncRunType();
    await mount();
    // The device options come from the host, so a clone's own index can only be applied once they exist.
    const gpu = source.settings?.mdrun_gpu;
    if (gpu != null && [...(form.elements.mdrun_gpu?.options || [])].some(option => option.value === String(gpu))) {
      form.elements.mdrun_gpu.value = String(gpu);
    }
    gpuDevice.refresh();
    syncModel();
    refreshReadiness();
  }

  function clearDeletedClone(id) {
    if (form.elements.clone_of.value === id) setCloneSource('', 'Clone source deleted. Your settings are kept for a new run.');
  }

  async function openComposition(compositionId) {
    // The one door out of Combinations: a saved composition is a CG molecule here, so opening its run selects the
    // molecule and its derived model. A record whose derived model could not be read is reported rather than shown
    // as an empty form that would fail at readiness.
    selectTab(panelIds()['new-run']);
    await mount();
    const model = compositionRecords.find(item => item.id === compositionId || item.molecule_id === compositionId);
    if (!model) {
      notice(`Composition ${compositionId} is not available as a CG molecule in this workspace.`);
      return false;
    }
    form.elements.run_type.value = 'cg';
    form.elements.molecule_id.value = model.molecule_id;
    await updateMolecule();
    await syncRunType();
    return true;
  }

  return { mount, cloneRun, clearDeletedClone, setCloneSource, openComposition };
}
