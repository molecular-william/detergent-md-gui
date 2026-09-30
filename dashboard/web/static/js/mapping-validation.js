// Mapping Validation: the AA-vs-CG comparison the analysis published, rendered as it was published.
//
// The numbers come from `/api/jobs/<id>/mapping-consistency`, which reads the attempt the analysis wrote
// rather than recomputing anything, so this panel cannot disagree with the artifact a reader can open. Two
// claims on this page are our own data and are badged (`inside the AA range`, `inside the AA spread`); the
// reference entry's values are printed as context with no verdict attached, and the two cards with nothing
// behind them say why instead of showing a substitute number.
import { $, api } from './shared.js';

const number = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const fixed = (value, digits = 4) => {
  const parsed = number(value);
  return parsed === null ? '—' : parsed.toFixed(digits);
};
const signed = (value, digits = 1) => {
  const parsed = number(value);
  return parsed === null ? '—' : `${parsed >= 0 ? '+' : ''}${parsed.toFixed(digits)}%`;
};
const pairLabel = (pair) => {
  if (!Array.isArray(pair)) return String(pair ?? '—');
  return pair.map(part => (Array.isArray(part) ? `(${part[0]},${part[1]})` : String(part))).join(' – ');
};
const cell = (value) => String(value ?? '').replace(/[&<>]/g, character => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[character]));

function pairRows(comparison) {
  const rows = comparison?.pairs?.rows || [];
  if (!rows.length) return '<tr><td colspan="6">This comparison holds no constrained pairs.</td></tr>';
  return rows.map(row => {
    const verdict = row.unconstrained
      ? 'unconstrained'
      : row.inside_range ? 'inside the AA range' : 'outside the AA range';
    const badge = row.unconstrained ? 'badge' : (row.inside_range ? 'badge' : 'badge validation-claim');
    return `<tr><td>${cell(pairLabel(row.pair))}</td>`
      + `<td>${fixed(row.aa?.mean)} ± ${fixed(row.aa?.stderr)}</td>`
      + `<td>${fixed(row.cg?.mean)} ± ${fixed(row.cg?.stderr)}</td>`
      + `<td>${signed(row.delta_pct)}</td>`
      + `<td>${row.reference_nm === null || row.reference_nm === undefined
        ? '—' : `${fixed(row.reference_nm)} (${signed(row.delta_vs_reference_pct)} context)`}</td>`
      + `<td><span class="${badge}">${verdict}</span></td></tr>`;
  }).join('');
}

function termRows(comparison) {
  const rows = comparison?.terms || [];
  if (!rows.length) return '<tr><td colspan="7">This comparison holds no bonded terms.</td></tr>';
  return rows.map(row => {
    const verdict = row.compared === false
      ? 'not compared'
      : (number(row.overlap) !== null && row.overlap >= 0.5 ? 'overlapping' : 'weak overlap');
    const badge = row.compared === false || (number(row.overlap) !== null && row.overlap < 0.5)
      ? 'badge validation-claim' : 'badge';
    return `<tr><td>${cell(row.section || '')}</td><td>${cell(row.beads || '')}</td>`
      + `<td>${fixed(row.aa?.mean, 2)} ± ${fixed(row.aa?.std, 2)}</td>`
      + `<td>${fixed(row.cg?.mean, 2)} ± ${fixed(row.cg?.std, 2)}</td>`
      + `<td>${number(row.delta) === null ? '—' : `${number(row.delta) >= 0 ? '+' : ''}${number(row.delta).toFixed(2)}`}</td>`
      + `<td>${fixed(row.overlap, 3)}</td><td><span class="${badge}">${verdict}</span></td></tr>`;
  }).join('');
}

function drawDisplacement(host, shape) {
  // Per bead, in picometres: the comparison publishes nanometres, and at 4 pm an axis in nanometres reads as
  // zero. The beads the rigid-body fit used are filled, so a reader can see which numbers the fit rests on.
  if (!host) return;
  const beads = (shape && shape.per_bead) || [];
  if (!beads.length || typeof window.Plotly === 'undefined') {
    host.textContent = 'The per-bead displacement is not in this comparison.';
    return;
  }
  const labels = beads.map(entry => `(${entry.bead?.[0]},${entry.bead?.[1]})`);
  const values = beads.map(entry => Number(entry.displacement_nm) * 1000);
  const fitted = new Set((shape.fit_beads || []).map(bead => `(${bead[0]},${bead[1]})`));
  window.Plotly.react(host, [{
    type: 'bar', x: labels, y: values,
    marker: { color: labels.map(label => (fitted.has(label) ? '#2455b0' : '#b9c6d8')) },
    text: values.map(value => value.toFixed(1)), textposition: 'outside', cliponaxis: false,
    hovertemplate: '%{x}: %{y:.2f} pm<extra></extra>',
  }], {
    margin: { l: 56, r: 12, t: 8, b: 44 }, height: 260, bargap: 0.35,
    yaxis: { title: { text: 'displacement (pm)', font: { size: 11 } }, rangemode: 'tozero' },
    xaxis: { title: { text: 'bead', font: { size: 11 } }, tickangle: 0 },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  }, { displayModeBar: false, responsive: true });
}

export function createMappingValidation({ request = api } = {}) {
  let mounted = false;

  function identity(body) {
    const comparison = body.comparison || {};
    const counts = comparison.pairs?.counts || {};
    return {
      molecule: body.molecule || comparison.molecule || '—',
      entry: comparison.entry || '—',
      reference: body.reference_run_id || '—',
      profile: body.profile || '—',
      attempt: body.attempt || '—',
      published: body.published_at ? String(body.published_at).replace('T', ' ').slice(0, 19) + ' UTC' : '—',
      outside: counts.cg_outside_aa_range,
      pairs: counts.pairs,
    };
  }

  function render(body) {
    const comparison = body.comparison || {};
    const facts = identity(body);
    const message = $('#validation-message');
    message.hidden = true;
    $('#validation-identity').textContent =
      `${facts.molecule} · reference entry ${facts.entry} (context only) · AA source ${facts.reference} · `
      + `profile ${facts.profile} · comparison ${facts.attempt} published ${facts.published}`;
    $('#validation-pair-rows').innerHTML = pairRows(comparison);
    $('#validation-term-rows').innerHTML = termRows(comparison);
    const outside = facts.outside;
    const badge = $('#validation-pairs-badge');
    badge.hidden = outside === undefined || outside === null;
    // The claim is badged only when our own data supports it: outside-the-range pairs are the adverse
    // reading, so the badge is the danger tint then and neutral when nothing is outside.
    badge.className = Number(outside) > 0 ? 'badge validation-claim' : 'badge';
    badge.textContent = `${outside ?? '—'} of ${facts.pairs ?? '—'} pairs outside the AA observed range`;
    const shape = comparison.displacement || {};
    $('#validation-shape-detail').textContent = Number.isFinite(Number(shape.rmsd_nm))
      ? `Fitted on the beads that own atoms: rmsd ${Number(shape.rmsd_nm).toFixed(4)} nm, `
        + `max ${Number(shape.max_nm).toFixed(4)} nm over ${shape.aa_frames} AA and ${shape.cg_frames} CG frames. `
        + 'The fitted beads are filled; the others are carried for completeness. The Connolly surfaces are a '
        + 'separate analysis on this run, and are not drawn here.'
      : 'The run’s shape analysis has not been published.';
    drawDisplacement($('#validation-shape-plot'), shape);
    $('#validation-interpretation').textContent = comparison.interpretation
      || 'Every comparison here is against our own atomistic reference.';
  }

  async function load() {
    const run = $('#validation-run')?.value;
    const notice = $('#validation-message');
    if (!run) {
      notice.hidden = false; notice.textContent = 'No completed CG run to compare yet.';
      $('#validation-pair-rows').innerHTML = '<tr><td colspan="6">No comparison loaded.</td></tr>';
      $('#validation-term-rows').innerHTML = '<tr><td colspan="7">No comparison loaded.</td></tr>';
      $('#validation-identity').textContent = 'Choose a completed CG run.';
      $('#validation-pairs-badge').hidden = true;
      return;
    }
    try {
      // `api()` returns the body itself; only the diagnostics endpoint wraps its payload in `data`.
      render(await request(`/api/jobs/${run}/mapping-consistency`));
    } catch (error) {
      notice.hidden = false;
      notice.textContent = `${run}: ${error.message}`;
      $('#validation-pair-rows').innerHTML = '<tr><td colspan="6">No comparison published for this run.</td></tr>';
      $('#validation-term-rows').innerHTML = '<tr><td colspan="7">No comparison published for this run.</td></tr>';
      $('#validation-pairs-badge').hidden = true;
    }
  }

  async function fillRuns() {
    const select = $('#validation-run'); if (!select) return;
    const wanted = select.value || new URLSearchParams(location.search).get('run') || '';
    const payload = await request('/api/jobs');
    const jobs = (Array.isArray(payload) ? payload : (payload.jobs || payload.data || []))
      .filter(job => job.run_type === 'aa_cg');
    select.innerHTML = jobs.length
      ? jobs.map(job => `<option value="${job.id}">${job.id} · ${job.molecule_id || 'molecule'} · ${job.status}</option>`).join('')
      : '<option value="">No CG run yet</option>';
    if (wanted && jobs.some(job => job.id === wanted)) select.value = wanted;
    else if (jobs.length) select.value = jobs.find(job => job.status === 'completed')?.id || jobs[0].id;
  }

  async function mount() {
    if (!document.querySelector('#validation')) return;
    const select = $('#validation-run');
    if (!mounted) {
      select.addEventListener('change', load);
      $('#validation-refresh').addEventListener('click', () => { fillRuns().then(load); });
    }
    await fillRuns();
    await load();
    mounted = true;
  }

  async function open(runId) {
    await mount();
    const select = $('#validation-run');
    if (runId && select && [...select.options].some(option => option.value === runId)) {
      select.value = runId;
      await load();
    }
  }

  return { mount, open };
}
