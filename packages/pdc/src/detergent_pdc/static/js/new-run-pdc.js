import { $, storage, setText, notice, api, post, cachedApi, invalidateResource, guarded, DROP, panelIds } from '/static/js/shared.js';
import { createGpuDevice } from '/static/js/gpu-device.js';
import { BEAD_FAMILY_PARAMETERS, BEAD_RADIUS_PARAMETERS, SECONDARY_CLASS_COLOURS, SECONDARY_CLASS_ORDER,
         PROTEIN_BACKBONE, applyBeadRadii, renderBeadLegend, renderSecondaryLegend } from '/static/js/ngl-beads.js';
import { registerNewRunExtension, writeReadiness } from '/static/js/new-run.js';

// The protein-detergent feature's New run extension: the whole of the pdc workspace's form.
//
// `dashboard.html` renders this panel's markup from `templates/fragments/new-run-pdc.html`, only for the workspace
// whose pipeline it describes, and the module registers itself on `/static/js/new-run.js` as that workspace's panel.
// There is no AA reference, no method and no bonded fit to hide, because nothing rendered one. Every control it
// reads is a name `execution/adapters/pdc.py` accepts -- its `validate_payload` and `SETTING_SPECS` are the authority
// for the spelling, and a control whose value no stage consumes is a control that lies.
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
                   'nstlog', 'nstenergy', 'nstxtcout', 'xtc_precision', 'nstcomm',
                   'nstlist', 'verlet_buffer_tolerance', 'rlist', 'rcoulomb', 'rvdw',
                   'ref_t', 'tau_t', 'ref_p', 'tau_p', 'compressibility',
                   'mdrun_gpu', 'mdrun_ntomp', 'mdrun_ranks'];
  // The catalogue publishes the settings under the builders' names; the panel's controls carry the pipeline's.
  const DEFAULT_ALIASES = {assessment_ns: 'pdc_assessment_ns', extension_ns: 'pdc_extension_ns',
                           placement_mode: 'pdc_placement_mode'};
  // The device is the host's, not the build's: the select is filled from `/api/run/devices`, and a run that names
  // none sends nothing, so the adapter's default device stands. The note is a readiness fact, never a gate.
  const gpuSelect = field('mdrun_gpu');
  const gpuDevice = gpuSelect
    ? createGpuDevice({select: gpuSelect, note: pdcNode('.new-pdc-gpu-note'), saved: () => saved().mdrun_gpu})
    : {load: async () => {}, refresh: () => {}};
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
    // A check already scheduled by the debounced `input` is superseded by this one; letting it fire after this
    // request settles would disable the launch button again for no new information.
    clearTimeout(readinessTimer);
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
      writeReadiness(ready.checks, ready.blockers);
      setText($('#review-status'), ready.ready ? 'Inputs ready' : (ready.blockers?.length ? 'Action required' : 'Not ready'));
      $('#review-status').dataset.ready = String(!!ready.ready);
      setText($('#launch-blocker'), ready.ready ? '' : (ready.blockers?.[0] || 'Inputs are not ready.'));
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
  //: The line that says the ribbon could not be loaded. Its own element rather than `.new-pdc-preview-basis`, which
  //: carries what the placement measured: a failure of the second request is not a fact about the frame.
  function ribbonNote(text) {
    const note = previewNode('.new-pdc-preview-ribbon-note');
    if (!note) return;
    setText(note, text || '');
    note.hidden = !text;
  }
  let previewFrame = null, previewRequest = 0, previewTimer, previewDraw = 0;
  // The stage lives on the host element, the way `pdc.js` keeps its own (`viewer.pdcStage`): one owner, and a test
  // or a console can reach the thing that is drawn without a hook this module would have to publish.
  const previewStage = () => previewNode('.new-pdc-preview-viewer')?.previewStage || null;

  // The two view switches are about the protein. With an empty micelle there is no protein representation to make
  // licorice and no all-atom structure to draw under the beads, so both are disabled with a reason rather than
  // left clickable and silently doing nothing. The ribbon's previous state is kept while it is unavailable, so
  // choosing a protein again restores the reader's choice instead of resetting it.
  function syncPreviewControls() {
    const hasProtein = !!field('protein').value;
    const bonds = previewNode('.new-pdc-preview-bonds input');
    const ribbon = previewNode('.new-pdc-preview-ribbon input');
    for (const [input, why] of [[bonds, 'an empty micelle has no protein'], [ribbon, 'an empty micelle has no all-atom protein ribbon']]) {
      if (!input) continue;
      const label = input.closest('label');
      if (hasProtein) {
        input.disabled = false;
        if (label) label.title = input === bonds
          ? "Draw the protein as licorice sticks so the model's own bonds are visible"
          : 'Draw the all-atom structure the beads were coarse-grained from, as a ribbon under the beads';
      } else {
        input.disabled = true;
        if (label) label.title = `Disabled · ${why}`;
      }
    }
    if (!ribbon) return;
    if (!hasProtein) {
      if (ribbon.dataset.savedChecked === undefined) ribbon.dataset.savedChecked = String(ribbon.checked);
      ribbon.checked = false;
    } else if (ribbon.dataset.savedChecked !== undefined) {
      ribbon.checked = ribbon.dataset.savedChecked !== 'false';
      delete ribbon.dataset.savedChecked;
    }
  }

  function previewInputs() {
    return {protein: field('protein').value || '', chains: selectedChains(),
            mapping: field('mapping_candidate').value || '', molecule: field('molecule_id').value || '',
            template: templatePath(), count: field('aggregation_number').value || '',
            mode: placementMode(), seed: field('pdc_seed').value || '',
            margin: field('box_margin_nm').value || '', initial_z: field('initial_z_nm').value || '',
            prepare: preparing()};
  }
  // What would be coarse-grained, or drawn from another mapping: a change to one of these is a different question,
  // and the frame on screen is no longer this form's. Everything the reader can still move without new
  // coarse-graining re-derives instead.
  const previewExpensive = inputs => `${inputs.protein}|${inputs.chains.join(',')}|${inputs.mapping}|${inputs.molecule}|${inputs.prepare}`;
  const previewCheap = inputs => [inputs.count, inputs.mode, inputs.seed, inputs.margin, inputs.initial_z,
                                  inputs.template].join('|');

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
    return query;
  }

  // The picture's own representations ----------------------------------------------------------------------------
  //
  // One frame, and three different things said about the beads in it:
  //
  // * the **detergent's** beads on their Martini 3 polarity family, which is the code the file carries in its b-factor
  //   column and the one thing a bead's size cannot say;
  // * the protein's **side chains** -- and any backbone bead the assignment leaves unstated -- on that same family,
  //   which for a protein bead is `family not stated` and stays that way: a side chain has no secondary structure of
  //   its own; and
  // * the protein's **backbone** beads on the secondary structure of the residue each belongs to, from the assignment
  //   the server put in `basis.secondary_structure` -- keyed by the residue number this very frame gives it, so no
  //   number is measured here.
  //
  // One representation per class, over NGL's own selections on those residue numbers, rather than a rewritten file:
  // the frame is the artifact the run records as its first snapshot, and its b-factor column already means the
  // family. A residue the assignment does not give one class to -- its frame number holds two residues of different
  // classes, or it is not in the payload at all -- is drawn with the protein's side chains in its family colour: a
  // backbone bead is never given a structure the server did not state for its own residue.
  //
  // The protein's representations are the ones the **Bonds** control switches: `ball+stick` at the card's own scale,
  // or `licorice`, which hides the ball and leaves a stick at a quarter of the bead's radius -- the shape the model's
  // own `CONECT` records need to be visible inside beads drawn at 0.3 of their size. The detergent's representation
  // is `ball+stick` either way.
  //
  // The selections name the backbone's atom name and the residue numbers the assignment carries, because that is what
  // this vendored NGL's grammar understands: measured in the page, `resname PRO` is a parse error and `:PRO` is read
  // as a chain, while `.BB` and bare `1-4` are the atom name and the residue range. Both are protein and nothing else
  // is: the numbers come from the assignment, which has one entry per protein residue, and `BB` is martinize2's
  // backbone bead (`ngl-beads.js` `PROTEIN_BACKBONE`).
  const PREVIEW_BACKBONE = `.${PROTEIN_BACKBONE}`;

  //: A list of residue numbers as one selection term, runs of them collapsed: `1-4 or 9`, which is the spelling this
  //: NGL build parses. A protein of 379 residues arrives as a hundred such runs, and the selection is a string.
  function residueSelection(numbers) {
    const sorted = [...new Set(numbers)].filter(Number.isFinite).sort((a, b) => a - b);
    const runs = [];
    for (const number of sorted) {
      const last = runs[runs.length - 1];
      if (last && number === last[1] + 1) last[1] = number; else runs.push([number, number]);
    }
    return runs.map(([first, last]) => (first === last ? `${first}` : `${first}-${last}`)).join(' or ');
  }

  //: The residue numbers the assignment gives each class, from the payload as it arrived. A `null` class -- the
  //: frame cannot tell two residues apart under one number -- is not in any of the three, and is drawn as family.
  function secondaryGroups(assignment) {
    const groups = {helix: [], sheet: [], coil: []};
    for (const [resno, name] of Object.entries(assignment?.classes || {})) {
      if (name in groups) groups[name].push(Number(resno));
    }
    return groups;
  }

  // The protein as the structure it was coarse-grained from ------------------------------------------------------
  //
  // The beads are a coarse-grained model *of* a structure, and the two are one picture here: the server names the
  // all-atom file martinize2 was handed in `basis.protein_structure` (its cache key and the URL that serves it, so
  // this file never builds a URL), and it is drawn as a ribbon **under** the beads. Both are in one frame --
  // martinize2 writes its beads in the coordinates it read -- so nothing is transformed to overlay them.
  //
  // The ribbon makes no claim of its own. One neutral grey that is neither a Martini family nor a DSSP class, so it
  // cannot be decoded as either: the colours in this picture are the *beads'*, and the card's sentence says so. It is
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
  //: A grey that is neither a family colour nor a class colour (`ngl-beads.js` carries both tables), so the ribbon
  //: under the beads cannot be decoded as either.
  const PREVIEW_RIBBON_COLOUR = '#adb5bd';
  //: Firm, not faint: the protein's beads are drawn translucent over this ribbon (`PREVIEW_PROTEIN_BEAD_OPACITY`),
  //: and a ribbon at a third opacity under them measured as a grey smear rather than the helices it is. It still
  //: writes no depth, so it cannot paint over a bead.
  const PREVIEW_RIBBON_OPACITY = 0.85;
  //: The protein's beads sit on the very atoms its ribbon runs through, so at full opacity they hide it completely
  //: (measured on 1at9: a 2933-atom cartoon invisible under 928 beads). While the ribbon is shown the protein's beads
  //: are drawn translucent, which is what makes the two layers one picture instead of two. The detergent's beads are
  //: not -- nothing of the ribbon is under them, and a washed-out micelle would say the detergent is uncertain.
  const PREVIEW_PROTEIN_BEAD_OPACITY = 0.5;

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
    // Read from the control at drawing time, exactly as Bonds reads its own: a view of the frame on screen, never an
    // input to it -- absent from `previewInputs`, sending nothing, leaving the state line alone.
    if (!previewNode('.new-pdc-preview-ribbon input')?.checked) return;
    const name = ribbonRepresentation();
    if (!name) return;
    ribbon.addRepresentation(name, {colorScheme: 'uniform', colorValue: PREVIEW_RIBBON_COLOUR,
                                    opacity: PREVIEW_RIBBON_OPACITY, depthWrite: false, side: 'front',
                                    useInteriorColor: false});
  }

  // The loaded frame's beads and the assignment they are coloured with, kept on the host element beside
  // `previewStage`: the Bonds control redraws the representations of the frame that is already here rather than
  // asking the server for it again, and this is the state that redraw needs.
  function drawPreviewRepresentations() {
    const host = previewNode('.new-pdc-preview-viewer'), component = host?.previewComponent;
    if (!component) return;
    for (const representation of [...component.reprList]) component.removeRepresentation(representation);
    // Read from the control at drawing time, so the two cannot drift: the control is a view of this frame, never an
    // input to it -- it is absent from `previewInputs`, sends nothing, and leaves the state line saying the frame on
    // screen is the one this form asked for.
    const bonds = !!previewNode('.new-pdc-preview-bonds input')?.checked;
    const protein = bonds ? 'licorice' : 'ball+stick';
    const beads = {...BEAD_RADIUS_PARAMETERS, ...BEAD_FAMILY_PARAMETERS};
    // The ribbon is drawn from the same all-atom structure these beads were coarse-grained from, so it lies *inside*
    // them: shown together, the protein's beads are translucent and the detergent's stay solid.
    const underRibbon = previewNode('.new-pdc-preview-ribbon input')?.checked
      ? {opacity: PREVIEW_PROTEIN_BEAD_OPACITY, depthWrite: false} : {};
    const assignment = host.previewSecondary;
    const groups = secondaryGroups(assignment);
    const coloured = [...groups.helix, ...groups.sheet, ...groups.coil];
    // Every residue number the assignment carries is a protein residue's -- a `null` class is a residue the frame
    // could not give one class to, not an absent one -- so its complement in the frame is the detergent's.
    const proteinResidues = Object.keys(assignment?.classes || {}).map(Number);
    if (!coloured.length || !proteinResidues.length) {
      // No assignment to draw: one representation of the whole frame, which is what this card drew before it had
      // one -- the beads on their families, and nothing claimed about a structure that was not stated.
      component.addRepresentation('ball+stick', {sele: '*', ...beads});
      return;
    }
    const residues = residueSelection(proteinResidues);
    // The detergent's own beads, always `ball+stick`: what a detergent is doing in this picture does not depend on
    // how a reader wants to read the protein's bonds.
    component.addRepresentation('ball+stick', {sele: `not (${residues})`, ...beads});
    // The protein's beads that are not a class' backbone: its side chains, and any residue the assignment does not
    // name. Built as the complement of the very selections below, so no bead is drawn twice and none is dropped.
    component.addRepresentation(protein, {
      sele: `(${residues}) and not (${PREVIEW_BACKBONE} and (${residueSelection(coloured)}))`,
      ...beads, ...underRibbon});
    for (const name of SECONDARY_CLASS_ORDER) {
      if (!groups[name].length) continue;
      component.addRepresentation(protein, {
        sele: `${PREVIEW_BACKBONE} and (${residueSelection(groups[name])})`,
        ...BEAD_RADIUS_PARAMETERS, ...underRibbon, colorScheme: 'uniform',
        colorValue: SECONDARY_CLASS_COLOURS[name],
      });
    }
  }

  function showPreviewFrame(pdb, assignment, structure) {
    const host = previewNode('.new-pdc-preview-viewer');
    if (!host || typeof NGL === 'undefined') return;
    // The stage is built the moment there is something to draw, and asked to resize on a tab show and a window
    // change: NGL sizes its drawing buffer when the stage is built and only recomputes it when asked, so a stage
    // built at one width keeps that buffer inside a host that later grows.
    if (!host.previewStage) host.previewStage = new NGL.Stage(host, {backgroundColor: 'white'});
    const stage = host.previewStage;
    stage.removeAllComponents();
    host.previewComponent = null;
    host.previewRibbon = null;
    host.previewSecondary = assignment || null;
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
        // Both of the module's answers go on the representations: the radius each bead's own size class gives it, and
        // the colour its type family -- or its residue's secondary structure -- gives it.
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

  // The secondary-structure sentence and its legend. The counts are the server's own -- `summary` is counted from
  // the letters it assigned -- and the protein's name is the one the basis named, so the card prints a record rather
  // than a measurement of its own. When the answer carries no assignment the card says so and names the reason the
  // server gave; when it carries one, the legend under the picture is the key to the backbone's three colours, and
  // both come from `ngl-beads.js`'s one table.
  function renderPreviewSecondary(basis) {
    const assignment = basis?.secondary_structure || null, legend = previewNode('.new-pdc-preview-secondary-legend');
    const note = previewNode('.new-pdc-preview-secondary');
    const groups = secondaryGroups(assignment);
    const coloured = groups.helix.length + groups.sheet.length + groups.coil.length;
    if (legend) legend.hidden = !coloured;
    if (!note) return;
    note.hidden = !assignment;
    if (!assignment) { setText(note, ''); return; }
    if (!coloured) {
      const reason = assignment.detail || 'the assignment could not be keyed to this frame';
      setText(note, `No secondary structure is drawn: ${reason}`);
      return;
    }
    const summary = assignment.summary || {};
    const counts = SECONDARY_CLASS_ORDER.map(name => `${Number(summary[name] || 0).toLocaleString()} ${name}`);
    setText(note, `${basis.protein || 'the protein'}: ${counts.join(', ')}`
      + ' — the protein\u2019s backbone beads, coloured by the residue each one belongs to');
  }

  function renderPreviewFrame(body) {
    const basis = body.basis || {}, cost = body.cost || {}, box = basis.box_nm || [];
    const viewer = previewNode('.new-pdc-preview-viewer'), refusal = previewNode('.new-pdc-preview-refusal');
    if (refusal) { refusal.hidden = true; refusal.textContent = ''; }
    if (viewer) viewer.hidden = false;
    showPreviewFrame(body.pdb || '', basis.secondary_structure, basis.protein_structure);
    renderPreviewSecondary(basis);
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
    const host = previewNode('.new-pdc-preview-viewer'), secondaryLegend = previewNode('.new-pdc-preview-secondary-legend');
    const secondaryNote = previewNode('.new-pdc-preview-secondary');
    if (host) { host.previewComponent = null; host.previewRibbon = null; host.previewSecondary = null; }
    ribbonNote('');
    if (viewer) viewer.hidden = true;
    // A refusal draws nothing, so it has no backbone to colour and no counts to print: both say nothing rather than
    // leaving the last frame's legend and numbers beside a sentence about a system that was not built.
    if (secondaryLegend) secondaryLegend.hidden = true;
    if (secondaryNote) { secondaryNote.hidden = true; setText(secondaryNote, ''); }
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
  field('remove_out_of_micelle')?.addEventListener('change', () => { store(); syncSummary(); checkReadiness(); });
  // The prepare step changes what martinize2 reads, so it is one of the expensive inputs: the frame on screen is no
  // longer this form's once it moves, and the card says so rather than quietly drawing the old one.
  pdcNode('.new-pdc-import-button')?.addEventListener('click', importStructure);
  // The preview's own cheap inputs: each of these re-derives a frame that already exists, and the exchange rate is
  // the cache -- the coarse-grained protein is not rebuilt -- which is why these move and the three expensive ones
  // only mark the frame stale.
  field('aggregation_number').addEventListener('input', previewMoved);
  for (const name of ['pdc_seed', 'box_margin_nm', 'initial_z_nm']) field(name)?.addEventListener('input', previewMoved);
  pdcNode('.new-pdc-preview-derive')?.addEventListener('click', derivePreview);
  // The Bonds control is a view of the frame on screen and nothing else: it redraws the protein's own
  // representations in `licorice` so the model's CONECT records read as sticks, leaves the detergent's as they were,
  // and -- because it is not in `previewInputs` and sends no request -- cannot be mistaken for a different placement.
  pdcNode('.new-pdc-preview-bonds input')?.addEventListener('change', () => { drawPreviewRepresentations(); });
  // The Ribbon control beside it is the same kind of thing: it shows or hides the all-atom structure the beads were
  // coarse-grained from, as a layer under them. It sends nothing, is not in `previewInputs`, and leaves the state
  // line saying the frame on screen is the one this form asked for.
  pdcNode('.new-pdc-preview-ribbon input')?.addEventListener('change', () => {
    // The beads' opacity is read off this same control (`drawPreviewRepresentations`), so hiding the ribbon has to
    // redraw them too -- otherwise the protein's beads would stay translucent over nothing.
    drawPreviewRibbon();
    drawPreviewRepresentations();
  });
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
      payload.remove_out_of_micelle = removeOutside();
      // The plan's step 1, sent always: the adapter's default is off, and a run whose preparation was asked for must
      // not be readable as one that was not. A protein-free run cannot ask for it -- there is nothing to prepare --
      // so it is stated only where the run has a structure, exactly as the chain selection is.
      if (field('protein').value) payload.prepare_protein = preparing();
      // The style is a choice the adapter reads through its own placement-mode alias, so it travels under the
      // panel's spelling (`pdc_placement_mode`) exactly as the seed does.
      payload.pdc_placement_mode = placementMode();
      for (const key of NUMBERS) {
        const value = field(key)?.value;
        if (value !== '' && value != null) payload[key] = Number(value);
      }
      if (field('mdrun_nb')?.value) payload.mdrun_nb = field('mdrun_nb').value;
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
      // The legend the beads are decoded with, filled from `ngl-beads.js`'s one family table at mount -- and beside
      // it the secondary structure's, from that module's other table. Neither is drawn until the frame answers with
      // something to decode, which is why the second one starts hidden.
      renderBeadLegend(pdcNode('.new-pdc-preview .bead-legend'));
      renderSecondaryLegend(pdcNode('.new-pdc-preview .new-pdc-preview-secondary-legend'));
      await Promise.all([loadCatalogue(), loadDetergents()]);
      // After the picks that decide what this build is: the device list is a host fact and a status line, not a
      // precondition for the form.
      gpuDevice.load();
      for (const input of [...form.elements].filter(el => el.name)) {
        if (input.value === '' && remembered[input.name] !== undefined && input.tagName !== 'SELECT') {
          input.value = remembered[input.name];
        }
      }
      fillDefaults();
      if (remembered.mdrun_nb && field('mdrun_nb')) field('mdrun_nb').value = remembered.mdrun_nb;
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

//: The workspace this form is: `dashboard.html` renders its fragment under this slug, and the URL is what tells the
//: core panel which form it is looking at.
registerNewRunExtension({workspace: 'protein-detergent', create: createPdcNewRun});
