"""What a run offers to play, as segments: which legs merge, where a boundary is, and what is a duplicate copy.

A protein-detergent run rebuilds its system mid-run -- the removal path takes detergents out and re-solvates -- so its legs
are not one system. Measured on `00b9ae6db23f`: 11,708 atoms through NVT, NPT and the assessment, then 10,427 in the
extension, and the final assessment re-declares the extension's trajectory rather than writing a second one. The panel
cannot be asked to infer any of that from file names, so `segments` states it: `group` is the merge unit, a change of group
is a boundary, and a duplicate says which segment it repeats.
"""
from pathlib import Path

from dashboard.analysis.runs import layout, segments

GRO = 'system {count}\n{count:5d}\n    1DDM      S1A     1   0.100   0.200   0.300\n   8.00000   8.00000   8.00000\n'


def write(path: Path, text: str = '', size: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text else 'x' * size)
    return path


def pdc_run(root: Path) -> Path:
    """A run shaped like a protein-detergent one, with the real atom-count change and a re-declared trajectory."""
    write(root / '1_system/system.gro', GRO.format(count=8))
    write(root / '2_minimisation/system.gro', GRO.format(count=40))
    write(root / '3_nvt/system.gro', GRO.format(count=40))
    write(root / '3_nvt/system.xtc', size=120)
    write(root / '4_npt/system.gro', GRO.format(count=40))
    write(root / '4_npt/system.xtc', size=140)
    write(root / '2_assessment/prod/run.gro', GRO.format(count=40))
    write(root / '2_assessment/prod/whole.xtc', size=160)
    write(root / '4_extension/prod/run.gro', GRO.format(count=32))
    write(root / '4_extension/prod/whole.xtc', size=180)
    write(root / '4_extension/prod/run.xtc', size=90)
    write(root / '5_assessment/prod/run.gro', GRO.format(count=32))
    write(root / '5_assessment/prod/run.xtc', size=90, text='')  # the extension's raw file, byte for byte
    return root


def test_a_pdc_run_is_segments_with_the_atoms_each_one_holds(tmp_path):
    answer = segments.segments(pdc_run(tmp_path), 'pdc')

    assert answer['run_type'] == 'pdc' and answer['why'] is None
    names = [entry['name'] for entry in answer['segments']]
    assert names[0] == 'System preparation' and names[-1] == 'Final assessment', names
    by_name = {entry['name']: entry for entry in answer['segments']}
    assert by_name['System preparation']['atoms'] == 8 and by_name['System preparation']['trajectory'] is None
    assert by_name['CG extension MD']['atoms'] == 32


def test_legs_with_the_same_system_share_a_merge_group(tmp_path):
    """NVT, NPT and the assessment are one system: a player may concatenate them without switching anything."""
    answer = segments.segments(pdc_run(tmp_path), 'pdc')
    by_name = {entry['name']: entry for entry in answer['segments']}

    assert by_name['NVT equilibration']['group'] == by_name['NPT equilibration']['group']
    assert by_name['NPT equilibration']['group'] == by_name['CG assessment MD']['group']
    assert by_name['CG extension MD']['group'] != by_name['CG assessment MD']['group']
    assert by_name['CG assessment MD']['group'] is not None


def test_the_rebuilt_system_is_stated_as_a_boundary_with_both_atom_counts(tmp_path):
    answer = segments.segments(pdc_run(tmp_path), 'pdc')

    assert answer['boundaries'] == [{'at': 'CG extension MD', 'after': 'CG assessment MD',
                                     'atoms_from': 40, 'atoms_to': 32}]


def test_a_leg_that_re_declares_another_trajectory_is_not_a_segment(tmp_path):
    """The final assessment reads the extension's own file; a film that played it would repeat those frames."""
    answer = segments.segments(pdc_run(tmp_path), 'pdc')
    final = {entry['name']: entry for entry in answer['segments']}['Final assessment']

    assert final['duplicate_of'] == 'CG extension MD'
    assert final['group'] is None, 'a duplicate is not a merge unit'
    assert 'the same trajectory as CG extension MD' in final['note']
    playable = [entry for entry in answer['segments'] if entry.get('group') is not None]
    assert 'Final assessment' not in [entry['name'] for entry in playable]


def test_the_whole_box_trajectory_is_preferred_over_the_raw_one(tmp_path):
    """A raw frame shows molecules broken across the periodic boundary: a picture of the box, not of the system."""
    answer = segments.segments(pdc_run(tmp_path), 'pdc')
    by_name = {entry['name']: entry for entry in answer['segments']}

    assert by_name['CG assessment MD']['trajectory'].endswith('whole.xtc')
    assert by_name['CG extension MD']['trajectory'].endswith('whole.xtc')


def test_a_leg_with_no_trajectory_is_listed_for_its_structure_and_holds_no_group(tmp_path):
    """Minimisation writes no frames in this pipeline; the dry build never has any."""
    answer = segments.segments(pdc_run(tmp_path), 'pdc')
    by_name = {entry['name']: entry for entry in answer['segments']}

    assert by_name['Energy minimisation']['structure'].endswith('2_minimisation/system.gro')
    assert by_name['Energy minimisation']['trajectory'] is None
    assert by_name['Energy minimisation']['group'] is None, 'nothing to merge, so no merge unit'


def test_a_single_molecule_run_is_one_segment_from_the_layout(tmp_path):
    root = tmp_path / 'run'
    write(root / 'stages/4_CG_sim/prod/lig_CG.gro', GRO.format(count=12))
    write(root / 'stages/4_CG_sim/prod/lig_CG.xtc', size=64)

    answer = segments.segments(root, 'cg_composition')

    assert len(answer['segments']) == 1
    entry = answer['segments'][0]
    assert entry['atoms'] == 12 and entry['group'] == 1
    assert entry['trajectory'] == '4_CG_sim/prod/lig_CG.xtc', 'the stages/ prefix is not part of the run-relative path'


def test_a_run_with_nothing_to_play_says_why(tmp_path):
    root = tmp_path / 'run'
    write(root / '07_reference/lig.gro', GRO.format(count=4))

    answer = segments.segments(root, 'aa_only')

    assert answer['segments'] == [] and 'no trajectory' in answer['why']


def test_a_run_in_the_analysis_work_spelling_is_read_the_same_way(tmp_path):
    """An analysis subprocess is handed the same files at the work directory's root, not under `stages/`."""
    root = pdc_run(tmp_path / 'work')

    assert segments.is_pdc(root)
    assert len([entry for entry in segments.segments(root, None)['segments'] if entry['group']]) == 4


def test_the_layout_names_the_pdc_production_trajectory(tmp_path):
    """The run view reads its one trajectory through `layout`; a pdc run must not resolve as having none."""
    root = pdc_run(tmp_path)
    trajectory, structure, role = layout.frame_source(root)

    assert role == 'pdc_trajectory'
    assert trajectory.name == 'whole.xtc' and structure.name == 'run.gro'
