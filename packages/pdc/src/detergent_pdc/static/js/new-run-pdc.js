import { $, storage, setText, notice, api, post, cachedApi, invalidateResource, guarded, DROP, panelIds } from '/static/js/shared.js';
import { createGpuDevice } from '/static/js/gpu-device.js';
import { ensureNgl } from '/static/js/ngl-loader.js';
import { BEAD_FAMILY_PARAMETERS, BEAD_RADIUS_PARAMETERS, applyBeadRadii, renderBeadLegend } from '/static/js/ngl-beads.js';
import { attachHelpIcons, registerNewRunExtension, writeReadiness } from '/static/js/new-run.js';

// The protein-detergent feature's New run extension: the whole of the pdc workspace's form.
//
// `dashboard.html` renders this panel's markup from `templates/fragments/new-run-pdc.html`, only for the workspace
// whose pipeline it describes, and the module registers itself on `/static/js/new-run.js` as that workspace's panel.
// There is no AA reference, no method and no bonded fit to hide, because nothing rendered one. Every control it
// reads is a name `execution/adapters/pdc.py` accepts -- its `validate_payload` and `SETTING_SPECS` are the authority
// for the spelling, and a control whose value no stage consumes is a control that lies.
//
// One house rule shapes how it reaches the DOM. The id contract (`packages/core/tests/integration/test_dom_ids.py`)
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
  const NUMBERS = ['aggregation_number', 'pdc_nvt_ps', 'pdc_npt_ps', 'pdc_assessment_ns', 'pdc_extension_ns', 'pdc_seed', 'salt_molar',
                   'box_margin_nm', 'initial_z_nm', 'contact_nm', 'selection_threshold_fraction', 'belt_gap_nm',
                   'min_body_gap_nm', 'belt_axial_window_nm',
                   'nstlog', 'nstenergy', 'nstxtcout', 'xtc_precision', 'nstcomm',
                   'pdc_nvt_dt_fs', 'pdc_npt_dt_fs', 'pdc_assessment_dt_fs', 'pdc_extension_dt_fs',
                   'pdc_minimisation_steps', 'pdc_minimisation_emtol', 'pdc_minimisation_emstep',
                   'verlet_buffer_tolerance', 'rlist', 'rcoulomb', 'rvdw',
                   // The physics each leg states for itself: the run-wide names these replaced (`nstlist`, `ref_t`,
                   // `tau_t`, `ref_p`, `tau_p`, `compressibility`) are retired from the form; the adapter still reads
                   // them for old payloads and presets.
                   'pdc_nvt_nstlist', 'pdc_nvt_ref_t', 'pdc_nvt_tau_t',
                   'pdc_npt_nstlist', 'pdc_npt_ref_t', 'pdc_npt_tau_t',
                   'pdc_npt_ref_p', 'pdc_npt_tau_p', 'pdc_npt_compressibility',
                   'pdc_production_nstlist', 'pdc_production_ref_t', 'pdc_production_tau_t',
                   'pdc_production_tau_p', 'pdc_production_ref_p', 'pdc_production_compressibility',
                   'mdrun_gpu', 'mdrun_ntomp', 'mdrun_ranks', 'mdrun_cpt'];
  // The four per-stage timesteps have no catalogue default: a blank box is the reviewed profile's own dt. Their
  // Default button therefore clears, rather than writing a number the catalogue does not publish.
  const DT_FIELDS = new Set(['pdc_nvt_dt_fs', 'pdc_npt_dt_fs', 'pdc_assessment_dt_fs', 'pdc_extension_dt_fs']);
  // The catalogue publishes the settings under the builders' names; the panel's controls carry the pipeline's. The
  // preset store answers the same builders' names, so this map is also the one that puts a loaded preset back on its
  // controls -- `seed` included, which no catalogue default carries but a preset always does.
  const DEFAULT_ALIASES = {seed: 'pdc_seed',
                           assessment_ns: 'pdc_assessment_ns', extension_ns: 'pdc_extension_ns',
                           placement_mode: 'pdc_placement_mode',
                           // The adapter stores the equilibration durations under the builder's names, and both were
                           // missing from this map: the two controls rendered blank while the run still used 500 and
                           // 4 500 ps, which is the one thing a starting value must never do. The step cap is the
                           // same kind of alias.
                           nvt_ps: 'pdc_nvt_ps', npt_ps: 'pdc_npt_ps', minimisation_steps: 'pdc_minimisation_steps'};
  // The three values `pdc.CHOICE_SPECS['protein_vsite']` advertises, spelled for the review. The control's own option
  // labels are the same words; this map exists only so the summary can add what the choice does.
  const VSITE_LABELS = {hydrogens: 'Hydrogens', aromatics: 'Aromatics'};
  // The device is the host's, not the build's: the select is filled from `/api/run/devices`, and a run that names
  // none sends nothing, so the adapter's default device stands. The note is a readiness fact, never a gate.
  const gpuSelect = field('mdrun_gpu');
  const gpuDevice = gpuSelect
    ? createGpuDevice({select: gpuSelect, note: pdcNode('.new-pdc-gpu-note'), saved: () => saved().mdrun_gpu,
                       onChange: () => syncStartButtons()})
    : {load: async () => {}, refresh: () => {}};
  let catalogue = null, detergents = [], chosen = new Map();
  let mounted = false, mounting = null, generation = 0;
  //: The last readiness answer, and whether a POST is out: both launch buttons are held by these two facts.
  let readyState = false, submitting = false;
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
  // The back-map's `pdb2gmx -vsite` choice. It is not a number and not a boolean: the back-map stage's wrapper reads
  // it as one of three strings and appends the flag to the `pdb2gmx` calls CG2AT2 makes, and to no other command.
  const proteinVsite = () => field('protein_vsite')?.value || 'none';
  // Each dynamics leg's transient protein-restraint window, and the NPT leg's barostat: choices like
  // `protein_vsite`, sent under the adapter's advertised names. The restraint selects lead with the reference
  // protocol's own answer (minimisation and NPT hold the backbone, NVT does not), so a run that never touches them
  // sends the value it renders; the adapter writes each leg's define into that leg's MDP only.
  const RESTRAINT_LEGS = ['min', 'nvt', 'npt'];
  const restrainProtein = leg => field('pdc_posres_' + leg)?.value || (leg === 'nvt' ? 'no' : 'yes');
  const nptPcoupl = () => field('pdc_npt_pcoupl')?.value || 'c-rescale';
  const nptPcoupltype = () => field('pdc_npt_pcoupltype')?.value || 'isotropic';
  // The removal/assessment pipeline is a choice, not an assumption. On is the regular assessment + removal +
  // checkpoint chain; off is one plain CG MD leg. The adapter owns the stage consequences; this panel makes the
  // choice visible and sends it.
  const removeOutside = () => !!field('remove_out_of_micelle')?.checked;
  // The plan's step 1 is a step about a protein: pdb2pqr rebuilds and protonates the structure before martinize2
  // reads it. An empty micelle has no structure, so the adapter records the stage skipped; the panel must not send
  // prepare_protein=true for it either, because the preview and prepare both refuse what does not exist.
  const preparing = () => Boolean(field('protein').value);
  // The select's option value is the catalogue entry's id (`DDM:DDM`), which is what the Complexes panel's own picker
  // carries; what a run is *prepared* with is the template file, and `pdc.prepare`/`pdc.readiness` resolve that path
  // against the project root. So the path travels from the entry, never from the option's value.
  const templatePath = () => templateEntry()?.template || '';

  // The run label ------------------------------------------------------------------------------------------------
  //
  // A suggestion, not a stored value: the engine's `new-run.js` writes its own tokens until the reader types, and
  // this panel names what it built instead -- `[detergent]_[micelle|pdb]_[count]_[conformation]_[time]`.
  // `labelEdited` is the one fact that decides both, and it starts true only when a stored label proves the reader
  // once wrote one. An untouched label is never stored, so the next mount suggests from that mount's inputs.
  let labelEdited = saved().label !== undefined;
  const labelInput = field('label');
  const trimZeros = value => String(Number(value.toFixed(3)));
  // A blank duration is the catalogue's own, exactly as `fillDefaults` would have written it. The catalogue
  // publishes the builders' names (`assessment_ns`), while the controls carry the panel's (`pdc_assessment_ns`),
  // so the default is looked up through the same alias map the Default buttons use.
  const catalogueName = name => Object.keys(DEFAULT_ALIASES).find(key => DEFAULT_ALIASES[key] === name) || name;
  function labelNs(name) {
    const text = String(field(name)?.value ?? '').trim();
    const value = text === '' ? Number(catalogue?.defaults?.[catalogueName(name)]) : Number(text);
    return Number.isFinite(value) ? value : null;
  }
  // `1000` ns is `1us`, `1500` is `1.5us`, `202` stays `202ns`: the printed time carries no trailing zeros.
  function labelTime() {
    const assessment = labelNs('pdc_assessment_ns'), extension = labelNs('pdc_extension_ns');
    if (assessment === null || extension === null) return '';
    const total = assessment + extension;
    if (!(total > 0)) return '';
    return total >= 1000 ? `${trimZeros(total / 1000)}us` : `${trimZeros(total)}ns`;
  }
  // The catalogue names the protein; a picked file it does not list is named by its stem, which is what was chosen.
  function labelProtein() {
    const name = String(proteinEntry()?.name || '').trim();
    if (name) return name.replace(/\s+/g, '-');
    return String(field('protein').value || '').split('/').pop().replace(/\.[^.]+$/, '').replace(/\s+/g, '-');
  }
  function suggestedLabel() {
    const detergentName = String(field('molecule_id').value || '').trim();
    const count = String(field('aggregation_number').value || catalogue?.defaults?.aggregation_number || '').trim();
    if (!detergentName || !count) return '';
    return [detergentName, preparing() ? labelProtein() : 'micelle', count,
            shapeSpec() ? 'libconf' : '1conf', labelTime()].filter(part => part !== '').join('_');
  }
  // Emptied by hand, the label stays empty: the server generates the fallback for a run with no label, and a
  // suggestion written over the reader's empty field would be a value they did not choose.
  function updateSuggestedLabel() {
    if (labelEdited || !labelInput) return;
    const suggestion = suggestedLabel();
    if (suggestion) labelInput.value = suggestion;
  }
  labelInput?.addEventListener('input', () => { labelEdited = true; store(); });

  function store() {
    const values = Object.fromEntries([...form.elements].filter(el => el.name).map(el => [el.name, el.value]));
    // A suggestion is not the reader's value: an untouched label is left out of the store, so a later mount
    // suggests from that mount's inputs rather than restoring a name nobody wrote.
    if (!labelEdited) delete values.label;
    storage.set('pdc-form', values);
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

  // The models this detergent can be built from, fitted ones first, each grouped by what it carries. The server has
  // already decided which saved mappings a build can reuse, which of them carry a fitted parameterization and what the
  // sentence beside each one says -- so this renders two groups and never infers fitted from derived itself. The
  // option's value stays the mapping's file, because that file is the model's identity to the form, the preview and
  // the run (`mapping_candidate`), even though it is no longer what the reader is shown.
  async function loadMappings() {
    const select = field('mapping_candidate');
    const molecule = field('molecule_id').value;
    const wanted = select.value || saved().mapping_candidate || '';
    if (!molecule) { select.replaceChildren(new Option('Choose a detergent first', '')); return; }
    select.replaceChildren(new Option('Looking for saved models…', ''));
    let models = [];
    try {
      const result = await cachedApi(`/api/pdc/models?molecule_id=${encodeURIComponent(molecule)}`,
                                     {maxAge: 10000});
      models = result.models || [];
    } catch (error) {
      select.replaceChildren(new Option('The model list could not be read', ''));
      return;
    }
    const group = (title, entries) => {
      const element = document.createElement('optgroup');
      element.label = title;
      element.append(...entries.map(model => new Option(model.label, model.file)));
      return element;
    };
    select.replaceChildren(new Option(models.length ? 'No model: a build records centres-only'
      : 'No saved mapping this detergent can be built from', ''),
      ...(models.length ? [group('Models (fitted)', models.filter(model => model.fitted)),
                           group('Mappings with derived terms', models.filter(model => !model.fitted))] : []));
    select.value = mappingFor(molecule, wanted, models);
  }

  // Which model the panel hands the form, and therefore the preview and the run: the detergent's own first one -- a
  // fitted model before a derived one, because the list is ordered that way -- so the picture is made of the beads that
  // mapping declares and the run simulates the terms its parameterization carries when it has one. It reached the
  // writer as a centres-only frame until 2026-10-14 -- one point per detergent, no moleculetype, hence no types --
  // which is why every bead on this detergent's preview came back `family not stated`; the frame the reader asked to
  // see carrying its own families is the mapping's beads, and a build with no mapping is a real build rather than the
  // default.
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
    return candidates.length ? candidates[0].file : '';
  }
  function rememberMapping() {
    storage.set('pdc-mapping-choice',
                {...mappingChoices(), [field('molecule_id').value]: field('mapping_candidate').value || MAPPING_NONE});
  }

  function fillDefaults() {
    const defaults = catalogue?.defaults || {};
    for (const [key, value] of Object.entries(defaults)) {
      const input = field(DEFAULT_ALIASES[key] || key);
      // A checkbox's state is its `checked` attribute and never its value: a default written into `value` sets no
      // state at all, and reads as though it had. The two checkboxes this pipeline has (`backmap`, the prepare step)
      // carry their defaults in the markup, where a reader can see them.
      if (!input || input.type === 'checkbox') continue;
      // A per-stage timestep has no catalogue default; filling it here would state the profile's dt as an override.
      if (DT_FIELDS.has(input.name)) continue;
      if (input.value === '') input.value = value;
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
    // The z-box's Auto button measures a protein, so it follows the same selection this block does.
    syncAutoButton();
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

  // The initial-z Auto is a measurement of the chosen protein. An empty micelle has no structure to measure, so the
  // button says why by being disabled rather than answering a number about nothing.
  function syncAutoButton() {
    const button = pdcNode('.pdc-auto-z');
    if (!button) return;
    const hasProtein = !!field('protein').value;
    button.disabled = !hasProtein;
    button.title = hasProtein
      ? 'Measure the selected protein and size the z box from it'
      : 'Choose a protein: an empty micelle has no structure to measure a z box from.';
  }

  // The detergent shape ------------------------------------------------------------------------------------------
  //
  // Three mutually exclusive sources for the conformations the build stamps: the template's one molecule
  // (`single`, today's build), a library built from micelle-only runs, or a library already stored in this
  // workspace. Both lists and every refusal sentence are the server's; the card only chooses between them and
  // hands the adapter the one setting it validates. Only the chosen mode's body is shown, and `single` has no body.
  let shapeRuns = [], shapeRunIds = new Set(), shapeRunsLoaded = false, shapeRunsError = '';
  let shapeLibraries = [], shapeLibraryKey = '', shapeLibrariesLoaded = false, shapeLibrariesError = '';
  const shapeMode = () => field('shape_source')?.value || 'single';
  // The template states the detergent's own residue; a library is stored per residue, so that is the list's filter.
  const shapeResidue = () => templateEntry()?.residue || '';

  function durationNs(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? `${number.toLocaleString('en-US')} ns` : 'duration not recorded';
  }
  const shapeSize = () => Number(field('conformations_size')?.value);
  const shapeSeed = () => Number(field('conformations_seed')?.value);
  const selectedRunIds = () => shapeRuns.filter(run => run.eligible && shapeRunIds.has(run.id)).map(run => run.id);

  function shapeSpec() {
    if (shapeMode() === 'build') {
      const runs = selectedRunIds(), size = shapeSize(), seed = shapeSeed();
      if (!runs.length || !Number.isInteger(size) || !Number.isInteger(seed)) return null;
      return {runs, size, seed};
    }
    if (shapeMode() === 'stored') {
      const library = shapeLibraries.find(item => item.key === shapeLibraryKey);
      return library ? {key: library.key, sha256: library.sha256} : null;
    }
    return null;
  }

  function renderShapeRuns() {
    const list = pdcNode('.eligible-runs');
    if (!list) return;
    list.replaceChildren(...shapeRuns.map(run => {
      const label = document.createElement('label');
      label.className = 'eligible-run';
      const box = document.createElement('input');
      box.type = 'checkbox'; box.value = run.id;
      box.checked = !!run.eligible && shapeRunIds.has(run.id);
      // An ineligible run is shown with its own sentence rather than hidden, and it cannot be selected.
      box.disabled = !run.eligible;
      if (!run.eligible) label.title = run.reason || 'not eligible';
      const id = document.createElement('code'); id.textContent = run.id;
      const where = document.createElement('span'); where.className = 'where';
      // The flexible column carries the run's description, or the server's sentence for a run that cannot be used --
      // a long refusal in the narrow `auto` column beside the tag would wrap the row into an unreadable stack.
      where.textContent = run.eligible
        ? `${run.residue || 'detergent'} empty micelle · ${durationNs(run.duration_ns)}`
        : (run.reason || 'not eligible');
      const meta = document.createElement('span'); meta.className = 'meta';
      meta.textContent = run.eligible ? (run.label || '') : (run.protein ? 'has a protein' : 'not eligible');
      const tag = document.createElement('span'); tag.className = `tag${run.eligible ? '' : ' warn'}`;
      tag.textContent = run.eligible ? 'eligible' : 'not eligible';
      label.append(box, id, where, meta, tag);
      return label;
    }));
  }

  function renderShapeLibraries() {
    const list = pdcNode('.stored-libraries');
    if (!list) return;
    const note = text => {
      const element = document.createElement('p');
      element.className = 'hint';
      element.textContent = text;
      list.replaceChildren(element);
    };
    if (!shapeLibrariesLoaded) return note('Reading the stored libraries…');
    if (shapeLibrariesError) return note(shapeLibrariesError);
    if (!shapeLibraries.length) return note('No stored library yet — build one from runs, or copy one in.');
    list.replaceChildren(...shapeLibraries.map(library => {
      const row = document.createElement('label');
      row.className = 'stored-library';
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'shape_library'; radio.value = library.key;
      radio.checked = library.key === shapeLibraryKey;
      const key = document.createElement('code'); key.textContent = library.key;
      const where = document.createElement('span'); where.className = 'where';
      const sources = Array.isArray(library.sources) ? library.sources.length : 0;
      where.textContent = `${Number(library.size).toLocaleString('en-US')} · ${sources} run${sources === 1 ? '' : 's'}`;
      const meta = document.createElement('span'); meta.className = 'meta';
      const digest = String(library.sha256 || '');
      meta.textContent = digest ? `digest ${digest.slice(0, 4)}…${digest.slice(-4)}` : 'digest not recorded';
      const tag = document.createElement('span'); tag.className = 'tag'; tag.textContent = 'stored';
      // A stored library is the workspace's, so a reader can remove it. The button sits inside the row's label, so
      // it stops the label's own activation: deleting a library must never select it first.
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'secondary danger stored-library-delete';
      remove.textContent = 'Delete';
      remove.setAttribute('aria-label', `Delete the stored library ${library.key}`);
      remove.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        deleteShapeLibrary(library);
      });
      row.append(radio, key, where, meta, tag, remove);
      return row;
    }));
  }

  // Delete one stored library, after a confirm that names what is lost. The coordinates are the workspace's own, so
  // the question is asked here and nowhere else; the server still requires `confirm: true` as its own guard.
  async function deleteShapeLibrary(library) {
    const key = library.key;
    if (!window.confirm(`Delete the stored library ${key}? Its coordinates are removed from this workspace and any run that selected it will no longer be able to use it.`)) return;
    try {
      await api(`/api/pdc/conformations/libraries/${encodeURIComponent(key)}`,
                {method: 'DELETE', headers: {'Content-Type': 'application/json'},
                 body: JSON.stringify({confirm: true})});
    } catch (error) {
      say('.shape-stored-status', `The stored library ${key} was not deleted: ${error.message}`);
      return;
    }
    // The list is re-read rather than edited in place: the server owns what remains, and `loadShapeLibraries`
    // already moves the selection to the first survivor when the deleted key was the chosen one.
    await loadShapeLibraries();
    notice(`Stored library ${key} deleted.`);
  }

  function syncShapeStatus() {
    if (!shapeRunsLoaded) return say('.shape-summary', 'Reading the micelle-only runs…');
    if (shapeRunsError) return say('.shape-summary', shapeRunsError);
    const count = shapeRunIds.size;
    const size = Number.isInteger(shapeSize()) ? shapeSize().toLocaleString('en-US') : '—';
    const seed = field('conformations_seed')?.value === '' ? '—' : field('conformations_seed')?.value;
    say('.shape-summary', `${size} from ${count} run${count === 1 ? '' : 's'}, seed ${seed} · stored once built`);
  }

  // The card and its two lists are read on mount; the stored list is read again after a successful submit so a build
  // from runs becomes selectable immediately, and when the detergent changes because it is stored per residue.
  async function loadShapeRuns() {
    try {
      const body = await api('/api/pdc/conformations/runs');
      shapeRuns = Array.isArray(body.runs) ? body.runs : [];
      const available = new Set(shapeRuns.filter(run => run.eligible).map(run => run.id));
      // A first answer selects every eligible run; a later one keeps what the reader ticked and drops what is gone.
      shapeRunIds = shapeRunsLoaded ? new Set([...shapeRunIds].filter(id => available.has(id))) : available;
      shapeRunsLoaded = true; shapeRunsError = '';
    } catch (error) {
      shapeRunsLoaded = true;
      shapeRunsError = `The micelle-only runs could not be read: ${error.message}`;
    }
    renderShapeRuns(); syncShape();
    // A reader can reach the card before this answer lands; the gate it armed at the switch is cleared here.
    if (shapeMode() === 'build') refreshReadinessSoon();
  }

  async function loadShapeLibraries() {
    const residue = shapeResidue();
    const query = residue ? `?residue=${encodeURIComponent(residue)}` : '';
    try {
      const body = await api(`/api/pdc/conformations/libraries${query}`);
      shapeLibraries = Array.isArray(body.libraries) ? body.libraries : [];
      if (!shapeLibraries.some(library => library.key === shapeLibraryKey)) {
        shapeLibraryKey = shapeLibraries[0]?.key || '';
      }
      shapeLibrariesLoaded = true; shapeLibrariesError = '';
    } catch (error) {
      shapeLibrariesLoaded = true;
      shapeLibrariesError = `The stored libraries could not be read: ${error.message}`;
    }
    renderShapeLibraries(); syncShape();
    if (shapeMode() === 'stored') refreshReadinessSoon();
  }

  function syncShape() {
    const mode = shapeMode();
    for (const body of form.querySelectorAll('[data-shape-body]')) body.hidden = body.dataset.shapeBody !== mode;
    syncShapeStatus();
    say('.shape-stored-status', shapeLibrariesError);
    syncPreviewLibrary();
  }

  function shapeChanged() {
    // The label's conformation token follows the shape, so the suggestion moves with it.
    syncShape(); syncSummary(); store(); checkReadiness(); renderPreviewState();
  }

  // The workflow diagram is a render of the choices above, not a second copy of the pipeline. The static SVG used to
  // draw all ten stages whether or not they would run; an empty micelle has no prepare/coarse-grain, and removing the
  // removal pipeline removes judge, extend and final assessment. The active path is drawn, and a caption names what
  // was left out and why. Coordinates are the existing five-column, two-row vocabulary; the bottom row runs right to
  // left, the way the old diagram's return path did.
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const FLOW_COLUMNS = [6, 214, 422, 630, 838];
  const FLOW_WIDTHS = [176, 176, 176, 176, 136];
  function flowNode(label, sub, key, cls = '') {
    return {label, sub, key, cls};
  }
  function workflowStages() {
    const hasProtein = !!field('protein').value;
    const pre = preassembled();
    const count = field('aggregation_number').value || '—';
    const assessment = field('pdc_assessment_ns').value || '—';
    const extension = field('pdc_extension_ns').value || '—';
    const assessmentNs = Number(field('pdc_assessment_ns').value);
    const extensionNs = Number(field('pdc_extension_ns').value);
    const total = Number.isFinite(assessmentNs) && Number.isFinite(extensionNs) ? `${assessmentNs + extensionNs} ns` : '—';
    const stages = [];
    if (hasProtein) {
      stages.push(flowNode('Prepare', 'PDB2PQR · skipped if unavailable', 'prepare'));
      stages.push(flowNode('Coarse-grain', 'martinize2 · Martini 3 · elastic', 'coarse-grain'));
    }
    stages.push(flowNode(hasProtein ? (pre ? 'Place the belt' : 'Self-assemble')
                                    : (pre ? 'Build the micelle' : 'Self-assemble'),
                         pre ? `${count} detergents · pre-assembled`
                             : `${count} detergents · random start`,
                         'build', 'new-pdc-placed-node'));
    stages.push(flowNode('Equilibrate', 'minimise · NVT · NPT', 'equilibrate'));
    if (removeOutside()) {
      stages.push(flowNode('Sample', `CG assessment MD · ${assessment} ns`, 'sample'));
      stages.push(flowNode('Judge', 'micelle assessment · removal', 'judge'));
      stages.push(flowNode('Extend', `checkpoint · ${extension} ns`, 'extend'));
      stages.push(flowNode('Final assessment', 'finished CG system', 'final-assessment'));
    } else {
      stages.push(flowNode('CG MD', `${total} · one leg, no removal`, 'sample'));
    }
    if (hasProtein && backmapping()) stages.push(flowNode('Back-map', 'CG2AT2 · atoms, then neutralise', 'back-map', 'new-pdc-backmap-node'));
    stages.push(flowNode('Result', hasProtein && backmapping() ? 'atomistic complex + records' : 'CG system + records', 'result'));
    return stages.map((stage, index) => ({...stage, label: `${index + 1} · ${stage.label}`}));
  }
  function renderWorkflowDiagram() {
    const host = pdcNode('.new-pdc-flow');
    if (!host) return;
    const stages = workflowStages();
    host.replaceChildren();
    const addNode = (stage, x, y, width) => {
      const group = document.createElementNS(SVG_NS, 'g');
      group.setAttribute('class', `new-pdc-flow-node ${stage.cls}`.trim());
      group.dataset.stage = stage.key;
      const rect = document.createElementNS(SVG_NS, 'rect');
      rect.setAttribute('x', x); rect.setAttribute('y', y);
      rect.setAttribute('width', width); rect.setAttribute('height', 52); rect.setAttribute('rx', 7);
      const title = document.createElementNS(SVG_NS, 'text');
      title.setAttribute('class', 'title');
      title.setAttribute('x', x + width / 2); title.setAttribute('y', y + 21);
      title.textContent = stage.label;
      const sub = document.createElementNS(SVG_NS, 'text');
      sub.setAttribute('class', 'sub'); sub.setAttribute('x', x + width / 2); sub.setAttribute('y', y + 39);
      sub.textContent = stage.sub;
      group.append(rect, title, sub);
      host.append(group);
    };
    const addLink = points => {
      const path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('class', 'new-pdc-flow-link');
      path.setAttribute('d', points);
      path.setAttribute('marker-end', 'url(#new-pdc-arrow)');
      host.append(path);
    };
    const top = stages.slice(0, 5), bottom = stages.slice(5);
    top.forEach((stage, index) => addNode(stage, FLOW_COLUMNS[index], 24, FLOW_WIDTHS[index]));
    if (bottom.length) {
      bottom.forEach((stage, index) => {
        const column = FLOW_COLUMNS.length - 1 - index;
        addNode(stage, FLOW_COLUMNS[column], 118, FLOW_WIDTHS[column]);
      });
      const lastTop = FLOW_COLUMNS[top.length - 1];
      const firstBottom = FLOW_COLUMNS[FLOW_COLUMNS.length - 1];
      if (lastTop === firstBottom) addLink(`M${lastTop + FLOW_WIDTHS[top.length - 1] / 2},76 V118`);
      else addLink(`M${lastTop + FLOW_WIDTHS[top.length - 1] / 2},76 V97 H${firstBottom + FLOW_WIDTHS[4] / 2} V118`);
    }
    for (let index = 0; index < top.length - 1; index++) {
      const from = FLOW_COLUMNS[index] + FLOW_WIDTHS[index];
      const to = FLOW_COLUMNS[index + 1];
      addLink(`M${from},50 H${to}`);
    }
    for (let index = 0; index < bottom.length - 1; index++) {
      const from = FLOW_COLUMNS[FLOW_COLUMNS.length - 1 - index];
      const to = FLOW_COLUMNS[FLOW_COLUMNS.length - 2 - index] + FLOW_WIDTHS[FLOW_COLUMNS.length - 2 - index];
      addLink(`M${from},144 H${to}`);
    }
    const svg = host.ownerSVGElement;
    const title = svg?.querySelector('title');
    const desc = svg?.querySelector('desc');
    const words = stages.map(stage => stage.label.replace(/^\d+ · /, '')).join(' → ');
    if (title) title.textContent = `The stages this run will take: ${words}`;
    if (desc) desc.textContent = `Active stages: ${words}.`;
    if (svg) svg.setAttribute('aria-label', title?.textContent || 'The stages this run will take');
    const skipped = [];
    if (!field('protein').value) skipped.push('protein preparation and coarse-graining: empty micelle');
    if (!removeOutside()) skipped.push('micelle assessment, removal, extension and final assessment: removal is off');
    if (!field('protein').value || !backmapping()) skipped.push('back-map: no atomistic structure is produced');
    say('.new-pdc-flow-skipped', skipped.length ? `Skipped — ${skipped.join(' · ')}.` : '');
  }

  // One facts line per stage editor, from the numbers the run will post: a closed editor still states its duration,
  // timestep, implied step count and restraint window. The engine's writer (`new-run.js`) is private and keyed to
  // the AA/CG stage names, and this form's stages are neither, so the table is here. Hundreds are grouped the way the
  // rest of the dashboard prints them (`5 000 000`).
  const STAGE_FACTS = [
    {stage: 'minimisation', steps: 'pdc_minimisation_steps', emtol: 'pdc_minimisation_emtol',
     emstep: 'pdc_minimisation_emstep', restraint: 'pdc_posres_min'},
    {stage: 'nvt', ps: 'pdc_nvt_ps', dt: 'pdc_nvt_dt_fs', restraint: 'pdc_posres_nvt'},
    {stage: 'npt', ps: 'pdc_npt_ps', dt: 'pdc_npt_dt_fs', restraint: 'pdc_posres_npt'},
    // Assessment and extension are one editor with two durations and one shared physics set, so their line states
    // both durations and the timestep(s) that turn them into steps.
    {stage: 'production', assessment_ns: 'pdc_assessment_ns', assessment_dt: 'pdc_assessment_dt_fs',
     extension_ns: 'pdc_extension_ns', extension_dt: 'pdc_extension_dt_fs'},
  ];
  // The three boxes one dynamics stage reads: duration, its own timestep, and the step count the two imply. The
  // count is derived and carries no `name`, so it never reaches the payload; editing it back-solves the duration at
  // the stated timestep. `unit` is the duration's, and the arithmetic is the adapter's own (steps = duration / dt).
  const TIME_ROWS = {
    nvt: {duration: 'pdc_nvt_ps', dt: 'pdc_nvt_dt_fs', unit: 'ps'},
    npt: {duration: 'pdc_npt_ps', dt: 'pdc_npt_dt_fs', unit: 'ps'},
    assessment: {duration: 'pdc_assessment_ns', dt: 'pdc_assessment_dt_fs', unit: 'ns'},
    extension: {duration: 'pdc_extension_ns', dt: 'pdc_extension_dt_fs', unit: 'ns'},
  };
  const STEPS_UNKNOWN_TITLE = 'A reviewed timestep is not known in the browser, so the step count cannot be worked out here.';
  const durationFs = row => row.unit === 'ps' ? 1000 : 1000000;
  function syncTimeRow(stage) {
    const row = TIME_ROWS[stage], box = pdcNode(`.pdc-steps[data-stage="${stage}"]`);
    if (!row || !box) return;
    const duration = stageNumber(row.duration), dt = stageNumber(row.dt);
    // No dt means no step count the browser can state: the reviewed profile's dt is the server's own. Read-only,
    // not disabled, so the reason in the title is reachable and the box cannot silently look like an answer.
    box.readOnly = dt === null;
    box.title = dt === null ? STEPS_UNKNOWN_TITLE : '';
    box.value = duration === null || dt === null ? '' : String(Math.round(duration * durationFs(row) / dt));
  }
  function syncTimeRows() { for (const stage of Object.keys(TIME_ROWS)) syncTimeRow(stage); }
  const groupedNumber = value => Number(value).toLocaleString('en-GB').replace(/,/g, ' ');
  function stageNumber(name) {
    const text = String(field(name)?.value ?? '').trim();
    if (text === '') return null;
    const value = Number(text);
    return Number.isFinite(value) ? value : null;
  }
  // The merged production line: both durations, the timestep(s) stated for them, and the total step count those
  // imply. One shared dt is printed once; two different ones name their own leg, because a single number would be a
  // claim about both legs that the form did not make.
  function productionFacts(spec) {
    const assessmentNs = stageNumber(spec.assessment_ns), extensionNs = stageNumber(spec.extension_ns);
    const assessmentDt = stageNumber(spec.assessment_dt), extensionDt = stageNumber(spec.extension_dt);
    const parts = [];
    if (assessmentNs !== null) parts.push(`${groupedNumber(assessmentNs)} ns assessment`);
    if (extensionNs !== null) parts.push(`${groupedNumber(extensionNs)} ns extension`);
    if (assessmentDt !== null && extensionDt !== null) {
      parts.push(assessmentDt === extensionDt ? `${assessmentDt} fs`
                                              : `${assessmentDt} fs assessment · ${extensionDt} fs extension`);
    } else if (assessmentDt !== null) parts.push(`${assessmentDt} fs assessment`);
    else if (extensionDt !== null) parts.push(`${extensionDt} fs extension`);
    if (assessmentNs !== null && extensionNs !== null && assessmentDt && extensionDt) {
      const steps = Math.round(assessmentNs * 1000000 / assessmentDt)
                  + Math.round(extensionNs * 1000000 / extensionDt);
      parts.push(`${groupedNumber(steps)} steps`);
    }
    return parts;
  }
  function syncStageFacts() {
    for (const spec of STAGE_FACTS) {
      const host = form.querySelector(`.new-pdc-stage-facts[data-stage="${spec.stage}"]`);
      if (!host) continue;
      if (spec.stage === 'production') { host.textContent = productionFacts(spec).join(' · '); continue; }
      const parts = [];
      const steps = spec.steps ? stageNumber(spec.steps) : null;
      const ps = spec.ps ? stageNumber(spec.ps) : null;
      const ns = spec.ns ? stageNumber(spec.ns) : null;
      const dt = spec.dt ? stageNumber(spec.dt) : null;
      if (steps !== null) parts.push(`${groupedNumber(steps)} steps`);
      if (ps !== null) parts.push(ps === 0 ? 'skipped' : `${groupedNumber(ps)} ps`);
      if (ns !== null) parts.push(`${groupedNumber(ns)} ns`);
      if (spec.emtol) { const value = stageNumber(spec.emtol); if (value !== null) parts.push(`${value} kJ/mol/nm`); }
      if (spec.emstep) { const value = stageNumber(spec.emstep); if (value !== null) parts.push(`${value} nm`); }
      if (dt !== null) parts.push(`${dt} fs`);
      // The step count the duration implies at that timestep, the same arithmetic `adapters/pdc.py` prepares with.
      if (ps && dt) parts.push(`${groupedNumber(Math.round(ps * 1000 / dt))} steps`);
      if (ns && dt) parts.push(`${groupedNumber(Math.round(ns * 1000000 / dt))} steps`);
      if (spec.restraint) {
        const value = field(spec.restraint)?.value;
        if (value) parts.push(value === 'yes' ? 'restrained' : 'free');
      }
      host.textContent = parts.join(' · ');
    }
    syncTimeRows();
  }

  // The three controls act on a pre-assembled belt on a membrane-stating protein; self-assembly settles the belt
  // from a random start, so they are hidden there. Hidden, not disabled: the values still travel, and the adapter
  // ignores them outside a belt.
  function syncBeltGap() {
    for (const name of ['belt_gap_nm', 'min_body_gap_nm', 'belt_axial_window_nm']) {
      const label = form.querySelector(`[name=${name}]`)?.closest('label');
      if (label) label.hidden = placementMode() === 'self-assembly';
    }
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
    const assessmentNs = Number(field('pdc_assessment_ns').value);
    const extensionNs = Number(field('pdc_extension_ns').value);
    const totalNs = Number.isFinite(assessmentNs) && Number.isFinite(extensionNs)
      ? assessmentNs + extensionNs : null;
    setText(summary('sampling'), removeOutside()
      ? `${field('pdc_assessment_ns').value || '—'} ns assessment · `
        + `${field('pdc_extension_ns').value || '—'} ns extension`
      : `${totalNs == null ? '—' : `${totalNs} ns`} CG MD · one leg, no removal pipeline`);
    syncStageFacts();
    const belt = pdcNode('.new-pdc-belt-block'), empty = pdcNode('.new-pdc-empty-block');
    if (belt) belt.hidden = !hasProtein;
    if (empty) empty.hidden = hasProtein;
    say('.new-pdc-count-label', hasProtein ? 'Detergents in the belt' : 'Detergents in the micelle');
    say('.new-pdc-config-title', hasProtein ? 'Detergent belt and sampling' : 'Micelle and sampling');
    say('.new-pdc-estimate-label', hasProtein ? 'Estimate' : 'Experiments');
    say('.new-pdc-workflow-note', hasProtein
      ? "With a protein, steps 3 and 5 use the protein's hydrophobic surface."
      : "Empty micelle: step 3 is the micelle on its own, and step 5's protein clause does not apply.");

    // The choice has to mean something on the screen, so the strip and the review both say which style is in force.
    const pre = preassembled();
    setText(summary('placement'), pre ? 'Pre-assembled micelle · CHARMM-GUI' : 'Self-assembly · MemProtMD');
    setText(summary('seed'), field('pdc_seed').value || 'not set — the run cannot start');
    // What the run will and will not produce, stated in the review so a reader cannot mistake a run without
    // back-mapping for one with it. The workflow strip's own step says the same.
    const backmap = backmapping() && hasProtein;
    setText(summary('backmap'), backmap
      ? 'CG2AT2 to atomistic (−o align)'
      : (hasProtein
          ? 'off — the run stops coarse-grained, with no atomistic structure produced'
          : 'skipped · empty micelle has no protein to align'));
    say('.new-pdc-backmap-note', backmap
      ? 'On: the final CG state is converted to atomistic with CG2AT2 (-o align).'
      : (hasProtein
          ? 'Off: the back-map stage records skipped and the run stops coarse-grained, with no atomistic structure produced.'
          : 'Skipped: an empty micelle has no protein to align, so no atomistic structure is produced.'));
    // The virtual-site choice is the back-map's, and the review says whether it will reach a pdb2gmx at all.
    const vsite = proteinVsite();
    setText(summary('vsite'), vsite === 'none' ? 'none · pdb2gmx default'
      : (!backmap || !hasProtein
          ? `${VSITE_LABELS[vsite]} · recorded, but the back-map does not run`
          : `${VSITE_LABELS[vsite]} · pdb2gmx -vsite ${vsite}`));
    // The plan's step 1 is about a protein. An empty micelle records it skipped, so the review says that instead of
    // promising a rebuild the run cannot do, and the protein card's statement of the step is not shown at all.
    setText(summary('prepare'), hasProtein
      ? 'PDB2PQR: always on — rebuild the missing atoms, then protonate (skipped if the tool is absent)'
      : 'skipped · empty micelle has no protein to prepare');
    const prepareNote = pdcNode('.new-pdc-prepare-note');
    if (prepareNote) prepareNote.hidden = !hasProtein;
    setText(summary('removal'), removeOutside()
      ? 'on · CG assessment, removal and checkpoint extension'
      : 'off · one plain CG MD leg, no assessment/removal/extension/final assessment');
    const number = item && item.aggregation_number != null ? String(item.aggregation_number) : null;
    // The estimate is the server's: the review shows the answer the route gave (or its refusal), and with no
    // protein there is no slab to size, so the detergent's own measured micelle size stands instead.
    setText(summary('estimate'), hasProtein
      ? (estimateState.summary || '—')
      : `experimental aggregation number ${number ?? 'not recorded yet'}`);
    say('.new-pdc-empty-number', number ?? '— not recorded yet');
    say('.new-pdc-empty-count', String(count));
    syncBeltGap();
    updateSuggestedLabel();
    syncPreviewControls();
    renderWorkflowDiagram();
  }

  // The coverage estimate the plan asks for, rendered from the route's answer rather than computed here: the
  // numbers, the method the route states and its caveat, or -- when the route refuses -- the route's own reason.
  // No arithmetic of the panel's own reaches the screen: `fraction`, `needed` and the areas are the server's, and
  // all this does is format them.
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
      // The short form the bubble carries; the route's full `method` is its own statement and is not reprinted here.
      say('.new-pdc-method', body.method_summary || body.method || '');
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
    let body;
    try {
      body = await api(`/api/pdc/proteins/${encodeURIComponent(entry_id)}/encapsulation?${query}`);
    } catch (error) {
      if (mine !== estimateRequest) return;
      const refused = error.status !== undefined;
      const reason = !refused
        ? 'The estimate could not be read: the coordinator did not answer.'
        : (error.message === `Request failed (${error.status})`
          ? `the estimate was refused (status ${error.status})` : error.message);
      estimateState = {kind: 'refused', summary: refused ? reason : 'estimate unavailable', body: null, reason};
      renderEstimate(); syncSummary();
      return;
    }
    if (mine !== estimateRequest) return;
    estimateState = {kind: 'answer', body,
                     summary: `about ${Math.round(Number(body.fraction) * 100)}% of the apolar slab`, reason: ''};
    renderEstimate(); syncSummary();
  }

  // The protein's own size and the box the build starts from ------------------------------------------------------
  //
  // Both numbers are measured by the extent route from the chosen structure's coordinates, with the form's own box
  // margin and initial-z, so a reader moving either sees the box the build would start from rather than a stale
  // estimate. As with the coverage estimate, the question is numbered: a reader can change the protein or a chain
  // while an earlier request is in flight, and a slow answer to an older question must not land on a newer one.
  // The route answers `dimensions_nm` as an `{x, y, z}` object and `initial_box_nm` as an `[x, y, z]` list, so both
  // spellings are read here rather than making the panel assume one the route did not promise.
  const formatExtent = values => {
    const axes = Array.isArray(values) ? values
      : (values && typeof values === 'object' ? ['x', 'y', 'z'].map(axis => values[axis]) : []);
    if (axes.length !== 3 || !axes.every(value => value != null && Number.isFinite(Number(value)))) return '';
    return axes.map(value => Number(value).toFixed(1)).join(' × ');
  };
  let extentState = {kind: 'idle'}, extentRequest = 0, extentTimer, extentController;

  function renderExtent() {
    const size = pdcNode('.new-pdc-protein-size'), box = pdcNode('.new-pdc-box-estimate');
    if (!size || !box) return;
    const hasProtein = !!field('protein').value;
    size.hidden = box.hidden = !hasProtein;
    if (!hasProtein) { setText(size, ''); setText(box, ''); return; }
    const state = extentState;
    if (state.kind === 'answer') {
      setText(size, `${state.dimensions} nm`);
      setText(box, `${state.rule === 'membrane' ? 'membrane box' : 'initial box'} ${state.box} nm`);
      return;
    }
    // A refusal is the route's own sentence; a request still in flight says so instead of leaving the lines blank.
    setText(size, state.kind === 'refused' ? state.reason
      : (state.kind === 'loading' ? 'Measuring the protein and the box it implies…'
        : ''));
    setText(box, '');
  }

  async function loadExtent() {
    const entry = field('protein').value;
    const mine = ++extentRequest;
    // A superseded measurement is cancelled, not left to finish and be dropped: the token guard already keeps its
    // answer off screen, and the abort keeps the server's queue from holding a question nobody will read.
    extentController?.abort();
    extentController = new AbortController();
    if (!entry) {
      extentState = {kind: 'idle'};
      renderExtent();
      return;
    }
    const query = new URLSearchParams({margin_nm: field('box_margin_nm')?.value || '',
                                       initial_z_nm: field('initial_z_nm')?.value || ''});
    // Only a selection that exists is sent; an entry with no ticks is the whole structure, as the estimate reads it.
    const chains = selectedChains();
    if (chains.length) query.set('chains', chains.join(','));
    extentState = {kind: 'loading'};
    renderExtent();
    const entry_id = String(entry).replace(/^\/+/, '');
    let response;
    try {
      response = await fetch(`/api/pdc/proteins/${encodeURIComponent(entry_id)}/extent?${query}`,
                             {signal: extentController.signal});
    } catch (error) {
      if (error.name === 'AbortError' || mine !== extentRequest) return;   // superseded: the newer question owns the line
      extentState = {kind: 'refused', reason: 'The protein’s size could not be read: the coordinator did not answer.'};
      renderExtent();
      return;
    }
    // The route's refusal sentence is JSON (`{error}`); an answer that is not JSON is no measurement at all, so it
    // is reported as a refusal rather than rendered as one.
    let body = {};
    try { body = JSON.parse(await response.text()); } catch (error) { body = {}; }
    if (mine !== extentRequest) return;
    const dimensions = formatExtent(body.dimensions_nm), box = formatExtent(body.initial_box_nm);
    if (!response.ok || !dimensions || !box) {
      extentState = {kind: 'refused',
                     reason: body.error || `the protein’s size was refused (status ${response.status})`};
      renderExtent();
      return;
    }
    // The route's own suggested z box, when it answers one: the Auto button writes this number into the field.
    const autoZ = Number(body.auto_initial_z_nm);
    extentState = {kind: 'answer', dimensions, box, rule: body.rule || 'initial',
                   autoZ: Number.isFinite(autoZ) ? autoZ : undefined};
    renderExtent();
  }

  // One typed margin is one question: wait until the reader stops moving the box before asking the route.
  function scheduleExtent() {
    clearTimeout(extentTimer);
    extentTimer = setTimeout(loadExtent, 250);
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
    // The shape setting is validated in the adapter too, but the card can refuse here first and say what to do:
    // a build with no run selected, a size out of the adapter's 1..5000 range, or a stored mode with an unread list.
    if (shapeMode() === 'build') {
      if (shapeRunsError) return shapeRunsError;
      if (!shapeRunIds.size) return 'Choose at least one micelle-only run to build the conformations from.';
      const size = shapeSize(), seed = shapeSeed();
      if (!Number.isInteger(size) || size < 1 || size > 5000) return 'Size must be a whole number from 1 to 5000.';
      if (!Number.isInteger(seed)) return 'Choose a whole-number seed for the conformation selection.';
    }
    if (shapeMode() === 'stored') {
      if (shapeLibrariesError) return shapeLibrariesError;
      if (!shapeSpec()) return 'Choose a stored library, or build one from runs.';
    }
    return '';
  }

  // Queue holds on readiness and an in-flight submit; Share adds the chosen device's active run, because there is
  // nothing to share with a free device. The dashboard's own `active` map is what says a run is already there.
  function syncStartButtons() {
    const ready = readyState === true;
    $('#start-run').disabled = !ready || submitting;
    const share = $('#start-run-share');
    if (share) share.disabled = !ready || submitting || !gpuDevice.hasActiveRun?.();
  }

  async function checkReadiness() {
    // A check already scheduled by the debounced `input` is superseded by this one; letting it fire after this
    // request settles would disable the launch button again for no new information.
    clearTimeout(readinessTimer);
    const mine = ++generation;
    readyState = false;
    syncStartButtons();
    syncSummary();
    const blocker = gate();
    if (blocker) {
      setText($('#review-status'), 'Action required'); $('#review-status').dataset.ready = 'false';
      setText($('#readiness'), blocker); setText($('#launch-blocker'), blocker);
      syncStartButtons();
      return;
    }
    const query = new URLSearchParams({run_type: 'pdc', molecule_id: field('molecule_id').value,
                                       protein: field('protein').value || '', template: templatePath()});
    try {
      const ready = await api('/api/readiness?' + query);
      if (mine !== generation) return;
      writeReadiness(ready.checks, ready.blockers);
      setText($('#review-status'), ready.ready ? 'Inputs ready' : (ready.blockers?.length ? 'Action required' : 'Not ready'));
      $('#review-status').dataset.ready = String(!!ready.ready);
      setText($('#launch-blocker'), ready.ready ? '' : (ready.blockers?.[0] || 'Inputs are not ready.'));
      readyState = !!ready.ready;
      syncStartButtons();
    } catch (error) {
      if (mine !== generation) return;
      readyState = false;
      syncStartButtons();
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
    let body;
    try {
      body = await api('/api/pdc/proteins/import', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({pdbid})});
    } catch (error) {
      if (button) button.disabled = false;
      if (error.status === undefined) {
        say('.new-pdc-import-status', 'The import could not be read: the coordinator did not answer.');
        return;
      }
      const reason = error.message === `Request failed (${error.status})` ? error.status : error.message;
      say('.new-pdc-import-status', `That import was refused: ${reason}`);
      return;
    }
    if (button) button.disabled = false;
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
    syncChains(); syncSummary(); loadEstimate(); scheduleExtent(); checkReadiness(); renderPreviewState();
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
  //: The line that says the ribbon could not be loaded. Its own element rather than `.new-pdc-preview-basis`, which
  //: carries what the placement measured: a failure of the second request is not a fact about the frame.
  function ribbonNote(text) {
    const note = previewNode('.new-pdc-preview-ribbon-note');
    if (!note) return;
    setText(note, text || '');
    note.hidden = !text;
  }
  let previewFrame = null, previewRequest = 0, previewTimer, previewDraw = 0, previewController;
  // The stage lives on the host element, the way `pdc.js` keeps its own (`viewer.pdcStage`): one owner, and a test
  // or a console can reach the thing that is drawn without a hook this module would have to publish.
  const previewStage = () => previewNode('.new-pdc-preview-viewer')?.previewStage || null;

  // The Ribbon switch is about the protein, and an empty micelle has none: no all-atom structure to draw under the
  // detergent beads. It is disabled with a reason rather than left clickable and silently doing nothing, and its
  // previous state is kept while it is unavailable so choosing a protein again restores the reader's choice.
  function syncPreviewControls() {
    const hasProtein = !!field('protein').value;
    const ribbon = previewNode('.new-pdc-preview-ribbon input');
    if (!ribbon) return;
    const label = ribbon.closest('label');
    ribbon.disabled = !hasProtein;
    if (label) {
      label.title = hasProtein
        ? 'Draw the all-atom structure the beads were coarse-grained from, as a ribbon under the detergent beads'
        : 'Disabled · an empty micelle has no all-atom protein ribbon';
    }
    if (!hasProtein) {
      if (ribbon.dataset.savedChecked === undefined) ribbon.dataset.savedChecked = String(ribbon.checked);
      ribbon.checked = false;
    } else if (ribbon.dataset.savedChecked !== undefined) {
      ribbon.checked = ribbon.dataset.savedChecked !== 'false';
      delete ribbon.dataset.savedChecked;
    }
  }

  function previewInputs() {
    const shape = shapeSpec();
    return {protein: field('protein').value || '', chains: selectedChains(),
            mapping: field('mapping_candidate').value || '', molecule: field('molecule_id').value || '',
            template: templatePath(), count: field('aggregation_number').value || '',
            mode: placementMode(), seed: field('pdc_seed').value || '',
            gap: field('belt_gap_nm').value || '',
            bodyGap: field('min_body_gap_nm').value || '',
            axialWindow: field('belt_axial_window_nm').value || '',
            margin: field('box_margin_nm').value || '', initial_z: field('initial_z_nm').value || '',
            prepare: preparing(), shape: shape ? JSON.stringify(shape) : ''};
  }
  // What would be coarse-grained, or drawn from another mapping: a change to one of these is a different question,
  // and the frame on screen is no longer this form's. Everything the reader can still move without new
  // coarse-graining re-derives instead. The shape spec joins them because resolving a library reads trajectories:
  // a changed library is a different draw, and a build from runs can be the expensive part of the derive.
  const previewExpensive = inputs => `${inputs.protein}|${inputs.chains.join(',')}|${inputs.mapping}|${inputs.molecule}|${inputs.prepare}|${inputs.shape}`;
  const previewCheap = inputs => [inputs.count, inputs.mode, inputs.seed, inputs.margin, inputs.initial_z,
                                  inputs.gap, inputs.bodyGap, inputs.axialWindow, inputs.template].join('|');

  function seconds(value) {
    const count = Number(value) || 0;
    return `${count >= 1 ? count.toFixed(1) : count.toFixed(3)} s`;
  }
  const kilobytes = bytes => `${Math.max(1, Math.round((Number(bytes) || 0) / 1024))} KB`;
  // A distance the placement measured, at the resolution every other nanometre on this card is printed at.
  const nanometres = value => `${Number(value).toFixed(2)} nm`;

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
    // The plan's step 1, when this derive asked for it: the number is the tool's own wall time, and the tool's own
    // count of what it built, rather than a headline from a plan.
    const prepare = cost.prepare_seconds
      ? ` · PDB2PQR ${seconds(cost.prepare_seconds)}` + (basis?.prepare?.heavy_atoms_added != null
          ? ` (${basis.prepare.heavy_atoms_added} heavy atoms)`
          : '')
      : '';
    if (!basis?.protein_beads) return `no coarse-graining — the micelle is placed directly: ${placement}${mapping}`;
    return cost.cg_cached
      ? `the coarse-grained protein was already cached (${kilobytes(cost.cg_bytes)}) · ${placement}${mapping}${prepare}`
      : `martinize2 ${seconds(cost.coarse_graining_seconds)} (${basis.protein_beads} beads) · ${placement}${mapping}${prepare}`;
  }

  function keptSentence(cost, basis) {
    return basis?.protein_beads
      ? `the coarse-grained protein, in this workspace's preview/cg/${cost.cg_key} (${kilobytes(cost.cg_bytes)}); `
        + 'the frames are not kept — a run re-derives its own snapshot'
      : 'nothing: an empty micelle coarse-grains nothing, and the frames are not kept';
  }

  // Why the frame on screen is no longer this form's, named: a shape change is not a protein change, and the
  // existing sentence is kept verbatim for the protein/subunit/mapping case the preview's own test pins.
  function staleSentence(inputs, moment) {
    const before = previewFrame.inputs;
    const drawn = before.protein !== inputs.protein || before.chains.join(',') !== inputs.chains.join(',')
      || before.mapping !== inputs.mapping || before.molecule !== inputs.molecule || before.prepare !== inputs.prepare;
    const shape = before.shape !== inputs.shape;
    if (!shape) return `The protein, the subunits or the mapping have changed since this ${moment} — derive it again.`;
    if (!drawn) return `The detergent shape has changed since this ${moment} — derive it again.`;
    return `The protein, the subunits, the mapping and the detergent shape have changed since this ${moment} — derive it again.`;
  }

  // The preview's own sentence about the conformations it draws. The default is the single-conformation build; a
  // derived frame naming a resolved library replaces it with the key and size (never coordinates). The fallback is
  // deliberate: a body without `basis.conformations` -- the server has not answered with one, or the derive was
  // refused -- keeps the sentence the card shows for a build with no library.
  const SINGLE_SHAPE_LINE = "One rigid conformation. No library; the template's own coordinates are rotated onto every site.";
  function previewLibraryLine() {
    // `single` is today's build whatever a body says: there is no library in that mode.
    if (shapeMode() === 'single') return SINGLE_SHAPE_LINE;
    const frame = previewFrame;
    const shape = shapeSpec();
    const conformations = frame && !frame.refused && frame.body?.basis?.conformations;
    if (conformations && frame.inputs.shape === (shape ? JSON.stringify(shape) : '')) {
      const parts = [];
      if (conformations.key) parts.push(`Library ${conformations.key}`);
      const size = Number(conformations.size);
      if (Number.isFinite(size)) parts.push(`${size.toLocaleString('en-US')} conformations`);
      const sources = Array.isArray(conformations.sources) ? conformations.sources.length : 0;
      if (sources) parts.push(`from ${sources} run${sources === 1 ? '' : 's'}`);
      if (parts.length) return parts.join(' · ');
    }
    return SINGLE_SHAPE_LINE;
  }
  function syncPreviewLibrary() {
    const line = previewNode('.new-pdc-preview-library');
    if (line) setText(line, previewLibraryLine());
  }

  function renderPreviewState() {
    const state = previewNode('.new-pdc-preview-state');
    syncPreviewLibrary();
    if (!state || !previewFrame) return;
    const stale = previewExpensive(previewFrame.inputs) !== previewExpensive(previewInputs());
    state.classList.toggle('stale', stale);
    if (previewFrame.refused) {
      state.textContent = stale
        ? staleSentence(previewInputs(), 'refusal')
        : (previewFrame.unreadable
            ? 'No answer came back to read; the sentence above says so.'
            : 'The build refuses these inputs; the sentence above is its own.');
      return;
    }
    state.textContent = stale
      ? staleSentence(previewInputs(), 'frame was derived')
      : (previewCheap(previewFrame.inputs) !== previewCheap(previewInputs())
          ? 'Derived for the inputs below; the count, the style, the seed or the box have moved since.'
          : 'Derived for the inputs on this form.');
  }

  function previewQuery(inputs) {
    const query = new URLSearchParams({template: inputs.template, molecule_id: inputs.molecule,
                                       aggregation_number: inputs.count, placement_mode: inputs.mode,
                                       pdc_seed: inputs.seed,
                                       // Always stated, so a frame cannot be read as one the other choice made: a
                                       // derive that asked for the preparation and one that did not are two
                                       // different coarse-grained proteins (the server keys its cache on it).
                                       prepare_protein: inputs.prepare ? 'true' : 'false'});
    // A catalogue id can be an absolute path for an imported structure, and the route reads such a path with its
    // leading slash stripped -- the same spelling the estimate's own call uses.
    if (inputs.protein) query.set('protein', String(inputs.protein).replace(/^\/+/, ''));
    if (inputs.chains.length) query.set('chains', inputs.chains.join(','));
    if (inputs.mapping) query.set('mapping_candidate', inputs.mapping);
    if (inputs.margin) query.set('box_margin_nm', inputs.margin);
    if (inputs.initial_z) query.set('initial_z_nm', inputs.initial_z);
    if (inputs.gap) query.set('belt_gap_nm', inputs.gap);
    if (inputs.bodyGap) query.set('min_body_gap_nm', inputs.bodyGap);
    if (inputs.axialWindow) query.set('belt_axial_window_nm', inputs.axialWindow);
    // The shape spec travels as JSON, URL-encoded by `URLSearchParams`: `single` has no spec and sends nothing,
    // exactly as the submit payload does not.
    if (inputs.shape) query.set('conformation_library', inputs.shape);
    return query;
  }

  // The picture's own representation ----------------------------------------------------------------------------
  //
  // One frame and one claim about it: the **detergent's** beads, on the Martini 3 polarity family the file carries
  // in its b-factor column -- the one thing a bead's size cannot say. The protein's beads are still in the frame: the
  // PDB is the artifact a run records as its first snapshot, and it numbers the protein's beads 1..N before the
  // detergent's molecules. `basis.protein_residues` says how many of those there are, so the detergent's
  // representation is the frame minus those residue numbers; an empty micelle (0) draws the whole frame. Nothing
  // covers the protein's beads, and the all-atom structure they were coarse-grained from is the ribbon beneath them.
  //
  // The selection is NGL's own grammar on residue numbers: measured in the page, `resname PRO` is a parse error and
  // `:PRO` is read as a chain, while bare `1-4` is the residue range this build parses. The b-factor column already
  // means the family, so the frame is drawn as it is rather than rewritten.
  const detergentSelection = proteinResidues => (proteinResidues ? `not (1-${proteinResidues})` : '*');

  // The protein as the structure it was coarse-grained from ------------------------------------------------------
  //
  // The beads are a coarse-grained model *of* a structure, and the two are one picture here: the server names the
  // all-atom file martinize2 was handed in `basis.protein_structure` (its cache key and the URL that serves it, so
  // this file never builds a URL), and it is drawn as a ribbon **under** the beads. Both are in one frame --
  // martinize2 writes its beads in the coordinates it read -- so nothing is transformed to overlay them.
  //
  // The ribbon makes no claim of its own. One neutral grey that is no Martini family's colour, so it cannot be
  // decoded as one: the colours in this picture are the *beads'*. It is
  // also drawn first and with `depthWrite: false`, which is what makes "under" true in the renderer as well as in
  // the prose -- a surface that wrote depth would cut holes in the beads in front of it and be cut by the ones behind.
  // `side: 'front'` keeps the ribbon from blending its own far wall through its near one: measured on 1AT9, both
  // sides accumulated to a near-opaque grey wherever helices are dense, which made the backdrop read as the subject.
  //
  // Which representation is the ribbon is asked of the bundle rather than assumed. This vendored NGL is 2.3.1
  // (`vendor/ngl.js.source.json`), and its `NGL.RepresentationRegistry` -- the registry `addRepresentation` looks a
  // name up in, and which carries `names` and `get(name)` rather than a `nameList` -- lists `cartoon`, `ribbon`,
  // `backbone`, `trace` and `tube` among the twenty-four it knows. `cartoon` is the one taken, because it is the only
  // one that draws helices as helices from the file's own `HELIX`/`SHEET` records -- which `pdc_build.select_protein`
  // keeps, so a deposited structure arrives with its secondary structure in it. The order below is the fallback: a
  // spline tube (`backbone`), then the C-alpha `trace`, neither of which needs anything but a backbone trace.
  const PREVIEW_RIBBON_REPRESENTATIONS = ['cartoon', 'ribbon', 'backbone', 'trace'];
  //: A grey no Martini family owns, so the ribbon under the beads cannot be decoded as one.
  const PREVIEW_RIBBON_COLOUR = '#adb5bd';
  //: Firm, not faint: a ribbon at a third opacity measured as a grey smear rather than the helices it is. It writes
  //: no depth, so it cannot paint over a detergent bead in front of it.
  const PREVIEW_RIBBON_OPACITY = 0.85;

  function ribbonRepresentation() {
    const registry = NGL.RepresentationRegistry;
    return PREVIEW_RIBBON_REPRESENTATIONS.find(name => !!(registry && registry.get(name))) || null;
  }

  // The ribbon's own redraw, from the component the load left on the host and the control's state at drawing time:
  // toggling it removes or adds the ribbon's representation and touches nothing else -- not the beads, not the
  // server, not the state line.
  function drawPreviewRibbon() {
    const ribbon = previewNode('.new-pdc-preview-viewer')?.previewRibbon;
    if (!ribbon) return;
    for (const representation of [...ribbon.reprList]) ribbon.removeRepresentation(representation);
    // Read from the control at drawing time: a view of the frame on screen, never an input to it -- absent from
    // `previewInputs`, sending nothing, leaving the state line alone.
    if (!previewNode('.new-pdc-preview-ribbon input')?.checked) return;
    const name = ribbonRepresentation();
    if (!name) return;
    ribbon.addRepresentation(name, {colorScheme: 'uniform', colorValue: PREVIEW_RIBBON_COLOUR,
                                    opacity: PREVIEW_RIBBON_OPACITY, depthWrite: false, side: 'front',
                                    useInteriorColor: false});
  }

  // The loaded frame's beads, drawn together: the detergent's on their families, nothing over the protein's. The
  // protein residue count is kept on the host element beside `previewStage` and `previewComponent`, because the
  // Ribbon control redraws the representations of the frame that is already here rather than asking the server again.
  function drawPreviewRepresentations() {
    const host = previewNode('.new-pdc-preview-viewer'), component = host?.previewComponent;
    if (!component) return;
    for (const representation of [...component.reprList]) component.removeRepresentation(representation);
    const beads = {...BEAD_RADIUS_PARAMETERS, ...BEAD_FAMILY_PARAMETERS};
    component.addRepresentation('ball+stick', {sele: detergentSelection(Number(host.previewProteinResidues) || 0),
                                                ...beads});
  }

  async function showPreviewFrame(pdb, proteinResidues, structure) {
    const host = previewNode('.new-pdc-preview-viewer');
    if (!host) return;
    // The shell no longer carries NGL: it is 1.28 MB and only a 3D stage needs it, so the bundle arrives with the
    // first thing there is to draw (`ngl-loader.js`). A bundle that cannot load leaves the preview empty; the panel's
    // own numbers, legend and controls are drawn from the server's answer and do not depend on it.
    try { await ensureNgl(); } catch (error) { return; }
    // The stage is built the moment there is something to draw, and asked to resize on a tab show and a window
    // change: NGL sizes its drawing buffer when the stage is built and only recomputes it when asked, so a stage
    // built at one width keeps that buffer inside a host that later grows.
    if (!host.previewStage) host.previewStage = new NGL.Stage(host, {backgroundColor: 'white'});
    const stage = host.previewStage;
    stage.removeAllComponents();
    host.previewComponent = null;
    host.previewRibbon = null;
    host.previewProteinResidues = Number(proteinResidues) || 0;
    ribbonNote('');
    // Which draw this is. NGL resolves a `loadFile` whenever the file arrives, so a derive pressed while an earlier
    // frame is still loading would otherwise add the older picture on top of the newer one: a draw that is no longer
    // the latest drops its component instead of stacking it.
    const draw = ++previewDraw;
    const superseded = () => draw !== previewDraw;
    // The ribbon is loaded **first and waited for**, so the beads are added to the stage after it: NGL draws its
    // components in the order they were added, and two layers that swap places depending on which file arrived first
    // would flicker between derives. A URL the server named but that cannot be fetched (an entry pruned between the
    // two requests) leaves the beads and says so, rather than showing a picture that silently lost half of itself.
    const ribbon = structure?.url
      ? stage.loadFile(structure.url, {ext: 'pdb', defaultRepresentation: false}).then(component => {
          if (superseded()) { stage.removeComponent(component); return null; }
          host.previewRibbon = component;
          drawPreviewRibbon();
          return component;
        }).catch(error => {
          if (superseded()) return null;
          ribbonNote(`The all-atom structure the beads were coarse-grained from could not be loaded `
                     + `(${error.message || error}), so there is no ribbon under them: the beads are the frame's own.`);
          return null;
        })
      : Promise.resolve(null);
    // The guess is off, not optional. A coarse-grained bead has no element and no covalent radius, so NGL's
    // distance-based `inferBonds` draws head beads onto tail beads -- measured in `pdc.js` at 90 bonds on a frame
    // the model bonds 60 ways. The file carries the model's own bonds as CONECT records whenever the build has a
    // mapping; when it carries none (a centres-only build, one bead per molecule) there is no bond to draw at all.
    // The all-atom structure above keeps the guess: it has elements, and no `CONECT` records to trust instead.
    ribbon.then(() => (superseded() ? null
                                    : stage.loadFile(new Blob([pdb], {type: 'text/plain'}),
                                                     {ext: 'pdb', inferBonds: 'none'})))
      .then(component => {
        if (!component) return;
        if (superseded()) { stage.removeComponent(component); return; }
        applyBeadRadii(component.structure, {scale: PREVIEW_BEAD_SCALE});
        host.previewComponent = component;
        // Both of the module's answers go on the representation: the radius each bead's own size class gives it, and
        // the colour its type family gives it.
        drawPreviewRepresentations();
        component.autoView();
        stage.handleResize();
      }).catch(error => sayPreview('.new-pdc-preview-basis',
                                   `The frame the server sent could not be drawn: ${error.message || error}`));
  }

  // What the placement measured, beside the picture --------------------------------------------------------------
  //
  // Two things the run's own basis now carries and the card could not say before: the **shell** the sites were
  // placed on, and -- when the count the reader asked for does not fit -- the count the shape would hold. Both are
  // read from `basis` as the server wrote them and rendered as they arrived; nothing here measures anything.
  //
  // The shell sentence is the sphere's, and only the sphere's: a belt's geometry is a torus about a centre-line and
  // its numbers are the band's (`band_radius_nm`, printed in the Box row), so a sentence built from `shell_radius_nm`
  // there would describe a shape the build did not make. Each clause is dropped rather than printed as null or NaN:
  // a template whose molecule states no coordinates has no bead count to report and its own recorded reason instead,
  // and an empty micelle has no bead to be closest to.
  function shellClauses(basis) {
    if (!basis || basis.placement_shape !== 'sphere' || basis.shell_radius_nm == null) return [];
    const clauses = [`the shell is ${nanometres(basis.shell_radius_nm)}`];
    // Which of the two numbers decided the radius, in the placement's own two words (`radius_source`): the protein's
    // measurement, or the setting used as a floor under it.
    if (basis.radius_source === 'measured') clauses.push('measured from the protein this selection includes');
    else if (basis.radius_source === 'floor') clauses.push('the radius setting, which the protein did not reach past');
    const beads = basis.body_profile?.bead_count;
    if (beads != null) clauses.push(`clearance measured against all ${beads} beads of the detergent`);
    else if (basis.body_profile_reason) clauses.push(basis.body_profile_reason);
    if (basis.bead_clearance_nm != null) clauses.push(`closest bead to the protein ${nanometres(basis.bead_clearance_nm)}`);
    if (basis.estimated_density_per_nm3 != null) {
      clauses.push(`${Number(basis.estimated_density_per_nm3).toFixed(2)} detergents per nm3`);
    }
    return clauses;
  }

  // The count the shape would hold, when the placement measured one: `0` is a measurement too -- nothing fits -- and
  // is not a count a reader can use, so only a positive count reaches the paragraph and the button.
  function measuredCapacity(basis) {
    const measurement = basis?.capacity_aggregation;
    const count = Number(measurement?.count);
    if (!measurement || !Number.isFinite(count) || count <= 0) return null;
    return {count, seeds: Array.isArray(measurement.seeds) ? measurement.seeds : []};
  }

  // The two paragraphs and the button, for an answer and for a refusal alike: a refusal's basis carries the same
  // measurement (the gate measured what fits in order to write its own sentence), so the reader can see the number
  // behind the refusal and take it without waiting for a second derive.
  function renderPreviewPlacement(basis) {
    const shell = previewNode('.new-pdc-preview-shell'), capacity = previewNode('.new-pdc-preview-capacity');
    const button = previewNode('.new-pdc-preview-use-capacity');
    const clauses = shellClauses(basis);
    if (shell) { shell.hidden = !clauses.length; setText(shell, clauses.join(' - ')); }
    const measured = measuredCapacity(basis);
    if (capacity) {
      capacity.hidden = !measured;
      setText(capacity, measured
        ? `The placement measured what fits: about ${measured.count} detergents, over ${measured.seeds.length} seeds, `
          + 'at the 0.25 nm overlap gate.'
        : '');
    }
    if (button) {
      button.hidden = !measured;
      setText(button, measured ? `Use ${measured.count}` : '');
      if (measured) button.dataset.count = String(measured.count); else delete button.dataset.count;
    }
  }

  function renderPreviewFrame(body) {
    const basis = body.basis || {}, cost = body.cost || {}, box = basis.box_nm || [];
    const viewer = previewNode('.new-pdc-preview-viewer'), refusal = previewNode('.new-pdc-preview-refusal');
    if (refusal) { refusal.hidden = true; refusal.textContent = ''; }
    if (viewer) viewer.hidden = false;
    showPreviewFrame(body.pdb || '', basis.protein_residues, basis.protein_structure);
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
    const bandMin = Number(basis.band_radius_min_nm), bandMax = Number(basis.band_radius_max_nm);
    const bandSentence = Number.isFinite(bandMin) && Number.isFinite(bandMax) && Math.abs(bandMax - bandMin) > 0.05
      ? ` · the belt follows the protein at ${bandMin.toFixed(2)}–${bandMax.toFixed(2)} nm in the membrane plane`
      : (basis.band_radius_nm
          ? ` · the belt is a band of radius ${Number(basis.band_radius_nm).toFixed(2)} nm in the membrane plane`
          : '');
    sayPreview('.new-pdc-preview-box', `${box.map(value => Number(value).toFixed(2)).join(' × ')} nm — the box the build `
      + 'writes, before equilibration changes it' + bandSentence);
    sayPreview('.new-pdc-preview-cost', costSentence(cost, basis));
    sayPreview('.new-pdc-preview-kept', keptSentence(cost, basis));
    renderPreviewPlacement(basis);
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
    // A load still in flight belongs to the picture being replaced, and it must not land on this one: bumping the
    // draw token makes it drop its component instead of drawing a frame beside a refusal.
    previewDraw += 1;
    const host = previewNode('.new-pdc-preview-viewer');
    if (host) { host.previewComponent = null; host.previewRibbon = null; host.previewProteinResidues = 0; }
    ribbonNote('');
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
    renderPreviewPlacement(basis);
    renderPreviewState();
  }

  async function derivePreview() {
    const inputs = previewInputs();
    const mine = ++previewRequest;
    // The debounce asked again, so the answer nobody will read is cancelled rather than waited for. The token guard
    // below still drops a reply that was already in flight; the abort keeps the build queue from working on it.
    previewController?.abort();
    previewController = new AbortController();
    const state = previewNode('.new-pdc-preview-state');
    if (state) { state.classList.remove('stale'); setText(state, 'Deriving the placement…'); }
    let response, body = {};
    try {
      response = await fetch('/api/pdc/preview/placement?' + previewQuery(inputs),
                             {signal: previewController.signal});
    } catch (error) {
      if (error.name === 'AbortError' || mine !== previewRequest) return;   // superseded: the newer question owns the card
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
      previewFrame = {inputs, refused: true, body};
      renderPreviewRefusal(body.error || `the preview was refused (status ${response.status}).`, null);
      return;
    }
    // The body is kept, not only its verdict: the preview's shape line reads `basis.conformations` from it.
    previewFrame = {inputs, refused: !body.valid, body};
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
    // A library is stored per residue, so the list follows the detergent and not only the first mount.
    loadShapeLibraries();
  });
  field('template').addEventListener('change', () => {
    describeTemplate(); store(); syncSummary(); checkReadiness(); previewMoved(); loadShapeLibraries();
  });
  field('protein').addEventListener('change', () => { syncChains(); store(); syncSummary(); loadEstimate(); scheduleExtent(); checkReadiness(); renderPreviewState(); });
  // The subunit ticks are rebuilt whenever the chosen entry changes, so the listener sits on the group that holds
  // them: a per-box handler would be lost with the box it was bound to. Every tick is a change to the question the
  // estimate answers, so the route is asked again and the numbers move with the choice.
  pdcNode('.new-pdc-chain-list')?.addEventListener('change', () => {
    describeChains(); store(); syncSummary(); loadEstimate(); scheduleExtent(); checkReadiness(); renderPreviewState();
  });
  field('mapping_candidate').addEventListener('change', () => { rememberMapping(); store(); syncSummary(); loadEstimate(); checkReadiness(); renderPreviewState(); });
  // Every number the adapter reads. `input` keeps the summary and the gate current while a value is typed -- a
  // number input fires `change` only on blur, so a gate that listened for that alone would leave the reader looking
  // at a blocker they had already cleared (and one readiness fetch per keystroke is noise, so it is debounced);
  // `change` settles it at once when the field is left.
  for (const name of NUMBERS) {
    const input = field(name);
    if (!input) continue;
    input.addEventListener('input', () => { syncSummary(); store(); if (!applyingPreset) refreshReadinessSoon(); });
    input.addEventListener('change', () => { syncSummary(); store(); if (!applyingPreset) checkReadiness(); });
  }
  field('aggregation_number').addEventListener('input', loadEstimate);
  field('pdc_placement_mode')?.addEventListener('change', () => { store(); syncSummary(); checkReadiness(); previewMoved(); });
  // The shape source and its inputs: each is a different question for the preview, so an existing frame is marked
  // stale rather than redrawn -- resolving a library can read a whole trajectory. The stored list is not re-read
  // by this listener; it is read on mount, after a submit, and when the detergent changes.
  for (const input of form.querySelectorAll('input[name="shape_source"]')) {
    input.addEventListener('change', shapeChanged);
  }
  for (const name of ['conformations_size', 'conformations_seed']) {
    const input = field(name);
    if (!input) continue;
    input.addEventListener('input', () => { syncShapeStatus(); store(); renderPreviewState(); refreshReadinessSoon(); });
    input.addEventListener('change', shapeChanged);
  }
  pdcNode('.eligible-runs')?.addEventListener('change', event => {
    const box = event.target;
    if (!box || box.type !== 'checkbox') return;
    if (box.checked) shapeRunIds.add(box.value); else shapeRunIds.delete(box.value);
    shapeChanged();
  });
  pdcNode('.stored-libraries')?.addEventListener('change', event => {
    const radio = event.target;
    if (!radio || radio.type !== 'radio') return;
    shapeLibraryKey = radio.value;
    shapeChanged();
  });
  field('backmap')?.addEventListener('change', () => { store(); syncSummary(); checkReadiness(); });
  field('remove_out_of_micelle')?.addEventListener('change', () => { store(); syncSummary(); checkReadiness(); });
  field('protein_vsite')?.addEventListener('change', () => { store(); syncSummary(); });
  // Named stage-setting presets ---------------------------------------------------------------------------------
  //
  // The store is the workspace's (`/api/setting-presets`, run type `pdc`), the same one the validation panel uses.
  // A preset here is every named control in the Stage settings fieldset: the five stages, their per-stage timesteps
  // and the six groups that used to be a separate fold. The bar's ids are the engine's own (the validation page
  // renders them, which is what keeps the id contract), but this module owns the handlers because the engine's panel
  // is not created on this workspace.
  let presets = [], appliedPreset = null, presetsGeneration = 0, applyingPreset = false;
  // Read live rather than listed by hand: a control added to the fieldset is a preset setting without a second
  // edit, and a control with no `name` (the derived step count) is never captured -- it is never submitted either.
  const PDC_PRESET_FIELDS = () => [...(pdcNode('fieldset.new-pdc-stages')?.querySelectorAll('[name]') || [])];
  function presetSettings() {
    const settings = {};
    for (const control of PDC_PRESET_FIELDS()) {
      if (control.value === '' || control.value == null) continue;
      settings[control.name] = control.value;
    }
    return settings;
  }
  const presetById = id => presets.find(item => item.id === id) || null;
  function renderPresetMarker() {
    const isDefault = !!presetById(appliedPreset?.id)?.is_default;
    setText(pdcNode('.preset-marker'), appliedPreset
      ? `Applied preset: ${appliedPreset.name}${isDefault ? ' · default' : ''}` : 'Profile defaults');
  }
  function renderPresetOptions() {
    const select = pdcNode('.preset-select'), chosen = appliedPreset?.id || '';
    select.replaceChildren(new Option('Profile defaults (no preset)', ''));
    for (const preset of presets) {
      select.append(new Option(`${preset.name}${preset.is_default ? ' · default' : ''}`, preset.id));
    }
    select.value = presets.some(preset => preset.id === chosen) ? chosen : '';
    if (!select.value) appliedPreset = null;
    renderPresetMarker();
  }
  async function loadPresets() {
    const generation = ++presetsGeneration;
    try {
      const answer = await api('/api/setting-presets?' + new URLSearchParams({run_type: 'pdc'}));
      if (generation !== presetsGeneration) return null;
      presets = answer.presets || [];
      renderPresetOptions();
      return answer;
    } catch (error) { notice(error.message); return null; }
  }
  // A stored preset comes back in the adapter's normalized spelling, which is the builders' short name for the five
  // settings `DEFAULT_ALIASES` maps (`nvt_ps` for `pdc_nvt_ps`, `assessment_ns` for `pdc_assessment_ns`, and so on).
  // Translate those back onto the panel's controls, then translate the two global timesteps a preset saved before
  // per-stage timesteps carries: equil -> NVT + NPT, production -> assessment + extension, so an old preset restores
  // the same physics.
  function presetSettingsToPanel(stored) {
    const settings = {};
    for (const [key, value] of Object.entries(stored || {})) settings[DEFAULT_ALIASES[key] || key] = value;
    const legacy = [['pdc_equil_dt_fs', ['pdc_nvt_dt_fs', 'pdc_npt_dt_fs']],
                    ['pdc_production_dt_fs', ['pdc_assessment_dt_fs', 'pdc_extension_dt_fs']]];
    for (const [old, legs] of legacy) {
      if (settings[old] === undefined) continue;
      for (const leg of legs) if (settings[leg] === undefined) settings[leg] = settings[old];
    }
    return settings;
  }
  function applyPreset(preset) {
    const settings = presetSettingsToPanel(preset.settings);
    // A preset moves many controls at once; firing each one's readiness check would queue one fetch per control.
    // The events still fire (the facts, the step boxes and the stored form follow them), and readiness is asked once
    // when the whole preset has landed.
    applyingPreset = true;
    try {
      for (const control of PDC_PRESET_FIELDS()) {
        if (!(control.name in settings)) continue;
        const value = String(settings[control.name]);
        // A stored value the form cannot offer -- a device this host lost -- is skipped rather than blanking it.
        if (control.tagName === 'SELECT' && ![...control.options].some(option => option.value === value)) continue;
        control.value = value;
        control.dispatchEvent(new Event('input', {bubbles: true}));
        control.dispatchEvent(new Event('change', {bubbles: true}));
      }
    } finally {
      applyingPreset = false;
    }
    appliedPreset = {id: preset.id, name: preset.name};
    const select = pdcNode('.preset-select');
    if ([...select.options].some(option => option.value === preset.id)) select.value = preset.id;
    renderPresetMarker();
    gpuDevice.refresh();
    syncTimeRows();
    syncSummary();
    store();
    refreshReadinessSoon();
  }
  pdcNode('.preset-load')?.addEventListener('click', () => {
    const preset = presetById(pdcNode('.preset-select')?.value);
    if (preset) applyPreset(preset);
  });
  pdcNode('.preset-save')?.addEventListener('click', async () => {
    const name = window.prompt('Name this preset', presetById(pdcNode('.preset-select')?.value)?.name || '');
    if (name === null) return;
    if (!name.trim()) { notice('A preset needs a name.'); return; }
    try {
      const answer = await post('/api/setting-presets',
                                {name: name.trim(), run_type: 'pdc', settings: presetSettings()});
      appliedPreset = {id: answer.preset.id, name: answer.preset.name};
      await loadPresets();
      notice(`Preset ${answer.preset.name} saved.`);
    } catch (error) { notice(error.message); }
  });
  pdcNode('.preset-default')?.addEventListener('click', async () => {
    const preset = presetById(pdcNode('.preset-select')?.value);
    if (!preset) { notice('Select a preset to make it the default.'); return; }
    try {
      await api(`/api/setting-presets/${encodeURIComponent(preset.id)}`,
                {method: 'PATCH', headers: {'Content-Type': 'application/json'},
                 body: JSON.stringify({is_default: true})});
      await loadPresets();
      notice(`${preset.name} is the pdc default.`);
    } catch (error) { notice(error.message); }
  });
  pdcNode('.preset-delete')?.addEventListener('click', async () => {
    const preset = presetById(pdcNode('.preset-select')?.value);
    if (!preset) { notice('Select a preset to delete.'); return; }
    if (!window.confirm(`Delete the preset “${preset.name}”?`)) return;
    try {
      await api(`/api/setting-presets/${encodeURIComponent(preset.id)}`, {method: 'DELETE'});
      if (appliedPreset?.id === preset.id) appliedPreset = null;
      await loadPresets();
      notice(`Preset ${preset.name} deleted.`);
    } catch (error) { notice(error.message); }
  });

  // Each leg's restraint choice moves its editor's facts line and nothing else, but it is a run setting like any
  // other: stored, summarised and re-checked.
  for (const leg of RESTRAINT_LEGS) {
    field('pdc_posres_' + leg)?.addEventListener('change', () => { store(); syncSummary(); checkReadiness(); });
  }
  // A seed is drawn, not defaulted: an integer from 1 through today's date, the one value no catalogue default can
  // supply. It dispatches `input` and `change`, so the gate, the stored form, the review and readiness all follow.
  pdcNode('.pdc-generate-seed')?.addEventListener('click', () => {
    const input = field('pdc_seed');
    if (!input) return;
    input.value = String(1 + Math.floor(Math.random() * todaySeed()));
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  });

  // The Default buttons. The engine's `.use-default` loop reads `/api/defaults`, which answers 400 for a pdc
  // payload because it describes the one-molecule run; this panel reads the catalogue it already fetched, under its
  // own class, so the two handlers can never both fire on one button.
  const CATALOGUE_KEY = Object.fromEntries(Object.entries(DEFAULT_ALIASES).map(([key, name]) => [name, key]));
  for (const button of form.querySelectorAll('.pdc-default')) {
    button.addEventListener('click', () => {
      const name = button.dataset.field;
      const input = field(name);
      if (!input) return;
      // The seed's default is the project's own: today's date. It is no catalogue number, so it is written here.
      if (name === 'pdc_seed') input.value = String(todaySeed());
      // A per-stage timestep has no catalogue default: blank is the reviewed profile's own dt, so Default clears it.
      else if (DT_FIELDS.has(name)) input.value = '';
      else {
        const value = (catalogue?.defaults || {})[CATALOGUE_KEY[name] || name];
        if (value === undefined) return;
        input.value = String(value);
      }
      input.dispatchEvent(new Event('input', {bubbles: true}));
      input.dispatchEvent(new Event('change', {bubbles: true}));
    });
  }
  // The derived step box: editing it back-solves the duration at that stage's own timestep, so a reader may state
  // either end of the same arithmetic. No `name` means it is never submitted and never stored as a setting.
  for (const box of form.querySelectorAll('.pdc-steps')) {
    box.addEventListener('input', () => {
      const stage = box.dataset.stage, row = TIME_ROWS[stage];
      const dt = row ? stageNumber(row.dt) : null;
      const steps = Number(box.value);
      if (!row || dt === null || box.value === '' || !Number.isFinite(steps) || steps < 0) return;
      const duration = row.unit === 'ps' ? steps * dt / 1000 : steps * dt / 1000000;
      const input = field(row.duration);
      if (!input) return;
      input.value = String(Math.round(duration * 1000) / 1000);
      input.dispatchEvent(new Event('input', {bubbles: true}));
      input.dispatchEvent(new Event('change', {bubbles: true}));
    });
    box.addEventListener('change', () => syncTimeRow(box.dataset.stage));
  }
  // The estimate's info button: hover and keyboard focus show the tip through CSS, and a tap has no hover, so a click
  // toggles it. Escape or a click elsewhere closes it -- the same contract as the engine's per-setting buttons.
  const estimateHead = pdcNode('.new-pdc-estimate-head');
  const estimateInfo = estimateHead?.querySelector('.info-btn');
  const estimateTip = estimateHead?.querySelector('.setting-tip');
  const closeEstimateTip = () => {
    estimateTip?.classList.remove('is-open');
    estimateInfo?.setAttribute('aria-expanded', 'false');
    // Focus on the button shows the tip through CSS (:focus-within), so closing it while the button still has the
    // focus would leave the tip on screen and the state attribute saying otherwise.
    if (document.activeElement === estimateInfo) estimateInfo.blur();
  };
  estimateInfo?.addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    const open = estimateTip?.classList.toggle('is-open');
    estimateInfo.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeEstimateTip(); });
  document.addEventListener('click', event => {
    if (!event.target.closest?.('.new-pdc-estimate-head')) closeEstimateTip();
  });
  // The prepare step changes what martinize2 reads, so it is one of the expensive inputs: the frame on screen is no
  // longer this form's once it moves, and the card says so rather than quietly drawing the old one.
  pdcNode('.new-pdc-import-button')?.addEventListener('click', importStructure);
  // The preview's own cheap inputs: each of these re-derives a frame that already exists, and the exchange rate is
  // the cache -- the coarse-grained protein is not rebuilt -- which is why these move and the three expensive ones
  // only mark the frame stale.
  field('aggregation_number').addEventListener('input', previewMoved);
  for (const name of ['pdc_seed', 'box_margin_nm', 'initial_z_nm', 'belt_gap_nm', 'min_body_gap_nm',
                      'belt_axial_window_nm']) field(name)?.addEventListener('input', previewMoved);
  // The box's own two inputs also move the estimate of the initial box, which is measured from them.
  for (const name of ['box_margin_nm', 'initial_z_nm']) field(name)?.addEventListener('input', scheduleExtent);
  // Auto is the extent route's own suggested z box, written into the field as a reader typing it would: the box
  // line, the preview's staleness, the summary and the gate then follow the same `input`/`change` events.
  pdcNode('.pdc-auto-z')?.addEventListener('click', async () => {
    if (!field('protein').value) {
      notice('Choose a protein: an empty micelle has no structure to measure a z box from.');
      return;
    }
    const button = pdcNode('.pdc-auto-z');
    if (button) button.disabled = true;
    try {
      await loadExtent();
      if (extentState.kind === 'answer' && Number.isFinite(extentState.autoZ)) {
        const input = field('initial_z_nm');
        if (!input) return;
        input.value = String(extentState.autoZ);
        input.dispatchEvent(new Event('input', {bubbles: true}));
        input.dispatchEvent(new Event('change', {bubbles: true}));
      } else if (extentState.kind === 'refused') {
        notice(extentState.reason);
      }
    } finally {
      syncAutoButton();
    }
  });
  pdcNode('.new-pdc-preview-derive')?.addEventListener('click', derivePreview);
  // The Ribbon control is a view of the frame on screen: it shows or hides the all-atom structure the beads were
  // coarse-grained from, as a layer under them. It sends nothing, is not in `previewInputs`, and leaves the state
  // line saying the frame on screen is the one this form asked for.
  pdcNode('.new-pdc-preview-ribbon input')?.addEventListener('change', () => { drawPreviewRibbon(); });
  // The count the placement measured, put into the count field exactly as a reader typing it would: the field's own
  // `input` listener re-derives the frame (and the estimate and the readiness gate with it), so this button queues
  // nothing and starts no run.
  pdcNode('.new-pdc-preview-use-capacity')?.addEventListener('click', event => {
    const count = Number(event.currentTarget.dataset.count);
    const input = field('aggregation_number');
    if (!Number.isFinite(count) || count < 1 || !input) return;
    input.value = String(count);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
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
    const sharing = event.submitter?.id === 'start-run-share' ? 'share' : 'queue';
    submitting = true;
    syncStartButtons();
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
      payload.remove_out_of_micelle = removeOutside();
      // Stated always, like the back-map choice: a run whose pdb2gmx was asked for aromatic virtual sites must not be
      // readable as one that used the default.
      payload.protein_vsite = proteinVsite();
      // Each leg's restraint window and the NPT barostat are stated always, like the back-map choice: a run that
      // asked for a window (the defaults hold minimisation and NPT) must not be readable as one that did not, and a
      // stated barostat must travel.
      for (const leg of RESTRAINT_LEGS) payload['pdc_posres_' + leg] = restrainProtein(leg);
      payload.pdc_npt_pcoupl = nptPcoupl();
      payload.pdc_npt_pcoupltype = nptPcoupltype();
      // The plan's step 1, sent always: the adapter's default is off, and a run whose preparation was asked for must
      // not be readable as one that was not. A protein-free run cannot ask for it -- there is nothing to prepare --
      // so it is stated only where the run has a structure, exactly as the chain selection is.
      if (field('protein').value) payload.prepare_protein = preparing();
      // The style is a choice the adapter reads through its own placement-mode alias, so it travels under the
      // panel's spelling (`pdc_placement_mode`) exactly as the seed does.
      payload.pdc_placement_mode = placementMode();
      // `single` is the adapter's absent setting, so it adds no key at all -- not a null it would have to translate.
      // The build spec is `{runs,size,seed}` and the stored one is `{key,sha256}`, as `normalise_spec` reads them.
      const shape = shapeSpec();
      if (shape) payload.conformation_library = shape;
      for (const key of NUMBERS) {
        const value = field(key)?.value;
        if (value !== '' && value != null) payload[key] = Number(value);
      }
      if (field('mdrun_nb')?.value) payload.mdrun_nb = field('mdrun_nb').value;
      // Stated always, like the back-map choice: the update scheme a run asked for must not be readable as one that
      // took the profile's own, and `auto` is a choice rather than an absence.
      payload.mdrun_update = field('mdrun_update')?.value || 'auto';
      // Each launch button states its own choice, always: a run asked to share a device must not be readable as one
      // that asked to queue beside it.
      payload.gpu_sharing = sharing;
      await post('/', payload);
      notice('Run queued.');
      // A build from runs writes its library into the store, so the stored list is read again and the new library
      // is selectable without a reload. This is not awaited: the notice and the runs tab do not wait for it.
      loadShapeLibraries();
      selectTab(panelIds().runs);
      if (refreshJobs) await refreshJobs();
    } catch (error) {
      notice(error.message);
    } finally {
      submitting = false;
      checkReadiness();
    }
  });

  async function mount() {
    if (mounting) return mounting;
    $('#' + panelIds()['new-run']).setAttribute('aria-busy', 'true');
    $('#start-run').disabled = true;
    mounting = (async () => {
      const remembered = saved();
      // The legend the beads are decoded with, filled from `ngl-beads.js`'s family table at mount.
      renderBeadLegend(pdcNode('.new-pdc-preview .bead-legend'));
      await Promise.all([loadCatalogue(), loadDetergents()]);
      // One info button per setting the catalogue sent a sentence for, on the same contract as the engine's panel.
      // `attachHelpIcons` keeps one attachment per (form, name), so a re-read of the catalogue adds no duplicate.
      attachHelpIcons(form, catalogue?.help);
      // After the picks that decide what this build is: the device list is a host fact and a status line, not a
      // precondition for the form.
      gpuDevice.load();
      for (const input of [...form.elements].filter(el => el.name)) {
        if (input.value === '' && remembered[input.name] !== undefined && input.tagName !== 'SELECT') {
          input.value = remembered[input.name];
        }
      }
      fillDefaults();
      // The preset bar's list, and -- on a form no reader has used yet -- the run type's default preset. Nothing
      // outranks it here (this panel has no clone and no run-type select), but a stored form does: it holds the last
      // values this reader typed, so the default is applied only when there are none. It goes after `fillDefaults`
      // because a preset states what the form should open with, and it outranks the catalogue's own numbers.
      const presetAnswer = await loadPresets();
      if (!Object.keys(remembered).length) {
        const preset = presetById(presetAnswer?.default);
        if (preset) applyPreset(preset);
      }
      if (remembered.mdrun_nb && field('mdrun_nb')) field('mdrun_nb').value = remembered.mdrun_nb;
      // The select's stored value is restored explicitly for the same reason `mdrun_nb`'s is: the loop above keeps
      // only non-selects, and a remembered back-map choice must not be replaced by the default on the next load.
      if (remembered.protein_vsite && field('protein_vsite')) {
        field('protein_vsite').value = remembered.protein_vsite;
      }
      // The seed defaults to today's date: the adapter requires one and a build with no seed cannot be compared with
      // another. Cleared by hand it stays empty and the gate names it.
      const seedInput = field('pdc_seed');
      if (seedInput && seedInput.value === '') seedInput.value = String(todaySeed());
      syncChains();
      scheduleExtent();
      await loadMappings();
      // The shape card's two lists: the runs it can build from and the libraries already stored for this residue.
      // They are read after the catalogue, because the stored list is filtered by the template's own residue.
      syncShape();
      loadShapeRuns();
      loadShapeLibraries();
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

//: The workspace this form is: `dashboard.html` renders its fragment under this slug, and the URL is what tells the
//: core panel which form it is looking at.
registerNewRunExtension({workspace: 'protein-detergent', create: createPdcNewRun});
