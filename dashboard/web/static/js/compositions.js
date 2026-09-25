import { $, cachedApi, post, setText, storage } from './shared.js';
import { mountBondedPlot } from './bonded-plot.js';

export function createCompositions({ openBondedModel, openCompositionRun }) {
  const host = $('#compositions');
  const sugar = $('#composition-sugar'), recipe = $('#composition-tail-recipe');
  const carbon = $('#composition-carbon-count'), head = $('#composition-head-endpoint');
  const tail = $('#composition-tail-endpoint'), profile = $('#composition-linkage-profile');
  const name = $('#composition-display-name'), previewButton = $('#composition-preview');
  const saveButton = $('#composition-save'), openBonded = $('#composition-open-bonded'), startRun = $('#composition-start-run');
  let catalog = null, lastPreview = null, saved = null, generation = 0, mounted = false;
  const plots = {};

  function plotFor(key) {
    // Created on first paint: this tab is hidden at load, and Plotly sizes itself to its element.
    if (!plots[key]) plots[key] = mountBondedPlot($('#composition-plot-' + key), {
      onBeadSelection: names => chooseEndpoint(key, names),
    });
    return plots[key];
  }

  function chooseEndpoint(which, names) {
    // Clicking a bead in either fragment panel picks the bead the linkage attaches to, which is what
    // the two endpoint dropdowns already mean -- so the choice is a click rather than a lookup.
    if (which === 'joined') return;
    const name = names[names.length - 1];
    const select = $(which === 'head' ? '#composition-head-endpoint' : '#composition-tail-endpoint');
    if (!name || !select || ![...select.options].some(option => option.value === name)) return;
    select.value = name;
    paint(lastPreview);
  }

  function paint(result) {
    const basis = $('#composition-geometry-basis');
    const geometry = result?.geometry;
    for (const key of ('head', 'tail', 'joined')) plotFor(key).render({});
    if (!geometry) { if (basis) basis.textContent = 'Preview geometry appears here.'; return; }
    const link = [geometry.link.head_bead, geometry.link.tail_bead];
    // The two linkage beads are painted red by the plotter's selection colour, in both panel and join.
    plotFor('head').render({beads: geometry.head.beads, edges: geometry.head.edges, selectedBeads: [geometry.link.head_bead]});
    plotFor('tail').render({beads: geometry.tail.beads, edges: geometry.tail.edges, selectedBeads: [geometry.link.tail_bead]});
    plotFor('joined').render({beads: geometry.joined.beads, edges: geometry.joined.edges, selectedBeads: link});
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
  function renderPlot(result) {
    paint(result);
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
      lastPreview = result; syncEndpoints(); renderPlot(result); renderDiagnostics(result); updateActions();
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
