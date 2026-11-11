// One Run view monitor's Analysis card: the run's own figures, the controls that queue them, the analysis checklist,
// the assessment's diagnostics, and the analysis sections a feature registers for its own records.
//
// The Runs page used to draw this in its card's **Analysis graphs** panel. It is here now, beside the run's structure
// and trajectory, because a figure is read next to the thing it was measured from -- and because the two monitors
// already hold the runs a reader compares. The Runs card keeps its artifact list, records and console; it draws no
// figures and offers no analysis button.
//
// Three facts decide the shape:
//
// **The server's `/figures` answer is the figure list.** It carries the run's current set (newest attempt of each
// analysis kind) and how many earlier sets it replaced, so this module does not walk the artifact index and does not
// guess which image is current. `RunFigureViewer` is the same viewer the Runs card used: tabs, captions, zoom, and
// pan for an image larger than its frame. Every figure it lists is a PNG or SVG; an interactive HTML artifact is
// published data, not a figure tab, so the viewer carries no iframe.
//
// **The queue is the job record's own.** Every button posts the route it always did; the answer to a queue is not a
// figure but a task, so the card asks `/analyses` again and re-reads `/figures` once a task settles. It polls only
// while something is in flight -- `window.__runViewPollMs` is the test seam the Trajectory block already uses -- and a
// run switch bumps its token so a late answer writes nothing.
//
// **The sections are the features'.** `run-view-analysis-extension.js` holds them; this file only builds the tab
// strip, keeps one pane per section and calls the section's own `mount` when it is opened. A section that is not
// defined for this run is replaced by that feature's one-sentence notice, so every run still says why.
//
// **The map is one per card, not one per pane.** A feature may register a map -- a single scene above the section
// rows that the tabs are perspectives on. The card mounts it lazily the first time a section is opened, tells it
// which section is showing, hides it on Figures (that section is the figure viewer, not a perspective), refreshes
// it when an analysis settles and resets it when the run changes. The engine passes the section names through
// without knowing them: `setMode(name)` is the whole vocabulary it shares with the feature.
import { $, api, post, liveVisible, whenLive, liveApi, panelIds, artifactUrl } from './shared.js';
import { setPanelBusy } from './panel-busy.js';
import { RunFigureViewer } from './figures.js';
import { renderDistanceDiagnostics } from './runs-diagnostics.js';
import { analysisMapFor, analysisNoticeFor, analysisSectionsFor } from './run-view-analysis-extension.js';

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
      <div class="analysis-views" role="tablist" aria-label="Analysis sections" hidden></div>
      <div class="analysis-map" hidden></div>
      <p class="analysis-notice" role="status" hidden></p>
      <div class="analysis-panes">
        <section class="analysis-pane" data-section="figures" role="tabpanel">
          <div class="analysis-plots" id="${id('run-view-analysis-plots')}"></div>
          <div class="analysis-diagnostics" id="${id('run-view-analysis-diagnostics')}"></div>
        </section>
      </div>
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
  const views = card ? card.querySelector('.analysis-views') : null;
  const mapHost = card ? card.querySelector('.analysis-map') : null;
  const notice = card ? card.querySelector('.analysis-notice') : null;
  const panes = card ? card.querySelector('.analysis-panes') : null;
  const figuresPane = card ? card.querySelector('.analysis-pane[data-section="figures"]') : null;

  let job = null;
  let token = 0;
  let viewer = null;
  let timer = null;
  let drawn = '';                       // the task set the list is showing, so a poll that changed nothing rewrites nothing
  let statuses = new Map();             // task id -> last status seen, so a settle is noticed rather than guessed
  const tails = new Map();              // attempt id -> the one line a failed attempt's log ends with
  let sections = [];                    // the registered sections this run offers
  let mounted = new Set();              // the section names whose pane has been built for this run
  let mapDefinition = null;             // the registered map this run offers, or null
  let map = null;                       // that map's controller once it is mounted
  let mapPending = null;                // the in-flight mount, so two activations mount once
  let mapMode = '';                     // the last section the map was asked to show

  const setNote = text => { note.textContent = text || ''; };

  //: The run view section hiding the card is the same condition `run-view.js` reads; polling stops while the reader
  //: is on another panel and the card comes back with an immediate read, not a lighter status-only one.
  const shown = () => {
    const section = $('#' + panelIds()['run-view']);
    return !!section && !section.hidden;
  };
  const liveShown = () => liveVisible() && shown();

  // -------------------------------------------------------------------------------------------- the list and the figures

  //: The run keeps every attempt on disk; the card shows the current state, one row per kind. The route returns them
  //: in the order they were queued, so the latest `created_at` is the current answer.
  function latestByKind(tasks) {
    const latest = new Map();
    for (const task of tasks) {
      const current = latest.get(task.kind);
      if (!current || String(task.created_at || '') >= String(current.created_at || '')) latest.set(task.kind, task);
    }
    return [...latest.values()].sort((first, second) =>
      String(first.created_at || '').localeCompare(String(second.created_at || '')));
  }

  //: A failed attempt's own `error` is the command line; its console's last line is the reason. Read the small log
  //: once per attempt and remember it, so a poll does not fetch the same file again.
  async function failureMessage(task) {
    if (tails.has(task.id)) return tails.get(task.id);
    let message = task.error || '';
    if (task.directory) {
      try {
        const response = await fetch(artifactUrl(job.id, `${task.directory}/console.log`));
        if (response.ok) {
          const lines = (await response.text()).split('\n').map(line => line.trimEnd()).filter(Boolean);
          if (lines.length) message = lines[lines.length - 1];
        }
      } catch (error) {
        // The task's own error is the fallback; a missing log is not a second failure to report.
      }
    }
    tails.set(task.id, message);
    return message;
  }

  async function renderTasks(tasks, mine) {
    const rows = latestByKind(tasks);
    const messages = await Promise.all(rows.map(task => (task.status === 'failed'
      ? failureMessage(task)
      : Promise.resolve(task.progress || ''))));
    if (mine !== token) return;        // the monitor moved to another run while the logs were being read
    const key = JSON.stringify(rows.map((task, index) => [task.id, task.kind, task.status,
                                                          messages[index], task.directory || '']));
    if (key === drawn) return;
    drawn = key;
    const list = document.createElement('ul');
    list.className = 'analysis-check';
    list.append(...rows.map((task, index) => row(task, messages[index])));
    taskList.replaceChildren(list);
  }

  //: One line per analysis kind: a decorative box (ticked by CSS once calculated), the kind as the label, then the
  //: status word the screen reader reads. A failed attempt keeps the last line of its own log as the reason; an
  //: unsettled one keeps the route's progress and the Cancel button. No log link: the console is in the artifacts.
  function row(task, message) {
    const item = document.createElement('li');
    item.dataset.status = task.status;

    const box = document.createElement('span');
    box.className = 'check';
    box.setAttribute('aria-hidden', 'true');

    const kind = document.createElement('b');
    kind.className = 'check-kind';
    kind.textContent = task.kind;

    const status = document.createElement('span');
    status.className = 'check-status';
    status.textContent = task.status;

    item.append(box, kind, document.createTextNode(' · '), status);
    if (message && (task.status === 'failed' || UNSETTLED.includes(task.status))) {
      const detail = document.createElement('span');
      detail.className = task.status === 'failed' ? 'check-why' : 'check-progress';
      detail.textContent = message;
      item.append(document.createTextNode(' · '), detail);
    }
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
      item.append(cancel);
    }
    return item;
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
      viewer = new RunFigureViewer($(id('run-view-analysis-plots')), job.id, {pending: ['trajectory overview']});
    }
    viewer.update(figures);
    const superseded = Number(media.superseded) || 0;
    setNote(figures.length
      ? `${figures.length} figure${figures.length === 1 ? '' : 's'}`
        + (superseded ? ` · ${superseded} earlier set${superseded === 1 ? '' : 's'} on disk in the artifact index` : '')
      : 'No analysis graphs yet. Recompute queues the analyses this run owes; Trajectory overview is a first look at '
        + 'the trajectory it wrote.');
    const button = views ? views.querySelector('button[data-section="figures"]') : null;
    if (button) button.textContent = `Figures${figures.length ? ` (${figures.length})` : ''}`;
    renderDistanceDiagnostics(card, job).catch(() => {});
  }

  // ------------------------------------------------------------------------------------------------ the sections

  //: The card's own tab strip: Figures, then one tab per section the feature registered for this run. The nav is
  //: hidden when no feature has a section, so an install without one draws the card it always did.
  function buildSections() {
    sections = analysisSectionsFor(job);
    views.replaceChildren();
    views.hidden = sections.length === 0;
    for (const pane of [...panes.querySelectorAll('.analysis-pane')]) {
      if (pane.dataset.section !== 'figures') pane.remove();
    }
    mounted = new Set();
    mapDefinition = analysisMapFor(job);
    const text = analysisNoticeFor(job);
    notice.hidden = !text;
    notice.textContent = text;
    if (!sections.length) {
      figuresPane.hidden = false;
      return;
    }
    const entries = [{name: 'figures', label: 'Figures'}, ...sections.map(section => ({
      name: section.name,
      label: typeof section.label === 'function' ? section.label(job) : (section.label || section.name),
    }))];
    for (const entry of entries) {
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('role', 'tab');
      button.dataset.section = entry.name;
      button.textContent = entry.label;
      button.onclick = () => activate(entry.name);
      views.append(button);
    }
    for (const section of sections) {
      const pane = document.createElement('section');
      pane.className = 'analysis-pane';
      pane.dataset.section = section.name;
      pane.setAttribute('role', 'tabpanel');
      pane.hidden = true;
      panes.append(pane);
    }
    activate('figures');
  }

  function sectionFor(name) {
    return sections.find(section => section.name === name) || null;
  }

  function paneFor(name) {
    return [...panes.querySelectorAll('.analysis-pane')].find(pane => pane.dataset.section === name) || null;
  }

  function buttonFor(name) {
    return views ? views.querySelector(`button[data-section="${name}"]`) : null;
  }

  function context(name, mine) {
    return {host: paneFor(name), job, side, isCurrent: () => mine === token, button: buttonFor(name), queue};
  }

  function drawSection(name, mine) {
    const section = sectionFor(name);
    const pane = paneFor(name);
    if (!section || !pane) return;
    const label = buttonFor(name);
    const fail = error => {
      if (mine !== token) return;
      pane.replaceChildren();
      const line = document.createElement('p');
      line.className = 'hint';
      line.textContent = `This section could not be drawn: ${error.message}`;
      pane.append(line);
    };
    // A section reads its own record before it can draw; the pane says so meanwhile, and the band clears even when the
    // section writes its whole markup over the line or fails, because the line is the pane's first child, not the
    // section's state.
    setPanelBusy(pane, 'Reading this section…');
    Promise.resolve(section.mount(context(name, mine))).catch(fail)
      .finally(() => { if (mine === token) setPanelBusy(pane, ''); });
    if (label) label.disabled = false;
  }

  function activate(name) {
    const mine = token;
    for (const button of views.querySelectorAll('button[role="tab"]')) {
      button.setAttribute('aria-selected', String(button.dataset.section === name));
    }
    for (const pane of panes.querySelectorAll('.analysis-pane')) {
      pane.hidden = pane.dataset.section !== name;
    }
    if (name === 'figures') {
      // Figures is the figure viewer, not a perspective on the map, so the host leaves the card rather than
      // sitting empty above the tabs: the map is restored, still drawn, on the next mapping section.
      hideMap();
      return;
    }
    showMap();
    mapMode = name;
    if (map) setMapMode(name);
    else mountMap(mine);
    if (!mounted.has(name)) {
      mounted.add(name);
      drawSection(name, mine);
    } else if (typeof (sectionFor(name)?.refresh) === 'function') {
      // Returning to a section re-reads it: a task may have settled while another tab was open and the card's
      // poll re-fetched only the figures. The section decides whether its own attempt changed.
      Promise.resolve(sectionFor(name).refresh(context(name, mine))).catch(() => {});
    }
  }

  function refreshSections() {
    if (!job) return;
    const mine = token;
    for (const name of mounted) {
      const section = sectionFor(name);
      if (section && typeof section.refresh === 'function') {
        Promise.resolve(section.refresh(context(name, mine))).catch(() => {});
      }
    }
  }

  // ------------------------------------------------------------------------------------------------------ the map

  //: The map is mounted into one host for the card, lazily: the first mapping section asked for it, not the run.
  //: `mount` may be async, so the card's token is checked after the await -- a monitor that moved to another run
  //: while the feature was drawing takes the scene back out instead of showing it over the wrong run's rows.
  function mountMap(mine) {
    if (!mapDefinition || !mapHost || map) return Promise.resolve(map);
    if (mapPending) return mapPending;
    const definition = mapDefinition;
    const run = job;
    mapPending = Promise.resolve()
      .then(() => definition.mount({host: mapHost, job: run, side, isCurrent: () => mine === token, queue}))
      .then(controller => {
        mapPending = null;
        if (mine !== token) {
          callMap(controller, 'reset');   // the host was emptied at the switch, so this has nowhere to paint
          return null;
        }
        map = controller || {};
        // The reader may have opened another section while the feature was still drawing: show the one that is
        // selected now, not the one that asked for the mount.
        setMapMode(mapMode);
        return map;
      })
      .catch(error => {
        mapPending = null;
        if (mine !== token || !mapHost) return null;
        // One sentence where the scene would have been; the section rows and the feature's reading are the map's
        // to keep, and a card whose map failed still reads.
        mapHost.hidden = false;
        const line = document.createElement('p');
        line.className = 'hint';
        line.textContent = `The map could not be drawn: ${error.message}`;
        mapHost.replaceChildren(line);
        return null;
      });
    return mapPending;
  }

  //: A controller method is the feature's own code: it may be missing on a partial controller, and it may reject.
  //: Neither takes the card down, because the rows beside the map are still the reader's answer.
  function callMap(controller, method, ...args) {
    if (!controller || typeof controller[method] !== 'function') return;
    try {
      Promise.resolve(controller[method](...args)).catch(() => {});
    } catch (error) {
      // A scene that cannot be redrawn is not a card that cannot be read.
    }
  }

  function setMapMode(name) {
    if (map && name) callMap(map, 'setMode', name);
  }

  function refreshMap() {
    if (map) callMap(map, 'refresh');
  }

  function showMap() {
    if (mapDefinition && mapHost) mapHost.hidden = false;
  }

  function hideMap() {
    if (mapHost) mapHost.hidden = true;
  }

  //: A run switch resets the scene and empties the host; a late mount is token-guarded above, so what lands here
  //: is always the current run's own controller.
  function clearMap() {
    const controller = map;
    map = null;
    mapPending = null;
    mapDefinition = null;
    mapMode = '';
    if (controller) callMap(controller, 'reset');
    if (mapHost) {
      mapHost.hidden = true;
      mapHost.replaceChildren();
    }
  }

  // ---------------------------------------------------------------------------------------------------- the queue

  async function reload({fresh = false} = {}) {
    if (!job) return;
    const mine = token;
    let tasks;
    try {
      // The polled list is the summary view: the same records without the heavy fields this card never reads, and
      // shared with the Trajectory block's poll through `liveApi` so one tick asks once.
      tasks = await liveApi(`/api/jobs/${encodeURIComponent(job.id)}/analyses?view=summary`);
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
    await renderTasks(tasks, mine);
    await loadFigures(mine, fresh || settled);
    if (settled) { refreshSections(); refreshMap(); }
    schedule(tasks, mine);
  }

  function schedule(tasks, mine) {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!(tasks || []).some(task => UNSETTLED.includes(task.status))) return;
    if (!liveShown()) return;
    timer = setTimeout(() => {
      timer = null;
      if (mine === token && liveShown()) reload().catch(() => {});
    }, pollMilliseconds());
  }

  //: Back on screen: the same `reload` the timer would run, so the task line and progress are overwritten from one
  //: answer. Nothing is fetched when every task is already settled -- that is still the card's stop rule.
  function resume() {
    if (!job || !liveShown()) return;
    if (![...statuses.values()].some(status => UNSETTLED.includes(status))) return;
    if (timer) { clearTimeout(timer); timer = null; }
    reload().catch(() => {});
  }
  whenLive(resume);
  document.addEventListener('dashboard:tab', resume);

  async function queue(path, body, sentence) {
    if (!job) return;
    const mine = token;
    let text;
    try { text = sentence(await post(path, body)); }
    catch (error) { if (mine === token) setNote(error.message); return; }
    await reload({fresh: true});
    // A reader who switched runs while the request was in flight gets no sentence about the run they left: the token
    // is bumped by every `setRun`, and a delayed answer writing onto the new run's card names the wrong run.
    if (mine !== token) return;
    // The sentence is written after the refresh the queue caused: the refresh's own answer (a figure count, the task
    // list) is a state, and the sentence about what was just queued is the news, so the news wins for that turn.
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
    tails.clear();
    taskList.replaceChildren();
    diagnostics().replaceChildren();
    delete diagnostics().dataset.distanceRun;
    viewer?.destroy();
    viewer = null;
    $(id('run-view-analysis-plots')).replaceChildren();
    overview.hidden = true;
    rescore.hidden = true;
    recompute.disabled = true;
    sections = [];
    mounted = new Set();
    clearMap();
    if (views) { views.replaceChildren(); views.hidden = true; }
    if (notice) { notice.hidden = true; notice.textContent = ''; }
    if (panes) {
      for (const pane of [...panes.querySelectorAll('.analysis-pane')]) {
        if (pane.dataset.section !== 'figures') pane.remove();
      }
      if (figuresPane) figuresPane.hidden = false;
    }
    setNote('');
  }

  function diagnostics() {
    return $(id('run-view-analysis-diagnostics'));
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
      buildSections();
      setNote('Reading this run\'s analyses…');
      reload().catch(() => {});
    },
  };
}
