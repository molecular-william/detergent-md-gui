import { $, cachedApi } from './shared.js';

export function createPdc() {
  const template = $('#pdc-template'), protein = $('#pdc-protein');
  const status = $('#pdc-panel-status'), limitation = $('#pdc-template-limitation');
  const viewer = $('#pdc-viewer'), viewerBasis = $('#pdc-view-basis');
  let catalog = null, currentRun = null;

  function fill(select, values, label) {
    select.replaceChildren(...values.map(item => new Option(label(item), item.id)));
  }

  function describe() {
    // The catalogue reports what a template *is*, not only its name: the shipped one is a skeleton, and a panel
    // that hid that would be offering a fitted detergent model the repository does not have.
    const chosen = (catalog?.templates || []).find(item => item.id === template.value);
    if (limitation) limitation.textContent = chosen ? chosen.limitations.join(' · ') : '';
    if (status) status.textContent = chosen && !chosen.files_present
      ? 'This template names files the repository does not have; a build would stop at validation rather than later.'
      : 'Setup only: this panel lists what can be built; the pipeline stages follow.';
  }

  async function load() {
    if (catalog) return;
    catalog = await cachedApi('/api/pdc/catalog', {maxAge: 60000});
    fill(template, catalog.templates, item => `${item.name} · ${item.registered_type || 'unregistered'}`);
    // An empty micelle is in scope, so the protein list leads with the absence of one.
    fill(protein, [{id: '', name: 'No protein (empty micelle)'}, ...catalog.proteins], item => item.name);
    describe();
  }

  template?.addEventListener('change', describe);
  template?.addEventListener('change', loadSystem);
  protein?.addEventListener('change', loadSystem);

  function stage() {
    // Created on first use: NGL sizes itself to its host element, and the host is sized for it in pdc.css.
    if (!viewer) return null;
    if (!viewer.pdcStage) viewer.pdcStage = new NGL.Stage(viewer, {backgroundColor: 'white'});
    return viewer.pdcStage;
  }

  async function loadSystem() {
    // The viewer shows the system a stage actually wrote. Until one exists the route says so, and the panel repeats
    // it rather than drawing an empty box.
    if (!viewer) return;
    const run = currentRun?.id;
    if (!run) { if (viewerBasis) viewerBasis.textContent = 'The built system appears here once a build has run.'; return; }
    const response = await fetch(`/api/pdc/${run}/system.pdb`);
    if (!response.ok) { if (viewerBasis) viewerBasis.textContent = 'No built system to show yet.'; return; }
    const stageRef = stage();
    stageRef.removeAllComponents();
    const component = stageRef.loadFile(new Blob([await response.text()], {type: 'text/plain'}), {ext: 'pdb'});
    component.then(item => {
      item.addRepresentation('ball+stick', {radiusScale: 0.75, aspectRatio: 2});
      item.autoView();
      if (viewerBasis) viewerBasis.textContent = `Showing ${item.structure.atomCount} beads from the built system; water and ions are omitted.`;
    });
  }

  return { mount: async () => { await load(); return $('#pdc'); }, loadSystem,
           // The build flow will call this when a stage has produced a system; a test calls it to exercise the
           // viewer without waiting for a run.
           setRun: (id) => { currentRun = id ? {id} : null; return loadSystem(); } };
}
