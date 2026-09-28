import { $, cachedApi, post, setText, storage } from './shared.js';

export function createCompositions({ openBondedModel, openCompositionRun }) {
  const host = $('#compositions');
  const sugar = $('#composition-sugar'), recipe = $('#composition-tail-recipe');
  const carbon = $('#composition-carbon-count'), head = $('#composition-head-endpoint');
  const tail = $('#composition-tail-endpoint'), profile = $('#composition-linkage-profile');
  const name = $('#composition-display-name'), previewButton = $('#composition-preview');
  const saveButton = $('#composition-save'), openBonded = $('#composition-open-bonded'), startRun = $('#composition-start-run');
  let catalog = null, lastPreview = null, saved = null, generation = 0, mounted = false;
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

  function represent(key, pdb, sele, selected) {
    // One structure, three views: the file holds both fragments under SUG and TAI, so a selection is what
    // separates the panels. The linkage bead is a second representation, in the colour that marks a choice.
    const stage = stageFor(key);
    stage.removeAllComponents();
    const component = stage.loadFile(new Blob([pdb], {type: 'text/plain'}), {ext: 'pdb'});
    component.then(item => {
      item.addRepresentation('ball+stick', {sele, radiusScale: 1.55});
      if (selected.length) item.addRepresentation('ball+stick', {sele: selected.join(' or '), color: 0xdf203d, radiusScale: 1.55});
      item.autoView(sele);
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
    if (result.pdb) {
      represent('head', result.pdb, 'SUG', [geometry.link.head_bead]);
      represent('tail', result.pdb, 'TAI', [geometry.link.tail_bead]);
      represent('joined', result.pdb, '*', link);
    }
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
  function payload() {
    return {head_fragment_id: `builtin:martini-sugars-v2:${sugar.value}`, tail_recipe_id: recipe.value,
      carbon_count: Number(carbon.value), head_endpoint: {bead: head.value}, tail_endpoint: {bead: tail.value},
      linkage_profile_id: profile.value, display_name: name.value.trim() || undefined,
      source_sha256: selectedSugar()?.source_sha256};
  }
  function renderDiagnostics(result) {
    const target = $('#composition-diagnostics');
    if (!result) { target.textContent = 'Choose the fragments and preview the candidate.'; return; }
    target.innerHTML = `<strong>Structural checks: ${result.validation.structural.ok ? 'ready' : 'blocked'}</strong><p>${result.mapping.beads.length} beads · ${result.topology.bonds.length} bonded terms · identity ${result.identity.slice(0, 12)}</p>`;
    const dls = $('#composition-provenance-list').querySelectorAll('dd');
    [result.head.id, `${result.tail.recipe_id} · ${result.tail.carbon_count} carbons`, result.profile.name, 'candidate-unvalidated'].forEach((text, index) => setText(dls[index], text));
  }
  function updateActions() {
    const ready = !!lastPreview;
    saveButton.disabled = !ready || !!saved;
    openBonded.disabled = !saved; startRun.disabled = !saved;
  }
  async function load() {
    if (catalog) return;
    catalog = await cachedApi('/api/compositions/catalog', {maxAge: 60000});
    options(sugar, catalog.sugars); options(recipe, catalog.tail_recipes); options(profile, catalog.linkage_profiles);
    syncEndpoints();
  }
  async function preview() {
    const token = ++generation; saved = null; lastPreview = null; updateActions();
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
    try { saved = await post('/api/compositions', payload()); updateActions(); setText($('#composition-panel-status'), `Saved ${saved.name}.`); return saved; }
    catch (error) { setText($('#composition-panel-status'), error.message); throw error; }
  }
  sugar?.addEventListener('change', () => { lastPreview = null; saved = null; syncEndpoints(); updateActions(); });
  recipe?.addEventListener('change', () => { lastPreview = null; saved = null; updateActions(); });
  carbon?.addEventListener('input', () => { lastPreview = null; saved = null; updateActions(); });
  previewButton?.addEventListener('click', () => preview().catch(() => {}));
  saveButton?.addEventListener('click', () => save().catch(() => {}));
  openBonded?.addEventListener('click', () => saved && openBondedModel(saved));
  startRun?.addEventListener('click', () => saved && openCompositionRun(saved));
  return { mount: async () => { if (!mounted) { mounted = true; await load(); } }, preview, save };
}
