// Mapping Validation: the AA-vs-CG comparison the analysis published, rendered as it was published.
//
// The numbers come from `/api/jobs/<id>/mapping-consistency`, which reads the attempt the analysis wrote
// rather than recomputing anything, so this panel cannot disagree with the artifact a reader can open. Two
// claims on this page are our own data and are badged (`inside the AA range`, `inside the AA spread`); the
// reference entry's values are printed as context with no verdict attached, and the two cards with nothing
// behind them say why instead of showing a substitute number.
import { $, api } from '/static/js/shared.js';
import { ensurePlotly } from '/static/js/plotly-loader.js';

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

// Which draw is the current one. The bundle arrives asynchronously and the reader can switch runs while it does, so a
// resolve that lands after a newer comparison must not paint the older bars over it. Module scope, because the token
// has to outlive the draw that took it: it is the newer draw that invalidates the older.
let drawGeneration = 0;

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

async function drawDisplacement(host, shape) {
  // Per bead, in picometres: the comparison publishes nanometres, and at 4 pm an axis in nanometres reads as
  // zero. The beads the rigid-body fit used are filled, so a reader can see which numbers the fit rests on.
  const token = ++drawGeneration;
  if (!host) return;
  const beads = (shape && shape.per_bead) || [];
  // This message describes a comparison with no per-bead numbers in it, and nothing else: a Plotly bundle
  // that has not been fetched yet is not a missing measurement, so it is fetched in front of the draw
  // rather than reported here as one.
  if (!beads.length) {
    host.textContent = 'The per-bead displacement is not in this comparison.';
    return;
  }
  try {
    await ensurePlotly();
  } catch (error) {
    if (token !== drawGeneration) return;
    host.textContent = `The per-bead displacement could not be drawn: ${error.message}.`;
    return;
  }
  if (token !== drawGeneration) return;
  const labels = beads.map(entry => `(${entry.bead?.[0]},${entry.bead?.[1]})`);
  const values = beads.map(entry => Number(entry.displacement_nm) * 1000);
  const fitted = new Set((shape.fit_beads || []).map(bead => `(${bead[0]},${bead[1]})`));
  try {
    await window.Plotly.react(host, [{
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
  } catch (error) {
    // The draw answers for its own failure, in the host it was given: `render` does not wait on this chart, so a
    // rejection here would be a rejection nobody is holding.
    if (token !== drawGeneration) return;
    host.textContent = `The per-bead displacement could not be drawn: ${error.message}.`;
  }
}

function acrossTable(body) {
  // The same beads' own letters in every molecule -- the interaction, not the ring it sits in.
  const molecules = body.molecules || [];
  const rows = body.signatures || [];
  const head = ['Bead types', 'Where', ...molecules, 'Spread', 'Reading']
    .map(name => `<th>${cell(name)}</th>`).join('');
  const columns = 2 + molecules.length + 2;
  if (!rows.length) {
    return { head, html: `<tr><td colspan="${columns}">No bead-type pair is shared by the loaded molecules.</td></tr>` };
  }
  const html = rows.map(signature => {
    const perMolecule = molecules.map(name => {
      const entry = signature.molecules[name];
      if (!entry) return '<td>—</td>';
      const pairs = (entry.pairs || []).map(pair => pair.join('–')).join(', ');
      const count = `${entry.rows} ${entry.rows === 1 ? 'pair' : 'pairs'}`;
      // The pairs are named, not just counted: a mean over unlike pairs is a different quantity, and only the
      // reader who can see which edges were averaged can tell.
      return `<td>${fixed(entry.atomistic_mean_nm)} <span class="hint">${cell(count)}: ${cell(pairs)}</span></td>`;
    }).join('');
    const reading = signature.pairs_match
      ? '<span class="badge">same edges</span>'
      : '<span class="badge validation-claim">different edges</span>';
    const spread = number(signature.spread_pct) === null ? '—' : `${number(signature.spread_pct).toFixed(2)}%`;
    return `<tr><td>${cell(signature.types.join(' – '))}</td><td>${cell(signature.role)}</td>`
      + `${perMolecule}<td>${spread}</td><td>${reading}</td></tr>`;
  }).join('');
  return { head, html };
}

function publishedComparison(job) {
  return (job.analyses || []).some(task => task.kind === 'mapping-consistency' && task.status === 'completed');
}


// The linkage: the bond, angles and dihedral that join the two rings. No `pairs` row can show it, because every
// row there is a constrained distance inside one ring -- which is exactly why the interaction that differs most
// between disaccharides was the one this panel could not see. A dihedral's published mean is a wrapped quantity,
// so its spread is withheld and the cell says so rather than showing a percentage that means nothing.
function linkageTable(body) {
  const molecules = body.molecules || [];
  const rows = body.linkages || [];
  const head = ['Term', 'Types', ...molecules, 'Spread'].map(name => `<th>${cell(name)}</th>`).join('');
  const columns = 3 + molecules.length;
  const measure = (entry, value) => {
    const parsed = number(value);
    if (parsed === null) return '—';
    return entry.section === 'bonds' ? `${parsed.toFixed(4)} nm` : `${parsed.toFixed(1)}°`;
  };
  if (!rows.length) {
    return { head, html: `<tr><td colspan="${columns}">No linkage term is stated by the loaded molecules.</td></tr>` };
  }
  const html = rows.map(entry => {
    const perMolecule = molecules.map(name => {
      const row = (entry.molecules || {})[name];
      if (!row) return '<td>—</td>';
      const terms = (row.terms || []).map(term => cell(term)).join(', ');
      return `<td>${measure(entry, row.atomistic_mean)} <span class="hint">${terms} → `
        + `${measure(entry, row.cg_mean)}</span></td>`;
    }).join('');
    const spread = entry.circular
      ? '<span class="badge">wrapped angle: no spread</span>'
      : (number(entry.spread_pct) === null ? '—' : `${number(entry.spread_pct).toFixed(2)}%`);
    return `<tr><td>${cell(entry.section)}</td><td>${cell(entry.types.join(' – '))}</td>`
      + `${perMolecule}<td>${spread}</td></tr>`;
  }).join('');
  return { head, html };
}

function shortTime(value) {
  return String(value ?? '').replace('T', ' ').slice(0, 16);
}


// The envelope analysis publishes SASA statistics and a self-contained figure of its own. The figure is served
// through the artifact route and framed rather than redrawn: it is a 3D scene built by the analysis that measured
// it, and a second renderer here would be a second thing to keep true.
function surfaceRows(surfaces) {
  const statistics = Object.entries(surfaces.statistics || {});
  if (!statistics.length) return '<tr><td colspan="5">The published analysis states no statistics.</td></tr>';
  return statistics.map(([model, stat]) => {
    const start = number(stat.start_ps), end = number(stat.end_ps);
    const duration = start === null || end === null ? '—' : `${((end - start) / 1000).toFixed(1)} ns`;
    return `<tr><td>${cell(model)}</td><td>${number(stat.frames) ?? '—'}</td><td>${duration}</td>`
      + `<td>${fixed(stat.mean_nm2, 3)}</td><td>${fixed(stat.std_nm2, 3)}</td></tr>`;
  }).join('');
}

function surfaceFigure(body) {
  const surfaces = body.surfaces || {};
  if (!surfaces.available || !surfaces.figure) return '';
  // Built from the path the route returned, relative to the run, and never from a filesystem path.
  const relative = String(surfaces.figure).split('/').map(encodeURIComponent).join('/');
  return `<iframe class="validation-surface-frame" loading="lazy"`
    + ` title="Solvent-accessible envelopes, drawn by the surfaces analysis"`
    + ` src="/api/jobs/${encodeURIComponent(body.run || '')}/artifacts/${relative}?inline=1"></iframe>`;
}

function overlapFigure(body) {
  const overlap = body.overlap || {};
  if (!overlap.available || !overlap.figure) return '';
  // Built from the path the route returned, relative to the run, and never from a filesystem path.
  const relative = String(overlap.figure).split('/').map(encodeURIComponent).join('/');
  return `<iframe class="validation-surface-frame" loading="lazy"`
    + ` title="Bead pair overlap between the atomistic reference and the coarse-grained model"`
    + ` src="/api/jobs/${encodeURIComponent(body.run || '')}/artifacts/${relative}?inline=1"></iframe>`;
}

// The heatmap is 55 cells for an 11-bead molecule, so the numbers a reader would otherwise have to read off it are
// stated: how many pairs, the mean, and the three that agree least, worst first.
function overlapDetail(overlap) {
  const pairs = overlap.pairs || [], values = overlap.overlaps || [];
  const rows = pairs.map((pair, index) => ({ pair: (pair || []).join(' → '), value: Number(values[index]) }))
    .filter((row) => Number.isFinite(row.value));
  if (!rows.length) return 'The published analysis states no pair overlaps.';
  const mean = rows.reduce((sum, row) => sum + row.value, 0) / rows.length;
  const worst = [...rows].sort((a, b) => a.value - b.value).slice(0, 3)
    .map((row) => `${row.pair} at ${row.value.toFixed(3)}`).join('; ');
  const range = Array.isArray(overlap.range_nm) ? overlap.range_nm : null;
  const frames = overlap.frames || {};
  return `${rows.length} bead pairs, mean overlap ${mean.toFixed(3)} over `
    + `${range ? `${Number(range[0]).toFixed(2)}–${Number(range[1]).toFixed(2)} nm` : 'the shared bin range'}. `
    + `Furthest apart: ${worst}. Frames: reference ${frames.reference ?? '—'}, model ${frames.model ?? '—'}. `
    + 'Each pair is a distance inside one residue, so nothing here says anything about the bonds between residues.';
}

// Constrained terms are named rather than numbered: a term the fit writes as a rigid rod and the measurement reads as
// a spring is a different molecule, and the numbers beside it would not show that. So the verdict column says which
// of the two sides is which, in words, rather than a tick.
function crossCheckRows(crossCheck) {
  const rows = crossCheck.rows || [];
  const unmeasured = (crossCheck.unmeasured || []).map((entry) =>
    `<tr><td>${cell((entry.beads || []).join('–'))}</td>`
    + `<td colspan="6">not measured · ${cell(entry.reason)}</td></tr>`).join('');
  if (!rows.length && !unmeasured.length) {
    return '<tr><td colspan="7">The published analysis compares no terms.</td></tr>';
  }
  const measured = rows.map((row) => {
    const ours = row.ours || {}, estimate = row.estimate || {};
    const verdict = row.verdicts_agree
      ? (ours.constraint ? 'both rigid' : 'both springs')
      : (ours.constraint ? 'we write rigid, the estimate reads a spring'
                         : 'we write a spring, the estimate reads rigid');
    const delta = Number.isFinite(Number(row.delta_value)) ? Number(row.delta_value) : null;
    return `<tr><td>${cell((row.beads || []).join('–'))}</td>`
      + `<td>${fixed(ours.value, 3)} nm</td>`
      + `<td>${ours.constraint ? 'constraint' : fixed(ours.force_constant, 1)}</td>`
      + `<td>${fixed(estimate.value, 3)} nm</td><td>${fixed(estimate.force_constant, 1)}</td>`
      + `<td>${delta === null ? '—' : `${delta > 0 ? '+' : ''}${delta.toFixed(4)} nm`}</td>`
      + `<td>${row.verdicts_agree ? cell(verdict) : `<strong>${cell(verdict)}</strong>`}</td></tr>`;
  }).join('');
  return measured + unmeasured;
}

// A dihedral's phase is only comparable across tools that share a sign convention, so the verdict column leads with
// the multiplicity -- which no convention can flip -- and the phases sit beside it as the detail they are. The report
// names that assumption in its own limitations rather than leaving it to this comment.
function dihedralFitRows(fit) {
  const rows = fit.rows || [];
  const unmeasured = (fit.unmeasured || []).map((entry) =>
    `<tr><td>${cell((entry.beads || []).join('–'))}</td>`
    + `<td colspan="7">not measured · ${cell(entry.reason)}</td></tr>`).join('');
  if (!rows.length && !unmeasured.length) {
    return '<tr><td colspan="8">The published analysis fits no declared dihedral.</td></tr>';
  }
  const measured = rows.map((row) => {
    const ours = row.ours || {}, fitted = row.fit || {};
    const verdict = row.multiplicities_agree
      ? `both ${ours.multiplicity}-fold`
      : `we write ${ours.multiplicity}-fold, the criterion chooses ${fitted.dominant_multiplicity}-fold`;
    return `<tr><td>${cell((row.beads || []).join('–'))}</td>`
      + `<td>${fixed(ours.phase_deg, 1)}°</td><td>${fixed(ours.force_constant_kj_mol, 2)}</td>`
      + `<td>${ours.multiplicity}</td><td>${fitted.terms}</td><td>${fitted.dominant_multiplicity}</td>`
      + `<td>${fixed(fitted.residual_rms_kj_mol, 2)}</td>`
      + `<td>${row.multiplicities_agree ? cell(verdict) : `<strong>${cell(verdict)}</strong>`}</td></tr>`;
  }).join('');
  return measured + unmeasured;
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
        + 'The fitted beads are filled; the others are carried for completeness. The solvent-accessible '
        + 'envelopes below come from the separate surfaces analysis on this run.'
      : 'The run’s shape analysis has not been published.';
    // Not awaited: the chart fetches a 4.8 MB bundle and answers for its own failure, and every card below this
    // line is text the panel already has. Waiting here made the reader's first sight of the comparison wait on a
    // download, for a picture that carries no number the tables do not.
    drawDisplacement($('#validation-shape-plot'), shape);
    const surfaces = body.surfaces || {};
    const note = $('#validation-surface-note');
    if (note) {
      note.textContent = surfaces.available
        ? `Attempt ${surfaces.attempt}, published ${shortTime(surfaces.published_at)} UTC. `
          + `${surfaces.rendering || ''} ${surfaces.validated ? '' : 'Not scientifically validated.'}`.trim()
        : (surfaces.reason || 'The run’s envelope analysis has not been published.');
    }
    const surfaceBody = $('#validation-surface-rows');
    if (surfaceBody) {
      surfaceBody.innerHTML = surfaces.available
        ? surfaceRows(surfaces)
        : '<tr><td colspan="5">No envelope analysis has been published for this run.</td></tr>';
    }
    const figureHost = $('#validation-surface-figure');
    if (figureHost) figureHost.innerHTML = surfaceFigure(body);
    const overlap = body.overlap || {};
    const overlapNote = $('#validation-overlap-note');
    if (overlapNote) {
      overlapNote.textContent = overlap.available
        ? `Attempt ${overlap.attempt}, published ${shortTime(overlap.published_at)} UTC. `
          + `${overlap.residue || 'The molecule'} against its own atomistic reference. `
          + `${overlap.figure ? '' : 'Its figure is no longer on disk, so only the numbers remain. '}`
          + `${overlap.validated ? '' : 'Not scientifically validated.'}`.trim()
        : (overlap.reason || 'The run’s bead-overlap analysis has not been published.');
    }
    const overlapDetailLine = $('#validation-overlap-detail');
    // A published analysis whose figure is gone still owes the reader its numbers, so the detail line does not
    // depend on the figure existing.
    if (overlapDetailLine) overlapDetailLine.textContent = overlap.available ? overlapDetail(overlap) : '';
    const overlapHost = $('#validation-overlap-figure');
    if (overlapHost) overlapHost.innerHTML = overlapFigure(body);
    const crossCheck = body.bonded_cross_check || {};
    const checkNote = $('#validation-crosscheck-note');
    if (checkNote) {
      const disagreements = crossCheck.disagreements || [];
      checkNote.textContent = crossCheck.available
        ? `Attempt ${crossCheck.attempt}, published ${shortTime(crossCheck.published_at)} UTC. `
          + `${crossCheck.ours_from || 'the run topology'} · ${crossCheck.ours_provenance || ''} `
          + `Threshold ${fixed(crossCheck.threshold, 0)} kJ/mol/nm² at ${fixed(crossCheck.temperature, 2)} K. `
          + (disagreements.length
              ? `${disagreements.length} of ${(crossCheck.rows || []).length} terms where the two sides disagree: `
                + `${disagreements.map((pair) => pair.join('–')).join(', ')}. `
              : 'No term disagrees. ')
          + `${crossCheck.validated ? '' : 'Not scientifically validated.'}`
        : (crossCheck.reason || 'The run’s bonded cross-check has not been published.');
    }
    const checkRows = $('#validation-crosscheck-rows');
    if (checkRows) {
      checkRows.innerHTML = crossCheck.available
        ? crossCheckRows(crossCheck)
        : '<tr><td colspan="7">No bonded cross-check has been published for this run.</td></tr>';
    }
    const checkCaption = $('#validation-crosscheck-caption');
    if (checkCaption && crossCheck.available) {
      checkCaption.textContent = 'Terms the run\u2019s topology declares, each against an independent estimate from the '
        + `same frames · ${crossCheck.frames_measured ?? '—'} mapped frames`;
    }
    const checkLimits = $('#validation-crosscheck-limits');
    if (checkLimits) {
      checkLimits.textContent = crossCheck.available ? (crossCheck.limitations || []).join(' ') : '';
    }
    const dihedralFit = body.dihedral_fit || {};
    const fitNote = $('#validation-dihedral-note');
    if (fitNote) {
      const disagreements = dihedralFit.disagreements || [];
      fitNote.textContent = dihedralFit.available
        ? `Attempt ${dihedralFit.attempt}, published ${shortTime(dihedralFit.published_at)} UTC. `
          + `${dihedralFit.ours_from || 'the run topology'} · ${dihedralFit.ours_provenance || ''} `
          + `${dihedralFit.frames_measured ?? '—'} mapped frames at ${fixed(dihedralFit.temperature, 2)} K, `
          + `multiplicity chosen by ${String(dihedralFit.criterion || '').toUpperCase()}. `
          + (disagreements.length
              ? `${disagreements.length} of ${(dihedralFit.rows || []).length} terms where the criterion chooses a `
                + 'different multiplicity from the tool. '
              : 'Every declared multiplicity is one the criterion chooses too. ')
          + `${dihedralFit.validated ? '' : 'Not scientifically validated.'}`
        : (dihedralFit.reason || 'The run’s dihedral fit has not been published.');
    }
    const fitRows = $('#validation-dihedral-rows');
    if (fitRows) {
      fitRows.innerHTML = dihedralFit.available
        ? dihedralFitRows(dihedralFit)
        : '<tr><td colspan="8">No dihedral fit has been published for this run.</td></tr>';
    }
    const fitLimits = $('#validation-dihedral-limits');
    if (fitLimits) {
      // The convention caveat is a limitation of the report, so it belongs in front of the reader rather than in the
      // code that draws it.
      fitLimits.textContent = dihedralFit.available
        ? [dihedralFit.limitations?.[0], ...(dihedralFit.limitations || []).slice(1)].join(' ')
        : '';
    }
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
    // The list is paged at 20 by default, and the oldest CG run is the one a reader most often wants to compare
    // against, so the panel asks for everything rather than for the newest page.
    const payload = await request('/api/jobs?limit=100');
    const jobs = (Array.isArray(payload) ? payload : (payload.jobs || payload.data || []))
      .filter(job => job.run_type === 'aa_cg');
    select.innerHTML = jobs.length
      ? jobs.map(job => `<option value="${job.id}">${job.id} · ${job.molecule_id || 'molecule'} · ${job.status}</option>`).join('')
      : '<option value="">No CG run yet</option>';
    if (wanted && jobs.some(job => job.id === wanted)) select.value = wanted;
    else if (jobs.length) select.value = jobs.find(job => job.status === 'completed')?.id || jobs[0].id;
  }

  async function loadAcross() {
    const tbody = $('#validation-across-rows');
    const head = $('#validation-across-head');
    const sources = $('#validation-across-sources');
    const linkageBody = $('#validation-linkage-rows');
    const linkageHead = $('#validation-linkage-head');
    if (!tbody || !head) return;
    const fallbackHead = '<th>Bead types</th><th>Where</th><th>Spread</th><th>Reading</th>';
    const linkageFallback = '<th>Term</th><th>Types</th><th>Spread</th>';
    const empty = (message) => {
      head.innerHTML = fallbackHead;
      tbody.innerHTML = `<tr><td colspan="4">${message}</td></tr>`;
      if (linkageHead) linkageHead.innerHTML = linkageFallback;
      if (linkageBody) linkageBody.innerHTML = `<tr><td colspan="3">${message}</td></tr>`;
      if (sources) sources.textContent = '';
    };
    try {
      const payload = await request('/api/jobs?limit=100');
      const jobs = (Array.isArray(payload) ? payload : (payload.jobs || payload.data || []))
        .filter(job => job.run_type === 'aa_cg' && job.status === 'completed' && publishedComparison(job));
      // One run per molecule: the route refuses two of a kind rather than letting the second replace the first.
      const byMolecule = new Map();
      for (const job of jobs) {
        const molecule = job.molecule_id || job.detergent || job.id;
        if (!byMolecule.has(molecule)) byMolecule.set(molecule, job.id);
      }
      if (byMolecule.size < 2) {
        empty(jobs.length === 1
          ? `${cell(Object.keys(Object.fromEntries(byMolecule))[0] || 'One molecule')} is the only molecule with a published comparison; a spread needs two.`
          : 'No completed coarse-grained run has a published comparison yet.');
        return;
      }
      const body = await request(`/api/runs/transferability?ids=${[...byMolecule.values()].join(',')}`);
      const table = acrossTable(body);
      head.innerHTML = table.head;
      tbody.innerHTML = table.html;
      if (linkageHead && linkageBody) {
        const linkage = linkageTable(body);
        linkageHead.innerHTML = linkage.head;
        linkageBody.innerHTML = linkage.html;
      }
      if (sources) {
        sources.textContent = 'Read from: ' + Object.entries(body.sources || {}).map(([molecule, entry]) =>
          `${molecule} ${entry.run} (attempt ${entry.attempt}, published ${shortTime(entry.published_at)} UTC)`
        ).join(' · ');
      }
    } catch (error) {
      empty(cell(error.message));
    }
  }

  async function mount() {
    if (!document.querySelector('#validation')) return;
    const select = $('#validation-run');
    if (!mounted) {
      select.addEventListener('change', load);
      $('#validation-refresh').addEventListener('click', () => { fillRuns().then(load); loadAcross(); });
    }
    await fillRuns();
    await load();
    await loadAcross();
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
