// The Trajectory block of one Run view monitor: the frames an analysis has built from the selected segment, played on
// the canvas, and the arguments a fresh build takes.
//
// Two facts decide the shape of this module.
//
// **The viewer cannot read a trajectory.** This vendored NGL has no XTC/TRR parser (`grep -c XTC ngl.js` = 0), so
// playback is a server-written multi-model PDB. That file is big -- roughly 0.9 MB a model for an 11,708-atom system,
// which is 110 MB at 120 models -- and it is fetched when the reader presses Play and never on mount. The small
// `frames.json` beside it is what the summary and the time readout are read from, and fetching that is cheap. The
// *selected segment's* own frame count and span come from `/api/jobs/<id>/trajectory`, which reads the trajectory's
// header (0.045 s on a 1.7 GB file, measured) -- never a frame walk.
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

//: The eleven keys a frame-series attempt records its arguments under -- the form, the lookup for an existing attempt
//: and the POST body are all this one list, so a key cannot be added to one of them and forgotten in another.
const ARGS = ['trajectory', 'structure', 'start_ns', 'end_ns', 'interval_ns', 'atoms', 'pbc', 'boxcenter',
  'center', 'fit', 'group'];

//: One times speed: ten frames a second, the rate nglview's own Play uses and the one a reader can follow. A speed of
//: 2 halves the frame interval and 0.5 doubles it; it is the interval, not a multiplier of anything else.
const FRAME_MS = 100;

//: How often a queued build is asked whether it has finished. `window.__runViewPollMs` is the one test seam, the way
//: `bonded-parameterization.js` has one: the browser tier must not wait seconds for a poll it is asserting about.
const POLL_MS = 2000;

//: The server's own cap on one attempt, stated to the reader rather than re-checked here: the panel cannot count the
//: trajectory's frames, so it cannot know whether an interval is too fine -- a hint that pretended otherwise would print
//: a wrong estimate as a fact.
const MAX_MODELS = 240;

//: Where a run's mapping states which beads make up which fragment. Read lazily, when the form is opened: a run with
//: no mapping answers 404, and that is "no fragments to group on", not a failure of the panel.
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
// and the options form -- opened only by the "Frame options" button, which never builds -- is its own `<form>`.
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
        <button type="button" id="${id('run-view-build')}" aria-expanded="false"
                aria-controls="${id('run-view-recompute')}" disabled>Frame options</button>
      </div>
      <p class="run-view-segment-meta" id="${id('run-view-segment-meta')}" role="status"></p>
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
      <div class="run-view-recompute" id="${id('run-view-recompute')}" hidden>
        <form id="${id('run-view-form')}">
          <div class="run-view-form-grid">
            <label for="${id('run-view-form-atoms')}">Atoms
              <select id="${id('run-view-form-atoms')}">
                <option value="all">all atoms (water left out)</option>
                <option value="beads">beads only</option>
                <option value="ca">CA atoms only</option>
              </select>
            </label>
            <label for="${id('run-view-form-interval')}">ns per frame
              <input type="number" id="${id('run-view-form-interval')}" min="0.000001" step="any"
                     placeholder="auto (about 120 models)">
            </label>
            <label for="${id('run-view-form-start')}">Start (ns)
              <input type="number" id="${id('run-view-form-start')}" min="0" step="any" placeholder="whole file">
            </label>
            <label for="${id('run-view-form-end')}">End (ns)
              <input type="number" id="${id('run-view-form-end')}" min="0" step="any" placeholder="whole file">
            </label>
            <label for="${id('run-view-form-pbc')}">PBC
              <select id="${id('run-view-form-pbc')}">
                <option value="none" selected>none — the file as the run wrote it</option>
                <option value="mol">mol — gather each molecule split across the boundary</option>
                <option value="res">res — put each residue back in the box</option>
                <option value="atom">atom — put each atom back in the box</option>
                <option value="whole">whole — gather each molecule split across the boundary</option>
                <option value="nojump">nojump — remove jumps over the window (history-dependent)</option>
                <option value="cluster">cluster — gather the group's atoms around their centre of mass
                  (needs the run's .tpr)</option>
              </select>
            </label>
            <label for="${id('run-view-form-boxcenter')}">Box centre
              <select id="${id('run-view-form-boxcenter')}">
                <option value="tric" selected>tric — half the sum of the box vectors</option>
                <option value="rect">rect — half the diagonal of the box</option>
                <option value="zero">zero — the origin</option>
              </select>
              <span class="hint">Where Centre puts the group, and where cluster gathers it.</span>
            </label>
            <label for="${id('run-view-form-fit')}">Fit
              <select id="${id('run-view-form-fit')}">
                <option value="none">none</option>
                <option value="trans">trans — translation only</option>
                <option value="rot+trans">rot+trans — rotation and translation</option>
              </select>
            </label>
            <label for="${id('run-view-form-group')}" id="${id('run-view-form-group-label')}" hidden>Group
              <select id="${id('run-view-form-group')}" hidden>
                <option value="solute" selected>solute</option>
                <option value="protein">protein</option>
              </select>
            </label>
            <label class="run-view-form-check" for="${id('run-view-form-center')}">
              <input type="checkbox" id="${id('run-view-form-center')}"> Centre
            </label>
          </div>
          <div class="run-view-form-actions">
            <button type="submit" id="${id('run-view-submit')}" disabled>Build frames</button>
            <span class="hint" id="${id('run-view-form-note')}"></span>
          </div>
        </form>
        <p class="hint">ns per frame is a request: the server converts it with the trajectory's own time step and
          records the cadence it actually got. A blank interval aims at roughly 120 models, and a blank start and end
          mean the whole file. PBC, Box centre, Centre, Fit and Group change the view of the frames, never the run:
          mol/whole gather a molecule split across the boundary, res/atom put each residue/each atom back in the box,
          cluster gathers the chosen group's atoms around their centre of mass -- it needs the run's .tpr, so the
          server refuses it with a sentence when the run has none -- and nojump removes jumps over the whole window
          (it is history-dependent). Box centre names where the middle of the box is for Centre (and for cluster):
          tric is half the sum of the box vectors, rect half the diagonal, zero the origin. Centre puts the group
          there, and Fit is a translation or a rotation and translation on that group. The server caps one build at
          ${MAX_MODELS} models and about 250 MB, and refuses a bigger one. The segment line above states the
          trajectory's frame count from its header, but a build's size also depends on which atoms are kept, so this
          panel does not predict it. Changing a
          control here is what makes the build a new attempt; a matching one already built is reused and shown
          instead.</p>
      </div>
    </div>`;
}

//: The arguments a segment is built from when nothing has been chosen: beads for a coarse-grained trajectory (its
//: atoms are beads), everything for an atomistic one, an automatic cadence, no bounds and the file's own view.
export function defaultArguments(entry, runType) {
  return {
    trajectory: entry.trajectory,
    structure: entry.structure || null,
    start_ns: null,
    end_ns: null,
    interval_ns: null,
    atoms: isCoarseGrained(entry.trajectory, runType) ? 'beads' : 'all',
    pbc: 'none',
    boxcenter: 'tric',
    center: false,
    fit: 'none',
    group: null,
  };
}

//: A payload as the eleven arguments. An old attempt's keys are read as the view they described rather than relabelled:
//: `assembled` meant `pbc: 'mol'` plus a centre, `fit: 'protein'` a rigid fit on the protein, and `fit: 'beads'` a
//: rigid fit on one mapping fragment. `legacy` keeps what the old keys said, so the sentence can name the frame step
//: the attempt was actually built with instead of pretending it was asked for in nanoseconds.
function recordedArguments(payload) {
  const source = payload && typeof payload === 'object' ? payload : {};
  const args = {};
  for (const key of ARGS) args[key] = source[key] != null ? source[key] : null;
  const has = key => Object.prototype.hasOwnProperty.call(source, key);
  args.legacy = {
    frameStep: !has('interval_ns'),
    stride: Number.isInteger(source.stride) && source.stride > 0 ? source.stride : null,
  };
  args.pbc = has('pbc') ? source.pbc : (source.assembled === true ? 'mol' : 'none');
  // A payload written before the box centre existed was always built at the tric default, so normalising a missing
  // key to it is what keeps such an attempt findable by the default form.
  args.boxcenter = ['tric', 'rect', 'zero'].includes(source.boxcenter) ? source.boxcenter : 'tric';
  args.center = has('center') ? source.center === true : source.assembled === true;
  const stated = has('group') && source.group != null ? source.group : null;
  if (source.fit === 'protein') {
    args.fit = 'rot+trans';
    args.group = stated || 'protein';
  } else if (source.fit === 'beads') {
    args.fit = 'rot+trans';
    const letter = typeof source.fragment === 'string' ? source.fragment.trim().toUpperCase() : '';
    args.group = stated || (letter ? `fragment:${letter}` : null);
  } else {
    args.fit = source.fit != null ? source.fit : 'none';
    args.group = stated;
  }
  // The server fills `solute` when the centre or the fit needs a group and the payload states none, so the lookup
  // compares against that same default rather than against a null the server would never have used.
  if (args.group == null && (args.center || args.fit !== 'none')) args.group = 'solute';
  return args;
}

function sameArguments(left, right) {
  return ARGS.every(key => (left[key] ?? null) === (right[key] ?? null));
}

//: The newest matching attempt of this kind in a status. The list is in append order, so the last match is the newest
//: -- which is what "the newest attempt whose args equal the form" means, without a second server route for it. This
//: is the fallback for a series built before the run kept one: its attempts are read from their own directories.
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

//: The one stored series of this run, when it has one. The server keeps a single `frame-series` record for it and
//: replaces its published files in place, so the latest build is the series whatever arguments it was built with.
function stableSeries(tasks) {
  let found = null;
  for (const task of tasks) if (task && task.kind === 'frame-series' && task.stable) found = task;
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

//: The segment readout states whole ns when the span is whole and one decimal otherwise -- a 900 ns run reads
//: "900 ns", not "900.0", and a 100.5 ns one keeps its half.
const segmentNs = value => {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Number.isInteger(number) ? String(number) : number.toFixed(1);
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

//: The group a centre or fit acts on, in words.
function groupName(group) {
  if (group === 'protein') return 'the protein';
  if (group === 'solute') return 'the solute';
  if (typeof group === 'string' && group.startsWith('fragment:')) return `fragment ${group.slice(9)}`;
  return null;
}

//: The build, in words: what it was built from, one model every how many nanoseconds, of what, and the view that was
//: applied. It reads the attempt's recorded arguments and its `frames.json`, not the form: an old attempt built with a
//: frame step says so, and its cadence is the one the record states -- never one this panel guessed.
function buildSentence(args, entry, frames) {
  const parts = [`Built from ${entry.name}`];
  const cadence = Number(frames && frames.cadence_ns);
  if (cadence > 0) parts.push(`one model every ${nsText(cadence)} ns`);
  else if (args.interval_ns != null) parts.push(`one model every ${nsText(args.interval_ns)} ns requested`);
  else if (args.legacy && args.legacy.stride) parts.push(`every ${ordinal(args.legacy.stride)} frame`);
  if (args.start_ns != null || args.end_ns != null) {
    parts.push(`${args.start_ns == null ? 'the start' : `${nsText(args.start_ns)} ns`}`
      + `–${args.end_ns == null ? 'the end' : `${nsText(args.end_ns)} ns`}`);
  }
  parts.push(args.atoms === 'beads' ? 'beads only'
    : (args.atoms === 'ca' ? 'CA atoms only' : 'all atoms (water left out)'));
  const on = groupName(args.group);
  if (args.pbc && args.pbc !== 'none') parts.push(`PBC ${args.pbc}`);
  // A non-default box centre is part of the view for a centre and for cluster (which passes it to gmx), so the
  // sentence names it in both cases rather than only when Centre happens to be on.
  const boxCentre = args.boxcenter && args.boxcenter !== 'tric' ? `the ${args.boxcenter} box centre` : null;
  if (args.center) {
    parts.push(boxCentre
      ? (on ? `centred on ${on} at ${boxCentre}` : `centred at ${boxCentre}`)
      : (on ? `centred on ${on}` : 'centred'));
  } else if (args.pbc === 'cluster' && boxCentre) {
    parts.push(`at ${boxCentre}`);
  }
  if (args.fit === 'trans') parts.push(`translation-only fit${on ? ` on ${on}` : ''}`);
  else if (args.fit === 'rot+trans') parts.push(`rotation-and-translation fit${on ? ` on ${on}` : ''}`);
  if (args.legacy && args.legacy.frameStep) parts.push('built with a frame step');
  return parts.join(', ');
}

//: What a series holds, from the record of the build and the file it published: models, timespan and size -- all read
//: off `frames.json` rather than counted by anything here.
function seriesSentence(args, entry, frames) {
  const times = Array.isArray(frames.times_ns) ? frames.times_ns : [];
  const models = Number(frames.models) || times.length;
  const pieces = [`${models} model${models === 1 ? '' : 's'}`];
  if (times.length > 1) pieces.push(`${nsText(times[0])}–${nsText(times[times.length - 1])} ns`);
  const bytes = megabytes(frames.bytes);
  if (bytes) pieces.push(bytes);
  return `${buildSentence(args, entry, frames)}. It holds ${pieces.join(', ')}.`;
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
  const segmentNote = $(id('run-view-segment-meta'));
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
  const intervalInput = $(id('run-view-form-interval'));
  const startInput = $(id('run-view-form-start'));
  const endInput = $(id('run-view-form-end'));
  const pbcPick = $(id('run-view-form-pbc'));
  const boxcenterPick = $(id('run-view-form-boxcenter'));
  const centerBox = $(id('run-view-form-center'));
  const fitPick = $(id('run-view-form-fit'));
  const groupPick = $(id('run-view-form-group'));
  const groupLabel = $(id('run-view-form-group-label'));
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
    writeSegmentMeta();
  }

  // The selected segment's own size and length, read from the trajectory's header by the server. It sits under the
  // picker so a reader comparing systems sees them without pressing Play. A header that could not be read says so:
  // printing nothing would look like a segment with no frames, and a number this panel made up would be worse.
  function writeSegmentMeta() {
    const entry = entryNow();
    if (!entry) {
      segmentNote.textContent = '';
      return;
    }
    const frames = Number(entry.frames);
    const known = Number.isFinite(frames) && frames > 0;
    const span = entry.time_ns == null ? null : segmentNs(entry.time_ns);
    if (!known && span === null) {
      segmentNote.textContent = 'Frames and time not recorded for this segment.';
      return;
    }
    const parts = [];
    if (known) parts.push(`${frames.toLocaleString('en-US')} frame${frames === 1 ? '' : 's'}`);
    parts.push(span === null ? 'total time not recorded' : `${span} ns`);
    segmentNote.textContent = parts.join(' · ');
  }

  // The arguments the form holds now: what a submit sends, and what a series is looked up by. `group` is null when
  // neither the centre nor the fit uses one, which is the same default the server fills for itself.
  function formArguments(entry) {
    return {
      trajectory: entry.trajectory,
      structure: entry.structure || null,
      start_ns: numberOrNull(startInput.value),
      end_ns: numberOrNull(endInput.value),
      interval_ns: numberOrNull(intervalInput.value),
      atoms: atomsPick.value,
      pbc: pbcPick.value,
      boxcenter: boxcenterPick.value,
      center: centerBox.checked,
      fit: fitPick.value,
      group: groupNeeded() ? (groupPick.value || null) : null,
    };
  }

  function fillForm(args) {
    atomsPick.value = ['all', 'beads', 'ca'].includes(args.atoms) ? args.atoms : 'all';
    intervalInput.value = args.interval_ns == null ? '' : String(args.interval_ns);
    startInput.value = args.start_ns == null ? '' : String(args.start_ns);
    endInput.value = args.end_ns == null ? '' : String(args.end_ns);
    pbcPick.value = ['none', 'mol', 'res', 'atom', 'whole', 'nojump', 'cluster'].includes(args.pbc)
      ? args.pbc : 'none';
    boxcenterPick.value = ['tric', 'rect', 'zero'].includes(args.boxcenter) ? args.boxcenter : 'tric';
    centerBox.checked = !!args.center;
    fitPick.value = ['none', 'trans', 'rot+trans'].includes(args.fit) ? args.fit : 'none';
    setGroupValue(args.group);
    showGroupRow(groupNeeded());
  }

  // The group is needed exactly when the centre or the fit acts on one; otherwise the control is hidden and the body
  // sends null, so a default build's recorded arguments stay the eleven default ones.
  const groupNeeded = () => fitPick.value !== 'none' || centerBox.checked;

  function showGroupRow(on) {
    groupLabel.hidden = !on;
    groupPick.hidden = !on;
  }

  // A group name the select may not offer yet -- a recorded fragment whose mapping has since changed -- is appended
  // rather than dropped, because restoring the attempt's own view is the point of the fill.
  function setGroupValue(value) {
    const wanted = value || 'solute';
    if (![...groupPick.options].some(option => option.value === wanted)) {
      const option = document.createElement('option');
      option.value = wanted;
      option.textContent = wanted.replace(/^fragment:/, 'fragment ');
      groupPick.append(option);
    }
    groupPick.value = wanted;
  }

  // The run's mapping supplies fragment letters for the group select; the two fixed groups are always offered. The
  // current choice is kept, because the mapping read can resolve after the reader has already picked one.
  function setGroupOptions(letters) {
    const previous = groupPick.value || 'solute';
    const options = ['solute', 'protein'].map(value => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      return option;
    });
    for (const letter of letters) {
      const option = document.createElement('option');
      option.value = `fragment:${letter}`;
      const beads = (fragments && fragments[letter]) || [];
      option.textContent = beads.length ? `fragment ${letter} — ${beads.join(', ')}` : `fragment ${letter}`;
      options.push(option);
    }
    groupPick.replaceChildren(...options);
    setGroupValue(previous);
  }

  // The mapping is read when the form is first opened, not on mount: a run whose mapping is missing answers 404, and
  // that is a state -- no fragments to group on -- rather than a failure of the panel.
  async function loadFragments() {
    if (fragments !== null || !job) return fragments || {};
    // One read for one form: the button that opens it, a fit or centre chosen while it is open, and a series being
    // shown all ask, and two callers asking at once would fetch the mapping twice.
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
      setGroupOptions(Object.keys(found).sort());
      return fragments;
    })();
    try {
      return await fragmentsPending;
    } finally {
      fragmentsPending = null;
    }
  }

  // ------------------------------------------------------------------------------------------------ the attempt

  // The submit is the only control that queues a build, and its label says which build that is: one nothing has built
  // with these arguments yet, the attempt already on the stage (a recompute of it), or the identical attempt the run is
  // already building, which the disabled button waits for.
  function updateSubmit() {
    const entry = entryNow();
    if (!job || !entry) {
      submitButton.disabled = true;
      submitButton.textContent = 'Build frames';
      return;
    }
    const args = formArguments(entry);
    const stored = stableSeries(tasks);
    // The stored series is the run's one build, so it is what the button offers to recompute; a form that names other
    // arguments is a new build that replaces it, and the label says so.
    const inflight = stored
      ? (['queued', 'running'].includes(stored.status) ? stored : null)
      : newest(tasks, ['queued', 'running'], args);
    const built = stored || newest(tasks, ['completed', 'failed', 'cancelled'], args);
    const matches = stored ? sameArguments(recordedArguments(stored.payload), args) : true;
    submitButton.textContent = inflight ? 'Building frames…'
      : (built && matches ? 'Recompute frames' : 'Build frames');
    submitButton.disabled = !!inflight;
    if (inflight) setFormNote(`This build is ${inflight.status}. The button waits for it.`);
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
    const stored = stableSeries(tasks);
    if (stored) {
      await selectStored(stored, entry, token, prefill);
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

  // The run's one stored series: Play reads it whatever it was built with, and the form only decides what the next
  // Build replaces it with. A settled failure does not hide the last good build -- its files are still on disk and
  // the record says what went wrong.
  async function selectStored(task, entry, token, prefill) {
    if (task.status === 'queued' || task.status === 'running') {
      seriesLine.textContent = '';
      setNote(`Building frames from ${entry.name}. This page asks again until the build settles.`);
      playButton.disabled = true;
      updateSubmit();
      ensurePolling();
      return;
    }
    if (task.status === 'completed') {
      await showSeries(task, entry, token, prefill);
      return;
    }
    if (outputNamed(task, 'frames.json') && outputNamed(task, 'run-frames.pdb')) {
      await showSeries(task, entry, token, prefill, task);
      return;
    }
    await showFailure(task, entry, token);
  }

  async function showSeries(task, entry, token, prefill, failure = null) {
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
    // The record of the build on disk wins over the task's own payload: after a failed rebuild the payload names the
    // arguments that never published, while `frames.json` still describes the series Play is handed. A record that
    // states no arguments at all defers to the payload rather than claiming every default.
    const args = recordedArguments(frames.args && Object.keys(frames.args).length ? frames.args : task.payload);
    // The series was built from one segment. Switching the combo changes the form and the segment on screen, never the
    // stored build, so the sentence must name the segment the build sampled -- not the one selected now.
    const source = playable.find(candidate => candidate.trajectory === args.trajectory)
      || {name: String(args.trajectory || '').split('/').pop() || 'its source', identity: null};
    const times = Array.isArray(frames.times_ns) ? frames.times_ns : [];
    current = {task, entry, frames, pdbPath, args, times};
    // A series is older than the trajectory when the digest the build recorded is not the one the source segment
    // reports now. Only compared when both sides state one: an older answer states neither, and calling that stale
    // would accuse a file nothing has changed.
    const stale = source.identity && frames.trajectory_identity
      && String(frames.trajectory_identity) !== String(source.identity);
    seriesLine.textContent = (stale
      ? 'This series was built from an older copy of that trajectory, so it may not show what the run '
        + 'holds now. ' : '') + seriesSentence(args, source, frames);
    const notes = [];
    if (failure) {
      notes.push(`The rebuild ${failure.status}${failure.error ? `: ${failure.error}` : '.'} `
        + 'The stored series is the last successful build.');
    }
    if (stale) notes.push('Open Frame options and build again to rebuild it from the trajectory on disk.');
    if (!sameArguments(args, formArguments(entry))) {
      notes.push('The selected segment or frame options differ from this build: Build replaces the stored series '
        + 'with them.');
    }
    setNote(notes.join(' '));
    playButton.disabled = false;
    if (prefill) {
      if (typeof args.group === 'string' && args.group.startsWith('fragment:')) await loadFragments();
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
    writeSegmentMeta();
    selectSeries({prefill: true});
  });

  // The one opener of the options form, and the one name for it. It never builds: `aria-expanded` and `hidden` are the
  // same state written in one place, so the reader cannot click a "Frame options" that the form disagrees with.
  function setOptionsOpen(open) {
    recompute.hidden = !open;
    buildButton.setAttribute('aria-expanded', String(!!open));
  }

  buildButton.addEventListener('click', () => {
    const open = recompute.hidden;
    setOptionsOpen(open);
    if (open) {
      loadFragments();
      atomsPick.focus();
    }
  });

  for (const element of [startInput, endInput, intervalInput]) {
    element.addEventListener('change', () => {
      updateSubmit();
      selectSeries();
    });
  }
  for (const element of [atomsPick, pbcPick, boxcenterPick, groupPick]) {
    element.addEventListener('change', () => {
      updateSubmit();
      selectSeries();
    });
  }
  // The group row follows the two controls that use it. The mapping is read when the form opens, so a fit chosen here
  // waits on that one read rather than starting a second.
  function updateGroupRow() {
    showGroupRow(groupNeeded());
    if (groupNeeded()) loadFragments();
    updateSubmit();
    selectSeries();
  }
  fitPick.addEventListener('change', updateGroupRow);
  centerBox.addEventListener('change', updateGroupRow);

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
      segmentNote.textContent = '';
      buildButton.disabled = true;
      playButton.disabled = true;
      submitButton.disabled = true;
      submitButton.textContent = 'Build frames';
      seriesLine.textContent = '';
      setNote('Choose a run to play its trajectory.');
      setFormNote('');
      fillForm(defaultArguments({trajectory: '', structure: null}, null));
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
      submitButton.textContent = 'Build frames';
      if (!playable.length) {
        seriesLine.textContent = '';
        segmentNote.textContent = '';
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
