"""The fit job: a mapping and a linked AA reference become a revision, with no MD anywhere.

D2 of `docs/design/2026-10-16-parameterization-and-new-run.md`: producing a parameterization is a
job of the CG Bond Interactions panel and not a run. Its inputs are `(mapping, AA reference, engine,
options)`; its outputs are the terms, the diagnostics, the fit's provenance and the checks; it runs
with a status and can be cancelled; and it is listed in the panel rather than in Runs, because it
makes no MD and a run is a thing that does.

It lives under `models/bonded/` because its only durable output *is* a revision of a mapping
(`parameterization.save`). The execution layer is reached lazily, inside the functions that need a
tool, for the same reason `analysis.runs.bartender_fit` reaches it that way: models -> execution is
not a direction this tree takes at import time.

What a job works in is a *pair*, not a job: `work/<mapping content hash>-<AA run id>/` holds the
mapped frames, the engine's output and the checks, and a second fit of the same mapping against the
same reference reuses the frames. That is what "building the mapped trajectory if the AA reference
has none" means -- minutes of CPU, no MD, and paid once per pair rather than once per fit.

Three engines, each saying which ensemble it saw (D3):

  fast-forward        `ff_inter` on the mapped AA trajectory, through the same stage script a run
                      runs, with the `-constraints` threshold recorded because it decides whether a
                      fitted pair becomes a constraint or a spring.
  bartender           `-refit -owntraj` through `analysis.runs.bartender_fit`, never its own GFN
                      sampling; its bare term sections are merged back into a topology by
                      `bartender_fit.model_topology`.

Both read an ensemble, so both need a reference: the reference-free engine that read the mapping alone was removed
(2026-10-20) with its panel button, since a revision nobody fitted is not what this panel is for. `bonded.generation`
stays -- `detergent_cg` and `POST /api/bonded-states/automatic` build bonded states with it.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from ... import files, paths
from .. import mappings
from ..molecules import draft as draft_model
from . import parameterization as parameterizations

#: The steps a job passes through, in order, as the panel's progress box names them.
STEPS = ('mapped frames', 'fit', 'checks', 'save')

STATUSES = ('queued', 'running', 'completed', 'failed', 'cancelled')

#: A fit reads a trajectory and histograms it; it does not simulate. Minutes, not hours, and a job
#: that never returns is worse than one that fails. `ff_inter` on a ten-nanosecond reference is the
#: slow one, and BARTENDER is slower still when a linkage goes in as an improper.
DEFAULT_TIMEOUT = 3600

_JOB = re.compile(r'[a-f0-9]{16}')

#: The live jobs of *this process*: the cancellation flag and the process to end. A running job also
#: reads its own record's status, so a cancellation from another process still stops it at the next
#: poll; this is only the part that can be reached immediately.
_ACTIVE: dict[str, dict] = {}
_LOCK = threading.RLock()


class Cancelled(RuntimeError):
    """Raised inside a job whose cancellation was asked for: it stops, and its record says so."""


def jobs_root() -> Path:
    return parameterizations.storage_root() / 'jobs'


def _validate(job_id) -> str:
    if not isinstance(job_id, str) or not _JOB.fullmatch(job_id):
        raise ValueError('Invalid fit job ID')
    return job_id


def _job_path(job_id) -> Path:
    return jobs_root() / f'{_validate(job_id)}.json'


def log_path(job_id) -> Path:
    return jobs_root() / f'{_validate(job_id)}.log'


def job(job_id) -> dict:
    path = _job_path(job_id)
    if not path.is_file():
        raise KeyError(f'Unknown fit job: {job_id}')
    return json.loads(path.read_text())


def _update(job_id, **fields) -> dict:
    """Read, change and write a job's record under one lock.

    The status is read back before every step and every poll, so a cancellation that lands while a
    tool runs is seen rather than overwritten by the next write of a record that predates it.
    """
    with _LOCK:
        record = job(job_id)
        record.update(fields)
        files.atomic_json(_job_path(job_id), record)
        return record


def jobs(mapping=None, *, content_hash=None, mapping_hash=None, job_id=None, limit=None) -> list:
    """Every fit job known, newest first, optionally only one mapping's.

    The panel's own list. It is deliberately not the run store: nothing here will ever be simulated,
    so a line in Runs would be a run-shaped claim about minutes of CPU that produced a document.

    A caller may hold hashes instead of a mapping, and the two hashes answer the two questions the
    revision store's `matches` asks: `content_hash` is compatibility (a rename keeps its jobs),
    `mapping_hash` is provenance (the candidate a job was queued for -- all a caller can know before
    the job has saved a record). A job belongs to the model when either hash it carries is one of
    those asked about, so this is the one place that decides "which jobs are this mapping's". The
    newest are kept first and `limit` is applied *after* the filter, so a limit can never hide a
    model's own job behind another model's newer one.

    `job_id` answers the panel's other question -- "what is *my* job doing" -- by the one key it already
    holds. A poll that asks by the mapping's hash is right only while the job's own hash agrees with it,
    and a disagreement (an identity that moved, two copies of one mapping) left the box showing the
    record it queued forever, with no answer saying why.
    """
    root = jobs_root()
    records = []
    if root.is_dir():
        for path in sorted(root.glob('*.json')):
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict) or not isinstance(record.get('id'), str):
                continue
            records.append(record)
    if mapping is not None:
        # A mapping speaks for compatibility alone: `changed` bead assignments are their own model,
        # while a rename is the same one (D5's own reading, and the reason a revision is keyed by it).
        content_hash = parameterizations.content_identity(mapping)
    if job_id:
        records = [record for record in records if record.get('id') == job_id]
    if content_hash or mapping_hash:
        records = [record for record in records
                   if (content_hash and record.get('mapping_content_hash') == content_hash)
                   or (mapping_hash and record.get('mapping_hash') == mapping_hash)]
    records.sort(key=lambda record: record.get('created_at') or '', reverse=True)
    return records[:limit] if limit else records


def latest(mapping):
    found = jobs(mapping, limit=1)
    return found[0] if found else None


def work_dir(mapping, reference_run_id=None) -> Path:
    """The working directory of one (mapping, AA reference) pair.

    The reference is part of the key because the frames are its own: the same mapping against a
    different AA reference is a different fit and must not read the other one's trajectory.
    """
    if reference_run_id is not None and not re.fullmatch(r'[a-f0-9]{12}', reference_run_id):
        raise ValueError('AA reference run ID must be twelve hexadecimal characters')
    # The same fallback the record store makes: a pair staged before numbers were normalised is reused rather than
    # rebuilt, which is the difference between a re-fit of minutes and one of a mapped trajectory.
    name = f'{parameterizations.content_identity(mapping)}-{reference_run_id or "no-reference"}'
    root = parameterizations.work_root()
    if not (root / name).is_dir():
        legacy = root / f'{mappings.legacy_content_identity(mapping)}-{reference_run_id or "no-reference"}'
        if legacy.is_dir():
            return legacy
    return root / name


# --- resolving the reference, starting, cancelling and reading a job ---------------------------------


def resolve_reference(aa_reference, *, runs_root=None) -> dict:
    """A named AA-only run, resolved and hashed: what a fit may measure against.

    D4: the reference is linked, not implied, and a model whose reference is gone must say so rather
    than silently fitting against nothing -- so an unresolvable one raises here rather than as a job
    that fails four minutes later.
    """
    from ...analysis.runs import references as aa_references

    run_id = aa_reference if isinstance(aa_reference, str) else (aa_reference or {}).get('run_id')
    root = Path(runs_root) if runs_root is not None else paths.current().runs
    directory, data = aa_references.resolve(root, run_id)
    reference_file = Path(directory) / 'reference.json'
    settings = data.get('settings') or {}
    digest = files.sha256(reference_file)
    return {
        'run_id': run_id,
        'directory': str(directory),
        'reference_sha256': digest,
        'record': {
            'reference_sha256': digest,
            'frames': (data.get('frames') or {}).get('count'),
            'aa_reference': {
                'run_id': run_id,
                'reference_sha256': digest,
                'molecule_identity': data.get('molecule_identity'),
                'temperature_k': settings.get('temperature_k'),
                'production_ns': (settings.get('aa_production_ps') or 0) / 1000.0 or None,
            },
        },
    }


def start(mapping, *, engine, aa_reference=None, options=None, reference=None, molecule_root=None,
          runs_root=None, timeout=None, background=True, runner=None) -> dict:
    """Queue a fit and return its record.

    `reference` is a reference the caller has already resolved (`resolve_reference`, or the
    coordinator's own resolution) and `aa_reference` names one for this function to resolve itself;
    either way what is recorded is the run id and the hash of its `reference.json`, because a fit is
    only readable beside the ensemble it came from.

    `background=False` runs the job inside this call, which is what a test and a CLI want. The
    default hands it to a thread the panel polls and can cancel.

    `runner` is the command runner a job executes its tools through. It is a parameter rather than a
    patched module global so that a test stands in for an engine without touching anything else.
    """
    if engine not in parameterizations.ENGINES:
        raise ValueError(f'Unknown fitting engine: {engine!r}')
    loaded = draft_model.load(mapping, molecule_root=molecule_root)
    resolved = reference if reference is not None else (
        resolve_reference(aa_reference, runs_root=runs_root) if aa_reference else None)
    if resolved is None:
        raise ValueError('This engine fits to an ensemble; link an AA reference')
    run_id = (resolved or {}).get('run_id')
    job_id = uuid.uuid4().hex[:16]
    record = {
        'id': job_id,
        'status': 'queued',
        'mapping_name': mapping.get('name') or mapping.get('file') or 'mapping',
        'molecule_id': mapping.get('molecule_id'),
        **parameterizations.identities(mapping),
        'engine': engine,
        'options': parameterizations.normalise_options(mapping, options),
        'aa_reference': (resolved or {}).get('record', {}).get('aa_reference'),
        'reference_run_id': run_id,
        'reference_sha256': (resolved or {}).get('reference_sha256'),
        'molecule_root': str(molecule_root) if molecule_root is not None else None,
        'timeout': timeout or DEFAULT_TIMEOUT,
        'steps': list(STEPS),
        'step': None,
        'completed_steps': [],
        'progress': {'done': 0, 'total': len(STEPS), 'detail': 'queued'},
        'work': str(work_dir(mapping, run_id)),
        'log': str(log_path(job_id)),
        'created_at': files.now_iso(),
        'started_at': None,
        'ended_at': None,
        'error': None,
        'revision': None,
        'cancelled_at': None,
        'scientifically_validated': False,
    }
    files.atomic_json(_job_path(job_id), record)
    log_path(job_id).parent.mkdir(parents=True, exist_ok=True)
    log_path(job_id).write_text('')
    if not background:
        return execute(job_id, mapping=mapping, loaded=loaded, reference=resolved, runner=runner)
    with _LOCK:
        _ACTIVE[job_id] = {'cancelled': threading.Event(), 'process': None}
    # Where the workspace is, captured here and re-selected in the thread. `paths.current()` reads a
    # Flask app context first and a context variable second, and a context variable does not cross a
    # thread boundary: without this the job would resolve its records and its work directory against
    # the *default* workspace while the panel it was queued from reads its own.
    selected = paths.current()
    threading.Thread(target=_guarded, args=(job_id, loaded, resolved, mapping, runner, selected),
                     name=f'bonded-fit-{job_id}', daemon=True).start()
    return job(job_id)


def cancel(job_id) -> dict:
    """Ask a job to stop, and end the process it is in if it is in one.

    Cancellation is asked for rather than imposed: the job notices between steps, and a tool that is
    mid-call is terminated rather than left to finish a fit nobody will read.
    """
    record = job(job_id)
    if record['status'] in ('completed', 'failed', 'cancelled'):
        return record
    with _LOCK:
        active = _ACTIVE.get(_validate(job_id))
        if active:
            active['cancelled'].set()
            process = active.get('process')
            if process is not None and process.poll() is None:
                process.terminate()
    return _update(job_id, status='cancelled', cancelled_at=files.now_iso(), ended_at=files.now_iso(),
                   progress={**record.get('progress', {}), 'detail': 'cancelled'})


# --- reading and writing a job's own progress --------------------------------------------------------


def _tail(path, limit=2000) -> str:
    try:
        return Path(path).read_text()[-limit:]
    except OSError:
        return ''


def _is_cancelled(job_id) -> bool:
    with _LOCK:
        active = _ACTIVE.get(_validate(job_id))
        if active and active['cancelled'].is_set():
            return True
    try:
        return job(job_id).get('status') == 'cancelled'
    except (OSError, ValueError, KeyError):
        return False


def _check_cancel(job_id) -> None:
    if _is_cancelled(job_id):
        raise Cancelled('cancelled')


def _step(job_id, step, detail='') -> dict:
    """Enter a step: the record names the work in progress, so the panel's box can show it."""
    _check_cancel(job_id)
    record = job(job_id)
    done = record.get('completed_steps') or []
    return _update(job_id, status='running', started_at=record.get('started_at') or files.now_iso(),
                   step=step, progress={'done': len(done), 'total': len(STEPS), 'detail': detail or step},
                   log_tail=_tail(record.get('log')))


def _finished(job_id, step, detail='') -> dict:
    record = job(job_id)
    done = list(record.get('completed_steps') or [])
    if step not in done:
        done.append(step)
    return _update(job_id, completed_steps=done, step=None,
                   progress={'done': len(done), 'total': len(STEPS), 'detail': detail or step})


def _fail(job_id, message) -> dict:
    record = job(job_id)
    if record.get('status') == 'cancelled':
        return record
    return _update(job_id, status='failed', error=message, ended_at=files.now_iso(),
                   progress={**record.get('progress', {}), 'detail': 'failed'},
                   log_tail=_tail(record.get('log'), 4000))


def _guarded(job_id, loaded, reference, mapping, runner, selected):
    # The whole body, including the failure it writes, runs under the workspace the job was queued
    # from: recording a failure in the wrong workspace would leave the panel reading a job that never
    # finished and an orphan record where nobody looks.
    with paths.use(selected):
        try:
            execute(job_id, mapping=mapping, loaded=loaded, reference=reference, runner=runner)
        except Cancelled:
            pass
        except Exception as exc:                              # noqa: BLE001 - the job's own failure
            _fail(job_id, f'{type(exc).__name__}: {exc}')
        finally:
            with _LOCK:
                _ACTIVE.pop(job_id, None)


# --- running one command, cancellably ---------------------------------------------------------------


def run_command(command, cwd, *, env=None, timeout=None, job_id=None, log=None):
    """Run one tool with a handle on it, so a cancellation can reach it.

    `subprocess.run`, which `bartender_fit._run` uses, cannot be interrupted: the only handle on the
    child is the call that is already blocked. A job the panel can cancel needs the handle, so this
    uses `Popen` and polls -- and sets `stdin=DEVNULL` for the reason that module documents, which is
    that an unattended subprocess has to get past a prompt with nothing to answer it.
    """
    timeout = timeout or DEFAULT_TIMEOUT
    target = Path(log).open('a') if log else None
    try:
        process = subprocess.Popen(command, cwd=cwd, env=_environment(env), stdin=subprocess.DEVNULL,
                                   stdout=target or subprocess.DEVNULL, stderr=subprocess.STDOUT, text=True)
    finally:
        if target is not None:
            target.close()
    if job_id:
        with _LOCK:
            active = _ACTIVE.get(job_id)
            if active is not None:
                active['process'] = process
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if job_id and _is_cancelled(job_id):
                _end(process)
                raise Cancelled('cancelled')
            if time.monotonic() > deadline:
                _end(process)
                raise TimeoutError(f'{command[0]} did not return within {timeout:g} s')
            time.sleep(0.2)
    finally:
        if job_id:
            with _LOCK:
                active = _ACTIVE.get(job_id)
                if active is not None:
                    active['process'] = None
    if process.returncode != 0:
        raise RuntimeError(f'{" ".join(str(part) for part in command)} exited {process.returncode}')
    return process


def _end(process):
    process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=30)


def _environment(extra=None):
    from ...execution.environment import environment
    values = dict(environment())
    values.update({key: str(value) for key, value in (extra or {}).items() if value is not None})
    return values


# --- what a job does, in the order it does it --------------------------------------------------------


def execute(job_id, *, mapping, loaded=None, reference=None, runner=None, timeout=None) -> dict:
    """Run one queued job to a stored revision, synchronously.

    The body is reachable on its own -- from a CLI, from a test, from this module's own thread --
    because the queueing is the only part a thread is needed for. `runner` is the seam a test uses to
    stand in for a tool: the job's own guards decide whether an engine produced what it promised, so
    a runner that writes the artefact the guard looks for is a whole engine as far as this is
    concerned.
    """
    record = job(job_id)
    _check_cancel(job_id)
    runner = runner or run_command
    timeout = timeout or record.get('timeout') or DEFAULT_TIMEOUT
    loaded = loaded if loaded is not None else draft_model.load(mapping, molecule_root=record.get('molecule_root'))
    reference = reference if reference is not None else _stored_reference(record)
    engine, options = record['engine'], record['options']
    log = record.get('log')

    def call(command, cwd, env=None, limit=None):
        return runner(command, cwd, env=env, timeout=limit or timeout, job_id=job_id, log=log)

    # For its effect, not its return: `_frames` writes the mapped frames beside the revision, and the record of what
    # it wrote is already in `record`.
    _frames(job_id, loaded, reference, engine, record, call)
    _check_cancel(job_id)

    _step(job_id, 'fit', f'{engine} reads the mapped frames')
    produced = _fit(engine, loaded, reference, record, options, call, timeout)
    _finished(job_id, 'fit', f'{engine} wrote {len(produced["terms"])} terms')

    _step(job_id, 'checks', 'dihedral-fit and bonded-cross-check')
    checks = _checks(engine, record, options)
    _finished(job_id, 'checks', ', '.join(f'{name}: {_word(report)}' for name, report in checks.items()))

    _check_cancel(job_id)
    _step(job_id, 'save', 'storing the revision')
    extra = produced['extra']
    payload = {
        'engine': engine,
        'options': options,
        'ensemble': produced['ensemble'],
        'aa_reference': (reference or {}).get('record', {}).get('aa_reference'),
        'temperature_source': extra.get('temperature_source'),
        'engine_command': extra.get('engine_command'),
        'engine_terms': produced['terms'],
        'engine_default_source': extra.get('engine_default_source'),
        'refinement': produced.get('refinement'),
        'diagnostics': extra.get('diagnostics'),
        'topology': produced['topology'],
        'terms': parameterizations.term_counts({'topology': produced['topology']}),
        'checks': checks,
        'notes': extra.get('notes') or [],
    }
    revision = parameterizations.save(mapping, payload, expected_revision=record.get('expected_revision'),
                                      work=record.get('work'))
    _finished(job_id, 'save', f'revision {revision["revision"]}')
    return _update(job_id, status='completed', ended_at=files.now_iso(), error=None,
                   revision=revision['revision'],
                   revision_sha256=parameterizations.revision_sha256(revision),
                   progress={'done': len(STEPS), 'total': len(STEPS), 'detail': f'revision {revision["revision"]}'},
                   log_tail=_tail(log))


def _stored_reference(record):
    """The reference a job started in another process recorded, as far as it can be re-resolved.

    A record carries the run id and the reference's hash and not the directory, because a directory
    is a fact about this machine rather than about the fit. Re-entering one therefore resolves it
    again, which also re-checks the hashes: a reference that changed under a queued fit must not be
    silently fitted against.
    """
    run_id = record.get('reference_run_id')
    if not run_id:
        return None
    return resolve_reference(run_id)


# --- the engines ----------------------------------------------------------------------------------


def _frames(job_id, loaded, reference, engine, record, call) -> bool:
    """Stage the pair's working directory, and build the mapped trajectory if it has none.

    The frame builder is `sugar_mapping.py`, the one mapper, run with the reference as its
    `AA_REFERENCE_DIR`: the same repository module stage 2 of a run runs, so a panel fit and a run map
    their frames identically. It refuses to overwrite an earlier mapping, which is what makes "if it has
    none" a fact about the directory rather than a flag somebody has to keep.
    """
    from ...execution.adapters import cg

    # The mapper prints nothing per frame, so this is the whole progress report for the longest step in a fit;
    # the panel states it rather than leaving a reader to conclude the job has stalled.
    _step(job_id, 'mapped frames', 'staging the pair; the mapper reports no per-frame progress')
    work = Path(record['work'])
    mapping_dir, stage_dir = work / '2_mapping', work / '3_initial_CG'
    mapping_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    names = _names_for(loaded, record.get('molecule_root'))
    cg.stage_mapping(mapping_dir, loaded, names=names)
    cg.stage_parameterization(stage_dir, loaded, names=names, molecule_root=record.get('molecule_root'))
    directory = (reference or {}).get('directory')
    if directory is None:
        raise ValueError('This engine fits to an ensemble; no AA reference directory was resolved')
    built = False
    if not (mapping_dir / 'mapped.xtc').is_file():
        call([sys.executable, '-m', 'dashboard.execution.scripts.sugar_mapping'], mapping_dir,
             env={'AA_REFERENCE_DIR': directory, 'MOLECULE_TYPE': names.residue_name,
                  'PYTHONPATH': str(paths.current().project_root)})
        built = True
    missing = [name for name in ('mapped.gro', 'mapped.xtc') if not (mapping_dir / name).is_file()]
    if missing:
        raise RuntimeError('the mapper did not write ' + ', '.join(missing))
    # The engines also read the reference's own coordinates: BARTENDER's `-refit -owntraj` is handed
    # this reference's trajectory, mapped through the mapping's own `.ndx`, and never its own sample.
    reference_dir = work / '1_AA-reference' / 'prod'
    reference_dir.mkdir(parents=True, exist_ok=True)
    for name in ('lig.gro', 'lig.xtc'):
        source = Path(directory) / name
        if source.is_file() and not (reference_dir / name).is_file():
            shutil.copy2(source, reference_dir / name)
    _finished(job_id, 'mapped frames',
              'built from the AA reference' if built else 'reusing the mapped frames already built')
    return built


def _fit(engine, loaded, reference, record, options, call, timeout) -> dict:
    names = _names_for(loaded, record.get('molecule_root'))
    if engine == 'fast-forward':
        return _fast_forward(loaded, names, record, options, call, timeout)
    if engine == 'bartender':
        return _bartender(loaded, names, record, call, timeout)
    raise ValueError(f'Unknown fitting engine: {engine!r}')


def _fast_forward(loaded, names, record, options, call, timeout) -> dict:
    """`ff_inter` on the mapped AA trajectory, through the same stage script a run runs.

    The script is the repository's `dashboard/execution/scripts/fit_topology.sh`, run in this fit's
    stage directory with the fit's temperature in `RUN_SETTING_TEMPERATURE_K` exactly as a run's
    executor hands a stage its settings -- one definition of the invocation, so a panel fit and a
    run's stage 3 cannot drift apart. `refine_bonded.py` then replaces the declared torsions with the
    circular model when the mapping asks for one, and writes `bonded_fit.json` either way.
    """
    from ...execution.adapters import cg

    work = Path(record['work'])
    stage = work / '3_initial_CG'
    command = ['bash', '-e', '-o', 'pipefail', str(cg.SCRIPTS / 'fit_topology.sh')]
    call(command, stage, env={'MOLECULE_TYPE': names.residue_name, 'INITIAL_ITP': names.initial_itp,
                              'FINAL_ITP': names.final_itp,
                              'RUN_SETTING_TEMPERATURE_K': str(options['temperature_k']),
                              'PYTHON': sys.executable,
                              'PYTHONPATH': str(paths.current().project_root)}, limit=timeout)
    final = stage / names.final_itp
    if not final.is_file():
        raise RuntimeError(f'ff_inter did not write {names.final_itp}; there is no fit to store')
    topology = final.read_text()
    report = _read_json(stage / 'bonded_fit.json')
    return {
        'topology': topology,
        'terms': _term_rows(topology),
        'ensemble': {'frames': _frames_built(work), 'trajectory': '2_mapping/mapped.xtc',
                     'source': 'the mapped AA frames of the linked reference: heavy-atom centres mapped '
                               'by `sugar_mapping.py`, which is stage 2 of a run'},
        'refinement': report,
        'extra': {
            'engine_command': command,
            'engine_default_source': 'ff_inter',
            'temperature_source': 'the fit temperature this job was asked for',
            'diagnostics': {'refinement': report, 'topology': names.final_itp},
            'notes': [f'ff_inter was given `-constraints {options["constraints_threshold"]:g}`: above that '
                      'force constant a fitted pair is written as a constraint, and below it as a spring.'],
        },
    }


def _bartender(loaded, names, record, call, timeout) -> dict:
    """BARTENDER's `-refit -owntraj`, and its bare term sections merged back into a model.

    `bartender_fit.run` is the repository's own invocation: it renumbers the topology to its physical
    beads (a virtual site has no atoms to fit), writes the reference's trajectory and asks for
    `-refit -owntraj`, so BARTENDER fits to *our* AA reference through *our* mapping's `.ndx` and
    never to its own GFN sampling. What it writes is `gmx_out.itp` -- sections and no molecule -- and
    `bartender_fit.model_topology` is what turns that back into the model's topology.
    """
    from ...analysis.runs import bartender_fit

    work = Path(record['work'])
    stage = work / '3_initial_CG'
    _ring_constraints(work, names, call)
    fitted = stage / bartender_fit.FITTED
    if not fitted.is_file():
        bartender_fit.run(work, {'cpus': 8, 'timeout': timeout})
    if not fitted.is_file():
        raise RuntimeError('BARTENDER did not write gmx_out.itp; there is no fit to store')
    terms = bartender_fit.fitted_terms(fitted.read_text())
    topology = bartender_fit.topology_from_fit((stage / names.initial_itp).read_text(), terms, loaded['beads'])
    (stage / names.final_itp).write_text(topology)
    # The fit's interaction topology, under the name the run's own readers look for. For Fast-Forward
    # that is `refine_bonded.py`'s preserved `*_ff_inter.itp`; the name says "the fit's terms", not
    # "which tool fitted them", and it is what the two checks and the analysis layer's declared
    # sources are written against.
    (stage / f'{Path(names.final_itp).stem}_ff_inter.itp').write_text(topology)
    return {
        'topology': topology,
        'terms': _term_rows(topology),
        'ensemble': {'frames': _frames_built(work), 'trajectory': '1_AA-reference/prod/lig.xtc',
                     'source': "the linked AA reference's own atomistic trajectory, read through this "
                               "mapping's `.ndx` by BARTENDER's `-refit -owntraj`; never BARTENDER's own "
                               'GFN sampling'},
        'extra': {
            'engine_command': bartender_fit.bartender_command('bartender', 8),
            'engine_default_source': 'bartender',
            'temperature_source': 'BARTENDER reads the temperature from the trajectory it is given',
            'diagnostics': {'sections': {section: len(rows) for section, rows in terms.items()}},
            'notes': ['BARTENDER is driven with `-refit -owntraj` against this mapping\'s own mapped '
                      'reference; it is never asked to generate samples of its own.'],
        },
    }


def _ring_constraints(work, names, call) -> bool:
    """Apply the mapping's AA-derived ring lengths before an engine reads the seeded topology.

    The same pass a run's stage 3 runs (`prepare_ring_constraints.py`), and it returns without
    touching anything for a mapping with no rings: `ring_targets.json` is the mapper's own output and
    only a ring mapping has one.
    """
    if not (Path(work) / '2_mapping' / 'ring_targets.json').is_file():
        return False
    call([sys.executable, '-m', 'dashboard.execution.scripts.prepare_ring_constraints'],
         Path(work) / '3_initial_CG',
         env={'INITIAL_ITP': names.initial_itp, 'MOLECULE_TYPE': names.residue_name,
              'PYTHONPATH': str(paths.current().project_root)})
    return True


def _checks(engine, record, options) -> dict:
    """The two re-derivations that need no CG trajectory (D6), run as part of producing the revision.

    They are checks and not gates: an analysis that cannot run is recorded with its own reason
    instead of failing the fit, which is the rule every other check in this tree follows -- a check
    must not be able to fail the thing it questions.
    """
    from ...analysis.runs import bonded_estimate, dihedral_fit

    work = Path(record['work'])
    if not (work / '2_mapping' / 'mapped.xtc').is_file():
        reason = 'the mapped trajectory is absent, so neither check has frames to read'
        return {name: {'error': reason} for name in parameterizations.CHECKS}
    payload = {'temperature': options['temperature_k'],
               'constraint_threshold': options['constraints_threshold'],
               'temperature_source': f"this fit's own temperature, {options['temperature_k']:g} K"}
    results = {}
    for name, function in (('dihedral-fit', dihedral_fit.publish),
                           ('bonded-cross-check', bonded_estimate.cross_check)):
        try:
            results[name] = function(work, payload)
        except (ValueError, OSError, KeyError) as exc:
            results[name] = {'error': str(exc)}
    return results


# --- small helpers ----------------------------------------------------------------------------------


def _word(report):
    if report is None:
        return 'not run'
    if isinstance(report, dict) and 'error' in report:
        return 'unavailable'
    return 'published'


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _frames_built(work):
    """How many frames the mapped trajectory has, from the mapper's own record of it."""
    record = _read_json(Path(work) / '2_mapping' / 'mapping_validation.json') or {}
    frames = record.get('frames')
    return int(frames) if isinstance(frames, int) else None


def _term_rows(topology):
    """A stored topology's terms, as the compact rows a revision keeps beside it."""
    from . import parse_interactions
    return [{'kind': row['kind'], 'beads': row['beads'], 'function': row['function'],
             'parameters': row['parameters']}
            for row in parse_interactions(topology)]


def _names_for(loaded, molecule_root=None):
    """The naming context a model's molecule has: its registry selection, or this project's default.

    A run is prepared for a molecule the caller has already selected, so its `prepare` is handed a
    snapshot. A fit job is started for a *mapping*, so the molecule comes from the mapping's own
    `molecule_id` -- the model names its molecule, which is the same field the mapping workspace
    resolves its structure from. A mapping that names none is the packaged DDM model.
    """
    from ...execution.adapters.cg_names import CGNames

    molecule_id = loaded.get('molecule_id')
    if isinstance(molecule_id, str) and molecule_id:
        from ..molecules import aa as aa_molecules
        root = Path(molecule_root) if molecule_root is not None else paths.current().project_root / 'molecules'
        try:
            return CGNames.for_snapshot(aa_molecules.selection(root, molecule_id))
        except (ValueError, OSError, KeyError):
            # A molecule whose sources have moved is not a reason to fit against a name invented here;
            # the caller's own load has already refused anything else about this mapping.
            pass
    return CGNames.ddm_defaults()
