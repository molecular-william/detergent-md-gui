"""Runs HTTP endpoints."""
import codecs
import hashlib
import json
import os
import tempfile
import uuid
import zipfile

from flask import Blueprint, Response, abort, jsonify, render_template, request, send_file

from dashboard import files

from ...execution.adapters import aa, cg
from ...execution.adapters.micelle import run_micelle_job
from ...execution.coordination import admission
from ...models.molecules import aa as aa_molecules
from .. import views
from ..sections import PANELS, SECTIONS, TAB_IDS, legacy_tab_targets, section_by_slug
from .common import coordinator, json_object, pagination

blueprint = Blueprint('runs', __name__)


def view_of(c, job, summary=False):
    """The browser's view of one run: the view module decides, the coordinator supplies.

    Two of its inputs are the coordinator's to know -- which of its workers holds the
    run, and where the console log is (outside the run directory in the pre-2.0 layout).
    """
    run_dir = c.run_path(job) if views.usable_run_id(job) else None
    if run_dir is None:
        return views.run_view(job, summary=summary)
    return views.run_view(job, run_dir=run_dir, manifest=c.manifest_data(job),
                          ownership=c.ownership(job), busy=c.externally_busy(job),
                          console_log=c.log_path(job), summary=summary)


def workspace_context(section, panel):
    """What the shell needs to render a workspace: the active workspace, its panel, and the registries.

    One place rather than three, because the three routes that render it must not be able to disagree about what the
    template is handed -- and `legacy_tabs` is what answers the old `/#tab` bookmarks the previous navigation wrote.

    `section` arrives as a URL **slug** and `workspace` is that slug's record. An unknown slug raises rather than
    resolving to `None`, and that guard is the fix for a real failure: the front door passed the registry's *key*
    where a slug was expected, `section_by_slug` returned `None`, and the template's `{% for slug in workspace.tabs %}`
    iterated an undefined value -- which Jinja does silently. The page rendered its two workspace tabs and an empty
    row beneath them, with no error in the console and no test noticing. A `TypeError` here is a far better outcome
    than a page that is quietly missing a third of itself.
    """
    found = section_by_slug(section)
    if found is None:
        raise ValueError(f'no workspace has the slug {section!r}')
    return dict(section=section, panel=panel, workspace=found, workspaces=SECTIONS,
                panel_info=PANELS, tab_ids=TAB_IDS, legacy_tabs=legacy_tab_targets())


@blueprint.get('/')
def index():
    """The front door, and the only page whose workspace is not in its URL.

    It renders validation -- a browser with no memory of another workspace lands there -- and the shell replaces the
    URL with the remembered one if there is one. Rendering rather than redirecting is deliberate: a redirect would
    put a chosen-looking URL in the history when the root is not somewhere anyone chose to be, and it would give
    validation two canonical paths instead of one.
    """
    return render_template('dashboard.html',
                           **workspace_context(SECTIONS['validation']['slug'],
                                               SECTIONS['validation']['tabs'][0]))


@blueprint.get('/<section>')
def section_view(section):
    """A workspace, opened on its first panel."""
    found = section_by_slug(section)
    if found is None:
        abort(404)
    return render_template('dashboard.html', **workspace_context(section, found['tabs'][0]))


@blueprint.get('/<section>/<panel>')
def panel_view(section, panel):
    """One panel of one workspace.

    A panel this workspace does not have is a **404**, not a substituted tab. The old page answered a tab name it did
    not recognise with the first tab it had, which is how a wrong link became a wrong page with no report; a URL that
    names a panel is checkable, so it is checked.
    """
    found = section_by_slug(section)
    if found is None or panel not in found['tabs']:
        abort(404)
    return render_template('dashboard.html', **workspace_context(section, panel))


@blueprint.get('/api/jobs')
def jobs_api():
    """One shape for every request form: an object that names the page it answered.

    The bare array this used to return when `page` was absent gave one endpoint two
    response shapes, and every client had to defend against both.
    """
    c = coordinator()
    summary = request.args.get('view') == 'summary'
    page, limit = pagination()
    rows, total = c.database().page(page, limit, request.args.get('status',''), request.args.get('search','')[:160])
    payload = {'jobs': [view_of(c, j, summary=summary) | {'revision': revision} for j,revision in rows], 'total': total, 'page': page, 'limit': limit}
    etag = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if request.if_none_match.contains(etag): return Response(status=304, headers={'ETag': etag})
    response = jsonify(payload); response.set_etag(etag); return response


@blueprint.post('/')
def queue():
    c = coordinator()
    data = json_object(optional=True) or request.form
    admission.validate_run_type(data)
    if 'molecule_id' in data:
        try: aa_molecules.validate_id(data['molecule_id'])
        except ValueError as exc: abort(400, str(exc))
    intent=data.get('bonded_intent','fit_and_simulate')
    if intent not in ('fit_and_simulate','fit_only','reuse_state'): abort(400,'Unknown bonded run intent')
    aa_specs=set(aa.SETTING_SPECS)|set(aa.CHOICE_SPECS)
    if data.get('run_type')=='pdc':
        from ...execution.adapters import pdc
        specs=set(pdc.SETTING_SPECS)
    else:
        specs=aa_specs if data.get('run_type')=='aa_only' else set(cg.SETTING_SPECS)|aa_specs
    job = c.create_job(data.get('detergent') or data.get('molecule_id') or data.get('composition_id'), data.get('method'), data.get('label', ''), profile=data.get('profile', 'standard'), settings={k: data.get(k) for k in specs if data.get(k) not in (None, '')}, reference_run_id=data.get('reference_run_id') or None, mapping_candidate=data.get('mapping_candidate'), bonded_state_id=data.get('bonded_state_id') or None, bonded_intent=intent, temporary_validation=str(data.get('temporary_validation','')).lower() in ('1','true','yes'), molecule_id=data.get('molecule_id'),run_type=data.get('run_type'), composition_id=data.get('composition_id'), protein=data.get('protein') or None, template=data.get('template') or None)
    return jsonify(view_of(c, job)), 201


@blueprint.post('/api/micelle/build')
def micelle_build_api():
    """Thin adapter for the native micelle CLI; reports are ordinary run artifacts."""
    c = coordinator()
    payload = json_object()
    jid = uuid.uuid4().hex[:12]
    job = {'id': jid, 'label': payload.get('label') or 'Micelle build', 'detergent': payload.get('detergent','DDM'),
           'method': 'micelle', 'status': 'running', 'stage': 'micelle build', 'created': c.now(), 'profile': 'micelle', 'settings': payload}
    with c.JOBS_LOCK:
        c.database().insert(job)
    directory = c.RUNS / jid; directory.mkdir(parents=True, exist_ok=False)
    try:
        result = run_micelle_job(payload, directory)
        (directory/'logs').mkdir(exist_ok=True)
        (directory/'logs/console.log').write_text(result.get('stdout','') + result.get('stderr',''))
        c.database().update(jid, status='completed' if result['status']=='completed' else 'failed', stage='complete' if result['status']=='completed' else 'micelle build', ended_at=c.now(), error=result.get('stderr') if result['status']!='completed' else None, command=' '.join(result['command']))
    except Exception as exc:
        c.database().update(jid, status='failed', stage='micelle build', ended_at=c.now(), error=str(exc))
    return jsonify(view_of(c, c.lookup(jid))), 201


@blueprint.post('/control/<jid>/<action>')
def control(jid, action):
    c = coordinator()
    if action != 'cancel': abort(400, 'Only cancellation is supported')
    job, status = c.cancel_job(jid)
    return jsonify(view_of(c, job)), status


@blueprint.post('/retry/<jid>')
def retry(jid):
    c = coordinator()
    job = c.lookup(jid)
    if job['status'] != 'failed':
        abort(409, 'Only failed runs can be retried')
    new = c.create_job(job['detergent'], job['method'], job.get('label', ''), retry_of=jid, profile=job.get('profile', 'standard'), settings=job.get('settings'), reference_run_id=job.get('reference_run_id'), mapping_snapshot=job.get('mapping_snapshot'), molecule_id=job.get('molecule_id'), molecule_snapshot=job.get('molecule_snapshot'),run_type=job.get('run_type'),bonded_state_id=job.get('bonded_state_id'),bonded_intent=job.get('bonded_intent','fit_and_simulate'))
    return jsonify(view_of(c, new)), 201


@blueprint.get('/api/jobs/<jid>/log')
def console_api(jid):
    c = coordinator()
    job = c.lookup(jid)
    path = c.log_path(job)
    if job.get('layout_version') == 2 and request.args.get('download') != '1':
        stage = next((s for s in reversed(c.manifest_data(job).get('stages', [])) if s.get('log')), None)
        if stage:
            candidate = c.stage_log_path(job, stage['log'])
            if candidate: path = candidate
    source_key = str(path.relative_to(c.run_path(job))) if path.is_relative_to(c.run_path(job)) else path.name
    if request.args.get('download') == '1':
        if job.get('layout_version') == 2:
            buffer = tempfile.SpooledTemporaryFile(max_size=8*1024*1024)
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
                for item in files.safe_files(c.run_path(job)/'logs'): archive.write(item, item.name)
            buffer.seek(0)
            response = send_file(buffer, as_attachment=True, download_name=f'{jid}-logs.zip', mimetype='application/zip')
            response.call_on_close(buffer.close)
            return response
        if not path.is_file():
            abort(404, 'No console output yet')
        return send_file(path, as_attachment=True, download_name=f'{jid}.log', mimetype='text/plain')
    try:
        offset = int(request.args.get('offset', '0'))
        if offset < 0:
            raise ValueError
    except ValueError:
        abort(400, 'Invalid log offset')
    if not path.is_file():
        return jsonify(text='', offset=0, reset=offset != 0)
    with path.open('rb') as fp:
        size = os.fstat(fp.fileno()).st_size
        reset = offset > size or request.args.get('source', source_key) != source_key
        if reset: offset = 0
        # First open shows the tail. Subsequent reads append bounded chunks.
        if offset == 0: offset = max(0, size - 65536)
        fp.seek(offset)
        data = fp.read(65536)
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        text = decoder.decode(data, final=fp.tell() >= size)
        unread = len(decoder.getstate()[0])
        return jsonify(text=text, offset=fp.tell() - unread, reset=reset, source=source_key)


@blueprint.delete('/api/jobs/<jid>')
def delete_job(jid):
    return jsonify(deleted=coordinator().delete_job(jid))


@blueprint.get('/api/jobs/<jid>')
def job_detail(jid):
    c = coordinator()
    job = c.lookup(jid)
    return jsonify(view_of(c, job) | {'tools': c.manifest_data(job).get('tools', {})})


@blueprint.post('/api/jobs/<jid>/clone')
def clone_job(jid):
    c = coordinator()
    source = c.lookup(jid); data = json_object(optional=True)
    effective_type=data.get('run_type',source.get('run_type'))
    admission.validate_run_type(dict(data,run_type=effective_type))
    if 'molecule_id' in data:
        try: aa_molecules.validate_id(data['molecule_id'])
        except ValueError as exc: abort(400, str(exc))
    new = c.create_job(source['detergent'], source['method'], data.get('label', source.get('label','')+' copy'),
                     retry_of=jid, profile=data.get('profile', source.get('profile','standard')),
                     settings=data.get('settings', source.get('settings')), reference_run_id=(data.get('reference_run_id',source.get('reference_run_id')) or None) if effective_type!='aa_only' else None,
                     mapping_candidate=data.get('mapping_candidate'), mapping_snapshot=source.get('mapping_snapshot') if data.get('run_type',source.get('run_type'))!='aa_only' and data.get('mapping_candidate', source.get('mapping_candidate')) == source.get('mapping_candidate') else None, molecule_id=data.get('molecule_id', source.get('molecule_id')),
                     run_type=effective_type,bonded_state_id=None if effective_type=='aa_only' else data.get('bonded_state_id',source.get('bonded_state_id')),bonded_intent=data.get('bonded_intent',source.get('bonded_intent','fit_and_simulate')))
    return jsonify(view_of(c, new)), 201


@blueprint.post('/api/jobs/<jid>/resume')
def resume_job(jid):
    c = coordinator()
    data = json_object(optional=True)
    job = c.resume_in_place(jid, data.get('stage'))
    return jsonify(view_of(c, job)), 200


@blueprint.get('/api/jobs/<jid>/artifacts')
def artifacts_api(jid):
    """One shape for every request form, as /api/jobs answers: an object naming the page."""
    c = coordinator()
    # Refresh when figures are requested so newly generated diagnostics become visible
    # without waiting for a job-state transition or process restart.
    entries = c.artifact_index(c.lookup(jid), refresh=request.args.get('media') == '1')
    page, limit = pagination(); search = request.args.get('search','').lower()
    entries = [e for e in entries if search in e['path'].lower()]
    if request.args.get('media') == '1': entries = [e for e in entries if e['path'].endswith(('.png','.svg','surface-comparison.html'))]
    return jsonify(artifacts=entries[(page-1)*limit:page*limit], total=len(entries), page=page, limit=limit)


@blueprint.get('/api/jobs/<jid>/figures')
def figures_api(jid):
    c = coordinator()
    entries = c.artifact_index(c.lookup(jid), refresh=request.args.get('refresh') == '1')
    return jsonify(artifacts=[e for e in entries if e['path'].endswith(('.png','.svg','surface-comparison.html'))],
                   revision=c.lookup(jid).get('artifact_revision'))


@blueprint.get('/api/jobs/<jid>/artifacts/<path:relative>')
def artifact_file(jid, relative):
    c = coordinator()
    run_dir = c.run_path(c.lookup(jid)).resolve()
    candidate = run_dir/relative
    if any(part.is_symlink() for part in (candidate,*candidate.parents) if part.is_relative_to(run_dir)): abort(404, 'Symlink artifacts are excluded')
    path = candidate.resolve()
    if run_dir not in path.parents or not path.is_file():
        abort(404, 'Unknown artifact')
    response = send_file(path, as_attachment=request.args.get('inline') != '1', download_name=path.name)
    if path.suffix == '.html': response.headers['Content-Security-Policy'] = "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; worker-src blob:"
    return response
