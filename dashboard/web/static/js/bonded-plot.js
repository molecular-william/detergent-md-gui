// Plotly owns the 3D scene; the workspace controller owns draft state.
export function mountBondedPlot(host, {onBeadSelection, onTermSelection, onPlotError}) {
  let selectedBeads = [];
  let clickHandler = null;

  function pointsFor(names, positions) {
    return names.map(name => positions.get(name)).filter(Boolean);
  }

  function render({beads = [], edges = [], terms = [], selectedBeads: selected = [], selectedTermId = ''} = {}) {
    selectedBeads = [...selected];
    if (!window.Plotly || !host) {
      onPlotError?.('The local Plotly bundle could not be loaded. The interaction table remains available.');
      return;
    }
    const positions = new Map(beads.map(bead => [bead.name, bead.position]));
    const physical = beads.filter(bead => !bead.virtual_site);
    const traces = [{
      type: 'scatter3d', mode: 'markers+text', name: 'CG beads',
      x: physical.map(bead => bead.position[0]), y: physical.map(bead => bead.position[1]),
      z: physical.map(bead => bead.position[2]), text: physical.map(bead => bead.name),
      textposition: 'top center', customdata: physical.map(bead => bead.name),
      marker: {size: physical.map(bead => selectedBeads.includes(bead.name) ? 12 : 9),
               color: physical.map(bead => selectedBeads.includes(bead.name) ? '#df203d' : '#2455b0'),
               line: {width: 1, color: '#ffffff'}},
      hovertemplate: '<b>%{text}</b><br>x %{x:.3f} nm<br>y %{y:.3f} nm<br>z %{z:.3f} nm<extra></extra>',
      meta: 'bead',
    }];
    const edgeX = [], edgeY = [], edgeZ = [];
    for (const edge of edges) {
      const first = positions.get(edge[0]), second = positions.get(edge[1]);
      if (!first || !second) continue;
      edgeX.push(first[0], second[0], null); edgeY.push(first[1], second[1], null); edgeZ.push(first[2], second[2], null);
    }
    if (edgeX.length) traces.push({type: 'scatter3d', mode: 'lines', name: 'Mapping connectivity',
      x: edgeX, y: edgeY, z: edgeZ, line: {color: '#a8b5c4', width: 4}, hoverinfo: 'skip', meta: 'edge'});
    for (const term of terms) {
      const points = pointsFor(term.beads || [], positions);
      if (points.length < 2) continue;
      const selectedTerm = term.id === selectedTermId;
      traces.push({type: 'scatter3d', mode: 'lines', name: `${term.kind} · ${term.beads.join(' · ')}`,
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
    clickHandler = event => {
      const point = event?.points?.[0];
      if (!point) return;
      if (point.data?.meta === 'bead') {
        const name = point.customdata;
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
    host.on?.('plotly_click', clickHandler);
    window.Plotly.react(host, traces, layout, {responsive: true, displaylogo: false, modeBarButtonsToRemove: ['lasso3d', 'select3d']})
      .catch(error => onPlotError?.(`The 3D diagram could not be rendered: ${error.message}`));
  }

  function destroy() {
    host?.removeAllListeners?.('plotly_click');
    if (window.Plotly && host) window.Plotly.purge(host);
  }

  return {render, destroy};
}
