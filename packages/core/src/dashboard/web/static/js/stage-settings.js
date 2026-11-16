// Read-only rendering of the values a run recorded, and the AA progress bar's stage segments.
// The server owns the grouping and the step arithmetic (dashboard/web/stage_settings.py); this module
// only draws the shapes it is handed, so the runs row and the Run view's Analysis tab cannot disagree.

export const STAGE_COLORS = {
  min: '#64748b', nvt: '#0ea5e9', npt: '#f59e0b', production: '#22c55e',
  equilibration: '#14b8a6', other: '#94a3b8',
};

function valueText(value, unit) {
  if (Array.isArray(value)) return value.join(', ') + (unit ? ' ' + unit : '');
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (value === null || value === undefined || value === '') return '—';
  return String(value) + (unit ? ' ' + unit : '');
}

export function renderStageSettings(host, detail) {
  if (!host) return;
  host.replaceChildren();
  const settings = (detail && detail.stage_settings) || null;
  const groups = settings && Array.isArray(settings.groups) ? settings.groups : [];
  if (!groups.length) {
    const empty = document.createElement('p');
    empty.className = 'hint';
    empty.textContent = 'No stage settings recorded for this run.';
    host.append(empty);
    return;
  }
  for (const group of groups) {
    const heading = document.createElement('h4');
    heading.className = 'stage-settings-title';
    heading.textContent = group.label || group.stage || 'Stage';
    host.append(heading);
    const table = document.createElement('table');
    table.className = 'stage-settings-table';
    const body = document.createElement('tbody');
    for (const field of group.fields || []) {
      const row = document.createElement('tr');
      const key = document.createElement('th');
      key.scope = 'row';
      key.textContent = field.label || field.key;
      const value = document.createElement('td');
      value.textContent = valueText(field.value, field.unit);
      row.append(key, value);
      body.append(row);
    }
    table.append(body);
    host.append(table);
  }
}

function segmentIndex(segments, stage) {
  return segments.findIndex(segment => segment.stage === stage);
}

//: Draw the AA bar as contiguous stage segments and fill them from the run's own progress record.
//: Returns false for a run whose bar stays the single fill (CG, pdc, osmotic, or an older AA run).
export function renderProgressSegments(host, detail) {
  if (!host) return false;
  const segments = detail && detail.stage_segments;
  if (!detail || detail.run_type !== 'aa_only' || !Array.isArray(segments) || !segments.length) return false;
  const signature = segments.map(segment => segment.stage + ':' + segment.fraction).join('|');
  if (host.dataset.segments !== signature) {
    host.dataset.segments = signature;
    host.replaceChildren();
    for (const segment of segments) {
      const span = document.createElement('span');
      span.className = 'job-progress-seg';
      span.dataset.stage = segment.stage;
      span.dataset.kind = segment.kind || 'other';
      span.style.width = (segment.fraction * 100).toFixed(3) + '%';
      span.title = (segment.label || segment.stage) + ' · ' + segment.steps + ' steps';
      host.append(span);
    }
  }
  const progress = (detail && detail.progress) || {};
  const current = segmentIndex(segments, progress.stage);
  const within = Number.isFinite(Number(progress.percent)) ? Math.max(0, Math.min(100, Number(progress.percent))) : 0;
  segments.forEach((segment, index) => {
    const span = host.querySelector('.job-progress-seg[data-stage="' + segment.stage.replace(/"/g, '\\"') + '"]');
    if (!span) return;
    span.style.setProperty('--segment-color', STAGE_COLORS[segment.kind] || STAGE_COLORS.other);
    span.classList.toggle('done', current > index);
    span.classList.toggle('current', current === index);
    span.classList.toggle('future', current >= 0 && index > current);
    span.style.setProperty('--fill', (current === index ? within : current > index ? 100 : 0) + '%');
  });
  const percent = current >= 0
    ? Math.round(100 * (segments.slice(0, current).reduce((sum, segment) => sum + segment.fraction, 0)
      + segments[current].fraction * within / 100))
    : (progress.stage ? 100 : 0);
  host.setAttribute('aria-valuenow', String(percent));
  host.setAttribute('aria-valuetext', current >= 0 ? (segments[current].label || segments[current].stage) + ' ' + within + '%' : '');
  host.classList.add('segmented');
  return true;
}
