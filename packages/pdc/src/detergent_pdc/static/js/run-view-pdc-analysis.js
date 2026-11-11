// The pdc feature's Structure and interactions section for the Run view Analysis card.
//
// One kind so far: `pdc-structure`. The section reads the newest published record from
// `GET /api/jobs/<id>/pdc-structure` and draws what the record states -- the leg, the sample, the figures, the
// method, the cutoffs and the report's own caveats. It computes nothing and queues through the engine's generic
// `POST /api/jobs/<id>/<kind>` route.
//
// Four states, drawn differently: nothing computed yet (a 404 from the route), published, a run with no protein
// (the protein–detergent interface is null, never a zero), and a run whose production leg is the fallback
// assessment leg. An empty state is not a failure and nothing here is called validated.
import { api, plural } from '/static/js/shared.js';
import { registerRunViewAnalysisSection } from '/static/js/run-view.js';

const KIND = 'pdc-structure';
const SECTION = 'pdc-structure';

const number = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const fixed = (value, digits = 2) => {
  const parsed = number(value);
  return parsed === null ? '—' : parsed.toFixed(digits);
};
const cell = (value) => String(value ?? '').replace(/[&<>]/g, character => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[character]));
const shortTime = (value) => String(value ?? '').replace('T', ' ').slice(0, 16);
const thousands = (value) => {
  const parsed = number(value);
  return parsed === null ? '—' : String(parsed).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
};
const extensionLeg = (body) => /^(?:08_extension|4_extension)$/.test(String(body?.leg?.stage_directory || ''));

async function load(host, job, isCurrent) {
  try {
    return {body: await api(`/api/jobs/${encodeURIComponent(job.id)}/${KIND}`)};
  } catch (error) {
    if (!isCurrent()) return {cancelled: true};
    if (error.status === 404) return {body: null};
    host.replaceChildren(paragraph('hint', `${error.message}. The structure analysis could not be read.`));
    return {failed: true};
  }
}

function paragraph(className, text) {
  const line = document.createElement('p');
  line.className = className;
  line.textContent = text;
  return line;
}

//: One queue button for this section's one kind. It is disabled while its request is in flight, so a double press
//: cannot start two attempts.
function queueButton(job, queue, label, sentence) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'secondary pds-queue';
  button.textContent = label;
  button.onclick = async () => {
    if (!queue) return;
    button.disabled = true;
    try {
      await queue(`/api/jobs/${encodeURIComponent(job.id)}/${KIND}`, {}, () => sentence);
    } finally {
      button.disabled = false;
    }
  };
  return button;
}

const SUB_HEAD = `<div class="pds-sub-head"><b>Structure</b>
  <span class="pds-chip kind">pdc-structure</span>
  <span class="pds-chip gmx">one GROMACS pass · read-only</span></div>`;

function emptyMarkup(job, queue) {
  const sub = document.createElement('div');
  sub.className = 'pds-sub';
  sub.innerHTML = `${SUB_HEAD}
    <div class="pds-status"><span class="pds-dot"></span> Nothing computed yet.</div>
    <div class="pds-empty"><b>Nothing computed yet.</b> Shape, micelle size, radial distribution and contact
      counts are read from one bounded sample of this run's production leg, with <code>gmx gyrate</code>,
      <code>gmx rdf</code> and <code>gmx mindist</code>.</div>
    <p class="pds-hint">Nothing on this section is validation, and an empty state is not a failure.</p>`;
  sub.append(queueButton(job, queue, 'Calculate structure', 'Structure analysis queued.'));
  return sub;
}

function figure(label, value, unit = '') {
  return `<div class="pds-fig"><span class="pds-fig-label">${label}</span>
    <b>${value}${unit ? `<span class="pds-unit">${unit}</span>` : ''}</b></div>`;
}

function sampleLine(sampling) {
  const parts = [`<b>${cell(thousands(sampling.frames_sampled))} of ${cell(thousands(sampling.frames_in_file))} frames</b>`,
                 `stride ${cell(sampling.stride)}`];
  if (number(sampling.span_ns) !== null) parts.push(`spanning ${fixed(sampling.span_ns, 1)} ns`);
  if (number(sampling.frame_dt_ps) !== null) parts.push(`frame spacing ${fixed(sampling.frame_dt_ps, 1)} ps as the file states it`);
  return parts.join(', ');
}

function cutoffLine(body) {
  const parts = [];
  if (number(body.micelle?.contact_nm) !== null) parts.push(`<b>micelle contact ${fixed(body.micelle.contact_nm, 2)} nm</b>`);
  if (number(body.contacts?.cutoff_nm) !== null) parts.push(`<b>contact cutoff ${fixed(body.contacts.cutoff_nm, 2)} nm</b>`);
  const curve = (body.rdf || [])[0];
  if (curve) parts.push(`<b>radial maximum ${fixed(curve.r_max_nm, 2)} nm, bin ${fixed(curve.bin_width_nm, 2)} nm</b>`);
  return parts.join(' · ');
}

function rdfLabel(curve) {
  return curve.first === 'protein' ? `${curve.first}→${curve.second}` : `${curve.first}–${curve.second}`;
}

function publishedMarkup(body, job, queue) {
  const host = document.createElement('div');
  host.className = 'pds-sub';
  const aggregation = body.aggregation;
  const sampling = body.sampling || {};
  const shape = body.shape_nm || {};
  const rg = shape.rg || {};
  const contacts = body.contacts;
  const micelle = body.micelle || {};
  const fallback = body.leg?.fallback_reason || !extensionLeg(body);
  const noProtein = body.protein_present === false;
  host.innerHTML = `
    <div class="pds-notices">
      ${noProtein ? `<div class="pds-notice"><b>This run has no protein.</b> The protein–detergent interface is
        not defined for it, so only the detergent-only forms are reported: the micelle's shape and size,
        detergent–detergent distributions, and no protein contact count.</div>` : ''}
      ${fallback ? `<div class="pds-notice"><b>This is the run's fallback production leg.</b>
        ${body.leg?.fallback_reason ? `The run recorded: “${cell(body.leg.fallback_reason)}” ` : ''}
        The production leg is <b>${cell(body.leg?.name)}</b> (<code>${cell(body.leg?.stage_directory)}</code>), and
        every number below describes that leg. Its system was never rebuilt, so it is not comparable with a run
        that has an extension leg.</div>` : ''}
    </div>
    ${SUB_HEAD}
    <div class="pds-status"><span class="pds-dot live"></span> Published ${cell(shortTime(body.published_at))} UTC
      · attempt <code>${cell(body.attempt)}</code>
      · ${cell(thousands(sampling.frames_sampled))} of ${cell(thousands(sampling.frames_in_file))} frames, stride ${cell(sampling.stride)}
      · <b>${cell(body.leg?.name)}</b>${noProtein ? ' · no protein in this run' : ''}${fallback ? ' · fallback, not an extension leg' : ''}</div>
    <h4 class="pds-heading">Micelle</h4>
    <div class="pds-figures">
      ${figure('Radius of gyration', fixed(rg.mean, 2), 'nm')}
      ${aggregation
        ? figure('Largest cluster', fixed(aggregation.largest_mean, 1), 'molecules')
          + figure('Free detergents', fixed(aggregation.free_mean, 1), 'molecules')
          + figure('Clusters', fixed(aggregation.cluster_count_mean, 1))
        : figure('Largest cluster', 'not measured')}
      ${shape.asphericity_nm2
        ? figure('Asphericity', fixed(shape.asphericity_nm2.mean, 3), 'nm²')
        : figure('Asphericity', 'not measured')}
    </div>
    ${aggregation ? '' : `<p class="pds-hint">The run's own micelle criterion could not be applied, so the
      aggregation numbers are not reported. See the caveats below.</p>`}
    ${(body.rdf || []).length ? `<h4 class="pds-heading">Radial distribution</h4>
      <div class="pds-figures">${(body.rdf || []).map(curve => figure(
        `${cell(rdfLabel(curve))}, first peak`,
        number(curve.first_peak_nm) === null ? '—' : fixed(curve.first_peak_nm, 2), 'nm')).join('')}</div>` : ''}
    <h4 class="pds-heading">Contacts</h4>
    <div class="pds-figures">
      ${contacts
        ? figure(`Protein–detergent beads within ${fixed(contacts.cutoff_nm, 2)} nm`,
                 `${fixed(contacts.mean, 0)} ± ${fixed(contacts.sem, 1)}`, 'beads, mean ± SEM')
        : figure('Protein–detergent contacts', noProtein ? 'not defined' : 'not measured')}
    </div>
    <p class="pds-meta">Method: <b>${cell(body.method)}</b></p>
    <p class="pds-meta">Sampling: ${sampleLine(sampling)} · the leg's whole length, read once</p>
    ${cutoffLine(body) ? `<p class="pds-meta">Cutoffs: ${cutoffLine(body)}</p>` : ''}
    ${body.commands?.length ? `<p class="pds-meta">Commands: <b>${plural(body.commands.length, 'GROMACS command')}
      recorded</b> in the report.</p>` : ''}`;
  host.append(queueButton(job, queue, 'Recalculate structure', 'Structure analysis queued.'));
  if (Array.isArray(body.caveats) && body.caveats.length) {
    const caveat = document.createElement('div');
    caveat.className = 'pds-caveat';
    caveat.innerHTML = `<b>What these numbers are, and are not.</b>
      <ul>${body.caveats.map(text => `<li>${cell(text)}</li>`).join('')}</ul>`;
    host.append(caveat);
  }
  return host;
}

async function paint(host, {job, isCurrent, queue, refresh}) {
  const answer = await load(host, job, isCurrent);
  if (answer.cancelled || answer.failed) return;
  if (answer.body === null) {
    delete host.dataset.attempt;
    host.replaceChildren(emptyMarkup(job, queue));
    return;
  }
  const body = answer.body;
  if (refresh && host.dataset.attempt === String(body.attempt)) return;
  host.dataset.attempt = String(body.attempt);
  host.replaceChildren(publishedMarkup(body, job, queue));
}

registerRunViewAnalysisSection({
  name: SECTION,
  label: 'Structure and interactions',
  order: 40,
  serves: job => Boolean(job) && String(job.run_type || '') === 'pdc',
  mount: context => paint(context.host, {job: context.job, isCurrent: context.isCurrent, queue: context.queue, refresh: false}),
  refresh: context => paint(context.host, {job: context.job, isCurrent: context.isCurrent, queue: context.queue, refresh: true}),
});
