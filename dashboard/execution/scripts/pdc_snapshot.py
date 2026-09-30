"""One place that writes what a run looks like at a moment, and the numbers that go with the picture.

Design note `2026-09-30-pdc-detergent-model-and-snapshots.md`: a snapshot is *derived*, never stored truth, and it
is written together with the criterion's numbers at that moment so a gallery cannot disagree with a verdict. The
index (`snapshots.json`) is the record; the panel reads the PDBs and the index through the existing viewer route.

Called by the stages that already hold the coordinates -- stage 1 before any dynamics, and each assessment phase --
rather than by a stage of its own, so a resumed run re-derives its snapshots instead of keeping stale ones.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dashboard.execution.adapters import pdc_view

DIRECTORY = 'snapshots'
INDEX_NAME = 'snapshots.json'


def index(stage: Path) -> dict:
    path = Path(stage) / INDEX_NAME
    if path.is_file():
        return json.loads(path.read_text())
    return {'snapshots': [], 'note': 'derived: a resumed run re-derives these rather than keeping stale files'}


def write_snapshot(stage: Path, name: str, structure: Path, *, title: str, time_ps: float | None = None,
                   criterion: dict | None = None, detergent_residue: str = 'DDM',
                   include_water: bool = False) -> dict:
    """Write one PDB and add it to the stage's index, with the numbers the moment was judged on."""
    stage = Path(stage)
    structure = Path(structure)
    atoms = pdc_view.read_gro(structure)
    directory = stage / DIRECTORY
    directory.mkdir(exist_ok=True)
    target = directory / f'{name}.pdb'
    target.write_text(pdc_view.system_pdb(atoms, detergent_residue=detergent_residue,
                                          include_water=include_water, title=title))
    record = {'name': name, 'time_ps': time_ps, 'pdb': str(target.relative_to(stage)),
              'source': str(structure), 'source_sha256': hashlib.sha256(structure.read_bytes()).hexdigest(),
              'atoms': len(atoms), 'water_and_ions': include_water, 'verdict': criterion}
    document = index(stage)
    document['snapshots'] = [entry for entry in document['snapshots'] if entry.get('name') != name] + [record]
    (stage / INDEX_NAME).write_text(json.dumps(document, indent=2, sort_keys=True))
    return record
