"""Explicit CG-only workflow for immutable molecule compositions.

What this module offers the rest of the application: PROTOCOL (the run-type
surface at the end of this file), the STAGE_DEFS/STAGES stage tables, and
readiness()/prepare_run() -- the two operations the protocol forwards. Two facts
are stated here rather than left to be inferred from absent attributes: a
composition screening run configures no setting (SETTING_SPECS is empty), and it
calls no external executable, so its tool report records the Python interpreter
alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ... import files, paths
from ...models import compositions
from .. import protocol, run_inputs
from ..environment import recorded_environment
from ..stages import Stage, stage_tables

ARTIFACTS = ('composition.gro', 'composition.itp', 'mapping.json', 'bonded-state.json')

#: The three stages run repository scripts, recorded in the manifest's `stage_scripts` by path and digest. Nothing
#: executable is written into the run any more: the screening stubs are this repository's code, and the artifact they
#: copy is resolved from the run's own input record rather than stamped into a generated script.
STAGE_DEFS = (
    Stage('CG simulation', '1_CG-simulation/cg_simulation.sh',
          ('../../inputs/inputs.json',), ('cg.gro', 'screening.json'),
          script='dashboard/execution/scripts/composition_simulation.sh'),
    Stage('CG assessment', '2_CG-assessment/assess.sh',
          ('../1_CG-simulation/cg.gro',), ('validation.json',),
          script='dashboard/execution/scripts/composition_assessment.sh'),
    Stage('CG SASA', '3_CG-SASA/sasa.sh',
          ('../1_CG-simulation/cg.gro',), ('sasa.json',),
          script='dashboard/execution/scripts/composition_sasa.sh'),
)
STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS = stage_tables(STAGE_DEFS)
VERSION = 'cg-composition-v1'


def readiness(composition_id: str, root: Path) -> dict:
    checks = []
    try:
        record = compositions.get(composition_id)
        artifact_root = Path(record['artifact_root'])
        for name in ('composition.gro', 'composition.itp', 'mapping.json', 'bonded-state.json'):
            path = artifact_root / name
            checks.append({'label': name, 'path': str(path), 'ready': path.is_file() and not path.is_symlink(),
                           'detail': 'Immutable composition artifact' if path.is_file() else 'Missing artifact'})
    except (ValueError, OSError, KeyError, FileNotFoundError) as exc:
        return {'ready': False, 'blockers': [str(exc)], 'checks': []}
    blockers = [f"Missing composition artifact: {item['label']}" for item in checks if not item['ready']]
    return {'ready': not blockers, 'blockers': blockers, 'checks': checks}


def prepare_run(run_dir: Path, composition_id: str, settings=None) -> None:
    record = compositions.get(composition_id)
    artifact_root = Path(record['artifact_root']).resolve()
    if artifact_root.is_symlink() or not artifact_root.is_dir():
        raise ValueError('Composition artifact directory is unavailable')
    workspace = paths.current().workspace.resolve()
    try:
        relative_root = artifact_root.relative_to(workspace).as_posix()
    except ValueError:
        references = [run_inputs.absolute('composition_artifact', artifact_root / name, label=name)
                      for name in ARTIFACTS]
    else:
        references = [run_inputs.store('composition_artifact', f'{relative_root}/{name}', label=name,
                                       workspace_root=workspace)
                      for name in ARTIFACTS]
    # The stage directories are where each stage works; the scripts themselves are repository files, named in the
    # manifest and run with the stage directory as their working directory. A run holds no `.sh` and no `.py`.
    stages = Path(run_dir) / 'stages'
    for stage in STAGE_DEFS:
        (stages / stage.relative).parent.mkdir(parents=True, exist_ok=True)
    inputs = Path(run_dir) / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    metadata = {'run_type': 'cg_composition', 'workflow_version': VERSION,
                'execution_kind': 'screening-stub',
                'limitations': ['Composition screening is a stub: the stage scripts copy the composition '
                                'geometry and write declaration files. No GROMACS MD, assessment or SASA was '
                                'executed, and no trajectory or plot exists.'],
                'composition_id': composition_id, 'composition_snapshot_sha256': record['snapshot_hash'],
                'composition_identity': record['identity'], 'scientifically_validated': False,
                'settings': settings or {}}
    protocol.write_prepared_manifest(Path(run_dir), metadata, tools={}, plan=[name for name, _ in STAGES],
                                     environment=recorded_environment(), references=references,
                                     scripts={stage.name: stage.script for stage in STAGE_DEFS})


SETTING_SPECS: dict = {}
"""Composition screening runs expose no configurable setting.

The prepared scripts fix their own durations, so there is no bound to check and
nothing a caller could tune. The mapping is empty and declared, not missing.
"""


def stage_defaults() -> dict:
    """No settings means no defaults: an empty mapping, not an absent hook."""
    return {}


def normalize_settings(settings=None) -> dict:
    """Accept an object of settings and pass it through unchanged.

    Nothing here is range-checked, because no setting affects a composition run.
    The type check keeps the failure mode the same as the other adapters'.
    """
    if settings is not None and not isinstance(settings, dict):
        raise ValueError('Composition settings must be an object')
    return dict(settings or {})


def tool_metadata() -> dict:
    """Record the interpreter, the only tool a composition run executes.

    The prepared scripts copy immutable artifacts and write screening JSON with
    shell builtins, so there is no external executable to report. Reporting the
    Python interpreter keeps the record's shape the same as the other run types
    without inventing a tool this run never calls.
    """
    executable = sys.executable
    return {'python': {'path': executable, 'version_output': sys.version, 'sha256': files.sha256(executable)}}


def _protocol_stage_contract(metadata):
    """Composition stages carry no run-specific placeholders."""
    return STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS


def _protocol_readiness(metadata):
    composition_id = metadata.get('composition_id')
    if not composition_id:
        return protocol.blocked('composition_id is required to check a composition run')
    return readiness(composition_id, metadata.get('root'))


def _protocol_prepare(run_dir, metadata):
    prepare_run(run_dir, metadata['composition_id'], metadata.get('settings'))


PROTOCOL = protocol.Protocol(
    name='cg_composition',
    stage_contract=_protocol_stage_contract,
    stages=lambda metadata: tuple(STAGE_DEFS),
    settings_specs=lambda: SETTING_SPECS,
    stage_defaults=stage_defaults,
    normalize_settings=lambda settings=None, profile='standard': normalize_settings(settings),
    readiness=_protocol_readiness,
    prepare=_protocol_prepare,
    tool_report=tool_metadata,
)
