"""Shared stage execution, provenance, and resumable workflow state."""
import datetime
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import weakref
from pathlib import Path, PurePosixPath

from .. import files
from . import protocol, run_inputs, run_scripts
from .adapters.cg_names import CGNames
from .coordination.manifest import stage_log_path
from .environment import ROOT, environment, recorded_environment
from .stages import Stage


def stage_command(name, script):
    command = ['bash', '-e', '-o', 'pipefail', str(script)]
    if name == 'AA reference' and script.name == 'run_1mol_AA_system.sh':
        command += ['molecule.pdb', 'spc216.gro', 'SOL', '3']
    return command


#: Notified with a run's directory once all of its stages have been attempted. The analysis layer registers its own
#: handler here rather than this module importing it: an analysis's frames are published by the analysis layer, whose
#: worker already imports this module, so reaching for it from here is the cycle the two are arranged to avoid.
#: Registration is weak, so an application that has gone stops being notified, and a handler for a run it does not
#: own answers with nothing.
_run_completed = []


def on_run_completed(listener):
    """Register `listener(run_dir)`, called once a run's stages are all attempted. Returns it, so it can decorate."""
    try:
        reference = weakref.WeakMethod(listener)
    except TypeError:  # a plain function rather than a bound method: kept by reference
        reference = weakref.ref(listener)
    _run_completed.append(reference)
    return listener


def run_completed(run_dir):
    """Tell every registered listener that a run's stages are all attempted, and forget the ones that are gone."""
    for reference in list(_run_completed):
        listener = reference()
        if listener is None:
            _run_completed.remove(reference)
        else:
            listener(Path(run_dir))


def missing_files(directory, patterns):
    """The declared inputs a stage directory does not hold.

    A declaration ending in `/` names a directory the stage carries whole (the pdc adapter declares the protein's
    topology tree that way, because martinize2 decides how many `.itp`s there are), so the directory's own presence
    is what satisfies it -- `is_file` would call every such entry missing and refuse the stage.
    """
    def given(path, pattern):
        if path.is_file() and path.stat().st_size:
            return True
        return str(pattern).endswith('/') and path.is_dir()

    return [pattern for pattern in patterns
            if not any(given(p, pattern) for p in directory.glob(pattern))]


def declared_output_hashes(directory, patterns, recorded=None):
    """Hash only the declared outputs, keeping launchers out of resume checks.

    ``recorded`` supports manifests written before output-only checksums were
    introduced: their full-directory hash map is filtered using the current
    stage contract before verification or copying.
    """
    patterns = tuple(patterns)
    result = {}
    if recorded is not None:
        # Keep missing declared outputs in the expected map so ``files.verify``
        # rejects them instead of silently verifying an empty filtered set.
        for relative, digest in recorded.items():
            if any(PurePosixPath(relative).match(pattern) or fnmatch.fnmatch(relative, pattern)
                   for pattern in patterns):
                result[relative] = digest
        return result
    directory = Path(directory)
    for pattern in patterns:
        for path in directory.glob(pattern):
            if path.is_file() and not path.is_symlink():
                relative = path.relative_to(directory).as_posix()
                result[relative] = files.sha256(path)
    return result


def _declared_paths(directory, pattern):
    """The files a declared input names: the match itself, or -- for an entry ending in `/` -- every file inside it.

    A stage that carries a directory whole is given those files, so they are what its manifest has to record as its
    provenance. Hashing the entry alone records nothing, because a directory is not a file.
    """
    for path in directory.glob(pattern):
        if str(pattern).endswith('/') and path.is_dir():
            yield from sorted(child for child in path.rglob('*') if child.is_file())
            continue
        yield path


def validate_stage_inputs(name, directory, required):
    """Refuse a stage whose declared inputs are not on disk.

    `required` is the run type's own contract (`stage_definitions(metadata)[1]`), passed in rather than defaulted: it
    used to fall back to the CG adapter's table for every run type, which meant an AA-only stage was checked against a
    contract that was not its own. The only caller supplies the right one, so the fallback was dead code that would
    have been wrong if it had ever run.
    """
    missing = missing_files(directory, required.get(name, ()))
    if name == 'AA reference' and (directory / 'system_EMPTY.top').is_file():
        includes = re.findall(r'^\s*#include\s+"([^"]+)"', (directory / 'system_EMPTY.top').read_text(), re.M)
        missing += missing_files(directory, includes)
    if missing:
        raise FileNotFoundError(f'{name}: missing required inputs: {", ".join(missing)}. Stage molecule-specific inputs before execution.')


def _run_type(metadata) -> str:
    """The adapter that owns a run; absent means the historical combined AA-to-CG job."""
    return protocol.run_type_of(metadata)


def stage_definitions(metadata):
    """Return the executable contract selected by immutable run metadata."""
    return protocol.adapter_for(_run_type(metadata)).stage_contract(metadata)


def plan_for(metadata) -> tuple[Stage, ...]:
    """Return the resolved immutable stage declarations for a run."""
    return protocol.adapter_for(_run_type(metadata)).stages(metadata)


def stage_root(run_dir):
    """Where a run keeps its stage directories: `stages/`, and only that.

    The legacy fallback (`stages/` when present, else the run root) was the one rule that let pdc and osmotic write
    stage directories at the run root. Every run now has `stages/`, and a run without it is refused rather than
    guessed at -- a reader that silently takes the run root for an execution root is how the two layouts stayed
    indistinguishable.
    """
    run_dir = Path(run_dir)
    stages = run_dir / 'stages'
    if run_dir.is_symlink() or stages.is_symlink():
        raise ValueError('Execution directories must not be symbolic links')
    if not stages.is_dir():
        raise ValueError(f'{run_dir} has no stages/ directory')
    return stages


def resumable_stages(run_dir, metadata=None):
    if metadata is None:
        try:
            metadata = json.loads((run_dir / 'manifest.json').read_text())
        except (ValueError, OSError): return []
    data = metadata
    if not isinstance(data,dict): return []
    choices = []
    for name, _ in stage_definitions(data)[0]:
        entry = next((e for e in reversed(data.get('stages', [])) if isinstance(e,dict) and e.get('name') == name), {})
        # A skipped stage is a completed part of the prefix but has no directory to resume into, so it is never offered
        # as a start -- and it does not end the prefix: stopping there would make every later stage unreachable. Every
        # other stage is offered before the prefix is tested, which is what keeps a run whose first stage never ran
        # resumable from the start.
        if entry.get('status') != 'skipped': choices.append(name)
        if entry.get('status') not in ('completed', 'reused', 'skipped'): break
    return choices


def _stopped_stage(metadata):
    """The first stage in the run's plan that is not completed, reused or skipped.

    A stage the run's own prepare ruled out (`skipped_stages`) counts as skipped even when it never reached the
    manifest, so a failed run whose first unfinished stage is one that will never run still names the stage that
    stopped it.
    """
    if not isinstance(metadata, dict):
        return None
    plan = plan_for(metadata)
    recorded = {}
    for entry in reversed(metadata.get('stages') or []):
        if isinstance(entry, dict) and entry.get('name') not in recorded:
            recorded[entry['name']] = entry.get('status')
    skipped = set(metadata.get('skipped_stages') or {})
    for stage in plan:
        if recorded.get(stage.name) in ('completed', 'reused', 'skipped') or stage.name in skipped:
            continue
        return stage
    return None


def continue_plan(run_dir, metadata=None):
    """The stage that stopped and the checkpoint Resume would continue it from, or None.

    The checkpoint is the first existing one the stage's declaration names, spelled relative to the stage directory
    for the record and absolute for the stage that runs it. A stage that resumes itself (`resumes_in_place`) is
    continued with no checkpoint at all, because re-entry is the whole of its resume. None means Resume is not
    offered: no stage is left, or the stopped stage declares no checkpoint that exists.
    """
    run_dir = Path(run_dir)
    if metadata is None:
        try:
            metadata = json.loads((run_dir / 'manifest.json').read_text())
        except (OSError, ValueError):
            return None
    if not isinstance(metadata, dict):
        return None
    stage = _stopped_stage(metadata)
    if stage is None:
        return None
    if getattr(stage, 'resumes_in_place', False):
        return {'name': stage.name, 'relative': stage.relative, 'checkpoint': None,
                'checkpoint_relative': None, 'resumes_in_place': True}
    declared = getattr(stage, 'checkpoint', None)
    if isinstance(declared, str):
        declared = (declared,)
    if not declared:
        return None
    try:
        directory = stage_root(run_dir) / Path(stage.relative).parent
    except (OSError, ValueError):
        # A run directory without its stages/ tree has nothing for a reader to offer; the view reports that run
        # unrepairable rather than this helper raising out of a page.
        return None
    for candidate in declared:
        if not isinstance(candidate, str) or not candidate:
            continue
        path = directory / candidate
        if path.is_file() and not path.is_symlink():
            return {'name': stage.name, 'relative': stage.relative,
                    'checkpoint': str(path.absolute()),
                    'checkpoint_relative': PurePosixPath(candidate).as_posix(),
                    'resumes_in_place': False}
    return None


def _resume_attempt(run_dir):
    history = Path(run_dir) / 'resume_history'
    history.mkdir(parents=True, exist_ok=True)
    attempts = [int(path.name) for path in history.iterdir() if path.is_dir() and path.name.isdigit()]
    return history / f'{max(attempts, default=0) + 1:04d}'


def _restore_resume_journal(run_dir, journal):
    run_dir = Path(run_dir)
    archive = run_dir / journal['archive']
    root = stage_root(run_dir)
    for relative in reversed(journal.get('created', [])):
        current = root / relative
        if current.is_symlink() or current.is_file():
            current.unlink()
        elif current.is_dir():
            shutil.rmtree(current)
    for item in reversed(journal.get('moved', [])):
        current = root / item['relative']
        saved = archive / 'stages' / item['relative']
        if current.is_symlink() or current.is_file():
            current.unlink()
        elif current.is_dir():
            shutil.rmtree(current)
        if saved.exists():
            current.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(saved), str(current))
    before = archive / 'manifest.before.json'
    if before.is_file():
        restored = run_dir / '.manifest.resume.restore'
        restored.write_bytes(before.read_bytes())
        os.replace(restored, run_dir / 'manifest.json')
    journal_path = run_dir / 'resume_journal.json'
    if journal_path.is_file(): journal_path.unlink()
    if archive.is_dir(): shutil.rmtree(archive)


def recover_resume_journal(run_dir, job=None):
    """Finish or roll back an interrupted in-place resume preparation."""
    run_dir = Path(run_dir)
    journal_path = run_dir / 'resume_journal.json'
    if not journal_path.is_file(): return
    journal = json.loads(journal_path.read_text())
    if journal.get('status') == 'committed' and job and job.get('status') in ('queued', 'running'):
        journal_path.unlink()
        return
    _restore_resume_journal(run_dir, journal)


def prepare_resume_in_place(run_dir, from_stage, analyses=None, finalize=True):
    """Prepare an in-place resume while preserving current stage files and run ID."""
    run_dir = Path(run_dir)
    manifest_path = run_dir / 'manifest.json'
    metadata = json.loads(manifest_path.read_text())
    if from_stage not in resumable_stages(run_dir, metadata):
        raise ValueError('That stage is outside the completed-stage prefix; choose an earlier stage or clone the run')
    plan, _, _ = stage_definitions(metadata)
    names = [name for name, _ in plan]
    start = names.index(from_stage)
    if run_dir.joinpath('resume_journal.json').is_file():
        recover_resume_journal(run_dir, {'status': 'failed'})
    attempt = _resume_attempt(run_dir)
    archive = attempt.relative_to(run_dir)
    if analyses is not None and analyses != metadata.get('analyses', []):
        metadata['analyses'] = analyses
    files.atomic_json(attempt / 'manifest.before.json', metadata)
    files.atomic_json(attempt / 'job.before.json', metadata)
    journal_path = run_dir / 'resume_journal.json'
    journal = {'status': 'preparing', 'archive': str(archive), 'moved': [], 'created': []}
    files.atomic_json(journal_path, journal)
    try:
        root = stage_root(run_dir)
        skipped = set(metadata.get('skipped_stages') or {})
        for name, relative in plan[start:]:
            relative_dir = Path(relative).parent
            source = root / relative_dir
            if source.is_symlink(): raise ValueError(f'{relative_dir}: stage directory must not be symbolic')
            if name in skipped:
                # The run's own prepare decided this stage will not run, so it has no directory to archive or resume.
                continue
            if not source.is_dir():
                raise FileNotFoundError(f'{relative_dir}: current stage directory is missing')
        history = metadata.setdefault('resume_history', [])
        history.append({'attempt': attempt.name, 'from_stage': from_stage, 'status': metadata.get('status'),
                        'stages': metadata.get('stages', []), 'analyses': metadata.get('analyses', []),
                        'archived_at': datetime.datetime.now(datetime.timezone.utc).isoformat()})
        metadata['stages'] = [entry for entry in metadata.get('stages', []) if entry.get('name') in names[:start]]
        metadata['analyses'] = [dict(task, status='superseded', superseded_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
                                for task in metadata.get('analyses', [])]
        metadata.update(status='queued', error=None, ended_at=None, resume_count=metadata.get('resume_count', 0) + 1,
                        resume_from=from_stage, resume_requested_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        resume_in_place=True)
        files.atomic_json(manifest_path, metadata)
        journal['status'] = 'committed'
        files.atomic_json(journal_path, journal)
        if finalize:
            journal_path.unlink()
        return metadata
    except Exception:
        _restore_resume_journal(run_dir, journal)
        raise


def prepare_continue_in_place(run_dir, analyses=None):
    """Prepare continuing the stopped stage from its checkpoint, keeping its directory and files.

    Resume and Restart differ in one thing here: Restart archives the stages from its boundary, so the stage starts
    from its inputs. Continue keeps the failed stage's directory as it is, removes only its manifest record, and
    records the checkpoint the worker hands that stage. The stage script decides what to skip and appends to what is
    already there; nothing is archived and nothing is deleted.
    """
    run_dir = Path(run_dir)
    manifest_path = run_dir / 'manifest.json'
    metadata = json.loads(manifest_path.read_text())
    plan = continue_plan(run_dir, metadata=metadata)
    if plan is None:
        stage = _stopped_stage(metadata)
        if stage is None:
            raise ValueError('This run has no stage left to continue; use Restart from stage')
        raise ValueError(f'{stage.name} has no checkpoint to continue from; use Restart from stage')
    names = [name for name, _ in stage_definitions(metadata)[0]]
    try:
        start = names.index(plan['name'])
    except ValueError as exc:
        raise ValueError(f'{plan["name"]} is not a stage of this run; use Restart from stage') from exc
    if run_dir.joinpath('resume_journal.json').is_file():
        recover_resume_journal(run_dir, {'status': 'failed'})
    if analyses is not None and analyses != metadata.get('analyses', []):
        metadata['analyses'] = analyses
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata['stages'] = [entry for entry in metadata.get('stages', []) if entry.get('name') in names[:start]]
    metadata['analyses'] = [dict(task, status='superseded', superseded_at=now)
                            for task in metadata.get('analyses', [])]
    metadata.update(status='queued', error=None, ended_at=None,
                    resume_count=metadata.get('resume_count', 0) + 1,
                    resume_mode='continue', continue_stage=plan['name'],
                    continue_checkpoint=plan['checkpoint_relative'],
                    resume_from=plan['name'], resume_requested_at=now, resume_in_place=True)
    files.atomic_json(manifest_path, metadata)
    return metadata


def run(run_dir: Path, log: Path, execute=None, on_stage=None, stop_after=None):
    root = stage_root(run_dir)
    initial=json.loads((run_dir/'manifest.json').read_text()) if (run_dir/'manifest.json').exists() else {}
    plan,required_inputs,required_outputs=stage_definitions(initial)
    shared=initial.get('shared_reference')
    shared_path=None
    if shared:
        from ..analysis.runs import references as aa_references
        shared_path,_=aa_references.resolve(run_dir.parent,shared['source_run_id'],shared['sha256'])
    with log.open('a') as fp:
        for name, relative in plan:
            stage_dir = root / Path(relative).parent
            manifest = run_dir / 'manifest.json'
            data = json.loads(manifest.read_text()) if manifest.exists() else {'stages': []}
            if data.get('inputs') is not None:
                # A run that names its inputs by reference is checked before every stage: a repository or store file
                # changed under a prepared run refuses here, before a stage reads bytes the run did not record.
                run_inputs.verify_manifest(run_dir, data)
            previous = next((s for s in reversed(data['stages']) if s.get('name') == name), None)
            skipped = (data.get('skipped_stages') or {}).get(name)
            if skipped is not None:
                # The run's own prepare decided this stage will not run. Nothing was written for it, so nothing is
                # executed and no directory exists: the record says skipped, with the reason, and the run carries on.
                if previous is not None and previous.get('status') == 'skipped':
                    if stop_after == name:
                        break
                    continue
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                data['stages'].append({'name': name, 'status': 'skipped', 'reason': skipped, 'command': [],
                                       'cwd': None, 'log': None, 'exit_code': None, 'environment': {},
                                       'started_at': now, 'ended_at': now})
                files.atomic_json(run_dir / 'manifest.json', data)
                if stop_after == name:
                    break
                continue
            if previous:
                if previous.get('status') in ('completed','reused'):
                    if not data.get('resume_in_place'):
                        outputs = declared_output_hashes(stage_dir, required_outputs.get(name, ()), previous.get('outputs_sha256'))
                        files.verify(stage_dir, outputs)
                    continue
                raise ValueError('This stage already has an attempt; reset it through resume preparation before running again')
            # The code is verified where it is about to run, not where a completed stage is merely being walked past.
            for module, declared in (data.get('python_modules') or {}).items():
                run_scripts.verify_one(module, declared, root=ROOT)
            script = run_scripts.script_for(data, name, stage_dir / Path(relative).name, root=ROOT)
            started = datetime.datetime.now(datetime.timezone.utc).isoformat()
            entry = {'inputs': list(required_inputs.get(name, ())), 'outputs': list(required_outputs.get(name, ())), 'cwd': str(stage_dir), 'environment': recorded_environment(), 'name': name, 'command': stage_command(name, script), 'started_at': started, 'status': 'running', 'log': str(log), 'exit_code': None}
            # What the stage is *given*, not what it works in. The stage directory is where a stage writes -- a series
            # driver's condition directories, their trajectories and the per-condition force-field copies all sit
            # inside it -- so hashing the whole directory records the run's own output as its provenance, and an
            # in-place resume re-enters the stage and pays for it again (measured on the project's own series: 57
            # files / 1,830.6 MB, against a declared 19 files / ~14 KB). The declaration already names the set the
            # stage must be given, so the recorded map follows it: read once, spelled relative to the stage directory
            # for `inputs_sha256` and relative to the execution root for `dependency_sha256`.
            declared_inputs = [(path, files.sha256(path))
                               for pattern in required_inputs.get(name, ())
                               for path in _declared_paths(stage_dir, pattern)
                               if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve())]
            entry['inputs_sha256'] = {str(path.relative_to(stage_dir)): digest for path, digest in declared_inputs}
            entry['dependency_sha256'] = {str(path.relative_to(root)): digest for path, digest in declared_inputs}
            data['stages'].append(entry); files.atomic_json(manifest, data)
            stage_log = stage_log_path(run_dir, name=stage_dir.name, resume_count=data.get('resume_count'))
            if stage_log is None:
                raise ValueError(f'No log location for stage {name}')
            entry['log'] = str(stage_log)
            tick = __import__('time').monotonic()

            def write_stage(record, **fields):
                """How this site writes: into the stage entry, and a terminal status into the run.

                Two things the shared lifecycle cannot know about a stage. The reuse path records
                `reused` and leaves the loop, which the manager sees as a successful block and would
                overwrite with `completed` -- so a record that already reached a terminal status keeps
                it. And a terminal status is also the run's, with the failure line in the stage log,
                where it has always been written.
                """
                if record.get('status') in ('reused', 'failed', 'cancelled') and fields.get('status') == 'completed':
                    return
                record.update(fields)
                if record.get('status') in ('failed', 'cancelled'):
                    data['status'] = record['status']; data['error'] = record['error']
                    fp.write(f'\n{name} failed: {record["error"]}\n'); fp.flush()

            # The mdrun budget and the scheme choices in one place: the manifest records what ran, and the CG
            # stages get the flags as environment because their commands are shell scripts.
            from . import devices
            from .adapters import aa as aa_adapter
            stage_settings = dict(initial.get('settings') or data.get('settings') or {})
            # Three brackets, all from the one builder:
            #   MDRUN_FLAGS_AUTO   minimisation -- every scheme at auto, no checkpoint flag;
            #   MDRUN_FLAGS        equilibration and production for the CG-style scripts (the run's schemes, PME
            #                      left on the CPU, which the GPU launcher tests pin);
            #   MDRUN_FLAGS_PME    the AA reference's dynamics (the run's schemes and PME on the GPU).
            # A script's minimisation line reads AUTO, so a scheme chosen for the dynamics cannot reach the first leg.
            gromacs_flavour = aa_adapter.gromacs_flavour()
            mdrun_launcher, mdrun_flags = aa_adapter.mdrun_command_flags(
                stage_settings, 'equilibration', gromacs_flavour)
            _, mdrun_flags_auto = aa_adapter.mdrun_command_flags(stage_settings, 'em', gromacs_flavour)
            _, mdrun_flags_dynamics = aa_adapter.mdrun_command_flags(stage_settings, 'production', gromacs_flavour)
            # The device this run uses, resolved once: every stage records the same index, and each stage measures
            # what is on it when the stage starts.
            gpu_index = int(stage_settings.get('mdrun_gpu') or 0)

            def finish_stage(record):
                record['resource_usage'] = {'wall_seconds': __import__('time').monotonic()-tick, 'openmp_threads': int(stage_settings.get('mdrun_ntomp') or 8), 'mpi_ranks': int(stage_settings.get('mdrun_ranks') or 1), 'gromacs_flavour': gromacs_flavour,
                                        # A host that reports no device records no device, not index 0 with an empty name.
                                        'gpu': devices.usage(gpu_index) if devices.present() else None,
                                        'output_bytes': sum(p.stat().st_size for p in files.safe_files(stage_dir))}
                record['ended_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                files.atomic_json(manifest, data)

            # Imported at call time because the lifecycle module imports this one for Cancelled;
            # a module-level import would be circular.
            from .coordination.attempt import attempt as managed_attempt
            with managed_attempt(entry, update=write_stage, on_exit=finish_stage):
                stage_env=environment()
                # A stage's scripts are repository files; they need the interpreter this application runs and the
                # checkout on the import path, recorded so the run says which python executed it. `STAGE_DATA` names
                # the generated per-stage record a script reads its run numbers from.
                stage_env['PYTHON']=sys.executable
                stage_env['PYTHONPATH']=str(ROOT)
                stage_env['STAGE_DATA']=str(stage_dir / 'stage.json')
                # What Resume recorded: this stage, and no other, is handed the checkpoint it continues from. The
                # path is absolute because the stage runs with its own directory as the working directory.
                continued_from = data.get('continue_checkpoint')
                if data.get('continue_stage') == name and continued_from:
                    continued_from = str((stage_dir / continued_from).absolute())
                    stage_env['MDRUN_CONTINUE'] = continued_from
                    entry['environment']['MDRUN_CONTINUE'] = continued_from
                entry['environment']['PYTHON']=sys.executable
                entry['environment']['PYTHONPATH']=str(ROOT)
                # A shared stage script reads the values it was written against from the run's settings, so the
                # file in the repository is one file rather than a per-run stamped copy. Names are upper-cased with a
                # prefix so they cannot collide with GROMACS' own environment.
                for _key, _value in stage_settings.items():
                    if _value is not None and not isinstance(_value, (dict, list, tuple)):
                        stage_env[f'RUN_SETTING_{str(_key).upper()}'] = str(_value)
                stage_env['MDRUN_LAUNCHER']=mdrun_launcher
                stage_env['MDRUN_FLAGS_AUTO']=mdrun_flags_auto
                stage_env['MDRUN_FLAGS']=mdrun_flags
                stage_env['MDRUN_FLAGS_PME']=mdrun_flags_dynamics
                # **`OMP_NUM_THREADS` and `-ntomp` have to agree, and GROMACS refuses to run when they do not:**
                # "Environment variable OMP_NUM_THREADS (8) and the number of threads requested on the command line
                # (4) have different values. Either omit one, or set them both to the same value." `environment()`
                # hard-codes 8, which was harmless only for as long as every setting was also 8 -- the first run
                # with `mdrun_ntomp = 4` died in its minimisation because of it. The number is taken from the flags
                # that were actually built rather than from the setting, so an `auto` bracket that chose differently
                # cannot put the two out of step, and the recorded environment stays truthful.
                _flags = (mdrun_flags or '').split()
                if '-ntomp' in _flags and _flags.index('-ntomp') + 1 < len(_flags):
                    stage_env['OMP_NUM_THREADS'] = _flags[_flags.index('-ntomp') + 1]
                entry['environment']['MDRUN_LAUNCHER']=mdrun_launcher
                entry['environment']['MDRUN_FLAGS_AUTO']=mdrun_flags_auto
                entry['environment']['MDRUN_FLAGS']=mdrun_flags
                entry['environment']['MDRUN_FLAGS_PME']=mdrun_flags_dynamics
                if stage_env.get('OMP_NUM_THREADS'):
                    entry['environment']['OMP_NUM_THREADS']=stage_env['OMP_NUM_THREADS']
                if shared_path:
                    aa_references.resolve(run_dir.parent,shared['source_run_id'],shared['sha256'])
                    stage_env['AA_REFERENCE_DIR']=str(shared_path)
                    entry['environment']['AA_REFERENCE_DIR']=str(shared_path)
                    entry['shared_reference']=shared
                cg_names = initial.get('cg_names')
                if cg_names is None and initial.get('molecule_snapshot'):
                    cg_names = CGNames.for_snapshot(initial['molecule_snapshot']).__dict__
                if cg_names:
                    for key, value in {'MOLECULE_TYPE': cg_names['residue_name'],
                                       'INITIAL_ITP': cg_names['initial_itp'],
                                       'FINAL_ITP': cg_names['final_itp']}.items():
                        stage_env[key] = value
                        entry['environment'][key] = value
                if name == 'AA reference' and data.get('reference_reused'):
                    if on_stage: on_stage(name, entry)
                    entry.update(status='reused', command=[], source_run=data['reference_run_id'],
                                 outputs_sha256=declared_output_hashes(stage_dir, required_outputs.get(name, ())), exit_code=0)
                    continue
                if on_stage:
                    on_stage(name, entry)
                if not script.is_file():
                    raise FileNotFoundError(f'required stage script missing: {script}')
                local_required={k:tuple(p for p in patterns if not (shared_path and '1_AA-reference/prod/' in p)) for k,patterns in required_inputs.items()}
                validate_stage_inputs(name, stage_dir, local_required)
                fp.write(f'\n## {name}\n$ {shlex.join(entry["command"])}\n'); fp.flush()
                stage_log.parent.mkdir(parents=True, exist_ok=True)
                with stage_log.open('a') as output:
                    try:
                        result = (execute or subprocess.run)(entry['command'], cwd=stage_dir, env=stage_env, stdout=output, stderr=subprocess.STDOUT, check=True)
                    except subprocess.CalledProcessError as exc:
                        if exc.returncode != SKIPPED_EXIT_CODE:
                            raise
                        raise Skipped(skip_reason(stage_dir, name)) from None
                entry['exit_code'] = result.returncode
                missing = missing_files(stage_dir, required_outputs.get(name, ()))
                if missing:
                    raise RuntimeError(f'{name}: command exited successfully but required outputs are missing or empty: {", ".join(missing)}')
                entry['status'] = 'completed'; entry['exit_code'] = 0
                entry['outputs_sha256'] = declared_output_hashes(stage_dir, required_outputs.get(name, ()))
                if data.get('continue_stage') == name:
                    # The continuation is spent: a later stage must not inherit it, and a reader of the finished
                    # manifest should not think this run is still waiting to continue.
                    data.pop('continue_stage', None)
                    data.pop('continue_checkpoint', None)
                    data.pop('resume_mode', None)
            if stop_after == name:
                break
        data = json.loads((run_dir/'manifest.json').read_text())
        data.update(status='completed', ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        files.atomic_json(run_dir/'manifest.json', data)
        # A run publishes its frames without anyone asking: this is where the stage plan is finished and the run's
        # own manifest says so, and the notification is what the analysis layer queues the run's own kinds from.
        run_completed(run_dir)


class Cancelled(RuntimeError):
    pass


SKIPPED_EXIT_CODE = 4


class Skipped(RuntimeError):
    """A stage that had nothing to do.

    The contract's fourth outcome. A stage exits `SKIPPED_EXIT_CODE` and writes `skip.json` beside its script with the
    reason; the run records `skipped` and carries on, because nothing was attempted and nothing is owed. A protein-free
    complex run reaches the back-map, which aligns a protein and therefore has none to align.

    The code travels on the exception. `attempt` records a terminal `exit_code` from `returncode` when an exception
    carries one, and a skipped stage used to record none -- so the record disagreed with the contract that says
    `skipped = exit 4`, and a reader could not tell this skip from a stage that never ran.
    """

    returncode = SKIPPED_EXIT_CODE


def skip_reason(stage_dir, name):
    """Why a stage had nothing to do: the stage's own words, so a reader is not left guessing at an exit code."""
    try:
        return str(json.loads((Path(stage_dir) / 'skip.json').read_text()).get('reason') or f'{name} had nothing to do')
    except (OSError, ValueError):
        return f'{name} had nothing to do'
