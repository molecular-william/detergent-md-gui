"""Shared stage execution, provenance, and resumable workflow state."""
import datetime
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from .. import files
from . import protocol
from .adapters import cg
from .adapters.cg_names import CGNames
from .coordination.manifest import stage_log_path
from .environment import environment, execution_root, recorded_environment
from .stages import Stage


def stage_command(name, script):
    command = ['bash', '-e', '-o', 'pipefail', str(script)]
    if name == 'AA reference' and script.name == 'run_1mol_AA_system.sh':
        command += ['molecule.pdb', 'spc216.gro', 'SOL', '3']
    return command


def missing_files(directory, patterns):
    return [pattern for pattern in patterns if not any(p.is_file() and p.stat().st_size for p in directory.glob(pattern))]


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


def validate_stage_inputs(name, directory, required=None):
    missing = missing_files(directory, (cg.REQUIRED_INPUTS if required is None else required).get(name, ()))
    if name == 'AA reference' and (directory / 'system_EMPTY.top').is_file():
        includes = re.findall(r'^\s*#include\s+"([^"]+)"', (directory / 'system_EMPTY.top').read_text(), re.M)
        missing += missing_files(directory, includes)
    if missing:
        raise FileNotFoundError(f'{name}: missing required inputs: {", ".join(missing)}. Stage molecule-specific inputs before execution.')


def _run_type(metadata) -> str:
    """The adapter that owns a run; absent means the historical combined AA-to-CG job."""
    return metadata.get('run_type') or 'aa_cg'


def stage_definitions(metadata):
    """Return the executable contract selected by immutable run metadata."""
    return protocol.adapter_for(_run_type(metadata)).stage_contract(metadata)


def plan_for(metadata) -> tuple[Stage, ...]:
    """Return the resolved immutable stage declarations for a run."""
    return protocol.adapter_for(_run_type(metadata)).stages(metadata)


def prepare_run(run_dir, **kwargs):
    """New layout; all executable relative paths remain inside stages/."""
    if kwargs.get('composition_id'):
        from .adapters import composition
        composition.prepare_run(run_dir, kwargs['composition_id'], kwargs.get('settings'))
        return
    stages = run_dir / 'stages'; stages.mkdir()
    cg.prepare(stages, **kwargs)
    metadata = json.loads((stages / 'manifest.json').read_text())
    (stages / 'manifest.json').unlink()
    shutil.copytree(stages, run_dir / 'inputs')
    protocol.write_prepared_manifest(run_dir, metadata, tools=metadata.get('tools', {}),
                                     plan=metadata.get('stage_plan') or [name for name, _ in cg.STAGES],
                                     environment=metadata.get('environment'))


def resumable_stages(run_dir, metadata=None):
    if metadata is None:
        try:
            metadata = json.loads((run_dir / 'manifest.json').read_text())
        except (ValueError, OSError): return []
    data = metadata
    if not isinstance(data,dict): return []
    choices = []
    for name, _ in stage_definitions(data)[0]:
        choices.append(name)
        entry = next((e for e in reversed(data.get('stages', [])) if isinstance(e,dict) and e.get('name') == name), {})
        if entry.get('status') not in ('completed', 'reused'): break
    return choices


def prepare_resume(run_dir, source, from_stage):
    """Fork a new attempt, reusing verified upstream stages only."""
    if from_stage not in resumable_stages(source):
        raise ValueError('Upstream stage hashes are unavailable; choose an earlier stage or clone the run')
    old = json.loads((source / 'manifest.json').read_text())
    files.verify(source / 'inputs', old['input_snapshot_sha256'])
    shutil.copytree(source / 'inputs', run_dir / 'inputs')
    shutil.copytree(source / 'inputs', run_dir / 'stages')
    metadata = {k: v for k,v in old.items() if k not in ('stages','status','error','ended_at','started_at','id')}
    if old.get('run_type')=='aa_only':
        from .adapters import aa
        tools=aa.tool_metadata()
    else:tools=cg.tool_metadata()
    metadata.update(tools=tools, environment=recorded_environment(), source_manifest_sha256=files.sha256(source/'manifest.json'), stages=[], resume_of=source.name, resume_from=from_stage, reference_reused=old.get('reference_reused',False))
    plan, _, required_outputs = stage_definitions(old)
    for name, relative in plan:
        if name == from_stage: break
        entry = next(e for e in reversed(old['stages']) if e['name'] == name)
        src = execution_root(source) / Path(relative).parent
        outputs = declared_output_hashes(src, required_outputs.get(name, ()), entry.get('outputs_sha256'))
        files.verify(src, outputs)
        dst = run_dir / 'stages' / Path(relative).parent
        for rel in outputs:
            out = dst / rel; out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, out)
        record = dict(entry, outputs_sha256=outputs, status='reused', source_run=source.name,
                      source_stage=name, tools=old.get('tools',{}), command=[], started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), log=None)
        metadata['stages'].append(record)
    files.atomic_json(run_dir / 'manifest.json', metadata)


def _resume_attempt(run_dir):
    history = Path(run_dir) / 'resume_history'
    history.mkdir(parents=True, exist_ok=True)
    attempts = [int(path.name) for path in history.iterdir() if path.is_dir() and path.name.isdigit()]
    return history / f'{max(attempts, default=0) + 1:04d}'


def _restore_resume_journal(run_dir, journal):
    run_dir = Path(run_dir)
    archive = run_dir / journal['archive']
    stage_root = execution_root(run_dir)
    for relative in reversed(journal.get('created', [])):
        current = stage_root / relative
        if current.is_symlink() or current.is_file():
            current.unlink()
        elif current.is_dir():
            shutil.rmtree(current)
    for item in reversed(journal.get('moved', [])):
        current = stage_root / item['relative']
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
        stage_root = execution_root(run_dir)
        for name, relative in plan[start:]:
            relative_dir = Path(relative).parent
            source = stage_root / relative_dir
            if source.is_symlink(): raise ValueError(f'{relative_dir}: stage directory must not be symbolic')
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


def run(run_dir: Path, log: Path, execute=None, on_stage=None, stop_after=None):
    stage_root = execution_root(run_dir)
    initial=json.loads((run_dir/'manifest.json').read_text()) if (run_dir/'manifest.json').exists() else {}
    plan,required_inputs,required_outputs=stage_definitions(initial)
    shared=initial.get('shared_reference')
    shared_path=None
    if shared:
        from ..analysis.runs import references as aa_references
        shared_path,_=aa_references.resolve(run_dir.parent,shared['source_run_id'],shared['sha256'])
    with log.open('a') as fp:
        for name, relative in plan:
            script = stage_root / relative
            manifest = run_dir / 'manifest.json'
            data = json.loads(manifest.read_text()) if manifest.exists() else {'stages': []}
            previous = next((s for s in reversed(data['stages']) if s.get('name') == name), None)
            if previous:
                if previous.get('status') in ('completed','reused'):
                    if not data.get('resume_in_place'):
                        outputs = declared_output_hashes(script.parent, required_outputs.get(name, ()), previous.get('outputs_sha256'))
                        files.verify(script.parent, outputs)
                    continue
                raise ValueError('This stage already has an attempt; reset it through resume preparation before running again')
            started = datetime.datetime.now(datetime.timezone.utc).isoformat()
            entry = {'inputs': list(required_inputs.get(name, ())), 'outputs': list(required_outputs.get(name, ())), 'cwd': str(script.parent), 'environment': recorded_environment(), 'name': name, 'command': stage_command(name, script), 'started_at': started, 'status': 'running', 'log': str(log), 'exit_code': None}
            entry['inputs_sha256'] = files.hashes(script.parent)
            entry['dependency_sha256'] = {str(p.relative_to(stage_root)): files.sha256(p) for pattern in required_inputs.get(name,()) for p in script.parent.glob(pattern) if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(stage_root.resolve())}
            data['stages'].append(entry); files.atomic_json(manifest, data)
            stage_log = stage_log_path(run_dir, name=script.parent.name, resume_count=data.get('resume_count'))
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
            # stages get the flags as environment because their commands are shell scripts. A stage named for
            # minimisation keeps PME on the CPU; every other stage may put it on the GPU.
            from .adapters import aa as aa_adapter
            stage_settings = dict(initial.get('settings') or data.get('settings') or {})
            # The CG launchers offload nonbonded work only -- PME stays on the CPU there, which the GPU launcher
            # tests pin -- so they take the minimisation bracket. A stage setting that names a scheme still
            # overrides it, because the bracket only fills the choices left on 'auto'.
            gromacs_flavour = aa_adapter.gromacs_flavour()
            mdrun_launcher, mdrun_flags = aa_adapter.mdrun_command_flags(stage_settings, 'em', gromacs_flavour)

            def finish_stage(record):
                record['resource_usage'] = {'wall_seconds': __import__('time').monotonic()-tick, 'openmp_threads': int(stage_settings.get('mdrun_ntomp') or 8), 'mpi_ranks': int(stage_settings.get('mdrun_ranks') or 1), 'gromacs_flavour': gromacs_flavour, 'output_bytes': sum(p.stat().st_size for p in files.safe_files(script.parent))}
                record['ended_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                files.atomic_json(manifest, data)

            # Imported at call time because the lifecycle module imports this one for Cancelled;
            # a module-level import would be circular.
            from .coordination.attempt import attempt as managed_attempt
            with managed_attempt(entry, update=write_stage, on_exit=finish_stage):
                stage_env=environment()
                stage_env['MDRUN_LAUNCHER']=mdrun_launcher
                stage_env['MDRUN_FLAGS']=mdrun_flags
                entry['environment']['MDRUN_LAUNCHER']=mdrun_launcher
                entry['environment']['MDRUN_FLAGS']=mdrun_flags
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
                                 outputs_sha256=declared_output_hashes(script.parent, required_outputs.get(name, ())), exit_code=0)
                    continue
                if on_stage:
                    on_stage(name, entry)
                if not script.is_file():
                    raise FileNotFoundError(f'required stage script missing: {relative}')
                local_required={k:tuple(p for p in patterns if not (shared_path and '1_AA-reference/prod/' in p)) for k,patterns in required_inputs.items()}
                validate_stage_inputs(name, script.parent,local_required)
                fp.write(f'\n## {name}\n$ {shlex.join(entry["command"])}\n'); fp.flush()
                stage_log.parent.mkdir(parents=True, exist_ok=True)
                with stage_log.open('a') as output:
                    result = (execute or subprocess.run)(entry['command'], cwd=script.parent, env=stage_env, stdout=output, stderr=subprocess.STDOUT, check=True)
                entry['exit_code'] = result.returncode
                missing = missing_files(script.parent, required_outputs.get(name, ()))
                if missing:
                    raise RuntimeError(f'{name}: command exited successfully but required outputs are missing or empty: {", ".join(missing)}')
                entry['status'] = 'completed'; entry['exit_code'] = 0
                entry['outputs_sha256'] = declared_output_hashes(script.parent, required_outputs.get(name, ()))
            if stop_after == name:
                break
        data = json.loads((run_dir/'manifest.json').read_text())
        data.update(status='completed', ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        files.atomic_json(run_dir/'manifest.json', data)


class Cancelled(RuntimeError):
    pass
