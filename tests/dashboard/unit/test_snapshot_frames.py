"""The frame producer reads the run's own layout, and the frames it writes hold real coordinates.

No run in the developer's workspace has a `snapshots/` directory, so a test that needed one would be a test of
that workspace. These build the two layouts a completed run is written in -- an AA-only run's `07_reference/` and
a CG consumer's `4_CG_sim/` -- and check the drawn atoms against the trajectory they came from rather than against
a file that happens to be present.
"""
import re

import MDAnalysis as mda
import numpy as np
import pytest

from dashboard.analysis.runs import layout, observability
from tests.dashboard import support


def _trajectory(directory, stem, frames, atoms=4):
    """`<stem>.gro` and a `<stem>.xtc` of `frames` frames whose coordinates are distinct and exact in nm.

    Positions are multiples of ten ångström, so the nanometres GROMACS writes are integers: a reader that mixes
    the two units cannot pass the coordinate assertions below on a rounded value that never moved.
    """
    directory.mkdir(parents=True, exist_ok=True)
    universe = mda.Universe.empty(atoms, n_residues=1, atom_resindex=[0] * atoms, trajectory=True)
    universe.add_TopologyAttr('names', [f'C{index:02d}' for index in range(1, atoms + 1)])
    universe.add_TopologyAttr('resnames', ['LIG'])
    universe.add_TopologyAttr('resids', [1])
    base = np.arange(atoms * 3, dtype=float).reshape(atoms, 3) * 10.0
    with mda.Writer(str(directory / f'{stem}.xtc'), n_atoms=atoms) as writer:
        for frame in range(frames):
            universe.atoms.positions = base + frame * 10.0
            if frame == 0:
                universe.atoms.write(str(directory / f'{stem}.gro'))
            writer.write(universe.atoms)
    return directory / f'{stem}.xtc'


def _aa_only_run(root, frames=5, atoms=4):
    _trajectory(root / 'stages/07_reference', 'lig', frames, atoms)
    return root


def _cg_stage_run(root, frames=6, atoms=4):
    """The measured older CG layout: the stage's own `eq`/`md` output, with no extracted solute beside it."""
    _trajectory(root / 'stages/4_CG_sim', 'eq', frames, atoms)
    _trajectory(root / 'stages/4_CG_sim', 'md', frames, atoms)
    return root


def _coordinates(path):
    """The xyz of every atom in a hand-written snapshot PDB, in file order."""
    rows = [line for line in path.read_text().splitlines() if line.startswith('ATOM')]
    return [[float(value) for value in re.findall(r'-?\d+\.\d{3}', line)[:3]] for line in rows]


def test_an_aa_only_run_publishes_frames_from_its_own_published_reference(tmp_path):
    """`07_reference/lig.xtc` is where an AA-only run keeps the trajectory; nothing names `1_AA-reference/`."""
    result = observability.generate(_aa_only_run(tmp_path), samples=3)

    assert result['frames'] == 5
    assert result['role'] == 'aa_trajectory'
    assert result['trajectory'] == 'stages/07_reference/lig.xtc'
    created = set(result['files'])
    assert {'AA-first.pdb', 'AA-first.svg', 'AA-middle.pdb', 'AA-middle.svg',
            'AA-last.pdb', 'AA-last.svg', 'AA-frames.pdb'} <= created
    assert all((tmp_path / 'snapshots' / name).is_file() for name in created)


def test_the_drawn_coordinates_are_the_trajectorys_own(tmp_path):
    """The frames are real: the first and last snapshots carry the coordinates of frame 0 and frame 4."""
    result = observability.generate(_aa_only_run(tmp_path, frames=5, atoms=4), samples=3)
    snapshots = tmp_path / 'snapshots'
    universe = mda.Universe(str(tmp_path / 'stages/07_reference/lig.gro'),
                            str(tmp_path / 'stages/07_reference/lig.xtc'))

    universe.trajectory[0]
    first = np.asarray(universe.atoms.positions)
    universe.trajectory[4]
    last = np.asarray(universe.atoms.positions)

    assert np.allclose(_coordinates(snapshots / 'AA-first.pdb'), first, atol=1e-2)
    assert np.allclose(_coordinates(snapshots / 'AA-last.pdb'), last, atol=1e-2)
    assert result['files']


def test_a_cg_run_is_read_at_the_cg_simulation_stage(tmp_path):
    """The measured layout: `4_CG_sim/{eq,md}.xtc`. The production `md.xtc` is preferred to the equilibration."""
    result = observability.generate(_cg_stage_run(tmp_path), samples=3)

    assert result['role'] == 'cg_stage_trajectory'
    assert result['trajectory'] == 'stages/4_CG_sim/md.xtc'
    assert {'CG-first.pdb', 'CG-first.svg', 'CG-last.pdb', 'CG-frames.pdb'} <= set(result['files'])
    assert not list((tmp_path / 'snapshots').glob('AA-*'))


def test_the_extracted_coarse_grained_solute_is_read_when_the_pipeline_wrote_one(tmp_path):
    """A current CG run also extracts the solute; that is the trajectory a frame should be drawn from."""
    positions = [[0.0, 0.0, 0.0], [0.4, 0.0, 0.0], [0.0, 0.4, 0.0], [0.0, 0.0, 0.4]]
    support.cg_fixture_run(tmp_path, positions, names=('B01', 'B02', 'B03', 'B04'), frames=4)

    result = observability.generate(tmp_path, samples=2)

    assert result['role'] == 'cg_trajectory'
    assert result['trajectory'] == 'stages/4_CG_sim/prod/lig_CG.xtc'


def test_the_series_names_its_sample_count_and_stride(tmp_path):
    """The panel plays one file, so the file has to say which frames it holds and how far apart they sat."""
    result = observability.generate(_aa_only_run(tmp_path, frames=200), samples=40)

    series = result['series']
    assert series['file'] == 'AA-frames.pdb'
    assert series['sampled'] == 40
    assert series['stride'] == 5
    text = (tmp_path / 'snapshots/AA-frames.pdb').read_text()
    assert text.count('MODEL') == 40
    assert sum(1 for line in text.splitlines() if line.startswith('ATOM')) == 40 * 4


def test_a_series_never_asks_for_more_frames_than_the_trajectory_has(tmp_path):
    result = observability.generate(_aa_only_run(tmp_path, frames=3), samples=40)

    assert result['series']['sampled'] == 3
    assert (tmp_path / 'snapshots/AA-frames.pdb').read_text().count('MODEL') == 3


def test_the_default_series_spreads_the_frames_it_was_asked_for():
    """No cadence asked for is the even spread, unchanged: the first frame, the last, and `samples` of them."""
    indices = observability._series_indices(200, 10.0, 40, None, observability.SERIES_CAP)

    assert len(indices) == 40
    assert indices[0] == 0 and indices[-1] == 199


def test_a_cadence_in_nanoseconds_is_honoured_in_frames():
    """5 ns at a 10 ps time step is every 500th frame of a real run's own trajectory.

    The numbers are the measured ones: `a2a457cf9413`'s `md.xtc` holds 20,001 frames at 10 ps (200 ns), so a 5 ns
    cadence is 41 frames and the record states 5.0 -- which is what the panel prints and the prompt names.
    """
    indices = observability._series_indices(20001, 10.0, 40, 5.0, observability.SERIES_CAP)

    assert len(indices) == 41
    assert indices[:3] == [0, 500, 1000] and indices[-1] == 20000
    assert observability._cadence_ns(indices, 10.0) == 5.0


def test_a_cadence_finer_than_the_cap_is_capped_and_still_states_its_cadence():
    """A series is one PDB a browser loads whole, so the cap binds and the record says what was drawn."""
    indices = observability._series_indices(20001, 10.0, 40, 1.0, observability.SERIES_CAP)

    assert len(indices) == observability.SERIES_CAP == 200
    assert indices[0] == 0
    assert observability._cadence_ns(indices, 10.0) == 1.0


def test_a_cadence_on_a_trajectory_with_no_time_step_is_refused():
    """A trajectory whose frames carry no time cannot honour nanoseconds: refused with that reason, not guessed."""
    with pytest.raises(ValueError, match='states no time step'):
        observability._series_indices(20, 0.0, 40, 5.0, observability.SERIES_CAP)


def test_the_series_record_states_its_own_cadence(tmp_path):
    """The record carries the cadence of the frames it published, which is what the note and the prompt print."""
    result = observability.generate(_aa_only_run(tmp_path, frames=200), samples=40)

    series = result['series']
    assert series['sampled'] == 40 and series['stride'] == 5
    # This fixture's trajectory carries no time step, so where a cadence cannot be known the record says so rather
    # than inventing one: `None` is what the panel prints as "its cadence was not recorded".
    assert series['frame_ps'] == 0.0 and series['interval_ns'] is None and series['duration_ns'] == 0.0
    assert series['requested_interval_ns'] is None


def _cg_run_with_bonds(root, frames=4, bonds=((1, 2), (2, 3), (3, 4))):
    """A CG run whose moleculetype states bonds, so a series has something to carry.

    `support.cg_fixture_run` writes the shape a CG run has -- its `stages/3_initial_CG` moleculetype, its structure
    and its trajectory -- and the moleculetype is given `[ bonds ]` here because the fixture's own carries none.
    """
    topology = ('; the run\'s own bonded draft\n[ moleculetype ]\nSUCR 1\n\n[ atoms ]\n'
                + '\n'.join(f'{index} SP1r 1 SUCR B0{index} {index} 0 54' for index in range(1, 5))
                + '\n\n[ bonds ]\n'
                + '\n'.join(f'{first} {second} 1 0.429374836245 5000' for first, second in bonds) + '\n')
    positions = [[0.0, 0.0, 0.0], [0.4, 0.0, 0.0], [0.8, 0.0, 0.0], [1.2, 0.0, 0.0]]
    support.cg_fixture_run(root, positions, frames=frames, topology=topology)
    return root


def test_a_cg_series_carries_the_family_code_and_the_models_own_bonds(tmp_path):
    """The two things the run view reads a bead from, per model, or the picture is grey spheres with no bonds.

    Measured on the first series this repository published: MDAnalysis's own PDB writer emitted b-factor `0.00` on
    every bead and no `CONECT` record, so the panel -- which draws a CG file with `bfactor` colours and its distance
    guess off -- showed neither the family nor the connectivity of the model it was drawing. The series must state
    both, in the same columns the run's own single-frame structure uses.
    """
    # No cadence is asked for: this fixture's trajectory carries no time step (a written XTC with no times), so a
    # cadence in nanoseconds would be refused -- which is the rule the neighbouring test holds.
    result = observability.generate(_cg_run_with_bonds(tmp_path, frames=4), samples=2)

    text = (tmp_path / 'snapshots/CG-frames.pdb').read_text()
    lines = text.splitlines()
    families = [line[60:66].strip() for line in lines if line.startswith('HETATM')]
    assert set(families) == {'3.00'}, f'the b-factor column is not the beads\' own family: {sorted(set(families))}'
    # 5001 bonds the model states ... the moleculetype in this fixture bonds it 3 ways, once per model.
    assert text.count('CONECT') == 3 * result['series']['sampled'], \
        f"the series carries {text.count('CONECT')} CONECT records for 3 bonds over {result['series']['sampled']} models"
    # Anchored to the line: "the MODEL'S own bonds" is a REMARK in this file, so a substring count is not a count
    # of models.
    assert len(re.findall(r'^MODEL', text, re.M)) == result['series']['sampled']
    assert any(line.startswith('REMARK 950 BONDS ARE THE MODEL\'S OWN') for line in lines)
    assert any('SAMPLED SERIES: 2 models' in line for line in lines), \
        'the file does not say how many models it holds'
    assert result['series']['topology'] and 'SUCR_initial.itp' in result['series']['topology']
    # The moments the strip's buttons jump to are written the same way: a reader landing on one sees the same beads.
    first = (tmp_path / 'snapshots/CG-first.pdb').read_text()
    assert first.count('CONECT') == 3, 'a single moment must carry the model\'s bonds too'
    assert {line[60:66].strip() for line in first.splitlines() if line.startswith('HETATM')} == {'3.00'}


def test_a_cg_series_with_no_moleculetype_says_it_has_no_bonds(tmp_path):
    """No topology is a state the file reports: the same conventions, and a REMARK instead of invented bonds."""
    root = tmp_path
    support.cg_fixture_run(root, [[0.0, 0.0, 0.0], [0.4, 0.0, 0.0]], names=('B01', 'B02'), frames=3)
    (root / 'stages/3_initial_CG/SUCR_initial.itp').unlink()

    observability.generate(root, samples=2)

    text = (root / 'snapshots/CG-frames.pdb').read_text()
    assert 'CONECT' not in text, 'a run that states no moleculetype must not be given bonds'
    assert any('NO BONDS RECORDED' in line for line in text.splitlines())


def test_an_all_atom_series_keeps_the_readers_own_records(tmp_path):
    """Real chemistry, not beads: the elements come from the atoms and the panel guesses the bonds it can see."""
    result = observability.generate(_aa_only_run(tmp_path, frames=5), samples=2)

    text = (tmp_path / 'snapshots/AA-frames.pdb').read_text()
    assert 'CONECT' not in text and 'REMARK 950 BONDS' not in text
    assert result['series']['topology'] is None


def test_a_run_with_no_trajectory_is_refused(tmp_path):
    """Refused as a value error, and as the resolver's own type: that is what a caller records a skip from."""
    with pytest.raises(layout.NoTrajectory, match='no trajectory to review'):
        observability.generate(tmp_path)


def test_an_unknown_label_is_refused(tmp_path):
    with pytest.raises(ValueError, match='Unknown snapshot label'):
        observability.generate(_aa_only_run(tmp_path), labels=('first', 'every'))
