"""Explicit CG-only workflow for immutable molecule compositions."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .. import files, paths
from ..models import compositions
from .stages import Stage, stage_tables

STAGE_DEFS = (
    Stage('CG simulation', '1_CG-simulation/cg_simulation.sh',
          ('../composition.gro', '../composition.itp'), ('cg.gro', 'cg.xtc')),
    Stage('CG assessment', '2_CG-assessment/assess.sh',
          ('../1_CG-simulation/cg.gro', '../composition.itp'), ('validation.json',)),
    Stage('CG SASA', '3_CG-SASA/sasa.sh',
          ('../1_CG-simulation/cg.gro',), ('sasa.xvg',)),
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
    stages = Path(run_dir) / 'stages'
    stages.mkdir(parents=True, exist_ok=True)
    for name, relative in ((stage.name, stage.relative) for stage in STAGE_DEFS):
        script = stages / relative
        script.parent.mkdir(parents=True, exist_ok=True)
        if name == 'CG simulation':
            script.write_text('#!/usr/bin/env bash\nset -euo pipefail\ncp ../composition.gro cg.gro\nprintf "composition CG screening\\n" > cg.xtc\n')
        elif name == 'CG assessment':
            script.write_text('#!/usr/bin/env bash\nset -euo pipefail\nprintf \'{"status":"screened","scientifically_validated":false}\\n\' > validation.json\n')
        else:
            script.write_text('#!/usr/bin/env bash\nset -euo pipefail\nprintf "# composition CG SASA screening\\n" > sasa.xvg\n')
        script.chmod(0o755)
    for name in ('composition.gro', 'composition.itp', 'mapping.json', 'bonded-state.json'):
        shutil.copy2(artifact_root / name, stages / name)
    metadata = {'run_type': 'cg_composition', 'workflow_version': VERSION,
                'composition_id': composition_id, 'composition_snapshot_sha256': record['snapshot_hash'],
                'composition_identity': record['identity'], 'scientifically_validated': False,
                'stage_plan': [name for name, _ in STAGES], 'settings': settings or {}}
    files.atomic_json(Path(run_dir) / 'manifest.json', metadata)
