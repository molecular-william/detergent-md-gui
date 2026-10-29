// The Osmotic Series set-up door.
//
// It collects the settings `execution/adapters/osmotic.py` reads and posts them to the existing
// `POST /api/osmotic/series` -- **one run, N concentrations**, one directory and one checkpoint each, run one at a
// time by the run type's own driver. Nothing is recomputed here: the carbohydrate list, what each one is missing,
// the two failure choices, the standing setup and the series as it stands are all the server's answers, rendered.
//
// The run list is read through the run-type filter on `/api/jobs`, so this panel asks for the series and not for
// every run in the workspace.
//
// Controls are reached through `form.elements` and class hooks, never through panel-only ids: the DOM-id guard
// renders this page's ids in both directions, and an id nothing addresses fails it.

import { $, $$, setText, notice, api, cachedApi, post } from '/static/js/shared.js';

//: The panel's default series: the five measured points Ebrahimi & Sadeghi report for maltose at 308.15 K. The
//: 0.0 control is skipped on purpose -- it is the same for every sugar, so it is not this series' business to
//: run it, and `+ Add a concentration` puts it back for a run that wants it. The route's own fallback
//: (`routes/osmotic.PAPER_MOLALITIES`) still names all six; the panel always sends its own set, so this five is
//: what is queued.
const DEFAULT_SERIES = [0.5, 1.0, 1.5, 2.0, 2.5];
//: `osmotic_box.MOLALITY_RANGE`, as `osmotic_molality`'s own spec enforces it. The catalogue states it; this is
//: only for a panel whose catalogue has not arrived.
const FALLBACK_RANGE = [0.0, 2.5];
//: The measured throughput of one condition alone, so the tally can say how long the series will take.
const FALLBACK_NS_PER_DAY = 2400.0;

export function createOsmoticSeries() {
  let catalogue = null;
  let wired = false;
  let outside = 0;

  const panel = () => $('.osmotic-layout');
  const form = () => panel();
  const controls = () => (form() ? form().elements : {});
  const range = () => ((catalogue || {}).molality_range || FALLBACK_RANGE);
  const numberInput = () => (controls().osmotic_duration_ns ? controls().osmotic_duration_ns : null);

  function selectedSugar() {
    const element = controls().osmotic_sugar;
    return ((catalogue || {}).sugars || []).find(sugar => sugar.molecule_id === (element && element.value)) || null;
  }

  function durationNs() {
    const element = numberInput();
    const value = Math.floor(Number(element && element.value) || 0);
    return value > 0 ? value : 1;
  }

  function chosenFailure() {
    const chosen = document.querySelector('.osmotic-onfail-group input:checked');
    return chosen ? chosen.value : 'carry_on';
  }

  // Every row's value, and the ones outside the paper's range -- named at the row, and left out of the count,
  // because the route refuses the whole series rather than part of it.
  function readRows() {
    const low = range()[0], high = range()[1];
    const good = [], bad = [];
    $$('.osmotic-conc-row', panel()).forEach(row => {
      const input = $('input', row);
      const note = $('.osmotic-row-note', row);
      const raw = input.value.trim();
      const value = raw === '' ? NaN : Number(raw);
      const rejected = !Number.isFinite(value) || value < low || value > high;
      input.classList.toggle('bad-value', rejected);
      if (rejected) {
        note.textContent = '— outside the paper\'s ' + low.toFixed(1) + '–' + high.toFixed(1) + ' range';
        note.style.color = 'var(--danger)';
        bad.push(raw === '' ? '(blank)' : raw);
      } else {
        note.textContent = value === 0 ? '— the 0.0 control: no measurement, and the same for every sugar' : '';
        note.style.color = '';
        good.push(value);
      }
    });
    return {good, bad};
  }

  function row(value) {
    const item = document.createElement('li');
    item.className = 'osmotic-conc-row';
    item.innerHTML = '<input type="number" min="0" max="2.5" step="0.1" value="' + value + '" aria-label="molality">'
      + '<span class="osmotic-molality-note">molal <span class="osmotic-row-note"></span></span>'
      + '<button type="button" class="secondary osmotic-conc-remove" aria-label="Remove this concentration">Remove</button>';
    return item;
  }

  function fill(values) {
    const list = $('.osmotic-concentrations', panel());
    if (list) list.replaceChildren(...values.map(row));
    recount();
  }

  function recount() {
    const {good, bad} = readRows();
    outside = bad.length;
    const duration = durationNs();
    const count = good.length;
    const total = count * duration;
    const perDay = (catalogue || {}).ns_per_day || FALLBACK_NS_PER_DAY;

    setText($('.osmotic-count-line', panel()),
            count + (count === 1 ? ' run · ' : ' runs · ') + total.toLocaleString() + ' ns');
    setText($('.osmotic-count-detail', panel()), count
      ? good.map(value => value.toFixed(1)).join(', ') + ' molal · ' + duration + ' ns each · about '
        + (total / perDay).toFixed(1) + ' days at the measured ' + perDay.toFixed(0)
        + ' ns/day for one condition alone.'
      : 'No concentration is set, so there is no series to queue.');
    setText($('.osmotic-summary-count', panel()), String(count));
    setText($('.osmotic-summary-conc', panel()),
            count ? good.map(value => value.toFixed(1)).join(', ') + ' molal' : '—');
    setText($('.osmotic-summary-duration', panel()),
            duration + ' ns each · ' + total.toLocaleString() + ' ns total');

    const warning = $('.osmotic-range-warning', panel());
    if (warning) {
      warning.hidden = !bad.length;
      if (bad.length) {
        warning.innerHTML = '<strong>Refused:</strong> ' + bad.join(', ')
          + ' is outside the paper\'s ' + range()[0].toFixed(1) + '–' + range()[1].toFixed(1)
          + ' molal range (<code>osmotic_molality</code>, 0.0–2.5). The route checks every condition before it '
          + 'creates anything, so one value out of range refuses the whole series — nothing is queued until it '
          + 'is corrected.';
      }
    }
    review();
  }

  // The sugar gate. The state comes from the catalogue (`ready`, `blocked`, `refused`) rather than being worked
  // out from the parts, so the browser cannot disagree with the server about which one applies.
  function renderSugarStatus(sugar) {
    const status = $('.osmotic-sugar-status', panel());
    if (!status) return;
    if (!sugar) {
      status.className = 'osmotic-sugar-status bad';
      status.innerHTML = '<strong>No catalogue.</strong> The carbohydrate list could not be read, so no series '
        + 'can be set up. Reload the panel, or check that the dashboard is still running.';
      return;
    }
    if (sugar.state === 'refused') {
      status.className = 'osmotic-sugar-status bad';
      status.innerHTML = '<strong>Refused — no saved CG mapping.</strong> ' + sugar.blockers.join(' ');
    } else if (sugar.state === 'blocked') {
      status.className = 'osmotic-sugar-status bad';
      status.innerHTML = '<strong>Blocked — the solute files are not there.</strong> ' + sugar.blockers.join(' ');
    } else {
      status.className = 'osmotic-sugar-status ok';
      status.innerHTML = '<strong>Ready.</strong> ' + sugar.mappings.length
        + (sugar.mappings.length === 1 ? ' mapping, its solute files present in ' : ' mappings, their solute files present in ')
        + '<code>' + sugar.solute_root + '</code>, and the box sized from the mapping\'s own beads.';
    }
  }

  function renderMapping(sugar) {
    const select = controls().osmotic_mapping_candidate;
    if (!select) return;
    const mappings = (sugar && sugar.mappings) || [];
    select.replaceChildren(...(mappings.length
      ? mappings.map(mapping => new Option(mapping.name, mapping.file))
      : [new Option('— none offered —', '')]));
    select.disabled = !mappings.length;
  }

  function renderFailureGroup() {
    const policy = (catalogue || {}).failure_policy || {};
    const options = policy.options || [];
    $$('input[name=osmotic_series_on_failure]', panel()).forEach(radio => {
      const option = options.find(candidate => candidate.value === radio.value);
      // Carrying on is the route's own contract, so an absent option for it is never a reason to disable it.
      const available = option ? option.available : radio.value === 'carry_on';
      radio.disabled = !available;
      radio.title = available ? '' : (option && option.reason) || '';
      if (!available && radio.checked) {
        const carryOn = $$('input[name=osmotic_series_on_failure]', panel()).find(other => other.value === 'carry_on');
        if (carryOn) carryOn.checked = true;
      }
    });
    const stop = options.find(option => option.value === 'stop');
    const reason = $('.osmotic-stop-reason', panel());
    if (reason) {
      reason.hidden = !stop || stop.available;
      setText(reason, stop && !stop.available ? stop.reason : '');
    }
    // `innerHTML`, not `setText`: the note names the flag and the ceiling in `code`, and a text-node write made
    // the markup visible on the page -- "(code>gmx mdrun -cpi</code>)" -- which the screenshot caught.
    const retry = $('.osmotic-retry-note', panel());
    if (retry) {
      retry.innerHTML = 'A failed condition is resumed, not restarted: it continues from the run\'s last usable '
        + 'checkpoint (<code>gmx mdrun -cpi</code>) and is retried up to ' + (policy.attempts_max || 3)
        + ' times before it is called failed. ' + (policy.attempts_max || 3)
        + ' is the house ceiling — <code>attempts_max</code>, as in the PDC pipeline.';
    }
  }

  function review() {
    const sugar = selectedSugar();
    renderSugarStatus(sugar);
    const summaryCount = $('.osmotic-summary-count', panel());
    const count = summaryCount ? Number(summaryCount.textContent) || 0 : 0;
    const policy = (catalogue || {}).failure_policy || {};
    const status = $('.osmotic-review-status', panel());
    const noteEl = $('.osmotic-review-note', panel());
    const start = $('.osmotic-start', panel());

    setText($('.osmotic-summary-sugar', panel()), sugar ? sugar.label : '—');
    const mapping = sugar && sugar.mappings.find(entry => entry.file === (controls().osmotic_mapping_candidate || {}).value);
    setText($('.osmotic-summary-mapping', panel()), mapping ? mapping.name : '—');
    setText($('.osmotic-summary-solute', panel()), sugar
      ? (sugar.state === 'refused'
        ? '— not prepared —'
        : sugar.solute_root + ' · ' + sugar.solute_files_present + ' of ' + sugar.solute_files.length + ' present')
      : '—');
    setText($('.osmotic-summary-onfail', panel()),
            'Resume from the last checkpoint, up to ' + (policy.attempts_max || 3) + ' attempts · '
            + (chosenFailure() === 'stop' ? 'then stop the series' : 'then carry on'));

    const refused = !sugar || sugar.state === 'refused';
    const blocked = !refused && sugar.state === 'blocked';
    let statusText = 'Ready', note = '';
    if (refused) {
      statusText = 'Blocked';
      note = 'Start is disabled: this carbohydrate has no mapping, so the box cannot be sized.';
    } else if (blocked) {
      statusText = 'Blocked';
      note = 'Start is disabled: the run would fail in prepare, where the missing file is named.';
    } else if (!count) {
      statusText = 'No series';
      note = 'Start is disabled: add at least one concentration.';
    } else if (outside) {
      statusText = 'Refused';
      note = 'Start is disabled: ' + outside + ' concentration is outside the paper\'s range, and the route '
        + 'refuses the whole series rather than part of it.';
    } else {
      note = 'Queues ' + count + ' condition' + (count === 1 ? '' : 's') + ' as one run: they run one at a time, '
        + 'each in its own directory with its own checkpoint, so a failed one resumes where it stopped and the '
        + 'ones that finished are not repeated.';
    }
    setText(status, statusText);
    if (status) status.className = 'osmotic-review-status ' + (statusText === 'Ready' ? 'ready' : 'blocked');
    setText(noteEl, note);
    if (start) start.disabled = refused || blocked || !count || outside > 0;
  }

  function renderSetup(setup) {
    const body = $('.osmotic-setup-rows', panel());
    if (!body || !setup) return;
    const box = setup.box_nm || [];
    const rows = [
      ['Box', box.join(' × ') + ' nm — <code>osmotic_box.BOX_NM</code>, the paper\'s box, fixed for the whole series'],
      ['Dividing area', setup.dividing_area_nm2 + ' nm² — <code>osmotic_box.dividing_area_nm2()</code>; the force '
        + 'is divided by this, and the build records it so the analysis never recomputes it'],
      ['Confinement', 'flat within ' + setup.confinement_nm + ' nm of the box centre, '
        + setup.confinement_kj_mol_nm2 + ' kJ/mol/nm² beyond it — the paper\'s flat bottom, exactly the quarter box'],
      ['Walls', 'PLUMED, one <code>UPPER_WALLS</code>/<code>LOWER_WALLS</code> pair per molecule at <code>KAPPA = '
        + setup.kappa + '</code> — half the paper\'s constant because PLUMED writes <code>V = KAPPA·(x−AT)²</code>'],
      ['Restraint', 'the reference bead <code>REF</code>, restrained to the box centre in z at '
        + setup.restraint_kj_mol_nm2 + ' kJ/mol/nm² with <code>refcoord-scaling = all</code> — '
        + '<code>osmotic.REFERENCE_RESTRAINT</code>'],
      ['Salt', 'none added — the osmometry it compares against measured salt-free solutions'],
      ['Seed', 'placement <code>random.Random(' + setup.seed + ')</code> in the runner; the mdps fix '
        + '<code>gen-seed = -1</code>. Not a control: a series is comparable because its conditions share these'],
      ['mdrun', '<code>-ntomp ' + setup.mdrun_ntomp + ' -gpu_id ' + setup.mdrun_gpu + ' -nb gpu -pin on</code>, '
        + setup.mdrun_ranks + ' MPI rank — the measured best for this box with the confinement loaded; the device is '
        + 'the series\' own <code>mdrun_gpu</code>'],
    ];
    body.replaceChildren(...rows.map(([label, text]) => {
      const tr = document.createElement('tr');
      const head = document.createElement('td');
      head.textContent = label;
      const cell = document.createElement('td');
      cell.innerHTML = text;
      tr.append(head, cell);
      return tr;
    }));
  }

  function conditionRow(condition) {
    const measured = condition.measured;
    const paper = condition.paper;
    const molality = condition.molality_requested;
    const cells = [
      molality === null || molality === undefined ? '—' : Number(molality).toFixed(1),
      condition.solute_molecules === null || condition.solute_molecules === undefined
        ? '—' : String(condition.solute_molecules),
      measured ? Number(measured.pressure_bar).toFixed(3) + ' bar'
        : (condition.state === 'failed' ? '— failed'
          : (Number(molality) === 0 ? '— control' : '— not measured')),
      paper ? Number(paper.pressure_bar).toFixed(2) + ' ± ' + Number(paper.uncertainty_bar).toFixed(2) : '—',
      condition.ratio === null || condition.ratio === undefined ? '—' : Number(condition.ratio).toFixed(2),
    ];
    const tr = document.createElement('tr');
    cells.forEach(text => {
      const cell = document.createElement('td');
      cell.textContent = text;
      tr.append(cell);
    });
    return tr;
  }

  function runRow(job) {
    const molalities = ((job.settings || {}).molalities || []).length;
    const cells = [
      job.id,
      job.label || '—',
      job.status || '—',
      molalities ? String(molalities) : '—',
    ];
    const tr = document.createElement('tr');
    if (job.id) tr.dataset.run = job.id;
    cells.forEach(text => {
      const cell = document.createElement('td');
      cell.textContent = text;
      tr.append(cell);
    });
    return tr;
  }

  // The run-type filter on the run list: one request, this run type only. The conditions the panel already reads
  // are *files* of one of these runs; this is the other half, the runs themselves -- the one that shows a series
  // that failed before it measured anything.
  function renderRuns() {
    return api('/api/jobs?run_type=osmotic&limit=20').then(body => {
      const rows = $('.osmotic-run-rows', panel());
      if (!rows) return;
      const jobs = body.jobs || [];
      rows.replaceChildren(...jobs.map(runRow));
      setText($('.osmotic-runs-note', panel()), jobs.length
        ? jobs.length + ' of ' + body.total + ' run(s) of this run type' + (jobs.length < body.total
          ? ' — the newest page, as the endpoint pages at 20. ' : '. ')
          + 'One run owns every concentration: a series is not N jobs.'
        : 'No run of this type exists yet, so there is nothing to read beside the conditions.');
    }, error => {
      setText($('.osmotic-runs-note', panel()), 'The runs could not be read: ' + error.message);
    });
  }

  function renderSeries() {
    return api('/api/osmotic/conditions').then(body => {
      const rows = $('.osmotic-series-rows', panel());
      if (!rows) return;
      const conditions = body.conditions || [];
      rows.replaceChildren(...conditions.map(conditionRow));
      setText($('.osmotic-reader-title', panel()), (body.molecule_id || 'The series') + ', measured');
      const measured = conditions.filter(condition => condition.measured).length;
      setText($('.osmotic-reader-note', panel()), conditions.length
        ? measured + ' of ' + conditions.length + ' conditions have a measurement; the rest are a gap, and no '
          + 'curve is drawn through one. A completed series is execution and measurement, not a validated model.'
        : 'No condition has recorded a measurement yet, so there is no series to show.');
    }, error => {
      setText($('.osmotic-reader-note', panel()), 'The series could not be read: ' + error.message);
    });
  }

  function queue(event) {
    event.preventDefault();
    const sugar = selectedSugar();
    if (!sugar || sugar.state !== 'ready') return;
    const policy = (catalogue || {}).failure_policy || {};
    const body = {
      molecule_id: sugar.molecule_id,
      mapping_candidate: controls().osmotic_mapping_candidate.value,
      molalities: readRows().good,
      osmotic_production_ps: durationNs() * 1000,
      temperature_k: Number(controls().osmotic_temperature_k.value),
      solute_root: sugar.solute_root,
    };
    // Only a choice the run type carries: an unadvertised key is dropped by the queue route without complaint,
    // and a choice that silently does not travel is worse than one that was never offered.
    if (policy.advertised) body[policy.key || 'series_on_failure'] = chosenFailure();
    const start = $('.osmotic-start', panel());
    if (start) start.disabled = true;
    return post('/api/osmotic/series', body).then(result => {
      const count = result.count || (result.molalities || []).length;
      notice('Series queued: ' + count + ' condition' + (count === 1 ? '' : 's') + ' in run '
        + (result.run_id || '') + ' (series ' + (result.series_id || '') + '). One run owns them all, so they run '
        + 'one at a time. Scientific validation is not established by a completed series.');
    }, error => {
      notice('The series was not queued: ' + error.message);
    }).finally(review);
  }

  function wire() {
    if (wired) return;
    wired = true;
    const root = form();
    const list = $('.osmotic-concentrations', root);
    list.addEventListener('input', recount);
    list.addEventListener('click', event => {
      const remove = event.target.closest('.osmotic-conc-remove');
      if (!remove) return;
      remove.closest('.osmotic-conc-row').remove();
      recount();
    });
    $('.osmotic-add-conc', panel()).addEventListener('click', () => {
      const rows = $$('.osmotic-conc-row input', panel());
      const last = rows.length ? Number(rows[rows.length - 1].value) || 0 : 0;
      list.append(row(Math.min(range()[1], rows.length ? last + 0.5 : 0.5).toFixed(1)));
      recount();
    });
    $('.osmotic-reset-conc', panel()).addEventListener('click', () => fill(DEFAULT_SERIES));
    numberInput().addEventListener('input', recount);
    root.addEventListener('change', event => {
      if (event.target.name === 'osmotic_sugar') { renderMapping(selectedSugar()); recount(); }
      if (event.target.name === 'osmotic_mapping_candidate') recount();
      if (event.target.name === 'osmotic_series_on_failure') recount();
    });
    root.addEventListener('input', event => {
      if (event.target.name === 'osmotic_temperature_k') {
        setText($('.osmotic-summary-temp', panel()), (Number(event.target.value) || 0).toFixed(2) + ' K');
      }
    });
    root.addEventListener('submit', queue);
  }

  async function mount() {
    const root = panel();
    if (!root) return;
    wire();
    catalogue = await cachedApi('/api/osmotic/catalogue');
    const sugars = catalogue.sugars || [];
    const select = controls().osmotic_sugar;
    // The ready sugar opens selected when there is one -- the panel is usable without a decision nobody has
    // made yet -- otherwise the first, whose refusal is then the panel's own statement.
    const preferred = sugars.find(sugar => sugar.state === 'ready') || sugars[0];
    select.replaceChildren(...sugars.map(sugar => new Option(
      sugar.molecule_id + ' · ' + (sugar.state === 'ready'
        ? sugar.mappings.length + (sugar.mappings.length === 1 ? ' mapping, solute files present' : ' mappings, solute files present')
        : sugar.state === 'blocked' ? 'mapping exists, no solute files' : 'no CG mapping (refused)'),
      sugar.molecule_id)));
    if (preferred) select.value = preferred.molecule_id;
    renderMapping(selectedSugar());
    renderFailureGroup();
    renderSetup(catalogue.setup);
    const defaults = catalogue.defaults || {};
    if (defaults.temperature_k && controls().osmotic_temperature_k) {
      controls().osmotic_temperature_k.value = defaults.temperature_k;
    }
    if (defaults.duration_ns && numberInput()) numberInput().value = defaults.duration_ns;
    setText($('.osmotic-summary-temp', panel()), (Number((controls().osmotic_temperature_k || {}).value) || 0).toFixed(2) + ' K');
    if (!$('.osmotic-conc-row', panel())) fill(DEFAULT_SERIES);
    recount();
    await Promise.all([renderSeries(), renderRuns()]);
  }

  return { mount };
}