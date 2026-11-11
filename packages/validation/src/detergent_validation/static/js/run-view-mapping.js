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
import { api, artifactText, plural } from '/static/js/shared.js';
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

//: Which runs have a comparison to read. A run type is the fast answer; a record that predates the type but holds a
//: published comparison is served too, because the endpoint answers for it and hiding the tab would be a second
//: answer to the same question.
function isComparisonRun(job) {
  if (!job) return false;
  const kind = (job.parameterization || {}).kind || job.cg_model_kind || 'revision';
  if (String(job.run_type || '') === 'cg' && kind === 'revision') return true;
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

function measure(head, values, context, itemId) {
  // `data-item` is the map's own row identity: an attention item focuses the row it names, and the map controller
  // owns the convention (`pair:<index>` / `term:<index>`). It is empty on rows the map does not rank.
  return `<article class="rvm-measure"${itemId ? ` data-item="${cell(itemId)}" aria-selected="false"` : ''}>
    <div class="rvm-head">${head}</div>
    <div class="rvm-values">${values}</div>
    ${context ? `<p class="rvm-context">${context}</p>` : ''}
  </article>`;
}

function pairRows(comparison) {
  const rows = comparison?.pairs?.rows || [];
  if (!rows.length) return '<p class="hint">This comparison holds no constrained pairs.</p>';
  return measureList(rows.map((row, index) => {
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
      `Reference entry <b>${cell(reference)}</b> · this run's AA range <b>${cell(aaRange)}</b>`,
      `pair:${index}`);
  }));
}

function termRow(row, index) {
  const overlap = number(row.overlap);
  const verdict = row.compared === false ? 'not compared' : (overlap !== null && overlap >= 0.5
    ? 'overlapping' : 'weak overlap');
  const claim = row.compared === false || overlap === null || overlap < 0.5;
  return measure(
    `<span class="rvm-lead">${cell(row.section || '')}</span> <b>${cell(row.beads || '')}</b>
     <span class="rvm-badge${claim ? ' rvm-claim' : ''}">${verdict}</span>`,
    `<span>AA <b>${fixed(row.aa?.mean, 2)} ± ${fixed(row.aa?.std, 2)}</b></span>
     <span>CG <b>${fixed(row.cg?.mean, 2)} ± ${fixed(row.cg?.std, 2)}</b></span>
     <span>Δ <b>${delta(row.delta)}</b></span><span>overlap <b>${fixed(row.overlap, 3)}</b></span>`,
    '', `term:${index}`);
}

//: A term kind that collapses: usually there are more rows than a reader wants between them and the next heading, so
//: each group is one disclosure around the same measure rows. Collapsed by default; the map's focus opens the group
//: that holds the row it names. The summary is a real `<summary>` so keyboard and assistive technology get the
//: disclosure for free. Bond and angle rows keep the source order of their kind; dihedrals stay flat after the groups.
function termGroup(label, rows, hint) {
  return `<details class="rvm-term-group">
    <summary class="rvm-term-summary">${label} (${rows.length})<span class="rvm-term-summary-hint">${hint}</span></summary>
    <div class="rvm-measures">${rows.join('')}</div>
  </details>`;
}

function termRows(comparison) {
  const rows = comparison?.terms || [];
  if (!rows.length) return '<p class="hint">This comparison holds no bonded terms.</p>';
  const bonds = [], angles = [], flat = [];
  rows.forEach((row, index) => {
    const section = String(row.section || '');
    if (section === 'bonds') bonds.push(termRow(row, index));
    else if (section === 'angles') angles.push(termRow(row, index));
    else flat.push(termRow(row, index));
  });
  const parts = [];
  if (bonds.length) parts.push(termGroup('Bonds', bonds, 'measured bond rows'));
  if (angles.length) parts.push(termGroup('Angles', angles, 'measured angle rows'));
  if (flat.length) parts.push(measureList(flat));
  return parts.join('');
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

//: The four names are the producer's own statistics keys, so the block below the heading and the table speak the same
//: words. Every model is explained even when the published statistics omit it: a mapping that declares no rings
//: publishes no "Mapped ring-scaled" row, and its line says why rather than leaving a described model unexplained.
//: The AA run id is the Shape identity line's, not repeated here; the AA line points at it.
function surfaceModels() {
  return `<div class="rvm-models" role="group" aria-label="What the four models are">
    <p class="lead"><b>SASA</b> (solvent-accessible surface area) is how much of a molecule’s surface a solvent-sized
      probe could touch, in nm². Four models are measured here; only one is this run’s own data.</p>
    <dl>
      <dt>AA</dt>
      <dd>the <b>atomistic reference</b>: a separate all-atom simulation of the same molecule (the AA source run named
        above), every atom present, none grouped into beads. Not this CG run’s data.</dd>
      <dt>Mapped raw</dt>
      <dd>the same AA frames, with each bead placed at the average position of the atoms it owns (a virtual site sits
        at the average of its parent beads). Still the reference; no coarse-grained force field was used.</dd>
      <dt>Mapped ring-scaled</dt>
      <dd>the same mapped frames with <b>ring dilation</b>: each declared ring’s beads are moved out from that ring’s
        centre by the ring’s own scale, a number the mapping declares between 0.5 and 2.0. A rough illustration, and
        this row is absent when the mapping declares no rings.</dd>
      <dt>Simulated CG <span class="rvm-own">this run</span></dt>
      <dd>this run’s own coarse-grained trajectory, where each bead stands for a group of atoms. The only row computed
        from this run; it is what the scene and the SASA chart compare with AA.</dd>
    </dl>
  </div>`;
}

//: Three columns and nothing else: the frames and the span are the trajectory's, not a property of the mean, and the
//: probe is already stated in the note above. Numbers are nowrap so two rows read as one column of numbers; the table
//: sits beside the plot in a full-width card and stacks under it otherwise (the sheet owns that placement). Only the
//: Simulated CG row is this run's own data, so it alone carries the text marker; the sentence under the table says
//: what the other rows are.
function surfaceRows(surfaces) {
  const statistics = Object.entries(surfaces.statistics || {});
  if (!statistics.length) return '<p class="hint">The published analysis states no statistics.</p>';
  const rows = statistics.map(([model, stat]) => `<tr><th scope="row">${cell(model)}${
    model === 'Simulated CG' ? ' <span class="rvm-own">this run</span>' : ''}</th>
      <td>${fixed(stat.mean_nm2, 3)}</td><td>${fixed(stat.std_nm2, 3)}</td></tr>`).join('');
  return `<div class="table-scroll"><table class="rvm-table rvm-table-compact">
    <thead><tr><th scope="col">Model</th><th scope="col">Mean SASA</th><th scope="col">SD</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="hint rvm-surface-caption">The AA, Mapped raw and Mapped ring-scaled rows are AA-derived context, not
      independent evidence: they come from the same atomistic frames. None of these numbers is an experiment.</p></div>`;
}

function surfacePairMarkup(surfaces) {
  if (surfaces.aa_cg_comparison) {
    return `<div class="rvm-checks">
      <label><input type="checkbox" data-surface-model="aa" checked> AA reference</label>
      <label><input type="checkbox" data-surface-model="cg" checked> Simulated CG</label>
    </div>
    <div class="rvm-surface-plot" role="img"
      aria-label="AA reference and Simulated CG solvent-accessible envelopes in one scene"></div>`;
  }
  return `<div class="rvm-surface-fallback"><p class="hint">This surfaces attempt predates the AA vs Simulated CG
    pair. The SASA table and series below are this attempt's own; <b>Recalculate surfaces</b> publishes the two
    panels.</p></div>`;
}

// The surfaces analysis publishes the primary pair as data: two centred meshes, the same probe and the same extent.
// The card draws them in one scene with the Plotly it already loads, so the primary pair is not one column among the
// measured variants and no second Plotly bundle is loaded.

//: `gmx sasa -o` writes `time(ps) area(nm^2)`; the chart reads the same file the analysis measured.
function parseSasaSeries(text) {
  const rows = [];
  for (const line of String(text || '').split(/\r?\n/)) {
    const clean = line.trim();
    if (!clean || clean.startsWith('#') || clean.startsWith('@')) continue;
    const [time, area] = clean.split(/\s+/);
    const x = number(time), y = number(area);
    if (x !== null && y !== null) rows.push([x / 1000, y]);
  }
  return rows;
}

//: One scene, four traces: each model's mesh and its markers. The two checkboxes are the legend -- the scene's own
//: legend stays off -- and `data-surface-model` says which pair of traces a box owns.
function drawSurfacePair(pane, data) {
  const plotHost = pane?.querySelector('.rvm-surface-plot');
  const panels = Array.isArray(data?.panels) ? data.panels : [];
  if (!plotHost || panels.length < 2) return;
  const extent = number(data.extent) ?? 1;
  //: Trace indices are the checkbox contract: 0 and 1 are AA, 2 and 3 are Simulated CG.
  const traces = [];
  panels.slice(0, 2).forEach(panel => {
    const mesh = panel.mesh || {}, markers = panel.markers || {};
    traces.push(
      {type: 'mesh3d', x: mesh.x, y: mesh.y, z: mesh.z, i: mesh.i, j: mesh.j, k: mesh.k,
       color: panel.colour, opacity: .45, name: panel.label, showlegend: false, hoverinfo: 'skip', visible: true},
      {type: 'scatter3d', x: markers.x, y: markers.y, z: markers.z, mode: 'markers',
       marker: {size: markers.size ?? 4, color: markers.colour || '#26384f', opacity: .9},
       name: markers.name || panel.label, showlegend: false, hoverinfo: 'skip', visible: true});
  });
  ensurePlotly().then(() => window.Plotly.react(plotHost, traces, {
    margin: {l: 0, r: 0, t: 0, b: 0}, height: 230, showlegend: false,
    scene: {aspectmode: 'cube', camera: {eye: {x: 1.4, y: 1.4, z: 1.1}},
      xaxis: {title: {text: 'x (nm)', font: {size: 11}}, range: [-extent, extent]},
      yaxis: {title: {text: 'y (nm)', font: {size: 11}}, range: [-extent, extent]},
      zaxis: {title: {text: 'z (nm)', font: {size: 11}}, range: [-extent, extent]}},
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  }, {displayModeBar: false, responsive: true})).then(() => {
    observePlotResize(plotHost);
    for (const box of pane.querySelectorAll('input[data-surface-model]')) {
      const indices = box.dataset.surfaceModel === 'aa' ? [0, 1] : [2, 3];
      box.onchange = () => window.Plotly.restyle(plotHost, {visible: box.checked}, indices);
    }
  }).catch(error => {
    plotHost.textContent = `The AA vs Simulated CG pair could not be drawn: ${error.message}.`;
  });
}

function drawSasaChart(host, series) {
  if (!host || !series.length) return;
  ensurePlotly().then(() => {
    const traces = series.map(entry => ({
      type: 'scatter', mode: 'lines', name: entry.label,
      x: entry.rows.map(row => row[0]), y: entry.rows.map(row => row[1]),
      line: {color: entry.colour, width: 1.6},
      hovertemplate: `${entry.label} · %{x:.2f} ns · %{y:.3f} nm²<extra></extra>`,
    }));
    return window.Plotly.react(host, traces, {
      margin: {l: 52, r: 12, t: 6, b: 34}, height: 240,
      xaxis: {title: {text: 'time (ns)', font: {size: 11}}},
      yaxis: {title: {text: 'SASA (nm²)', font: {size: 11}}},
      legend: {orientation: 'h', y: 1.14, x: 0, font: {size: 12}},
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    }, {displayModeBar: false, responsive: true}).then(() => observePlotResize(host));
  }).catch(error => {
    host.textContent = `The SASA chart could not be drawn: ${error.message}.`;
  });
}

function overlapFigure(overlap, run) {
  if (!overlap.available || !overlap.figure) return '';
  const relative = String(overlap.figure).split('/').map(encodeURIComponent).join('/');
  return `<iframe class="rvm-frame rvm-overlap-frame" loading="lazy"
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

//: A Plotly graph is sized once, when it is drawn. The second-monitor toggle doubles the card's width without a
//: window resize, so `responsive: true` never hears about it; watching the host is the one signal both cases deliver.
//: One observer per host: a repaint that rewrites the pane makes a new host, and its entry goes with the old node.
const plotResizes = new WeakMap();

export function observePlotResize(host) {
  if (!host || typeof ResizeObserver === 'undefined' || plotResizes.has(host)) return;
  let width = host.getBoundingClientRect().width;
  const observer = new ResizeObserver(entries => {
    if (!host.isConnected) { observer.disconnect(); return; }
    const next = entries[0]?.contentRect?.width ?? host.clientWidth;
    if (!Number.isFinite(next) || Math.abs(next - width) < 1) return;
    width = next;
    // Plotly refuses a host whose computed display is `none`; the section switch that hid it will show it again and
    // fire this observer once more, so the hidden step waits rather than rejecting.
    if (next <= 0 || getComputedStyle(host).display === 'none' || !window.Plotly || !host._fullLayout) return;
    Promise.resolve(window.Plotly.Plots.resize(host)).catch(() => {});
  });
  observer.observe(host);
  plotResizes.set(host, observer);
}

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
    }, { displayModeBar: false, responsive: true }).then(() => {
      if (current()) observePlotResize(chart);
    });
  }).catch(error => {
    if (current()) chart.textContent = `The per-bead displacement could not be drawn: ${error.message}.`;
  });
}

// ------------------------------------------------------------------------------------------------- the sections

//: The published Fast-Forward record. It is its own analysis attempt, so the Bonded pane reads it beside the
//: comparison; a run that has not published one answers `available: false` with its reason.
async function loadFf(job, isCurrent) {
  try {
    const body = await api(`/api/jobs/${encodeURIComponent(job.id)}/ff-interactions`);
    return isCurrent() ? body : null;
  } catch (error) {
    return {available: false, reason: error.message};
  }
}

function ffSourceLabel(ff) {
  if (ff?.source === 'consumed') {
    const revision = ff.reference?.revision;
    return `consumed · parameterization store${revision === undefined ? '' : ` · revision ${revision}`}`;
  }
  return ff?.source === 'fitted' ? 'fitted · stage 3 ff_inter' : 'Fast-Forward';
}

function ffPanelMarkup(ff) {
  if (!ff || !ff.available) {
    return `<h4>Fast-Forward · reference vs simulated</h4>
      <p class="hint">${cell(ff?.reason || 'No Fast-Forward interaction record has been published for this run yet.')}</p>`;
  }
  return `<div class="rvm-ff-head"><h4>Fast-Forward · reference vs simulated</h4>
      <span class="rvm-ff-source">${cell(ffSourceLabel(ff))}</span></div>
    <p class="hint">Select a bonded term to see its reference and simulated distributions. <b>Hellinger</b> below is
      Fast-Forward's own distance; the row's <b>overlap</b> badge is the dashboard's histogram intersection. They are
      different metrics.</p>
    <div class="rvm-ff-chart" hidden></div>
    <p class="rvm-ff-empty">A term with no reference or simulated side will say which one is absent.</p>`;
}

function drawFfChart(chart, term) {
  if (!chart) return;
  ensurePlotly().then(() => {
    const unit = term.unit === 'degrees' ? 'degrees' : 'nm';
    const traces = [
      {type: 'scatter', mode: 'lines', name: 'reference', x: term.reference.x, y: term.reference.density,
       line: {color: '#2864b5', width: 1.8}, hovertemplate: `reference · %{x:.3f} ${unit} · %{y:.4f}<extra></extra>`},
      {type: 'scatter', mode: 'lines', name: 'simulated', x: term.simulated.x, y: term.simulated.density,
       line: {color: '#188b75', width: 1.8, dash: 'dash'},
       hovertemplate: `simulated · %{x:.3f} ${unit} · %{y:.4f}<extra></extra>`},
    ];
    return window.Plotly.react(chart, traces, {
      margin: {l: 48, r: 10, t: 6, b: 34}, height: 200,
      xaxis: {title: {text: `bin (${unit})`, font: {size: 11}}},
      yaxis: {title: {text: 'probability density', font: {size: 11}}},
      legend: {orientation: 'h', y: 1.16, x: 0, font: {size: 12}},
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    }, {displayModeBar: false, responsive: true}).then(() => observePlotResize(chart));
  }).catch(error => {
    chart.textContent = `The distribution could not be drawn: ${error.message}.`;
  });
}

function ffMetric(label, value, what, className = '') {
  return `<div class="rvm-ff-metric ${className}"><span class="rvm-ff-metric-name">${cell(label)}</span>
    <b>${cell(value)}</b><span class="rvm-ff-metric-what">${cell(what)}</span></div>`;
}

//: One selected term's panel. The FF term is matched by the comparison's own label and section -- both analyses
//: describe the same topology term -- so a record from a different comparison cannot silently attach itself.
function showFfTerm(host, aside, ff, comparison, index) {
  const row = (comparison.terms || [])[index];
  if (!row) return;
  host.dataset.ffTerm = String(index);
  for (const article of host.querySelectorAll('[data-item^="term:"]')) {
    article.setAttribute('aria-selected', String(article.dataset.item === `term:${index}`));
  }
  const source = ffSourceLabel(ff);
  const head = `<div class="rvm-ff-head"><h4>Fast-Forward · ${cell(row.section || 'term')}</h4>
    <span class="rvm-ff-source">${cell(source)}</span></div>`;
  if (!ff || !ff.available) {
    aside.innerHTML = `${head}<p class="hint">${cell(ff?.reason
      || 'No Fast-Forward interaction record has been published for this run yet.')}</p>`;
    return;
  }
  const section = String(row.section || '');
  const label = String(row.beads || '');
  const term = (ff.terms || []).find(entry => entry.label === label && entry.section === section)
    || (ff.terms || []).find(entry => entry.label === label);
  if (!term) {
    aside.innerHTML = `${head}<p class="hint">${cell(label)}</p>
      <p class="hint">This term has no Fast-Forward distribution. It is in the comparison but not in the published
        FF term list, so its overlap number and the cross-check still apply.</p>`;
    return;
  }
  const absent = term.reference_missing || term.simulated_missing;
  const metrics = `<div class="rvm-ff-metrics">
      ${ffMetric('FF Hellinger distance', term.hellinger === undefined ? 'not scored' : fixed(term.hellinger, 3),
        'Fast-Forward ff_assess; 0 identical, 1 no overlap. Different from the overlap coefficient.', 'ff')}
      ${ffMetric('FF score', term.ff_score === undefined ? 'not scored' : fixed(term.ff_score, 3),
        "Fast-Forward's score for the same term; lower is closer.", 'ff')}
      ${ffMetric('Dashboard overlap coefficient', fixed(row.overlap, 3),
        'Histogram intersection of the dashboard comparison; 1 identical. Not the Hellinger distance.', 'overlap')}
    </div>`;
  if (absent) {
    const which = term.reference_missing ? 'reference' : 'simulated';
    const why = term.reference_missing || term.simulated_missing;
    aside.innerHTML = `${head}<p class="hint">${cell(row.section)} · <b>${cell(label)}</b> ·
      ${cell(term.unit === 'degrees' ? 'degrees' : 'nm')}</p>${metrics}
      <p class="rvm-ff-missing"><b>No ${cell(which)} distribution for this term.</b> ${cell(why)} One side alone is
        not a comparison.</p>`;
    return;
  }
  aside.innerHTML = `${head}<p class="hint">${cell(row.section)} · <b>${cell(label)}</b> ·
      ${cell(term.unit === 'degrees' ? 'degrees' : 'nm')} · bins from the analysis's own text distributions.</p>
    ${metrics}<div class="rvm-ff-chart"></div>`;
  drawFfChart(aside.querySelector('.rvm-ff-chart'), term);
}

//: The mirror of the map's `rvm-term-focus`: this pane selected a term and the comparison map owns the scene's
//: highlight. The event bubbles to the Analysis card, where the map listens; it carries the map's own id vocabulary
//: and nothing else, so the map and the rows cannot disagree about which term is selected.
function announceTermToMap(host, index) {
  if (!Number.isInteger(index) || index < 0) return;
  host.dispatchEvent(new CustomEvent('rvm-term-select', {
    bubbles: true, detail: {mode: 'mapping-bonded', itemId: `term:${index}`},
  }));
}

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
  host.innerHTML = `${identity(body)}
    <details class="rvm-term-group">
      <summary class="rvm-term-summary">Constrained pairs (${rows.length})
        <span class="rvm-term-summary-hint">measured pair rows</span></summary>
      ${pairRows(comparison)}
      <p class="hint">These constraints are fitted from the atomistic reference they are compared against here, so
        agreement is a check that the mapping, the mapped trajectory and the simulated trajectory are one assignment.
        It is not a statement about the model's physics, and it is not evidence from experiment.</p>
    </details>
    <h4>Per-bead displacement after a rigid-body fit</h4>
    <p class="hint">${number(comparison.displacement?.rmsd_nm) === null ? '' : `rmsd
      ${fixed(comparison.displacement.rmsd_nm)} nm, max ${fixed(comparison.displacement.max_nm)} nm over
      ${comparison.displacement.aa_frames ?? '—'} AA and ${comparison.displacement.cg_frames ?? '—'} CG frames.
      Filled bars are the beads that own atoms and were used for the fit; the others are carried for completeness.`}</p>
    <div class="rvm-chart"></div>`;
  drawDisplacement(host, comparison.displacement);
}

async function paintBonded(host, {job, isCurrent, button, refresh, queue}) {
  const [body, ff] = await Promise.all([loadBody(host, job, isCurrent), loadFf(job, isCurrent)]);
  if (!body || !isCurrent()) return;
  // The comparison's attempt is not the only record this pane shows: a cross-check, a dihedral fit or the FF
  // interaction record publishing later must repaint the pane even though the comparison itself is unchanged.
  const attemptKey = [body.attempt, body.bonded_cross_check?.attempt, body.dihedral_fit?.attempt,
    ff?.attempt, ff?.published_at].map(value => value ?? '').join('|');
  if (refresh && host.dataset.attempt === attemptKey) {
    // Returning to this section: the map may have cleared its item id when the section changed, and the pane's
    // remembered term is this section's selection. Hand it back; the published record is unchanged, so the index
    // still names this same row.
    if (host.dataset.ffTerm) announceTermToMap(host, Number(host.dataset.ffTerm));
    return;
  }
  host.dataset.attempt = attemptKey;
  // A selection belongs to one run's term list: a monitor that moves to another run must not open the same index
  // against the new comparison.
  if (host.dataset.run !== String(job.id)) {
    host.dataset.run = String(job.id);
    delete host.dataset.ffTerm;
  }
  // An index names a row in one attempt's published term list; a republished comparison is a new list, so the
  // remembered selection is dropped rather than pointed at whatever now holds that index.
  if (host.dataset.comparison !== String(body.attempt ?? '')) {
    host.dataset.comparison = String(body.attempt ?? '');
    delete host.dataset.ffTerm;
  }
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
    <div class="rvm-term-view">
      <div class="rvm-term-list" role="listbox" aria-label="Bonded terms">${termRows(comparison)}</div>
      <aside class="rvm-ff" data-ff-panel aria-live="polite">${ffPanelMarkup(ff)}</aside>
    </div>
    <p class="hint">Each bonded term the model carries, as it appears in the mapped atomistic trajectory and in the
      simulated coarse-grained one. <b>Overlap</b> is the shared area of the two histograms: 1 is identical, 0 is no
      overlap. Δ is the mean difference in the term's own unit (nm or degrees). Select a term for its Fast-Forward
      reference-vs-simulated distribution on the right; that chart's <b>Hellinger</b> is a different metric from
      <b>overlap</b>.</p>
    <div class="rvm-sub">
      <details class="rvm-sub-group">
        <summary>Our fit against the independent estimate</summary>
        <p class="hint">${crossCheckNote}</p>
        ${crossCheck.available ? crossCheckRows(crossCheck) : ''}
        <p class="hint">${crossCheck.available ? (crossCheck.limitations || []).join(' ') : ''}</p>
      </details>
    </div>
    <div class="rvm-sub"><h4>Dihedral terms · a criterion against the tool default</h4>
      <p class="hint">${dihedralNote}</p>
      ${dihedral.available ? dihedralRows(dihedral) : ''}
      <p class="hint">${dihedral.available ? (dihedral.limitations || []).join(' ') : ''}</p>
    </div>`;
  const aside = host.querySelector('[data-ff-panel]');
  if ((!ff || !ff.available) && aside) {
    addQueueButton(aside, job, queue,
      {label: 'Calculate Fast-Forward distributions', kind: 'ff-interactions',
       sentence: 'Fast-Forward distributions queued.'});
  }
  for (const article of host.querySelectorAll('[data-item^="term:"]')) {
    const index = Number(String(article.dataset.item).split(':')[1]);
    article.tabIndex = 0;
    article.setAttribute('role', 'option');
    // One selection in two views: this row paints the Fast-Forward panel and tells the comparison map which term
    // to highlight. The map never answers this event, so the two directions cannot echo each other.
    const activate = () => {
      showFfTerm(host, aside, ff, comparison, index);
      announceTermToMap(host, index);
    };
    article.addEventListener('click', activate);
    article.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); }
    });
  }
  // The map's term line and the row are one selection: the map announces the term it focused, and this pane shows
  // the same term. The listener is replaced on every repaint so two maps/two paints cannot stack handlers.
  host._ffAbort?.abort();
  const controller = new AbortController();
  host._ffAbort = controller;
  host.closest('.run-view-analysis')?.addEventListener('rvm-term-focus', event => {
    if (event.detail?.mode !== 'mapping-bonded') return;
    const index = Number(String(event.detail.itemId || '').split(':')[1]);
    if (Number.isInteger(index) && index >= 0) showFfTerm(host, aside, ff, comparison, index);
  }, {signal: controller.signal});
  if (host.dataset.ffTerm !== undefined) {
    const index = Number(host.dataset.ffTerm);
    if (Number.isInteger(index) && index >= 0 && index < (comparison.terms || []).length) {
      showFfTerm(host, aside, ff, comparison, index);
      announceTermToMap(host, index);
    } else {
      delete host.dataset.ffTerm;
    }
  }
}

//: The Shape section's missing analyses are started here: the generic queue route takes an empty body, so the button
//: names the kind and the card's own `queue` handles the task list and the refresh. One at a time: while a request is
//: in flight every queue button in this pane is disabled, so a double press cannot queue two attempts.
function addQueueButton(container, job, queue, {label, kind, sentence}) {
  if (!queue) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'secondary rvm-queue';
  button.textContent = label;
  button.onclick = async () => {
    // Both of the section's queue buttons share one press: whichever is clicked, neither can start a second
    // analysis while the first request is in flight.
    const scope = container.closest('.analysis-pane') || container;
    const peers = [...scope.querySelectorAll('.rvm-queue')];
    for (const peer of peers) peer.disabled = true;
    try {
      await queue(`/api/jobs/${encodeURIComponent(job.id)}/${kind}`, {}, () => sentence);
    } finally {
      for (const peer of peers) peer.disabled = false;
    }
  };
  container.append(button);
}

async function paintShape(host, {job, isCurrent, button, refresh, queue}) {
  const body = await loadBody(host, job, isCurrent);
  if (!body || !isCurrent()) return;
  // Surfaces and bead overlap are separate attempts on the same run: either one publishing later changes this pane
  // without changing the comparison's attempt.
  const attemptKey = [body.attempt, body.surfaces?.attempt, body.overlap?.attempt]
    .map(value => value ?? '').join('|');
  if (refresh && host.dataset.attempt === attemptKey) return;
  host.dataset.attempt = attemptKey;
  const run = body.run || job.id;
  const comparison = body.comparison || {};
  const surfaces = body.surfaces || {};
  const overlap = body.overlap || {};
  const statistics = surfaces.statistics || {};
  const primary = surfaces.available && statistics['AA'] && statistics['Simulated CG'];
  if (button) {
    const available = [surfaces.available, overlap.available].filter(Boolean).length;
    button.textContent = `Shape and volume (${available})`;
  }
  host.innerHTML = `<p class="rvm-identity">AA vs CG · rigid-body fitted on the beads that own atoms · AA source
      <b>${cell(body.reference_run_id || '—')}</b></p>
    <p class="hint"><b>rmsd ${fixed(comparison.displacement?.rmsd_nm)} nm, max
      ${fixed(comparison.displacement?.max_nm)} nm over ${comparison.displacement?.aa_frames ?? '—'} AA and
      ${comparison.displacement?.cg_frames ?? '—'} CG frames.</b> The fitted beads are filled in the Geometry chart;
      the others are carried for completeness.</p>
    <div class="rvm-sub" data-shape="surfaces"><h4>Surface area · AA vs Simulated CG</h4>
      ${surfaces.available ? surfaceModels() : ''}
      <p class="hint">${surfaces.available
        ? `Attempt <b>${cell(surfaces.attempt)}</b>, published ${cell(shortTime(surfaces.published_at))} UTC.
          ${cell(surfaces.rendering || '')} Probe ${fixed(surfaces.probe_nm, 3)} nm, the same on both panels.
          The mesh is the union of probe-inflated spheres (SAS), not a re-entrant solvent-excluded surface (SES).
          ${surfaces.validated ? '' : 'Not scientifically validated.'}`
        : cell(surfaces.reason || 'The run’s envelope analysis has not been published.')}</p>
      ${surfaces.available
        ? `<div class="rvm-surface-view">
            <div class="rvm-surface-plot-col">${surfacePairMarkup(surfaces)}</div>
            <div class="rvm-surface-table">${surfaceRows(surfaces)}</div>
          </div>`
        : ''}
      ${surfaces.available ? `<div class="rvm-sasa"><h4>SASA over time</h4>
        <p class="hint">Total solvent-accessible area from the analysis’s own <code>sasa.xvg</code>, AA and Simulated CG
          on one axis. SAS is not SES. SD is frame-to-frame variability, not uncertainty of the mean; a short
          trajectory does not establish convergence.</p>
        <div class="rvm-sasa-chart"></div></div>` : ''}
    </div>
    <div class="rvm-sub" data-shape="overlap"><h4>Bead overlap · separate analysis (not surface area)</h4>
      <p class="hint">${overlap.available
        ? `Attempt <b>${cell(overlap.attempt)}</b>, published ${cell(shortTime(overlap.published_at))} UTC.
          ${cell(overlap.residue || 'The molecule')} against its own atomistic reference.
          ${overlap.figure ? '' : 'Its figure is no longer on disk, so only the numbers remain. '}
          ${overlap.validated ? '' : 'Not scientifically validated.'}`
        : cell(overlap.reason || 'The run’s bead-overlap analysis has not been published.')}</p>
      ${overlap.available ? `<p class="hint">${cell(overlapDetail(overlap))}</p>` : ''}
      ${overlapFigure(overlap, run)}
    </div>`;
  const subs = host.querySelectorAll('.rvm-sub');
  if (!surfaces.available && subs[0]) {
    addQueueButton(subs[0], job, queue,
      {label: 'Calculate surfaces', kind: 'surfaces', sentence: 'Surfaces analysis queued.'});
  }
  if (!overlap.available && subs[1]) {
    addQueueButton(subs[1], job, queue,
      {label: 'Calculate bead overlap', kind: 'overlap', sentence: 'Bead overlap analysis queued.'});
  }
  // An attempt published before the pair JSON existed still has its SASA files and numbers; a new attempt is the
  // only way to publish the two-panel pair, so the pane states that and carries the action its sentence promises.
  if (surfaces.available && !surfaces.aa_cg_comparison && subs[0]) {
    addQueueButton(subs[0], job, queue,
      {label: 'Recalculate surfaces', kind: 'surfaces', sentence: 'Surfaces analysis queued.'});
  }
  if (!surfaces.available) return;
  if (surfaces.aa_cg_comparison) {
    const text = await artifactText(run, surfaces.aa_cg_comparison);
    if (!isCurrent()) return;
    if (text) {
      try {
        drawSurfacePair(host, JSON.parse(text));
      } catch (error) {
        const plot = host.querySelector('.rvm-surface-plot');
        if (plot) plot.textContent = `The AA vs Simulated CG pair could not be read: ${error.message}.`;
      }
    }
  }
  if (!primary) return;
  const seriesDefinitions = [
    {label: 'AA', stat: statistics['AA'], colour: '#2864b5'},
    {label: 'Simulated CG', stat: statistics['Simulated CG'], colour: '#188b75'},
  ];
  const loaded = await Promise.all(seriesDefinitions.map(async entry => {
    const text = entry.stat?.xvg ? await artifactText(run, entry.stat.xvg) : null;
    return {...entry, rows: parseSasaSeries(text)};
  }));
  if (!isCurrent()) return;
  const series = loaded.filter(entry => entry.rows.length >= 2);
  const chart = host.querySelector('.rvm-sasa-chart');
  if (series.length) drawSasaChart(chart, series);
  else if (chart) chart.textContent = 'No SASA series was published for this attempt.';
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
    mount: ({host, job, isCurrent, button, queue}) =>
      paintBonded(host, {job, isCurrent, button, queue, refresh: false}),
    refresh: ({host, job, isCurrent, button, queue}) =>
      paintBonded(host, {job, isCurrent, button, queue, refresh: true}),
  },
  {
    name: 'mapping-shape',
    label: 'Shape and volume',
    order: 30,
    serves: isComparisonRun,
    mount: ({host, job, isCurrent, button, queue}) =>
      paintShape(host, {job, isCurrent, button, queue, refresh: false}),
    refresh: ({host, job, isCurrent, button, queue}) =>
      paintShape(host, {job, isCurrent, button, queue, refresh: true}),
  },
];

for (const section of SECTIONS) registerRunViewAnalysisSection(section);

registerRunViewAnalysisNotice({
  name: 'mapping-comparison-not-defined',
  serves: job => !isComparisonRun(job),
  text: notDefinedText,
});
