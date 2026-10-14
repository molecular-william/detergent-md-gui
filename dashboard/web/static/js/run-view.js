// The Run view panel: one run, its structures, its frames and its figures, in either workspace.
//
// Scoped, never duplicated. The workspace the panel was mounted in decides which run types it offers -- the scope
// arrives in the page (`#run-view-scope`, written from `web/sections.py`'s per-workspace `run_types`), the panel
// asks `/api/jobs` for each of those types *by name*, and a `pdc` run is not drawn here at all: Complexes already
// draws a complex run's built system and its whole snapshot series with each moment's criterion numbers, so this
// panel is a door to it rather than a second strip.
//
// The bond rule is one module (`run-view-structure.js`) and every load goes through it; a coarse-grained structure
// is sized by `ngl-beads.js` rather than by its stand-in element. Both are the repository's existing answers, not
// new ones, which is the point of a shared panel rather than two viewers.
//
// The readout beside the canvas reports what the *renderer* resolved -- atom count and bond count read back off the
// loaded structure -- never what this panel intended to send. A guard asserted only on the request is a guard that
// cannot fail, and both failure modes it exists for (a selection matching nothing, an inference quietly adding
// bonds) render as a plausible picture with a clean console.

import { $, api, panelIds } from './shared.js';
import { BEAD_RADIUS_PARAMETERS, applyBeadRadii, sizeClassOf } from './ngl-beads.js';
import { conectCount, isCoarseGrained, loadParameters, structureExtension, structureRank } from './run-view-structure.js';

//: D13 -- nglview's own `Play(interval=100)`: ten frames a second. Printed on the row, and not a control: the row
//: is two buttons and the slider, and a rate field would be a fourth element in it.
const FRAME_MS = 100;
//: D12 -- stop at the ends rather than wrap or bounce. `loop` and `bounce` are one `setParameters` call away, and
//: the reason for stopping is that a run watched from frame 0 that silently wraps makes its last frame
//: indistinguishable from its first.
const END_MODE = 'once';
//: The route pages the artifact index and caps `limit` at 100, so every request here states its own limit.
const PAGE_LIMIT = 100;
const ALL_TYPES = '';

const TYPE_LABELS = {
  aa_only: 'AA run only',
  aa_cg: 'AA–CG run',
  cg_composition: 'CG composition',
  osmotic: 'Osmotic series',
  pdc: 'Protein-detergent complex',
};

export function createRunView() {
  const section = () => $('#' + panelIds()['run-view']);
  const typeSelect = $('#run-view-type'), statusSelect = $('#run-view-status'), search = $('#run-view-search');
  const list = $('#run-view-list'), count = $('#run-view-count');
  const holds = $('#run-view-holds'), identity = $('#run-view-identity');
  const what = $('#run-view-what'), delegation = $('#run-view-delegation');
  const viewer = $('#run-view-viewer'), readoutHost = $('#run-view-readout');
  const strip = $('#run-view-frames'), stripNote = $('#run-view-frames-note');
  const figures = $('#run-view-figures'), figuresNote = $('#run-view-figures-note');

  const transport = createTransport();
  let scope = {slug: '', types: []};
  let loaded = false;
  let runs = [];
  let totals = 0;
  let selected = null;
  let structures = [];
  let moments = [];
  let published = {frames: null, moments: [], series: null};
  let stage = null;
  let sizeClasses = null;

  // ------------------------------------------------------------------------------------------------ the scope

  function readScope() {
    const block = $('#run-view-scope');
    try {
      const parsed = JSON.parse(block ? block.textContent : '{}');
      scope = {slug: parsed.slug || '', types: Array.isArray(parsed.types) ? parsed.types : []};
    } catch (error) {
      scope = {slug: '', types: []};
    }
    typeSelect.replaceChildren(new Option('All types in this workspace', ALL_TYPES),
      ...scope.types.map(type => new Option(TYPE_LABELS[type] || type, type)));
  }

  // ------------------------------------------------------------------------------------------------- the chooser

  function scopeTypes() {
    const wanted = typeSelect.value;
    return wanted ? [wanted] : scope.types;
  }

  async function loadRuns() {
    if (!scope.types.length) {
      runs = [];
      totals = 0;
      list.replaceChildren();
      count.textContent = 'No run type is registered for this workspace, so there is nothing here to choose.';
      return;
    }
    count.textContent = 'Reading the run list…';
    const status = statusSelect.value;
    // One request per run type in scope -- the route's own `run_type` filter, so the page holds this workspace's
    // runs and `total` describes them rather than a hidden superset of every run on disk.
    const answers = await Promise.all(scopeTypes().map(async type => {
      const query = new URLSearchParams({view: 'summary', limit: String(PAGE_LIMIT), run_type: type});
      if (status) query.set('status', status);
      try {
        const body = await api(`/api/jobs?${query}`);
        return {type, jobs: body.jobs || [], total: Number(body.total) || 0};
      } catch (error) {
        return {type, jobs: [], total: 0, error: error.message};
      }
    }));
    totals = answers.reduce((sum, answer) => sum + answer.total, 0);
    runs = answers.flatMap(answer => answer.jobs)
      .sort((first, second) => String(second.created || '').localeCompare(String(first.created || ''))
                              || String(second.id || '').localeCompare(String(first.id || '')));
    renderList();
  }

  function matches(job) {
    const needle = (search.value || '').trim().toLowerCase();
    if (!needle) return true;
    return [job.id, job.label, job.molecule_name, job.detergent, job.run_type]
      .some(value => String(value || '').toLowerCase().includes(needle));
  }

  function renderList() {
    const shown = runs.filter(matches);
    list.replaceChildren(...shown.map(job => {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('aria-pressed', String(selected ? job.id === selected.id : false));
      const id = document.createElement('span');
      id.className = 'id';
      id.textContent = job.id;
      const meta = document.createElement('span');
      meta.className = 'meta';
      meta.textContent = [job.label || 'untitled', job.molecule_name || job.detergent || '—', job.run_type,
                          job.status].join(' · ');
      button.append(id, meta);
      button.addEventListener('click', () => { open(job.id).catch(error => { count.textContent = error.message; }); });
      item.append(button);
      return item;
    }));
    if (!shown.length) {
      const empty = document.createElement('li');
      empty.className = 'hint';
      empty.textContent = runs.length
        ? 'No run in this scope matches the search.'
        : (statusSelect.value
            ? `No run in this workspace's scope has status ${statusSelect.value}.`
            : "No run in this workspace's scope yet.");
      list.append(empty);
    }
    const breakdown = scopeTypes().map(type => `${TYPE_LABELS[type] || type} `
      + `${runs.filter(job => (job.run_type || 'aa_cg') === type).length}`).join(', ');
    count.textContent = `Showing ${shown.length} of ${totals} run${totals === 1 ? '' : 's'} in this workspace's `
      + `scope (${breakdown}). The list is one page: /api/jobs pages at 20 and caps limit at ${PAGE_LIMIT}, and the `
      + 'panel asks for one run type at a time rather than narrowing a page of every run.';
  }

  // ------------------------------------------------------------------------------------------------- one run

  async function open(id) {
    let job = runs.find(candidate => candidate.id === id) || null;
    if (!job && id) {
      // A link may name a run the current filter does not hold -- another status, or a page boundary. It is read
      // rather than ignored, and only if it belongs to this workspace's scope.
      try {
        job = await api(`/api/jobs/${encodeURIComponent(id)}`);
      } catch (error) {
        job = null;
      }
      if (job && scope.types.length && !scope.types.includes(job.run_type || 'aa_cg')) job = null;
    }
    if (!job) {
      identity.textContent = id ? `Run ${id} is not in this workspace's scope.` : 'Choose a run.';
      return;
    }
    selected = job;
    renderList();
    identity.textContent = `${job.id} · ${job.label || 'untitled'} · ${job.molecule_name || job.detergent || '—'} · `
      + `${job.run_type} · ${job.status} · created ${job.created || '—'}`;
    if ((job.run_type || '') === 'pdc') return delegate(job);
    await loadRun(job);
  }

  function delegate(job) {
    // D9 -- the overlap named rather than discovered. Complexes already draws a complex run's built system and its
    // whole snapshot series, each moment carrying its own criterion numbers, so this panel draws nothing and says
    // where to look, carrying the run across so the reader arrives on it already drawn.
    structures = [];
    moments = [];
    holds.replaceChildren(row('This run is drawn in Complexes.', '—'));
    what.textContent = 'Protein-detergent runs are drawn in Complexes, which already shows the built system and the '
      + "whole snapshot series with each moment's criterion numbers.";
    delegation.replaceChildren();
    delegation.hidden = false;
    const link = document.createElement('a');
    link.href = `/protein-detergent/complexes?run=${encodeURIComponent(job.id)}`;
    link.textContent = `Open run ${job.id} in Complexes`;
    delegation.append(link, document.createTextNode(' — that panel reads ?run= at mount and arms its viewer.'));
    viewer.hidden = true;
    stage?.removeAllComponents();
    transport.hide();
    transport.note('No transport row here, deliberately: the row belongs under a canvas this panel draws, and for '
      + "a complex run Complexes' own snapshot strip is the control for that run's frames.");
    readout([]);
    strip.replaceChildren();
    stripNote.textContent = "A complex run's frames are drawn in Complexes, in the same series.";
    loadFigures(job);
  }

  async function loadRun(job) {
    delegation.hidden = true;
    delegation.replaceChildren();
    viewer.hidden = false;
    what.textContent = 'Reading what this run holds…';
    holds.replaceChildren(row('Reading the run directory…', ''));
    moments = [];
    strip.replaceChildren();
    stripNote.textContent = '';

    let entries = [];
    published = {frames: null, moments: [], series: null};
    try {
      const [gro, pdb, indexes] = await Promise.all([
        artifactIndex(job.id, '.gro'), artifactIndex(job.id, '.pdb'),
        artifactIndex(job.id, 'analyses/snapshots/')]);
      entries = dedupe([...gro, ...pdb]);
      published = await publishedSnapshots(job.id, indexes);
    } catch (error) {
      holds.replaceChildren(row(`The run directory could not be read: ${error.message}`, ''));
      return;
    }

    moments = published.moments;
    structures = entries
      .filter(entry => entry.path.startsWith('stages/') && structureExtension(entry.path)
                       && !entry.path.includes('/inputs/'))
      .map(entry => ({path: entry.path, rank: structureRank(entry.path)}))
      .sort((first, second) => first.rank - second.rank || second.path.localeCompare(first.path));
    if (published.frames) {
      structures.unshift({path: published.frames, rank: -1, frames: true, series: published.series});
    }

    renderHolds(job);
    renderStrip(job);
    loadFigures(job);
    sizeClasses = await loadSizeClasses(job);
    if (!structures.length) {
      what.textContent = 'This run holds no structure file this viewer can open (.gro or .pdb under stages/).';
      readout([]);
      transport.hide();
      transport.note('No structure on screen, so there is nothing to play.');
      return;
    }
    await draw(job, structures[0].path);
  }

  async function artifactIndex(jobId, term) {
    // A page is not the index. The route pages the artifact index and caps `limit` at 100, and the index is walked
    // in *directory* order rather than by age, so a run that has published many attempts -- a series' conditions, or
    // a run analysed again since -- can hold the newest `analyses/snapshots/*/*/result.json`, the record that names
    // the frame series, past the first page. The reader therefore walks every page until the last short one and
    // returns the whole index, so the newest record is resolved wherever it landed.
    const entries = [];
    for (let page = 1; ; page += 1) {
      const query = new URLSearchParams({limit: String(PAGE_LIMIT), page: String(page), search: term});
      const body = await api(`/api/jobs/${encodeURIComponent(jobId)}/artifacts?${query}`);
      const held = body.artifacts || [];
      entries.push(...held);
      const total = Number(body.total);
      if (held.length < PAGE_LIMIT || !Number.isFinite(total) || entries.length >= total) break;
    }
    return dedupe(entries);
  }

  function dedupe(entries) {
    // The searches overlap -- `snapshots/AA-first.pdb` matches both a `.pdb` search and a `snapshots/` one -- and an
    // entry counted twice is a strip with two buttons for one moment.
    const seen = new Set();
    return entries.filter(entry => !seen.has(entry.path) && seen.add(entry.path));
  }

  async function publishedSnapshots(jobId, entries) {
    // The `snapshots` analysis publishes its frames the way every analysis does -- content-addressed, one level
    // under its own attempt, never at the run root:
    //   analyses/snapshots/<signature>/<attempt>/result.json
    //   analyses/snapshots/<signature>/<attempt>/<output_directory>/snapshots/AA-frames.pdb
    // (documented in `references/published-analysis-addressing.md`). So the reader finds the newest `result.json`,
    // joins the attempt directory with the record's `output_directory`, and takes the files the record names. The
    // producer is not asked to publish anywhere else: the attempt directory is the analysis's own, and a reader
    // that assumed a run-root `snapshots/` would see nothing however many runs have been published.
    const records = entries.filter(entry => entry.path.endsWith('result.json'));
    records.sort((first, second) => String(second.modified_at || '').localeCompare(String(first.modified_at || '')));
    for (const entry of records) {
      let record = null;
      try {
        record = JSON.parse(await artifactText(jobId, entry.path));
      } catch (error) {
        continue;
      }
      const attempt = entry.path.slice(0, entry.path.lastIndexOf('/') + 1);
      const output = String(record.output_directory || '').replace(/^\/+|\/+$/g, '');
      const root = output ? `${attempt}${output}/` : attempt;
      const named = Object.keys(record.outputs_sha256 || {});
      const files = (named.length ? named : (record.result?.files || []).map(name => `snapshots/${name}`))
        .filter(name => name.endsWith('.pdb'));
      const frames = files.find(name => /-frames\.pdb$/.test(name));
      const moments = files.filter(name => /-(first|middle|last)\.pdb$/.test(name))
        .map(name => ({path: root + name, label: /-([a-z]+)\.pdb$/.exec(name)[1]}));
      if (frames || moments.length) {
        return {frames: frames ? root + frames : null, moments, series: record.result?.series || null};
      }
    }
    return {frames: null, moments: [], series: null};
  }

  function row(path, bonds) {
    const line = document.createElement('tr');
    const file = document.createElement('td');
    const code = document.createElement('code');
    code.textContent = path;
    file.append(code);
    const bondCell = document.createElement('td');
    bondCell.textContent = bonds;
    line.append(file, bondCell);
    return line;
  }

  function renderHolds(job) {
    holds.replaceChildren(...structures.map(entry => {
      // A coarse-grained `.gro` is served with the run's own `[ bonds ]` + `[ constraints ]` written as CONECT (the
      // structure route); an all-atom `.gro` carries none, which is what the row says.
      const bonds = entry.frames
        ? 'none recorded — this is the sampled frame series the transport row plays'
        : (structureExtension(entry.path) !== 'gro'
            ? 'read when the file is opened'
            : (isCoarseGrained(entry.path, job.run_type)
                ? "the run's own [ bonds ] + [ constraints ], written as CONECT by the structure route"
                : 'none — a .gro carries no bond records'));
      const line = row(entry.path, bonds);
      line.setAttribute('aria-selected', String(entry.path === (structures[0] || {}).path));
      line.style.cursor = 'pointer';
      line.addEventListener('click', () => { draw(job, entry.path).catch(error => { what.textContent = error.message; }); });
      return line;
    }));
  }

  function renderStrip(job) {
    if (!moments.length) {
      strip.replaceChildren();
      stripNote.textContent = 'This run has published no frame snapshots. The snapshots analysis writes one '
        + 'multi-model PDB of sampled frames and the three labelled moments beside it, under its own attempt '
        + '(`analyses/snapshots/<signature>/<attempt>/.../snapshots/`); a run with no trajectory skips it with its '
        + 'own reason. Until one lands the strip is empty, and the row under the canvas says why: no route serves a '
        + "single frame of this run's .xtc, and this panel does not parse one in the browser.";
      syncStrip();
      return;
    }
    strip.replaceChildren(...moments.map(moment => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = moment.label;
      button.dataset.label = moment.label;
      button.dataset.frame = '';
      button.setAttribute('aria-pressed', 'false');
      button.addEventListener('click', () => transport.setFrame(button.dataset.frame));
      return button;
    }));
    stripNote.textContent = `${moments.length} sampled moments recorded. A strip button sets the frame and stops `
      + 'there; its pressed state moves only while the playhead sits exactly on it.';
    syncStrip();
  }

  // D16 -- the strip follows the playhead and never starts it. A button sets the frame the way the slider does and
  // stops; its pressed state moves only when the playhead is exactly on a saved frame, so a strip of three sampled
  // moments lights up three times a pass and not in between.
  function syncStrip() {
    const total = transport.frames;
    const last = Math.max(0, total - 1);
    strip.querySelectorAll('button').forEach(button => {
      const index = {first: 0, middle: Math.max(0, (total - 1) >> 1), last}[button.dataset.label];
      const known = Number.isInteger(index);
      button.dataset.frame = String(known ? index : '');
      button.disabled = !(total > 1);
      button.title = button.disabled
        ? 'this structure holds one frame, so there is no frame to jump to'
        : `frame ${index} of ${last}`;
      button.setAttribute('aria-pressed',
        String(!button.disabled && known && index === transport.frameNow()));
    });
  }

  async function loadFigures(job) {
    figures.replaceChildren();
    let entries = [];
    try {
      const body = await api(`/api/jobs/${encodeURIComponent(job.id)}/figures`);
      entries = body.artifacts || [];
    } catch (error) {
      figuresNote.textContent = `This run's figures could not be read: ${error.message}`;
      return;
    }
    if (!entries.length) {
      figuresNote.textContent = 'This run published no figure. Every figure the workspace holds belongs to the run '
        + 'that drew it, and this one drew none.';
      return;
    }
    figures.replaceChildren(...entries.map(entry => {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = `/api/jobs/${encodeURIComponent(job.id)}/artifacts/`
        + entry.path.split('/').map(encodeURIComponent).join('/') + '?inline=1';
      link.target = '_blank';
      link.rel = 'noopener';
      const code = document.createElement('code');
      code.textContent = entry.path;
      link.append(code);
      item.append(link);
      return item;
    }));
    figuresNote.textContent = `${entries.length} figure${entries.length === 1 ? '' : 's'}, straight from the stages `
      + 'that wrote them, opened inline through the run artifact route. The zoomable, pannable gallery stays in the '
      + 'Runs panel.';
  }

  // ------------------------------------------------------------------------------------- structures and the row

  async function loadSizeClasses(job) {
    // D8 -- the run's own `model.json` states each bead's size class when it is readable, and a caption says which
    // was used, because a bead's radius is a claim. It is read whether or not the artifact index returned it: the
    // index is paged, and a 404 here is simply "this run states no size class".
    try {
      const document_ = JSON.parse(await artifactText(job.id, 'stages/2_mapping/model.json'));
      const classes = {};
      for (const bead of document_.beads || []) {
        const size = String(bead.size || '').trim().toUpperCase();
        if (size) for (const name of [bead.export_name, bead.name]) {
          if (name) classes[String(name).trim().toUpperCase()] = size;
        }
      }
      return Object.keys(classes).length ? classes : null;
    } catch (error) {
      return null;
    }
  }

  async function artifactText(jobId, path) {
    const url = `/api/jobs/${encodeURIComponent(jobId)}/artifacts/`
      + path.split('/').map(encodeURIComponent).join('/') + '?inline=1';
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${path} could not be read (${response.status})`);
    return response.text();
  }

  //: The route that writes a run's own bonds onto one of its structures. A `.gro` carries no bond records -- and
  //: this vendored build's GRO parser guesses them from distances whatever `inferBonds` says, which the caller then
  //: clears -- so a coarse-grained model drawn off the artifact route is beads with no connectivity at all, while
  //: the run's own moleculetype, under `stages/3_initial_CG/`, states exactly which beads are bonded. This route is
  //: where those `[ bonds ]` and `[ constraints ]` become CONECT records, and its answer is read as the PDB it is.
  //: `null` means the route refused; the caller then falls back to the artifact route and the file is drawn the way
  //: it always was.
  async function structureText(job, path) {
    const response = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/structure`
      + `?path=${encodeURIComponent(path)}`);
    return response.ok ? response.text() : null;
  }

  function stageFor() {
    if (!viewer) return null;
    // Created on first use: NGL sizes itself to its host element, and the host is sized for it in run-view.css.
    if (!viewer.runViewStage) viewer.runViewStage = new NGL.Stage(viewer, {backgroundColor: 'white'});
    return viewer.runViewStage;
  }

  async function draw(job, path) {
    const entry = structures.find(candidate => candidate.path === path) || {path, rank: structureRank(path)};
    what.textContent = `Loading ${path}…`;
    const coarse = isCoarseGrained(path, job.run_type);
    // A coarse-grained `.gro` carries no bond records, and this build's GRO parser guesses from distances whatever
    // `inferBonds` says -- measured: the eight mapped beads of a `.gro` came back with four guessed bonds, which the
    // guard below then clears. Either way the picture is beads with no connectivity, while the run's own moleculetype
    // states the bonds: the run structure route is where they become CONECT records, and the answer is read as the
    // PDB it is, so the CONECT branch below draws exactly those bonds with the distance guess off. Every other file
    // keeps the artifact route and the rule in `run-view-structure.js`; a refused route falls back to that path.
    let text = null, served = false;
    if (coarse && structureExtension(path) === 'gro') {
      text = await structureText(job, path);
      served = text !== null;
    }
    let parameters;
    if (served) {
      parameters = {ext: 'pdb', inferBonds: 'none',
        reason: conectCount(text)
          ? "the run's own moleculetype, written as CONECT over this file's coordinates "
            + '(stages/3_initial_CG/) — the model\'s bonds, and the distance guess is off'
          : 'coarse-grained, and this run states no moleculetype under stages/3_initial_CG/, so the picture claims '
            + 'no bonds rather than guessing them'};
    } else {
      text = await artifactText(job.id, path);
      parameters = loadParameters(text, {path, runType: job.run_type});
    }
    const renderer = stageFor();
    if (!renderer) {
      what.textContent = 'This page could not start a 3D view. The file\'s own numbers, which do not need a '
        + 'renderer, still hold.';
      readout([['atoms in the file', String(countRecords(text))],
               ['bonds from the file', String(conectCount(text))],
               ['how the bonds would be decided', parameters.reason]]);
      return;
    }
    renderer.removeAllComponents();
    // Trap measured by the plan: a multi-model PDB loaded *without* `asTrajectory` comes back as one structure with
    // every model's atoms drawn at once and no trajectory at all -- and `loadFile` does not attach a trajectory by
    // itself; `component.addTrajectory()` is what creates one. A row built on the assumption that the trajectory is
    // there renders a plausible picture with a dead slider.
    const options = {...parameters};
    if (entry.frames) options.asTrajectory = true;
    const component = await renderer.loadFile(new Blob([text], {type: 'text/plain'}), options);
    if (entry.frames) component.addTrajectory();
    // A file that states no bonds of its own must be drawn without any, and `inferBonds: 'none'` is not enough on
    // its own for every format: this build's `PdbParser` passes the flag through to `calculateBonds`, but its
    // `GroParser` calls `calculateBonds(structure)` with no argument at all -- measured: the eight mapped beads of
    // a `.gro` came back with four guessed bonds whatever the flag said. So the store is emptied here too, and
    // **only** where the file carries no `CONECT` of its own, so a file that does state its bonds keeps every one.
    if (parameters.inferBonds === 'none' && conectCount(text) === 0) dropBonds(component.structure);
    if (coarse) {
      // A bead's radius is a size class the model states, not the stand-in element's: `ngl-beads.js` is the one
      // table and the one call, so this view draws the same beads as Complexes and the bead editor. The scale is
      // this panel's own and stated at the call: 1 -- the run view draws the model's radius, and the panel that
      // reads it larger (the composition preview) is where the multiplier belongs.
      applyBeadRadii(component.structure, {scale: 1, sizeOf: atom => {
        const named = sizeClasses && sizeClasses[String(atom.atomname || '').trim().toUpperCase()];
        return named || sizeClassOf(atom);
      }});
      component.addRepresentation('ball+stick', BEAD_RADIUS_PARAMETERS);
    } else {
      component.addRepresentation('ball+stick', {radiusScale: 0.55, aspectRatio: 2});
    }
    component.autoView();

    holds.querySelectorAll('tr').forEach((line, index) => {
      line.setAttribute('aria-selected', String(structures[index] && structures[index].path === path));
    });
    const structure = component.structure;
    what.textContent = `${job.id} · ${path} · ${entry.frames ? `sampled frames series (${structure.frames?.length || 0} `
      + 'models)' : (coarse ? 'coarse-grained' : 'all-atom')}.`;
    readout([
      ['atoms drawn', String(structure.atomCount)],
      [served ? "bonds the run's own topology states" : 'bonds the file states', String(conectCount(text))],
      ['bonds the viewer resolved', String(structure.bondCount), 'ok'],
      ['how the bonds were decided', parameters.reason],
      ['bead radii', coarse
        ? (sizeClasses ? "the run's own stages/2_mapping/model.json size classes" : 'uniform — no readable size class')
        : 'not applicable (all-atom)'],
    ]);
    attachRow(job, component, path, entry);
    syncStrip();
  }

  //: D13 -- printed on the row's own note so a reader can tell what rate they are watching, and not a control: the
  //: ask fixes the row's contents to two buttons and the slider.
  const RATE_TEXT = `${FRAME_MS} ms a frame, ten a second`;

  function attachRow(job, component, path, entry) {
    viewer.runViewTransport = transport;
    if (entry.frames) {
      const series = entry.series || {};
      const where = series.sampled
        ? `${series.sampled} frames sampled from the run's own trajectory at a stride of ${series.stride}`
        : 'the frames this run published';
      transport.attach(component, {note: `${where} · ${RATE_TEXT} (D13) · the ends stop rather than wrap (D12) · `
        + 'the slider is the frame shown and the frame playback starts from (D14) · the readout prints the frame '
        + 'index and no time, because frames served as a PDB declare none (D15).'});
      return;
    }
    const trajectory = job.run_type === 'aa_only' ? '07_reference/lig.xtc' : '4_CG_sim/md.xtc';
    transport.attach(component, {note: `${RATE_TEXT}. ${path} holds one frame, and no route serves a frame of this `
      + `run's ${trajectory}: the panel does not parse a .xtc in the browser. The controls are drawn rather than `
      + 'hidden so the reason is readable (D17). The snapshots analysis publishes a multi-model frame series under '
      + "its own attempt when it runs, and that is the file this row plays; this run has published none."});
  }

  function countRecords(text) {
    return (String(text).match(/^(ATOM|HETATM)/gm) || []).length;
  }

  function dropBonds(structure) {
    if (structure && structure.bondStore) structure.bondStore.count = 0;
  }

  function readout(cells) {
    readoutHost.replaceChildren(...cells.map(([label, value, kind]) => {
      const cell = document.createElement('span');
      const cap = document.createElement('span');
      cap.className = 'hint';
      cap.textContent = label;
      const strong = document.createElement('b');
      strong.className = kind || '';
      strong.textContent = value;
      cell.append(cap, strong);
      return cell;
    }));
  }

  // -------------------------------------------------------------------------------------- the transport row (T8)

  function createTransport() {
    const rowHost = $('#run-view-transport');
    const reverse = $('#run-view-reverse'), forward = $('#run-view-forward');
    const slider = $('#run-view-frame'), frameReadout = $('#run-view-frame-readout');
    const note = $('#run-view-transport-note');
    const callbacks = [];
    let trajectory = null, player = null, frames = 0;
    let hidden = true;

    const at = () => (trajectory && trajectory.currentFrame >= 0 ? trajectory.currentFrame : 0);

    function sync() {
      const running = !!(player && player.isRunning);
      const direction = player ? player.parameters.direction : 'forward';
      forward.setAttribute('aria-pressed', String(running && direction === 'forward'));
      reverse.setAttribute('aria-pressed', String(running && direction === 'backward'));
      const frame = at();
      slider.value = String(Math.max(0, Math.min(frame, Math.max(0, frames - 1))));
      frameReadout.textContent = frames > 1 ? `frame ${frame} of ${frames - 1}` : 'frame 0 of 0';
      for (const callback of callbacks) callback(frame, {running, direction});
    }

    function disable(reason) {
      const why = String(reason).replace(/\s+/g, ' ').trim();
      for (const element of [reverse, forward, slider]) { element.disabled = true; element.title = why; }
      if (note) note.textContent = why;
      sync();
    }

    function show() { hidden = false; rowHost.hidden = false; }
    function hide() { hidden = true; pause(); rowHost.hidden = true; }
    function pause() { if (player) { player.pause(); } sync(); }

    function play(which) {
      if (!player) return;
      const direction = which === 'reverse' ? 'backward' : 'forward';
      // Pressing the running direction again pauses: what nglview's single Play button does (D11).
      if (player.isRunning && player.parameters.direction === direction) player.pause();
      else { player.setParameters({direction}); player.play(); }
      sync();
    }

    reverse.addEventListener('click', () => play('reverse'));
    forward.addEventListener('click', () => play('forward'));
    slider.addEventListener('input', () => {
      if (!trajectory) return;
      if (player) player.pause();
      trajectory.setFrame(Number(slider.value));
      sync();
    });

    return {
      get frames() { return frames; },
      get trajectory() { return trajectory; },
      get player() { return player; },
      get hidden() { return hidden; },
      frameNow: at,
      readoutText: () => frameReadout.textContent,
      sync, show, hide, pause,
      onFrame(callback) { callbacks.push(callback); },
      note(text) { if (note) note.textContent = text; },
      setFrame(frame) {
        if (!trajectory) return;
        if (player) player.pause();
        trajectory.setFrame(Number(frame));
        sync();
      },
      attach(component, {note: noteText} = {}) {
        const element = component && component.trajList && component.trajList[0];
        trajectory = element ? element.trajectory : null;
        frames = trajectory ? trajectory.frameCount : 0;
        show();
        if (frames < 2) {
          disable(`${noteText || ''} Measured on the component the viewer resolved: ${frames} `
            + `frame${frames === 1 ? '' : 's'}.`);
          return;
        }
        player = new NGL.TrajectoryPlayer(trajectory, {step: 1, timeout: FRAME_MS, start: 0, end: frames - 1,
                                                       mode: END_MODE, direction: 'forward'});
        slider.max = String(frames - 1);
        for (const element of [reverse, forward, slider]) {
          element.disabled = false;
          element.removeAttribute('title');
        }
        if (note) note.textContent = noteText || '';
        element.signals.frameChanged.add(() => sync());
        trajectory.setFrame(0);
        sync();
      },
    };
  }

  // Trap measured by the plan: playback is driven by `requestAnimationFrame`, so a panel that is hidden advances
  // ZERO frames while it keeps claiming to play. Rather than return to a stale picture, the row pauses when this
  // panel stops being the open one -- and when the page itself is hidden.
  document.addEventListener('dashboard:tab', event => {
    if (event.detail && event.detail.id !== panelIds()['run-view']) transport.pause();
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) transport.pause(); });

  typeSelect.addEventListener('change', () => loadRuns().catch(error => { count.textContent = error.message; }));
  statusSelect.addEventListener('change', () => loadRuns().catch(error => { count.textContent = error.message; }));
  search.addEventListener('input', renderList);
  transport.onFrame(() => {
    strip.querySelectorAll('button').forEach(button => {
      button.setAttribute('aria-pressed', String(
        button.dataset.frame !== '' && Number(button.dataset.frame) === transport.frameNow()));
    });
  });

  return {
    mount: async () => {
      if (!loaded) {
        loaded = true;
        readScope();
        await loadRuns();
      }
      const wanted = new URLSearchParams(location.search).get('run') || '';
      const target = wanted || (selected ? selected.id : (runs[0] || {}).id || '');
      if (target) await open(target);
      return section();
    },
  };
}
