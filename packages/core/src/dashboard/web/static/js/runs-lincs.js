// The LINCS warnings a run's stage logs recorded, inside the Runs panel's Diagnostics disclosure.
//
// A warning names the constrained atoms; for the severe ones GROMACS wrote the initial and constrained coordinates
// beside the stage log. The table is the diagnostic; the 3D picture is an illustration of the selected warning, so it
// opens in one shared dialog only while it is wanted and is disposed on close. Nothing here recomputes a simulation or
// treats a trajectory frame as "the warning frame".
import { $, api } from './shared.js';
import { ensureNgl } from './ngl-loader.js';

const states = new WeakMap();

function stateOf(card) {
  let state = states.get(card);
  if (!state) {
    state = {key: null, answer: null};
    states.set(card, state);
  }
  return state;
}

const esc = value => String(value ?? '').replace(/[&<>"']/g,
  character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[character]);

function number(value, digits = 3) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : '—';
}

function atomText(identity) {
  return identity ? `${identity.residue} ${identity.residue_id} ${identity.name}` : '—';
}

// The one dialog, its viewer and the warning currently drawn. The dialog is markup in the shell, so two runs or two
// rows share one stage rather than creating a canvas each; the stage is disposed on close.
let viewerStage = null;
let activeWarning = null;

function dialog() {
  return $('#lincs-frame-dialog');
}

function disposeViewer() {
  if (viewerStage) {
    viewerStage.dispose();
    viewerStage = null;
  }
  const host = $('#lincs-frame-viewer');
  if (host) host.replaceChildren();
  activeWarning = null;
}

async function showFrame(which) {
  const warning = activeWarning;
  const frame = warning?.frames?.[which];
  const host = $('#lincs-frame-viewer');
  if (!warning || !frame || !host) return;
  const title = $('#lincs-frame-title'), caption = $('#lincs-frame-caption');
  if (title) title.textContent = `Step ${warning.step} · ${which === 'initial' ? 'initial frame (b)' : 'after constraining (c)'}`;
  if (caption) {
    const offenders = [...new Set([...(warning.atoms || []), ...(warning.bonds || []).flatMap(bond => [bond.a, bond.b])])];
    const neighbours = (warning.neighbours || []).map(row => row.other);
    caption.textContent = `${frame.name} · red: atoms ${offenders.join(', ')}`
      + (neighbours.length ? ` · grey: neighbours within ${warning.neighbour_cutoff_nm} nm — the tables in the row carry the names and distances.` : '');
  }
  for (const button of document.querySelectorAll('[data-lincs-frame]')) {
    button.setAttribute('aria-pressed', String(button.dataset.lincsFrame === which));
  }
  try {
    const NGL = await ensureNgl();
    if (!viewerStage) { host.replaceChildren(); viewerStage = new NGL.Stage(host, {backgroundColor: 'white'}); }
    viewerStage.removeAllComponents();
    const component = await viewerStage.loadFile(frame.url, {ext: 'pdb'});
    const offenders = [...new Set([...(warning.atoms || []), ...(warning.bonds || []).flatMap(bond => [bond.a, bond.b])])];
    const neighbours = [...new Set((warning.neighbours || []).map(row => row.other))];
    // NGL's `@` selector is the zero-based atom index, and the PDB series are the warning's 1-based atom numbers.
    const selector = serials => serials.length ? '@' + serials.map(serial => Number(serial) - 1).join(',') : '';
    component.addRepresentation('spacefill', {sele: '*', color: 0xc9d3dc, radiusScale: 0.22, opacity: 0.22});
    if (neighbours.length) {
      component.addRepresentation('spacefill', {sele: selector(neighbours), color: 0x7d8b98, radiusScale: 0.45,
                                                opacity: 0.7});
    }
    component.addRepresentation('spacefill', {sele: selector(offenders), color: 0xc62828, radiusScale: 1.0});
    component.autoView(selector(offenders));
    viewerStage.handleResize();
  } catch (error) {
    if (host) host.textContent = `The frame could not be drawn: ${error.message}`;
  }
}

function openFrame(warning, which) {
  const frame = warning?.frames?.[which];
  if (!frame) return;
  activeWarning = warning;
  const box = dialog();
  if (!box) return;
  if (!box.open) box.showModal();
  showFrame(which);
}

function detailHtml(warning) {
  const hasFrames = !!(warning.frames && Object.keys(warning.frames).length);
  const identities = warning.identities || {};
  const atoms = (warning.atoms || []).map(serial => atomText(identities[serial])).filter(text => text !== '—');
  let html = `<h5>Step ${esc(warning.step)} · ${hasFrames ? 'a written frame' : 'no written frame'}</h5>`;
  html += `<p class="hint">${warning.max_deviation == null ? '' :
    `Maximum relative constraint deviation after LINCS: <b>${esc(warning.max_deviation)}</b>`
    + (atoms.length ? ` between ${esc(atoms.join(' and '))}.` : '.')}
    ${hasFrames ? '' : ' GROMACS did not write coordinates for this warning; its atom numbers and bond table are exact, '
      + 'and no trajectory frame is presented as the warning frame.'}</p>`;
  if (warning.bonds?.length) {
    html += '<h6>The constrained bonds</h6><div class="table-scroll lincs-scroll"><table class="lincs-table"><thead><tr>'
      + '<th scope="col">Atoms</th><th scope="col">Residue · bead</th><th scope="col">Angle</th>'
      + '<th scope="col">Previous</th><th scope="col">Current</th><th scope="col">Constraint</th></tr></thead><tbody>';
    for (const bond of warning.bonds) {
      const left = atomText(identities[bond.a]), right = atomText(identities[bond.b]);
      const worst = warning.atoms?.length === 2 && ((bond.a === warning.atoms[0] && bond.b === warning.atoms[1])
        || (bond.a === warning.atoms[1] && bond.b === warning.atoms[0]));
      html += `<tr${worst ? ' class="worst"' : ''}><td>${esc(bond.a)}–${esc(bond.b)}</td>`
        + `<td>${esc(left)} · ${esc(right)}</td><td>${number(bond.angle_deg, 1)}°</td>`
        + `<td>${number(bond.previous_nm)} nm</td><td>${number(bond.current_nm)} nm</td>`
        + `<td>${number(bond.constraint_nm)} nm</td></tr>`;
    }
    html += '</tbody></table></div><p class="hint">Lengths in nm: “previous” is the initial frame, “current” the one after constraining.</p>';
  }
  if (warning.neighbours?.length) {
    html += `<h6>Neighbours · ${esc(warning.neighbour_cutoff_nm)} nm around the max-deviation pair</h6>`
      + '<div class="table-scroll lincs-scroll"><table class="lincs-table"><thead><tr><th scope="col">Atom</th>'
      + '<th scope="col">Residue · bead</th><th scope="col">To</th><th scope="col">Distance</th>'
      + '<th scope="col">Kind</th></tr></thead><tbody>';
    for (const row of warning.neighbours) {
      const kind = row.kind === 'bonded' ? 'bonded' : row.kind === 'solvent' ? 'solvent' : 'nonbonded';
      html += `<tr${row.short ? ' class="worst"' : ''}><td>${esc(row.atom)} ${esc(atomText(identities[row.atom]))}</td>`
        + `<td>${esc(atomText(identities[row.other]))}</td><td>${esc(row.other)}</td>`
        + `<td>${number(row.distance_nm)} nm${row.short ? ' · short' : ''}</td><td>${esc(kind)}</td></tr>`;
    }
    html += '</tbody></table></div><p class="hint">Measured in the initial frame. A bonded pair’s constraint length is '
      + 'what the warning is about; a nonbonded contact below ' + esc(warning.short_contact_nm) + ' nm is marked short.</p>';
  }
  html += '<div class="lincs-actions">';
  for (const [key, label] of [['initial', 'Show initial frame'], ['constrained', 'Show after constraining']]) {
    html += `<button type="button" class="secondary" data-lincs-show="${key}"`
      + `${warning.frames?.[key] ? '' : ' disabled'}>${label}</button>`;
  }
  html += '</div>';
  return html;
}

function capScroll(wrap) {
  const body = wrap.querySelector('tbody');
  const rows = body ? Array.from(body.rows) : [];
  if (rows.length <= 6) {
    wrap.classList.remove('has-more');
    wrap.style.removeProperty('max-height');
    return;
  }
  const top = wrap.getBoundingClientRect().top;
  const seventh = rows[6].getBoundingClientRect().top;
  // A closed disclosure has no layout: leave the table uncapped and recalculate when it is next opened rather than
  // writing a one-pixel window from two zero rectangles.
  if (!(seventh > top)) {
    wrap.classList.remove('has-more');
    wrap.style.removeProperty('max-height');
    return;
  }
  wrap.classList.add('has-more');
  wrap.style.maxHeight = `${Math.ceil(seventh - top)}px`;
}

function capTables(root) {
  if (!root) return;
  for (const wrap of root.querySelectorAll('.lincs-scroll')) capScroll(wrap);
}

function renderDetail(host, answer, index) {
  const warning = answer.warnings[index];
  if (!warning) return;
  const detail = $('.run-lincs-detail', host);
  if (!detail) return;
  detail.innerHTML = detailHtml(warning);
  for (const button of detail.querySelectorAll('[data-lincs-show]')) {
    button.addEventListener('click', () => openFrame(warning, button.dataset.lincsShow));
  }
  capTables(detail);
}

function render(card, answer) {
  const host = $('.run-lincs-host', card);
  const count = $('.lincs-count', card);
  if (!host) return;
  const warnings = Array.isArray(answer.warnings) ? answer.warnings : [];
  host.replaceChildren();
  if (!warnings.length) {
    if (count) { count.hidden = true; count.textContent = ''; }
    return;
  }
  if (count) {
    count.hidden = false;
    count.textContent = `· ${warnings.length} LINCS`;
  }
  const selected = Number.isInteger(answer.selected) && answer.selected < warnings.length
    ? answer.selected : warnings.length - 1;
  const section = document.createElement('section');
  section.className = 'run-lincs';
  let html = '<h4>LINCS warnings <span class="hint">from this run’s stage logs</span></h4>';
  if (answer.fatal_warnings) {
    html += `<p class="run-lincs-verdict">mdrun stopped after ${esc(answer.fatal_warnings.toLocaleString())} `
      + 'LINCS warnings.</p>';
  }
  html += '<div class="table-scroll lincs-scroll"><table class="lincs-warnings"><caption class="sr-only">LINCS warning blocks '
    + 'in this run’s stage logs</caption><thead><tr><th scope="col">Step</th><th scope="col">Time</th>'
    + '<th scope="col">Max deviation</th><th scope="col">Atoms</th><th scope="col">Frame</th></tr></thead><tbody>';
  warnings.forEach((warning, index) => {
    const frames = warning.frames && Object.keys(warning.frames).length;
    html += `<tr aria-selected="${index === selected}"><td><button type="button" class="linkish" `
      + `data-lincs-index="${index}">${esc(warning.step)}</button></td>`
      + `<td>${number(warning.time_ps, 1)} ps</td><td>${esc(warning.max_deviation ?? '—')}</td>`
      + `<td>${esc((warning.atoms || []).join('–'))}</td>`
      + `<td><span class="frame-tag ${frames ? 'yes' : 'no'}">${frames ? 'b + c' : '—'}</span></td></tr>`;
  });
  html += '</tbody></table></div><div class="run-lincs-detail" aria-live="polite"></div>';
  section.innerHTML = html;
  host.append(section);
  renderDetail(host, answer, selected);
  capTables(section);
  for (const button of section.querySelectorAll('[data-lincs-index]')) {
    button.addEventListener('click', () => {
      const index = Number(button.dataset.lincsIndex);
      for (const row of section.querySelectorAll('.lincs-warnings tbody tr')) {
        row.setAttribute('aria-selected', String(row.querySelector('[data-lincs-index]')?.dataset.lincsIndex === button.dataset.lincsIndex));
      }
      renderDetail(host, answer, index);
    });
  }
}

export async function renderLincsDiagnostics(card, job) {
  const host = $('.run-lincs-host', card);
  if (!host || !job) return;
  const state = stateOf(card);
  const key = `${job.id}:${job.artifact_revision ?? ''}`;
  const active = job.status === 'running' || job.status === 'queued';
  // A finished attempt is read once; a live one is read again on the table's poll so a new warning appears without a
  // reload. The disclosure's own open event calls this too, so a closed row costs no request.
  if (state.key === key && !active) {
    // The render already happened, but a disclosure closed while the answer arrived left the cap unmeasured.
    capTables(host);
    return;
  }
  let answer;
  try {
    answer = await api(`/api/jobs/${encodeURIComponent(job.id)}/lincs-warnings`);
  } catch (error) {
    host.replaceChildren();
    const count = $('.lincs-count', card);
    if (count) count.hidden = true;
    return;
  }
  state.key = key;
  state.answer = answer;
  render(card, answer);
}

$('#lincs-frame-dialog')?.addEventListener('close', disposeViewer);
for (const button of document.querySelectorAll('[data-lincs-frame]')) {
  button.addEventListener('click', () => showFrame(button.dataset.lincsFrame));
}
window.addEventListener('resize', () => viewerStage?.handleResize());
