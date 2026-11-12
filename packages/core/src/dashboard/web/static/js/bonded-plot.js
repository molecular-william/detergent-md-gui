// Plotly owns the 3D scene; the workspace controller owns draft state.
// The bead radii come from `ngl-beads.js`, the one table of what each size class means
// (`models/sugars/recognition.RADII_NM`); this module only turns one into a marker size.
import { beadRadiusNm } from './ngl-beads.js';
import { ensurePlotly } from './plotly-loader.js';

const TYPE_COLORS = ['#2455b0', '#b24b8f', '#168477', '#d27a1f', '#6c4bb2', '#5d7187', '#c03b3b', '#4d8c45'];
//: Marker pixels per nanometre of bead radius, on this plot's own axes. Not a bead-radii scale: the shared
//: `applyBeadRadii` does not apply here, because Plotly has no structure to size -- this is how a nanometre of
//: radius becomes a circle on screen, and the radii themselves are the model's.
const MARKER_PIXELS_PER_NM = 72;
//: One style per kind of bonded term, so a reader can tell at a glance which row a line belongs to.
//:
//: Every kind traces segments the connectivity already draws, so colour alone is not enough -- a solid line on a solid
//: line is hidden by it, and the terms are drawn after the edges. Three things separate them. **Ink** says what the term
//: is: bonds the mapping's green (`#36a269`), constraints a darker shade of the same green because a constraint is a
//: distance the mapping fixes rather than a potential it fits, angles amber, dihedrals the same green dashed and
//: half-transparent, impropers slate, virtual sites violet. **Offset** steps a term's line off the bonds by a fraction
//: of the molecule's diagonal, for the kinds whose geometry is collinear with them: angles and both torsion kinds.
//: A constraint is left on the bond it constrains, where its darker ink is enough -- it measures that exact distance.
//: An angle and a dihedral are drawn as their own **arcs** -- the notation the quantities already have, and each needs
//: neither an offset nor a line hidden under a bond: an angle's between its two arms, a dihedral's between the two
//: half-planes about the central bond.
const TERM_STYLES = {
  bonds: {ink: '54,162,105', dash: 'solid', alpha: 1, offset: 0},
  constraints: {ink: '26,92,60', dash: 'solid', alpha: 1, offset: 0},
  angles: {ink: '210,122,31', dash: 'solid', alpha: 0.7, offset: 0},
  dihedrals: {ink: '54,162,105', dash: 'dash', alpha: 0.7, offset: 1},
  impropers: {ink: '93,113,135', dash: 'dashdot', alpha: 1, offset: 1},
  virtual_sitesn: {ink: '108,75,178', dash: 'dot', alpha: 1, offset: 0},
};
const TERM_STYLE_DEFAULT = {ink: '54,162,105', dash: 'solid', alpha: 1, offset: 0};
const TERM_SELECTED_INK = '223,32,61';
//: The comparison map's pair inks, from the draft's legend: inside the AA range green, outside red,
//: unconstrained grey and dashed -- a pair the pinned entry does not constrain is not a measured pass.
//: The width language is the term line's own, one step shorter: 4, and 8 when selected.
const PAIR_STYLES = {
  inside: {ink: '31,122,77', dash: 'solid'},
  outside: {ink: '192,42,55', dash: 'solid'},
  unconstrained: {ink: '139,152,168', dash: 'dash'},
};
const PAIR_STYLE_DEFAULT = PAIR_STYLES.unconstrained;
const PAIR_WIDTH = 4;
const PAIR_SELECTED_WIDTH = 8;
//: A halo selection is a wide underlay in the scene's own paper colour: it cuts a gap out of every line
//: drawn before it, so a comparison term keeps its metric ink instead of becoming the Bonded panel's red.
const HALO_INK = '#ffffff';
const HALO_WIDTH = 16;
//: `beadColor`'s default metric fill: light to dark blue, the Geometry reading legend's own gradient. A
//: darker bead is a larger value; which direction is worse is the reading's sentence, not the hue's.
//: `beadColor.ramp`, when the caller passes one, replaces this scale without changing anything else.
const BEAD_SCALE_FROM = [219, 234, 254];  // #dbeafe
const BEAD_SCALE_TO = [29, 78, 216];      // #1d4ed8
//: A bead with no measured value is grey -- never zero, and never a green pass.
const BEAD_UNMEASURED = [139, 152, 168];
//: How far an offset term's line steps off the bonds it shares, as a fraction of the molecule's own diagonal.
//: Enough that the line reads as an annotation beside a bond rather than as a second bond on top of it, small enough
//: that it still visibly joins the atoms it names.
const TERM_OFFSET = 0.018;
//: An angle's arc: how many segments, and how far from the vertex, as a fraction of its shorter arm. The arm is the
//: span the arc has to fit inside, so the mark stays on the angle however long the bonds are.
const ANGLE_ARC_STEPS = 16;
const ANGLE_ARC_FRACTION = 0.35;

/** A small displacement, pseudo-random but fixed for one bead set.
 *
 * Two things have to hold and randomness alone gives neither: a re-render must not move a line (the panel re-renders
 * on every bead and row selection, and a jumping diagram is worse than an overlapping one), and `ff_inter`'s eight
 * harmonics of one torsion must coincide -- they are one dihedral written eight times, so a fan of eight dashed lines
 * would show a distinction the science does not have. Seeding on the bead set gives both, and gives different
 * terms different displacements.
 */
function termOffset(key, scale) {
  let hash = 2166136261;
  for (const character of key) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  const next = () => {
    hash ^= hash << 13; hash ^= hash >>> 17; hash ^= hash << 5;
    return ((hash >>> 0) % 2001) / 1000 - 1;
  };
  const shift = [next(), next(), next()];
  const length = Math.sqrt(shift[0] ** 2 + shift[1] ** 2 + shift[2] ** 2) || 1;
  return shift.map(value => (value / length) * scale);
}

/** Points along the arc between two arms, at a fixed radius from the vertex.
 *
 * The arc is what an angle looks like on paper: it starts on one arm, ends on the other, and says nothing about the
 * bonds' own lengths. A triple that is straight or folded has no arc to draw (`sin` of an angle that is a straight line
 * is zero, and the sweep would divide by it), so it is left to the table.
 */
function angleArc(vertex, first, second) {
  const arms = [first, second].map(point => point.map((value, axis) => value - vertex[axis]));
  const lengths = arms.map(arm => Math.hypot(...arm));
  if (!lengths.every(length => length > 0)) return [];
  const unit = arm => arm.map(value => value / Math.hypot(...arm));
  const [from, to] = arms.map(unit);
  const cosine = Math.max(-1, Math.min(1, from.reduce((sum, value, axis) => sum + value * to[axis], 0)));
  const sweep = Math.acos(cosine);
  if (sweep < 1e-3 || Math.PI - sweep < 1e-3) return [];
  const radius = ANGLE_ARC_FRACTION * Math.min(...lengths);
  const sine = Math.sin(sweep);
  const points = [];
  for (let step = 0; step <= ANGLE_ARC_STEPS; step += 1) {
    const along = step / ANGLE_ARC_STEPS;
    const weight = [Math.sin((1 - along) * sweep) / sine, Math.sin(along * sweep) / sine];
    points.push(vertex.map((value, axis) => value + radius * (weight[0] * from[axis] + weight[1] * to[axis])));
  }
  return points;
}

/** The torsion as an arc about the central bond, from the first half-plane to the second.
 *
 * Looking down `j -> k`, a dihedral is the angle between the plane holding `i` and the plane holding `l`. So the two
 * outer atoms are projected onto the plane perpendicular to the bond, and the sweep runs from one projection to the
 * other about the bond's axis, centred on the bond. The angle is taken *signed* through the triple product: the same
 * four atoms can turn either way, the two signs are different torsions, and an unsigned sweep would draw them alike.
 *
 * An outer atom lying on the axis projects to nothing and has no half-plane; so does a sweep of zero, which is the cis
 * or trans case where there is no arc to draw and `sin` would divide the sweep by it.
 */
function dihedralArc(first, second, third, fourth) {
  const axisPoint = second.map((value, index) => (value + third[index]) / 2);
  const along = third.map((value, index) => value - second[index]);
  const axisLength = Math.hypot(...along);
  if (!axisLength) return [];
  const axis = along.map(value => value / axisLength);
  const project = point => {
    const offset = point.map((value, index) => value - axisPoint[index]);
    const within = offset.reduce((sum, value, index) => sum + value * axis[index], 0);
    return offset.map((value, index) => value - within * axis[index]);
  };
  const arms = [project(first), project(fourth)];
  const lengths = arms.map(arm => Math.hypot(...arm));
  if (!lengths.every(length => length > 1e-9)) return [];
  const [from, to] = arms.map((arm, index) => arm.map(value => value / lengths[index]));
  const cross = [from[1] * to[2] - from[2] * to[1], from[2] * to[0] - from[0] * to[2],
                 from[0] * to[1] - from[1] * to[0]];
  const sine = cross.reduce((sum, value, index) => sum + value * axis[index], 0);
  const cosine = Math.max(-1, Math.min(1, from.reduce((sum, value, index) => sum + value * to[index], 0)));
  const sweep = Math.atan2(sine, cosine);
  if (Math.abs(sweep) < 1e-3) return [];
  const radius = ANGLE_ARC_FRACTION * Math.min(...lengths);
  const points = [];
  for (let step = 0; step <= ANGLE_ARC_STEPS; step += 1) {
    const turn = (step / ANGLE_ARC_STEPS) * sweep;
    const cosTurn = Math.cos(turn), sinTurn = Math.sin(turn);
    const around = [axis[1] * from[2] - axis[2] * from[1], axis[2] * from[0] - axis[0] * from[2],
                    axis[0] * from[1] - axis[1] * from[0]];
    const alongAxis = axis.reduce((sum, value, index) => sum + value * from[index], 0);
    const direction = from.map((value, index) =>
      value * cosTurn + around[index] * sinTurn + axis[index] * alongAxis * (1 - cosTurn));
    points.push(axisPoint.map((value, index) => value + radius * direction[index]));
  }
  return points;
}

function ink(rgb, alpha) {
  return `rgba(${rgb},${alpha})`;
}

function paint(triplet) {
  return `rgb(${triplet.join(',')})`;
}

/** A metric value's fill, clamped to the caller's own domain.
 *
 * `beadColor.ramp` is the caller's own ratio -> CSS colour function, for a reading whose scale means
 * something the default blue cannot (the Shape overlap's red -> amber -> green). Without one the fixed
 * light-to-dark blue is the scale.
 */
function metricFill(value, domain, ramp) {
  const low = Number(domain?.[0]);
  const high = Number(domain?.[1]);
  const ratio = Number.isFinite(value) && Number.isFinite(low) && Number.isFinite(high) && high > low
    ? Math.max(0, Math.min(1, (value - low) / (high - low)))
    : 0.5;
  if (typeof ramp === 'function') return ramp(ratio);
  return paint(BEAD_SCALE_FROM.map((channel, axis) =>
    Math.round(channel + (BEAD_SCALE_TO[axis] - channel) * ratio)));
}

/** One hover-ready reading of a metric value; the units live in the caller's own label. */
function metricReading(value) {
  return Number.isFinite(value) ? String(Math.round(value * 1000) / 1000) : 'not measured';
}

/** A term's ink as a CSS colour: a comparison reading passes one, while the styles' own inks are
 * `r,g,b` triplets that take the style's alpha. */
function termColour(value, alpha) {
  return /^\d{1,3},\d{1,3},\d{1,3}$/.test(value) ? ink(value, alpha) : value;
}

export function mountBondedPlot(host, {onBeadSelection, onTermSelection, onPairSelection, onPlotError,
                                    uirevision = 'bonded-workspace'} = {}) {
  let selectedBeads = [];
  let clickHandler = null;
  //: Which render is the current one. Plotly arrives asynchronously, and the reader re-renders this module on
  //: every bead selection, so a resolve that lands after a newer render must not paint the older scene.
  let generation = 0;

  /** Positions for a list of names, resolving a revision's export names (`B01`) to the mapping's own bead names.
   *
   * A fitted revision names beads the way the topology it wrote does: `B01` is the first bead of the mapping,
   * virtual sites included (`mappings/exports.py`), not a name the mapping uses. The scene draws the mapping's names,
   * so a term that arrives as `B01 · B11` has to be translated before it has a position -- without it every term
   * misses, and the diagram draws the connectivity with no bonded term on it at all.
   */
  function pointsFor(names, positions, aliases) {
    return names.map(name => positions.get(aliases.get(name) || name)).filter(Boolean);
  }

  function render({beads = [], edges = [], terms = [], pairs = [], selectedBeads: selected = [],
                   selectedTermId = '', selectedPairId = '', beadAliases = new Map(),
                   beadColor = null, selection = '', height = 620,
                   uirevision: sceneRevision = uirevision} = {}) {
    selectedBeads = [...selected];
    if (!host) {
      // A missing host is a missing host: the bundle is not even asked for on this path, so blaming it
      // would send a reader after the wrong thing.
      onPlotError?.('The 3D diagram has no host element in this panel. The interaction table remains available.');
      return Promise.resolve();
    }
    const token = ++generation;
    const positions = new Map(beads.map(bead => [bead.name, bead.position]));
    //: The molecule's own size, which is the only span a displacement can be "slight" against.
    const diagonal = ['0', '1', '2'].reduce((total, axis) => {
      const values = beads.map(bead => bead.position[Number(axis)]);
      return values.length ? Math.hypot(total, Math.max(...values) - Math.min(...values)) : total;
    }, 0);
    const physical = beads.filter(bead => !bead.virtual_site);
    // The comparison map colours every physical bead by its own measured value instead of grouping by type:
    // one trace, explicit per-point fills, no legend entry, because the fill no longer means a type.
    const metric = beadColor && beadColor.values instanceof Map ? beadColor : null;
    let traces;
    if (metric) {
      const measured = metric.measured instanceof Set ? metric.measured : new Set(metric.values.keys());
      const label = metric.label || 'value';
      const reading = bead => {
        const value = metric.values.get(bead.name);
        return measured.has(bead.name) ? metricReading(value) : 'not measured';
      };
      const fill = bead => {
        const value = metric.values.get(bead.name);
        return measured.has(bead.name) && Number.isFinite(value) ? metricFill(value, metric.domain, metric.ramp)
          : paint(BEAD_UNMEASURED);
      };
      traces = physical.length ? [{
        type: 'scatter3d', mode: 'markers+text', name: metric.label || 'Beads', showlegend: false,
        x: physical.map(bead => bead.position[0]), y: physical.map(bead => bead.position[1]),
        z: physical.map(bead => bead.position[2]), text: physical.map(bead => bead.name),
        textposition: 'top center', customdata: physical.map(bead => [bead.name, bead.size || 'R', reading(bead)]),
        marker: {size: physical.map(bead => (beadRadiusNm(bead.size || 'R') ?? beadRadiusNm('R')) * MARKER_PIXELS_PER_NM + (selectedBeads.includes(bead.name) ? 4 : 0)),
                 color: physical.map(fill),
                 line: {width: 1, color: physical.map(bead => selectedBeads.includes(bead.name) ? '#1c2940' : '#ffffff')}},
        hovertemplate: `<b>%{text}</b><br>${label} %{customdata[2]}<br>size class %{customdata[1]}<br>x %{x:.3f} nm<br>y %{y:.3f} nm<br>z %{z:.3f} nm<extra></extra>`,
        meta: 'bead',
      }] : [];
    } else {
      const typeGroups = new Map();
      for (const bead of physical) {
        const type = bead.type || 'Unspecified';
        if (!typeGroups.has(type)) typeGroups.set(type, []);
        typeGroups.get(type).push(bead);
      }
      const types = [...typeGroups.keys()].sort((first, second) => first.localeCompare(second));
      const typeColors = new Map(types.map((type, index) => [type, TYPE_COLORS[index % TYPE_COLORS.length]]));
      traces = types.map(type => {
        const group = typeGroups.get(type);
        return {
          type: 'scatter3d', mode: 'markers+text', name: type, legendgroup: `bead-type-${type}`,
          x: group.map(bead => bead.position[0]), y: group.map(bead => bead.position[1]),
          z: group.map(bead => bead.position[2]), text: group.map(bead => bead.name),
          textposition: 'top center', customdata: group.map(bead => [bead.name, bead.size || 'R']),
          marker: {size: group.map(bead => (beadRadiusNm(bead.size || 'R') ?? beadRadiusNm('R')) * MARKER_PIXELS_PER_NM + (selectedBeads.includes(bead.name) ? 4 : 0)),
                   color: group.map(bead => selectedBeads.includes(bead.name) ? '#df203d' : typeColors.get(type)),
                   line: {width: 1, color: '#ffffff'}},
          hovertemplate: `<b>%{text}</b><br>type ${type}<br>size class %{customdata[1]}<br>x %{x:.3f} nm<br>y %{y:.3f} nm<br>z %{z:.3f} nm<extra></extra>`,
          meta: 'bead',
        };
      });
    }
    // A virtual site is a bead with no atoms of its own: drawn as an open diamond, because a marker that is a solid
    // circle is read as an atom the model does not have.
    const virtualSites = beads.filter(bead => bead.virtual_site);
    if (virtualSites.length) {
      traces.push({type: 'scatter3d', mode: 'markers+text', name: 'Virtual sites', legendgroup: 'virtual-sites',
        x: virtualSites.map(bead => bead.position[0]), y: virtualSites.map(bead => bead.position[1]),
        z: virtualSites.map(bead => bead.position[2]), text: virtualSites.map(bead => bead.name),
        textposition: 'bottom right', textfont: {size: 9, color: '#6c4bb2'},
        customdata: virtualSites.map(bead => [bead.name, (bead.virtual_site?.parents || []).join(' · ')]),
        marker: {symbol: 'diamond-open', size: 12,
                 color: virtualSites.map(bead => selectedBeads.includes(bead.name) ? '#df203d' : '#6c4bb2'),
                 line: {width: 2, color: '#ffffff'}},
        hovertemplate: '<b>%{text}</b><br>virtual site, built from %{customdata[1]}<br>x %{x:.3f} nm<br>y %{y:.3f} nm<br>z %{z:.3f} nm<extra></extra>',
        meta: 'bead'});
    }
    // Which beads a virtual site is built from. The term names the site alone; the parents live on the mapping's own
    // bead record, so a site's geometry is a star from it to each parent -- a polyline through them would draw
    // segments between parents that no term declares.
    const virtualParents = new Map(beads.map(bead => [bead.name, (bead.virtual_site?.parents) || []]));
    const edgeX = [], edgeY = [], edgeZ = [];
    for (const edge of edges) {
      const first = positions.get(edge[0]), second = positions.get(edge[1]);
      if (!first || !second) continue;
      edgeX.push(first[0], second[0], null); edgeY.push(first[1], second[1], null); edgeZ.push(first[2], second[2], null);
    }
    if (edgeX.length) traces.push({type: 'scatter3d', mode: 'lines', name: 'Mapping connectivity', showlegend: false,
      x: edgeX, y: edgeY, z: edgeZ, line: {color: '#a8b5c4', width: 4}, hoverinfo: 'skip', meta: 'edge'});
    const resolve = name => beadAliases.get(name) || name;
    // Constrained pairs are the comparison's own lines. Pair ids are separate from term ids, so a click
    // tells the controller which reading it selected; a name with no position is skipped, because the
    // pair belongs in the rows rather than being drawn somewhere invented.
    for (const pair of pairs) {
      const first = positions.get(resolve(pair.a));
      const second = positions.get(resolve(pair.b));
      if (!first || !second) continue;
      const style = PAIR_STYLES[pair.status] || PAIR_STYLE_DEFAULT;
      traces.push({type: 'scatter3d', mode: 'lines', name: `${pair.a} – ${pair.b}`, showlegend: false,
        x: [first[0], second[0]], y: [first[1], second[1]], z: [first[2], second[2]],
        customdata: [pair.id, pair.id], meta: 'pair',
        line: {color: ink(style.ink, 1), width: pair.id === selectedPairId ? PAIR_SELECTED_WIDTH : PAIR_WIDTH,
               dash: style.dash},
        hovertemplate: `${pair.a} – ${pair.b}<br>${pair.status}<extra></extra>`});
    }
    for (const term of terms) {
      const selectedTerm = term.id === selectedTermId;
      const style = TERM_STYLES[term.kind] || TERM_STYLE_DEFAULT;
      const label = `${term.kind} · ${(term.beads || []).join(' · ')}`;
      // `term.ink` is a comparison reading's own colour: the Bonded style keeps its dash and offset and
      // only the ink changes. The default selection keeps today's red; a halo selection keeps the metric
      // ink and gains a wide underlay instead, so red stays reserved for "weak" in the metric scale.
      const termInk = term.ink ? termColour(term.ink, style.alpha) : ink(style.ink, style.alpha);
      const line = {color: selectedTerm && selection !== 'halo' ? ink(TERM_SELECTED_INK, style.alpha) : termInk,
                    width: selectedTerm ? 10 : 6, dash: style.dash};
      const draw = trace => {
        if (selectedTerm && selection === 'halo') {
          // The scene's paper is white, so the halo is white and solid: it cuts a gap out of the lines
          // under the selection without adding a second colour a reader would try to interpret.
          traces.push({...trace, meta: 'term-halo', hoverinfo: 'skip', hovertemplate: '',
            line: {...trace.line, color: HALO_INK, width: HALO_WIDTH, dash: 'solid'}});
        }
        traces.push(trace);
      };
      if (term.kind === 'virtual_sitesn') {
        // One name in the term, a parent list in the mapping: the geometry is a star from the site to each parent.
        const site = resolve((term.beads || [])[0]);
        const origin = positions.get(site);
        const parents = virtualParents.get(site) || [];
        if (!origin || !parents.length) continue;
        const x = [], y = [], z = [], ids = [];
        for (const parent of parents) {
          const target = positions.get(parent);
          if (!target) continue;
          x.push(origin[0], target[0], null);
          y.push(origin[1], target[1], null);
          z.push(origin[2], target[2], null);
          ids.push(term.id, term.id, term.id);
        }
        if (!x.length) continue;
        draw({type: 'scatter3d', mode: 'lines', name: label, showlegend: false, x, y, z,
          customdata: ids, meta: 'term', line, hovertemplate: `${label}<extra></extra>`});
        continue;
      }
      const placed = pointsFor(term.beads || [], positions, beadAliases);
      if (placed.length < 2) continue;
      if (term.kind === 'angles') {
        const arc = placed.length === 3 ? angleArc(placed[1], placed[0], placed[2]) : [];
        if (!arc.length) continue;
        draw({type: 'scatter3d', mode: 'lines', name: label, showlegend: false,
          x: arc.map(point => point[0]), y: arc.map(point => point[1]), z: arc.map(point => point[2]),
          customdata: arc.map(() => term.id), meta: 'term', line,
          hovertemplate: `${label}<extra></extra>`});
        continue;
      }
      // A term whose geometry lies along the bonds is stepped off them, by the same vector for every term naming the
      // same beads: eight harmonics of one dihedral are one line, not eight, and a re-render must not move it.
      const spine = style.offset
        ? (([shiftX, shiftY, shiftZ]) => placed.map(([x, y, z]) => [x + shiftX, y + shiftY, z + shiftZ]))(
          termOffset([term.kind, ...(term.beads || [])].join('|'), (diagonal || 1) * TERM_OFFSET))
        : placed;
      // A torsion carries both marks in one trace: the displaced spine says *which* four atoms, the arc says how far
      // round the central bond they are. A null separates them, so Plotly draws two segments and not a jump.
      let arc = [];
      if (term.kind === 'dihedrals' && placed.length === 4) arc = dihedralArc(...placed);
      const points = arc.length ? [...spine, null, ...arc] : spine;
      draw({type: 'scatter3d', mode: 'lines', name: label, showlegend: false,
        x: points.map(point => (point ? point[0] : null)), y: points.map(point => (point ? point[1] : null)),
        z: points.map(point => (point ? point[2] : null)),
        customdata: points.map(() => term.id), meta: 'term', line,
        hovertemplate: `${label}<extra></extra>`});
    }
    const layout = {
      height, margin: {l: 0, r: 0, t: 16, b: 0}, showlegend: true,
      legend: {orientation: 'h', y: 1.02, x: 0}, uirevision: sceneRevision,
      scene: {
        xaxis: {title: 'x (nm)', showgrid: true, zeroline: false},
        yaxis: {title: 'y (nm)', showgrid: true, zeroline: false},
        zaxis: {title: 'z (nm)', showgrid: true, zeroline: false},
        aspectmode: 'data', camera: {projection: {type: 'orthographic'}},
      }, paper_bgcolor: '#ffffff', plot_bgcolor: '#ffffff',
    };
    return ensurePlotly().then(() => {
      if (token !== generation) return;
      clickHandler = event => {
        const point = event?.points?.[0];
        if (!point) return;
        if (point.data?.meta === 'bead') {
          const name = Array.isArray(point.customdata) ? point.customdata[0] : point.customdata;
          const next = selectedBeads.includes(name)
            ? selectedBeads.filter(item => item !== name)
            : [...selectedBeads.slice(-1), name];
          selectedBeads = next;
          onBeadSelection?.(next);
        } else if (point.data?.meta === 'term') {
          onTermSelection?.(point.customdata);
        } else if (point.data?.meta === 'pair') {
          onPairSelection?.(point.customdata);
        }
      };
      host.removeAllListeners?.('plotly_click');
      return window.Plotly.react(host, traces, layout, {responsive: true, displaylogo: false, modeBarButtonsToRemove: ['lasso3d', 'select3d']})
        .then(() => {
          // Plotly's own first plot replaces the div's event emitter, so a listener added before it is
          // dropped; the click handler is attached once the scene exists.
          if (token !== generation) return;
          host.on?.('plotly_click', clickHandler);
          // Recorded, because this is the first moment a click on the scene is heard at all: anything emitted
          // before it is dropped by the div, not missed by the handler.
          host.dataset.clickReady = 'true';
        })
        .catch(error => {
          // The same guard as the continuations above: a rejection from a render the reader has already
          // replaced must not overwrite the newer chart's own message.
          if (token !== generation) return;
          onPlotError?.(`The 3D diagram could not be rendered: ${error.message}`);
        });
    }, error => {
      if (token !== generation) return;
      onPlotError?.(`The local Plotly bundle could not be loaded (${error.message}). The interaction table remains available.`);
    });
  }

  /** Re-measure the scene after its host changed size -- the collapsed pane's host measured zero width. */
  function resize() {
    if (!host || !window.Plotly || !host.clientWidth) return;
    window.Plotly.Plots.resize(host);
  }

  function destroy() {
    // A bundle still in flight must not draw into a host this module no longer owns.
    generation += 1;
    host?.removeAllListeners?.('plotly_click');
    if (window.Plotly && host) window.Plotly.purge(host);
  }

  return {render, resize, destroy};
}
