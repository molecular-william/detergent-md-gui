// One Run view monitor's Analysis card: the run's own figures, the controls that queue them, and the diagnostics that
// read the assessment beside them.
//
// The Runs page used to draw this in its card's **Analysis graphs** panel. It is here now, beside the run's structure
// and trajectory, because a figure is read next to the thing it was measured from -- and because the two monitors
// already hold the runs a reader compares. The Runs card keeps its artifact list, records and console; it draws no
// figures and offers no analysis button.
//
// Two facts decide the shape:
//
// **The server's `/figures` answer is the figure list.** It carries the run's current set (newest attempt of each
// analysis kind) and how many earlier sets it replaced, so this module does not walk the artifact index and does not
// guess which image is current. `RunFigureViewer` is the same viewer the Runs card used: tabs, captions, zoom, and an
// iframe for the one interactive figure.
//
// **The queue is the job record's own.** Every button posts the route it always did; the answer to a queue is not a
// figure but a task, so the card asks `/analyses` again and re-reads `/figures` once a task settles. It polls only
// while something is in flight -- `window.__runViewPollMs` is the test seam the Trajectory block already uses -- and a
// run switch bumps its token so a late answer writes nothing.
import { $, api, post } from './shared.js';
import { RunFigureViewer } from './figures.js';
import { renderDistanceDiagnostics } from './runs-diagnostics.js';

//: How long a queued or running analysis is left alone between asks. The Trajectory block's own seam, so a browser test
//: sets one knob rather than two.
const POLL_MS = 2000;

const pollMilliseconds = () => Number(window.__runViewPollMs) || POLL_MS;

//: The statuses a task can be in and still change without a request; anything else is settled.
const UNSETTLED = ['queued', 'running', 'cancelling'];

//: The stage that wrote the score matrix and the distance distributions. Re-score is offered only by a run that ran it,
//: the same rule the Runs card used, so a stage list that changed after this script shipped removes the button.
const ASSESSMENT_STAGE = 'CG assessment (ff_assess)';

export function analysisMarkup(side) {
  const id = name => `${name}-${side}`;
  return `
    <div class="card run-view-analysis" id="${id('run-view-analysis')}" role="group"
         aria-labelledby="${id('run-view-analysis-title')}">
      <h3 class="run-view-analysis-title" id="${id('run-view-analysis-title')}">Analysis</h3>
      <p class="hint run-view-analysis-note" id="${id('run-view-analysis-note')}" role="status"
         >Choose a run to see its analysis graphs.</p>
      <div class="toolbar run-view-analysis-actions">
        <button type="button" class="secondary" id="${id('run-view-analysis-recompute')}"
                >Recompute</button>
        <button type="button" class="secondary" id="${id('run-view-analysis-overview')}" hidden
                >Trajectory overview</button>
        <button type="button" class="secondary" id="${id('run-view-analysis-rescore')}" hidden
                >Re-score assessment</button>
      </div>
      <div class="analysis-tasks" id="${id('run-view-analysis-tasks')}" aria-live="polite"></div>
      <div class="analysis-diagnostics" id="${id('run-view-analysis-diagnostics')}"></div>
      <div class="analysis-plots" id="${id('run-view-analysis-plots')}"></div>
    </div>`;
}

export function createAnalysis({root, side}) {
  const id = name => `#${name}-${side}`;
  const card = $(id('run-view-analysis'));
  const note = $(id('run-view-analysis-note'));
  const recompute = $(id('run-view-analysis-recompute'));
  const overview = $(id('run-view-analysis-overview'));
  const rescore = $(id('run-view-analysis-rescore'));
  const taskList = $(id('run-view-analysis-tasks'));
  const diagnostics = $(id('run-view-analysis-diagnostics'));
  const plots = $(id('run-view-analysis-plots'));

  let job = null;
  let token = 0;
  let viewer = null;
  let timer = null;
  let drawn = '';                       // the task set the list is showing, so a poll that changed nothing rewrites nothing
  let statuses = new Map();             // task id -> last status seen, so a settle is noticed rather than guessed

  const setNote = text => { note.textContent = text || ''; };

  // ---------------------------------------------------------------------------------------------- the list and the figures

  function renderTasks(tasks) {
    const key = JSON.stringify(tasks.map(task => [task.id, task.status, task.progress || '', task.error || '',
                                                  task.directory || '']));
    if (key === drawn) return;
    drawn = key;
    taskList.replaceChildren(...tasks.map(row));
  }

  function row(task) {
    const line = document.createElement('p');
    const parts = [`${task.kind} · ${task.status}`, task.progress || task.error || ''].filter(Boolean);
    line.append(document.createTextNode(parts.join(' · ')));
    if (UNSETTLED.includes(task.status)) {
      const cancel = document.createElement('button');
      cancel.type = 'button'; cancel.className = 'secondary'; cancel.textContent = 'Cancel analysis';
      cancel.disabled = task.status === 'cancelling';
      cancel.onclick = async () => {
        try {
          await post(`/api/jobs/${job.id}/analyses/${task.id}/cancel`, {});
          await reload({fresh: true});
        } catch (error) { setNote(error.message); }
      };
      line.append(cancel);
    }
    if (task.directory) {
      const link = document.createElement('a');
      link.href = `/api/jobs/${job.id}/artifacts/${task.directory.split('/').map(encodeURIComponent).join('/')}/console.log`;
      link.textContent = ' Analysis log';
      line.append(link);
    }
    return line;
  }

  async function loadFigures(mine, fresh) {
    let media;
    try {
      media = await api(`/api/jobs/${encodeURIComponent(job.id)}/figures${fresh ? '?refresh=1' : ''}`);
    } catch (error) {
      if (mine === token) setNote(`This run's figures could not be read: ${error.message}`);
      return;
    }
    if (mine !== token) return;
    const figures = media.artifacts || [];
    if (!viewer || viewer.runId !== job.id) {
      viewer?.destroy();
      viewer = new RunFigureViewer(plots, job.id);
    }
    viewer.update(figures);
    const superseded = Number(media.superseded) || 0;
    setNote(figures.length
      ? `${figures.length} figure${figures.length === 1 ? '' : 's'}`
        + (superseded ? ` · ${superseded} earlier set${superseded === 1 ? '' : 's'} on disk in the artifact index` : '')
      : 'No analysis graphs yet. Recompute queues the analyses this run owes; Trajectory overview is a first look at '
        + 'the trajectory it wrote.');
    renderDistanceDiagnostics(card, job).catch(() => {});
  }

  // ---------------------------------------------------------------------------------------------------- the queue

  async function reload({fresh = false} = {}) {
    if (!job) return;
    const mine = token;
    let tasks;
    try {
      tasks = await api(`/api/jobs/${encodeURIComponent(job.id)}/analyses`);
    } catch (error) {
      if (mine === token) setNote(`This run's analyses could not be read: ${error.message}`);
      return;
    }
    if (mine !== token) return;
    // A task that has just reached a settled status has published whatever it will publish, so this is the one read
    // that must bypass the artifact index's cache; every other poll can reuse it.
    const settled = tasks.some(task => statuses.get(task.id) && statuses.get(task.id) !== task.status
      && !UNSETTLED.includes(task.status));
    statuses = new Map(tasks.map(task => [task.id, task.status]));
    renderTasks(tasks);
    await loadFigures(mine, fresh || settled);
    schedule(tasks, mine);
  }

  function schedule(tasks, mine) {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!(tasks || []).some(task => UNSETTLED.includes(task.status))) return;
    timer = setTimeout(() => { if (mine === token) reload().catch(() => {}); }, pollMilliseconds());
  }

  async function queue(path, body, sentence) {
    if (!job) return;
    let text;
    try { text = sentence(await post(path, body)); }
    catch (error) { setNote(error.message); return; }
    // The sentence is written after the refresh the queue caused: the refresh's own answer (a figure count, the task
    // list) is a state, and the sentence about what was just queued is the news, so the news wins for that turn.
    await reload({fresh: true});
    setNote(text);
  }

  recompute.onclick = () => queue(`/api/jobs/${job.id}/analyses/recompute`, {}, answer => {
    const queued = (answer.queued || []).length, owed = (answer.owed || []).length;
    return queued ? `${queued} analysis${queued === 1 ? '' : 'es'} queued${owed ? `, ${owed} to follow` : ''}`
      : owed ? `Nothing new queued: ${owed} still waiting to start` : 'Every analysis this run owes is already current';
  });
  overview.onclick = () => queue(`/api/jobs/${job.id}/trajectory-overview`, {},
    () => 'Trajectory overview queued.');
  rescore.onclick = () => queue(`/api/jobs/${job.id}/assessment/rescore`, {}, answer => {
    const histograms = `${answer.references} reference histogram${answer.references === 1 ? '' : 's'}`;
    return `Re-scoring ${answer.directory} with ${histograms}`
      + `${answer.pairs ? `, ${answer.pairs} of them pairwise` : ''}, from parameterization revision ${answer.revision}`;
  });

  // ---------------------------------------------------------------------------------------------------- the run

  function clear() {
    token += 1;
    if (timer) { clearTimeout(timer); timer = null; }
    job = null;
    drawn = '';
    statuses = new Map();
    taskList.replaceChildren();
    diagnostics.replaceChildren();
    delete diagnostics.dataset.distanceRun;
    viewer?.destroy();
    viewer = null;
    plots.replaceChildren();
    overview.hidden = true;
    rescore.hidden = true;
    recompute.disabled = true;
    setNote('');
  }

  return {
    reset() {
      clear();
      setNote('Choose a run to see its analysis graphs.');
    },

    setRun(next) {
      clear();
      job = next || null;
      if (!job) { setNote('Choose a run to see its analysis graphs.'); return; }
      recompute.disabled = false;
      // A run that never ran its assessment has nothing to re-score, and a run still in flight has nothing to
      // overview: the stage list and the status are the run's own record, not a guess made by this panel.
      overview.hidden = !['completed', 'failed', 'cancelled'].includes(job.status);
      rescore.hidden = !(job.stages || []).some(stage => stage.name === ASSESSMENT_STAGE);
      setNote('Reading this run\'s analyses…');
      reload().catch(() => {});
    },
  };
}
