// Read-only rendering of the values a run recorded, and the progress bar's stage segments.
// The server owns the grouping and the step arithmetic (dashboard/web/stage_settings.py); this module
// only draws the shapes it is handed, so the runs row and the Run view's Analysis tab cannot disagree.

export const STAGE_COLORS = {
  min: '#64748b', nvt: '#0ea5e9', npt: '#f59e0b', production: '#22c55e',
  equilibration: '#14b8a6', assessment: '#e11d48', fit: '#8b5cf6',
  mapping: '#94a3b8', analysis: '#0f766e', backmap: '#db2777', other: '#94a3b8',
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
    const block = document.createElement('section');
    block.className = 'stage-settings-group';
    const heading = document.createElement('h4');
    heading.className = 'stage-settings-title';
    heading.textContent = group.label || group.stage || 'Stage';
    block.append(heading);
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
    block.append(table);
    host.append(block);
  }
}

function segmentIndex(segments, stage) {
  return segments.findIndex(segment => segment.stage === stage);
}

//: Draw the run's bar as contiguous work-stage segments and fill them from its own progress record.
//: Returns false for a run whose bar stays the single fill: a run type with no segment table, or a plan that
//: contains none of its work stages.
export function renderProgressSegments(host, detail) {
  if (!host) return false;
  const segments = detail && detail.stage_segments;
  if (!detail || !Array.isArray(segments) || !segments.length) return false;
  const signature = segments.map(segment => segment.stage + ':' + segment.fraction + ':' + (segment.skipped ? 'x' : '')).join('|');
  if (host.dataset.segments !== signature) {
    host.dataset.segments = signature;
    host.replaceChildren();
    for (const segment of segments) {
      const span = document.createElement('span');
      span.className = 'job-progress-seg';
      span.dataset.stage = segment.stage;
      span.dataset.kind = segment.kind || 'other';
      span.style.width = (segment.fraction * 100).toFixed(3) + '%';
      span.title = (segment.label || segment.stage) + (segment.steps ? ' · ' + segment.steps + ' steps' : '');
      host.append(span);
    }
  }
  const progress = (detail && detail.progress) || {};
  const current = segmentIndex(segments, progress.stage);
  // `Number(null)` is 0, so a stage with no percent has to be recognised before the numeric check: otherwise a
  // stage with no step count would read as 0% done instead of "running".
  const hasPercent = progress.percent !== null && progress.percent !== undefined
    && Number.isFinite(Number(progress.percent));
  const within = hasPercent ? Math.max(0, Math.min(100, Number(progress.percent))) : 0;
  const unknown = current >= 0 && !hasPercent;
  segments.forEach((segment, index) => {
    const span = host.querySelector('.job-progress-seg[data-stage="' + segment.stage.replace(/"/g, '\\"') + '"]');
    if (!span) return;
    const skipped = !!segment.skipped;
    span.style.setProperty('--segment-color', STAGE_COLORS[segment.kind] || STAGE_COLORS.other);
    span.classList.toggle('done', !skipped && current > index);
    span.classList.toggle('current', !skipped && current === index);
    span.classList.toggle('future', !skipped && (current < 0 || index > current));
    span.classList.toggle('skipped', skipped);
    span.classList.toggle('unknown', !skipped && current === index && unknown);
    if (!skipped) span.style.setProperty('--fill', (current === index ? within : current > index ? 100 : 0) + '%');
  });
  const percent = current >= 0
    ? Math.round(100 * (segments.slice(0, current).reduce((sum, segment) => sum + segment.fraction, 0)
      + segments[current].fraction * within / 100))
    : 0;
  host.setAttribute('aria-valuenow', String(percent));
  host.setAttribute('aria-valuetext', current >= 0
    ? (segments[current].label || segments[current].stage) + ' ' + (unknown ? 'running' : within + '%') : '');
  host.classList.add('segmented');
  return true;
}
