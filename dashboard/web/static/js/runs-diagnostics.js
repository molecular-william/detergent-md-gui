import { $, api } from './shared.js';

/**
 * Render the distance diagnostic guidance box inside a run's analysis panel.
 *
 * Idempotent for a given run id: if the host already shows diagnostics for
 * that run, the function returns without refetching. Errors are silent
 * because the endpoint returns 404 for runs without diagnostics.
 */
export async function renderDistanceDiagnostics(card, job) {
  const host = $('.analysis-tasks', card); if (!host) return;
  if (host.dataset.distanceRun === job.id) return;
  let response;
  try { response = await api(`/api/jobs/${job.id}/distance-diagnostics`); }
  catch (_) { return; }
  const data = response.data || {};
  const pairs = data.pairs || [];
  const virtual = pairs.filter(p => p.kind === 'virtual_site_diagnostic' || p.beads.some(n => /VS$/i.test(n)));
  const physical = pairs.filter(p => !virtual.includes(p));
  const stratified = data.stratified_means_nm || {};
  const number = (value) => {
    if (value === null || value === undefined || value === '') return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const format = (value, suffix = '') => {
    const parsed = number(value);
    return parsed === null ? 'n/a' : parsed.toFixed(3) + suffix;
  };
  const mean = (items, key) => {
    const values = items.map(p => number(p.wasserstein_nm?.[key])).filter(value => value !== null);
    return values.length ? (values.reduce((s, value) => s + value, 0) / values.length).toFixed(3) : 'n/a';
  };
  const box = document.createElement('section');
  box.className = 'distance-diagnostic notice';
  box.setAttribute('aria-label', 'Distance diagnostic guidance');
  const sm = (kind, key) => {
    const direct = number(stratified[kind]?.[key]);
    if (direct !== null) return direct.toFixed(3);
    const source = kind === 'virtual_site_diagnostic' ? virtual : kind === 'physical' ? physical : [];
    return source.length ? mean(source, key) : 'n/a';
  };
  box.innerHTML = `<strong>Distance diagnostic guidance</strong><p>Virtual-site pairs are shown separately and are diagnostic only. Do not optimize them as ordinary bonded distances. Compare physical bead pairs using the expanded-ring AA target when ring scaling is enabled. Constrained distances are reported separately because a fixed CG distance can score poorly against a broad AA distribution.</p><div class="distance-diagnostic-grid"><span>Physical pairs · raw AA: <b>${sm('physical','raw_AA')} nm</b></span><span>Physical pairs · expanded ring: <b>${sm('physical','ring_expanded_AA')} nm</b></span><span>Constrained physical: <b>${sm('constrained_physical','ring_expanded_AA')} nm</b></span><span>Virtual-site diagnostics: <b>${sm('virtual_site_diagnostic','ring_expanded_AA')} nm</b></span></div><details><summary>Inspect pair diagnostics (${pairs.length} pairs)</summary><div class="distance-pair-table"></div></details>`;
  const table = $('.distance-pair-table', box);
  const t = document.createElement('table');
  t.innerHTML = '<thead><tr><th>Pair</th><th>Category</th><th>Raw AA</th><th>Expanded ring</th></tr></thead>';
  const body = document.createElement('tbody');
  for (const p of pairs) {
    const tr = document.createElement('tr');
    const label = p.kind === 'virtual_site_diagnostic' ? 'Virtual-site diagnostic'
      : p.kind === 'constrained_physical' ? 'Constrained physical'
      : 'Physical bead';
    tr.innerHTML = `<td>${p.beads.join('–')}</td><td>${label}</td><td>${format(p.wasserstein_nm?.raw_AA, ' nm')}</td><td>${format(p.wasserstein_nm?.ring_expanded_AA, ' nm')}</td>`;
    body.append(tr);
  }
  t.append(body); table.append(t);
  host.replaceChildren(box);
  host.dataset.distanceRun = job.id;
}