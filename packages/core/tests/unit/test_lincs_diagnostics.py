"""The LINCS warning reader: the log's atom numbers, the written frame, and the neighbourhood it measures."""
from __future__ import annotations

import pytest
from dashboard.analysis.runs import lincs

LOG = """Step 768688, time 23060.6 (ps)  LINCS WARNING
relative constraint deviation after LINCS:
rms 0.013671, max 0.490974 (between atoms 2 and 3)
bonds that rotated more than 30 degrees:
 atom 1 atom 2  angle  previous, current, constraint length
    1    2   42.3    0.3301   0.4920      0.3300
    2    3   70.5    0.3301   0.4920      0.3300
    2    3   70.5    0.3301   0.4920      0.3300

Step 768689, time 23060.7 (ps)  LINCS WARNING
relative constraint deviation after LINCS:
rms 19.1, max 371.9 (between atoms 2 and 3)
bonds that rotated more than 30 degrees:
 atom 1 atom 2  angle  previous, current, constraint length
    2    3   126.7    0.4920 114.6050      0.3300
Wrote pdb files with previous and current coordinates

Fatal error:
Too many LINCS warnings (1556)
"""


def pdb(positions):
    lines = []
    for serial, (name, residue, resid, xyz) in enumerate(positions, 1):
        x, y, z = xyz
        lines.append(f'ATOM  {serial:5d} {name:>4s} {residue:>3s} A{resid:4d}    '
                     f'{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00')
    return '\n'.join(lines) + '\n'


POSITIONS = [('BB', 'LEU', 162, (0.0, 0.0, 0.0)), ('BB', 'PHE', 163, (3.3, 0.0, 0.0)),
             ('BB', 'GLU', 164, (6.6, 0.0, 0.0)), ('SC1', 'GLU', 164, (6.6, 3.0, 0.0)),
             ('BB', 'ASP', 165, (8.5, 0.0, 0.0)), ('W', 'W', 1, (5.3, 3.0, 0.0))]


def test_a_warning_block_keeps_its_pair_and_one_row_per_bond():
    warnings = lincs.warnings_from_log(LOG)

    assert [warning['step'] for warning in warnings] == [768688, 768689]
    first = warnings[0]
    assert first['max_deviation'] == pytest.approx(0.490974)
    assert first['atoms'] == [2, 3]
    assert len(first['bonds']) == 2, 'the repeated bond line is one bond'
    assert first['bonds'][1]['current_nm'] == pytest.approx(0.4920)
    assert lincs.fatal_warnings(LOG) == 1556


def test_the_written_frame_names_the_atoms_the_warning_names(tmp_path):
    stage = tmp_path / 'stages' / '06_assessment'
    stage.mkdir(parents=True)
    (stage / 'step768689b.pdb').write_text(pdb(POSITIONS))
    (stage / 'step768689c.pdb').write_text(pdb(POSITIONS))
    warning = lincs.warnings_from_log(LOG)[1]

    frames = lincs.frames_for(stage, warning['step'])
    assert set(frames) == {'initial', 'constrained'}
    atoms = lincs.read_pdb(frames['initial'])
    named = lincs.identities(atoms, [2, 3, 5])

    assert named[2]['residue'] == 'PHE' and named[2]['residue_id'] == '163'
    assert named[5]['name'] == 'BB' and named[5]['residue'] == 'ASP'
    assert lincs.frames_for(stage, 768688) == {}, 'a step with no written pair reports none'


def test_the_neighbourhood_marks_the_short_contact_and_keeps_bonds_separate():
    # Build the same frame the route reads, without a file: the reader is one function over a mapping.
    atoms = {serial: {'serial': serial, 'name': name, 'residue': residue, 'residue_id': str(resid),
                      'position_nm': [value / 10 for value in xyz]}
             for serial, (name, residue, resid, xyz) in enumerate(POSITIONS, 1)}
    warning = lincs.warnings_from_log(LOG)[1]

    rows = lincs.neighbours(atoms, warning['atoms'], warning['bonds'])

    short = [row for row in rows if row['short']]
    assert short, rows
    assert short[0]['atom'] in (2, 3) and short[0]['other'] == 5
    assert short[0]['distance_nm'] == pytest.approx(0.19, abs=0.01)
    kinds = {(row['atom'], row['other']): row['kind'] for row in rows}
    assert kinds[(2, 3)] == 'bonded'
    assert kinds[(2, 6)] == 'solvent'
