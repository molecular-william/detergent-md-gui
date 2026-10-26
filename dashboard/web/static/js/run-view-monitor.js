// One monitor of the Run view: a run selected from a combo, its structure on a canvas, its frames on a transport, and
// its own "what this run holds" / "frames" / "figures" panels below the canvas, collapsed.
//
// Two of these sit side by side (`run-view.js` builds them), which is why everything here is scoped to `side`: every
// element id in this file is written `#<name>-<side>`, resolved once through `id()`, and never a bare `#run-view-…`
// that two monitors would fight over. The alternative -- one panel that swaps runs -- is the thing this replaced.
//
// The per-run work below is the panel's own, moved rather than rewritten: the structure index, the published frame
// series and its moments, the bond rule's application, the bead sizing, the readout, the generate controls and the
// overwrite prompt. A reader who used the single-run panel keeps every one of them, per monitor.
//
// The bond rule is one module (`run-view-structure.js`), the bead table is another (`ngl-beads.js`), and the chooser
// filters as you type over the run's own label, molecule, type, id and date. Nothing here decides anything twice.

import { $, api, panelIds, post } from './shared.js';
import { BEAD_FAMILY_PARAMETERS, BEAD_RADIUS_PARAMETERS, applyBeadRadii, renderBeadLegend, sizeClassOf } from './ngl-beads.js';
import { conectCount, dropBonds, inStage, isCoarseGrained, loadParameters, structureExtension,
         structureRank } from './run-view-structure.js';

//: D13 -- nglview's own `Play(interval=100)`: ten frames a second. Printed on the row, and not a control: the row is
//: two buttons and the slider, and a rate field would be a fourth element in it.
const FRAME_MS = 100;
//: D12 -- stop at the ends rather than wrap or bounce, so a run watched from frame 0 cannot silently wrap.
const END_MODE = 'once';
//: The route pages the artifact index and caps `limit` at 100, so every request here states its own limit.
const PAGE_LIMIT = 100;
//: D18 -- the scale this panel draws its beads at, on top of `ngl-beads.js`'s table, for reading only.
const BEAD_SCALE = 0.3;
//: How often a queued snapshots analysis is asked whether it has finished.
const GENERATE_POLL_MS = 4000;

export function createMonitor({root, side, runs, onPick, onFrame}) {
  const id = name => `#${name}-${side}`;
  root.innerHTML = monitorMarkup(side);
  // Resolved once, by the monitor's own ids. Every lookup in this file goes through one of these handles, so two
  // monitors in one page cannot reach into each other.
  const holds = $(id('run-view-holds'));
  const identity = $(id('run-view-identity'));
  const holdsCount = $(id('run-view-holds-count'));
  const what = $(id('run-view-what'));
  const segmentsWrap = $(id('run-view-segments-wrap'));
  const segmentsTable = $(id('run-view-segments-table'));
  const segmentsBody = $(id('run-view-segments'));
  const segmentsNote = $(id('run-view-segments-note'));
  const viewer = $(id('run-view-viewer'));
  const readoutHost = $(id('run-view-readout'));
  const label = $(id('run-view-label'));
  const status = $(id('run-view-status'));
  const strip = $(id('run-view-frames'));
  const stripNote = $(id('run-view-frames-note'));
  const framesCount = $(id('run-view-frames-count'));
  const figures = $(id('run-view-figures'));
  const figuresNote = $(id('run-view-figures-note'));
  const figuresCount = $(id('run-view-figures-count'));
  const generate = $(id('run-view-generate'));
  const generateNote = $(id('run-view-generate-note'));
  const intervalInput = $(id('run-view-generate-interval'));
  const alignInput = $(id('run-view-generate-align'));
  const alignOnInput = $(id('run-view-generate-align-on'));
  const rowHost = $(id('run-view-transport'));
  const reverse = $(id('run-view-reverse'));
  const slider = $(id('run-view-frame'));
  const note = $(id('run-view-transport-note'));
  const legend = $(id('run-view-legend'));

  const transport = createTransport();
  let selected = null;               // the run this monitor holds
  let structures = [];
  let moments = [];
  let published = {frames: null, moments: [], series: null};
  let generating = false;
  let pollTimer = null;
  let stage = null;
  let sizeClasses = null;
  let subunits = null;

  // The counts in the three summaries are read off the panels themselves rather than tracked separately, so a
  // collapsed panel still says how much is behind it and no second bookkeeping can disagree with the first.
  function refreshCounts() {
    holdsCount.textContent = holds.querySelectorAll('tr').length ? `(${holds.querySelectorAll('tr').length})` : '';
    const models = published.series ? Number(published.series.sampled) : 0;
    framesCount.textContent = models ? `(${models})` : (moments.length ? `(${moments.length})` : '');
    figuresCount.textContent = figures.querySelectorAll('li').length ? `(${figures.querySelectorAll('li').length})` : '';
  }
  for (const host of [holds, strip, figures, figuresNote, stripNote]) {
    new MutationObserver(refreshCounts).observe(host, {childList: true, subtree: true, characterData: true});
  }

  // ------------------------------------------------------------------------------------------------ the combo

  const combo = chooser(root, side, runs, job => onPick(job));


// The monitor's own markup, built here rather than in the page template: two of everything is the layout, and the
// ids are the only thing that differs between the two. The `<details>` are collapsed, which is what "minimizable and
// minimized by default" asked for, and each summary carries the count of what is behind it.
function monitorMarkup(side) {
  return `
  <div class="monitor" data-side="${side}">
    <div class="card monitor-head">
      <div class="chooser" data-open="false">
        <label class="grow"><span class="hint cap">Choose a run (completed only)</span>
          <input type="text" class="filter" id="run-view-choose-${side}" autocomplete="off" spellcheck="false"
                 placeholder="type a molecule, run type, id or date…"></label>
        <div class="list" role="listbox" id="run-view-list-${side}"></div>
      </div>
      <p class="hint" id="run-view-status-${side}"></p>
    </div>
    <div class="card run-view-stage">
      <p class="monitor-label" id="run-view-label-${side}"></p>
      <div id="run-view-viewer-${side}" class="run-view-viewer" role="img"
           aria-label="Structure from the run this monitor holds"></div>
      <div id="run-view-legend-${side}" class="bead-legend" data-bead-legend hidden
           aria-label="Bead colour by Martini 3 polarity family"></div>
      <div id="run-view-readout-${side}" class="run-view-readout"></div>
      <div class="run-view-transport" id="run-view-transport-${side}" role="group" aria-label="Playback" hidden>
        <div class="transport-controls">
          <button type="button" class="transport-reverse" id="run-view-reverse-${side}"
                  aria-label="Play in reverse" aria-pressed="false">◀</button>
          <button type="button" class="transport-forward" id="run-view-forward-${side}"
                  aria-label="Play forward" aria-pressed="false">▶</button>
          <label class="transport-frame">Frame
            <input type="range" id="run-view-frame-${side}" min="0" max="0" step="1" value="0"
                   aria-describedby="run-view-transport-note-${side}">
            <span id="run-view-frame-readout-${side}" class="transport-frame-readout">frame 0 of 0</span>
          </label>
        </div>
        <span class="hint" id="run-view-transport-note-${side}"></span>
      </div>
    </div>
    <details class="card run-view-sub" id="run-view-holds-details-${side}">
      <summary>what this run holds <span class="count" id="run-view-holds-count-${side}"></span></summary>
      <div class="body">
        <p class="hint" id="run-view-identity-${side}"></p>
        <p id="run-view-what-${side}"></p>
        <div class="table-scroll"><table class="run-view-structures">
          <caption class="sr-only">Structure files in the run this monitor holds</caption>
          <thead><tr><th scope="col">File</th><th scope="col">Bonds</th></tr></thead>
          <tbody id="run-view-holds-${side}"><tr><td colspan="2">No run selected.</td></tr></tbody>
        </table></div>
      </div>
    </details>
    <details class="card run-view-sub" id="run-view-frames-details-${side}">
      <summary>frames <span class="count" id="run-view-frames-count-${side}"></span></summary>
      <div class="body">
        <div class="table-scroll" id="run-view-segments-wrap-${side}" hidden>
          <table class="run-view-segments" id="run-view-segments-table-${side}">
            <caption class="sr-only">The CG MD segments this run holds, in stage order</caption>
            <thead><tr><th scope="col">Stage</th><th scope="col">Atoms</th>
              <th scope="col">Trajectory</th><th scope="col">Note</th></tr></thead>
            <tbody id="run-view-segments-${side}"></tbody>
          </table>
          <p class="hint" id="run-view-segments-note-${side}"></p>
        </div>
        <div id="run-view-frames-${side}" class="run-view-strip"></div>
        <p class="hint" id="run-view-frames-note-${side}"></p>
        <div class="toolbar run-view-generate">
          <button id="run-view-generate-${side}" type="button">Generate trajectory</button>
          <label>ns a frame <input type="number" id="run-view-generate-interval-${side}" min="0.01" step="0.01"
            placeholder="40 frames"></label>
          <label><input type="checkbox" id="run-view-generate-align-${side}"> fit the frames</label>
          <label>fit on: <select id="run-view-generate-align-on-${side}"></select></label>
        </div>
        <p class="hint" id="run-view-generate-note-${side}"></p>
      </div>
    </details>
    <details class="card run-view-sub" id="run-view-figures-details-${side}">
      <summary>figures <span class="count" id="run-view-figures-count-${side}"></span></summary>
      <div class="body">
        <ul id="run-view-figures-${side}" class="run-view-figures"></ul>
        <p class="hint" id="run-view-figures-note-${side}"></p>
      </div>
    </details>
  </div>`;
}

// The combo: an input with its own filtered listbox, so a reader types and the list narrows. Words in any order,
// matched against what a reader would type, and only completed runs are ever offered -- the host filters that, and
// this says how many were held back rather than hiding them silently.
function chooser(root, side, runs, onPick) {
  const box = root.querySelector('.chooser');
  const input = root.querySelector('.filter');
  const list = root.querySelector('.list');
  let selected = null, active = 0;
  //: What the reader has typed *since* they last reached for the box. The input also carries the chosen run's own
  //: label, so filtering by its value would filter every run out the moment a reader clicked the box without
  //: typing -- which is exactly what happened, and what an empty list under a focused box looks like.
  let query = '';

  const matches = (job, text) => {
    const needle = String(text || '').trim().toLowerCase();
    if (!needle) return true;
    const haystack = `${job.label || ''} ${job.molecule_id || ''} ${job.run_type || ''} ${job.id || ''} `
      + `${String(job.created || '').slice(0, 10)}`.toLowerCase();
    return needle.split(/\s+/).every(word => haystack.includes(word));
  };

  function render() {
    const shown = (runs || []).filter(job => matches(job, query));
    active = Math.min(active, Math.max(shown.length - 1, 0));
    box.dataset.open = 'true';
    if (!shown.length) {
      list.innerHTML = '<div class="none">No completed run matches that.</div>';
      return;
    }
    const groups = [];
    for (const job of shown) {
      const type = job.run_type || 'other';
      if (!groups.length || groups[groups.length - 1].type !== type) groups.push({type, jobs: []});
      groups[groups.length - 1].jobs.push(job);
    }
    list.replaceChildren(...groups.flatMap(group => {
      const head = document.createElement('div');
      head.className = 'group';
      head.textContent = group.type;
      return [head, ...group.jobs.map(job => {
        const button = document.createElement('button');
        button.type = 'button';
        button.setAttribute('role', 'option');
        button.dataset.id = job.id;
        button.innerHTML = `<span>${job.label || job.molecule_id || job.id}</span> `
          + `<span class="meta">· ${job.run_type} · ${job.id} · ${String(job.created || '').slice(0, 10)}</span>`;
        button.dataset.selected = String(selected && selected.id === job.id);
        return button;
      })];
    }));
  }

  function pick(job) {
    if (!job) return;
    selected = job;
    input.value = `${job.label || job.molecule_id || job.id} · ${job.run_type} · ${job.id}`;
    query = '';
    box.dataset.open = 'false';
    // Once. This used to call onPick here *and* above the field updates, so every pick opened the run twice: two
    // artifact walks, two `/figures` reads and two NGL loads for one choice.
    if (onPick) onPick(job);
  }

  input.addEventListener('focus', () => { query = ''; active = 0; render(); });
  input.addEventListener('input', () => { query = input.value; active = 0; render(); });
  input.addEventListener('keydown', event => {
    const shown = (runs || []).filter(job => matches(job, query));
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      active = Math.max(0, Math.min(shown.length - 1, active + (event.key === 'ArrowDown' ? 1 : -1)));
      list.querySelectorAll('button').forEach((button, index) => button.dataset.active = String(index === active));
      return;
    }
    if (event.key === 'Enter') { event.preventDefault(); pick(shown[active]); return; }
    if (event.key === 'Escape') box.dataset.open = 'false';
  });
  list.addEventListener('click', event => {
    const button = event.target.closest('button[data-id]');
    if (button) pick((runs || []).find(job => job.id === button.dataset.id));
  });
  document.addEventListener('click', event => {
    if (!box.contains(event.target)) box.dataset.open = 'false';
  });

  return {
    set: job => { selected = job; input.value = job
      ? `${job.label || job.molecule_id || job.id} · ${job.run_type} · ${job.id}` : ''; },
    get: () => selected,
    focus: () => input.focus(),
  };
}


  async function loadRun(job, {refresh = false} = {}) {
    // `refresh` asks the artifact routes to re-read the run directory rather than serve the index the store holds:
    // a completed run's index is otherwise frozen, so a run whose analysis published while this panel watched would
    // show nothing new until a restart. Only the path that queued that analysis sets it.
    viewer.hidden = false;
    // Who this monitor is holding, in one line: the id, what the run is called, the molecule it is about and the
    // day it ran. It was the list that used to say this, and the list is two combos now.
    identity.textContent = `${job.id} · ${job.label || 'untitled'} · `
      + `${job.molecule_name || job.detergent || '—'}`
      + (job.created ? ` · ${String(job.created).slice(0, 10)}` : '');
    what.textContent = 'Reading what this run holds…';
    holds.replaceChildren(row('Reading the run directory…', ''));
    moments = [];
    strip.replaceChildren();
    stripNote.textContent = '';
    // The segments are asked for here -- before the artifact index, the structure gate and the canvas -- and fired
    // rather than awaited: `/trajectory` answers from the run's stage files alone, so neither an index that failed
    // nor a structure list that matched nothing can stop the panel asking, the endpoint's own `why` is printed for a
    // run with nothing to play, and a slow answer cannot delay the drawing below.
    loadSegments(job);

    let entries = [];
    published = {frames: null, moments: [], series: null};
    try {
      const [gro, pdb, indexes] = await Promise.all([
        artifactIndex(job.id, '.gro', {refresh}), artifactIndex(job.id, '.pdb', {refresh}),
        artifactIndex(job.id, 'analyses/snapshots/', {refresh})]);
      entries = dedupe([...gro, ...pdb]);
      published = await publishedSnapshots(job.id, indexes);
    } catch (error) {
      holds.replaceChildren(row(`The run directory could not be read: ${error.message}`, ''));
      return;
    }

    moments = published.moments;
    structures = entries
      .filter(entry => inStage(entry.path) && structureExtension(entry.path)
                       && !entry.path.includes('/inputs/'))
      .map(entry => ({path: entry.path, rank: structureRank(entry.path)}))
      .sort((first, second) => first.rank - second.rank || second.path.localeCompare(first.path));
    if (published.frames) {
      structures.unshift({path: published.frames, rank: -1, frames: true, series: published.series});
    }

    renderHolds(job);
    renderStrip(job);
    updateGenerate(job);
    loadFigures(job);
    sizeClasses = await loadSizeClasses(job);
    subunits = await loadSubunits(job);
    renderAlignTargets();
    if (!structures.length) {
      what.textContent = 'This run holds no structure file this viewer can open (.gro or .pdb under stages/).';
      readout([]);
      transport.hide();
      transport.note('No structure on screen, so there is nothing to play.');
      return;
    }
    await draw(job, structures[0].path);
  }

  async function artifactIndex(jobId, term, {refresh = false} = {}) {
    // A page is not the index. The route pages the artifact index and caps `limit` at 100, and the index is walked
    // in *directory* order rather than by age, so a run that has published many attempts -- a series' conditions, or
    // a run analysed again since -- can hold the newest `analyses/snapshots/*/*/result.json`, the record that names
    // the frame series, past the first page. The reader therefore walks every page until the last short one and
    // returns the whole index, so the newest record is resolved wherever it landed.
    const entries = [];
    for (let page = 1; ; page += 1) {
      const query = new URLSearchParams({limit: String(PAGE_LIMIT), page: String(page), search: term});
      if (refresh) query.set('refresh', '1');
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

  // ----------------------------------------------------------------- generating a frame series (D18)

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  async function holdsTrajectory(job) {
    // The frames come from a file the run wrote, so the button's first question is whether this run holds one. The
    // artifact index answers it: a `.xtc` under `stages/`, and not under a stage's own `inputs/`, which holds copies
    // of what the run was handed rather than what it wrote.
    try {
      const entries = await artifactIndex(job.id, '.xtc');
      return entries.some(entry => inStage(entry.path) && !entry.path.includes('/inputs/'));
    } catch (error) {
      return false;
    }
  }

  async function updateGenerate(job) {
    // Runs on every run load: the control follows what the run holds. It is offered wherever a trajectory exists --
    // with a series already published it is how the cadence is changed, and pressing it asks before it replaces --
    // and drawn disabled with its reason where the run wrote no trajectory to sample.
    stopPolling();
    generating = false;
    if (!generate) return;
    generate.hidden = false;
    generate.disabled = false;
    generateNote.textContent = '';
    const holds = await holdsTrajectory(job);
    generate.disabled = !holds;
    if (intervalInput) intervalInput.disabled = !holds;
    generate.title = holds
      ? "Sample moments from this run's own trajectory and publish them as one multi-model file, which this row then "
        + 'plays. That is the snapshots analysis, run against this run.'
      : 'This run wrote no trajectory under stages/, so there are no frames to sample.';
    if (!holds) {
      generateNote.textContent = 'No trajectory in this run: nothing to sample.';
      return;
    }
    const series = published.series || {};
    const cadence = Number(series.interval_ns);
    const fit = series.aligned;
    if (fit && fit.target && alignOnInput) alignOnInput.value = fit.target;
    if (published.frames) {
      // The numbers the decision is about, printed where the reader decides it: how many frames are published, what
      // each one stands for, and whether the series is fitted. Cadence and fit are both the record's own rather than
      // re-derivations here, and the switch follows the series so pressing Generate reproduces what is playing.
      if (fit && alignInput) alignInput.checked = true;
      const rmsd = fit && fit.rmsd_nm ? Number(fit.rmsd_nm.max) : null;
      generateNote.textContent = (Number.isFinite(cadence) && cadence
        ? `Playing ${Number(series.sampled) || '?'} frames at ${cadence} ns per frame`
        : 'A series is published for this run')
        + (fit ? `, fitted on ${fit.target ? `fragment ${fit.target}` : `model ${Number(fit.reference) || 1}`}`
                 + (fit.target ? ` (${Number(fit.atoms) || '?'} of ${Number(fit.of) || '?'} beads)` : '')
                 + (Number.isFinite(rmsd) ? ` — RMSD across the fitted beads up to ${rmsd} nm` : '') + '.'
               : '.')
        + ' Pressing Generate replaces it.';
    } else if (alignInput) {
      alignInput.checked = false;
    }
  }

  function intervalRequested() {
    // `null` is "no cadence asked for", which is the default spread; `undefined` is a value that cannot be read as
    // one. The caller reports those two differently, so they are not folded into a falsy number.
    if (!intervalInput) return null;
    const text = intervalInput.value.trim();
    if (!text) return null;
    const value = Number(text);
    return Number.isFinite(value) && value > 0 ? value : undefined;
  }

  function confirmReplace() {
    // The prompt names what replacing means here: the series the row plays is superseded by a new attempt, and the
    // earlier attempt stays in the run's own analysis tree rather than being deleted. Built here rather than in the
    // template, the way the mapping editor's prompt is, and it resolves rather than deciding.
    return new Promise(resolve => {
      const series = published.series || {};
      const frames = Number(series.sampled), cadence = Number(series.interval_ns);
      const dialog = document.createElement('dialog');
      dialog.className = 'run-view-dialog';
      const title = document.createElement('h3');
      title.textContent = 'Replace this run’s published frame series?';
      const line = document.createElement('p');
      line.textContent = (Number.isFinite(frames) && frames ? `This run already plays ${frames} frames`
                                                           : 'This run already plays a published series')
        + (Number.isFinite(cadence) && cadence ? ` at ${cadence} ns per frame` : ', and its cadence was not recorded')
        + (series.aligned ? `, fitted on ${series.aligned.target ? `fragment ${series.aligned.target}`
                                                              : `model ${Number(series.aligned.reference) || 1}`}`
                          : '') + '.'
        + ' Generating publishes a new series at the cadence you set: this panel plays the newest, and the earlier '
        + "attempt stays in the run's own analysis tree.";
      const actions = document.createElement('div');
      actions.className = 'toolbar';
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.textContent = 'Cancel';
      cancel.addEventListener('click', () => dialog.close('cancel'));
      const replace = document.createElement('button');
      replace.type = 'button';
      replace.textContent = 'Replace';
      replace.addEventListener('click', () => dialog.close('replace'));
      actions.append(cancel, replace);
      dialog.append(title, line, actions);
      document.body.append(dialog);
      dialog.addEventListener('close',
        () => { dialog.remove(); resolve(dialog.returnValue === 'replace'); }, {once: true});
      dialog.showModal();
    });
  }

  async function queueGeneration(job) {
    if (generating) return;
    const requested = intervalRequested();
    if (requested === undefined) {
      generateNote.textContent = 'The cadence must be a positive number of nanoseconds per frame, or blank for the '
        + 'default spread.';
      return;
    }
    if (published.frames && !(await confirmReplace())) return;
    generating = true;
    generate.disabled = true;
    // An empty body is the default spread: each setting is sent only when it was asked for, so a reader who changes
    // nothing queues what the producer's own defaults describe.
    const body = {};
    if (requested !== null) body.interval_ns = requested;
    const aligning = !!(alignInput && alignInput.checked);
    const target = alignOnInput ? String(alignOnInput.value || '') : '';
    if (aligning || target) body.align = true;
    if (aligning && target) body.align_on = target;
    const asked = [requested === null ? null : `a frame every ${requested} ns`,
                   aligning ? (target ? `fitted on fragment ${target}` : 'fitted on the first frame') : null]
      .filter(Boolean).join(', ');
    generateNote.textContent = `Queueing the snapshots analysis${asked ? ' with ' + asked : ''}…`;
    try {
      await post(`/api/jobs/${encodeURIComponent(job.id)}/snapshots`, body);
      generateNote.textContent = asked
        ? `Sampling ${asked} from this run's own trajectory…`
        : "Sampling frames from this run's own trajectory…";
      stopPolling();
      pollTimer = setInterval(() => { watchGeneration(job); }, GENERATE_POLL_MS);
    } catch (error) {
      generating = false;
      generate.disabled = false;
      generateNote.textContent = `The analysis was not queued: ${error.message}`;
    }
  }

  async function watchGeneration(job) {
    // The panel does not guess that the analysis finished: it reads the task list back and reports what the record
    // says, so a failure is named rather than left spinning.
    let tasks = [];
    try {
      tasks = (await api(`/api/jobs/${encodeURIComponent(job.id)}/analyses`)) || [];
    } catch (error) {
      return;   // a page that cannot read the list keeps waiting rather than reporting a failure it did not see
    }
    const mine = tasks.filter(task => task.kind === 'snapshots');
    const newest = mine[mine.length - 1];
    if (!newest) return;
    if (newest.status === 'failed' || newest.status === 'cancelled') {
      stopPolling();
      generating = false;
      generate.disabled = false;
      generateNote.textContent = `The snapshots analysis ${newest.status}: ${newest.error || 'see its own log'}`;
      return;
    }
    if (newest.status === 'completed') {
      stopPolling();
      generateNote.textContent = 'Frames published — re-reading the run.';
      await loadRun(job, {refresh: true});
    }
  }

  if (generate) generate.addEventListener('click', () => { if (selected) queueGeneration(selected); });
  if (alignOnInput) alignOnInput.addEventListener('change', () => {
    // Choosing a fragment *is* asking for a fit: leaving the switch off would queue a setting the panel then shows
    // as unused, and the reader would have to hunt for the other control to make their own choice take effect.
    if (alignOnInput.value && alignInput) alignInput.checked = true;
  });

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

  // The CG chain as segments: which legs are one system, and where the system is rebuilt. A protein-detergent run's
  // film is sampled from one of these (the snapshots analysis reads the run's own layout), so the table is the map of
  // what a player would do -- legs sharing a `group` play as one trajectory, and a change of group is a boundary.
  let segmentsToken = 0;

  async function loadSegments(job) {
    // Every const this function dereferences, guarded together: guarding one of the four is a guard that lets the
    // others throw the moment a page renders without them.
    if (!segmentsWrap || !segmentsTable || !segmentsBody || !segmentsNote) return;
    const token = (segmentsToken += 1);
    segmentsWrap.hidden = true;
    segmentsBody.replaceChildren();
    segmentsNote.textContent = '';
    let answer;
    try {
      answer = await api(`/api/jobs/${encodeURIComponent(job.id)}/trajectory`);
    } catch (error) {
      // The token test comes first here too: a failure that belongs to the run the monitor has already left is that
      // run's failure, and writing it into the next run's panel names an error the reader is not looking at.
      if (token !== segmentsToken) return;
      segmentsTable.hidden = true;
      segmentsWrap.hidden = false;
      segmentsNote.textContent = `The segments could not be read: ${error.message}`;
      return;
    }
    if (token !== segmentsToken) return;   // the monitor moved to another run while this answered
    const rows = (answer && answer.segments) || [];
    const why = (answer && answer.why) || '';
    // The table is a protein-detergent run's: it lists the run's stages, and a single-molecule run has one trajectory
    // rather than a chain of them, so its single row would print a layout role (`cg_trajectory`) in a column headed
    // Stage. "Nothing to play" is a state either run type can be in, so that sentence is kept either way.
    const pdc = Boolean(answer && answer.run_type === 'pdc');
    segmentsTable.hidden = !pdc;
    segmentsWrap.hidden = !(pdc || why);
    if (!pdc || !rows.length) {
      segmentsNote.textContent = why;
      return;
    }
    const boundaries = new Map(((answer.boundaries) || []).map(entry => [entry.at, entry]));
    segmentsBody.replaceChildren(...rows.map(entry => {
      const line = document.createElement('tr');
      // `== null` rather than a falsy test: a merge group of 0 is a group, and a stage that has none is idle for one
      // of two reasons, which the value names instead of folding them into `true`.
      if (entry.group == null) line.dataset.idle = entry.duplicate_of ? 'duplicate' : 'no-trajectory';
      if (boundaries.has(entry.name)) line.dataset.boundary = 'true';
      const note = boundaries.has(entry.name)
        ? `system rebuilt here: ${entry.atoms} atoms, from ${boundaries.get(entry.name).atoms_from}`
        : (entry.duplicate_of ? `the same trajectory as ${entry.duplicate_of}` : (entry.note || ''));
      const texts = [entry.name,
                     entry.atoms == null ? '—' : String(entry.atoms),
                     entry.trajectory ? entry.trajectory.split('/').pop() : 'none',
                     note];
      texts.forEach((text, index) => {
        const cell = document.createElement(index === 0 ? 'th' : 'td');
        if (index === 0) cell.setAttribute('scope', 'row');
        cell.textContent = text;
        line.append(cell);
      });
      return line;
    }));
    // A `group` is a system, not a trajectory: group 1 on the measured run holds four distinct `.xtc` files, so
    // calling it a trajectory contradicts the table under this sentence.
    const systems = new Set(rows.filter(entry => entry.group != null).map(entry => entry.group)).size;
    segmentsNote.textContent = `${rows.length} stage${rows.length === 1 ? '' : 's'} in `
      + `${systems} system${systems === 1 ? '' : 's'}: stages in the same group share one system and play as one; `
      + 'a change of group is where the system is rebuilt.';
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
    // Declared out here, read in here: `body` is scoped to the `try`, and a line after it that reached for
    // `body.superseded` threw a ReferenceError -- which aborted `loadRun` before it drew anything at all.
    let superseded = 0;
    try {
      const body = await api(`/api/jobs/${encodeURIComponent(job.id)}/figures`);
      entries = body.artifacts || [];
      superseded = Number(body.superseded) || 0;
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
    // One set per analysis, not one per attempt: the route answers with what the run currently publishes, and says
    // how many of its own earlier sets it left out -- a reader who wants those can open them in the Runs gallery.
    figuresNote.textContent = `${entries.length} figure${entries.length === 1 ? '' : 's'}, straight from the stages `
      + 'that wrote them, opened inline through the run artifact route.'
      + (superseded ? ` ${superseded} superseded set${superseded === 1 ? '' : 's'} of the same analyses stay in this `
                      + "run's own analysis tree." : '')
      + ' The zoomable, pannable gallery stays in the Runs panel.';
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

  // Reads the fragments the run's own mapping states, for the fit's target: the same document the bead sizes come
  // from, so a fragment means one thing in this panel. `null` is "this run states none", which is not an error --
  // a run without a mapping can only be fitted on the whole molecule.
  async function loadSubunits(job) {
    try {
      const document_ = JSON.parse(await artifactText(job.id, 'stages/2_mapping/model.json'));
      const groups = new Map();
      for (const bead of document_.beads || []) {
        const letter = String(bead.letter || '').trim().toUpperCase();
        const name = String(bead.export_name || bead.name || '').trim();
        if (!letter || !name) continue;
        if (!groups.has(letter)) groups.set(letter, []);
        groups.get(letter).push(name);
      }
      return groups.size ? groups : null;
    } catch (error) {
      return null;
    }
  }

  // The fit's target: one option per fragment the run's own mapping states, plus fitting on everything. Offered
  // only where the run states fragments, and set to whatever the published series was fitted on, so the control
  // agrees with what is playing rather than with what was last clicked.
  function renderAlignTargets() {
    if (!alignOnInput) return;
    const label = alignOnInput.closest('label');
    alignOnInput.replaceChildren();
    const whole = document.createElement('option');
    whole.value = '';
    whole.textContent = 'whole molecule';
    alignOnInput.append(whole);
    for (const [letter, names] of subunits || []) {
      const option = document.createElement('option');
      option.value = letter;
      option.textContent = `${letter} (${names.length} bead${names.length === 1 ? '' : 's'})`;
      alignOnInput.append(option);
    }
    if (label) label.hidden = !subunits;
    const fitted = published.series && published.series.aligned;
    const wanted = fitted && fitted.target ? String(fitted.target) : '';
    alignOnInput.value = wanted;
    if (alignOnInput.value !== wanted) alignOnInput.value = '';   // a target this run no longer states
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
    // The legend is the key to a bead picture, so it appears with one: the family colours are what a coarse-grained
    // file's b-factor column carries, and an all-atom file is drawn in its elements' colours instead.
    if (legend) {
      renderBeadLegend(legend);
      legend.hidden = !coarse;
    }
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
            + "(its own topology file, for the molecule this file holds) — the model's bonds, and the distance "
            + 'guess is off'
          : 'coarse-grained, and this run states no moleculetype for the molecule this file holds, so the picture '
            + 'claims no bonds rather than guessing them'};
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
      // table and the one call, so this view draws the same beads as Complexes and the bead editor. The display
      // scale is this panel's own and stated at the call -- `BEAD_SCALE`, 0.3 -- and it multiplies the table's
      // radius on the way onto the structure, which is the value the readout below reports back.
      applyBeadRadii(component.structure, {scale: BEAD_SCALE, sizeOf: atom => {
        const named = sizeClasses && sizeClasses[String(atom.atomname || '').trim().toUpperCase()];
        return named || sizeClassOf(atom);
      }});
      // The colour is the bead's own type family, from the code `pdc_view.system_pdb` writes in the b-factor column
      // of the structure this panel serves (`ngl-beads.js` is the one table); a file that carries none draws every
      // bead as family-not-stated rather than as the first family.
      component.addRepresentation('ball+stick', {...BEAD_RADIUS_PARAMETERS, ...BEAD_FAMILY_PARAMETERS});
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
        ? (sizeClasses
            ? `the run's own stages/2_mapping/model.json size classes, drawn at ${BEAD_SCALE}x`
            : 'uniform — no readable size class')
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
    const rowHost = $(id('run-view-transport'));
    const reverse = $(id('run-view-reverse')), forward = $(id('run-view-forward'));
    const slider = $(id('run-view-frame')), frameReadout = $(id('run-view-frame-readout'));
    const note = $(id('run-view-transport-note'));
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

  // The panel's own two traps, kept. Playback is driven by `requestAnimationFrame`, so a panel that is not the open
  // one -- or a page that is itself hidden -- advances zero frames while still claiming to play; the row pauses
  // rather than return to a stale picture. And the stage has to be told to re-measure, because NGL measures its host
  // once: a monitor created at 1600 px keeps a 792 px canvas inside a 330 px column, which is what pushes the whole
  // document sideways at 390 px.
  window.addEventListener('resize', () => { stage?.handleResize(); });
  document.addEventListener('dashboard:tab', event => {
    stage?.handleResize();
    if (event.detail && event.detail.id !== panelIds()['run-view']) transport.pause();
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) transport.pause(); });

  // The moments strip follows the transport, so the pressed moment is the frame on screen rather than the one that
  // was clicked last. This is the panel's own wiring, kept: it is what makes the strip a control.
  transport.onFrame(frame => {
    strip.querySelectorAll('button').forEach(button => {
      button.setAttribute('aria-pressed', String(
        button.dataset.frame !== '' && Number(button.dataset.frame) === transport.frameNow()));
    });
    if (onFrame) onFrame(frame, selected);
  });

  return {
    root, side, slider, transport, legend, chooser: combo,
    run: () => selected,
    series: () => published,
    status: text => { status.textContent = text; },
    // The nanosecond a frame stands for, and the way to seek one: this is what the time link between two monitors
    // works in, because two series rarely share a cadence -- frame 40 on one side is not the same moment as frame
    // 40 on the other, while 40 ns is 40 ns.
    nanosecondOf: frame => {
      const cadence = published.series ? Number(published.series.interval_ns) : 0;
      return cadence ? Number(frame) * cadence : null;
    },
    frameFor: ns => {
      const cadence = published.series ? Number(published.series.interval_ns) : 0;
      return cadence ? Math.round(Number(ns) / cadence) : null;
    },
    seek: frame => {
      if (!slider || slider.disabled) return;
      const most = Number(slider.max) || 0;
      slider.value = String(Math.max(0, Math.min(most, Number(frame) || 0)));
      slider.dispatchEvent(new Event('input', {bubbles: true}));
    },
    loadRun: job => { selected = job; combo.set(job); return loadRun(job); },
    // For a run the workspace's own list does not hold -- a link from the Runs table to a run of another
    // workspace -- the monitor still draws it, and this is what says so where the identity line is.
    identify: text => { identity.textContent = text; },
  };
}
