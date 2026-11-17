// A completed run's equilibration diagnostics: a button that makes the analysis, or the three traces it published.
// The record is read only when the row's Diagnostics disclosure is open, and it names its own legs -- a run with one
// equilibration file is one leg, not the three an AA/pdc run writes. A running run cannot be analysed, so this panel
// says that instead of offering a request the queue route would refuse.
import { $, $$, api, post } from './shared.js';
import { ensurePlotly } from './plotly-loader.js';

//: How often an attempt that has been started is asked whether it published, and the ceiling on those asks. The
//: analysis is a handful of gmx energy reads on 100-500 kB files; a wait longer than this is a failure to see rather
//: than a slow read, so the panel stops and says so.
const POLL_MILLISECONDS = 2000;
const MAX_POLLS = 150;
const INK = '#2455b0';
const TARGET_INK = '#b03a48';

//: The terms the record draws, in the order the charts are stacked. The record's own `terms` says which it carries;
//: a leg that does not carry one says so instead of drawing an empty frame.
const TERMS = [
  {key: 'Potential', title: 'Potential', unit: 'kJ/mol'},
  {key: 'Temperature', title: 'Temperature', unit: 'K'},
  {key: 'Pressure', title: 'Pressure', unit: 'bar'},
];

//: The leg keys the producer writes, with the words the switch uses. A key this table does not know is still drawn:
//: its own key is its label, because the record decides which legs exist.
const LEG_TITLES = {minimisation: 'Minimisation', nvt: 'NVT', npt: 'NPT'};

//: The order the run itself ran its legs in. The record's keys are sorted when it is written, so drawing them in the
//: record's own order would put NPT before NVT; the run's chain decides the switch instead.
const LEG_ORDER = ['minimisation', 'nvt', 'npt'];

//: The leg whose trace the panel opens on: the first constant- or coupled-pressure equilibration the record has, so a
//: reader lands on the ensemble the quantities are interesting in, and falls back to whatever the record holds.
const LEG_PREFERRED = ['nvt', 'npt'];

const states = new WeakMap();

function stateOf(card) {
  let state = states.get(card);
  if (!state) {
    state = {key: null, generation: 0, timer: null, polling: false, polls: 0};
    states.set(card, state);
  }
  return state;
}

const endpoint = job => '/api/jobs/' + encodeURIComponent(job.id) + '/equilibration-traces';

function latestTask(job) {
  const tasks = Array.isArray(job?.analyses) ? job.analyses : [];
  for (let index = tasks.length - 1; index >= 0; index -= 1) {
    if (tasks[index]?.kind === 'equilibration-traces') return tasks[index];
  }
  return null;
}

const isActive = task => task?.status === 'queued' || task?.status === 'running';

function statusText(task) {
  if (!task) return '';
  const phase = typeof task.progress === 'string' ? task.progress : task.progress?.phase;
  return 'Analysis ' + task.status + (phase ? ' \u00b7 ' + phase : '');
}

// The key a re-read is compared on. A publication moves `artifact_revision`; a run that stops, or an attempt that
// starts or fails, changes the two facts the panel's own message is made of. The row's poll re-renders the card on
// every answer, so this is what keeps that a no-op until something the panel shows has moved.
function keyOf(job) {
  const task = latestTask(job);
  return JSON.stringify([job.id, job.artifact_revision ?? '', job.status, job.revision ?? '',
                         task?.id ?? '', task?.status ?? '']);
}

function enableRunButton(host) {
  const button = $('.run-equilibration-empty button', host);
  if (button) button.disabled = false;
}

function paragraph(className, text) {
  const node = document.createElement('p');
  node.className = className;
  node.textContent = text;
  return node;
}

function header(record) {
  const head = document.createElement('div');
  head.className = 'run-equilibration-head';
  const title = document.createElement('h4');
  title.textContent = 'Equilibration traces';
  head.append(title, paragraph('hint', 'Diagnostics, not validation: each leg\'s own energy file, sampled to a bounded '
    + 'number of points. A flat trace is not evidence of convergence.'));
  if (record?.gmx_version) head.append(paragraph('hint', 'GROMACS: ' + record.gmx_version));
  return head;
}

function format(value, unit) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '';
  const digits = Math.abs(number) >= 1000 ? 0 : Math.abs(number) >= 10 ? 1 : 3;
  return number.toFixed(digits) + (unit ? ' ' + unit : '');
}

//: A target line only where the run recorded the number and the leg's own ensemble has it. Minimisation has no
//: thermostat or barostat; pressure coupling is the NPT leg's. Nothing is ever defaulted to 300 K or 1 bar here.
function targetFor(record, legKey, term) {
  if (legKey === 'minimisation' || term.key === 'Potential') return null;
  if (term.key === 'Pressure' && legKey !== 'npt') return null;
  const value = Number((record.targets || {})[term.key]);
  return Number.isFinite(value) ? value : null;
}

//: A chart container that carried a Plotly plot keeps its class and its inline size after the plot is discarded, so a
//: panel that switches to a message would leave a hole as tall as the chart. Clearing both is what makes the message
//: the panel. The height here and the chart's `min-height` in runs.css move together.
function resetChart(chart) {
  chart.replaceChildren();
  chart.classList.remove('js-plotly-plot');
  chart.removeAttribute('style');
}

function chartFor(panel, term, leg, legKey, record, plotly, failure) {
  const chart = $('.run-equilibration-chart', panel);
  if (!chart) return;
  resetChart(chart);
  const legTitle = LEG_TITLES[legKey] || legKey;
  chart.setAttribute('aria-label', term.title + ' during the ' + legTitle + ' leg');
  const entry = leg.terms?.[term.key];
  const x = Array.isArray(leg.x) ? leg.x : [];
  if (!entry || !Array.isArray(entry.values) || !x.length) {
    chart.textContent = 'This leg\'s energy file does not carry ' + term.title + '.';
    return;
  }
  if (!plotly) {
    chart.textContent = 'The local Plotly bundle could not be loaded (' + failure + '), so this trace cannot be drawn.';
    return;
  }
  const xTitle = leg.x_unit === 'step' ? 'step' : 'time (ps)';
  const traces = [{
    type: 'scatter', mode: 'lines', name: legTitle + ' \u00b7 ' + term.title,
    x, y: entry.values, line: {color: INK, width: 1.6},
    hovertemplate: term.title + ' \u00b7 %{x:.2f} ' + (leg.x_unit === 'step' ? 'step' : 'ps')
      + ' \u00b7 %{y:.4g} ' + term.unit + '<extra></extra>',
  }];
  const target = targetFor(record, legKey, term);
  if (target !== null) {
    traces.push({
      type: 'scatter', mode: 'lines', name: 'target ' + format(target, term.unit),
      x: [x[0], x[x.length - 1]], y: [target, target], hoverinfo: 'skip',
      line: {color: TARGET_INK, width: 1.2, dash: 'dash'},
    });
  }
  window.Plotly.react(chart, traces, {
    margin: {l: 58, r: 12, t: 6, b: 34}, height: 150,
    xaxis: {title: {text: xTitle, font: {size: 11}}},
    yaxis: {title: {text: term.title + ' (' + term.unit + ')', font: {size: 11}}},
    legend: {orientation: 'h', y: 1.16, x: 0, font: {size: 11}},
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  }, {displayModeBar: false, responsive: true}).catch(error => {
    chart.textContent = 'The ' + term.title + ' trace could not be drawn: ' + error.message + '.';
  });
}

// One leg's three panels, under the switch. The token is what a rapid switch is guarded by: the bundle load is a
// promise, so a slower answer for the leg the reader left must not paint over the one they chose.
async function showLeg(section, record, legKey) {
  const token = String((Number(section.dataset.draw) || 0) + 1);
  section.dataset.draw = token;
  const leg = record.legs[legKey] || {};
  for (const button of $$('.run-equilibration-switch button', section)) {
    button.setAttribute('aria-pressed', String(button.dataset.leg === legKey));
  }
  const source = $('.run-equilibration-source', section);
  if (source) {
    const legTitle = LEG_TITLES[legKey] || legKey;
    const recorded = leg.duration_ps !== null && leg.duration_ps !== undefined;
    const duration = recorded && Number.isFinite(Number(leg.duration_ps))
      ? ' \u00b7 ' + format(leg.duration_ps, 'ps') : '';
    source.textContent = legTitle + ' leg \u00b7 source: ' + (leg.source || 'not recorded') + duration;
  }
  for (const panel of $$('.run-equilibration-panel', section)) {
    const term = TERMS.find(entry => entry.key === panel.dataset.term);
    if (!term) continue;
    const mean = $('.run-equilibration-mean', panel);
    if (mean) mean.textContent = leg.terms?.[term.key]?.mean !== undefined
      ? 'mean ' + format(leg.terms[term.key].mean, term.unit) : '';
  }
  let plotly = null;
  let failure = '';
  try {
    plotly = await ensurePlotly();
  } catch (error) {
    failure = error.message;
  }
  if (section.dataset.draw !== token) return;
  for (const panel of $$('.run-equilibration-panel', section)) {
    const term = TERMS.find(entry => entry.key === panel.dataset.term);
    if (term) chartFor(panel, term, leg, legKey, record, plotly, failure);
  }
}

function drawRecord(host, record) {
  const legs = record && record.legs && typeof record.legs === 'object' ? record.legs : {};
  const present = Object.keys(legs);
  const rank = key => {
    const position = LEG_ORDER.indexOf(key);
    return position === -1 ? LEG_ORDER.length : position;
  };
  const keys = [...present].sort((left, right) => rank(left) - rank(right));
  const section = document.createElement('section');
  section.className = 'run-equilibration';
  section.append(header(record));
  if (!keys.length) {
    section.append(paragraph('hint', 'This run published no equilibration traces: no leg\'s energy file could be read.'));
    host.replaceChildren(section);
    return;
  }
  const first = LEG_PREFERRED.find(key => keys.includes(key)) || keys[0];
  if (keys.length > 1) {
    const switchRow = document.createElement('div');
    switchRow.className = 'run-equilibration-switch';
    switchRow.setAttribute('role', 'group');
    switchRow.setAttribute('aria-label', 'Equilibration leg');
    for (const legKey of keys) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary';
      button.dataset.leg = legKey;
      button.textContent = LEG_TITLES[legKey] || legKey;
      button.onclick = () => showLeg(section, record, legKey);
      switchRow.append(button);
    }
    section.append(switchRow);
  }
  const panels = document.createElement('div');
  panels.className = 'run-equilibration-panels';
  for (const term of TERMS) {
    const panel = document.createElement('figure');
    panel.className = 'run-equilibration-panel';
    panel.dataset.term = term.key;
    const caption = document.createElement('figcaption');
    const name = document.createElement('span');
    name.className = 'run-equilibration-term';
    name.textContent = term.title + ' (' + term.unit + ')';
    const mean = document.createElement('span');
    mean.className = 'run-equilibration-mean hint';
    caption.append(name, mean);
    const chart = document.createElement('div');
    chart.className = 'run-equilibration-chart';
    chart.setAttribute('role', 'img');
    chart.setAttribute('aria-label', term.title + ' during the ' + (LEG_TITLES[first] || first) + ' leg');
    panel.append(caption, chart);
    panels.append(panel);
  }
  section.append(panels);
  section.append(paragraph('run-equilibration-source hint', ''));
  host.replaceChildren(section);
  return showLeg(section, record, first);
}

function showUnpublished(host, card, job, state, generation) {
  const task = latestTask(job);
  const active = isActive(task);
  const wrap = document.createElement('div');
  wrap.className = 'run-equilibration-empty';
  const message = task?.status === 'failed'
    ? 'The traces attempt failed. The run still holds its energy files, so it can be tried again.'
    : task?.status === 'skipped'
      ? 'The traces attempt was skipped: ' + (task.error || 'the run named no reason')
      : 'This run has not published equilibration traces yet. They are read from each leg\'s own energy file.';
  wrap.append(paragraph('hint', message));
  const status = paragraph('run-equilibration-status hint', statusText(task) || '');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'secondary';
  button.textContent = 'Run the traces';
  button.disabled = active;
  button.onclick = () => start(card, job, host, state, generation, button);
  wrap.append(button, status);
  host.replaceChildren(wrap);
  if (active) {
    state.polling = true;
    schedule(card, job, host, state, generation);
  }
}

async function start(card, job, host, state, generation, button) {
  button.disabled = true;
  const status = $('.run-equilibration-status', host);
  if (status) status.textContent = 'Queueing the traces\u2026';
  try {
    const task = await post(endpoint(job), {});
    if (generation !== state.generation) return;
    state.polls = 0;
    state.polling = true;
    if (status) status.textContent = statusText(task) || 'Analysis queued';
    schedule(card, job, host, state, generation);
  } catch (error) {
    if (generation !== state.generation) return;
    if (status) status.textContent = error.message;
    button.disabled = false;
  }
}

async function load(card, job, host, state, generation) {
  let answer;
  try {
    answer = await api(endpoint(job));
  } catch (error) {
    if (generation === state.generation) {
      // No record was read, so the next open -- or the row's next poll while it is open -- asks again rather than
      // keeping a transient error until the run happens to move.
      state.key = null;
      host.replaceChildren(paragraph('hint', error.message));
    }
    return;
  }
  if (generation !== state.generation) return;
  if (answer.published) {
    state.polling = false;
    drawRecord(host, answer);
    return;
  }
  if (!answer.run_stopped) {
    state.polling = false;
    host.replaceChildren(paragraph('hint', 'This run is still going. Its equilibration traces can be read once it '
      + 'finishes; analyses refuse a running run.'), paragraph('run-equilibration-status hint', statusText(latestTask(job))));
    return;
  }
  showUnpublished(host, card, job, state, generation);
}

function schedule(card, job, host, state, generation) {
  clearTimeout(state.timer);
  state.timer = setTimeout(() => poll(card, job, host, state, generation), POLL_MILLISECONDS);
}

async function poll(card, job, host, state, generation) {
  if (generation !== state.generation) return;
  const disclosure = $('.job-diagnostics', card);
  if (!disclosure?.open) {
    state.polling = false;
    return;
  }
  if (state.polls >= MAX_POLLS) {
    state.polling = false;
    enableRunButton(host);
    const status = $('.run-equilibration-status', host);
    if (status) status.textContent = 'The traces have not published yet. The run\'s own updates will keep this '
      + 'panel current.';
    return;
  }
  state.polls += 1;
  let answer;
  try {
    answer = await api(endpoint(job));
  } catch (error) {
    if (generation !== state.generation) return;
    state.polling = false;
    enableRunButton(host);
    const status = $('.run-equilibration-status', host);
    if (status) status.textContent = error.message;
    return;
  }
  if (generation !== state.generation) return;
  if (answer.published) {
    state.polling = false;
    drawRecord(host, answer);
    return;
  }
  const task = latestTask(card.job);
  if (task?.status === 'failed' || task?.status === 'cancelled') {
    state.polling = false;
    await load(card, card.job, host, state, generation);
    return;
  }
  const status = $('.run-equilibration-status', host);
  if (status) status.textContent = statusText(task) || 'Analysis running\u2026';
  schedule(card, job, host, state, generation);
}

// The row's one reader of this record. It is keyed on the facts the panel shows, so the table's poll is a no-op
// until the run moves; the disclosure's own open event and that poll both call it, the same pair Stage settings uses.
export async function renderRunDiagnostics(card, job) {
  const host = $('.run-equilibration-host', card);
  if (!host || !job) return;
  const disclosure = $('.job-diagnostics', card);
  const state = stateOf(card);
  const key = keyOf(job);
  if (state.key === key) {
    if (disclosure?.open && !state.polling && state.polls < MAX_POLLS && isActive(latestTask(job))) {
      state.polling = true;
      schedule(card, job, host, state, state.generation);
    }
    return;
  }
  state.key = key;
  const generation = ++state.generation;
  clearTimeout(state.timer);
  state.timer = null;
  state.polling = false;
  state.polls = 0;
  await load(card, job, host, state, generation);
}
