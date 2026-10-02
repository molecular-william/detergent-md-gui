"""BARTENDER's fit as an analysis: the two reconciliations, the invocation, and the target it is judged against.

The parts tested here are the ones that were wrong when done by hand the first time. The topology has to be renumbered
to its physical beads, because the exporter's `.ndx` and the generated topology number the molecule differently once
ring virtual sites are involved. The fitted parameter file has to be read by accumulating sections, because BARTENDER
writes `[ angles ]` twice and a parser that resets on the repeated header silently drops the fitted angles. And the
comparison has to be against the reference's *ensemble*, because a single frame is what made the same fit look 5% off
a pair it was 1.4% off.

Nothing here runs BARTENDER: what it would be asked to do is pinned in `bartender_command`.
"""
from __future__ import annotations

import MDAnalysis as mda
import pytest

from dashboard.analysis.runs import bartender_fit

BEADS = [
    {'name': 'R1', 'atoms': [1, 2], 'type': 'SP1r', 'size': 'S'},
    {'name': 'R2', 'atoms': [3], 'type': 'SP1r', 'size': 'S'},
    {'name': 'R3', 'atoms': [4], 'type': 'SN6', 'size': 'S'},
    {'name': 'VS', 'virtual_site': {'function': 1, 'parents': ['R1', 'R2', 'R3']}, 'type': 'TC4'},
    {'name': 'TAIL', 'atoms': [5], 'type': 'C1', 'size': 'R'},
]

TOPOLOGY = """; a draft
[ moleculetype ]
MOL 1

[ atoms ]
1 SP1r 1 MOL R1 1 0 54
2 SP1r 1 MOL R2 2 0 54
3 SN6 1 MOL R3 3 0 54
4 TC4 1 MOL VS 4 0 0
5 C1 1 MOL TAIL 5 0 72

[ constraints ]
1 2 1 0.310
1 3 1 0.359
2 3 1 0.299

[ bonds ]
1 5 1 0.528 394.25

[ virtual_sitesn ]
4 1 1 2 3

[ exclusions ]
4 1 2 3
"""


def test_the_topology_is_renumbered_to_its_physical_beads_and_the_virtual_site_goes():
    text, names = bartender_fit.physical_topology(TOPOLOGY, BEADS)

    assert names == ['R1', 'R2', 'R3', 'TAIL'], 'the virtual site is not a bead BARTENDER can fit'
    assert 'virtual_sitesn' not in text, 'and its section goes with it'
    assert ' 5 ' not in text.split('[ atoms ]')[1].split('[')[0], 'TAIL is bead 4 now, not 5'
    assert '4 1 2 3' not in text, 'the exclusion row named the virtual site, which no longer exists'
    assert '1 4 1 0.528' in text, 'the junction bond moves from bead 1-5 to bead 1-4'


def test_the_fitted_terms_accumulate_because_bartender_writes_angles_twice():
    """Measured: a parser that reset on the repeated header dropped all fourteen fitted angles, and the fit ran on
    without them."""
    text = ('; Topology by Bartender\n[bonds]\n; i j funct length force.c.\n'
            '  1 9   1      0.528       394.25 ; rmsd:     1.74\n'
            '[constraints]\n  1 2   1      0.310     262033.76 ; rmsd:     0.36\n'
            '[angles]\n  2     1       3          1     52.42   2154.81 ; rmsd:     2.63\n'
            '[angles]\n; ReB\n;;  2     1       3          2     52.55   3357.88\n'
            '[dihedrals]\n  2     4       6    5          1     -408.38      7.30   4 ; rmsd:     0.81\n')

    terms = bartender_fit.fitted_terms(text)

    assert len(terms['angles']) == 1, 'the fitted angle survives its section being written twice'
    assert len(terms['bonds']) == 1 and len(terms['constraints']) == 1 and len(terms['dihedrals']) == 1
    assert bartender_fit.ring_lengths(terms) == {'1-2': 0.310}


def test_the_invocation_fits_from_the_runs_own_trajectory(tmp_path):
    command = bartender_fit.bartender_command(tmp_path / 'bartender', 4)

    assert '-refit' in command, 'fit the bonded parameters rather than running its own sampling'
    assert command[command.index('-owntraj') + 1] == bartender_fit.TRAJECTORY
    assert '-noplot' in command, 'a headless analysis has nowhere to put a plot'
    assert command[command.index('-cpus') + 1] == '4'
    assert command[-2:] == ['solute_heavy.gro', bartender_fit.INPUT_FILE], 'geometry then input file'


def write_frames(path, frames):
    """A .gro and an .xtc of the same beads, so the ensemble is measured the way the analysis measures it."""
    universe = mda.Universe.empty(3, trajectory=True)
    universe.add_TopologyAttr('name', ['A', 'B', 'C'])
    universe.add_TopologyAttr('resname', ['LIG'])
    universe.add_TopologyAttr('resid', [1])
    gro = path / 'lig.gro'
    universe.atoms.positions = frames[0]
    universe.atoms.write(str(gro))
    universe.trajectory = mda.coordinates.memory.MemoryReader(frames, order='fac')
    with mda.Writer(str(path / 'lig.xtc'), n_atoms=3) as writer:
        for _ in universe.trajectory:
            writer.write(universe.atoms)
    return gro, path / 'lig.xtc'


def test_the_target_is_the_ensemble_and_not_one_frame(tmp_path):
    import numpy as np

    frames = np.array([[[0.0, 0.0, 0.0], [3.0, 0.0, 0.0], [3.0, 3.0, 0.0]],
                       [[0.0, 0.0, 0.0], [3.2, 0.0, 0.0], [3.0, 3.0, 0.0]],
                       [[0.0, 0.0, 0.0], [2.8, 0.0, 0.0], [3.0, 3.0, 0.0]]], dtype=np.float32)
    structure, trajectory = write_frames(tmp_path, frames)
    beads = [{'name': 'A', 'atoms': [1]}, {'name': 'B', 'atoms': [2]}, {'name': 'C', 'atoms': [3]}]

    ensemble = bartender_fit.ensemble_distances(structure, trajectory, beads)

    assert ensemble['A-B']['frames'] == 3
    assert ensemble['A-B']['mean_nm'] == pytest.approx(0.30, abs=0.005), 'the mean, not the first frame'
    assert ensemble['A-B']['sd_nm'] > 0.0
    assert ensemble['B-C']['mean_nm'] == pytest.approx(np.hypot(0.0, 0.3), abs=0.01)


def test_a_run_without_an_atomistic_reference_is_refused(tmp_path):
    with pytest.raises(ValueError, match='does not carry what a fit needs'):
        bartender_fit.run(tmp_path, {})


def test_the_model_is_chosen_and_not_the_first_itp_in_the_directory(tmp_path):
    """A stage directory holds the reference the mapping was fitted against, a coordinate seed, and the model.

    Measured: taking the first by name picked a seed, and the fit then ran against a different parameter set -- only
    visible by comparing the input it built (8 angles, one row written as an improper) with the one that works
    (14 angles, a proper dihedral). The fitted interaction topology is the model the CG simulation was built from.
    """
    seed = tmp_path / 'LIG1_coordinate_seed.itp'
    initial = tmp_path / 'LIG1_initial.itp'
    model = tmp_path / 'LIG1_ff_inter.itp'
    reference = tmp_path / 'reference_sugars_v2.itp'
    for path in (seed, initial, model, reference):
        path.write_text('[ moleculetype ]\nLIG1 1\n')

    chosen = bartender_fit.model_topology([reference, seed, initial, model])

    assert chosen == model, chosen
    assert bartender_fit.model_topology([seed, initial]).name == 'LIG1_initial.itp', 'the seed is the last resort'
    assert bartender_fit.model_topology([]) is None


def test_the_fit_runs_through_the_tools_own_environment_file(tmp_path):
    """Measured: the same command took one minute in a shell and ten under an analysis, because the shell had sourced
    `bartender_config.sh` and the analysis had not. The flags were identical; the environment was the difference."""
    command = bartender_fit.shell_command(tmp_path / 'bartender', 2, tmp_path)

    assert command[0] == 'bash' and 'bartender_config.sh' in command[-1]
    assert 'exec ' in command[-1] and '-refit' in command[-1], 'the fit runs inside the sourced environment'
