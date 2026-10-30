// The Trajectory block of one Run view monitor: the frames an analysis has built from the selected segment, played on
// the canvas, and the arguments a fresh build takes.
//
// Two facts decide the shape of this module.
//
// **The viewer cannot read a trajectory.** This vendored NGL has no XTC/TRR parser (`grep -c XTC ngl.js` = 0), so
// playback is a server-written multi-model PDB. That file is big -- roughly 0.9 MB a model for an 11,708-atom system,
// which is 110 MB at 120 models -- and a run cannot count its own frames cheaply (43 s for a 2.6 GB xtc through
// `gmx check`). So it is fetched when the reader presses Play and never on mount. The small `frames.json` beside it
// is what the summary and the time readout are read from, and fetching that is cheap.
//
// **One trajectory at a time.** A run's system can be rebuilt mid-run (a protein-detergent run removes detergents and
// re-solvates what is left), so the segments of `/api/jobs/<id>/trajectory` are not one file. The block plays the
// selected segment's series; the structure picture stays a separate component, hidden while a series is on the stage
// and never destroyed by this module.
//
// Every id in here is suffixed by `side`, because two monitors sit side by side in one page (see
// `run-view-monitor.js`). The ids are written here, once: the monitor only inserts `trajectoryMarkup(side)`.
//
// The trap this block shares with the segment table is the token. A reader can pick another run, or another segment,
// while a fetch is in flight; an answer that belongs to the row they left must write nothing. `runToken` separates
// runs, `formToken` separates arguments, `loading` separates series files.
import { api } from './shared.js';
import { isCoarseGrained } from './run-view-structure.js';

//: The nine keys a frame-series attempt records its arguments under -- the form, the lookup for an existing attempt
//: and the POST body are all this one list, so a key cannot be added to one of them and forgotten in another.
const ARGS = ['trajectory', 'structure', 'start_ns', 'end_ns', 'stride', 'fit', 'fragment', 'atoms', 'assembled'];

//: One times speed: ten frames a second, the rate nglview's own Play uses and the one a reader can follow. A speed of
//: 2 halves the frame interval and 0.5 doubles it; it is the interval, not a multiplier of anything else.
const FRAME_MS = 100;

//: How often a queued build is asked whether it has finished. `window.__runViewPollMs` is the one test seam, the way
//: `bonded-parameterization.js` has one: the browser tier must not wait seconds for a poll it is asserting about.
const POLL_MS = 2000;

//: The server's own cap on one attempt, stated to the reader rather than re-checked here: the panel cannot count the
//: trajectory's frames, so it cannot know whether a step is too small -- a hint that pretended otherwise would print
//: a wrong estimate as a fact.
const MAX_MODELS = 240;

//: Where a run's mapping states which beads make up which fragment. Read lazily, when the form is opened: a run with
//: no mapping answers 404, and that is "no fragments to fit on", not a failure of the panel.
const MAPPING = 'stages/2_mapping/model.json';

const pollMilliseconds = () => Number(window.__runViewPollMs) || POLL_MS;

//: A build is queued under the job lock and the server fingerprints the chosen trajectory before it answers -- 5.8 s
//: for a live 2.5 GB `.xtc`, measured, and worse on a cold cache. The shared `api()` client caps every request at ten
//: seconds and combines that with any signal using the shorter one, so this request carries its own, longer timeout;
//: without it a queued build would be reported as refused while it was in fact running.
const BUILD_TIMEOUT_MS = 120000;

async function queueBuild(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(BUILD_TIMEOUT_MS),
  });
  const type = response.headers.get('content-type') || '';
  const data = type.includes('json') ? await response.json() : {error: `Request failed (${response.status})`};
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

// The block, above the segment table. A group rather than a form region: the controls act on the canvas beside them,
// and the recompute form inside it is its own `<form>`.
export function trajectoryMarkup(side) {
  const id = name => `${name}-${side}`;
  return `
    <div class="card run-view-trajectory" role="group" aria-labelledby="${id('run-view-trajectory-title')}">
      <h3 class="run-view-trajectory-title" id="${id('run-view-trajectory-title')}">Trajectory</h3>
      <p class="hint run-view-trajectory-note" id="${id('run-view-trajectory-note')}" role="status"
         >Choose a run to play its trajectory.</p>
      <div class="run-view-trajectory-pick">
        <label for="${id('run-view-segment')}">Segment</label>
        <select id="${id('run-view-segment')}" disabled></select>
        <button type="button" id="${id('run-view-build')}" disabled>Recompute frames</button>
      </div>
      <p class="run-view-series" id="${id('run-view-series')}" aria-live="polite"></p>
      <div class="transport-controls" role="group" aria-label="Playback">
        <button type="button" id="${id('run-view-play')}" aria-pressed="false" disabled>Play</button>
        <button type="button" id="${id('run-view-step-back')}" aria-label="One frame back" disabled>−1</button>
        <button type="button" id="${id('run-view-step-forward')}" aria-label="One frame forward" disabled>+1</button>
        <label class="transport-frame">Frame
          <input type="range" id="${id('run-view-frame')}" min="0" max="0" step="1" value="0"
                 aria-describedby="${id('run-view-time')}" disabled>
        </label>
        <label>Speed
          <select id="${id('run-view-speed')}">
            <option value="0.5">0.5×</option>
            <option value="1" selected>1×</option>
            <option value="2">2×</option>
          </select>
        </label>
        <label class="transport-loop"><input type="checkbox" id="${id('run-view-loop')}"> Loop</label>
        <span class="run-view-time" id="${id('run-view-time')}">t = — ns · model 0/0</span>
      </div>
      <details class="run-view-recompute" id="${id('run-view-recompute')}">
        <summary>Frame arguments</summary>
        <form id="${id('run-view-form')}">
          <div class="run-view-form-grid">
            <label for="${id('run-view-form-atoms')}">Atoms
              <select id="${id('run-view-form-atoms')}">
                <option value="all">all atoms (water left out)</option>
                <option value="beads">beads only</option>
                <option value="ca">CA atoms only</option>
              </select>
            </label>
            <label for="${id('run-view-form-fit')}">Fit
              <select id="${id('run-view-form-fit')}">
                <option value="none">none</option>
                <option value="protein">protein</option>
              </select>
            </label>
            <label for="${id('run-view-form-fragment')}" id="${id('run-view-form-fragment-label')}" hidden>Fragment
              <select id="${id('run-view-form-fragment')}" hidden></select>
            </label>
            <label for="${id('run-view-form-start')}">Start (ns)
              <input type="number" id="${id('run-view-form-start')}" min="0" step="any" placeholder="whole file">
            </label>
            <label for="${id('run-view-form-end')}">End (ns)
              <input type="number" id="${id('run-view-form-end')}" min="0" step="any" placeholder="whole file">
            </label>
            <label for="${id('run-view-form-stride')}">Step (frames)
              <input type="number" id="${id('run-view-form-stride')}" min="1" step="1" placeholder="auto">
            </label>
            <label class="run-view-form-check" for="${id('run-view-form-assembled')}">
              <input type="checkbox" id="${id('run-view-form-assembled')}"> Assemble
            </label>
          </div>
          <div class="run-view-form-actions">
            <button type="submit" id="${id('run-view-submit')}" disabled>Build frames</button>
            <span class="hint" id="${id('run-view-form-note')}"></span>
          </div>
        </form>
        <p class="hint">The server caps one build at ${MAX_MODELS} models and about 250 MB, and refuses a bigger one.
          This panel does not count the trajectory's frames -- counting a 2.6 GB file takes about a minute -- so it
          cannot predict a build's size. A blank step aims at roughly 120 models; a blank start and end mean the
          whole file. Changing a control here is what makes the build a new attempt; a matching one already built is
          reused and shown instead.</p>
      </details>
    </div>`;
}

//: The arguments a segment is built from when nothing has been chosen: beads for a coarse-grained trajectory (its
//: atoms are beads), everything for an atomistic one, no fit, no bounds, no assembly.
export function defaultArguments(entry, runType) {
  return {
    trajectory: entry.trajectory,
    structure: entry.structure || null,
    start_ns: null,
    end_ns: null,
    stride: null,
    fit: 'none',
    fragment: null,
    atoms: isCoarseGrained(entry.trajectory, runType) ? 'beads' : 'all',
    assembled: false,
  };
}

//: A payload as the nine arguments, with a key the record does not hold read as `null` -- which is what the lookup
//: compares, so an attempt recorded by an older form is not silently taken for a match.
function recordedArguments(payload) {
  const args = {};
  for (const key of ARGS) args[key] = payload && payload[key] != null ? payload[key] : null;
  return args;
}

function sameArguments(left, right) {
  return ARGS.every(key => (left[key] ?? null) === (right[key] ?? null));
}

//: The newest matching attempt of this kind in a status. The list is in append order, so the last match is the newest
//: -- which is what "the newest attempt whose args equal the form" means, without a second server route for it.
function newest(tasks, statuses, args) {
  let found = null;
  for (const task of tasks) {
    if (!task || task.kind !== 'frame-series') continue;
    if (!statuses.includes(task.status)) continue;
    if (!sameArguments(recordedArguments(task.payload), args)) continue;
    found = task;
  }
  return found;
}

const outputNamed = (task, name) => (task.outputs || [])
  .find(path => String(path) === name || String(path).endsWith('/' + name)) || null;

//: A number a reader typed, or `null` for a blank field: a blank is the server's "default this", never a zero.
const numberOrNull = text => {
  const raw = String(text == null ? '' : text).trim();
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
};

//: Four significant digits, because a time can be 0.00002 ns (a 20 fs CG frame) or 95.5 ns, and a fixed number of
//: decimals gets one of the two wrong.
const nsText = value => {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return String(Number(number.toPrecision(4)));
};

const ordinal = number => {
  const whole = Math.abs(Math.round(Number(number) || 0));
  const tens = whole % 100;
  if (tens >= 11 && tens <= 13) return `${whole}th`;
  return `${whole}${{1: 'st', 2: 'nd', 3: 'rd'}[whole % 10] || 'th'}`;
};

const megabytes = bytes => {
  const number = Number(bytes);
  if (!Number.isFinite(number) || number <= 0) return '';
  return `${(number / (1024 * 1024)).toFixed(number >= 100 * 1024 * 1024 ? 0 : 1)} MB`;
};

//: The build, in words: what it was built from, at what step, of what, aligned on what. A sentence rather than a
//: second table of the recorded arguments -- the reader already chose those, and this is the one line to quote.
function buildSentence(args, entry) {
  const parts = [`Built from ${entry.name}`];
  parts.push(args.stride == null ? 'at a stride the server chose' : `every ${ordinal(args.stride)} frame`);
  if (args.start_ns != null || args.end_ns != null) {
    parts.push(`${args.start_ns == null ? 'the start' : `${nsText(args.start_ns)} ns`}`
      + `–${args.end_ns == null ? 'the end' : `${nsText(args.end_ns)} ns`}`);
  }
  parts.push(args.atoms === 'beads' ? 'beads only'
    : (args.atoms === 'ca' ? 'CA atoms only' : 'all atoms (water left out)'));
  if (args.fit === 'protein') parts.push('aligned on the protein');
  else if (args.fit === 'beads') parts.push(`aligned on fragment ${args.fragment}`);
  if (args.assembled) parts.push('assembled');
  return parts.join(', ');
}

//: What a series holds, from the record of the build and the file it published: models, cadence, timespan and size --
//: all read off `frames.json` rather than counted by anything here.
function seriesSentence(args, entry, frames) {
  const times = Array.isArray(frames.times_ns) ? frames.times_ns : [];
  const models = Number(frames.models) || times.length;
  const pieces = [`${models} model${models === 1 ? '' : 's'}`];
  const cadence = Number(frames.cadence_ns);
  if (cadence > 0) pieces.push(`one every ${nsText(cadence)} ns`);
  if (times.length > 1) pieces.push(`${nsText(times[0])}–${nsText(times[times.length - 1])} ns`);
  const bytes = megabytes(frames.bytes);
  if (bytes) pieces.push(bytes);
  return `${buildSentence(args, entry)}. It holds ${pieces.join(', ')}.`;
}

function nearestIndex(times, ns) {
  if (ns == null || !Array.isArray(times) || !times.length) return 0;
  let best = 0;
  let gap = Infinity;
  times.forEach((time, index) => {
    const value = Number(time);
    if (!Number.isFinite(value)) return;
    const distance = Math.abs(value - Number(ns));
    if (distance < gap) { gap = distance; best = index; }
  });
  return best;
}

export function createTrajectory({root, side, stageOf, artifactText, decorate}) {
  const id = name => `#${name}-${side}`;
  const $ = selector => root.querySelector(selector);
  const note = $(id('run-view-trajectory-note'));
  const pick = $(id('run-view-segment'));
  const buildButton = $(id('run-view-build'));
  const seriesLine = $(id('run-view-series'));
  const playButton = $(id('run-view-play'));
  const backButton = $(id('run-view-step-back'));
  const forwardButton = $(id('run-view-step-forward'));
  const slider = $(id('run-view-frame'));
  const speedSelect = $(id('run-view-speed'));
  const loopBox = $(id('run-view-loop'));
  const timeLine = $(id('run-view-time'));
  const recompute = $(id('run-view-recompute'));
  const form = $(id('run-view-form'));
  const atomsPick = $(id('run-view-form-atoms'));
  const fitPick = $(id('run-view-form-fit'));
  const fragmentPick = $(id('run-view-form-fragment'));
  const fragmentLabel = $(id('run-view-form-fragment-label'));
  const startInput = $(id('run-view-form-start'));
  const endInput = $(id('run-view-form-end'));
  const strideInput = $(id('run-view-form-stride'));
  const assembleBox = $(id('run-view-form-assembled'));
  const submitButton = $(id('run-view-submit'));
  const formNote = $(id('run-view-form-note'));

  let job = null;
  let answer = null;
  let playable = [];
  let tasks = [];
  let tasksLoaded = false;
  let runToken = 0;               // the run this block holds; every answer is checked against it
  let formToken = 0;              // the arguments a fetch was started for
  let loading = 0;                // the series file a load was started for
  let series = null;              // {component, trajectory, models, frames, args, entry, times}
  let current = null;             // the attempt the block says it is showing: {task, entry, frames, pdbPath, args, times}
  let structureComponent = null;  // the picture this block hides while a series is on the stage
  let player = null;
  let timer = null;               // the build poll
  let fragments = null;           // {letter: [bead names]}, once asked for; `null` means "not asked yet"
  let fragmentsPending = null;    // the read in flight, so two openings of the form fetch the mapping once
  let fragmentsToken = 0;
  let lastNs = null;              // the moment on screen, so a rebuilt series opens at the same place

  // ---------------------------------------------------------------------------------------------- the block's states

  const setNote = text => { note.textContent = text || ''; };
  const setFormNote = text => { formNote.textContent = text || ''; };

  function setSeekable(on) {
    slider.disabled = !on;
    backButton.disabled = !on;
    forwardButton.disabled = !on;
  }

  function writeTime(index, models) {
    const times = (series && series.times) || [];
    const value = models > 0 ? times[index] : undefined;
    timeLine.textContent = `t = ${models > 0 ? nsText(value) : '—'} ns · model `
      + `${models > 0 ? index + 1 : 0}/${models}`;
  }

  // The one reader of the player's state: the slider, the readout and the button's own label all follow it, so no
  // second copy of "which frame is on screen" can disagree with the component the viewer is drawing.
  function sync() {
    const trajectory = series && series.trajectory;
    const models = series ? series.models : 0;
    const at = trajectory && trajectory.currentFrame >= 0 ? trajectory.currentFrame : 0;
    const index = models ? Math.max(0, Math.min(at, models - 1)) : 0;
    slider.max = String(Math.max(0, models - 1));
    slider.value = String(index);
    const playing = !!(player && player.isRunning);
    playButton.textContent = playing ? 'Pause' : 'Play';
    playButton.setAttribute('aria-pressed', String(playing));
    writeTime(index, models);
    if (models && series.times && Number.isFinite(Number(series.times[index]))) {
      lastNs = Number(series.times[index]);
    }
  }

  function pause() {
    if (player) player.pause();
    player = null;
  }

  // The series component leaves the stage; the structure component stays and is shown again. Called when the reader
  // changes the run, the segment or the arguments, and -- with `keepStage` -- before the monitor replaces the stage's
  // whole contents, where removing the component here would be work done twice and a disposed trajectory twice told.
  function discardSeries({keepStage = false} = {}) {
    loading += 1;
    pause();
    if (series) {
      if (!keepStage && series.component) {
        const stage = stageOf();
        if (stage) stage.removeComponent(series.component);
      }
      if (structureComponent) structureComponent.setVisibility(true);
      series = null;
    }
    if (!keepStage) {
      // The attempt on the stage is gone, so the attempt the block claims is gone with it: Play must not reload a
      // series the form no longer describes.
      current = null;
      playButton.disabled = true;
    }
    slider.max = '0';
    slider.value = '0';
    setSeekable(false);
    sync();
  }

  // -------------------------------------------------------------------------------------------------- the segments

  function entryNow() {
    const index = Number(pick.value);
    return playable[Number.isInteger(index) && index >= 0 ? index : 0] || null;
  }

  // The segment control: the playable segments only (a copy of another segment's trajectory is not a place to play
  // twice), defaulting to the last one, which is the run's latest system. Names are the server's own.
  function renderSegments() {
    pick.replaceChildren(...playable.map((entry, index) => {
      const option = document.createElement('option');
      option.value = String(index);
      option.textContent = entry.name + (Number(entry.atoms) > 0 ? ` · ${Number(entry.atoms)} atoms` : '');
      return option;
    }));
    pick.disabled = !playable.length;
    if (playable.length) pick.value = String(playable.length - 1);
  }

  // The arguments the form holds now: what a submit sends, and what a series is looked up by.
  function formArguments(entry) {
    const fit = fitPick.value;
    return {
      trajectory: entry.trajectory,
      structure: entry.structure || null,
      start_ns: numberOrNull(startInput.value),
      end_ns: numberOrNull(endInput.value),
      stride: numberOrNull(strideInput.value),
      fit,
      fragment: fit === 'beads' ? (fragmentPick.value || null) : null,
      atoms: atomsPick.value,
      assembled: assembleBox.checked,
    };
  }

  function fillForm(args) {
    atomsPick.value = ['all', 'beads', 'ca'].includes(args.atoms) ? args.atoms : 'all';
    if (args.fit === 'beads') offerBeads(true);
    fitPick.value = ['none', 'protein', 'beads'].includes(args.fit) ? args.fit : 'none';
    showFragmentRow(fitPick.value === 'beads');
    if (fitPick.value === 'beads' && args.fragment
        && ![...fragmentPick.options].some(option => option.value === args.fragment)) {
      const option = document.createElement('option');
      option.value = args.fragment;
      option.textContent = args.fragment;
      fragmentPick.append(option);
    }
    if (fitPick.value === 'beads') fragmentPick.value = args.fragment || '';
    startInput.value = args.start_ns == null ? '' : String(args.start_ns);
    endInput.value = args.end_ns == null ? '' : String(args.end_ns);
    strideInput.value = args.stride == null ? '' : String(args.stride);
    assembleBox.checked = !!args.assembled;
  }

  function showFragmentRow(on) {
    fragmentLabel.hidden = !on;
    fragmentPick.hidden = !on;
  }

  // `beads` is an option of the fit select only where the run's mapping states fragments: a fit that names no
  // fragment is a request the server refuses, and offering a select that can only be refused is worse than no select.
  function offerBeads(on) {
    const found = [...fitPick.options].find(option => option.value === 'beads');
    if (on && !found) {
      const option = document.createElement('option');
      option.value = 'beads';
      option.textContent = 'beads (aligned on a fragment)';
      fitPick.append(option);
    } else if (!on && found) {
      found.remove();
    }
  }

  function setFragmentOptions(letters) {
    fragmentPick.replaceChildren(...letters.map(letter => {
      const option = document.createElement('option');
      option.value = letter;
      const beads = (fragments && fragments[letter]) || [];
      option.textContent = beads.length ? `${letter} — ${beads.join(', ')}` : letter;
      return option;
    }));
  }

  // The mapping is read when the form is first opened, not on mount: a run whose mapping is missing answers 404, and
  // that is a state -- no fragments to fit on -- rather than a failure of the panel.
  async function loadFragments() {
    if (fragments !== null || !job) return fragments || {};
    // One read for one click: the Build button opens the form and the `<details>`' own toggle event fires with it, and
    // two callers asking at once would fetch the mapping twice.
    if (fragmentsPending) return fragmentsPending;
    const runId = job.id;
    fragmentsPending = (async () => {
      const token = (fragmentsToken += 1);
      let found = {};
      try {
        const document_ = JSON.parse(await artifactText(runId, MAPPING));
        for (const bead of document_.beads || []) {
          const letter = String(bead.letter || '').trim().toUpperCase();
          const name = String(bead.export_name || bead.name || '').trim();
          if (letter && name) (found[letter] = found[letter] || []).push(name);
        }
      } catch (error) {
        found = {};
      }
      if (token !== fragmentsToken || !job || job.id !== runId) return {};
      fragments = found;
      const letters = Object.keys(found).sort();
      offerBeads(letters.length > 0);
      setFragmentOptions(letters);
      if (!letters.length) {
        showFragmentRow(false);
        if (fitPick.value === 'beads') fitPick.value = 'none';
      }
      return fragments;
    })();
    try {
      return await fragmentsPending;
    } finally {
      fragmentsPending = null;
    }
  }

  // ------------------------------------------------------------------------------------------------ the attempt

  // The submit button's own state: a bead fit without a fragment cannot be sent, and neither can an attempt the run is
  // already building -- pressing it again would queue a second copy of the same work.
  function updateSubmit() {
    const entry = entryNow();
    if (!job || !entry) {
      submitButton.disabled = true;
      return;
    }
    const args = formArguments(entry);
    const needsFragment = args.fit === 'beads' && !args.fragment;
    const inflight = newest(tasks, ['queued', 'running'], args);
    submitButton.disabled = needsFragment || !!inflight;
    if (needsFragment) setFormNote('A bead fit needs a fragment to align on.');
    else if (inflight) setFormNote(`This build is ${inflight.status}. The button waits for it.`);
  }

  function clearPoll() {
    if (timer) clearTimeout(timer);
    timer = null;
  }

  // One timer, and only while a build is in flight: a settled attempt has nothing left to ask about. It is re-armed
  // from `selectSeries`, so the poll stops by itself on the answer that settles the attempt.
  function ensurePolling() {
    if (timer || !job) return;
    const token = runToken;
    timer = setTimeout(async () => {
      timer = null;
      if (token !== runToken) return;
      await loadTasks(token);
    }, pollMilliseconds());
  }

  async function loadTasks(token) {
    const runId = job && job.id;
    if (!runId) return;
    let list;
    try {
      list = await api(`/api/jobs/${encodeURIComponent(runId)}/analyses`);
    } catch (error) {
      if (token !== runToken) return;
      tasksLoaded = true;
      setNote(`This run's analyses could not be read: ${error.message}`);
      return;
    }
    if (token !== runToken) return;
    tasks = Array.isArray(list) ? list : [];
    tasksLoaded = true;
    await selectSeries();
  }

  // What the block shows for the arguments the form holds: the newest completed attempt with those arguments, or the
  // attempt the run is building, or the one that failed with them, or the plain fact that none exists yet.
  async function selectSeries({prefill = false} = {}) {
    const token = (formToken += 1);
    if (!job) return;
    const entry = entryNow();
    if (!entry) {
      discardSeries();
      seriesLine.textContent = '';
      setNote((answer && answer.why) || 'This run offers no trajectory to play.');
      playButton.disabled = true;
      return;
    }
    discardSeries();
    if (prefill) fillForm(defaultArguments(entry, job.run_type));
    const args = formArguments(entry);
    if (!tasksLoaded) {
      // The analyses have not answered yet; saying "none built" here and taking it back a moment later is a flicker
      // that reads as a failed build.
      setNote('Reading this run\'s analyses…');
      playButton.disabled = true;
      return;
    }
    const inflight = newest(tasks, ['queued', 'running'], args);
    const completed = newest(tasks, ['completed'], args);
    const failed = newest(tasks, ['failed', 'cancelled'], args);
    if (inflight) {
      seriesLine.textContent = '';
      setNote(`Building frames from ${entry.name}. This page asks again until the attempt settles.`);
      playButton.disabled = true;
      updateSubmit();
      ensurePolling();
      return;
    }
    if (completed) {
      await showSeries(completed, entry, token, prefill);
      return;
    }
    seriesLine.textContent = '';
    if (failed) {
      await showFailure(failed, entry, token);
      return;
    }
    setNote('');
    seriesLine.textContent = `No frames have been built from ${entry.name} with these arguments yet.`;
    playButton.disabled = true;
    updateSubmit();
  }

  async function showSeries(task, entry, token, prefill) {
    const framesPath = outputNamed(task, 'frames.json');
    const pdbPath = outputNamed(task, 'run-frames.pdb');
    if (!framesPath || !pdbPath) {
      if (token !== formToken) return;
      seriesLine.textContent = '';
      setNote(`The build recorded no frames file, so there is nothing to play. Its record is ${task.directory || '—'}.`);
      playButton.disabled = true;
      updateSubmit();
      return;
    }
    let frames;
    try {
      frames = JSON.parse(await artifactText(job.id, framesPath));
    } catch (error) {
      if (token !== formToken) return;
      seriesLine.textContent = '';
      setNote(`The frames of ${entry.name} could not be read: ${error.message}`);
      playButton.disabled = true;
      updateSubmit();
      return;
    }
    if (token !== formToken) return;
    const args = recordedArguments(task.payload);
    const times = Array.isArray(frames.times_ns) ? frames.times_ns : [];
    current = {task, entry, frames, pdbPath, args, times};
    // A series is older than the trajectory when the digest the build recorded is not the one the segment reports
    // now. Only compared when both sides state one: an older answer states neither, and calling that stale would
    // accuse a file nothing has changed.
    const stale = entry.identity && frames.trajectory_identity
      && String(frames.trajectory_identity) !== String(entry.identity);
    seriesLine.textContent = (stale
      ? 'This series was built from an older copy of the segment\'s trajectory, so it may not show what the run '
        + 'holds now. ' : '') + seriesSentence(args, entry, frames);
    setNote(stale ? 'Recompute frames to rebuild it from the trajectory on disk.' : '');
    playButton.disabled = false;
    if (prefill) {
      if (args.fit === 'beads') await loadFragments();
      if (token !== formToken) return;
      fillForm(args);
    }
    updateSubmit();
  }

  async function showFailure(task, entry, token) {
    let log = '';
    if (task.directory) {
      try {
        log = await artifactText(job.id, `${task.directory}/console.log`);
      } catch (error) {
        log = '';
      }
    }
    if (token !== formToken) return;
    const lines = String(log).split('\n').map(line => line.trimEnd()).filter(line => line.trim());
    const tail = lines.slice(-8).join('\n');
    seriesLine.textContent = '';
    setNote(`The build from ${entry.name} ${task.status}${task.error ? `: ${task.error}` : '.'}`
      + (tail ? ` Its log ends:\n${tail}` : ''));
    playButton.disabled = true;
    updateSubmit();
  }

  // ---------------------------------------------------------------------------------------------------- the player

  const frameTimeout = () => FRAME_MS / (Number(speedSelect.value) || 1);

  // A series is loaded on Play and not before: the PDB is the large half of a build. Returns whether there is a
  // trajectory to play afterwards.
  async function ensureLoaded() {
    if (!job || !current) return false;
    if (series) return true;
    const token = (loading += 1);
    const context = current;
    const entry = context.entry;
    setNote('Loading the frames…');
    let text;
    try {
      text = await artifactText(job.id, context.pdbPath);
    } catch (error) {
      if (token !== loading) return false;
      setNote(`The frames could not be read: ${error.message}`);
      return false;
    }
    if (token !== loading) return false;
    const renderer = stageOf();
    if (!renderer) {
      setNote('This page could not start a 3D view, so the frames cannot be drawn here.');
      return false;
    }
    let component;
    try {
      // `asTrajectory` is what makes this build's PDB parser collect a multi-model file's frames: without it every
      // `MODEL` after the first is read as coordinates of the same structure and `addTrajectory()` gets no frame at
      // all. It does not attach the trajectory itself -- `addTrajectory()` below is what creates one.
      component = await renderer.loadFile(new Blob([text], {type: 'text/plain'}),
                                          {ext: 'pdb', inferBonds: 'none', asTrajectory: true});
    } catch (error) {
      if (token !== loading) return false;
      setNote(`The frames did not load in the viewer: ${error.message}`);
      return false;
    }
    if (token !== loading) {
      // The reader moved to another run or another segment while the file was parsing: the component must not stay on
      // a stage that now belongs to something else.
      renderer.removeComponent(component);
      return false;
    }
    // A multi-model PDB loaded without `asTrajectory` comes back as one structure holding every model's atoms and no
    // trajectory at all, and `loadFile` does not attach one by itself -- `component.addTrajectory()` is what creates
    // it. A block built on the assumption that the trajectory is there renders a plausible picture and a dead slider.
    if (!component.trajList || !component.trajList.length) component.addTrajectory();
    const element = component.trajList && component.trajList[0];
    const trajectory = element ? element.trajectory : null;
    const models = trajectory ? Number(trajectory.frameCount) : 0;
    if (!trajectory || models < 1) {
      renderer.removeComponent(component);
      setNote('The frames file holds no model this viewer can step through.');
      return false;
    }
    decorate(component, isCoarseGrained(entry.trajectory, job.run_type));
    component.autoView();
    // The structure component is kept, not replaced: one picture of one system at a time, and the reader's place in
    // the table below is the structure's own. It is shown again when the series leaves the stage.
    if (structureComponent) structureComponent.setVisibility(false);
    series = {component, trajectory, models, frames: context.frames, args: context.args, entry, times: context.times};
    player = new NGL.TrajectoryPlayer(trajectory, {
      step: 1, timeout: frameTimeout(), start: 0, end: models - 1,
      mode: loopBox.checked ? 'loop' : 'once', direction: 'forward'});
    element.signals.frameChanged.add(() => sync());
    trajectory.setFrame(nearestIndex(series.times, lastNs));
    setSeekable(models > 1);
    setNote(models > 1 ? '' : 'This series holds one model, so there is nothing to step through.');
    sync();
    return true;
  }

  function seek(index) {
    if (!series || !series.trajectory) return;
    if (player) player.pause();
    const target = Math.max(0, Math.min(series.models - 1, Number(index) || 0));
    series.trajectory.setFrame(target);
    sync();
  }

  async function onPlay() {
    if (!current) return;
    if (player && player.isRunning) {
      player.pause();
      sync();
      return;
    }
    if (!series) {
      playButton.disabled = true;
      const loaded = await ensureLoaded();
      if (!loaded) {
        playButton.disabled = !current;
        return;
      }
    }
    if (!player) return;
    player.play();
    playButton.disabled = false;
    sync();
  }

  // ----------------------------------------------------------------------------------------------------- submit

  async function submit() {
    const entry = entryNow();
    if (!job || !entry) return;
    const args = formArguments(entry);
    if (args.fit === 'beads' && !args.fragment) {
      setFormNote('A bead fit needs a fragment to align on.');
      return;
    }
    const token = runToken;
    submitButton.disabled = true;
    setFormNote('Queuing the build…');
    try {
      await queueBuild(`/api/jobs/${encodeURIComponent(job.id)}/frame-series`, args);
    } catch (error) {
      if (token !== runToken) return;
      setFormNote(`The build was refused: ${error.message}`);
      updateSubmit();
      return;
    }
    if (token !== runToken) return;
    setFormNote('Building… this page asks again until the attempt settles.');
    await loadTasks(token);
  }

  // ----------------------------------------------------------------------------------------------------- wiring

  pick.addEventListener('change', () => {
    selectSeries({prefill: true});
  });

  buildButton.addEventListener('click', () => {
    recompute.open = true;
    loadFragments();
    atomsPick.focus();
  });

  recompute.addEventListener('toggle', () => {
    if (recompute.open) loadFragments();
  });

  for (const element of [startInput, endInput, strideInput]) {
    element.addEventListener('change', () => {
      updateSubmit();
      selectSeries();
    });
  }
  for (const element of [atomsPick, fragmentPick, assembleBox]) {
    element.addEventListener('change', () => {
      updateSubmit();
      selectSeries();
    });
  }
  fitPick.addEventListener('change', async () => {
    if (fitPick.value === 'beads') {
      await loadFragments();
      if (fragments && !Object.keys(fragments).length) {
        offerBeads(false);
        fitPick.value = 'none';
      }
    }
    showFragmentRow(fitPick.value === 'beads');
    updateSubmit();
    selectSeries();
  });

  form.addEventListener('submit', event => {
    event.preventDefault();
    submit();
  });

  playButton.addEventListener('click', () => {
    onPlay().catch(error => setNote(`Playback could not start: ${error.message}`));
  });
  backButton.addEventListener('click', () => seek((series ? series.trajectory.currentFrame : 0) - 1));
  forwardButton.addEventListener('click', () => seek((series ? series.trajectory.currentFrame : 0) + 1));
  slider.addEventListener('input', () => seek(Number(slider.value)));
  speedSelect.addEventListener('change', () => {
    if (player) player.setParameters({timeout: frameTimeout()});
  });
  loopBox.addEventListener('change', () => {
    if (player) player.setParameters({mode: loopBox.checked ? 'loop' : 'once'});
  });

  return {
    // A new run. Everything a fetch could still be carrying now belongs to a run this block no longer holds.
    reset() {
      runToken += 1;
      formToken += 1;
      fragmentsToken += 1;
      clearPoll();
      discardSeries();
      job = null;
      answer = null;
      playable = [];
      tasks = [];
      tasksLoaded = false;
      current = null;
      fragments = null;
      fragmentsPending = null;
      lastNs = null;
      structureComponent = null;
      pick.replaceChildren();
      pick.disabled = true;
      buildButton.disabled = true;
      playButton.disabled = true;
      submitButton.disabled = true;
      seriesLine.textContent = '';
      setNote('Choose a run to play its trajectory.');
      setFormNote('');
      offerBeads(false);
      fillForm(defaultArguments({trajectory: '', structure: null}, null));
      showFragmentRow(false);
    },

    // The run's own segments answer, from the monitor's one `/trajectory` fetch. The analyses are asked for here, once,
    // because the lookup for a matching build needs them and nothing else in the panel does.
    setRun(nextJob, nextAnswer) {
      job = nextJob;
      answer = nextAnswer || {};
      playable = (answer.segments || []).filter(entry => entry.trajectory && !entry.duplicate_of);
      fragments = null;
      fragmentsPending = null;
      fragmentsToken += 1;
      tasks = [];
      tasksLoaded = false;
      current = null;
      lastNs = null;
      renderSegments();
      buildButton.disabled = !playable.length;
      playButton.disabled = true;
      submitButton.disabled = true;
      if (!playable.length) {
        seriesLine.textContent = '';
        setNote(answer.why || 'This run offers no trajectory to play.');
        return;
      }
      // The form holds the selected segment's own defaults before the analyses are read, so the lookup below asks for
      // the attempt this run's latest system would be built as -- not for whatever the previous run's form said.
      fillForm(defaultArguments(entryNow(), job.run_type));
      setNote('Reading this run\'s analyses…');
      loadTasks(runToken);
    },

    // The monitor is about to replace what is on the stage (it draws another structure file). The series goes with
    // it, and the summary stays: pressing Play again fetches it, which is the one rule this block keeps.
    detach() {
      discardSeries({keepStage: true});
    },

    // The structure component now on the stage, which a series hides while it is shown and never disposes.
    structure(component) {
      structureComponent = component || null;
    },
  };
}
