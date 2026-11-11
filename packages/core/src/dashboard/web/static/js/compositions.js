import { $, api, cachedApi, post, setText, invalidateResource, panelIds } from './shared.js';
import { BEAD_RADIUS_PARAMETERS, applyBeadRadii } from './ngl-beads.js';

//: The AA molecule each published Martini 3 sugar entry is published for (`models/sugars/reference.py:PUBLISHED_FOR`).
//: It is a *default provenance link*, never a claim: the panel offers the folder only when the catalogue has it, the
//: reader can clear or change it, and a sugar no line here names simply starts with no link.
const SUGAR_MOLECULES = {LAC: 'Lactose', SUCR: 'Sucrose', TREH: 'Trehalose', GLC: 'Glucose'};

export function createCompositions({ openBondedModel, openCompositionRun }) {
  const host = $('#'+panelIds().combinations);
  const sugar = $('#composition-sugar'), recipe = $('#composition-tail-recipe');
  const carbon = $('#composition-carbon-count'), head = $('#composition-head-endpoint');
  const tail = $('#composition-tail-endpoint'), profile = $('#composition-linkage-profile');
  const name = $('#composition-molecule-name'), headMolecule = $('#composition-head-molecule');
  const previewButton = $('#composition-preview');
  const saveButton = $('#composition-save'), openBonded = $('#composition-open-bonded'), startRun = $('#composition-start-run');
  let catalog = null, molecules = [], savedModels = [];
  let lastPreview = null, saved = null, generation = 0, mounted = false;
  //: The selected saved model's parameterization: the history the GET route answers with, the rows as read, and the
  //: rows being edited. `termsView` null means the card is hidden (a preview has no persistence target).
  let termsView = null, termsOriginal = [], termsDraft = [], termsOverrides = [], termsSaving = false;
  // "Suggested until edited": the molecule name follows the recipe while the reader has not typed one, and the head
  // link follows the sugar until they choose one. `lastDefault` is what a name still equal to the suggestion may move.
  let nameEdited = false, lastDefault = '', linkEdited = false;
  const plots = {};

  function stageFor(key) {
    // Created on first paint: this tab is hidden at load, and a viewer sizes itself to its element.
    if (!plots[key]) {
      plots[key] = new NGL.Stage($('#composition-plot-' + key), {backgroundColor: 'white'});
      // This panel's test seam. NGL stages live in this closure, and a browser test has to be able to ask
      // what was mounted without reaching into the viewer.
      if (host) host.compositionStages = plots;
    }
    return plots[key];
  }

  // The beads are drawn at the radius their own size class has in the model, out of the one table and the one call
  // (`ngl-beads.js`), times this panel's own display scale: a preview is read at a glance, and the model's 2.6
  // Angstrom balls are hard to tell apart at panel scale. Measured on this vendored build (2026-10-14): `ball+stick`
  // resolves `radiusType: 'size'` (0.15 A) unless it is told otherwise, so before this call every bead here was
  // drawn at the same 1.125 A -- the stand-in element the file writes made no difference on screen at all, and the
  // classes had no proportions. The scale is the one knob that moves this panel's picture and it never touches the
  // table, which is what keeps a reading aid out of the model.
  const BEAD_RADIUS_SCALE = 3.75;

  // One colour per bead type, so a bead keeps its colour in every view. The map is explicit and the fallback is
  // a single neutral grey rather than a generated hue: a type nobody has given a colour yet is visibly generic
  // instead of looking deliberate.
  const BEAD_COLOURS = {
    C1: 0x4a5568, C2: 0x4a5568, C3: 0x4a5568, C4: 0x4a5568, C5: 0x4a5568,  // apolar carbon beads
    SP1: 0x2b6cb0, SP1r: 0x2b6cb0, SN6: 0x2f855a, SP4r: 0x805ad5, TC4: 0xb7791f,
  };
  const BEAD_COLOUR_FALLBACK = 0x718096;
  const LINKAGE_COLOUR = 0xdf203d;
  // The bond-only representation is deliberately colourless: it carries connectivity, not identity, and the beads
  // above it are the ones that say which type a bead is.
  const BOND_COLOUR = 0x555555;
  const beadColour = type => BEAD_COLOURS[String(type || '')] ?? BEAD_COLOUR_FALLBACK;

  function represent(key, pdb, beads, selected) {
    // One structure, three views: each panel is told which beads it owns, so what it draws is that list grouped
    // by type, and the fragment split needs no residue selection. The linkage beads are a second set of
    // representations, in the colour that marks a choice.
    const stage = stageFor(key);
    stage.removeAllComponents();
    // NGL invents bonds from interatomic distances unless the file tells it otherwise: `inferBonds` defaults to
    // `'all'`. This file carries the candidate's own bonded terms as CONECT records, and the guess runs *as well* --
    // the defect the Complexes panel was measured with (a placement frame the model bonds 60 ways, drawn 90), and
    // here it would add sticks the model does not bond on top of the linkage the reader is checking. Where the file
    // states its own bonds the guess is switched off; a file that carries no records keeps NGL's bonds rather than
    // being drawn as unconnected dots.
    const parameters = {ext: 'pdb'};
    if (/^CONECT/m.test(pdb)) parameters.inferBonds = 'none';
    const component = stage.loadFile(new Blob([pdb], {type: 'text/plain'}), parameters);
    // Beads are addressed by their position in the file, not by name. This NGL build parses a bare word as a
    // residue name, so a selection built from bead names matches nothing -- the representations then draw
    // nothing, and autoView(selection) asks for the centre and zoom of a selection it could not resolve, which
    // is the camera's own starting place. Three blank panels, with nothing thrown and nothing logged. The order
    // is read back out of the PDB text the viewer is handed, so the indices cannot drift from the structure NGL
    // loaded -- and every panel loads the whole file, so a panel-relative index would address another panel's
    // beads. `@0` is the first atom.
    const order = [...pdb.matchAll(/^HETATM.{6}(.{4})/gm)].map(match => match[1].trim());
    const at = bead => '@' + order.indexOf(bead);
    const groups = new Map();
    for (const bead of beads) {
      const colour = beadColour(bead.type);
      if (!groups.has(colour)) groups.set(colour, []);
      groups.get(colour).push(at(bead.name));
    }
    component.then(item => {
      // The radii go on the structure once, from the model's own size classes (`ngl-beads.js`), and every
      // representation below is told to read them (`radiusType: 'explicit'` inside `BEAD_RADIUS_PARAMETERS`): the
      // per-type representations are for colour, not for size, which is what a representation's single radius scale
      // cannot do. One bead's radius is its class', so two panels of the same candidate cannot disagree about it.
      applyBeadRadii(item.structure, {scale: BEAD_RADIUS_SCALE});
      for (const [colour, selection] of groups) {
        item.addRepresentation('ball+stick', {sele: selection.join(' or '), color: colour,
          ...BEAD_RADIUS_PARAMETERS});
      }
      if (selected.length) {
        item.addRepresentation('ball+stick', {sele: selected.map(at).join(' or '), color: LINKAGE_COLOUR,
          ...BEAD_RADIUS_PARAMETERS});
      }
      // NGL draws a stick only between two atoms inside one representation, so a scheme that gives each bead type
      // its own representation also cuts the bonds that cross between types: the sugar's ring beads A and B share
      // a colour and get a stick, while C -- alone in its colour -- keeps its two ring bonds in the file and is
      // drawn as an orphan. One bond-only representation over every bead the panel owns restores the connectivity
      // without touching the colouring, which is the part that is deliberate.
      item.addRepresentation('line', {sele: beads.map(bead => at(bead.name)).join(' or '), color: BOND_COLOUR});
      // Frame the structure, not a selection: this is the form that measurably moves the camera.
      item.autoView();
    });
    return component;
  }

  function paint(result) {
    const basis = $('#composition-geometry-basis');
    const geometry = result?.geometry;
    for (const key of ['head', 'tail', 'joined']) stageFor(key);
    if (!geometry) {
      // A result without geometry means this dashboard process predates the panel: say so instead of
      // leaving three empty rectangles, which is exactly how a server running old code looked.
      if (basis) basis.textContent = result
        ? 'This dashboard process returned no bead geometry. Restart it, then preview again.'
        : 'Preview geometry appears here.';
      return;
    }
    const link = [geometry.link.head_bead, geometry.link.tail_bead];
    if (!result.pdb) {
      // Geometry without a structure file means this dashboard process predates the viewer. Say so rather than
      // leaving three empty canvases: a process older than the panel is the failure mode this project has hit
      // before, and silence is what makes it expensive to diagnose.
      if (basis) basis.textContent = 'This dashboard process returned no structure file for the viewer. '
        + 'Restart the dashboard, then preview again.';
      return;
    }
    represent('head', result.pdb, geometry.head.beads, [geometry.link.head_bead]);
    represent('tail', result.pdb, geometry.tail.beads, [geometry.link.tail_bead]);
    represent('joined', result.pdb, geometry.joined.beads, link);
    if (basis) basis.textContent = geometry.basis;
  }
  const selectedSugar = () => catalog?.sugars.find(item => item.id === sugar.value);
  function options(select, values, label = x => x.name || x.id) {
    select.replaceChildren(...values.map(item => new Option(label(item), item.id)));
  }
  function syncEndpoints() {
    const item = selectedSugar();
    options(head, (item?.endpoints || []).map(id => ({id, name: id})));
    const chosenTail = (lastPreview?.tail?.beads || []).map(item => ({id: item.name, name: `${item.name} · C${item.carbon_range.join('–C')}`}));
    options(tail, chosenTail.length ? chosenTail : [{id: 'C01', name: 'C01'}]);
  }

  // The model's name and its head link -------------------------------------------------------------------------
  //
  // A composition is a named CG model now, so the name is part of the form: it defaults to the sugar residue and
  // carbon count (`GLC-C12`), and it follows the recipe until the reader types one. The link names the AA molecule
  // the head fragment came from; it is provenance, and it is what makes the derived parameterization's source
  // `recipe+reference` rather than `recipe-only`.
  function defaultName() {
    const count = Number(carbon?.value);
    return sugar?.value && Number.isFinite(count) && count > 0 ? `${sugar.value}-C${count}` : '';
  }
  function syncNameDefault() {
    const suggestion = defaultName();
    if (!suggestion) return;
    const follows = !nameEdited || !name.value.trim() || name.value.trim() === lastDefault;
    lastDefault = suggestion;
    if (follows) { name.value = suggestion; nameEdited = false; }
  }
  function defaultHead() {
    const wanted = SUGAR_MOLECULES[sugar?.value];
    return molecules.some(record => record.id === wanted) ? wanted : '';
  }
  function fillHeadMolecules() {
    const chosen = headMolecule.value;
    headMolecule.replaceChildren(new Option('No link (derived only)', ''));
    for (const record of molecules) {
      headMolecule.append(new Option(`${record.name || record.id} · molecules/${record.id}`, record.id));
    }
    const keep = chosen && molecules.some(record => record.id === chosen) ? chosen : defaultHead();
    headMolecule.value = keep;
  }
  function syncHeadDefault() {
    if (!linkEdited) headMolecule.value = defaultHead();
  }
  function payload() {
    const chosenName = name?.value.trim() || defaultName();
    return {head_fragment_id: `builtin:martini-sugars-v2:${sugar.value}`, tail_recipe_id: recipe.value,
      carbon_count: Number(carbon.value), head_endpoint: {bead: head.value}, tail_endpoint: {bead: tail.value},
      linkage_profile_id: profile.value, display_name: chosenName || undefined,
      molecule_name: chosenName || undefined, head_molecule_id: headMolecule?.value || undefined,
      source_sha256: selectedSugar()?.source_sha256};
  }
  function renderDiagnostics(result) {
    const target = $('#composition-diagnostics');
    if (!result) { target.textContent = 'Choose the fragments and preview the candidate.'; return; }
    // The card beside it states the *saved* model; a preview is reported here, against the model's own measurements.
    target.innerHTML = `<strong>Structural checks: ${result.validation.structural.ok ? 'ready' : 'blocked'}</strong><p>${result.mapping.beads.length} beads · ${result.topology.bonds.length} bonded terms · identity ${result.identity.slice(0, 12)}</p>`;
  }

  // The saved CG model: what Bond Interactions and New run will read -------------------------------------------
  function termSummary(terms) {
    const parts = Object.entries(terms || {}).filter(([, count]) => count).map(([kind, count]) => `${count} ${kind}`);
    return parts.join(' · ') || 'none recorded';
  }
  function modelFacts(model) {
    const parameterization = model?.parameterization;
    const topology = parameterization?.topology;
    return {
      id: model?.molecule_id || model?.id || '—',
      name: model?.molecule_name || model?.name || '—',
      head: model?.head_molecule_id || 'No link (derived only)',
      beads: topology?.beads == null ? '—' : `${topology.beads} beads`,
      terms: topology?.terms ? termSummary(topology.terms) : '—',
      parameterization: parameterization
        ? `${parameterization.base || (parameterization.revision ? 'edited' : 'derived')} · `
          + `revision ${parameterization.revision ?? 0} · ${parameterization.source}` : 'no parameterization',
      status: model?.status || 'candidate-unvalidated',
    };
  }
  function renderSaved() {
    const list = $('#composition-provenance-list');
    const facts = modelFacts(saved);
    list.replaceChildren();
    for (const [label, value] of [['Molecule id', facts.id], ['Molecule name', facts.name],
                                  ['Links to', facts.head], ['Beads', facts.beads], ['Terms', facts.terms],
                                  ['Parameterization', facts.parameterization], ['Status', facts.status]]) {
      const dt = document.createElement('dt'); dt.textContent = label;
      const dd = document.createElement('dd'); dd.textContent = value;
      list.append(dt, dd);
    }
    setText($('#composition-model-summary'),
      saved ? `${facts.name} · derived CG model` : 'Preview and save to derive a CG model from this recipe.');
  }
  function renderSavedModels() {
    const body = $('#composition-model-rows');
    body.replaceChildren();
    for (const model of savedModels) {
      const facts = modelFacts(model);
      const row = document.createElement('tr');
      for (const value of [facts.name, facts.head, facts.beads, facts.terms, facts.status]) {
        const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
      }
      const actions = document.createElement('td');
      const open = document.createElement('button');
      open.type = 'button'; open.textContent = 'Open the CG run';
      open.disabled = !model.parameterization;
      open.addEventListener('click', () => openCompositionRun(model));
      // The second door: the same catalog row, opened in the terms card below. A composition is saved before its
      // terms can be edited (a preview has nowhere to persist them), so this is the model's own row that selects it.
      const edit = document.createElement('button');
      edit.type = 'button'; edit.className = 'secondary'; edit.textContent = 'Edit terms';
      edit.disabled = !model.parameterization;
      edit.addEventListener('click', () => openTerms(model).catch(error => setText($('#composition-panel-status'), error.message)));
      actions.append(open, document.createTextNode(' '), edit); row.append(actions);
      body.append(row);
    }
    setText($('#composition-models-status'),
      savedModels.length ? '' : 'No compositions saved in this workspace yet.');
  }
  async function loadSavedModels() {
    try {
      const answer = await cachedApi('/api/cg-models?view=summary', {maxAge: 60000});
      savedModels = (answer.models || []).filter(model => model.kind === 'composition');
    } catch (error) {
      savedModels = [];
    }
    renderSavedModels();
  }

  // The bonded terms of the selected saved model -------------------------------------------------------------
  //
  // A saved composition's parameterization is revision 0 (the derived model) plus the revisions a reader saved. The
  // table edits the flexible terms only: constraints and virtual sites are model terms and are shown read-only. Every
  // save appends a revision through `POST /api/compositions/<id>/parameterizations`; the ranges and the function
  // choices come from that route, so this file restates none of the numbers.
  const cloneRow = row => ({...row, beads: [...row.beads],
    parent_beads: row.parent_beads ? [...row.parent_beads] : undefined,
    function_options: row.function_options || [], parameter_labels: row.parameter_labels || [],
    parameters: (row.parameters || []).map(value => Number(value))});
  const boundsFor = (kind, func) => termsView?.ranges?.[kind]?.[String(func)] || [];
  const originalRow = row => termsOriginal.find(item => item.id === row.id);

  function rowChanged(row) {
    const original = originalRow(row);
    if (!original) return true;
    if (String(original.function) !== String(row.function)) return true;
    if ((original.parameters || []).length !== row.parameters.length) return true;
    return row.parameters.some((value, index) => Number(value) !== Number(original.parameters[index]));
  }

  function termRow(row) {
    const tr = document.createElement('tr');
    const kind = document.createElement('td');
    kind.textContent = row.kind.startsWith('virtual') ? 'virtual site' : row.kind;
    const beads = document.createElement('td');
    beads.textContent = row.beads.join(' – ')
      + (row.parent_beads?.length ? ` (of ${row.parent_beads.join(', ')})` : '');
    const fn = document.createElement('td');
    // The function form is a reading here, as in Bond Interactions: an edit changes values, never the potential.
    const fnPill = document.createElement('span'); fnPill.className = 'pill';
    fnPill.textContent = row.kind.startsWith('virtual') ? 'centre of geometry' : `function ${row.function}`;
    fn.append(fnPill);
    const parameters = document.createElement('td');
    if (row.editable) {
      const bounds = boundsFor(row.kind, row.function);
      const labels = row.parameter_labels?.length ? row.parameter_labels : bounds.map(bound => bound.label);
      const wrap = document.createElement('div'); wrap.className = 'composition-term-inputs';
      labels.forEach((label, index) => {
        const bound = bounds[index] || {min: undefined, max: undefined, integer: false, label: `parameter ${index + 1}`};
        const input = document.createElement('input');
        input.type = 'number'; input.step = bound.integer ? '1' : 'any';
        if (Number.isFinite(bound.min)) input.min = String(bound.min);
        if (Number.isFinite(bound.max)) input.max = String(bound.max);
        input.value = row.parameters[index] === undefined || Number.isNaN(row.parameters[index])
          ? '' : String(row.parameters[index]);
        input.setAttribute('aria-label', `${row.beads.join('–')} ${bound.label}`);
        input.title = `${bound.label} · ${bound.min}–${bound.max}${bound.integer ? ' · integer' : ''}`;
        input.addEventListener('input', () => {
          row.parameters[index] = input.value === '' ? NaN : Number(input.value);
          const original = originalRow(row);
          const changed = !original || Number(original.parameters[index]) !== Number(row.parameters[index]);
          input.dataset.dirty = String(changed);
          input.setCustomValidity(input.validity.badInput || input.validity.rangeUnderflow || input.validity.rangeOverflow
            ? `${bound.label} must be between ${bound.min} and ${bound.max}${bound.integer ? ' (an integer)' : ''}`
            : '');
          updateTermActions();
        });
        wrap.append(input);
      });
      parameters.append(wrap);
    } else {
      const text = row.kind.startsWith('virtual') ? 'centre of geometry' : (row.parameters || []).join(' ');
      parameters.textContent = text; parameters.className = 'hint';
    }
    const source = document.createElement('td');
    const pill = document.createElement('span'); pill.className = 'pill'; pill.textContent = row.source;
    source.append(pill);
    tr.append(kind, beads, fn, parameters, source);
    return tr;
  }

  function renderTermRows() {
    const body = $('#composition-term-rows');
    if (!body) return;
    body.replaceChildren(...termsDraft.map(termRow));
    updateTermActions();
  }

  function updateTermActions() {
    const button = $('#composition-save-terms');
    if (!button) return;
    const inputs = [...document.querySelectorAll('#composition-term-rows input')];
    const invalid = inputs.some(input => input.value === '' || !input.validity.valid);
    const dirty = termsDraft.some(rowChanged);
    button.disabled = !termsView || termsSaving || invalid || !dirty;
    button.title = !termsView ? 'Select a saved CG molecule first.'
      : termsSaving ? 'Saving…'
      : invalid ? 'Fix the highlighted values first.'
      : !dirty ? 'No unsaved edits.'
      : 'Write these terms as the next revision and make it current.';
  }

  function renderTerms() {
    const card = $('#composition-terms');
    if (!card) return;
    if (!termsView || !saved) { card.hidden = true; return; }
    card.hidden = false;
    const shown = termsView.current_parameterization || {};
    const revision = shown.revision ?? 0;
    const facts = modelFacts(saved);
    setText($('#composition-terms-badge'), `${shown.base || (revision ? 'edited' : 'derived')} · revision ${revision}`);
    setText($('#composition-terms-summary'),
      revision ? `${facts.name} · ${shown.beads ?? '—'} beads · revision ${revision} was saved by hand; revision 0 is `
                 + 'the derived model'
               : `${facts.name} · ${shown.beads ?? '—'} beads · the derived model`);
    setText($('#composition-terms-note'),
      'Save in place appends the next revision and makes it current: the next CG run consumes it. Constraints and '
      + 'virtual sites are model terms and cannot be edited. A run records the revision it consumed.');
    renderTermRows();
    setText($('#composition-terms-status'), '');
  }

  function clearTerms() {
    termsView = null; termsOriginal = []; termsDraft = []; termsOverrides = []; termsSaving = false;
    const card = $('#composition-terms');
    if (card) card.hidden = true;
    const body = $('#composition-term-rows');
    if (body) body.replaceChildren();
    setText($('#composition-terms-status'), '');
  }

  async function loadTerms(detail) {
    const compositionId = detail?.molecule_id || detail?.id;
    if (!compositionId) return null;
    termsView = await api('/api/compositions/' + encodeURIComponent(compositionId) + '/parameterizations');
    termsOriginal = (termsView.terms || []).map(cloneRow);
    termsDraft = termsOriginal.map(cloneRow);
    // A revision's overrides apply to the derived base, not to the previous revision, so each save must post the
    // complete set: the ones already current plus the rows just changed. Posting only the dirty rows would silently
    // return every earlier override to its derived value.
    const current = (termsView.revisions || []).find(item => item.revision === termsView.current) || null;
    termsOverrides = (current?.overrides || []).map(item => ({
      section: item.section, beads: [...item.beads], function: Number(item.function),
      parameters: (item.parameters || []).map(Number)}));
    renderTerms();
    return termsView;
  }

  async function openTerms(model) {
    const compositionId = model?.molecule_id || model?.id;
    if (!compositionId) return null;
    setText($('#composition-panel-status'), 'Reading the bonded terms…');
    const detail = await api('/api/cg-models/composition/' + encodeURIComponent(compositionId));
    saved = detail; renderSaved(); updateActions();
    await loadTerms(detail);
    setText($('#composition-panel-status'),
      `Editing ${modelFacts(detail).name}: Save in place writes a new revision.`);
    return detail;
  }

  async function saveTerms() {
    if (!termsView || termsSaving) return null;
    const overrideKey = item => `${item.section}|${[...item.beads].join('|')}`;
    const merged = new Map(termsOverrides.map(item => [overrideKey(item), item]));
    for (const row of termsDraft.filter(row => row.editable && rowChanged(row))) {
      const item = {section: row.kind, beads: [...row.beads], function: Number(row.function),
                    parameters: row.parameters.map(Number)};
      merged.set(overrideKey(item), item);
    }
    const overrides = [...merged.values()];
    if (!termsDraft.some(rowChanged)) { updateTermActions(); return null; }
    termsSaving = true; updateTermActions();
    setText($('#composition-terms-status'), 'Saving the terms as a new revision…');
    try {
      const item = await post('/api/compositions/' + encodeURIComponent(termsView.composition_id)
        + '/parameterizations', {expected_revision: termsView.current, overrides});
      invalidateResource('/api/cg-models');
      saved = await api('/api/cg-models/composition/' + encodeURIComponent(termsView.composition_id));
      renderSaved(); updateActions();
      await loadTerms(saved);
      setText($('#composition-terms-status'),
        `Saved as revision ${item.revision}: the next CG run consumes it.`);
      invalidateResource('/api/molecules');
      await loadSavedModels();
      return item;
    } catch (error) {
      if (error.status === 409) {
        await loadTerms(saved);
        setText($('#composition-terms-status'),
          'This model changed since it was read; the current revision was reloaded and nothing was saved.');
      } else {
        setText($('#composition-terms-status'), error.message);
      }
      return null;
    } finally {
      termsSaving = false;
      updateTermActions();
    }
  }

  function updateActions() {
    const ready = !!lastPreview;
    // The preview needs the catalogue's own values, and until it arrives the selects are empty. A payload built
    // from an empty select asks the server for the fragment named '' and gets back a message about fragment ids,
    // which gives no hint that the real problem was a click that arrived a moment too early.
    previewButton.disabled = !catalog || !sugar?.value || !recipe?.value;
    saveButton.disabled = !ready || !!saved;
    openBonded.disabled = !saved; startRun.disabled = !saved;
  }
  async function load() {
    if (catalog) return;
    const [catalogAnswer, moleculeAnswer] = await Promise.all([
      cachedApi('/api/compositions/catalog', {maxAge: 60000}),
      cachedApi('/api/molecules', {maxAge: 60000}).catch(() => ({molecules: []})),
    ]);
    catalog = catalogAnswer;
    // A CG molecule is a pdc detergent; the atomistic folders are the AA sources a head can link to.
    molecules = (moleculeAnswer.molecules || []).filter(record => record.kind !== 'cg' && record.valid !== false);
    options(sugar, catalog.sugars); options(recipe, catalog.tail_recipes); options(profile, catalog.linkage_profiles);
    fillHeadMolecules(); syncEndpoints(); syncNameDefault();
    updateActions();
    await loadSavedModels();
  }
  async function preview() {
    if (!catalog || !sugar?.value) {
      setText($('#composition-panel-status'), 'Waiting for the fragment catalogue; try again in a moment.');
      return null;
    }
    const token = ++generation; saved = null; lastPreview = null; clearTerms(); updateActions(); renderSaved();
    setText($('#composition-panel-status'), 'Building deterministic preview…');
    try {
      const result = await post('/api/compositions/preview', payload());
      if (token !== generation) return result;
      lastPreview = result; syncEndpoints(); paint(result); renderDiagnostics(result); updateActions();
      setText($('#composition-panel-status'), 'Preview ready. Review provenance before saving.'); return result;
    } catch (error) { setText($('#composition-panel-status'), error.message); renderDiagnostics(null); throw error; }
  }
  async function save() {
    if (!lastPreview) return null;
    setText($('#composition-panel-status'), 'Saving immutable composition…');
    try {
      const created = await post('/api/compositions', payload());
      // The row the catalog lists is the record plus its derived parameterization, which the create route does not
      // repeat; reading it back is what the panel shows, not a second guess at beads and terms.
      try { saved = await api('/api/cg-models/composition/' + encodeURIComponent(created.id)); }
      catch (error) { saved = created; }
      renderSaved();
      invalidateResource('/api/cg-models'); invalidateResource('/api/molecules');
      updateActions();
      await loadSavedModels();
      // The new composition's derived model is revision 0: the terms card opens on it so a reader can edit its
      // flexible terms straight away, and Save in place writes revision 1.
      await loadTerms(saved);
      setText($('#composition-panel-status'), `Saved ${modelFacts(saved).name} as a candidate-unvalidated CG molecule.`);
      return saved;
    } catch (error) { setText($('#composition-panel-status'), error.message); throw error; }
  }
  function clearResult() {
    lastPreview = null; saved = null; updateActions();
    renderSaved(); clearTerms();
  }
  sugar?.addEventListener('change', () => {
    clearResult(); syncEndpoints(); syncNameDefault(); syncHeadDefault(); updateActions();
  });
  recipe?.addEventListener('change', () => { clearResult(); updateActions(); });
  carbon?.addEventListener('input', () => { clearResult(); syncNameDefault(); updateActions(); });
  // The endpoint and linkage-profile choices are part of the recipe too: a changed one makes the preview (and the
  // saved model it produced) stale, exactly as a changed sugar or carbon count does. Without this the recipe form
  // kept `saved` set and looked stuck until the reader previewed again.
  head?.addEventListener('change', () => { clearResult(); updateActions(); });
  tail?.addEventListener('change', () => { clearResult(); updateActions(); });
  profile?.addEventListener('change', () => { clearResult(); updateActions(); });
  name?.addEventListener('input', () => { nameEdited = true; });
  headMolecule?.addEventListener('change', () => { linkEdited = true; });
  previewButton?.addEventListener('click', () => preview().catch(() => {}));
  saveButton?.addEventListener('click', () => save().catch(() => {}));
  $('#composition-save-terms')?.addEventListener('click', () => saveTerms());
  openBonded?.addEventListener('click', () => saved && openBondedModel(saved));
  startRun?.addEventListener('click', () => saved && openCompositionRun(saved));
  return { mount: async () => { if (!mounted) { mounted = true; await load(); } }, preview, save };
}
