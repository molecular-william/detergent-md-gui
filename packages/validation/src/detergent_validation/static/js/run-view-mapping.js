// The validation feature's Run view analysis sections: geometry, bonded terms, and shape and volume.
//
// These are the three cards the Mapping Validation tab used to draw per run, moved beside the run they describe.
// They read the same published record the tab read -- `GET /api/jobs/<id>/mapping-consistency` -- and compute
// nothing: an attempt name and its publish time are stated where a record is present, and a missing companion
// analysis prints its own reason rather than an empty table. The fourth and fifth cards (solution behaviour and
// across molecules) are not one trajectory's analysis and are retired with the tab; the endpoint and the analysis
// kinds stay.
//
// The sections are registered with `run-view.js` when this module loads (Feature.extension_modules), one instance
// per monitor. Every selector is resolved inside the host the card hands over and every mutable token lives in a
// per-host dataset, because two monitors in one page share this module.
import { api } from '/static/js/shared.js';
import { ensurePlotly } from '/static/js/plotly-loader.js';
import { registerRunViewAnalysisNotice, registerRunViewAnalysisSection } from '/static/js/run-view.js';

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
const delta = (value, digits = 2) => {
  const parsed = number(value);
  return parsed === null ? '—' : `${parsed >= 0 ? '+' : ''}${parsed.toFixed(digits)}`;
};
const cell = (value) => String(value ?? '').replace(/[&<>]/g, character => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[character]));
const pairLabel = (pair) => {
  if (!Array.isArray(pair)) return String(pair ?? '—');
  return pair.map(part => (Array.isArray(part) ? `(${part[0]},${part[1]})` : String(part))).join(' – ');
};
const shortTime = (value) => String(value ?? '').replace('T', ' ').slice(0, 16);

//: The card's label for a section, kept in one place so a count is written the same way twice.
const plural = (count, one, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

//: Which runs have a comparison to read. A run type is the fast answer; a record that predates the type but holds a
//: published comparison is served too, because the endpoint answers for it and hiding the tab would be a second
//: answer to the same question.
function isComparisonRun(job) {
  if (!job) return false;
  if (String(job.run_type || '') === 'aa_cg') return true;
  return (job.analyses || []).some(task => task.kind === 'mapping-consistency');
}

function notDefinedText(job) {
  const type = String((job && job.run_type) || '');
  if (type === 'aa_only') {
    return 'Mapping comparison is not defined for this run. It is anchored on a run that holds an atomistic '
      + 'reference, its trajectory mapped onto the beads, and the simulated coarse-grained trajectory together; '
      + 'an atomistic-only run holds the first and not the other two. Its figures and task list work as on any run.';
  }
  if (type === 'pdc') {
    return 'Mapping comparison is not defined for a protein-detergent run: it consumes a mapping rather than being '
      + 'fitted by one, so there is no atomistic/mapped/CG trio to compare. Its figures and task list work as on '
      + 'any run.';
  }
  return 'Mapping comparison is not defined for this run: it does not hold an atomistic reference, a mapped '
    + 'trajectory and a simulated coarse-grained trajectory together. Its figures and task list work as on any run.';
}

// --------------------------------------------------------------------------------------------------- the record

async function loadBody(host, job, isCurrent, retry) {
  try {
    return await api(`/api/jobs/${encodeURIComponent(job.id)}/mapping-consistency`);
  } catch (error) {
    if (!isCurrent()) return null;
    host.replaceChildren(paragraph('hint', `${error.message}. The comparison is not queued for this run.`));
    if (retry) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary';
      button.textContent = 'Calculate the comparison';
      button.onclick = async () => {
        button.disabled = true;
        try {
          await retry();
        } finally {
          button.disabled = false;
        }
      };
      host.append(button);
    }
    return null;
  }
}

function paragraph(className, text) {
  const line = document.createElement('p');
  line.className = className;
  line.textContent = text;
  return line;
}

function identity(body) {
  const comparison = body.comparison || {};
  const counts = comparison.pairs?.counts || {};
  const outside = counts.cg_outside_aa_range;
  return `<p class="rvm-identity"><b>${cell(body.molecule || comparison.molecule || '—')}</b> · reference entry
      <b>${cell(comparison.entry || '—')}</b> (context only) · AA source <b>${cell(body.reference_run_id || '—')}</b>
      · profile <b>${cell(body.profile || '—')}</b> · comparison <b>${cell(body.attempt || '—')}</b> published
      ${cell(shortTime(body.published_at))} UTC</p>
    <p><span class="rvm-badge${Number(outside) > 0 ? ' rvm-claim' : ''}"
      >${outside ?? '—'} of ${counts.pairs ?? '—'} pairs outside the AA observed range</span></p>`;
}

function measureList(rows) {
  return `<div class="rvm-measures">${rows.join('')}</div>`;
}

function measure(head, values, context) {
  return `<article class="rvm-measure">
    <div class="rvm-head">${head}</div>
    <div class="rvm-values">${values}</div>
    ${context ? `<p class="rvm-context">${context}</p>` : ''}
  </article>`;
}

function pairRows(comparison) {
  const rows = comparison?.pairs?.rows || [];
  if (!rows.length) return '<p class="hint">This comparison holds no constrained pairs.</p>';
  return measureList(rows.map(row => {
    const verdict = row.unconstrained
      ? 'unconstrained'
      : row.inside_range ? 'inside the AA range' : 'outside the AA range';
    const claim = row.unconstrained || !row.inside_range;
    const aaRange = row.aa && number(row.aa.min) !== null && number(row.aa.max) !== null
      ? `${fixed(row.aa.min)}–${fixed(row.aa.max)}` : '—';
    const reference = row.reference_nm === null || row.reference_nm === undefined
      ? 'not stated'
      : `${fixed(row.reference_nm)} (${signed(row.delta_vs_reference_pct)} context)`;
    return measure(
      `<b>${cell(pairLabel(row.pair))}</b><span class="rvm-badge${claim ? ' rvm-claim' : ''}">${verdict}</span>`,
      `<span>AA <b>${fixed(row.aa?.mean)} ± ${fixed(row.aa?.stderr)}</b></span>
       <span>CG <b>${fixed(row.cg?.mean)} ± ${fixed(row.cg?.stderr)}</b></span>
       <span>Δ <b>${signed(row.delta_pct)}</b></span>`,
      `Reference entry <b>${cell(reference)}</b> · this run's AA range <b>${cell(aaRange)}</b>`);
  }));
}

function termRows(comparison) {
  const rows = comparison?.terms || [];
  if (!rows.length) return '<p class="hint">This comparison holds no bonded terms.</p>';
  return measureList(rows.map(row => {
    const overlap = number(row.overlap);
    const verdict = row.compared === false ? 'not compared' : (overlap !== null && overlap >= 0.5
      ? 'overlapping' : 'weak overlap');
    const claim = row.compared === false || overlap === null || overlap < 0.5;
    return measure(
      `<span class="rvm-lead">${cell(row.section || '')}</span> <b>${cell(row.beads || '')}</b>
       <span class="rvm-badge${claim ? ' rvm-claim' : ''}">${verdict}</span>`,
      `<span>AA <b>${fixed(row.aa?.mean, 2)} ± ${fixed(row.aa?.std, 2)}</b></span>
       <span>CG <b>${fixed(row.cg?.mean, 2)} ± ${fixed(row.cg?.std, 2)}</b></span>
       <span>Δ <b>${delta(row.delta)}</b></span><span>overlap <b>${fixed(row.overlap, 3)}</b></span>`);
  }));
}

function crossCheckRows(crossCheck) {
  const rows = crossCheck.rows || [];
  const unmeasured = (crossCheck.unmeasured || []).map(entry => measure(
    `<b>${cell((entry.beads || []).join('–'))}</b><span class="rvm-badge">not measured</span>`,
    '', cell(entry.reason)));
  if (!rows.length && !unmeasured.length) return '<p class="hint">The published analysis compares no terms.</p>';
  const measured = rows.map(row => {
    const ours = row.ours || {}, estimate = row.estimate || {};
    const verdict = row.verdicts_agree
      ? (ours.constraint ? 'both rigid' : 'both springs')
      : (ours.constraint ? 'we write rigid, the estimate reads a spring'
                         : 'we write a spring, the estimate reads rigid');
    return measure(
      `<b>${cell((row.beads || []).join('–'))}</b>
       <span class="rvm-badge${row.verdicts_agree ? '' : ' rvm-claim'}">${cell(verdict)}</span>`,
      `<span>ours <b>${fixed(ours.value, 3)} nm</b> ${ours.constraint
        ? '(constraint)' : `(k <b>${fixed(ours.force_constant, 1)}</b>)`}</span>
       <span>estimate <b>${fixed(estimate.value, 3)} nm</b> (k <b>${fixed(estimate.force_constant, 1)}</b>)</span>
       <span>Δ length <b>${delta(row.delta_value, 4)} nm</b></span>`);
  });
  return measureList([...measured, ...unmeasured]);
}

function dihedralRows(fit) {
  const rows = fit.rows || [];
  const unmeasured = (fit.unmeasured || []).map(entry => measure(
    `<b>${cell((entry.beads || []).join('–'))}</b><span class="rvm-badge">not measured</span>`,
    '', cell(entry.reason)));
  if (!rows.length && !unmeasured.length) return '<p class="hint">The published analysis fits no declared dihedral.</p>';
  const measured = rows.map(row => {
    const ours = row.ours || {}, fitted = row.fit || {};
    const verdict = row.multiplicities_agree
      ? `both ${ours.multiplicity}-fold`
      : `we write ${ours.multiplicity}-fold, the criterion chooses ${fitted.dominant_multiplicity}-fold`;
    return measure(
      `<b>${cell((row.beads || []).join('–'))}</b>
       <span class="rvm-badge${row.multiplicities_agree ? '' : ' rvm-claim'}">${cell(verdict)}</span>`,
      `<span>our φ <b>${fixed(ours.phase_deg, 1)}°</b></span><span>our k <b>${fixed(ours.force_constant_kj_mol, 2)}</b></span>
       <span>n <b>${ours.multiplicity}</b></span><span>fit keeps <b>${fitted.terms}</b></span>
       <span>fit's n <b>${fitted.dominant_multiplicity}</b></span>
       <span>residual <b>${fixed(fitted.residual_rms_kj_mol, 2)}</b></span>`);
  });
  return measureList([...measured, ...unmeasured]);
}

function surfaceRows(surfaces) {
  const statistics = Object.entries(surfaces.statistics || {});
  if (!statistics.length) return '<p class="hint">The published analysis states no statistics.</p>';
  const rows = statistics.map(([model, stat]) => {
    const start = number(stat.start_ps), end = number(stat.end_ps);
    const duration = start === null || end === null ? '—' : `${((end - start) / 1000).toFixed(1)} ns`;
    return `<tr><th scope="row">${cell(model)}</th><td>${number(stat.frames) ?? '—'}</td><td>${duration}</td>
      <td>${fixed(stat.mean_nm2, 3)}</td><td>${fixed(stat.std_nm2, 3)}</td></tr>`;
  }).join('');
  return `<div class="table-scroll"><table class="rvm-table">
    <caption>Mean SASA per model · probe ${fixed(surfaces.probe_nm, 3)} nm · nanometres squared</caption>
    <thead><tr><th scope="col">Model</th><th scope="col">Frames</th><th scope="col">Duration</th>
      <th scope="col">Mean SASA</th><th scope="col">SD</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function surfaceFigure(surfaces, run) {
  if (!surfaces.available || !surfaces.figure) return '';
  const relative = String(surfaces.figure).split('/').map(encodeURIComponent).join('/');
  return `<iframe class="rvm-frame" loading="lazy" title="Solvent-accessible envelopes, drawn by the surfaces analysis"
    src="/api/jobs/${encodeURIComponent(run)}/artifacts/${relative}?inline=1"></iframe>`;
}

function overlapFigure(overlap, run) {
  if (!overlap.available || !overlap.figure) return '';
  const relative = String(overlap.figure).split('/').map(encodeURIComponent).join('/');
  return `<iframe class="rvm-frame" loading="lazy"
    title="Bead pair overlap between the atomistic reference and the coarse-grained model"
    src="/api/jobs/${encodeURIComponent(run)}/artifacts/${relative}?inline=1"></iframe>`;
}

// The heatmap is 55 cells for an 11-bead molecule, so the numbers a reader would otherwise have to read off it are
// stated: how many pairs, the mean, and the three that agree least, worst first.
function overlapDetail(overlap) {
  const pairs = overlap.pairs || [], values = overlap.overlaps || [];
  const rows = pairs.map((pair, index) => ({ pair: (pair || []).join(' → '), value: Number(values[index]) }))
    .filter(row => Number.isFinite(row.value));
  if (!rows.length) return 'The published analysis states no pair overlaps.';
  const mean = rows.reduce((sum, row) => sum + row.value, 0) / rows.length;
  const worst = [...rows].sort((first, second) => first.value - second.value).slice(0, 3)
    .map(row => `${row.pair} at ${row.value.toFixed(3)}`).join('; ');
  const range = Array.isArray(overlap.range_nm) ? overlap.range_nm : null;
  const frames = overlap.frames || {};
  return `${rows.length} bead pairs, mean overlap ${mean.toFixed(3)} over `
    + `${range ? `${Number(range[0]).toFixed(2)}–${Number(range[1]).toFixed(2)} nm` : 'the shared bin range'}. `
    + `Furthest apart: ${worst}. Frames: reference ${frames.reference ?? '—'}, model ${frames.model ?? '—'}. `
    + 'Each pair is a distance inside one residue, so nothing here says anything about the bonds between residues.';
}

// ------------------------------------------------------------------------------------------------ the graphics

function drawDisplacement(host, shape) {
  // Per bead, in picometres: the comparison publishes nanometres, and at 4 pm an axis in nanometres reads as
  // zero. The beads the rigid-body fit used are filled, so a reader can see which numbers the fit rests on. The
  // token lives on the host, not in this module: two monitors draw two charts through the same function.
  const chart = host.querySelector('.rvm-chart');
  if (!chart) return;
  const beads = (shape && shape.per_bead) || [];
  if (!beads.length) {
    chart.textContent = 'The per-bead displacement is not in this comparison.';
    return;
  }
  const token = (Number(host.dataset.draw) || 0) + 1;
  host.dataset.draw = String(token);
  const current = () => Number(host.dataset.draw) === token;
  ensurePlotly().then(() => {
    if (!current()) return;
    const labels = beads.map(entry => `(${entry.bead?.[0]},${entry.bead?.[1]})`);
    const values = beads.map(entry => Number(entry.displacement_nm) * 1000);
    const fitted = new Set((shape.fit_beads || []).map(bead => `(${bead[0]},${bead[1]})`));
    return window.Plotly.react(chart, [{
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
  }).catch(error => {
    if (current()) chart.textContent = `The per-bead displacement could not be drawn: ${error.message}.`;
  });
}

// ------------------------------------------------------------------------------------------------- the sections

async function paintGeometry(host, {job, isCurrent, button, refresh, queue}) {
  const body = await loadBody(host, job, isCurrent, queue ? () => queue(
    `/api/jobs/${encodeURIComponent(job.id)}/mapping-consistency`, {},
    () => 'Mapping comparison queued.') : null);
  if (!body || !isCurrent()) return;
  if (refresh && host.dataset.attempt === String(body.attempt)) return;
  host.dataset.attempt = String(body.attempt);
  const comparison = body.comparison || {};
  const rows = comparison.pairs?.rows || [];
  if (button) button.textContent = `Geometry (${plural(rows.length, 'pair')})`;
  host.innerHTML = `${identity(body)}${pairRows(comparison)}
    <p class="hint">These constraints are fitted from the atomistic reference they are compared against here, so
      agreement is a check that the mapping, the mapped trajectory and the simulated trajectory are one assignment.
      It is not a statement about the model's physics, and it is not evidence from experiment.</p>
    <h4>Per-bead displacement after a rigid-body fit</h4>
    <p class="hint">${number(comparison.displacement?.rmsd_nm) === null ? '' : `rmsd
      ${fixed(comparison.displacement.rmsd_nm)} nm, max ${fixed(comparison.displacement.max_nm)} nm over
      ${comparison.displacement.aa_frames ?? '—'} AA and ${comparison.displacement.cg_frames ?? '—'} CG frames.
      Filled bars are the beads that own atoms and were used for the fit; the others are carried for completeness.`}</p>
    <div class="rvm-chart"></div>`;
  drawDisplacement(host, comparison.displacement);
}

async function paintBonded(host, {job, isCurrent, button, refresh}) {
  const body = await loadBody(host, job, isCurrent);
  if (!body || !isCurrent()) return;
  if (refresh && host.dataset.attempt === String(body.attempt)) return;
  host.dataset.attempt = String(body.attempt);
  const comparison = body.comparison || {};
  const crossCheck = body.bonded_cross_check || {};
  const dihedral = body.dihedral_fit || {};
  if (button) button.textContent = `Bonded terms (${(comparison.terms || []).length})`;
  const crossCheckNote = crossCheck.available
    ? `Attempt <b>${cell(crossCheck.attempt)}</b>, published ${cell(shortTime(crossCheck.published_at))} UTC.
      <b>${cell(crossCheck.ours_from || 'the run topology')}</b> · ${cell(crossCheck.ours_provenance || '')}
      Threshold ${fixed(crossCheck.threshold, 0)} kJ/mol/nm² at ${fixed(crossCheck.temperature, 2)} K.
      ${(crossCheck.disagreements || []).length
        ? `${(crossCheck.disagreements || []).length} of ${(crossCheck.rows || []).length} terms where the two sides
          disagree: ${(crossCheck.disagreements || []).map(pair => cell(pair.join('–'))).join(', ')}.`
        : 'No term disagrees.'} ${crossCheck.validated ? '' : 'Not scientifically validated.'}`
    : (crossCheck.reason || 'The run’s bonded cross-check has not been published.');
  const dihedralNote = dihedral.available
    ? `Attempt <b>${cell(dihedral.attempt)}</b>, published ${cell(shortTime(dihedral.published_at))} UTC.
      <b>${cell(dihedral.ours_from || 'the run topology')}</b> · ${cell(dihedral.ours_provenance || '')}
      ${dihedral.frames_measured ?? '—'} mapped frames at ${fixed(dihedral.temperature, 2)} K, multiplicity chosen
      by ${cell(String(dihedral.criterion || '').toUpperCase())}.
      ${(dihedral.disagreements || []).length
        ? `${(dihedral.disagreements || []).length} of ${(dihedral.rows || []).length} terms where the criterion
          chooses a different multiplicity from the tool.`
        : 'Every declared multiplicity is one the criterion chooses too.'}
      ${dihedral.validated ? '' : 'Not scientifically validated.'}`
    : (dihedral.reason || 'The run’s dihedral fit has not been published.');
  host.innerHTML = `<p class="rvm-identity">AA-mapped vs CG-simulated · topology
      <b>${cell(crossCheck.ours_from || dihedral.ours_from || 'the run’s own topology')}</b></p>
    ${termRows(comparison)}
    <p class="hint">Each bonded term the model carries, as it appears in the mapped atomistic trajectory and in the
      simulated coarse-grained one. <b>Overlap</b> is the shared area of the two histograms: 1 is identical, 0 is no
      overlap. Δ is the mean difference in the term's own unit (nm or degrees).</p>
    <div class="rvm-sub"><h4>Our fit against the independent estimate</h4>
      <p class="hint">${crossCheckNote}</p>
      ${crossCheck.available ? crossCheckRows(crossCheck) : ''}
      <p class="hint">${crossCheck.available ? (crossCheck.limitations || []).join(' ') : ''}</p>
    </div>
    <div class="rvm-sub"><h4>Dihedral terms · a criterion against the tool default</h4>
      <p class="hint">${dihedralNote}</p>
      ${dihedral.available ? dihedralRows(dihedral) : ''}
      <p class="hint">${dihedral.available ? (dihedral.limitations || []).join(' ') : ''}</p>
    </div>`;
}

async function paintShape(host, {job, isCurrent, button, refresh}) {
  const body = await loadBody(host, job, isCurrent);
  if (!body || !isCurrent()) return;
  if (refresh && host.dataset.attempt === String(body.attempt)) return;
  host.dataset.attempt = String(body.attempt);
  const comparison = body.comparison || {};
  const surfaces = body.surfaces || {};
  const overlap = body.overlap || {};
  if (button) {
    const available = [surfaces.available, overlap.available].filter(Boolean).length;
    button.textContent = `Shape and volume (${available})`;
  }
  host.innerHTML = `<p class="rvm-identity">AA vs CG · rigid-body fitted on the beads that own atoms</p>
    <p class="hint"><b>rmsd ${fixed(comparison.displacement?.rmsd_nm)} nm, max
      ${fixed(comparison.displacement?.max_nm)} nm over ${comparison.displacement?.aa_frames ?? '—'} AA and
      ${comparison.displacement?.cg_frames ?? '—'} CG frames.</b> The fitted beads are filled in the Geometry chart;
      the others are carried for completeness. The solvent-accessible envelopes below come from the separate
      surfaces analysis on this run.</p>
    <div class="rvm-sub"><h4>Solvent-accessible envelope</h4>
      <p class="hint">${surfaces.available
        ? `Attempt <b>${cell(surfaces.attempt)}</b>, published ${cell(shortTime(surfaces.published_at))} UTC.
          ${cell(surfaces.rendering || '')} ${surfaces.validated ? '' : 'Not scientifically validated.'}`
        : cell(surfaces.reason || 'The run’s envelope analysis has not been published.')}</p>
      ${surfaces.available ? surfaceRows(surfaces) : ''}
      ${surfaceFigure(surfaces, body.run || job.id)}
    </div>
    <div class="rvm-sub"><h4>Bead overlap</h4>
      <p class="hint">${overlap.available
        ? `Attempt <b>${cell(overlap.attempt)}</b>, published ${cell(shortTime(overlap.published_at))} UTC.
          ${cell(overlap.residue || 'The molecule')} against its own atomistic reference.
          ${overlap.figure ? '' : 'Its figure is no longer on disk, so only the numbers remain. '}
          ${overlap.validated ? '' : 'Not scientifically validated.'}`
        : cell(overlap.reason || 'The run’s bead-overlap analysis has not been published.')}</p>
      ${overlap.available ? `<p class="hint">${cell(overlapDetail(overlap))}</p>` : ''}
      ${overlapFigure(overlap, body.run || job.id)}
    </div>`;
}

// ------------------------------------------------------------------------------------------------- registration

const SECTIONS = [
  {
    name: 'mapping-geometry',
    label: 'Geometry',
    order: 10,
    serves: isComparisonRun,
    mount: ({host, job, isCurrent, button, queue}) => paintGeometry(host, {job, isCurrent, button, queue, refresh: false}),
    refresh: ({host, job, isCurrent, button, queue}) => paintGeometry(host, {job, isCurrent, button, queue, refresh: true}),
  },
  {
    name: 'mapping-bonded',
    label: 'Bonded terms',
    order: 20,
    serves: isComparisonRun,
    mount: ({host, job, isCurrent, button}) => paintBonded(host, {job, isCurrent, button, refresh: false}),
    refresh: ({host, job, isCurrent, button}) => paintBonded(host, {job, isCurrent, button, refresh: true}),
  },
  {
    name: 'mapping-shape',
    label: 'Shape and volume',
    order: 30,
    serves: isComparisonRun,
    mount: ({host, job, isCurrent, button}) => paintShape(host, {job, isCurrent, button, refresh: false}),
    refresh: ({host, job, isCurrent, button}) => paintShape(host, {job, isCurrent, button, refresh: true}),
  },
];

for (const section of SECTIONS) registerRunViewAnalysisSection(section);

registerRunViewAnalysisNotice({
  name: 'mapping-comparison-not-defined',
  serves: job => !isComparisonRun(job),
  text: notDefinedText,
});
