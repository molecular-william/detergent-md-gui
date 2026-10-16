"""Runs HTTP endpoints."""
import codecs
import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify, render_template, request, send_file

from dashboard import files

from ...analysis.runs.figures import current_figures
from ...execution import protocol
from ...execution.adapters import pdc_view
from ...execution.adapters.micelle import run_micelle_job
from ...execution.coordination import admission
from ...models.molecules import aa as aa_molecules
from .. import views
from ..sections import PANELS, SECTIONS, TAB_IDS, legacy_tab_targets, run_types_for, section_by_slug
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
                panel_info=PANELS, tab_ids=TAB_IDS, legacy_tabs=legacy_tab_targets(),
                # The Run view panel's scope, from the registry's own per-workspace `run_types`: the panel asks
                # `/api/jobs` for these by name, so what it can reach is the registry's answer and not a list the
                # JavaScript keeps for itself. Handed to the template rather than to the module, because the
                # module must not have to know which workspace rendered the page.
                run_view_scope={'slug': found['slug'], 'types': list(run_types_for(found['slug']))})


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


def pages_of_runs(c, page, limit, status='', search='', run_type=''):
    """One page of run records, optionally narrowed to a single run type.

    **The run-type clause lives here rather than in `Store.page`.** That method is the one place the run list's
    ordering and its search clause are decided, and it has four other callers that want every run; the narrowing
    is a *view* over the same list, so the clause below is written to agree with it exactly -- newest first, the
    same status and substring tests -- and the filtered answer is asserted to be the unfiltered one narrowed
    (`test_jobs_run_type_filter.py`). The alternative, filtering a fetched page in Python, would move the page
    boundaries: `total` and `has_more` would count runs the caller asked not to see.

    An absent `run_type` on a record means the historical combined AA-to-CG job
    (`protocol.run_type_of`), so filtering for `aa_cg` finds those too rather than reporting them as nothing.
    """
    store = c.database()
    if not run_type:
        return store.page(page, limit, status, search)
    clause = ("WHERE (?='' OR json_extract(data,'$.status')=?) AND (?='' OR instr(lower(data),lower(?))>0) "
              "AND COALESCE(json_extract(data,'$.run_type'),'aa_cg')=?")
    args = (status, status, search, search, run_type)
    with store.connection() as db:
        count = db.execute('SELECT count(*) FROM jobs ' + clause, args).fetchone()[0]
        rows = db.execute("SELECT data,revision FROM jobs " + clause
                          + " ORDER BY json_extract(data,'$.created') DESC, rowid DESC LIMIT ? OFFSET ?",
                          (*args, limit, (page - 1) * limit)).fetchall()
    return [(json.loads(row[0]), row[1]) for row in rows], count


@blueprint.get('/api/jobs')
def jobs_api():
    """One shape for every request form: an object that names the page it answered.

    The bare array this used to return when `page` was absent gave one endpoint two
    response shapes, and every client had to defend against both.

    **`run_type` narrows the list, and its absence changes nothing.** Every existing caller -- the run table's own
    refresh, the mapping-validation workspace, the pdc workspace, all three at `?limit=100` -- sends no
    `run_type` and gets exactly what it got before. A caller that names one gets only that run type, with `total`,
    `page` and `limit` describing the narrowed list rather than a hidden superset: a panel that filters after
    paging would show twenty rows and claim there were more of another kind. The value is checked against the
    registry of run types rather than accepted as free text, so a typo is a 400 that names the vocabulary instead
    of an empty page that reads as "none of those exist".
    """
    c = coordinator()
    summary = request.args.get('view') == 'summary'
    page, limit = pagination()
    run_type = request.args.get('run_type', '').strip()
    if run_type and run_type not in protocol.RUN_TYPES:
        abort(400, 'Unknown run type; one of: ' + ', '.join(protocol.RUN_TYPES))
    rows, total = pages_of_runs(c, page, limit, request.args.get('status', ''),
                                request.args.get('search', '')[:160], run_type)
    payload = {'jobs': [view_of(c, j, summary=summary) | {'revision': revision} for j, revision in rows],
               'total': total, 'page': page, 'limit': limit}
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
    # There is no per-run bonded intent or bonded-state selection to read any more (D1): `aa_cg` always fits its own
    # bonded parameters from the AA reference. The run contract lost both fields, so the route neither validates an
    # intent nor passes either key to `create_job` -- `admission.validate_run_type` is what still refuses a payload
    # that names a field its run type does not own (`AA_ONLY_FORBIDDEN`).
    # One question to the run type: which settings does it accept? The route used to answer this by unioning the AA
    # and CG dialect tables itself -- `cg.SETTING_SPECS | aa.SETTING_SPECS | aa.CHOICE_SPECS` for everything that was
    # not `aa_only` or `pdc`. That is the right answer for the run types composing those two halves and the wrong one
    # for `osmotic`, whose own settings (the molality above all) are in neither.
    run_type = protocol.run_type_of(data)
    adapter = protocol.adapter_for(run_type)
    specs = set(adapter.settings_specs()) | set(adapter.choice_specs())
    # The AA-CG run type's profile is the run type's own, not a panel choice (D2): the New run panel no longer offers
    # it, so a request that names none is stamped with the shape recorded by every AA-CG run, and the manifest keeps
    # saying which shape ran. A caller that names one explicitly still gets what it asked for -- an AA-CG run attaching
    # a short AA reference is a case the reference-compatibility check below has to be able to see and refuse.
    profile = data.get('profile') or ('draft-smoke-reference' if run_type == 'aa_cg' else 'standard')
    job = c.create_job(data.get('detergent') or data.get('molecule_id') or data.get('composition_id'), data.get('method'), data.get('label', ''), profile=profile, settings={k: data.get(k) for k in specs if data.get(k) not in (None, '')}, reference_run_id=data.get('reference_run_id') or None, mapping_candidate=data.get('mapping_candidate'), temporary_validation=str(data.get('temporary_validation','')).lower() in ('1','true','yes'), molecule_id=data.get('molecule_id'),run_type=data.get('run_type'), composition_id=data.get('composition_id'), protein=data.get('protein') or None, template=data.get('template') or None)
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
        c.database().update(jid, status='completed' if result['status']=='completed' else 'failed', stage='complete' if result['status']=='completed' else 'micelle build', ended_at=c.now(), error=result.get('error'), command=' '.join(result['command']))
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
    new = c.create_job(job['detergent'], job['method'], job.get('label', ''), retry_of=jid, profile=job.get('profile', 'standard'), settings=job.get('settings'), reference_run_id=job.get('reference_run_id'), mapping_snapshot=job.get('mapping_snapshot'), molecule_id=job.get('molecule_id'), molecule_snapshot=job.get('molecule_snapshot'),run_type=job.get('run_type'))
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
                     run_type=effective_type)
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
    # A client that has just changed this run's files asks for a re-read: `media=1` where it is about to show the
    # figures, `refresh=1` where it queued an analysis and is waiting for what that analysis will publish. The index
    # is cached in the store, and a *completed* run's is otherwise frozen for the life of the process -- which is
    # what a run that published frames would have to wait for a restart to show.
    entries = c.artifact_index(c.lookup(jid), refresh=request.args.get('refresh') == '1'
                               or request.args.get('media') == '1')
    page, limit = pagination(); search = request.args.get('search','').lower()
    entries = [e for e in entries if search in e['path'].lower()]
    if request.args.get('media') == '1': entries = [e for e in entries if e['path'].endswith(('.png','.svg','surface-comparison.html'))]
    return jsonify(artifacts=entries[(page-1)*limit:page*limit], total=len(entries), page=page, limit=limit)


@blueprint.get('/api/jobs/<jid>/figures')
def figures_api(jid):
    """The figures the run currently publishes, and how many published sets a newer one replaced.

    Not every image the index holds: an analysis publishes its figures again on every attempt, so the plain listing
    is mostly a file's own earlier selves -- measured, this workspace's sucrose CG run holds 38 images of which 33
    are the same three snapshot SVGs. `dashboard.analysis.runs.figures` holds the rule and its reasoning; the older
    sets stay on disk and are reachable through the artifact route the Runs gallery reads.
    """
    c = coordinator()
    entries = c.artifact_index(c.lookup(jid), refresh=request.args.get('refresh') == '1')
    figures, superseded = current_figures(
        [e for e in entries if e['path'].endswith(('.png', '.svg', 'surface-comparison.html'))])
    return jsonify(artifacts=figures, superseded=superseded,
                   revision=c.lookup(jid).get('artifact_revision'))


def structure_target(run_dir, relative: str) -> Path:
    """The file a run-relative path names, or a refusal that says which.

    A path is relative to the run directory and to nothing else, so a path that resolves outside it -- through
    `..`, or through a symlink anywhere along the way -- is a 404 rather than a way to read the filesystem. The
    guard is the artifact route's own (`artifact_file`), written out here rather than shared because the two answer
    differently: that one serves any file, this one refuses anything that is not a `.gro`.
    """
    run_dir = Path(run_dir).resolve()
    if not relative:
        abort(400, 'path is required: the run-relative .gro this route serves')
    candidate = run_dir / relative
    if any(part.is_symlink() for part in (candidate, *candidate.parents) if part.is_relative_to(run_dir)):
        abort(404, f'{relative} is not a file in this run')
    path = candidate.resolve()
    if run_dir not in path.parents or not path.is_file():
        abort(404, f'{relative} is not a file in this run')
    if path.suffix.lower() != '.gro':
        abort(400, f'{relative} is not a .gro: this route writes the bonds a .gro cannot carry, and a .pdb '
                   'already carries its own records — the artifact route serves it')
    return path


def run_topology(run_dir, manifest=None) -> Path | None:
    """The run's own coarse-grained moleculetype, or `None` when the run states none.

    The location is the run's own layout rule (`analysis.runs.layout.cg_topology`): the `.itp` under
    `stages/3_initial_CG/` that is not a system topology, searched at the run's root and under `stages/`. A fitted
    run leaves several copies there, so the run's manifest names the one it simulated -- `FINAL_ITP`, which every
    CG stage records in its environment. A run that recorded no name and holds exactly one `.itp` is answered by
    that one; every other case resolves to `None` rather than to a ranked guess, because the topology is what
    decides which beads exist and a picture of a model nobody ran is not worth drawing.
    """
    from ...analysis.runs import layout

    name = None
    for stage in (manifest or {}).get('stages') or []:
        name = (stage.get('environment') or {}).get('FINAL_ITP')
        if name:
            break
    try:
        return layout.cg_topology(run_dir, name)
    except ValueError:
        return None


@blueprint.get('/api/jobs/<jid>/structure')
def run_structure_api(jid):
    """A run's own structure file, with the model's own bonds written onto it.

    Measured on this box: a `.gro` carries no bond records, and this vendored viewer's GRO parser guesses from
    distances regardless of `inferBonds` -- eight mapped beads came back with four guessed bonds whichever flag was
    passed -- so the client clears the store and a coarse-grained run's mapped model, the picture that run exists to
    publish, comes out as beads with no connectivity at all. The run's own moleculetype under `stages/3_initial_CG/`
    states which beads are bonded, and this route writes those `[ bonds ]` and `[ constraints ]` as CONECT records
    over the file's own coordinates, through the same writer the complex system view uses
    (`execution.adapters.pdc_view.structure_pdb`). The client's CONECT branch then draws exactly those bonds and
    leaves its distance guess off, which is the one rule this repository already had.

    The topology is located by the run's own layout rule (`analysis.runs.layout.cg_topology`, named by the
    manifest's `FINAL_ITP` when the run recorded one), so a picture and an analysis read the same file. A topology
    that is absent or unreadable is a state the answer reports -- coordinates, no CONECT, and a REMARK saying so --
    never a guess, because the topology is what decides which beads exist.

    A `.pdb` is refused with a reason: it already carries, or declines, its own records and the artifact route
    serves it, so this route would be a second writer for the same bytes.
    """
    c = coordinator()
    job = c.lookup(jid)
    run_dir = c.run_path(job)
    path = structure_target(run_dir, request.args.get('path', '').strip())
    topology = run_topology(run_dir, c.manifest_data(job))
    moleculetype = None
    if topology is not None:
        try:
            moleculetype = pdc_view.read_moleculetype(topology)
        except (OSError, ValueError):
            moleculetype = None
    try:
        # The same fragments the frames carry: a reader who fits a series on one ring sees the same letters on the
        # single structure it came from, because both are written from the run's own mapping.
        text = pdc_view.structure_pdb(path, topology=moleculetype, subunits=pdc_view.read_subunits(run_dir),
                                      title=f'{path.name} (run {jid})')
    except (OSError, ValueError) as error:
        abort(400, f'{path.name} could not be read for the viewer: {error}')
    return Response(text, mimetype='text/plain')


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
