"""The coarse-grained reader, against a run the test builds and a geometry it knows the answer to.

No coarse-grained run exists in the developer's workspace, and a test that needed one would be testing that
workspace. This builds a four-bead system with known coordinates, so the measured distance is arithmetic the
test can check, and the refusal cases are constructed rather than waited for.
"""
import numpy as np
import pytest
from detergent_validation.analysis.runs import consistency

from tests.harness import support

MAPPING = {
    'beads': [
        {'name': 'S1A', 'letter': 'A', 'residue': 1, 'size': 'S', 'type': 'SP1r', 'atoms': [1, 2]},
        {'name': 'S1B', 'letter': 'B', 'residue': 1, 'size': 'S', 'type': 'SP4r', 'atoms': [3, 4]},
        {'name': 'S1C', 'letter': 'C', 'residue': 1, 'size': 'S', 'type': 'SP1r', 'atoms': [5, 6]},
        {'name': 'S1VS', 'letter': 'VS', 'residue': 1, 'size': 'T', 'type': 'TC4', 'atoms': [],
         'virtual_site': {'parents': ['S1A', 'S1B', 'S1C'], 'function': 1}},
    ],
    'rings': [{'beads': ['S1A', 'S1B', 'S1C'], 'scale': 1.15}],
}

#: A at the origin, B 0.4 nm along x, C 0.4 nm along y: two pairs are exactly 0.4 nm and the third is
#: sqrt(0.32) = 0.56569 nm, which is what the test asserts against. Nanometres, as GROMACS writes them.
POSITIONS = [[0.0, 0.0, 0.0], [0.4, 0.0, 0.0], [0.0, 0.4, 0.0], [0.0, 0.0, 0.0]]


def topology_text(names=('B01', 'B02', 'B03', 'B04'), extra_atom=False):
    rows = [f'{index} {"TC4" if name == "VS" else "SP1r"} 1 SUCR {name} {index} 0 '
            f'{"0" if name == "VS" else "54"}' for index, name in enumerate(names, 1)]
    if extra_atom:
        rows.append('5 SP1r 1 SUCR D 5 0 54')
    return ('[ moleculetype ]\nSUCR 1\n\n[ atoms ]\n' + '\n'.join(rows)
            + '\n\n[ constraints ]\n1 2 1 0.46\n1 3 1 0.54\n2 3 1 0.41\n')


def build_run(root, names=('B01', 'B02', 'B03', 'B04'), topology_names=None, extra_atom=False, frames=3,
              positions=None):
    """A minimal CG consumer, built through the shared fixture, with the topology the case asks for."""
    positions = list(positions or POSITIONS)[:len(names)]
    run_dir, _, _, _ = support.cg_fixture_run(
        root, positions, names=names, frames=frames,
        topology=topology_text(topology_names or names, extra_atom=extra_atom))
    return run_dir


def test_a_known_geometry_is_measured_on_the_coarse_grained_trajectory(tmp_path):
    measured = consistency.cg_samples(build_run(tmp_path), MAPPING)
    assert measured['frames'] == 3
    samples = measured['samples']
    assert np.isclose(np.mean(samples[frozenset((1, 2))]), 0.4, atol=1e-4)
    assert np.isclose(np.mean(samples[frozenset((1, 3))]), 0.4, atol=1e-4)
    assert np.isclose(np.mean(samples[frozenset((2, 3))]), np.hypot(0.4, 0.4), atol=1e-4)


def test_the_first_frame_is_kept_beside_the_samples(tmp_path):
    measured = consistency.cg_samples(build_run(tmp_path), MAPPING)
    assert np.isclose(measured['first'][frozenset((1, 2))], 0.4, atol=1e-4)


def test_the_measured_pairs_are_the_ones_the_mapping_constrains(tmp_path):
    measured = consistency.cg_samples(build_run(tmp_path), MAPPING)
    assert sorted(tuple(sorted(pair)) for pair in measured['samples']) == [(1, 2), (1, 3), (2, 3)]


def test_the_run_and_the_files_it_read_are_recorded(tmp_path):
    measured = consistency.cg_samples(build_run(tmp_path), MAPPING)
    assert measured['trajectory'].endswith('4_CG_sim/prod/lig_CG.xtc')
    assert measured['topology'].endswith('3_initial_CG/SUCR_initial.itp')
    assert measured['beads'][1] == (1, 'A')


def test_a_topology_naming_other_beads_is_refused_rather_than_read(tmp_path):
    root = build_run(tmp_path, topology_names=('X', 'Y', 'Z', 'W'))
    with pytest.raises(ValueError, match='does not describe this mapping'):
        consistency.cg_samples(root, MAPPING)


def test_a_topology_using_the_reference_letters_is_refused(tmp_path):
    """The letters name two beads `A` in a two-residue sugar; a run's files say `B01..` instead.

    This is the mismatch that made `gmx grompp` count eight atom-name disagreements and refuse the CG
    topology stage, so the reader refuses it here first, with the reason.
    """
    root = build_run(tmp_path, topology_names=('A', 'B', 'C', 'VS'))
    with pytest.raises(ValueError, match='does not describe this mapping'):
        consistency.cg_samples(root, MAPPING)


def test_a_topology_with_an_extra_bead_is_refused_rather_than_read(tmp_path):
    """The mapping's beads are all present, so the mismatch is caught by the count rather than the names."""
    root = build_run(tmp_path, extra_atom=True)
    with pytest.raises(ValueError, match='not the same system'):
        consistency.cg_samples(root, MAPPING)


def test_a_trajectory_of_the_wrong_bead_count_is_refused(tmp_path):
    root = build_run(tmp_path, names=('B01', 'B02', 'B03'), topology_names=('B01', 'B02', 'B03', 'B04'))
    with pytest.raises(ValueError, match='not the same system'):
        consistency.cg_samples(root, MAPPING)


def test_a_missing_structure_names_the_path_it_looked_for(tmp_path):
    root = build_run(tmp_path)
    (root / 'stages/4_CG_sim/prod/lig_CG.gro').unlink()
    with pytest.raises(ValueError, match='lig_CG.gro'):
        consistency.cg_samples(root, MAPPING)


def test_stride_and_limit_take_the_frames_the_caller_asked_for(tmp_path):
    root = build_run(tmp_path, frames=6)
    assert consistency.cg_samples(root, MAPPING, limit=2)['frames'] == 2
    assert consistency.cg_samples(root, MAPPING, stride=2)['frames'] == 3


def test_the_expected_currency_is_the_run_own_bead_ids():
    """The run's files name beads by position; the mapping's letters are a separate reading."""
    assert consistency.expected_currency(MAPPING) == {1: (1, 'B01'), 2: (1, 'B02'), 3: (1, 'B03')}
    assert consistency.mapping_currency(MAPPING, physical_only=True) == {1: (1, 'A'), 2: (1, 'B'),
                                                                        3: (1, 'C')}
