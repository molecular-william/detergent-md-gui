// The mapped AA/CG solvent-accessible surface, drawn from the server's mesh in one Plotly scene.
//
// The mesh is derived from the mapped coordinates, not from a simulated trajectory: the AA envelope is the reference
// the model was fitted against and the CG envelope is the mapped model's own beads, so the picture answers "where does
// the mapped model's surface sit beside the reference's?" -- it is not an estimate of either ensemble's interior.
//
// The pane owns three things and nothing else: a plot host (Plotly's scene), a checkbox that toggles the mesh's own
// vertices as dots, and the line under the plot that states what was drawn. Plotly arrives lazily (the bundle is
// 4.8 MB and only two panels need it), so a load waits for it and a result that arrives after the pane has moved on is
// dropped: the generation token is bumped by every load, clear and destroy.
import { post } from './shared.js';
import { ensurePlotly } from './plotly-loader.js';

//: The two surfaces' own colours, matching the interaction plot's AA blue and CG amber.
const AA_COLOR = '#2864b5';
const CG_COLOR = '#d97706';
//: Every vertex plotted as a dot would bury the scene; a regular subsample keeps the shape and the trace small.
const MAX_DOTS = 4000;
const HINT = 'Choose a model to see its mapped AA/CG surface.';

const CONFIG = {responsive: true, displaylogo: false, modeBarButtonsToRemove: ['lasso3d', 'select3d']};

const LAYOUT = {
  height: 360,
  margin: {l: 0, r: 0, t: 0, b: 0},
  paper_bgcolor: '#fff',
  plot_bgcolor: '#fff',
  showlegend: true,
  legend: {orientation: 'h', x: 0, y: 1},
  scene: {
    aspectmode: 'data',
    xaxis: {visible: false},
    yaxis: {visible: false},
    zaxis: {visible: false},
  },
};

function numberOrNull(...values) {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue;
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return null;
}

function flatNumbers(values) {
  if (!Array.isArray(values) || !values.length) return null;
  if (Array.isArray(values[0])) return values.flat().map(Number);
  return values.map(Number);
}

//: The server may state a mesh as flat arrays or as arrays of triples; both are flattened to what mesh3d reads.
function mesh(raw) {
  const vertices = flatNumbers(raw && raw.vertices);
  const faces = flatNumbers(raw && raw.faces);
  if (!vertices || !faces || vertices.length < 3 || faces.length < 3) return null;
  return {
    x: vertices.filter((_, index) => index % 3 === 0),
    y: vertices.filter((_, index) => index % 3 === 1),
    z: vertices.filter((_, index) => index % 3 === 2),
    i: faces.filter((_, index) => index % 3 === 0),
    j: faces.filter((_, index) => index % 3 === 1),
    k: faces.filter((_, index) => index % 3 === 2),
    points: vertices.length / 3,
    triangles: faces.length / 3,
  };
}

function dots(surface) {
  const stride = Math.max(1, Math.ceil(surface.points / MAX_DOTS));
  const x = [], y = [], z = [];
  for (let index = 0; index < surface.points; index += stride) {
    x.push(surface.x[index]);
    y.push(surface.y[index]);
    z.push(surface.z[index]);
  }
  return {x, y, z};
}

export function createBondedSurface({host}) {
  if (!host) throw new TypeError('createBondedSurface needs a host element');

  let generation = 0;
  let surfaces = null;
  let showingDots = false;

  const controls = document.createElement('div');
  controls.className = 'bonded-surface-controls';
  const toggle = document.createElement('label');
  toggle.className = 'bonded-surface-toggle';
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.id = 'bonded-surface-dots';
  toggle.append(checkbox, document.createTextNode(' Show surface dots'));

  const plotHost = document.createElement('div');
  plotHost.className = 'bonded-surface-plot';
  plotHost.setAttribute('aria-label', 'Mapped AA and CG solvent-accessible surface');

  const status = document.createElement('p');
  status.className = 'hint bonded-surface-status';
  status.setAttribute('role', 'status');

  function tracesFor(includeDots) {
    const traces = [];
    for (const [label, surface, color, opacity, flatshading] of [
      ['AA', surfaces && surfaces.aa, AA_COLOR, 0.35, false],
      ['mapped CG', surfaces && surfaces.cg, CG_COLOR, 0.55, true],
    ]) {
      if (!surface) continue;
      traces.push({
        type: 'mesh3d', name: label,
        x: surface.x, y: surface.y, z: surface.z,
        i: surface.i, j: surface.j, k: surface.k,
        color, opacity, flatshading, showscale: false, hoverinfo: 'skip',
      });
      if (includeDots) {
        const sampled = dots(surface);
        traces.push({
          type: 'scatter3d', mode: 'markers', name: label + ' surface dots',
          x: sampled.x, y: sampled.y, z: sampled.z,
          marker: {size: 2, color}, showlegend: false, hoverinfo: 'skip',
        });
      }
    }
    return traces;
  }

  function sentence() {
    const probe = surfaces.probe === null ? 'not stated' : surfaces.probe + ' nm';
    const spacing = surfaces.spacing === null ? 'not stated' : surfaces.spacing + ' nm';
    const counts = [];
    if (surfaces.aa) counts.push('AA ' + surfaces.aa.points + ' points / ' + surfaces.aa.triangles + ' triangles');
    if (surfaces.cg) counts.push('CG ' + surfaces.cg.points + ' points / ' + surfaces.cg.triangles + ' triangles');
    return 'SAS envelope from the mapped coordinates, not a simulation. Probe radius ' + probe
      + ' · spacing ' + spacing + ' · ' + counts.join(' · ') + '.';
  }

  function fail(error) {
    status.dataset.state = 'error';
    status.textContent = 'Surface unavailable: ' + (error && error.message ? error.message : error);
  }

  async function draw(mine) {
    await ensurePlotly();
    if (mine !== generation || !surfaces) return;
    await window.Plotly.react(plotHost, tracesFor(showingDots), LAYOUT, CONFIG);
    if (mine !== generation) return;
    status.dataset.state = '';
    status.textContent = sentence();
  }

  async function load(payload = {}) {
    const mine = ++generation;
    surfaces = null;
    showingDots = false;
    checkbox.checked = false;
    if (window.Plotly) window.Plotly.purge(plotHost);
    plotHost.replaceChildren();
    controls.replaceChildren(toggle);
    host.replaceChildren(controls, plotHost, status);
    status.dataset.state = '';
    status.textContent = 'Reading the mapped AA/CG surface…';
    try {
      const answer = await post('/api/bonded-surfaces', payload);
      if (mine !== generation) return;
      const metadata = (answer && answer.metadata) || {};
      surfaces = {
        aa: mesh(answer && answer.aa),
        cg: mesh(answer && answer.cg),
        probe: numberOrNull(answer && answer.probe_radius_nm, answer && answer.probe_nm,
                            metadata.probe_nm, metadata.probe_radius_nm),
        spacing: numberOrNull(answer && answer.spacing_nm, answer && answer.grid_spacing_nm,
                              metadata.grid_spacing_nm, metadata.spacing_nm),
      };
      if (!surfaces.aa && !surfaces.cg) throw new Error('the answer carried no AA or CG mesh');
      await draw(mine);
    } catch (error) {
      if (mine !== generation) return;
      surfaces = null;
      if (window.Plotly) window.Plotly.purge(plotHost);
      plotHost.replaceChildren();
      fail(error);
    }
  }

  function onToggle() {
    showingDots = checkbox.checked;
    if (!surfaces || !window.Plotly) return;
    const mine = generation;
    window.Plotly.react(plotHost, tracesFor(showingDots), LAYOUT, CONFIG).catch(error => {
      if (mine === generation) fail(error);
    });
  }
  checkbox.addEventListener('change', onToggle);

  function clear() {
    generation += 1;
    surfaces = null;
    showingDots = false;
    checkbox.checked = false;
    if (window.Plotly) window.Plotly.purge(plotHost);
    plotHost.replaceChildren();
    status.dataset.state = '';
    status.textContent = HINT;
    host.replaceChildren(status);
  }

  function destroy() {
    generation += 1;
    checkbox.removeEventListener('change', onToggle);
    if (window.Plotly) window.Plotly.purge(plotHost);
    plotHost.replaceChildren();
    host.replaceChildren();
    surfaces = null;
    showingDots = false;
  }

  clear();

  return {load, clear, destroy};
}
