"""Snapshots: the picture and the numbers it was drawn with, in one record.

The design note says a snapshot is derived, that the initial state is always recorded, and that a gallery must not
be able to disagree with a verdict. These tests pin the three: the PDB's beads, the index's record, and that
re-deriving a snapshot replaces its entry rather than accumulating copies of it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.execution.scripts import pdc_snapshot
from tests.dashboard.support import DDM_BEADS, DDM_BONDS, DDM_CONSTRAINTS, ddm_moleculetype


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


def test_the_cadence_comes_from_the_settings_and_stops_at_the_phases_end():
    assert pdc_snapshot.sample_times(100, 10, 20) == [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert pdc_snapshot.sample_times(100, 10, 3) == [10, 20, 30], 'the cap is what keeps a long run readable'
    assert pdc_snapshot.sample_times(5, 10, 20) == [], 'a phase shorter than the interval has no frames to record'
    for arguments, message in (((100, 0, 20), 'interval'), ((100, 10, 0), 'cap')):
        with pytest.raises(ValueError, match=message):
            pdc_snapshot.sample_times(*arguments)


def test_each_frame_is_dumped_judged_and_indexed(tmp_path, monkeypatch):
    """The dump is exercised through a stand-in for gmx; the verdict is the real criterion on a real file."""
    import subprocess

    molecule = tmp_path / 'molecules' / 'DDM'
    molecule.mkdir(parents=True)
    (molecule / 'micelle_template.json').write_text(json.dumps({
        'name': 'DDM', 'residue': 'DDM', 'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'}]}))
    settings = {'project_root': str(tmp_path), 'template': 'molecules/DDM/micelle_template.json',
                'tail_beads': ['TAIL1'], 'aggregation_number': 2, 'contact_nm': 0.6,
                'assessment_ns': 30, 'extension_ns': 900, 'snapshot_interval_ns': 10, 'snapshot_cap': 20}
    stage = tmp_path / 'stage'
    stage.mkdir()
    dumped = {'times': []}

    def fake_run(command, **kwargs):
        dumped['times'].append(float(command[command.index('-dump') + 1]))
        Path(command[command.index('-o') + 1]).write_text('\n'.join([
            'system', '4',
            gro_line(1, 'PRO', 'B01', 1, (0.0, 0.0, 0.0)),
            gro_line(1, 'PRO', 'B02', 2, (0.5, 0.0, 0.0)),
            gro_line(2, 'DDM', 'TAIL1', 3, (0.2, 0.0, 0.0)),
            gro_line(3, 'DDM', 'TAIL1', 4, (0.3, 0.0, 0.0)),
            '   6.00000   6.00000   6.00000']) + '\n')
        return None

    monkeypatch.setattr(subprocess, 'run', fake_run)
    records = pdc_snapshot.frames(stage, stage / 'prod' / 'whole.xtc', stage / 'prod' / 'run.tpr',
                                  settings, phase='assessment')

    assert dumped['times'] == [10.0, 20.0, 30.0]
    assert [record['name'] for record in records] == ['assessment_10ps', 'assessment_20ps', 'assessment_30ps']
    assert all(record['verdict']['largest_cluster'] == 2 for record in records)
    document = json.loads((stage / pdc_snapshot.INDEX_NAME).read_text())
    assert len(document['snapshots']) == 3
    assert (stage / 'snapshots' / 'assessment_20ps.pdb').is_file()


def test_a_phase_shorter_than_the_cadence_still_records_its_start(tmp_path, monkeypatch):
    """The note's rule: the initial state is always recorded.

    Measured: a 2 ns assessment on a 20 ns cadence sampled no moment at all, so the phase wrote no picture and said
    so only by recording a zero. A phase that ends before its first cadence moment still has a beginning, and the
    stage writes that frame just before asking for the series.
    """
    stage = tmp_path / 'stage'
    (stage / 'prod').mkdir(parents=True)
    gro_file(stage / 'prod' / 'start.gro', [(1, 'DDM', 'B01', (0.0, 0.0, 0.0)),
                                            (1, 'DDM', 'B02', (0.47, 0.0, 0.0))])

    verdict = {'verdict': 'in_micelle', 'largest_cluster': 6, 'aggregation_number': 6,
               'fraction_of_requested': 1.0, 'protein_contact_count': 0, 'reasons': []}
    monkeypatch.setattr('dashboard.execution.scripts.pdc_assess.judge',
                        lambda structure, settings: {'verdict': verdict, 'detergent_residue': 'DDM'})

    settings = {'assessment_ns': 2, 'extension_ns': 2, 'snapshot_interval_ns': 20.0, 'snapshot_cap': 20}
    records = pdc_snapshot.frames(stage, stage / 'prod' / 'whole.xtc', stage / 'prod' / 'run.tpr',
                                  settings, phase='assessment')

    assert [record['name'] for record in records] == ['assessment_start']
    assert records[0]['time_ps'] == 0.0
    assert records[0]['verdict']['verdict'] == 'in_micelle', 'the start is judged like any other frame'
    assert (stage / 'snapshots' / 'assessment_start.pdb').is_file()


def test_the_script_does_something_when_it_is_run_as_a_script():
    """It is copied into a stage and called as `python pdc_snapshot.py ...`; without a `__main__` guard it exits 0
    having done nothing at all.

    Measured: two stages recorded no snapshot and said nothing, and the reason was not the cadence and not the tail
    beads -- the file simply had no entry point, so the call was a silent no-op. It is the only script of the five
    the pdc stages run that lacked one.
    """
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[3]
    script = root / 'dashboard/execution/scripts/pdc_snapshot.py'
    # The stage runs it with the repository on the path -- its own prelude sets that -- so the test does too.
    result = subprocess.run([sys.executable, str(script), '--help'], capture_output=True, text=True,
                            env={**os.environ, 'PYTHONPATH': str(root)})

    assert result.returncode == 0, result.stderr
    assert '--phase' in result.stdout, f'a script with no entry point prints nothing: {result.stdout!r}'


def test_a_phase_says_what_it_started_from(tmp_path):
    """Measured: the assessment phase recorded its start and the extension phase recorded nothing.

    The fallback looked for `prod/start.gro`, which the assessment path writes and the restart path never does -- it
    begins from the rebuilt system -- so the extension's series came back empty. A phase can now name its own start.
    """
    from dashboard.execution.scripts import pdc_snapshot

    stage = tmp_path / '4_extension'
    (stage / 'prod').mkdir(parents=True)
    rebuilt = stage / 'system.gro'
    rebuilt.write_text('rebuilt\n')
    (stage / 'prod' / 'start.gro').write_text('the assessment path leaves one of these\n')

    assert pdc_snapshot.start_structure(stage, rebuilt) == rebuilt
    assert pdc_snapshot.start_structure(stage) == stage / 'prod' / 'start.gro'
    assert pdc_snapshot.start_structure(tmp_path / 'nowhere') is None


def test_the_extension_script_names_the_structure_it_started_from():
    """The restart path rebuilds the system, so the script has to say so; `prod/start.gro` is not there to find."""
    root = Path(__file__).resolve().parents[3]
    text = (root / 'dashboard/execution/scripts/pdc_extension.sh').read_text()

    assert '--start system.gro' in text, 'the extension phase would record no start frame'


def beads(molecules: int):
    """`molecules` detergents of eleven beads, in the moleculetype's order, each its own residue number."""
    return [(2 + molecule, 'DDM', name, (molecule * 3.0 + index * 0.3, 0.0, 0.0))
            for molecule in range(molecules) for index, name in enumerate(DDM_BEADS)]


def conect_pairs(lines) -> list[tuple[int, int]]:
    """The CONECT records of a PDB, as the bead serials they join."""
    return [(int(line[6:11]), int(line[11:16])) for line in lines if line.startswith('CONECT')]


def test_the_picture_gives_every_detergent_its_own_residue_and_the_models_own_bonds(tmp_path):
    """Two claims about the file a viewer reads, both measured against what a reader saw.

    Measured: the placement PDB wrote six detergents as *one* residue with no CONECT records, so the file itself
    said "one molecule" and NGL -- which guesses bonds from interatomic distances when a file carries none -- drew
    90 bonds on a frame the model bonds 60 ways, head beads onto tail beads among them. The residue number now
    separates the molecules, and the moleculetype's own ten bonds per molecule are written as CONECT records.
    """
    stage = tmp_path / '1_system'
    stage.mkdir()
    (stage / 'detergent_CG.itp').write_text(ddm_moleculetype())
    structure = gro_file(stage / 'system.gro', beads(3))

    record = pdc_snapshot.write_snapshot(stage, 'placement', structure, title='placed system')
    lines = (stage / record['pdb']).read_text().splitlines()

    residues = {line[22:26].strip() for line in lines if line.startswith('HETATM')}
    assert len(residues) == 3, f'the file still says one molecule: residue numbers {sorted(residues)}'
    assert len(conect_pairs(lines)) == 3 * 10, 'ten bonds per detergent: four [ bonds ] and six [ constraints ]'
    expected = [pair for molecule in range(3)
                for first, second in (*DDM_BONDS, *DDM_CONSTRAINTS)
                for pair in [(molecule * 11 + first, molecule * 11 + second)]]
    assert sorted(conect_pairs(lines)) == sorted(expected), 'the records are not the moleculetype\'s bonds'
    assert [line for line in lines if line.startswith('CONECT')][0] == 'CONECT    1   11'
    assert any('ELEMENTS ARE RADIUS STAND-INS' in line for line in lines)
    assert any("BONDS ARE THE MODEL'S OWN" in line and '[ constraints ]' in line for line in lines), \
        'the remarks have to say where the bonds came from'


def test_a_phase_that_only_judges_takes_the_topology_from_the_runs_other_stages(tmp_path):
    """Measured: `3_assessment` and `5_assessment` hold the snapshot script and write a picture of their phase,
    but the stage declaration copies `detergent_CG.itp` only into the stages that simulate. A search of the stage
    alone would leave those pictures with no bonds in them at all.
    """
    run = tmp_path / 'run'
    (run / '1_system').mkdir(parents=True)
    (run / '1_system' / 'detergent_CG.itp').write_text(ddm_moleculetype())
    stage = run / '3_assessment'
    stage.mkdir()

    record = pdc_snapshot.write_snapshot(stage, '3_assessment', gro_file(stage / 'system.gro', beads(2)),
                                         title='assessed')
    lines = (stage / record['pdb']).read_text().splitlines()

    assert len(conect_pairs(lines)) == 2 * 10


def test_a_run_with_no_topology_says_so_rather_than_leaving_a_viewer_to_invent_them(tmp_path):
    stage = tmp_path / 'run' / '1_system'
    stage.mkdir(parents=True)

    record = pdc_snapshot.write_snapshot(stage, 'placement', gro_file(stage / 'system.gro', beads(2)),
                                         title='placed system')
    text = (stage / record['pdb']).read_text()

    assert not conect_pairs(text.splitlines()), 'a bond nothing declares is a bond the picture invented'
    assert 'NO BONDS RECORDED' in text
    assert 'ELEMENTS ARE RADIUS STAND-INS' in text


def test_a_structure_whose_beads_are_not_the_moleculetype_is_left_unbonded(tmp_path):
    """A picture is not worth failing a stage over, and a bond drawn between the wrong beads is worse than none."""
    stage = tmp_path / '1_system'
    stage.mkdir()
    (stage / 'detergent_CG.itp').write_text(ddm_moleculetype())
    structure = gro_file(stage / 'system.gro', [(2, 'DDM', name, (index * 0.3, 0.0, 0.0))
                                                for index, name in enumerate(DDM_BEADS[:4], 1)])

    record = pdc_snapshot.write_snapshot(stage, 'placement', structure, title='placed system')
    text = (stage / record['pdb']).read_text()

    assert not conect_pairs(text.splitlines())
    assert 'NO BONDS RECORDED' in text
