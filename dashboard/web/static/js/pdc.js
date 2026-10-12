import { $, cachedApi, invalidateResource, panelIds } from './shared.js';

export function createPdc() {
  const template = $('#pdc-template'), protein = $('#pdc-protein');
  const status = $('#pdc-panel-status'), limitation = $('#pdc-template-limitation');
  const viewer = $('#pdc-viewer'), viewerBasis = $('#pdc-view-basis');
  const strip = $('#pdc-snapshots'), stripBasis = $('#pdc-snapshot-basis');
  const runSelect = $('#pdc-run');
  const mapping = $('#pdc-mapping'), queue = $('#pdc-queue');
  const importField = $('#pdc-protein-id'), importButton = $('#pdc-import'), importNote = $('#pdc-import-status');
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
    // After the catalogue, because the mapping list follows the chosen template's molecule.
    loadMappings();
  }

  function chosenTemplate() {
    return (catalog?.templates || []).find(item => item.id === template.value) || null;
  }

  async function loadMappings() {
    // A build is made of a mapping: the beads a candidate saved from the bead-assignment editor. The list follows the
    // template's molecule, because a mapping is a mapping *of* something, and the panel should not offer another
    // molecule's beads.
    if (!mapping) return;
    const molecule = chosenTemplate()?.molecule || '';
    mapping.replaceChildren(new Option('Looking for saved mappings…', ''));
    if (queue) queue.disabled = true;
    try {
      const payload = await (await fetch(`/api/mappings?molecule_id=${encodeURIComponent(molecule)}`)).json();
      const candidates = payload.candidates || [];
      // The label is the candidate's own name; the value is the file the coordinator resolves a build against.
      mapping.replaceChildren(...(candidates.length ? candidates : [{name: 'No saved mapping for this molecule'}])
        .map(item => new Option(item.name, item.file || item.name)));
      if (queue) queue.disabled = !candidates.length;
    } catch (error) {
      mapping.replaceChildren(new Option('The mapping list could not be read', ''));
    }
  }

  async function loadRuns() {
    // The panel's own door to a run, and it has to be the panel's: `setRun` used to have no caller but
    // `window.pdcSetRun`, a hook that exists for tests, so a reader could not reach the viewer or the series at all.
    if (!runSelect) return;
    runSelect.replaceChildren(new Option('Looking for complex runs…', ''));
    runSelect.disabled = true;
    let jobs = [];
    try {
      // Paged at 20 by default, and an older complex is exactly what a reader compares against, so ask for all.
      const payload = await (await fetch('/api/jobs?limit=100')).json();
      jobs = (payload.jobs || []).filter(job => job.run_type === 'pdc');
    } catch (error) {
      runSelect.replaceChildren(new Option('The run list could not be read', ''));
      return;
    }
    runSelect.replaceChildren(new Option(jobs.length ? 'Choose a run to view' : 'No complex run yet', ''),
      ...jobs.map(job => new Option(`${job.id} · ${job.molecule_id || 'molecule'} · ${job.status}`, job.id)));
    runSelect.disabled = !jobs.length;
    // A link may name the run it wants. Without one the panel opens on the placeholder rather than loading a system
    // nobody asked for -- an option that reads as chosen while nothing is shown would be the panel lying.
    const wanted = new URLSearchParams(location.search).get('run') || '';
    if (wanted && jobs.some(job => job.id === wanted)) {
      runSelect.value = wanted;
      armRun(wanted);
    }
  }

  function armRun(id) {
    // One door, whatever opened it: this list, a link, or the hook the browser tests hold.
    currentRun = id ? {id} : null;
    return Promise.all([loadSnapshots(), loadSystem()]);
  }

  async function importStructure() {
    // The id becomes a file name on the server, and a structure already there is the answer rather than a second
    // download -- so a refusal leaves the catalogue exactly as it was.
    const pdbid = (importField?.value || '').trim();
    if (!pdbid) return;
    if (importButton) importButton.disabled = true;
    if (importNote) importNote.textContent = `Fetching ${pdbid} from OPM…`;
    let response, body = {};
    try {
      response = await fetch('/api/pdc/proteins/import', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                          body: JSON.stringify({pdbid})});
      body = await response.json().catch(() => ({}));
    } catch (error) {
      if (importButton) importButton.disabled = false;
      if (importNote) importNote.textContent = 'The import could not be read: the coordinator did not answer.';
      return;
    }
    if (importButton) importButton.disabled = false;
    if (!response.ok) {
      if (importNote) importNote.textContent = `That import was refused: ${body.error || response.status}`;
      return;
    }
    // The catalogue is where the protein list comes from, so it is invalidated rather than trusted: a cached copy
    // would offer every structure except the one just imported.
    invalidateResource('/api/pdc/catalog');
    catalog = null;
    await load();
    const entry = (catalog.proteins || []).find(item => item.name === body.pdbid);
    if (entry) {
      protein.value = entry.id;
      protein.dispatchEvent(new Event('change'));
    }
    if (importField) importField.value = '';
    if (importNote) importNote.textContent = body.already_present
      ? `${body.pdbid} was already here; the list now offers it.`
      : `Imported ${body.pdbid}` + (body.half_thickness_nm
          ? ` — its file states a ${body.half_thickness_nm} nm half-thickness.`
          : ' — its file states no membrane, so a build would use the protein-extent box.');
  }

  async function queueBuild() {
    // Readiness is read before the POST, so a build that cannot start says why here rather than in a run that dies at
    // stage one. The settings are the catalogue's own defaults: the same ones the pipeline is prepared with.
    const chosen = chosenTemplate();
    if (!chosen || !mapping?.value) return;
    if (status) status.textContent = 'Reading what this build needs…';
    const query = new URLSearchParams({run_type: 'pdc', template: chosen.template, protein: protein?.value || ''});
    let ready = {};
    try {
      ready = await (await fetch(`/api/readiness?${query}`)).json();
    } catch (error) {
      if (status) status.textContent = 'The readiness check could not be read.';
      return;
    }
    if (!ready.ready) {
      if (status) status.textContent = `Not ready: ${(ready.blockers || []).join('; ')}`;
      return;
    }
    if (status) status.textContent = 'Queueing the build…';
    const payload = {...(catalog?.defaults || {}), molecule_id: chosen.molecule, run_type: 'pdc', method: 'bartender',
                     template: chosen.template, mapping_candidate: mapping.value,
                     protein_free: !(protein?.value || '')};
    let response, body = {};
    try {
      response = await fetch('/api/jobs', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                           body: JSON.stringify(payload)});
      body = await response.json().catch(() => ({}));
    } catch (error) {
      if (status) status.textContent = 'The build could not be queued: the coordinator did not answer.';
      return;
    }
    if (status) status.textContent = response.ok
      ? `Queued ${body.id || body.job?.id || 'a run'} — it appears in Single Molecule Simulations as it runs.`
      : `That build was refused: ${body.message || body.error || response.status}`;
  }

  template?.addEventListener('change', describe);
  template?.addEventListener('change', loadSystem);
  template?.addEventListener('change', loadMappings);
  protein?.addEventListener('change', loadSystem);
  // The panel's own selection, and the reason D4 exists: this listener is what makes the viewer reachable without a
  // test hook.
  runSelect?.addEventListener('change', () => { armRun(runSelect.value || null); });
  queue?.addEventListener('click', queueBuild);
  importButton?.addEventListener('click', importStructure);
  // A four-character id and a button, so Enter in the field is the same request as the click.
  importField?.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); importStructure(); }
  });

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

  return { mount: async () => { await Promise.all([load(), loadRuns()]); return $('#'+panelIds().complexes); },
           loadSystem, loadSnapshots,
           // The same door the panel's own list opens, kept as `window.pdcSetRun` for the tests that arm the viewer
           // without waiting for a run to exist.
           setRun: armRun };
}
