// The validation feature's comparison map: one bead scene above the Run view Analysis sections.
//
// Geometry, Bonded terms and Shape and volume are perspectives on one published record, not three charts. The map
// fetches `GET /api/jobs/<id>/mapping-consistency` and the run's own `stages/2_mapping/model.json` + `mapped.gro`,
// resolves the three bead vocabularies onto one key, and draws one `bonded-plot` scene. The section tabs recolour
// that scene; they do not replace it. `run-view-analysis.js` owns the host, hides it on Figures and calls
// `setMode(sectionName)` on every mapping section.
//
// Nothing here computes a measurement: every number is the published comparison's, and the reading ranks the
// record's own items rather than combining them into a score.
import { api } from '/static/js/shared.js';
import { mountBondedPlot } from '/static/js/bonded-plot.js';
import { registerRunViewAnalysisMap } from '/static/js/run-view.js';

const MODES = {
  'mapping-geometry': {title: 'Geometry', label: 'Pairs · displacement'},
  'mapping-bonded': {title: 'Bonded terms', label: 'Terms · overlap'},
  'mapping-shape': {title: 'Shape and volume', label: 'Bead overlap'},
};
//: Which file the scene is drawn from. The first is the run's own mapped frame; the fallback is an older tree whose
//: only frame is the CG leg's ligand.
const MODEL_PATH = 'stages/2_mapping/model.json';
const GRO_PATH = 'stages/2_mapping/mapped.gro';
const GRO_FALLBACK = 'stages/4_CG_sim/prod/lig_CG.gro';
//: A half-width card: the Bonded panel's 620 px scene is taller than the map's own reading needs.
const MAP_HEIGHT = 340;
//: Overlap inks, the draft's reading scale: green at or above 0.5, amber 0.3 to 0.5, red below, grey unmeasured.
const OVERLAP_GOOD = '#1f7a4d';
const OVERLAP_MID = '#c08a1f';
const OVERLAP_WEAK = '#c02a37';
const OVERLAP_MISSING = '#8b98a8';
const BELOW_THRESHOLD = 0.5;

/** The Shape reading's own fill: red at 0 overlap, amber at 0.5, green at 1. The comparison map passes it as
 *  `beadColor.ramp`, so the legend's gradient and the beads are one scale. */
const OVERLAP_STOPS = [[192, 42, 55], [224, 180, 74], [31, 122, 77]];
function overlapRamp(ratio) {
  const value = Math.max(0, Math.min(1, Number.isFinite(ratio) ? ratio : 0));
  const [low, high, blend] = value < 0.5 ? [0, 1, value / 0.5] : [1, 2, (value - 0.5) / 0.5];
  const colour = OVERLAP_STOPS[low].map((channel, index) =>
    Math.round(channel + (OVERLAP_STOPS[high][index] - channel) * blend));
  return `rgb(${colour.join(',')})`;
}

const numeric = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const plural = (count, one, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
const labelOf = (bead) => (Array.isArray(bead) ? `(${bead[0]},${bead[1]})` : String(bead ?? '—'));
const beadLabel = (bead) => (bead ? labelOf([bead.residue, bead.letter]) : '—');
const fixed = (value, digits = 2) => (numeric(value) === null ? '—' : numeric(value).toFixed(digits));
const signedPercent = (value, digits = 1) => {
  const parsed = numeric(value);
  return parsed === null ? '' : ` (Δ ${parsed >= 0 ? '+' : ''}${parsed.toFixed(digits)}%)`;
};

//: The same rule the sections use: a run type is the fast answer, and a published comparison is served even for a
//: record that predates the type.
function isComparisonRun(job) {
  if (!job) return false;
  if (String(job.run_type || '') === 'aa_cg') return true;
  return (job.analyses || []).some(task => task.kind === 'mapping-consistency');
}

//: A run-root path through the artifact route, as text. `null` means the file is not on disk, which the map states
//: rather than drawing an empty scene.
async function artifact(job, path) {
  const relative = String(path).split('/').map(encodeURIComponent).join('/');
  const response = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/artifacts/${relative}?inline=1`);
  if (!response.ok) return null;
  return response.text();
}

/** Atoms in a GRO frame, by name: `{1-based resid, resname, name, x, y, z}` fixed columns, positions in nm. */
function parseGro(text) {
  const lines = String(text || '').split(/\r?\n/);
  const count = Number((lines[1] || '').trim());
  const positions = new Map();
  if (!Number.isFinite(count)) return positions;
  for (let index = 2; index < 2 + count && index < lines.length; index += 1) {
    const line = lines[index] || '';
    if (line.length < 44) continue;
    const name = line.slice(10, 15).trim();
    const x = Number(line.slice(20, 28));
    const y = Number(line.slice(28, 36));
    const z = Number(line.slice(36, 44));
    if (name && [x, y, z].every(Number.isFinite)) positions.set(name, [x, y, z]);
  }
  return positions;
}

/** The published comparison's pair rows, with both beads resolved onto the exported names.
 *
 * A pair line needs two positions, so a row whose beads are missing from the model stays in the reading and gets a
 * grey state rather than a line drawn somewhere invented.
 */
function geometryPairs(comparison, alias) {
  return (comparison.pairs?.rows || []).map((row, index) => {
    const labels = (row.pair || []).map(labelOf);
    const beadKeys = (row.pair || []).map(part => alias(labelOf(part))).filter(Boolean);
    const status = row.unconstrained ? 'unconstrained'
      : row.inside_range === false ? 'outside' : 'inside';
    return {id: `pair:${index}`, index, row, label: labels.join(' – '), beadKeys, status,
            a: beadKeys[0] || null, b: beadKeys[1] || null};
  });
}

//: The mapping's section names are the term kinds the Bonded plot already styles. A proper dihedral is a dihedral.
const TERM_KIND = {'proper-dihedrals': 'dihedrals'};

/** One row per published term, coloured by overlap. A term the comparison did not measure is grey, never zero. */
function comparisonTerms(comparison, alias) {
  return (comparison.terms || []).map((row, index) => {
    const tokens = String(row.beads || '').split(' - ').map(token => token.trim()).filter(Boolean);
    const beadKeys = tokens.map(alias).filter(Boolean);
    const overlap = numeric(row.overlap);
    const compared = row.compared !== false && overlap !== null;
    return {id: `term:${index}`, index, row, label: tokens.join(' – '),
            kind: TERM_KIND[row.section] || row.section, beads: beadKeys,
            overlap: compared ? overlap : null,
            ink: !compared ? OVERLAP_MISSING
              : overlap >= BELOW_THRESHOLD ? OVERLAP_GOOD
                : overlap >= 0.3 ? OVERLAP_MID : OVERLAP_WEAK};
  });
}

function overlapPairs(overlap, alias) {
  const pairs = overlap.pairs || [], values = overlap.overlaps || [];
  return pairs.map((pair, index) => {
    if (!Array.isArray(pair)) return null;
    const a = alias(pair[0]), b = alias(pair[1]);
    const value = numeric(values[index]);
    if (!a || !b) return null;
    return {id: `overlap:${index}`, index, a, b, beadKeys: [a, b], value,
            label: `${a} – ${b}`};
  }).filter(Boolean);
}

// ---------------------------------------------------------------------------------------------------- the reading

function weakestTerms(terms) {
  return terms.filter(term => term.overlap !== null)
    .sort((first, second) => first.overlap - second.overlap);
}

function lowestOverlapPairs(pairs) {
  return pairs.filter(pair => pair.value !== null)
    .sort((first, second) => first.value - second.value);
}

function geometryReading(state) {
  const rows = state.comparison.pairs?.rows || [];
  const pairs = state.pairs;
  const outside = pairs.filter(pair => pair.status === 'outside');
  const unconstrained = pairs.filter(pair => pair.status === 'unconstrained');
  const displacements = [...state.displacement.entries()]
    .filter(([, value]) => numeric(value) !== null)
    .sort((first, second) => second[1] - first[1]);
  const largest = displacements[0] || null;
  const largestBead = largest ? state.byKey.get(largest[0]) : null;
  const rmsd = numeric(state.comparison.displacement?.rmsd_nm);
  const headline = rows.length
    ? `${plural(rows.length, 'pair')} · ${outside.length} outside the AA range · `
      + `${unconstrained.length} unconstrained`
      + (largest ? ` · largest displacement ${Math.round(largest[1])} pm at ${beadLabel(largestBead)}` : '')
    : 'No constrained pair is published for this comparison.';
  const caveat = '"Unconstrained" means the pinned entry states no constraint, not that the pair is free. '
    + `Displacement is after a rigid-body fit${rmsd === null ? '' : ` (rmsd ${fixed(rmsd, 4)} nm)`}; `
    + 'the AA observed range is this run\'s own and the pinned entry is carried as context, not as a pass mark.';
  const attention = outside.slice(0, 3).map(pair => ({
    rank: 0, actionable: true, itemId: pair.id, pairId: pair.id, beadKeys: pair.beadKeys,
    title: pair.label,
    detail: `outside the AA observed range${signedPercent(pair.row.delta_pct)}`,
    value: 'outside',
    status: `${pair.label} · outside the AA observed range`,
  }));
  if (attention.length < 3 && largest) {
    attention.push({
      rank: 0, actionable: true, itemId: null, beadKeys: [largest[0]],
      title: `${beadLabel(largestBead)} · largest displacement`,
      detail: `${Math.round(largest[1])} pm after the rigid-body fit`,
      value: `${Math.round(largest[1])} pm`,
      status: `${beadLabel(largestBead)} · displacement ${Math.round(largest[1])} pm`,
    });
  }
  if (attention.length < 3 && unconstrained.length) {
    attention.push({
      rank: 0, actionable: false,
      title: `${unconstrained.length} of ${rows.length} pairs unconstrained`,
      detail: 'the pinned entry states no constraint for them', value: 'context',
    });
  }
  return {title: 'Geometry', headline, caveat, attention};
}

function bondedReading(state) {
  const rows = state.comparison.terms || [];
  const measured = weakestTerms(state.terms);
  const below = measured.filter(term => term.overlap < BELOW_THRESHOLD);
  const weakest = measured[0] || null;
  const crossCheck = state.body?.bonded_cross_check || {};
  const dihedral = state.body?.dihedral_fit || {};
  const headline = rows.length
    ? `${plural(rows.length, 'term')} · ${below.length} below overlap 0.5`
      + (weakest ? ` · weakest ${weakest.kind} at ${fixed(weakest.overlap, 2)}` : '')
    : 'No bonded term is published for this comparison.';
  const caveat = 'Overlap is the shared area of the two histograms: 1 is identical and 0 is none. '
    + '0.5 is a reading threshold, not a validated cut, and the comparison is against this run\'s own atomistic '
    + 'reference rather than experiment.';
  const attention = measured.slice(0, 3).map(term => ({
    rank: 0, actionable: true, itemId: term.id, termId: term.id, beadKeys: term.beads,
    title: `${term.kind} · ${term.label}`,
    detail: `overlap ${fixed(term.overlap, 2)}${term.row.delta === null || term.row.delta === undefined
      ? '' : ` · Δ ${fixed(term.row.delta, 2)}`}`,
    value: fixed(term.overlap, 2),
    status: `${term.kind} · ${term.label} · overlap ${fixed(term.overlap, 2)}`,
  }));
  const disagreements = crossCheck.disagreements || [];
  if (attention.length < 3 && disagreements.length) {
    attention.push({
      rank: 0, actionable: false,
      title: `Cross-check: ${disagreements.length} of ${(crossCheck.rows || []).length} terms disagree`,
      detail: disagreements.map(pair => (Array.isArray(pair) ? pair.join('–') : String(pair))).join(', '),
      value: 'context',
    });
  }
  const multiplicity = dihedral.disagreements || [];
  if (attention.length < 3 && multiplicity.length) {
    attention.push({
      rank: 0, actionable: false,
      title: `Dihedral fit: ${multiplicity.length} of ${(dihedral.rows || []).length} terms read another multiplicity`,
      detail: multiplicity.map(pair => (Array.isArray(pair) ? pair.join('–') : String(pair))).join(', '),
      value: 'context',
    });
  }
  return {title: 'Bonded terms', headline, caveat, attention};
}

function shapeReading(state) {
  const overlap = state.body?.overlap || {};
  const surfaces = state.body?.surfaces || {};
  const pairs = lowestOverlapPairs(state.overlapPairs);
  const all = state.overlapPairs;
  const weakest = pairs[0] || null;
  const headline = overlap.available
    ? `${plural(all.length, 'bead pair')}` + (weakest ? ` · weakest ${fixed(weakest.value, 2)} at ${weakest.label}` : '')
      + (surfaces.available ? '' : ' · surfaces not published')
    : 'No bead-overlap analysis is published for this run.';
  const caveat = 'Bead overlap is a distance inside one residue; it says nothing about the bonds between residues. '
    + 'SASA is per model, not per bead, so it is not painted on the beads. '
    + (overlap.available ? '' : 'The Shape section can queue the missing analysis.');
  const attention = pairs.slice(0, 3).map(pair => ({
    rank: 0, actionable: true, itemId: pair.id, pairId: pair.id, beadKeys: pair.beadKeys,
    title: pair.label,
    detail: `mean bead overlap ${fixed(pair.value, 2)}`,
    value: fixed(pair.value, 2),
    status: `${pair.label} · overlap ${fixed(pair.value, 2)}`,
  }));
  if (attention.length < 3 && !surfaces.available) {
    attention.push({
      rank: 0, actionable: false, title: 'Surfaces not published',
      detail: 'the envelope is a separate analysis; the Shape section starts it', value: 'missing',
    });
  }
  if (attention.length < 3 && !overlap.available) {
    attention.push({
      rank: 0, actionable: false, title: 'Bead overlap not published',
      detail: 'the Shape section can queue it', value: 'missing',
    });
  }
  return {title: 'Shape and volume', headline, caveat, attention};
}

function readingFor(state) {
  if (state.mode === 'mapping-bonded') return bondedReading(state);
  if (state.mode === 'mapping-shape') return shapeReading(state);
  return geometryReading(state);
}

// ------------------------------------------------------------------------------------------------------- the scene

const titleText = (value) => String(value ?? '');

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function attentionNode(item, state, choose) {
  const line = document.createElement('li');
  if (item.actionable === false) {
    const context = element('div', 'rvm-attention-context');
    context.append(element('span', 'rvm-rank', String(item.rank)),
      (() => {
        const body = element('span');
        body.append(element('b', '', item.title), element('span', 'rvm-attention-detail', item.detail));
        return body;
      })(), element('span', 'rvm-attention-value', item.value));
    line.append(context);
    return line;
  }
  const button = document.createElement('button');
  button.type = 'button';
  button.dataset.item = item.itemId || '';
  button.setAttribute('aria-current', String(Boolean(item.itemId) && item.itemId === state.selected.itemId));
  const body = element('span');
  body.append(element('b', '', item.title), element('span', 'rvm-attention-detail', item.detail));
  button.append(element('span', 'rvm-rank', String(item.rank)), body,
    element('span', 'rvm-attention-value', item.value));
  button.onclick = () => choose(item);
  line.append(button);
  return line;
}

/** The map module. One instance per Analysis card; every mutable token lives in this closure, so two monitors on one
 *  page never share a selection, a mode or a draw token.
 */
export async function mount({host, job, side, isCurrent, queue}) {
  host.replaceChildren();
  host.classList.add('rvm-map');

  const head = element('div', 'rvm-map-head');
  const title = element('h3', 'rvm-map-title', 'Comparison map');
  const modeLabel = element('span', 'rvm-map-mode', MODES['mapping-geometry'].label);
  head.append(title, modeLabel);

  const body = element('div', 'rvm-map-body');
  const plotHost = element('div', 'rvm-map-plot');
  const missing = element('p', 'rvm-map-missing');
  missing.hidden = true;
  const legend = element('div', 'rvm-map-legend');
  const status = element('p', 'rvm-map-status', 'Reading the comparison…');
  body.append(plotHost, missing, legend, status);

  const reading = element('section', 'rvm-reading');
  reading.setAttribute('aria-label', 'Reading and attention');
  const headline = element('div', 'rvm-headline');
  const eyebrow = element('span', 'rvm-eyebrow', 'Reading · Geometry');
  const headlineText = element('p', 'rvm-headline-text');
  const caveat = element('p', 'rvm-caveat');
  headline.append(eyebrow, headlineText, caveat);
  const attentionWrap = element('div', 'rvm-attention-wrap');
  attentionWrap.append(element('h4', '', 'Ranked attention · top 3'));
  const attention = element('ol', 'rvm-attention');
  attentionWrap.append(attention);
  reading.append(headline, attentionWrap);
  host.append(head, body, reading);

  const state = {
    mode: 'mapping-geometry',
    body: null,
    comparison: {},
    model: null,
    beads: [],
    byKey: new Map(),
    aliases: new Map(),
    edges: [],
    displacement: new Map(),
    overlapByBead: new Map(),
    pairs: [],
    terms: [],
    overlapPairs: [],
    scene: false,
    selected: {beadKeys: [], itemId: null, pairId: null, termId: null},
    status: '',
    missingText: 'Reading the comparison…',
  };
  //: The map may be opened while the card is still reading its other answers; a token keeps a late answer out.
  let token = 0;
  const current = (mine) => mine === token && isCurrent();

  const plot = mountBondedPlot(plotHost, {
    onBeadSelection: (names) => {
      state.selected = {beadKeys: [...names], itemId: null, pairId: null, termId: null};
      state.status = '';
      renderAll();
    },
    onTermSelection: (picked) => {
      const id = Array.isArray(picked) ? picked[0] : picked;
      const term = state.terms.find(entry => entry.id === id);
      if (!term) return;
      state.selected = {beadKeys: term.beads, itemId: term.id, pairId: null, termId: term.id};
      state.status = `${term.kind} · ${term.label} · overlap ${fixed(term.overlap, 2)}`;
      renderAll();
    },
    onPairSelection: (picked) => {
      const id = Array.isArray(picked) ? picked[0] : picked;
      const pair = state.mode === 'mapping-shape'
        ? state.overlapPairs.find(entry => entry.id === id)
        : state.pairs.find(entry => entry.id === id);
      if (!pair) return;
      state.selected = {beadKeys: pair.beadKeys, itemId: pair.id, pairId: pair.id, termId: null};
      state.status = pairStatusText(pair);
      renderAll();
    },
    onPlotError: (message) => {
      if (!current(token)) return;
      state.scene = false;
      missing.hidden = false;
      missing.textContent = message;
      plotHost.hidden = true;
    },
  });

  function pairStatusText(pair) {
    if (state.mode === 'mapping-shape') return `${pair.label} · overlap ${fixed(pair.value, 2)}`;
    return `${pair.label} · ${pair.status === 'unconstrained'
      ? 'unconstrained · the pinned entry states none' : `${pair.status} the AA range`}`;
  }

  function choose(item) {
    const next = {beadKeys: [...(item.beadKeys || [])], itemId: item.itemId || null,
                  pairId: item.pairId || null, termId: item.termId || null};
    state.selected = next;
    state.status = item.status || '';
    renderAll();
  }

  function focusRow() {
    const card = host.closest('.run-view-analysis');
    if (!card) return;
    const pane = card.querySelector(`.analysis-pane[data-section="${state.mode}"]`);
    if (!pane) return;
    for (const row of pane.querySelectorAll('[data-item]')) {
      const selected = Boolean(state.selected.itemId) && row.dataset.item === state.selected.itemId;
      row.setAttribute('aria-selected', String(selected));
      // A collapsed term group must not hide the row the map is pointing at: opening its details is the only way the
      // reader can see what was focused, and it is the group's own control doing it.
      if (selected) {
        const group = row.closest('details');
        if (group && !group.open) group.open = true;
      }
    }
  }

  function paintLegend(reading) {
    legend.replaceChildren();
    if (!state.scene) return;
    if (state.mode === 'mapping-geometry') {
      const scale = element('span', 'rvm-legend-scale');
      scale.append(element('span', '', '0'),
        (() => {
          const gradient = element('span', 'rvm-gradient');
          gradient.setAttribute('aria-hidden', 'true');
          return gradient;
        })(), element('span', '', `${Math.round(reading?.domain?.[1] || 0)} pm`));
      legend.append(scale,
        legendLine(OVERLAP_GOOD, 'inside the AA range'),
        legendLine(OVERLAP_WEAK, 'outside'),
        legendLine(OVERLAP_MISSING, 'unconstrained', 'dashed'));
    } else if (state.mode === 'mapping-bonded') {
      legend.append(legendLine(OVERLAP_GOOD, 'overlap ≥ 0.5'), legendLine(OVERLAP_MID, '0.3–0.5'),
        legendLine(OVERLAP_WEAK, '< 0.3'), legendLine(OVERLAP_MISSING, 'not compared'));
    } else {
      const scale = element('span', 'rvm-legend-scale');
      scale.append(element('span', '', '0'),
        (() => {
          const gradient = element('span', 'rvm-gradient rvm-gradient-overlap');
          gradient.setAttribute('aria-hidden', 'true');
          return gradient;
        })(), element('span', '', '1'));
      legend.append(scale, legendLine(OVERLAP_MISSING, 'measured pair (selected thicker)', 'dashed'),
        element('span', 'rvm-legend-note', 'bead fill is overlap; pair lines are the measured pairs'));
    }
  }

  function legendLine(colour, text, dashed) {
    const spot = element('span', 'rvm-legend-line');
    spot.style.background = colour;
    if (dashed) spot.style.opacity = '0.6';
    const entry = element('span', 'rvm-legend-entry');
    entry.append(spot, document.createTextNode(text));
    return entry;
  }

  function paintStatus() {
    status.textContent = state.status || (state.mode === 'mapping-geometry'
      ? 'Click a bead, a pair line or an attention item to read it.'
      : state.mode === 'mapping-bonded'
        ? 'Beads are neutral; term lines are coloured by histogram overlap.'
        : 'Bead fill is per-bead mean overlap; the selected pair is drawn on the map.');
  }

  function paintReading() {
    if (!state.body) {
      eyebrow.textContent = 'Reading · no comparison';
      headlineText.textContent = state.missingText || '';
      caveat.textContent = '';
      attention.replaceChildren();
      return;
    }
    const reading = readingFor(state);
    eyebrow.textContent = `Reading · ${reading.title}`;
    headlineText.textContent = reading.headline;
    caveat.textContent = reading.caveat;
    const items = reading.attention.map((item, index) => ({...item, rank: index + 1}));
    attention.replaceChildren(...items.map(item => attentionNode(item, state, choose)));
  }

  function drawMap() {
    if (!state.scene) return;
    const render = {
      beads: state.beads,
      edges: state.edges,
      selectedBeads: state.selected.beadKeys,
      beadAliases: state.aliases,
      selection: 'halo',
      height: MAP_HEIGHT,
      uirevision: 'comparison-map',
    };
    if (state.mode === 'mapping-geometry') {
      const values = state.displacement;
      const measured = [...values.keys()];
      const highest = Math.max(0, ...measured.map(key => values.get(key)));
      render.beadColor = {values, domain: [0, highest], measured: new Set(measured), label: 'displacement (pm)'};
      render.pairs = state.pairs.filter(pair => pair.a && pair.b)
        .map(pair => ({id: pair.id, a: pair.a, b: pair.b, status: pair.status}));
      render.selectedPairId = state.selected.pairId || '';
      paintLegend({domain: [0, highest]});
    } else if (state.mode === 'mapping-bonded') {
      // Neutral beads: the term inks carry the metric, so the beads are one unmeasured grey trace rather than the
      // Bonded panel's type colours, which would make the reader look for a meaning in the fill.
      render.beadColor = {values: new Map(), domain: [0, 1], measured: new Set(), label: 'bead'};
      render.terms = state.terms.filter(term => term.beads.length === term.label.split(' – ').length)
        .map(term => ({id: term.id, kind: term.kind, beads: term.beads, ink: term.ink}));
      render.selectedTermId = state.selected.termId || '';
      paintLegend();
    } else {
      const values = state.overlapByBead;
      render.beadColor = {values, domain: [0, 1], measured: new Set(values.keys()),
        label: 'bead overlap', ramp: overlapRamp};
      render.pairs = state.overlapPairs.map(pair => ({
        id: pair.id, a: pair.a, b: pair.b, status: 'unconstrained'}));
      render.selectedPairId = state.selected.pairId || '';
      paintLegend();
    }
    plot.render(render);
  }

  function renderAll() {
    if (!current(token)) return;
    modeLabel.textContent = MODES[state.mode]?.label || state.mode;
    host.dataset.mode = state.mode;
    host.dataset.selectedBeads = state.selected.beadKeys.join(' ');
    paintReading();
    paintStatus();
    if (state.scene) {
      plotHost.hidden = false;
      missing.hidden = true;
      drawMap();
    } else {
      plotHost.hidden = true;
      missing.hidden = false;
      missing.textContent = state.missingText || 'The comparison map has nothing to draw.';
      legend.replaceChildren();
    }
    focusRow();
  }

  //: The three bead vocabularies onto one key: the mapping's own names (`S1A`), the entry labels (`(1,A)`) and the
  //: exported names (`B01`) all resolve to the exported name the topology and the GRO use. One implementation, so a
  //: term and a pair cannot disagree about which bead they name.
  function resolveBeads(model, positions) {
    const beads = [], byKey = new Map(), aliases = new Map();
    (model?.beads || []).forEach((entry, index) => {
      const name = String(entry.export_name || `B${String(index + 1).padStart(2, '0')}`);
      aliases.set(name, name);
      if (entry.name) aliases.set(String(entry.name), name);
      if (entry.residue !== undefined && entry.residue !== null && entry.letter) {
        aliases.set(`(${entry.residue},${entry.letter})`, name);
      }
      const record = {
        name, key: name, label: labelOf([entry.residue, entry.letter]),
        residue: entry.residue, letter: entry.letter, mappingName: entry.name || '',
        size: entry.size, type: entry.type, virtual_site: entry.virtual_site,
        position: positions.get(name) || null,
      };
      byKey.set(name, record);
      // A bead with no position stays in the reading and the rows; it is not drawn somewhere invented.
      if (record.position) beads.push(record);
    });
    return {beads, byKey, aliases};
  }

  function derive() {
    const model = state.model;
    const comparison = state.comparison = state.body?.comparison || {};
    const positions = state.positions || new Map();
    const resolved = resolveBeads(model, positions);
    state.beads = resolved.beads;
    state.byKey = resolved.byKey;
    const alias = (label) => resolved.aliases.get(label) || (resolved.byKey.has(label) ? label : null);
    state.aliases = resolved.aliases;
    state.edges = (model?.connections || [])
      .map(([first, second]) => [resolved.aliases.get(first) || first, resolved.aliases.get(second) || second])
      .filter(([first, second]) => resolved.byKey.get(first)?.position && resolved.byKey.get(second)?.position);
    state.displacement = new Map();
    for (const entry of comparison.displacement?.per_bead || []) {
      const key = alias(labelOf(entry.bead));
      const value = numeric(entry.displacement_nm);
      if (key && value !== null) state.displacement.set(key, value * 1000);   // nm -> pm, as the section chart does
    }
    state.overlapByBead = new Map();
    for (const entry of state.body?.overlap?.per_bead_mean || []) {
      const key = alias(entry.bead);
      const value = numeric(entry.mean);
      if (key && value !== null) state.overlapByBead.set(key, value);
    }
    state.pairs = geometryPairs(comparison, alias);
    state.terms = comparisonTerms(comparison, alias);
    state.overlapPairs = overlapPairs(state.body?.overlap || {}, alias);
    state.scene = state.beads.length > 0;
  }

  async function load(mine) {
    let body;
    try {
      body = await api(`/api/jobs/${encodeURIComponent(job.id)}/mapping-consistency`);
    } catch (error) {
      if (!current(mine)) return;
      state.body = null;
      state.scene = false;
      state.missingText = `${error.message}. ${error.status === 404
        ? 'The comparison has not been published for this run; Geometry can queue it.'
        : ''}`;
      renderAll();
      return;
    }
    if (!current(mine)) return;
    state.body = body;
    let modelText = null;
    try {
      modelText = await artifact(job, MODEL_PATH);
    } catch (error) {
      modelText = null;
    }
    if (!current(mine)) return;
    if (modelText === null) {
      state.model = null;
      state.comparison = body.comparison || {};
      state.scene = false;
      state.missingText = `The map cannot be drawn: ${MODEL_PATH} is missing from this run. `
        + 'The reading below still comes from the published comparison.';
      derive();
      renderAll();
      return;
    }
    let model;
    try {
      model = JSON.parse(modelText);
    } catch (error) {
      state.model = null;
      state.scene = false;
      state.missingText = `The map cannot be drawn: ${MODEL_PATH} could not be read (${error.message}).`;
      derive();
      renderAll();
      return;
    }
    let groText = null;
    let groPath = GRO_PATH;
    try {
      groText = await artifact(job, GRO_PATH);
      if (groText === null) { groPath = GRO_FALLBACK; groText = await artifact(job, GRO_FALLBACK); }
    } catch (error) {
      groText = null;
    }
    if (!current(mine)) return;
    state.model = model;
    if (groText === null) {
      state.positions = new Map();
      state.scene = false;
      state.missingText = `The map cannot be drawn: neither ${GRO_PATH} nor ${GRO_FALLBACK} is on disk. `
        + 'The reading below still comes from the published comparison.';
      derive();
      renderAll();
      return;
    }
    state.positions = parseGro(groText);
    state.missingText = '';
    derive();
    state.scene = state.beads.length > 0;
    renderAll();
  }

  function setMode(sectionName) {
    if (!MODES[sectionName] || sectionName === state.mode) {
      if (MODES[sectionName]) renderAll();
      return;
    }
    state.mode = sectionName;
    // The bead selection follows the reader across perspectives; an item id belongs to one section's rows, so it is
    // cleared with them.
    state.selected = {beadKeys: state.selected.beadKeys, itemId: null, pairId: null, termId: null};
    state.status = '';
    renderAll();
  }

  async function refresh() {
    const mine = token;
    if (!state.body) { await load(mine); return; }
    let next;
    try {
      next = await api(`/api/jobs/${encodeURIComponent(job.id)}/mapping-consistency`);
    } catch (error) {
      return;   // the record that was already read stays; a failed re-read does not erase it
    }
    if (!current(mine)) return;
    state.body = next;
    derive();
    renderAll();
  }

  function reset() {
    token += 1;
    plot.destroy();
    host.replaceChildren();
  }

  token += 1;
  renderAll();
  await load(token);
  return {setMode, refresh, reset};
}

registerRunViewAnalysisMap({name: 'mapping-comparison', serves: isComparisonRun, mount});
