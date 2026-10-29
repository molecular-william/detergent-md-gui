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

export function mountBondedPlot(host, {onBeadSelection, onTermSelection, onPlotError}) {
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

  function render({beads = [], edges = [], terms = [], selectedBeads: selected = [], selectedTermId = '',
                   beadAliases = new Map()} = {}) {
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
    const typeGroups = new Map();
    for (const bead of physical) {
      const type = bead.type || 'Unspecified';
      if (!typeGroups.has(type)) typeGroups.set(type, []);
      typeGroups.get(type).push(bead);
    }
    const types = [...typeGroups.keys()].sort((first, second) => first.localeCompare(second));
    const typeColors = new Map(types.map((type, index) => [type, TYPE_COLORS[index % TYPE_COLORS.length]]));
    const traces = types.map(type => {
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
    for (const term of terms) {
      const selectedTerm = term.id === selectedTermId;
      const style = TERM_STYLES[term.kind] || TERM_STYLE_DEFAULT;
      const label = `${term.kind} · ${(term.beads || []).join(' · ')}`;
      const line = {color: ink(selectedTerm ? TERM_SELECTED_INK : style.ink, style.alpha),
                    width: selectedTerm ? 10 : 6, dash: style.dash};
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
        traces.push({type: 'scatter3d', mode: 'lines', name: label, showlegend: false, x, y, z,
          customdata: ids, meta: 'term', line, hovertemplate: `${label}<extra></extra>`});
        continue;
      }
      const placed = pointsFor(term.beads || [], positions, beadAliases);
      if (placed.length < 2) continue;
      if (term.kind === 'angles') {
        const arc = placed.length === 3 ? angleArc(placed[1], placed[0], placed[2]) : [];
        if (!arc.length) continue;
        traces.push({type: 'scatter3d', mode: 'lines', name: label, showlegend: false,
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
      traces.push({type: 'scatter3d', mode: 'lines', name: label, showlegend: false,
        x: points.map(point => (point ? point[0] : null)), y: points.map(point => (point ? point[1] : null)),
        z: points.map(point => (point ? point[2] : null)),
        customdata: points.map(() => term.id), meta: 'term', line,
        hovertemplate: `${label}<extra></extra>`});
    }
    const layout = {
      height: 620, margin: {l: 0, r: 0, t: 16, b: 0}, showlegend: true,
      legend: {orientation: 'h', y: 1.02, x: 0}, uirevision: 'bonded-workspace',
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

  function destroy() {
    // A bundle still in flight must not draw into a host this module no longer owns.
    generation += 1;
    host?.removeAllListeners?.('plotly_click');
    if (window.Plotly && host) window.Plotly.purge(host);
  }

  return {render, destroy};
}
