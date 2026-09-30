import { $, cachedApi } from './shared.js';

export function createPdc() {
  const template = $('#pdc-template'), protein = $('#pdc-protein');
  const status = $('#pdc-panel-status'), limitation = $('#pdc-template-limitation');
  const viewer = $('#pdc-viewer'), viewerBasis = $('#pdc-view-basis');
  const strip = $('#pdc-snapshots'), stripBasis = $('#pdc-snapshot-basis');
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

  async function showPdb(text, describe) {
    const stageRef = stage();
    if (!stageRef) return;
    stageRef.removeAllComponents();
    const component = stageRef.loadFile(new Blob([text], {type: 'text/plain'}), {ext: 'pdb'});
    component.then(item => {
      item.addRepresentation('ball+stick', {radiusScale: 0.75, aspectRatio: 2});
      item.autoView();
      if (describe && viewerBasis) viewerBasis.textContent = describe(item);
    });
  }

  function describeSnapshot(snapshot) {
    // The picture and its numbers are one record: a reader should never have to guess which verdict a frame belongs
    // to, and a frame without a verdict (the placement) says so instead of showing a blank.
    const moment = snapshot.time_ps === null || snapshot.time_ps === undefined
      ? 'before dynamics' : `${Math.round(snapshot.time_ps)} ps`;
    const verdict = snapshot.verdict;
    if (!verdict) return `${snapshot.name} · ${moment} · ${snapshot.atoms} beads · not judged`;
    const answer = verdict.verdict ? 'micelle formed' : 'micelle not formed';
    return `${snapshot.name} · ${moment} · ${answer}: largest cluster ${verdict.largest_cluster} of `
      + `${verdict.aggregation_number} (${Math.round(100 * (verdict.fraction_of_requested || 0))}%), `
      + `${verdict.protein_contact_count} touching the protein`;
  }

  async function showSnapshot(button, snapshot) {
    const response = await fetch(`/api/pdc/${currentRun.id}/snapshots/${snapshot.stage}/${snapshot.pdb}`);
    if (!response.ok) { if (stripBasis) stripBasis.textContent = 'That snapshot is no longer on disk.'; return; }
    strip?.querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    if (stripBasis) stripBasis.textContent = describeSnapshot(snapshot);
    await showPdb(await response.text(), null);
  }

  async function loadSnapshots() {
    // The series is what makes a run readable: the placement, each phase's end state, and the frames between. It is
    // served from the stages that took the pictures, so a resumed run shows what it re-derived.
    if (!strip) return;
    if (!currentRun) { strip.replaceChildren(); if (stripBasis) stripBasis.textContent = 'Snapshots appear here as a run records them.'; return; }
    const response = await fetch(`/api/pdc/${currentRun.id}/snapshots`);
    const payload = response.ok ? await response.json() : {snapshots: []};
    const snapshots = payload.snapshots || [];
    if (!snapshots.length) {
      strip.replaceChildren();
      if (stripBasis) stripBasis.textContent = 'This run has recorded no snapshots yet.';
      return;
    }
    strip.replaceChildren(...snapshots.map(snapshot => {
      // Long phases read better in ns; a short frame keeps its ps, because that is the resolution it was taken at.
      const moment = snapshot.time_ps === null || snapshot.time_ps === undefined ? null : Number(snapshot.time_ps);
      const label = moment === null ? snapshot.name
        : (moment >= 1000 ? `${Math.round(moment / 1000)} ns` : `${Math.round(moment)} ps`);
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.title = describeSnapshot(snapshot);
      button.setAttribute('aria-pressed', 'false');
      button.addEventListener('click', () => showSnapshot(button, snapshot));
      return button;
    }));
    if (stripBasis) stripBasis.textContent = `${snapshots.length} snapshots recorded. Pick one to see it.`;
  }

  async function loadSystem() {
    // The viewer shows the system a stage actually wrote. Until one exists the route says so, and the panel repeats
    // it rather than drawing an empty box.
    if (!viewer) return;
    const run = currentRun?.id;
    if (!run) { if (viewerBasis) viewerBasis.textContent = 'The built system appears here once a build has run.'; return; }
    const response = await fetch(`/api/pdc/${run}/system.pdb`);
    if (!response.ok) { if (viewerBasis) viewerBasis.textContent = 'No built system to show yet.'; return; }
    await showPdb(await response.text(), item => `Showing ${item.structure.atomCount} beads from the built system; `
      + 'water and ions are omitted.');
  }

  return { mount: async () => { await load(); return $('#pdc'); }, loadSystem, loadSnapshots,
           // The build flow will call this when a stage has produced a system; a test calls it to exercise the
           // viewer and the series without waiting for a run.
           setRun: (id) => { currentRun = id ? {id} : null; return Promise.all([loadSnapshots(), loadSystem()]); } };
}
