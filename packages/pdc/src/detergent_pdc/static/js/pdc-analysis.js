// The pdc feature's PDC analysis tab.
//
// One completed protein-detergent run at a time: the newest published `pdc-structure` record, and the run's own
// `trajectory-overview`. Every number carries its sample, cutoff, method and caveat. The producer publishes one PNG
// per plotted metric; the record's route hands back `figures: [{name, path}]` and each is fetched through the run's
// artifact route, so the tab never guesses a sibling path.
//
// Nothing is computed unasked: **Compute structure** queues `pdc-structure` on a completed run, and **Compute
// overview** queues the core `trajectory-overview` when the run has none. Both are ordinary cached attempts; the
// overview's record is the same one the Run view's Analysis card reads. A 404 from the record route is the "not
// computed yet" state, not a failure.
//
// The tab draws no verdict, no mild/harsh label and no trend. A v1 record answers "not measured" for the metrics it
// predates; a run with no protein answers "not defined" for the protein interface; a failed attempt reports its own
// sentence and leaves the previous published data readable.
import { $, api, artifactText, artifactUrl, pollMilliseconds } from '/static/js/shared.js';

const KIND = 'pdc-structure';
const OVERVIEW = 'trajectory-overview';
const UNSETTLED = ('queued running').split(' ');

//: The kind's own four thresholds, in the order the options disclosure states them. The keys are the producer's
//: payload names; a blank field is simply absent, which is what "the server default" means.
const THRESHOLDS = [
  {key: 'rdf_bin_nm', input: '#pdc-opt-bin', label: 'RDF bin'},
  {key: 'rdf_rmax_nm', input: '#pdc-opt-rmax', label: 'RDF maximum'},
  {key: 'contact_nm', input: '#pdc-opt-contact', label: 'Contact cutoff'},
  {key: 'water_cutoff_nm', input: '#pdc-opt-water', label: 'Water cutoff'},
];

//: The four RDF pairs and the four contact groups, in the papers' order. A pair the record does not carry is a
//: state ("not measured"), never a zero.
const RDF_PAIRS = [['protein', 'head'], ['protein', 'tail'], ['head', 'head'], ['tail', 'tail']];
const CONTACT_GROUPS = [['protein', 'head'], ['protein', 'tail'], ['water', 'head'], ['water', 'tail']];

//: The record's per-metric figure names, which are the producer's committed names.
const FIGURES = {
  rdf: 'pdc-structure-rdf.png',
  proteinContacts: 'pdc-structure-contacts-protein.png',
  waterContacts: 'pdc-structure-contacts-water.png',
  shape: 'pdc-structure-shape.png',
  aggregation: 'pdc-structure-aggregation.png',
};

const number = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const fixed = (value, digits = 2) => {
  const parsed = number(value);
  return parsed === null ? '—' : parsed.toFixed(digits);
};
const thousands = (value) => {
  const parsed = number(value);
  return parsed === null ? '—' : String(Math.round(parsed)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
};
const cell = (value) => String(value ?? '').replace(/[&<>"]/g, character => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[character]));
const shortTime = (value) => String(value ?? '').replace('T', ' ').slice(0, 16);
const extensionLeg = (body) => /^(?:08_extension|4_extension)$/.test(String(body?.leg?.stage_directory || ''));
const pairLabel = ([first, second], curve = null) => {
  if (first === 'protein' || first === 'receptor') {
    const reference = curve?.reference === 'com' ? 'receptor COM' : first;
    return `${reference} → ${second}`;
  }
  return `${first} – ${second}`;
};

function newestTask(tasks, kind) {
  return (tasks || []).filter(task => task && task.kind === kind).at(-1) || null;
}

function emptyState(title, sentence) {
  const line = document.createElement('div');
  line.className = 'pds-empty';
  const lead = document.createElement('b');
  lead.textContent = title;
  line.append(lead, document.createTextNode(` ${sentence}`));
  return line;
}

function notice(title, sentence) {
  const line = document.createElement('div');
  line.className = 'pds-notice';
  line.innerHTML = `<b>${cell(title)}</b> ${cell(sentence)}`;
  return line;
}

function chip(label, kind) {
  const span = document.createElement('span');
  span.className = `pds-chip ${kind}`;
  span.textContent = label;
  return span;
}

function heading(text) {
  const line = document.createElement('h4');
  line.className = 'pds-heading';
  line.textContent = text;
  return line;
}

function subHead(title, chips) {
  const line = document.createElement('div');
  line.className = 'pds-sub-head';
  const strong = document.createElement('b');
  strong.textContent = title;
  line.append(strong, ...chips.map(([label, kind]) => chip(label, kind)));
  return line;
}

function meta(label, value) {
  const line = document.createElement('p');
  line.className = 'pds-meta';
  line.innerHTML = `${cell(label)} <b>${cell(value)}</b>`;
  return line;
}

function metric(label, value, unit = '') {
  return `<div class="pds-fig"><span>${cell(label)}</span><b>${cell(value)}`
    + `${unit ? `<span class="pds-unit">${cell(unit)}</span>` : ''}</b></div>`;
}

function table(headers, rows) {
  const host = document.createElement('table');
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  for (const [label, numeric] of headers) {
    const th = document.createElement('th');
    th.textContent = label;
    if (numeric) th.className = 'num';
    headRow.append(th);
  }
  head.append(headRow);
  const body = document.createElement('tbody');
  for (const row of rows) {
    const tr = document.createElement('tr');
    for (const [index, [value, numeric]] of row.entries()) {
      const td = document.createElement('td');
      if (numeric) td.className = 'num';
      if (value instanceof Node) td.append(value); else td.textContent = String(value ?? '');
      tr.append(td);
    }
    body.append(tr);
  }
  host.append(head, body);
  return host;
}

function imageFigure(job, path, caption) {
  const figure = document.createElement('figure');
  figure.className = 'analysis-figure';
  const image = document.createElement('img');
  image.src = artifactUrl(job.id, path);
  image.alt = caption;
  image.loading = 'lazy';
  const note = document.createElement('figcaption');
  note.textContent = caption;
  figure.append(image, note);
  return figure;
}

function downloadUrl(job, path) {
  return `/api/jobs/${encodeURIComponent(job.id)}/artifacts/`
    + String(path).split('/').map(encodeURIComponent).join('/');
}

function link(host, label, href, {download = null} = {}) {
  const anchor = document.createElement('a');
  anchor.className = 'button secondary';
  anchor.href = href;
  anchor.textContent = label;
  if (download) anchor.download = download;
  host.append(anchor);
  return anchor;
}

const csvCell = (value) => {
  const text = String(value ?? '');
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

function csvText(body, overview) {
  const rows = [['section', 'metric', 'value', 'unit']];
  const add = (section, name, value, unit = '') => {
    if (value === null || value === undefined || value === '') return;
    rows.push([section, name, String(value), unit]);
  };
  const sampling = body.sampling || {};
  for (const key of ['frames_in_file', 'frames_sampled', 'stride', 'span_ns', 'frame_dt_ps']) {
    add('sampling', key, sampling[key], key === 'span_ns' ? 'ns' : key === 'frame_dt_ps' ? 'ps' : '');
  }
  for (const [key, value] of Object.entries(body.thresholds || {})) add('threshold', key, value, 'nm');
  const shape = body.shape_nm || {};
  add('micelle', 'radius_of_gyration', shape.rg?.mean, 'nm');
  add('micelle', 'largest_cluster', body.aggregation?.largest_mean, 'molecules');
  add('micelle', 'free_detergents', body.aggregation?.free_mean, 'molecules');
  add('micelle', 'clusters', body.aggregation?.cluster_count_mean);
  add('micelle', 'asphericity', shape.asphericity?.mean, 'nm2');
  add('micelle', 'relative_shape_anisotropy', shape.relative_shape_anisotropy?.mean);
  for (const curve of body.rdf || []) {
    const pair = `${curve.first}_${curve.second}`;
    add('rdf', `${pair}_first_peak`, curve.first_peak_nm, 'nm');
    add('rdf', `${pair}_g_at_peak`, curve.first_peak_g);
    (curve.r_nm || []).forEach((r, index) => add('rdf', `${pair}_g`, curve.g?.[index], ''));
  }
  for (const group of body.contacts?.groups || []) {
    const pair = `${group.first}_${group.second}`;
    add('contacts', `${pair}_mean`, group.mean, 'beads');
    add('contacts', `${pair}_sem`, group.sem, 'beads');
    add('contacts', `${pair}_cutoff`, group.cutoff_nm, 'nm');
    (group.series?.time_ns || []).forEach((time, index) =>
      add('contacts', `${pair}_series`, group.series?.contacts?.[index], `beads@${time}ns`));
  }
  if (overview?.data) {
    const data = overview.data;
    add('overview', 'rmsd_mean', data.rmsd_nm?.mean, 'nm');
    add('overview', 'rmsf_mean', data.rmsf_nm?.mean, 'nm');
    add('overview', 'rg_mean', data.gyration_nm?.mean, 'nm');
    for (const [term, summary] of Object.entries(data.energy?.components || {})) {
      add('overview', `energy_${term}`, summary?.mean, 'kJ/mol');
    }
  }
  return `${rows.map(row => row.map(csvCell).join(',')).join('\n')}\n`;
}

export function createPdcAnalysis() {
  let wired = false;
  let ready = null;
  let runs = [];
  let current = null;
  let attempts = [];
  let record = null;
  let overview = null;
  let note = '';
  let busy = false;
  let token = 0;
  let timer = null;
  let objectUrls = [];

  const select = () => $('#pdc-analysis-run');
  const compute = () => $('#pdc-analysis-compute');
  const title = () => $('#pdc-analysis-title');
  const identity = () => $('#pdc-analysis-identity');
  const status = () => $('#pdc-analysis-status');
  const stats = () => $('#pdc-analysis-stats');
  const body = () => $('#pdc-analysis-body');

  function clearTimer() {
    if (timer) { clearTimeout(timer); timer = null; }
  }

  function resetObjectUrls() {
    for (const url of objectUrls) URL.revokeObjectURL(url);
    objectUrls = [];
  }

  function objectUrl(text, type) {
    const url = URL.createObjectURL(new Blob([text], {type}));
    objectUrls.push(url);
    return url;
  }

  function reflectUrl(id) {
    const url = new URL(location.href);
    if (id) url.searchParams.set('run', id); else url.searchParams.delete('run');
    history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }

  function options() {
    const chosen = {};
    for (const spec of THRESHOLDS) {
      const input = $(spec.input);
      const raw = (input?.value || '').trim();
      if (!raw) continue;
      const value = Number(raw);
      if (!Number.isFinite(value)) throw new Error(`${spec.label} must be a number, not ${raw}.`);
      chosen[spec.key] = value;
    }
    return chosen;
  }

  function describe(job) {
    return [job.label || job.id, job.molecule_id || 'molecule',
            job.created ? String(job.created).slice(0, 10) : ''].filter(Boolean).join(' · ');
  }

  // ------------------------------------------------------------------------------------------------- the run

  async function loadRuns() {
    const picker = select();
    picker.replaceChildren(new Option('Looking for completed runs…', ''));
    picker.disabled = true;
    let payload;
    try {
      payload = await api('/api/jobs?limit=100');
    } catch (error) {
      picker.replaceChildren(new Option('The run list could not be read', ''));
      note = `The run list could not be read: ${error.message}`;
      renderStatus();
      return;
    }
    runs = (payload.jobs || []).filter(job => job.run_type === 'pdc');
    const completed = runs.filter(job => job.status === 'completed');
    picker.replaceChildren(
      new Option(completed.length ? 'Choose a completed run'
        : 'No completed protein-detergent run yet', ''),
      ...completed.map(job => new Option(`${describe(job)} · ${job.status}`, job.id)));
    picker.disabled = !completed.length;
  }

  async function choose(id) {
    const job = runs.find(candidate => candidate.id === id) || null;
    const picker = select();
    picker.value = job && job.status === 'completed' ? job.id : '';
    reflectUrl(id || '');
    await loadJob(job);
  }

  async function loadJob(job) {
    token += 1;
    const mine = token;
    clearTimer();
    resetObjectUrls();
    current = job ? {id: job.id, label: job.label, molecule_id: job.molecule_id,
                     status: job.status, created: job.created} : null;
    attempts = [];
    record = null;
    overview = null;
    note = '';
    busy = false;
    updateControls();
    renderIdentity();
    renderStatus();
    title().textContent = current ? (current.label || current.id) : 'Choose a run';
    if (!current) {
      body().replaceChildren(emptyState('Choose a completed run.',
        'Shape, radial distributions and bead contacts are read from one bounded sample of the run’s production '
        + 'leg, and the run’s own trajectory overview is shown beside them.'));
      return;
    }
    if (current.status !== 'completed') {
      body().replaceChildren(notice('This run is still running.',
        'Analyses are queued on a stopped run. The tab will offer Compute when it completes.'));
      return;
    }
    body().replaceChildren(emptyState('Reading this run…', ''));
    await refresh(mine);
  }

  async function refresh(mine) {
    const job = current;
    if (!job || job.status !== 'completed') return;
    note = '';
    let tasks = [];
    try {
      tasks = await api(`/api/jobs/${encodeURIComponent(job.id)}/analyses?view=summary`);
    } catch (error) {
      if (mine !== token) return;
      note = `This run’s analyses could not be read: ${error.message}`;
    }
    if (mine !== token) return;
    attempts = Array.isArray(tasks) ? tasks : [];
    let answer = null;
    try {
      answer = await api(`/api/jobs/${encodeURIComponent(job.id)}/pdc-structure`);
    } catch (error) {
      if (mine !== token) return;
      // A 404 is the state "nothing computed yet"; every other answer is a read that failed.
      if (error.status !== 404) note = `The structure analysis could not be read: ${error.message}`;
    }
    if (mine !== token) return;
    record = answer && typeof answer === 'object' ? answer : null;
    overview = await readOverview(job, attempts);
    if (mine !== token) return;
    render();
    schedule(job, mine);
  }

  async function readOverview(job, tasks) {
    const task = newestTask(tasks, OVERVIEW);
    if (!task) return {missing: true};
    if (UNSETTLED.includes(task.status)) return {missing: true, pending: task};
    if (task.status !== 'completed') return {missing: true, failed: task};
    const directory = String(task.directory || '').replace(/\/+$/, '');
    if (!directory) return {missing: true, error: 'The overview attempt records no directory.'};
    try {
      const result = JSON.parse(await artifactText(job.id, `${directory}/result.json`, {strict: true}));
      const directoryName = String(result.output_directory || '').replace(/^\.\/?$/, '');
      const output = [directory, directoryName].filter(Boolean).join('/');
      const data = JSON.parse(await artifactText(job.id, `${output}/trajectory-overview.json`, {strict: true}));
      return {task, data, jsonPath: `${output}/trajectory-overview.json`,
              pngPath: `${output}/trajectory-overview.png`};
    } catch (error) {
      return {missing: true, error: `The published overview could not be read: ${error.message}`};
    }
  }

  function schedule(job, mine) {
    clearTimer();
    if (!attempts.some(task => UNSETTLED.includes(task.status)
            && (task.kind === KIND || task.kind === OVERVIEW))) return;
    timer = setTimeout(() => {
      timer = null;
      if (mine === token && current && current.id === job.id) refresh(mine).catch(() => {});
    }, Number(window.__pdcAnalysisPollMs) || pollMilliseconds(2000));
  }

  // ------------------------------------------------------------------------------------------------ the queue

  function updateControls() {
    const ready = Boolean(current && current.status === 'completed');
    const pending = attempts.some(task => task.kind === KIND && UNSETTLED.includes(task.status));
    const button = compute();
    if (!button) return;
    button.disabled = !ready || busy || pending;
    button.textContent = busy ? 'Queueing…' : pending ? 'Computing…' : 'Compute structure';
  }

  async function queue(kind, payload) {
    if (!current || current.status !== 'completed' || busy) return;
    busy = true;
    note = '';
    updateControls();
    renderStatus();
    try {
      await api(`/api/jobs/${encodeURIComponent(current.id)}/${kind}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    } catch (error) {
      busy = false;
      note = `The ${kind} analysis was not queued: ${error.message}`;
      updateControls();
      renderStatus();
      return;
    }
    busy = false;
    const mine = token;
    await refresh(mine);
  }

  function requestStructure() {
    let payload;
    try {
      payload = options();
    } catch (error) {
      note = error.message;
      renderStatus();
      return;
    }
    queue(KIND, payload);
  }

  // -------------------------------------------------------------------------------------------------- the view

  function renderIdentity() {
    const host = identity();
    host.replaceChildren();
    if (!current) {
      host.textContent = 'Choose a completed protein-detergent run.';
      return;
    }
    host.textContent = describe(current);
    host.append(' ', chip('data only', 'kind'), ' ', chip('not validated', 'gmx'));
  }

  function renderStatus() {
    const host = status();
    const lines = [];
    if (note) lines.push(note);
    const pending = attempts.filter(task => UNSETTLED.includes(task.status)
      && (task.kind === KIND || task.kind === OVERVIEW));
    if (pending.length) {
      lines.push(pending.map(task => `${task.kind} ${task.status}`).join(' · '));
    }
    for (const kind of [KIND, OVERVIEW]) {
      const task = newestTask(attempts, kind);
      if (!task || UNSETTLED.includes(task.status) || task.status === 'completed') continue;
      lines.push(`The latest ${kind} attempt ${task.status}: ${task.error || 'no reason recorded'}.`);
    }
    host.textContent = lines.join(' · ');
  }

  function figurePaths(body) {
    const paths = new Map();
    for (const entry of Array.isArray(body.figures) ? body.figures : []) {
      if (!entry || typeof entry !== 'object') continue;
      const name = String(entry.name || '');
      const path = String(entry.path || '');
      if (name && path) paths.set(name, path);
    }
    return paths;
  }

  function statGrid(metrics) {
    const grid = document.createElement('div');
    grid.className = 'pds-figures pdc-stat-grid';
    grid.innerHTML = metrics;
    return grid;
  }

  function figureCell(job, path, caption) {
    const cell = document.createElement('div');
    cell.className = 'pdc-row-cell pdc-figure-cell';
    cell.append(imageFigure(job, path, caption));
    return cell;
  }

  function figureRow(job, paths, specs) {
    // One row of figures, one equal column each. A figure the record does not carry is simply absent.
    const cells = [];
    for (const [name, caption] of specs) {
      const path = paths.get(name);
      if (path) cells.push(figureCell(job, path, caption));
    }
    if (!cells.length) return null;
    const row = document.createElement('div');
    row.className = `pdc-analysis-row pdc-figure-row columns-${cells.length}`;
    row.append(...cells);
    return row;
  }

  function cellRow(columns, children) {
    const row = document.createElement('div');
    row.className = `pdc-analysis-row columns-${columns}`;
    for (const child of children) {
      if (!child) continue;
      const cell = document.createElement('div');
      cell.className = 'pdc-row-cell';
      cell.append(child);
      row.append(cell);
    }
    return row;
  }

  function micelleStats(body) {
    const sub = document.createElement('div');
    sub.className = 'pds-sub pdc-micelle-stats';
    const shape = body.shape_nm || {};
    const aggregation = body.aggregation || {};
    const rg = shape.rg || {};
    const asphericity = shape.asphericity || shape.asphericity_nm2 || {};
    const anisotropy = shape.relative_shape_anisotropy || {};
    sub.append(subHead('Micelle', [['pdc-structure', 'kind'], ['gmx gyrate · read-only', 'gmx']]));
    sub.append(statGrid(`
      ${metric('Radius of gyration', fixed(rg.mean, 2), 'nm')}
      ${metric('Largest cluster', fixed(aggregation.largest_mean, 1), 'molecules')}
      ${metric('Free detergents', fixed(aggregation.free_mean, 1), 'molecules')}
      ${metric('Clusters', fixed(aggregation.cluster_count_mean, 1))}
      ${metric('Asphericity', fixed(asphericity.mean, 3), 'nm²')}
      ${metric('Relative shape anisotropy', fixed(anisotropy.mean, 3))}
    `));
    sub.append(meta('Subject:', body.micelle?.subject || shape.subject || 'the run’s detergent micelle'));
    return sub;
  }

  function micellePlaceholder() {
    const sub = document.createElement('div');
    sub.className = 'pds-sub pdc-micelle-stats';
    sub.append(subHead('Micelle', [['pdc-structure', 'kind']]));
    sub.insertAdjacentHTML('beforeend', '<div class="pds-empty"><b>Not computed.</b> Compute structure to publish '
      + 'the micelle shape and aggregation numbers.</div>');
    return sub;
  }

  function rdfTable(body) {
    const sub = document.createElement('div');
    sub.className = 'pds-sub';
    const curves = Array.isArray(body.rdf) ? body.rdf : [];
    const byPair = new Map(curves.map(curve => [`${curve.first}/${curve.second}`, curve]));
    const noProtein = body.protein_present === false;
    const receptorCom = curves.some(curve => curve.reference === 'com');
    const hint = receptorCom
      ? `How crowded the detergent is at a distance from the receptor or from another detergent. <b>g(r) = 1</b>
         is the bulk average. The two protein rows use the receptor's centre of mass as one reference point and
         report the strongest shell; head–head and tail–tail report their first contact peak. A pair this record
         does not carry says “not measured”.`
      : `How crowded the other beads are at a distance from the protein or from each other. <b>g(r) = 1</b> is the
         bulk average. This record predates the receptor-centre rows; its protein rows use every protein bead. A pair
         this record does not carry says “not measured”.`;
    sub.append(subHead('Radial distribution', [['gmx rdf', 'kind'], ['data only', 'gmx']]));
    sub.insertAdjacentHTML('beforeend', `<p class="pds-hint">${hint}</p>`);
    const rows = RDF_PAIRS.map(pair => {
      const curve = byPair.get(pair.join('/'));
      const first = pair[0] === 'protein' && noProtein;
      return [[pairLabel(pair, curve), false],
              [curve ? fixed(curve.first_peak_nm, 2) : (first ? 'not defined' : 'not measured'), true],
              [curve ? fixed(curve.first_peak_g, 2) : '—', true]];
    });
    sub.append(table([['Pair', false], ['Peak (nm)', true], ['g at peak', true]], rows));
    return sub;
  }

  function contactsTable(body) {
    const sub = document.createElement('div');
    sub.className = 'pds-sub';
    const contacts = body.contacts || {};
    const groups = Array.isArray(contacts.groups) ? contacts.groups : [];
    const byGroup = new Map(groups.map(group => [`${group.first}/${group.second}`, group]));
    const noProtein = body.protein_present === false;
    sub.append(subHead('Contacts', [['bead contacts · pair counts', 'kind'], ['not hydrogen bonds', 'gmx']]));
    sub.insertAdjacentHTML('beforeend', `<p class="pds-hint">Bead pairs within the cutoff, minimum image. These are
      <b>contacts</b>, not bonds and not hydrogen bonds; the water numbers count Martini <b>W beads</b> near the head
      or tail, not an all-atom hydration number.</p>`);
    const rows = CONTACT_GROUPS.map(pair => {
      const group = byGroup.get(pair.join('/'));
      const protein = pair[0] === 'protein';
      // A group the run cannot measure keeps its row with a null mean -- never a zero -- so the state is read
      // from the number, not from the row's presence.
      const measured = Boolean(group) && number(group.mean) !== null;
      return [[pairLabel(pair), false],
              [measured ? fixed(group.cutoff_nm, 2) : '—', true],
              [measured ? `${fixed(group.mean, 0)} ± ${fixed(group.sem, 1)}`
                : (protein && noProtein ? 'not defined' : 'not measured'), true]];
    });
    if (!groups.length && contacts && number(contacts.mean) !== null) {
      // The v1 record keeps one pooled protein–detergent count; it is shown as what it is, not as a group.
      rows.push([['protein – all detergent (pooled)', false],
                 [fixed(contacts.cutoff_nm, 2), true],
                 [`${fixed(contacts.mean, 0)} ± ${fixed(contacts.sem, 1)}`, true]]);
    }
    sub.append(table([['Group', false], ['Cutoff (nm)', true], ['Mean ± SEM (beads)', true]], rows));
    return sub;
  }

  function overviewButton(job) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary';
    button.textContent = 'Compute overview';
    button.disabled = busy || attempts.some(task => task.kind === OVERVIEW && UNSETTLED.includes(task.status));
    button.onclick = () => queue(OVERVIEW, {});
    return button;
  }

  function energyRows(data) {
    const rows = [];
    for (const [term, summary] of Object.entries(data.energy?.components || {})) {
      if (number(summary?.mean) === null) continue;
      rows.push([[term, false], [fixed(summary.mean, 1), true]]);
    }
    return rows;
  }

  function overviewReason() {
    return overview?.error || (overview?.failed
      ? `The latest overview attempt ${overview.failed.status}: ${overview.failed.error || 'no reason recorded'}.`
      : null);
  }

  function overviewStats(job) {
    const sub = document.createElement('div');
    sub.className = 'pds-sub pdc-overview-stats';
    sub.append(subHead('Protein shape and energy', [['trajectory-overview', 'kind'], ['read, not recomputed', 'gmx']]));
    if (!overview || overview.missing) {
      sub.insertAdjacentHTML('beforeend', `<p class="pds-hint">Read from the run’s own <b>trajectory-overview</b>
        record; this tab does not run a second pass for these numbers.</p>
        <div class="pds-empty"><b>Not computed.</b> ${cell(overviewReason() || 'This run has no trajectory overview yet.')}</div>`);
      if (overview?.pending) {
        sub.insertAdjacentHTML('beforeend',
          `<p class="pds-meta"><span class="pds-dot"></span> The overview attempt is ${cell(overview.pending.status)}.</p>`);
      } else if (job.status === 'completed') {
        sub.append(overviewButton(job));
      }
      return sub;
    }
    const data = overview.data || {};
    sub.insertAdjacentHTML('beforeend', `<p class="pds-hint">Read from the run’s existing trajectory-overview record
      (the core kind on the same production leg).</p>`);
    sub.append(statGrid(`
      ${metric('RMSD', fixed(data.rmsd_nm?.mean, 2), 'nm')}
      ${metric('RMSF, mean', fixed(data.rmsf_nm?.mean, 2), 'nm')}
      ${metric('Rg, protein', fixed(data.gyration_nm?.mean, 2), 'nm')}
    `));
    if (data.energy_absent) sub.append(meta('Energy absent:', data.energy_absent));
    return sub;
  }

  function overviewEnergyTable(job) {
    const sub = document.createElement('div');
    sub.className = 'pds-sub pdc-energy-table';
    sub.append(subHead('Energy terms', [['protein shape and energy', 'kind']]));
    if (!overview || overview.missing) {
      sub.insertAdjacentHTML('beforeend', `<p class="pds-hint">Read from the run’s own trajectory-overview record.</p>
        <div class="pds-empty"><b>Not computed.</b> ${cell(overviewReason() || 'This run has no trajectory overview yet.')}</div>`);
      return sub;
    }
    const data = overview.data || {};
    const energies = energyRows(data);
    if (energies.length) {
      sub.append(table([['Energy term', false], ['Mean (kJ/mol)', true]], energies));
    } else {
      sub.insertAdjacentHTML('beforeend', '<p class="pds-hint">This overview reports no energy terms.</p>');
    }
    return sub;
  }

  function overviewFigureBlock(job) {
    if (!overview || overview.missing) return null;
    const sub = document.createElement('div');
    sub.className = 'pds-sub pdc-overview-figure';
    sub.append(subHead('Trajectory overview', [['trajectory-overview', 'kind']]));
    sub.append(imageFigure(job, overview.pngPath, 'The overview’s own figure: RMSD, radius of gyration and the '
      + 'sampled energy trace.'));
    const data = overview.data || {};
    sub.append(meta('Sample:', `${thousands(data.frames_sampled)} of ${thousands(data.frames_in_file)} frames`
      + (data.segment ? ` from ${data.segment}` : '')));
    return sub;
  }

  function methodsSection(job, body) {
    const sub = document.createElement('div');
    sub.className = 'pds-sub';
    sub.append(subHead('Method, sampling, cutoffs', []));
    const sampling = body.sampling || {};
    if (body.method) sub.append(meta('Method:', body.method));
    sub.append(meta('Sampling:', `${thousands(sampling.frames_sampled)} of ${thousands(sampling.frames_in_file)} `
      + `frames, stride ${sampling.stride ?? '—'}`
      + (number(sampling.span_ns) !== null ? `, spanning ${fixed(sampling.span_ns, 1)} ns` : '')
      + (number(sampling.frame_dt_ps) !== null ? `, frame spacing ${fixed(sampling.frame_dt_ps, 1)} ps` : '')));
    const thresholds = body.thresholds || {};
    const firstCurve = (body.rdf || [])[0] || {};
    const parts = [];
    if (number(thresholds.rdf_bin_nm) !== null) parts.push(`RDF bin ${fixed(thresholds.rdf_bin_nm, 2)} nm`);
    if (number(thresholds.rdf_rmax_nm) !== null) parts.push(`RDF maximum ${fixed(thresholds.rdf_rmax_nm, 2)} nm`);
    if (number(body.micelle?.contact_nm) !== null) parts.push(`micelle contact ${fixed(body.micelle.contact_nm, 2)} nm`);
    if (number(thresholds.contact_nm) !== null) parts.push(`contact ${fixed(thresholds.contact_nm, 2)} nm`);
    if (number(thresholds.water_cutoff_nm) !== null) parts.push(`water ${fixed(thresholds.water_cutoff_nm, 2)} nm`);
    if (!number(thresholds.rdf_bin_nm) && number(firstCurve.bin_width_nm) !== null) {
      parts.push(`radial bin ${fixed(firstCurve.bin_width_nm, 2)} nm`);
    }
    if (!number(thresholds.rdf_rmax_nm) && number(firstCurve.r_max_nm) !== null) {
      parts.push(`radial maximum ${fixed(firstCurve.r_max_nm, 2)} nm`);
    }
    if (!number(thresholds.contact_nm) && number(body.contacts?.cutoff_nm) !== null) {
      parts.push(`contact ${fixed(body.contacts.cutoff_nm, 2)} nm`);
    }
    if (parts.length) sub.append(meta('Cutoffs:', parts.join(' · ')));
    return sub;
  }

  function caveatsSection(body) {
    if (!Array.isArray(body.caveats) || !body.caveats.length) return null;
    const caveat = document.createElement('div');
    caveat.className = 'pds-caveat';
    caveat.innerHTML = '<b>What these numbers are, and are not.</b>'
      + `<ul>${body.caveats.map(text => `<li>${cell(text)}</li>`).join('')}</ul>`;
    return caveat;
  }

  function downloadsSection(job, body, paths) {
    const sub = document.createElement('div');
    sub.className = 'pds-sub';
    sub.append(subHead('Downloads', []));
    sub.insertAdjacentHTML('beforeend', '<p class="pds-hint">The data, not a picture of the data: the report JSON, a '
      + 'CSV of the tables and series, the producer PNGs, and the overview’s own JSON/PNG.</p>');
    const host = document.createElement('div');
    host.className = 'downloads';
    // `source` is recorded from the runs root (it carries the job id); the artifact route reads from the run
    // root, so the job prefix is dropped rather than looked up below itself.
    const source = String(body.source || '');
    const relative = source.startsWith(`${job.id}/`) ? source.slice(job.id.length + 1) : source;
    link(host, 'pdc-structure.json',
         relative ? downloadUrl(job, relative) : objectUrl(JSON.stringify(body, null, 2), 'application/json'),
         {download: relative ? null : 'pdc-structure.json'});
    link(host, 'pdc-analysis.csv', objectUrl(csvText(body, overview), 'text/csv'), {download: 'pdc-analysis.csv'});
    for (const [name, path] of paths) link(host, name, downloadUrl(job, path));
    if (overview?.data) {
      link(host, 'trajectory-overview.json', downloadUrl(job, overview.jsonPath));
      link(host, 'trajectory-overview.png', downloadUrl(job, overview.pngPath));
    }
    sub.append(host);
    return sub;
  }

  function render() {
    resetObjectUrls();
    updateControls();
    renderIdentity();
    renderStatus();
    const statsHost = stats();
    const host = body();
    statsHost.replaceChildren();
    host.replaceChildren();
    if (!current) return;
    if (current.status !== 'completed') return;
    if (!record) {
      statsHost.append(micellePlaceholder(), overviewStats(current));
      host.append(emptyState('Nothing computed yet.',
        'Shape, micelle size, radial distribution and bead contacts are read from one bounded sample of this run’s '
        + 'production leg with gmx gyrate, gmx rdf and the bead-contact counts. Use Compute structure above.'));
      return;
    }
    const paths = figurePaths(record);
    const legacy = !(number(record.schema_version) >= 2
      || (Array.isArray(record.contacts?.groups) && record.contacts.groups.length));
    statsHost.append(micelleStats(record), overviewStats(current));
    if (record.protein_present === false) {
      host.append(notice('This run has no protein.',
        'The protein–detergent interface is not defined for it, so only the detergent-only forms are reported: the '
        + 'micelle’s shape and size, the detergent–detergent distributions, and the water-bead contacts.'));
    }
    if (!extensionLeg(record)) {
      host.append(notice('This is the run’s fallback production leg.',
        `${record.leg?.fallback_reason ? `The run recorded: “${record.leg.fallback_reason}”. ` : ''}`
        + `The production leg is ${record.leg?.name || 'not stated'} (${record.leg?.stage_directory || 'unstated'}); `
        + 'every number below describes that leg. Its system was never rebuilt, so it is not comparable with a run '
        + 'that has an extension leg.'));
    }
    if (legacy) {
      host.append(notice('This record predates the new metrics.',
        'The protein→tail distribution, the contact groups and the water-bead contacts say not measured. Compute '
        + 'structure publishes a new record that extends it.'));
    }
    const sampling = record.sampling || {};
    const statusLine = document.createElement('div');
    statusLine.className = 'pds-status';
    statusLine.innerHTML = `<span class="pds-dot live"></span> Published ${cell(shortTime(record.published_at))} UTC
      · attempt <code>${cell(record.attempt)}</code>
      · ${cell(thousands(sampling.frames_sampled))} of ${cell(thousands(sampling.frames_in_file))} frames, stride
      ${cell(sampling.stride)}
      · <b>${cell(record.leg?.name)}</b>
      · <span class="pds-chip gmx">scientifically_validated: ${cell(record.scientifically_validated === true)}</span>`;
    host.append(statusLine);
    // The micelle's two graphs span the card; the tables and the radial/contact graphs are separate rows of three.
    const micelleFigures = figureRow(current, paths, [
      [FIGURES.shape, 'Radius of gyration and the shape numbers over the sampled frames.'],
      [FIGURES.aggregation, 'Largest cluster and free detergents per sampled frame.'],
    ]);
    if (micelleFigures) host.append(micelleFigures);
    host.append(cellRow(3, [rdfTable(record), contactsTable(record), overviewEnergyTable(current)]));
    const analysisFigures = figureRow(current, paths, [
      [FIGURES.rdf, 'The four radial distribution curves on one axis.'],
      [FIGURES.proteinContacts, 'Protein–head and protein–tail contacts per sampled frame.'],
    ]);
    if (analysisFigures) host.append(analysisFigures);
    // The water-bead figure and the trajectory overview share one two-column row.
    const waterPath = paths.get(FIGURES.waterContacts);
    const waterCell = waterPath
      ? figureCell(current, waterPath, 'Water–head and water–tail bead contacts per sampled frame.') : null;
    const overviewFigure = overviewFigureBlock(current);
    const lastCells = [];
    if (waterCell) lastCells.push(waterCell);
    if (overviewFigure) {
      const cell = document.createElement('div');
      cell.className = 'pdc-row-cell';
      cell.append(overviewFigure);
      lastCells.push(cell);
    }
    if (lastCells.length) {
      const row = document.createElement('div');
      row.className = `pdc-analysis-row pdc-overview-row columns-${lastCells.length}`;
      row.append(...lastCells);
      host.append(row);
    }
    const foot = cellRow(2, [methodsSection(current, record), downloadsSection(current, record, paths)]);
    foot.classList.add('pdc-foot');
    host.append(foot);
    const caveats = caveatsSection(record);
    if (caveats) host.append(caveats);
  }

  // -------------------------------------------------------------------------------------------------- the wire

  function wire() {
    select().addEventListener('change', () => choose(select().value || ''));
    compute().addEventListener('click', requestStructure);
    // Back on the tab: the same read the poll would make, so a reader who left while an attempt ran sees its
    // result without waiting for the next tick. A hidden tab keeps its own timer -- the attempt settles by itself.
    document.addEventListener('dashboard:tab', (event) => {
      if (event.detail?.id === $('#pdc')?.id) {
        if (current && attempts.some(task => UNSETTLED.includes(task.status))) refresh(token);
      }
    });
    wired = true;
  }

  async function start() {
    if (!wired) wire();
    await loadRuns();
    const wanted = new URLSearchParams(location.search).get('run') || '';
    if (!wanted) {
      await loadJob(null);
      return $('#pdc');
    }
    const job = runs.find(candidate => candidate.id === wanted);
    if (!job) {
      select().value = '';
      await loadJob(null);
      noticeMissing(wanted);
      return $('#pdc');
    }
    if (job.status !== 'completed') {
      select().value = '';
      reflectUrl(wanted);
      await loadJob(job);
      return $('#pdc');
    }
    select().value = job.id;
    await loadJob(job);
    return $('#pdc');
  }

  function noticeMissing(id) {
    title().textContent = 'Choose a run';
    body().replaceChildren(emptyState('That run is not in the list.',
      `No protein-detergent run ${id} is in this workspace’s run list. The picker offers completed runs only.`));
  }

  return {
    mount: () => {
      ready = ready || start();
      return ready;
    },
    // The engine's hook (`window.pdcSetRun`) and the Run view's door: select the run in the picker and load it.
    setRun: async (id) => {
      ready = ready || start();
      await ready;
      await choose(String(id || ''));
      return $('#pdc');
    },
  };
}
