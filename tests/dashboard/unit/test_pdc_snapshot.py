"""Snapshots: the picture and the numbers it was drawn with, in one record.

The design note says a snapshot is derived, that the initial state is always recorded, and that a gallery must not
be able to disagree with a verdict. These tests pin the three: the PDB's beads, the index's record, and that
re-deriving a snapshot replaces its entry rather than accumulating copies of it.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard.execution.scripts import pdc_snapshot


def gro_line(residue_id: int, residue: str, name: str, serial: int, xyz) -> str:
    """One .gro atom line, in the fixed-width fields the format gives: 5, 5, 5, 5, then 3 x 8.3f."""
    return (f'{residue_id:5d}{residue[:5]:<5}{name[:5]:>5}{serial:5d}'
            f'{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}')


def gro_file(path: Path, atoms, box=(6.0, 6.0, 6.0)) -> Path:
    lines = ['system', str(len(atoms))]
    lines += [gro_line(residue_id, residue, name, index, xyz)
              for index, (residue_id, residue, name, xyz) in enumerate(atoms, 1)]
    lines.append(''.join(f'{value:10.5f}' for value in box))
    path.write_text('\n'.join(lines) + '\n')
    return path


def structure(tmp_path: Path) -> Path:
    return gro_file(tmp_path / 'system.gro', [
        (1, 'PRO', 'B01', (1.000, 0.000, 0.000)),
        (1, 'PRO', 'B02', (1.500, 0.000, 0.000)),
        (2, 'DDM', 'TAIL1', (3.000, 0.000, 0.000)),
        (2, 'DDM', 'HEAD', (3.500, 0.000, 0.000)),
        (9999, 'W', 'W', (4.000, 0.000, 0.000)),
    ])


def test_the_picture_holds_one_entry_per_bead_the_viewer_draws(tmp_path):
    record = pdc_snapshot.write_snapshot(tmp_path, 'placement', structure(tmp_path), title='placed system')
    lines = (tmp_path / record['pdb']).read_text().splitlines()

    beads = [line for line in lines if line.startswith('HETATM')]
    assert len(beads) == 4, 'the protein beads and the detergents; the water bead is not drawn'
    assert sum(' PRO ' in line for line in beads) == 2
    assert sum(' DET ' in line for line in beads) == 2
    assert lines[-1] == 'END'
    assert '10.000' in beads[0], 'positions are written in Angstrom, as PDB is'


def test_water_can_be_included_when_a_caller_asks_for_it(tmp_path):
    record = pdc_snapshot.write_snapshot(tmp_path, 'everything', structure(tmp_path), title='with solvent',
                                         include_water=True)

    beads = [line for line in (tmp_path / record['pdb']).read_text().splitlines() if line.startswith('HETATM')]
    assert len(beads) == 5


def test_the_index_is_the_record_and_carries_the_numbers_the_moment_was_judged_on(tmp_path):
    criterion = {'verdict': True, 'largest_cluster': 2, 'aggregation_number': 2, 'reasons': []}

    record = pdc_snapshot.write_snapshot(tmp_path, '2_assessment', structure(tmp_path), title='assessed',
                                         time_ps=100000.0, criterion=criterion)
    document = json.loads((tmp_path / pdc_snapshot.INDEX_NAME).read_text())

    assert [entry['name'] for entry in document['snapshots']] == ['2_assessment']
    assert record['verdict'] == criterion and record['time_ps'] == 100000.0
    assert record['atoms'] == 5 and record['water_and_ions'] is False
    assert record['source_sha256'] == pdc_snapshot.hashlib.sha256(structure(tmp_path).read_bytes()).hexdigest()
    assert 'derived' in document['note']


def test_re_deriving_a_snapshot_replaces_its_entry_rather_than_piling_up(tmp_path):
    pdc_snapshot.write_snapshot(tmp_path, 'placement', structure(tmp_path), title='first')
    pdc_snapshot.write_snapshot(tmp_path, 'placement', structure(tmp_path), title='second')
    pdc_snapshot.write_snapshot(tmp_path, 'start', structure(tmp_path), title='start')

    document = json.loads((tmp_path / pdc_snapshot.INDEX_NAME).read_text())

    assert [entry['name'] for entry in document['snapshots']] == ['placement', 'start']


def test_an_absent_index_is_an_empty_one_rather_than_an_error(tmp_path):
    document = pdc_snapshot.index(tmp_path)

    assert document['snapshots'] == [] and 'derived' in document['note']
