"""The coarse-grained reader, against a run the test builds and a geometry it knows the answer to.

No coarse-grained run exists in the developer's workspace, and a test that needed one would be testing that
workspace. This builds a four-bead system with known coordinates, so the measured distance is arithmetic the
test can check, and the refusal cases are constructed rather than waited for.
"""
import MDAnalysis as mda
import numpy as np
import pytest

from dashboard.analysis.runs import consistency

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
#: sqrt(0.32) = 0.56569 nm, which is what the test asserts against.
POSITIONS = [[0.0, 0.0, 0.0], [0.4, 0.0, 0.0], [0.0, 0.4, 0.0], [0.0, 0.0, 0.0]]


def topology_text(names=('A', 'B', 'C', 'VS'), extra_atom=False):
    rows = [f'{index} {"TC4" if name == "VS" else "SP1r"} 1 SUCR {name} {index} 0 '
            f'{"0" if name == "VS" else "54"}' for index, name in enumerate(names, 1)]
    if extra_atom:
        rows.append('5 SP1r 1 SUCR D 5 0 54')
    return ('[ moleculetype ]\nSUCR 1\n\n[ atoms ]\n' + '\n'.join(rows)
            + '\n\n[ constraints ]\n1 2 1 0.46\n1 3 1 0.54\n2 3 1 0.41\n')


def gro_text(names=('A', 'B', 'C', 'VS'), positions=None):
    positions = positions or POSITIONS
    lines = ['coarse-grained fixture', f'{len(names):5d}']
    for index, (name, xyz) in enumerate(zip(names, positions), 1):
        lines.append(f"{1:5d}{'SUCR':<5}{name:>5}{index:5d}"
                     + ''.join(f'{value:8.3f}' for value in xyz))
    lines.append('   1.00000   1.00000   1.00000')
    return '\n'.join(lines) + '\n'


def build_run(root, names=('A', 'B', 'C', 'VS'), topology_names=None, extra_atom=False, frames=3,
              positions=None):
    """A minimal CG consumer: its topology, its structure and a trajectory of the known geometry."""
    positions = list(positions or POSITIONS)[:len(names)]
    (root / 'stages/3_initial_CG').mkdir(parents=True, exist_ok=True)
    (root / 'stages/3_initial_CG/SUCR_initial.itp').write_text(
        topology_text(topology_names or names, extra_atom=extra_atom))
    production = root / 'stages/4_CG_sim/prod'
    production.mkdir(parents=True, exist_ok=True)
    (production / 'lig_CG.gro').write_text(gro_text(names, positions))
    universe = mda.Universe.empty(len(names), trajectory=True)
    universe.atoms.positions = np.asarray(positions, dtype=float)
    with mda.Writer(str(production / 'lig_CG.xtc'), n_atoms=len(names)) as writer:
        for _ in range(frames):
            writer.write(universe)
    return root


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
    root = build_run(tmp_path, topology_names=('X', 'Y', 'Z', 'VS'))
    with pytest.raises(ValueError, match='does not describe this mapping'):
        consistency.cg_samples(root, MAPPING)


def test_a_topology_with_an_extra_bead_is_refused_rather_than_read(tmp_path):
    """The mapping's beads are all present, so the mismatch is caught by the count rather than the names."""
    root = build_run(tmp_path, extra_atom=True)
    with pytest.raises(ValueError, match='not the same system'):
        consistency.cg_samples(root, MAPPING)


def test_a_trajectory_of_the_wrong_bead_count_is_refused(tmp_path):
    root = build_run(tmp_path, names=('A', 'B', 'C'), topology_names=('A', 'B', 'C', 'VS'))
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


def test_the_expected_currency_is_the_mapping_order_without_virtual_sites():
    assert consistency.expected_currency(MAPPING) == {1: (1, 'A'), 2: (1, 'B'), 3: (1, 'C')}
