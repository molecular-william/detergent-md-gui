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

export function mountBondedPlot(host, {onBeadSelection, onTermSelection, onPlotError}) {
  let selectedBeads = [];
  let clickHandler = null;
  //: Which render is the current one. Plotly arrives asynchronously, and the reader re-renders this module on
  //: every bead selection, so a resolve that lands after a newer render must not paint the older scene.
  let generation = 0;

  function pointsFor(names, positions) {
    return names.map(name => positions.get(name)).filter(Boolean);
  }

  function render({beads = [], edges = [], terms = [], selectedBeads: selected = [], selectedTermId = ''} = {}) {
    selectedBeads = [...selected];
    if (!host) {
      // A missing host is a missing host: the bundle is not even asked for on this path, so blaming it
      // would send a reader after the wrong thing.
      onPlotError?.('The 3D diagram has no host element in this panel. The interaction table remains available.');
      return Promise.resolve();
    }
    const token = ++generation;
    const positions = new Map(beads.map(bead => [bead.name, bead.position]));
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
    const edgeX = [], edgeY = [], edgeZ = [];
    for (const edge of edges) {
      const first = positions.get(edge[0]), second = positions.get(edge[1]);
      if (!first || !second) continue;
      edgeX.push(first[0], second[0], null); edgeY.push(first[1], second[1], null); edgeZ.push(first[2], second[2], null);
    }
    if (edgeX.length) traces.push({type: 'scatter3d', mode: 'lines', name: 'Mapping connectivity', showlegend: false,
      x: edgeX, y: edgeY, z: edgeZ, line: {color: '#a8b5c4', width: 4}, hoverinfo: 'skip', meta: 'edge'});
    for (const term of terms) {
      const points = pointsFor(term.beads || [], positions);
      if (points.length < 2) continue;
      const selectedTerm = term.id === selectedTermId;
      traces.push({type: 'scatter3d', mode: 'lines', name: `${term.kind} · ${term.beads.join(' · ')}`, showlegend: false,
        x: points.map(point => point[0]), y: points.map(point => point[1]), z: points.map(point => point[2]),
        customdata: points.map(() => term.id), meta: 'term',
        line: {color: selectedTerm ? '#df203d' : '#36a269', width: selectedTerm ? 10 : 6},
        hovertemplate: `${term.kind} · ${term.beads.join(' · ')}<extra></extra>`});
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
