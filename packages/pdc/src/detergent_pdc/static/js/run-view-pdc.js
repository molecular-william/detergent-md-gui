// The protein-detergent feature's Run view extension: the file conventions and stage chain of a pdc run.
//
// The panel is shared shell; this module is the part a pdc run needs and no other run does. It is registered with
// `/static/js/run-view.js` at load (`Feature.extension_modules` in `feature.py`), and the shell imports it only when
// this distribution is installed.
//
// Two things live here:
//
//   * the structure rules -- which of a pdc run's files are coarse-grained, which directories hold its stages, and
//     the order its structure files are listed in. The engine has no stage names of its own for this run type; the
//     stage table is this feature's (`layout.py`), and so is the directory spelling its scripts write.
//   * the stage-chain table under a monitor: `/api/jobs/<id>/trajectory` says which legs are one system and where
//     the system is rebuilt, and the table prints that answer. The panel fetches the answer; this module renders it.
import { registerRunViewExtension } from '/static/js/run-view.js';
import { api, post, notice, liveVisible, whenLive } from '/static/js/shared.js';

//: The run type this extension serves.
const RUN_TYPE = 'pdc';

//: The numbered stage layout (`01_prepare/` … `10_backmap/`) and the stage names pdc wrote before the numbering.
//: Both spellings are listed because runs written before the numbering are still live.
const STAGE_DIRECTORIES = [
  '01_prepare/', '02_system/', '03_minimisation/', '04_nvt/', '05_npt/', '06_assessment/',
  '07_micelle_assessment/', '08_extension/', '09_final_assessment/', '10_backmap/',
  '0_prepare/', '1_system/', '2_minimisation/', '3_nvt/', '4_npt/',
  '2_assessment/', '3_assessment/', '4_extension/', '5_assessment/', '6_backmap/',
];

//: The system a pdc run publishes is the extension's; the legs before it are the boxes it passed through, which is
//: why they rank after it. The micelle assessment's kept system and the back-map's atomistic product are not a
//: system the run simulated, so they rank last.
const RANKS = [
  [/(?:08_extension|4_extension)\/prod\/run\.gro/, 0],
  [/(?:09_final_assessment|5_assessment)\/prod\/run\.gro/, 1],
  [/(?:06_assessment|2_assessment)\/prod\/run\.gro/, 2],
  [/(?:05_npt|4_npt)\/system\.gro/, 3],
  [/(?:04_nvt|03_minimisation)\/system\.gro/, 4],
  [/(?:02_system|1_system)\/system\.gro/, 4],
];

function structureRank(path) {
  const text = String(path || '');
  for (const [pattern, rank] of RANKS) if (pattern.test(text)) return rank;
  // A path outside this layout has no opinion; anything this run placed after its boxes ranks last, as it did when
  // the whole table lived in the engine.
  return STAGE_DIRECTORIES.some(directory => text.startsWith(directory)) ? 5 : undefined;
}

//: The run's stage chain, drawn into the sub-panel the shell owns. `isCurrent()` is false once the monitor has
//: moved to another run, so an answer that arrived late writes nothing into the run the reader now holds.
async function runSelected({job, answer, nodes, isCurrent}) {
  if (!isCurrent()) return;
  if (nodes.extension) mountWholeTrajectory(nodes.extension, job, isCurrent);
  const rows = (answer && answer.segments) || [];
  const why = (answer && answer.why) || '';
  nodes.table.hidden = false;
  nodes.wrap.hidden = false;
  if (!rows.length) {
    nodes.note.textContent = why;
    return;
  }
  const boundaries = new Map(((answer.boundaries) || []).map(entry => [entry.at, entry]));
  nodes.body.replaceChildren(...rows.map(entry => {
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
  nodes.note.textContent = `${rows.length} stage${rows.length === 1 ? '' : 's'} in `
    + `${systems} system${systems === 1 ? '' : 's'}: stages in the same group share one system; `
    + 'a change of group is where the system is rebuilt.';
}


// --------------------------------------------------------------------------------- whole-system trajectory

//: The measured cost of XTC precision, relative to 3 decimals: 91 MB -> 69 MB at 2 decimals on a live slice, and
//: 1 decimal is about a fifth smaller again. The estimate is the honest order of magnitude, never a promise.
const DECIMAL_COST = {1: 0.62, 2: 0.76, 3: 1.0};
//: How often the panel asks while a rebuild runs; a 1.6 GiB conversion takes about a minute.
const WHOLE_POLL_MS = 2000;

function wholeBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) return null;
  const gb = value / (1024 ** 3);
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.max(1, Math.round(gb * 1000))} MB`;
}

function wholeLine(info) {
  if (!info || !info.bytes) return 'not built';
  const parts = [wholeBytes(info.bytes)];
  if (info.frames) parts.push(`${Number(info.frames).toLocaleString()} × ${info.cadence_ps ?? '?'} ps`);
  return parts.join(' · ');
}

function wholeEstimate(raw, dtPs, decimals) {
  if (!raw || !raw.bytes) return '';
  const ratio = raw.frames && raw.cadence_ps && dtPs ? Math.min(1, raw.cadence_ps / dtPs) : 1;
  const bytes = Math.max(1, raw.bytes * ratio * (DECIMAL_COST[decimals] || 1));
  return `≈ ${wholeBytes(bytes)} · ${(raw.bytes / bytes).toFixed(1)}× smaller`;
}

//: The panel under the Trajectory block: rebuild the derived whole.xtc from the raw one, with the size choices.
//: It is the pdc feature's card because `whole.xtc` is this run type's convention; the engine only gives it the slot.
function mountWholeTrajectory(node, job, isCurrent) {
  if (node.wholeResumeStop) { node.wholeResumeStop(); node.wholeResumeStop = null; }
  node.replaceChildren();
  if (!job || !job.id) return;
  const details = document.createElement('details');
  details.className = 'card whole-trajectory';
  details.open = true;
  details.innerHTML = `
    <summary><span>Whole trajectory</span><span class="summary-meta">…</span></summary>
    <div class="inside">
      <label>Frame step <input class="whole-dt" type="number" min="1" step="1"> ps</label>
      <label>Decimals <select class="whole-decimals"><option>1</option><option>2</option><option>3</option></select></label>
      <span class="estimate"></span>
      <span class="actions">
        <button type="button" class="linkish whole-match">match staged</button>
        <button type="button" class="primary whole-recompute">Recompute</button>
      </span>
    </div>
    <p class="whole-error hint" role="status" hidden></p>`;
  node.append(details);

  const summary = details.querySelector('.summary-meta');
  const dt = details.querySelector('.whole-dt');
  const decimals = details.querySelector('.whole-decimals');
  const estimate = details.querySelector('.estimate');
  const button = details.querySelector('.whole-recompute');
  const match = details.querySelector('.whole-match');
  const error = details.querySelector('.whole-error');
  const path = `/api/pdc/${encodeURIComponent(job.id)}/whole-trajectory`;
  let timer = null;
  let rawInfo = null;
  let announced = null;
  const dtValue = () => rawInfo;

  const paint = answer => {
    if (!isCurrent()) return;
    const raw = answer.raw || null;
    const whole = answer.whole || null;
    const state = (answer.state || {});
    summary.textContent = wholeLine(whole);
    const defaultDt = answer.defaults?.dt_ps ?? 100;
    if (!dt.value) dt.value = String(state.dt_ps ?? defaultDt);
    if (!decimals.dataset.ready) {
      decimals.value = String(state.decimals ?? (answer.defaults?.decimals ?? 2));
      decimals.dataset.ready = '1';
    }
    const running = state.status === 'running';
    button.disabled = running;
    button.textContent = running ? 'Recomputing…' : 'Recompute';
    estimate.textContent = running ? 'converting run.xtc…' : wholeEstimate(raw, Number(dt.value), Number(decimals.value));
    error.hidden = !state.error || running;
    error.textContent = state.status === 'failed' ? state.error : '';
    if (running) arm();
    else if (state.status === 'completed' && announced !== state.finished_at) {
      announced = state.finished_at;
      const sizes = state.before_bytes && state.after_bytes
        ? `${wholeBytes(state.before_bytes)} → ${wholeBytes(state.after_bytes)}` : '';
      notice(`whole.xtc rebuilt${sizes ? ': ' + sizes : ''}. Re-run the analyses and the frame series that read it.`);
    }
  };

  const load = async () => {
    try {
      const answer = await api(path);
      paint(answer);
      return answer;
    } catch (failure) {
      if (isCurrent()) { error.hidden = false; error.textContent = failure.message; }
      return null;
    }
  };

  function arm() {
    if (timer) return;
    if (!liveVisible()) return;              // resumed by `resumeStop`'s listener when the page is live again
    timer = setTimeout(async () => {
      timer = null;
      if (!isCurrent() || !liveVisible()) return;
      const answer = await load();
      if (answer && (answer.state || {}).status === 'running') arm();
    }, WHOLE_POLL_MS);
  }
  node.wholeResumeStop = whenLive(() => { if (isCurrent() && !timer) arm(); });
  dt.addEventListener('input', () => {
    estimate.textContent = wholeEstimate(dtValue(), Number(dt.value), Number(decimals.value));
  });
  decimals.addEventListener('change', () => {
    estimate.textContent = wholeEstimate(dtValue(), Number(dt.value), Number(decimals.value));
  });
  match.addEventListener('click', () => {
    const raw = dtValue();
    if (raw?.cadence_ps) dt.value = String(Math.round(raw.cadence_ps));
    decimals.value = '3';
    estimate.textContent = wholeEstimate(raw, Number(dt.value), Number(decimals.value));
  });
  button.addEventListener('click', async () => {
    button.disabled = true;
    error.hidden = true;
    try {
      const answer = await post(path, {dt_ps: Number(dt.value), decimals: Number(decimals.value)});
      paint(answer);
      if ((answer.state || {}).status === 'running') arm();
    } catch (failure) {
      button.disabled = false;
      error.hidden = false;
      error.textContent = failure.message;
    }
  });
  load().then(answer => { rawInfo = answer?.raw || null; });
}

registerRunViewExtension({
  name: RUN_TYPE,
  serves: job => String((job && job.run_type) || '') === RUN_TYPE,
  structure: {
    // A pdc run's structures are beads and its own CONECT records, whichever stage file they came from.
    isCoarseGrained: (path, runType) => String(runType || '') === RUN_TYPE ? true : undefined,
    inStage: path => STAGE_DIRECTORIES.some(directory => String(path || '').startsWith(directory)) ? true : undefined,
    rank: structureRank,
  },
  runSelected,
});
