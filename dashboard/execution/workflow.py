"""Shared stage execution, provenance and checksum-verified resume."""
from pathlib import Path
import os, shutil, subprocess, json, datetime, re, shlex, hashlib
from .. import files, paths
from .stage_io import environment, execution_root
from . import cg_adapter
from .cg_workflow import CGNames
from .stages import Stage, stage_tables
from .cg_adapter import (STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS, SETTING_SPECS,
    stage_defaults, normalize_settings,
    tool_metadata, _mdp_value, draft_model, FORCE_FIELD, TUTORIAL_TEMPLATE, AA_TEMPLATE, ROOT)

def readiness(detergent, method, profile='standard', mapping_candidate=None, molecule_root=None):
    """Re-export DDM readiness, forwarding an optional molecule root."""
    from .cg_adapter import readiness as _readiness
    return _readiness(detergent, method, profile, mapping_candidate, molecule_root=molecule_root)

def stage_command(name, script):
    command = ['bash', '-e', '-o', 'pipefail', str(script)]
    if name == 'AA reference' and script.name == 'run_1mol_AA_system.sh':
        command += ['molecule.pdb', 'spc216.gro', 'SOL', '3']
    return command


def missing_files(directory, patterns):
    return [pattern for pattern in patterns if not any(p.is_file() and p.stat().st_size for p in directory.glob(pattern))]


def validate_stage_inputs(name, directory, required=None):
    missing = missing_files(directory, (REQUIRED_INPUTS if required is None else required).get(name, ()))
    if name == 'AA reference' and (directory / 'system_EMPTY.top').is_file():
        includes = re.findall(r'^\s*#include\s+"([^"]+)"', (directory / 'system_EMPTY.top').read_text(), re.M)
        missing += missing_files(directory, includes)
    if missing:
        raise FileNotFoundError(f'{name}: missing required inputs: {", ".join(missing)}. Stage molecule-specific inputs before execution.')


def stage_definitions(metadata):
    """Return the executable contract selected by immutable run metadata."""
    if metadata.get('run_type')=='aa_only':
        from . import aa_workflow
        return aa_workflow.STAGES,aa_workflow.REQUIRED_INPUTS,aa_workflow.REQUIRED_OUTPUTS
    if metadata.get('run_type') not in (None,'aa_cg'):raise ValueError('Unknown run type')
    names = CGNames.for_snapshot(metadata['molecule_snapshot']) if metadata.get('molecule_snapshot') else CGNames.ddm_defaults()
    return cg_adapter.stage_contract(names)


def plan_for(metadata) -> tuple[Stage, ...]:
    """Return the resolved immutable stage declarations for a run."""
    if metadata.get('run_type') == 'aa_only':
        from . import aa_workflow
        return tuple(aa_workflow.STAGE_DEFS)
    if metadata.get('run_type') not in (None, 'aa_cg'):
        raise ValueError('Unknown run type')
    names = CGNames.for_snapshot(metadata['molecule_snapshot']) if metadata.get('molecule_snapshot') else CGNames.ddm_defaults()
    return tuple(stage.resolve(names.env()) for stage in cg_adapter.STAGE_DEFS)


def prepare_run(run_dir, **kwargs):
    """New layout; all executable relative paths remain inside stages/."""
    stages = run_dir / 'stages'; stages.mkdir()
    cg_adapter.prepare(stages, **kwargs)
    metadata = json.loads((stages / 'manifest.json').read_text())
    (stages / 'manifest.json').unlink()
    shutil.copytree(stages, run_dir / 'inputs')
    metadata.update(layout_version=2, input_snapshot_sha256=files.hashes(run_dir / 'inputs'),
                    prepared_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    files.atomic_json(run_dir / 'manifest.json', metadata)


def resumable_stages(run_dir, metadata=None):
    if metadata is None:
        try:
            metadata = json.loads((run_dir / 'manifest.json').read_text())
        except (ValueError, OSError): return []
    data = metadata
    if not isinstance(data,dict) or not data.get('input_snapshot_sha256'): return []
    choices = []
    for name, _ in stage_definitions(data)[0]:
        choices.append(name)
        entry = next((e for e in reversed(data.get('stages', [])) if isinstance(e,dict) and e.get('name') == name), {})
        if entry.get('status') not in ('completed', 'reused') or not entry.get('outputs_sha256'): break
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
        from . import aa_workflow
        tools=aa_workflow.tool_metadata()
    else:tools=tool_metadata()
    metadata.update(tools=tools, environment={k:environment()[k] for k in ('PATH','OMP_NUM_THREADS','MPLBACKEND')}, source_manifest_sha256=files.sha256(source/'manifest.json'), stages=[], resume_of=source.name, resume_from=from_stage, reference_reused=old.get('reference_reused',False))
    for name, relative in stage_definitions(old)[0]:
        if name == from_stage: break
        entry = next(e for e in reversed(old['stages']) if e['name'] == name)
        src = execution_root(source) / Path(relative).parent
        files.verify(src, entry['outputs_sha256'])
        dst = run_dir / 'stages' / Path(relative).parent
        for rel in entry['outputs_sha256']:
            out = dst / rel; out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, out)
        record = dict(entry, status='reused', source_run=source.name,
                      source_stage=name, tools=old.get('tools',{}), command=[], started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), log=None)
        metadata['stages'].append(record)
    files.atomic_json(run_dir / 'manifest.json', metadata)


def run(run_dir: Path, log: Path, execute=None, on_stage=None, stop_after=None):
    stage_root = execution_root(run_dir)
    initial=json.loads((run_dir/'manifest.json').read_text()) if (run_dir/'manifest.json').exists() else {}
    plan,required_inputs,required_outputs=stage_definitions(initial)
    shared=initial.get('shared_reference')
    shared_path=None
    if shared:
        from ..analysis import aa_references
        shared_path,_=aa_references.resolve(run_dir.parent,shared['source_run_id'],shared['sha256'])
    with log.open('a') as fp:
        for name, relative in plan:
            script = stage_root / relative
            manifest = run_dir / 'manifest.json'
            data = json.loads(manifest.read_text()) if manifest.exists() else {'stages': []}
            previous = next((s for s in reversed(data['stages']) if s.get('name') == name), None)
            if previous:
                if previous.get('status') in ('completed','reused'):
                    files.verify(script.parent, previous.get('outputs_sha256'))
                    continue
                raise ValueError('This stage already has an attempt; resume into a new run to preserve its outputs')
            started = datetime.datetime.now(datetime.timezone.utc).isoformat()
            entry = {'inputs': list(required_inputs.get(name, ())), 'outputs': list(required_outputs.get(name, ())), 'cwd': str(script.parent), 'environment': {k: environment()[k] for k in ('PATH','MPLBACKEND','OMP_NUM_THREADS')}, 'name': name, 'command': stage_command(name, script), 'started_at': started, 'status': 'running', 'log': str(log), 'exit_code': None}
            entry['inputs_sha256'] = files.hashes(script.parent)
            entry['dependency_sha256'] = {str(p.relative_to(stage_root)): files.sha256(p) for pattern in required_inputs.get(name,()) for p in script.parent.glob(pattern) if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(stage_root.resolve())}
            data['stages'].append(entry); files.atomic_json(manifest, data)
            stage_log = log.parent / (script.parent.name + '.log') if log.parent.name == 'logs' else log
            entry['log'] = str(stage_log)
            tick = __import__('time').monotonic()
            try:
                stage_env=environment()
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
                    entry.update(status='reused', command=[], source_run=data['reference_run_id'], outputs_sha256=files.hashes(script.parent), exit_code=0)
                    continue
                if on_stage:
                    on_stage(name, entry)
                if not script.is_file():
                    raise FileNotFoundError(f'required stage script missing: {relative}')
                local_required={k:tuple(p for p in patterns if not (shared_path and '1_AA-reference/prod/' in p)) for k,patterns in required_inputs.items()}
                validate_stage_inputs(name, script.parent,local_required)
                fp.write(f'\n## {name}\n$ {shlex.join(entry["command"])}\n'); fp.flush()
                with stage_log.open('a') as output:
                    result = (execute or subprocess.run)(entry['command'], cwd=script.parent, env=stage_env, stdout=output, stderr=subprocess.STDOUT, check=True)
                entry['exit_code'] = result.returncode
                missing = missing_files(script.parent, required_outputs.get(name, ()))
                if missing:
                    raise RuntimeError(f'{name}: command exited successfully but required outputs are missing or empty: {", ".join(missing)}')
                entry['status'] = 'completed'; entry['exit_code'] = 0
                entry['outputs_sha256'] = files.hashes(script.parent)
            except Exception as exc:
                entry['status'] = 'cancelled' if isinstance(exc, Cancelled) else 'failed'; entry['error'] = str(exc)
                if isinstance(exc, subprocess.CalledProcessError): entry['exit_code'] = exc.returncode
                data['status'] = entry['status']; data['error'] = str(exc)
                fp.write(f'\n{name} failed: {exc}\n'); fp.flush()
                raise
            finally:
                entry['resource_usage'] = {'wall_seconds': __import__('time').monotonic()-tick, 'openmp_threads': 8, 'output_bytes': sum(p.stat().st_size for p in files.safe_files(script.parent))}
                entry['ended_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                files.atomic_json(manifest, data)
            if stop_after == name:
                break
        data = json.loads((run_dir/'manifest.json').read_text())
        data.update(status='completed', ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        files.atomic_json(run_dir/'manifest.json', data)


class Cancelled(RuntimeError):
    pass
