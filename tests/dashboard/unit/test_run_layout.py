"""Two stage layouts, resolved by role rather than guessed at."""
import pytest

from dashboard.analysis.runs import layout


def write(root, *paths):
    for path in paths:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('x')


def test_an_aa_only_run_publishes_its_reference_under_07(tmp_path):
    write(tmp_path, 'stages/07_reference/lig.xtc', 'stages/07_reference/lig.gro')
    assert layout.resolve(tmp_path, 'aa_trajectory') == tmp_path / 'stages/07_reference/lig.xtc'
    assert layout.resolve(tmp_path, 'aa_structure') == tmp_path / 'stages/07_reference/lig.gro'


def test_a_cg_consumer_reads_the_atomistic_reference_it_prepared(tmp_path):
    write(tmp_path, 'stages/1_AA-reference/prod/lig.xtc', 'stages/1_AA-reference/prod/lig.gro')
    assert layout.resolve(tmp_path, 'aa_trajectory') == tmp_path / 'stages/1_AA-reference/prod/lig.xtc'
    assert layout.resolve(tmp_path, 'aa_structure') == tmp_path / 'stages/1_AA-reference/prod/lig.gro'


def test_a_cg_consumer_resolves_its_mapped_and_coarse_grained_trajectories(tmp_path):
    write(tmp_path, 'stages/2_mapping/mapped.xtc', 'stages/2_mapping/mapped.gro',
          'stages/4_CG_sim/prod/lig_CG.xtc', 'stages/4_CG_sim/prod/lig_CG.gro')
    assert layout.resolve(tmp_path, 'mapped_trajectory').name == 'mapped.xtc'
    assert layout.resolve(tmp_path, 'mapped_structure').name == 'mapped.gro'
    assert layout.resolve(tmp_path, 'cg_trajectory').name == 'lig_CG.xtc'
    assert layout.resolve(tmp_path, 'cg_structure').name == 'lig_CG.gro'


def test_a_missing_role_names_every_path_it_looked_for(tmp_path):
    with pytest.raises(ValueError) as error:
        layout.resolve(tmp_path, 'cg_trajectory')
    message = str(error.value)
    assert '4_CG_sim/prod/lig_CG.xtc' in message and 'no cg_trajectory' in message


def test_a_run_holding_both_layouts_is_refused_rather_than_chosen(tmp_path):
    write(tmp_path, 'stages/07_reference/lig.xtc', 'stages/1_AA-reference/prod/lig.xtc')
    with pytest.raises(ValueError, match='more than one aa_trajectory'):
        layout.resolve(tmp_path, 'aa_trajectory')


def test_an_unknown_role_is_refused_with_the_known_ones(tmp_path):
    with pytest.raises(ValueError, match='Unknown run role'):
        layout.resolve(tmp_path, 'cg_trajectoryy')


def test_the_cg_topology_is_found_by_its_residue_name(tmp_path):
    write(tmp_path, 'stages/3_initial_CG/SUCR_initial.itp')
    assert layout.cg_topology(tmp_path).name == 'SUCR_initial.itp'


def test_a_system_topology_beside_it_is_not_taken_for_the_molecule(tmp_path):
    write(tmp_path, 'stages/3_initial_CG/SUCR_initial.itp', 'stages/3_initial_CG/system_EMPTY.top')
    assert layout.cg_topology(tmp_path).name == 'SUCR_initial.itp'


def test_two_candidate_topologies_are_refused_rather_than_ranked(tmp_path):
    write(tmp_path, 'stages/3_initial_CG/SUCR_initial.itp', 'stages/3_initial_CG/LIG.itp')
    with pytest.raises(ValueError, match='more than one CG molecule topology'):
        layout.cg_topology(tmp_path)


def test_a_topology_that_is_absent_says_so_with_the_glob(tmp_path):
    with pytest.raises(ValueError, match='3_initial_CG'):
        layout.cg_topology(tmp_path)


def test_the_summary_reports_absences_as_data_rather_than_raising(tmp_path):
    write(tmp_path, 'stages/07_reference/lig.xtc', 'stages/common/molecule/molecule.itp')
    report = layout.summary(tmp_path)
    assert report['aa_trajectory'] == 'stages/07_reference/lig.xtc'
    assert report['solute_topology'] == 'stages/common/molecule/molecule.itp'
    assert report['cg_trajectory'] is None and report['cg_topology'] is None
    assert set(report) == set(layout.CANDIDATES) | {'cg_topology'}
