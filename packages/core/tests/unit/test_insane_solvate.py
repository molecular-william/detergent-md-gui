"""Insane places the water, keeps the box, and writes the Martini 3 molecule names into the stage's topology."""
from dashboard.execution import tools
from dashboard.execution.scripts import insane_solvate

from tests.harness.pdc_fixtures import write_gro


def test_insane_keeps_the_box_and_adds_water_to_the_existing_topology(tmp_path):
    assert tools.tool_path('insane'), 'the declared Insane must resolve'
    structure = write_gro(tmp_path / 'system.gro', [(1, 'DDM', 'B01', (2.5, 2.5, 2.5))], box=(5.0, 5.0, 5.0))
    topology = tmp_path / 'system.top'
    topology.write_text('[ molecules ]\nDDM 1\n')

    result = insane_solvate.solvate(structure, topology, tmp_path / 'solvated.gro')

    lines = (tmp_path / 'solvated.gro').read_text().splitlines()
    assert lines[0] == 'Insanely solvated protein.'
    assert lines[-1].split()[:3] == ['5.00000', '5.00000', '5.00000']
    assert result['molecules']['W'] > 0
    assert (tmp_path / 'solvated.gro').read_text().count(' W ') > 0
    rows = [line.split() for line in topology.read_text().splitlines() if line.split()]
    assert ['W', str(result['molecules']['W'])] in rows
    assert 'DDM 1' in topology.read_text()
    assert not (tmp_path / 'solvated.insane.top').exists()
