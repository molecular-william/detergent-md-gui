import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_ring_constraint_preparation_uses_molecule_specific_initial_itp(tmp_path):
    stage = tmp_path / '3_initial_CG'
    stage.mkdir()
    (stage / 'Maltose_initial.itp').write_text(
        '[ constraints ]\n1 2 1 0.10\n2 3 1 0.20\n'
    )
    (tmp_path / '2_mapping').mkdir()
    (tmp_path / '2_mapping' / 'ring_targets.json').write_text(json.dumps({
        'constraints': [
            {'atoms': [1, 2], 'target_nm': 0.15},
            {'atoms': [2, 3], 'target_nm': 0.25},
        ]
    }))
    environment = os.environ.copy()
    environment['INITIAL_ITP'] = 'Maltose_initial.itp'

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'dashboard/execution/scripts/prepare_ring_constraints.py')],
        cwd=stage, env=environment, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (stage / 'Maltose_initial.itp').is_file()
    assert (stage / 'Maltose_coordinate_seed.itp').is_file()
    assert '1 2 1 0.150000' in (stage / 'Maltose_initial.itp').read_text()
