import { $, $$, storage, setText, notice, api, post, cachedApi, invalidateResource, guarded, DROP } from './shared.js';
import { createConsoleViewer } from './console.js';
import { RunFigureViewer } from './figures.js';
import { renderDistanceDiagnostics } from './runs-diagnostics.js';

// Owns run cards, filtering, artifact loading, and polling. Form changes are callbacks.
// D1's line: the numbers the run card states, read from the summary the view projects off the published comparison --
// `/api/jobs` already carries it, so a card costs no request of its own. The count is `cg_outside_aa_range`, which is
// what card 1 of the panel badges, so the line says "range": the *spread* is the cross-molecule comparison on the same
// tab and it is a different quantity with a different meaning.
function consistencyLine(job) {
  const summary = job.consistency;
  if (!summary || !Number.isFinite(Number(summary.pairs))) return null;
  const total = Number(summary.pairs);
  const inside = total - (Number(summary.outside) || 0);
  return `Consistency: CG ${inside} of ${total} ring distances inside the AA observed range`;
}

export function createRuns({ onClone, onDeleted, onValidate }) {
  function setRunView(view) {
    const selected = ['table', 'grouped', 'dense'].includes(view) ? view : 'table';
    $('#runs').dataset.view = selected;
    $$('[data-run-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.runView === selected)));
    storage.set('runsView', selected);
  }
  $$('[data-run-view]').forEach(button => button.onclick = () => setRunView(button.dataset.runView));
  setRunView(storage.get('runsView', 'table'));

  const cards = new Map();
  const consoleViewer = createConsoleViewer({ getCards: () => cards.values() });
  function duration(seconds) {
    if (seconds === null || seconds === undefined) return 'Not recorded';
    const n = Math.floor(seconds); return `${Math.floor(n / 3600)}h ${Math.floor(n % 3600 / 60)}m ${n % 60}s`;
  }
  function stageDurationSeconds(start,end) { if (!start || !end) return null; const a=Date.parse(start), b=Date.parse(end); return Number.isFinite(a)&&Number.isFinite(b)&&b>=a ? (b-a)/1000 : null; }
  function updateJobs(jobs) {
    setText($('#empty-jobs td'), jobs.length ? '' : 'No runs yet. Check readiness in New run to get started.');
    $('#empty-jobs').hidden = !!jobs.length;
    const ids = new Set(jobs.map(job => job.id));
    for (const [id, card] of cards) if (!ids.has(id)) {
      if (card.contains($('#console-panel'))) { consoleViewer.detach(); }
      card.figureViewer?.destroy(); card.remove(); cards.delete(id);
    }
    for (const option of $$('#console-run option')) if (option.value && option.value !== consoleViewer.selectedRun && !ids.has(option.value)) option.remove();
    // Console selection can refer to a run on another page.
    let previousCard = $('#empty-jobs');
    for (const job of jobs) {
      let card = cards.get(job.id);
      if (!card) {
        card = $('#job-template').content.firstElementChild.cloneNode(true);
        card.dataset.id = job.id; cards.set(job.id, card); $('#jobs').append(card);
        const legacyDetails = {artifacts: 0, records: 1, analysis: 2};
        for (const kind of ['artifacts', 'records', 'console', 'analysis']) {
          const detail = $('.job-' + kind, card);
          const legacy = legacyDetails[kind];
          detail.open = storage.get(`resource.${job.id}.${kind}`, legacy !== undefined ? storage.get(`details.${job.id}.${legacy}`, false) : false);
          detail.addEventListener('toggle', () => {
            storage.set(`resource.${job.id}.${kind}`, detail.open);
            if (kind === 'console' && detail.open) consoleViewer.mount(card);
          });
        }
        for (const action of ['cancel','retry']) $('.job-'+action,card).onclick = async () => {
          try { await post(action === 'cancel' ? `/control/${job.id}/cancel` : `/retry/${job.id}`, {}); await refreshJobs(); }
          catch(error) { notice(error.message); }
        };
        $('.job-clone',card).onclick = async () => {
          try {
            const source = await api(`/api/jobs/${job.id}`);
            await onClone(source);
          } catch(error) { notice(error.message); }
        };
        // A completed coarse-grained run is the only run the comparison can be read from, so that is where the
        // panel is offered from. Whether a comparison was actually published is the panel's own answer to give,
        // and when it was, the control states what it found instead of offering a blank door.
        // The control's *state* is set on every render below, next to the status: it depends on the run's status and
        // on whether a comparison was published, both of which change after the card is created. Only the handler
        // belongs here, because the run id it closes over does not change.
        $('.job-validate', card).onclick = () => { try { onValidate(job.id); } catch (error) { notice(error.message); } };
        $('.job-resume',card).onclick = async () => {
          try { await post(`/api/jobs/${job.id}/resume`,{stage:$('.resume-stage',card).value}); notice('Run resumed; current stage files will be executed.'); await refreshJobs(); }
          catch(error) { notice(error.message); }
        };
        card.artifactPage = 1;
        $('.artifacts-prev',card).onclick = () => { card.artifactPage--; refreshArtifactViews(card,job).catch(error=>notice(error.message)); };
        $('.artifacts-next',card).onclick = () => { card.artifactPage++; refreshArtifactViews(card,job).catch(error=>notice(error.message)); };
        $('.artifact-search',card).oninput = () => { card.artifactPage = 1; refreshArtifactViews(card,job).catch(error=>notice(error.message)); };
        for (const detail of ['.job-artifacts','.job-analysis']) $(detail,card).addEventListener('toggle', () => {
          if ($(detail,card).open) refreshArtifactViews(card,card.job, true).catch(error=>notice(error.message));
        });
        $('.job-records',card).addEventListener('toggle',()=>{if($('.job-records',card).open)refreshRecords(card,card.job);});
        $('.job-delete', card).onclick = async event => {
          if (!window.confirm('Delete this run, its console log, and all generated artifacts? This cannot be undone.')) return;
          const button = event.currentTarget; button.disabled = true;
          try {
            await api(`/api/jobs/${job.id}`, {method: 'DELETE'});
            invalidateResource('/api/references'); invalidateResource('/api/storage');
            onDeleted(job.id);
            cards.delete(job.id); if (consoleViewer.selectedRun === job.id) consoleViewer.select('');
            card.figureViewer?.destroy(); card.remove(); notice('Run deleted.'); await refreshJobs();
          } catch (error) { notice(error.message); button.disabled = false; }
        };
        if (![...$('#console-run').options].some(option=>option.value === job.id)) { const option = document.createElement('option'); option.value = job.id; option.textContent = `${job.detergent} · ${job.id}`; $('#console-run').append(option); }
      }
      card.job=job;
      if (previousCard.nextElementSibling !== card) previousCard.after(card); previousCard = card;
      setText($('.job-title', card), (job.label || `${job.detergent} · ${job.method}`) + (job.profile === 'draft-smoke' ? ' · Draft smoke test' : ''));
      setText($('.job-meta', card), job.id);
      setText($('.job-molecule', card), job.molecule_name || job.detergent || '—');
      setText($('.job-method', card), {fast_forward: 'Fast_Forward', bartender: 'Bartender'}[job.method] || job.method);
      setText($('.job-created', card), job.created ? new Date(job.created).toLocaleString() : '—');
      setText($('.job-status', card), job.status === 'cancelling' ? 'Cancelling…' : job.status);
      $('.job-status', card).dataset.status = job.status;
      // Re-set on every render, not only at creation: a run that finishes while this page is open must offer its
      // comparison without a reload, and one whose comparison publishes later must stop reading as a blank door.
      // The handler is attached once, in the creation block, because the run id it closes over never changes.
      const validate = $('.job-validate', card);
      validate.hidden = !(job.run_type === 'aa_cg' && job.status === 'completed');
      setText(validate, consistencyLine(job) || 'Mapping validation');
      setText($('.job-stage', card), job.stage || 'Queued');
      // A run that declared itself a stub says so on the card, next to the status it
      // would otherwise share with a run that really executed the stage.
      const note = $('.execution-note', card);
      note.hidden = !job.execution_note; setText(note, job.execution_note || '');
      setText($('.job-elapsed', card), duration(job.elapsed_seconds));
      const eta = job.status !== 'running' ? '—' : job.gromacs_eta ? `GROMACS: ${job.gromacs_eta}` : job.gromacs_remaining_seconds !== undefined ? `GROMACS: ${duration(job.gromacs_remaining_seconds)} remaining` : 'Waiting for GROMACS estimate';
      setText($('.job-eta', card), eta);
      $('.job-error', card).hidden = !job.error;
      setText($('.job-error', card), job.error ? String(job.error).split('\n')[0] : '');
      $('.job-cancel', card).hidden = !job.can_cancel;
      $('.job-retry', card).hidden = !job.can_retry;
      $('.job-delete', card).hidden = !job.can_delete;
      $('.job-resume',card).hidden = !job.resume_stages?.length; $('.resume-control',card).hidden = !job.resume_stages?.length;
      const resumeSelect = $('.resume-stage',card), previousStage = resumeSelect.value;
      resumeSelect.replaceChildren(...(job.resume_stages || []).map(name=>new Option(name,name)));
      if ((job.resume_stages || []).includes(previousStage)) resumeSelect.value = previousStage; else if (job.resume_stages?.length) resumeSelect.value = job.resume_stages.at(-1);
      setText($('.job-validation',card),'Scientific validation: not established. ' + (job.metadata_warnings || []).join(' '));
      if($('.job-records',card).open)refreshRecords(card,job);
      const stageKey = JSON.stringify([job.stages || [],job.status,job.stage,job.workflow_stages]);
      if (card.dataset.stages !== stageKey) {
        const stageMap = new Map((job.stages || []).map(stage => [stage.name, stage]));
        const timeline = $('.workflow-timeline', card); timeline.replaceChildren();
        const names = job.workflow_stages?.length ? job.workflow_stages : (job.stages || []).map(stage => stage.name);
        for (const name of names) {
          const step = document.createElement('li'); step.className = 'timeline-step';
          const record = stageMap.get(name);
          const state = record?.status || (job.stage === name && ['running','failed','cancelled','cancelling'].includes(job.status) ? job.status : 'pending');
          step.dataset.status = state; step.tabIndex = 0;
          if (['running', 'cancelling'].includes(state)) step.setAttribute('aria-current', 'step');
          const elapsed = record ? stageDurationSeconds(record.started_at, record.ended_at) : null;
          const description = `${name}: ${state}${elapsed !== null ? ' · ' + duration(elapsed) : ''}`;
          step.title = description; step.setAttribute('aria-label', description);
          const dot = document.createElement('span'); dot.className = 'timeline-dot'; dot.setAttribute('aria-hidden', 'true');
          dot.textContent = {completed:'✓', reused:'↗', skipped:'–', failed:'×', cancelled:'■', running:'●', cancelling:'●'}[state] || '';
          const label = document.createElement('span'); label.className = 'timeline-label';
          // Two spellings for one stage: it was named after the tool it used to call, and 21 runs record it that way.
          // Their manifests keep the words they ran under -- only the visible abbreviation is shared, and the full
          // name still reaches the tooltip and the aria-label, so history is not rewritten to match the code.
          label.textContent = {'AA reference':'AA ref.', 'trajectory mapping':'Map', 'trajectory mapping (ff_map)':'Map',
                               'CG topology (ff_inter)':'Fit', 'CG simulation':'CG run',
                               'CG assessment (ff_assess)':'Assess', 'SASA analysis':'SASA'}[name] || name;
          step.append(dot, label); timeline.append(step);
        }
        card.dataset.stages = stageKey;
      }
      const tasksKey = JSON.stringify([job.analyses || [], job.artifact_revision, job.stages]);
      if (card.dataset.tasks !== tasksKey) {
        const taskList = $('.analysis-tasks',card); taskList.replaceChildren();
        for (const task of job.analyses || []) {
          const row = document.createElement('p'); row.textContent = `${task.kind} · ${task.status} · ${task.progress || task.error || ''}`;
          if (['queued','running','cancelling'].includes(task.status)) {
            const cancel = document.createElement('button'); cancel.className = 'secondary'; cancel.textContent = 'Cancel analysis'; cancel.disabled = task.status === 'cancelling';
            cancel.onclick = async () => { try { await post(`/api/jobs/${job.id}/analyses/${task.id}/cancel`,{}); await refreshJobs(); } catch(error) { notice(error.message); } }; row.append(cancel);
          }
          const link = document.createElement('a'); link.href = `/api/jobs/${job.id}/artifacts/${task.directory}/console.log`; link.textContent = ' Analysis log'; row.append(link);
          taskList.append(row);
        }
        card.dataset.tasks = tasksKey;
        if ($('.job-artifacts',card).open || $('.job-analysis',card).open) refreshArtifactViews(card,job).catch(error=>notice(error.message));
      }

    }
    const consoleCard = cards.get(consoleViewer.selectedRun);
    if (consoleCard && $('.job-console', consoleCard).open && !consoleCard.contains($('#console-panel'))) consoleViewer.mount(consoleCard);
  }
  async function refreshRecords(card, job) {
    const key=JSON.stringify([job.detail_revision,job.revision]);
    if(card.recordsKey===key || card.recordsPending===key)return;
    card.recordsPending=key;
    try {
      const detail=await api('/api/jobs/'+job.id);
      if(card.recordsPending!==key)return;
      job=detail;
      setText($('.job-command', card), (job.command || 'Command not recorded') + (job.error ? '\n\n' + job.error : ''));
        const records = $('.job-stages', card); records.replaceChildren();
        for (const stage of job.stages || []) {
          const line = document.createElement('p'); line.className = 'hint';
          line.textContent = `${stage.name} · ${stage.status} · ${stage.started_at || 'Start not recorded'} → ${stage.ended_at || 'End not recorded'} · exit ${stage.exit_code ?? '—'} · duration ${duration(stage.resource_usage?.wall_seconds)}`; records.append(line);
          const evidence = document.createElement('pre'); evidence.textContent = JSON.stringify({command:stage.command, inputs:stage.inputs, input_hashes:stage.inputs_sha256, outputs:stage.outputs, output_hashes:stage.outputs_sha256, environment:stage.environment, log:stage.log, resources:stage.resource_usage, error:stage.error, source_run:stage.source_run},null,2); records.append(evidence);
        }
      card.recordsKey=key;
    } catch(error) { if(card.recordsPending===key)setText($('.job-command',card),error.message); }
    finally { if(card.recordsPending===key)card.recordsPending=null; }
  }
  let runPage = 1, jobsGeneration = 0, jobsEtag = '', pollDelay = 5000;
  async function refreshArtifactViews(card,job,force=false) {
    const generation = (card.artifactGeneration || 0)+1; card.artifactGeneration = generation;
    if($('.job-artifacts',card).open) {
    const query = new URLSearchParams({page:card.artifactPage || 1, limit:25, search:$('.artifact-search',card).value});
    // One refresh feeds both panels of a card -- the artifact list and the analysis figures --
    // so this guard has to be per call, not per panel: sharing a generation between them drops
    // the answer the other panel is waiting for. It stays a counter of its own for that reason.
    const result = await api(`/api/jobs/${job.id}/artifacts?${query}`);
    if (generation !== card.artifactGeneration) return;
    const list = $('.artifact-list',card); list.replaceChildren();
    for (const artifact of result.artifacts) {
      const row = document.createElement('div'), link = document.createElement('a');
      link.href = `/api/jobs/${job.id}/artifacts/${artifact.path.split('/').map(encodeURIComponent).join('/')}`;
      link.textContent = `${artifact.path} · ${artifact.bytes.toLocaleString()} bytes`; link.download = artifact.path.split('/').pop(); row.append(link); list.append(row);
    }
    setText($('.artifact-summary',card),`${result.total} matching files`);
    setText($('.artifacts-page',card),`Page ${result.page}`);
    $('.artifacts-prev',card).disabled = result.page <= 1; $('.artifacts-next',card).disabled = result.page*result.limit >= result.total;
    }
    if ($('.job-analysis',card).open && (force || !card.figureViewer || card.figureRevision!==job.artifact_revision)) {
      const media = await api(`/api/jobs/${job.id}/figures${force?'?refresh=1':''}`);
      if (generation !== card.artifactGeneration) return;
      const figures = media.artifacts;
      card.figureRevision=media.revision;
      if(!card.figureViewer)card.figureViewer=new RunFigureViewer($('.analysis-plots',card),job.id);
      card.figureViewer.update(figures);
      renderDistanceDiagnostics(card, job).catch(() => {});
    }
  }
  async function refreshJobs(conditional=false) {
    const query = new URLSearchParams({view:'summary',page:runPage,limit:20,status:$('#run-status-filter').value,search:$('#run-search').value});
    // One loader for the table: a poll that lands after a newer one is dropped with its
    // answer. A 304 is not an answer, and stays a no-op here.
    const payload = await guarded('runs:jobs', async () => {
      const response = await fetch('/api/jobs?'+query,{headers:conditional && jobsEtag ? {'If-None-Match':jobsEtag} : {},signal:AbortSignal.timeout(10000)});
      if (response.status === 304) return null;
      if (!response.ok) throw new Error(`Run updates failed (${response.status})`);
      return {result: await response.json(), etag: response.headers.get('etag') || ''};
    });
    if (payload === DROP || payload === null) return;
    jobsEtag = payload.etag; updateJobs(payload.result.jobs);
    setText($('#runs-page'),`Page ${payload.result.page} · ${payload.result.total} runs`);
    $('#runs-prev').disabled = payload.result.page <= 1; $('#runs-next').disabled = payload.result.page*payload.result.limit >= payload.result.total;
  }
  $('#runs-prev').onclick = () => { runPage--; jobsEtag=''; refreshJobs().catch(e=>notice(e.message)); };
  $('#runs-next').onclick = () => { runPage++; jobsEtag=''; refreshJobs().catch(e=>notice(e.message)); };
  let searchTimer;
  for (const element of [$('#run-search'),$('#run-status-filter')]) element.oninput = () => { runPage=1; jobsEtag=''; clearTimeout(searchTimer); searchTimer=setTimeout(()=>refreshJobs().catch(e=>notice(e.message)),150); };
  let pollTimer, polling=false;
  async function poll() {
    if(polling) return;
    clearTimeout(pollTimer);
    if ($('#runs').hidden || document.hidden || !navigator.onLine) { pollTimer=setTimeout(poll,30000); return; }
    polling=true;
    try { await refreshJobs(true); await consoleViewer.refresh(); pollDelay=5000; setText($('#connection'),`Updated ${new Date().toLocaleTimeString()}`); }
    catch(error) { pollDelay=Math.min(pollDelay*2,60000); setText($('#connection'),`Updates unavailable: ${error.message}. Retrying in ${pollDelay/1000}s.`); }
    finally { polling=false; pollTimer=setTimeout(poll,pollDelay); }
  }
  for (const event of ['visibilitychange','online']) window.addEventListener(event,()=>{ if (!document.hidden) poll(); });
  async function refreshStorage(force=false) {
    try {
      if(force)invalidateResource('/api/storage');
      const result=await cachedApi(force?'/api/storage?refresh=1':'/api/storage',{maxAge:10000}), gib=n=>(n/1073741824).toFixed(2)+' GiB';
      const text=`Storage: ${gib(result.run_bytes)} / ${gib(result.limits.max_total_bytes)} quota; ${gib(result.disk_free_bytes)} free. ${result.retention_candidates.length} runs older than ${result.limits.retention_days} days for manual review. No automatic deletion.`;
      setText($('#storage-report'),text); setText($('#new-storage'),text);
    } catch(error) { setText($('#storage-report'),error.message); }
  }
  $('#refresh-storage').onclick=()=>refreshStorage(true);



  return { refreshJobs, refreshConsole: consoleViewer.refresh, refreshStorage,
    mount() { poll(); refreshStorage(); }, start() {} }; 
}
