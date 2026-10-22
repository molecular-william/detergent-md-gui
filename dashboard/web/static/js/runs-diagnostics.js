import { $, api } from './shared.js';

/**
 * Render the distance diagnostic guidance box inside a run's analysis panel.
 *
 * Idempotent for a given run id: if the host already shows diagnostics for
 * that run, the function returns without refetching. Errors are silent
 * because the endpoint returns 404 for runs without diagnostics.
 */
export async function renderDistanceDiagnostics(card, job) {
  // Sole writer of the diagnostics host. It used to write into the task list beside it, which `runs.js` fills on the
  // same refresh -- so whichever of the two wrote second erased the other, and the card's contents depended on
  // whether the diagnostics had been fetched yet rather than on the run.
  const host = $('.analysis-diagnostics', card); if (!host) return;
  // Idempotent per run *and* per artifact revision. A run whose assessment was re-scored publishes a new matrix under
  // `stages/5_assessment@<n>/`, and the index revision is what changes when that attempt's worker re-read the run -- so
  // keying on the run id alone would keep showing the numbers the re-score replaced until the page was reloaded.
  const key = `${job.id}:${job.artifact_revision ?? ''}`;
  if (host.dataset.distanceRun === key) return;
  let response;
  try { response = await api(`/api/jobs/${job.id}/distance-diagnostics`); }
  catch (_) { return; }
  const data = response.data || {};
  const pairs = data.pairs || [];
  // A pair's category comes from `kind`, written per pair by the analysis. Artifacts written before
  // that field existed have none, and guessing from bead names put constrained pairs into the
  // physical population -- where they look like evidence about the mapping when they are not free to
  // move at all. Without `kind` the honest answer is "unclassified", with the reason shown.
  const classified = pairs.length > 0 && pairs.every(p => p.kind !== undefined && p.kind !== null);
  const legacy = response.legacy === true || !classified;
  const virtual = classified ? pairs.filter(p => p.kind === 'virtual_site_diagnostic') : [];
  const physical = classified ? pairs.filter(p => p.kind !== 'virtual_site_diagnostic') : pairs;
  const scale = data.colour_scale_nm;
  const perRun = scale && scale.per_run !== false;
  // Records written before the scale became shared say so (`per_run`); the note follows the record rather than
  // the reader's assumption, and a run that ran past the shared scale is told apart from one that fits it.
  const scaleNote = scale && Number.isFinite(Number(scale.max))
    ? `<p class="hint">Heatmap colour scale: 0–${Number(scale.max).toFixed(3)} nm, `
      + (perRun ? 'set per run. Compare numbers, not colour.'
                : 'the same for every run, so two runs can be compared by colour.'
                  + (scale.clipped ? ' This run has distances beyond the scale: they are drawn at its top, and the numbers in each cell are not clipped.' : ''))
      + '</p>' : '';
  const legacyNote = legacy
    ? '<p class="hint">Written before per-pair classification, so constrained distances cannot be told apart from physical ones here. Re-run the distance analysis for a classified report.</p>' : '';
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
  const grid = classified
    ? `<div class="distance-diagnostic-grid"><span>Physical pairs · raw AA: <b>${sm('physical','raw_AA')} nm</b></span><span>Physical pairs · expanded ring: <b>${sm('physical','ring_expanded_AA')} nm</b></span><span>Constrained physical: <b>${sm('constrained_physical','ring_expanded_AA')} nm</b></span><span>Virtual-site diagnostics: <b>${sm('virtual_site_diagnostic','ring_expanded_AA')} nm</b></span></div>`
    : `<div class="distance-diagnostic-grid"><span>All pairs · raw AA: <b>${mean(pairs,'raw_AA')} nm</b></span><span>All pairs · expanded ring: <b>${mean(pairs,'ring_expanded_AA')} nm</b></span></div>`;
  box.innerHTML = `<strong>Distance diagnostic guidance</strong><p>Virtual-site pairs are shown separately and are diagnostic only. Do not optimize them as ordinary bonded distances. Compare physical bead pairs using the expanded-ring AA target when ring scaling is enabled. Constrained distances are reported separately because a fixed CG distance can score poorly against a broad AA distribution.</p>${legacyNote}${scaleNote}${grid}<details><summary>Inspect pair diagnostics (${pairs.length} pairs)</summary><div class="distance-pair-table"></div></details>`;
  const table = $('.distance-pair-table', box);
  const t = document.createElement('table');
  t.innerHTML = '<thead><tr><th>Pair</th><th>Category</th><th>Raw AA</th><th>Expanded ring</th></tr></thead>';
  const body = document.createElement('tbody');
  for (const p of pairs) {
    const tr = document.createElement('tr');
    const label = !classified ? 'Unclassified (legacy artifact)'
      : p.kind === 'virtual_site_diagnostic' ? 'Virtual-site diagnostic'
      : p.kind === 'constrained_physical' ? 'Constrained physical'
      : 'Physical bead';
    tr.innerHTML = `<td>${p.beads.join('–')}</td><td>${label}</td><td>${format(p.wasserstein_nm?.raw_AA, ' nm')}</td><td>${format(p.wasserstein_nm?.ring_expanded_AA, ' nm')}</td>`;
    body.append(tr);
  }
  t.append(body); table.append(t);
  host.replaceChildren(box);
  host.dataset.distanceRun = key;
}