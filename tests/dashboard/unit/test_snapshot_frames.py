"""The frame producer reads the run's own layout, and the frames it writes hold real coordinates.

No run in the developer's workspace has a `snapshots/` directory, so a test that needed one would be a test of
that workspace. These build the two layouts a completed run is written in -- an AA-only run's `07_reference/` and
a CG consumer's `4_CG_sim/` -- and check the drawn atoms against the trajectory they came from rather than against
a file that happens to be present.
"""
import json
import re
import shutil

import MDAnalysis as mda
import numpy as np
import pytest

from dashboard.analysis import worker
from dashboard.analysis.runs import layout, observability
from dashboard.execution import workflow
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


def test_the_producer_is_handed_the_moleculetype_it_draws_bonds_from(tmp_path):
    """The kind declares the moleculetype as a source, and the worker stages the manifest that names it.

    Measured: the first series this repository published carried neither bonds nor family codes for a run that has
    both, because a producer is handed a *staged* directory holding only the kind's declared sources -- the
    trajectory and its coordinates -- and the `.itp` the run simulated was not one of them, nor was the manifest
    where `FINAL_ITP` names it. This stages the way the worker does and holds the series that comes out.
    """
    root = tmp_path / 'run'
    topology = ('; the run\'s own bonded draft\n[ moleculetype ]\nSUCR 1\n\n[ atoms ]\n'
                + '\n'.join(f'{index} SP1r 1 SUCR B0{index} {index} 0 54' for index in range(1, 5))
                + '\n\n[ bonds ]\n1 2 1 0.429 5000\n2 3 1 0.429 5000\n3 4 1 0.429 5000\n')
    support.cg_fixture_run(root, [[0.0, 0.0, 0.0], [0.4, 0.0, 0.0], [0.8, 0.0, 0.0], [1.2, 0.0, 0.0]],
                           frames=3, topology=topology)
    # A run of this shape holds its own AA reference beside the CG half, which is what keeps the kind's declared
    # sources in play: without it `source_entries` falls to the legacy pair and stages nothing, which is a state no
    # completed run is in. The pair is a copy of the fixture's own, so it is a readable trajectory either way.
    reference = root / 'stages/1_AA-reference/prod'
    reference.mkdir(parents=True, exist_ok=True)
    for name in ('lig.gro', 'lig.xtc'):
        shutil.copy2(root / f'stages/4_CG_sim/prod/lig_CG.{name.split(".")[-1]}', reference / name)
    # The manifest a fitted run writes: `FINAL_ITP` is the one thing that says which `.itp` the simulation ran.
    (root / 'manifest.json').write_text(json.dumps({'run_type': 'aa_cg', 'stages': [
        {'name': 'CG simulation', 'environment': {'INITIAL_ITP': 'SUCR_initial.itp',
                                                 'FINAL_ITP': 'SUCR_initial.itp'}}]}))
    work = tmp_path / 'work'
    for relative, path in worker.source_entries(workflow.execution_root(root), 'snapshots').items():
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy2(root / 'manifest.json', work / 'manifest.json')

    result = observability.generate(work, samples=2)

    assert result['series']['topology'] and 'SUCR_initial.itp' in result['series']['topology'], \
        'the moleculetype was not staged, so the series cannot carry the model\'s bonds'
    text = (work / 'snapshots/CG-frames.pdb').read_text()
    assert text.count('CONECT') == 3 * result['series']['sampled']


#: A moleculetype with four beads and three bonds, for the runs the fitting tests build.
BONDED_TOPOLOGY = ('; the run\'s own bonded draft\n[ moleculetype ]\nSUCR 1\n\n[ atoms ]\n'
                   + '\n'.join(f'{index} SP1r 1 SUCR B0{index} {index} 0 54' for index in range(1, 5))
                   + '\n\n[ bonds ]\n1 2 1 0.429 5000\n2 3 1 0.429 5000\n3 4 1 0.429 5000\n')
BEADS_NM = [[0.0, 0.0, 0.0], [0.4, 0.0, 0.0], [0.8, 0.0, 0.0], [0.8, 0.4, 0.0]]


def _moving_run(root, transform, frames=4):
    """A CG run whose trajectory *moves* the molecule: one transform of the same beads per frame.

    `support.cg_fixture_run` writes a trajectory whose every frame holds the same coordinates, which cannot show
    whether a fit did anything. This writes the moleculetype and the structure through it, then rewrites the
    trajectory with `transform(frame, positions_nm)` applied, so the motion is exactly what the test asked for.
    """
    import numpy as np
    _, trajectory, structure, _ = support.cg_fixture_run(root, BEADS_NM, frames=1, topology=BONDED_TOPOLOGY)
    universe = mda.Universe(str(structure))
    with mda.Writer(str(trajectory), n_atoms=len(universe.atoms), multiframe=True) as writer:
        for frame in range(frames):
            universe.atoms.positions = np.asarray(transform(frame, np.asarray(BEADS_NM, dtype=float))) * 10.0
            writer.write(universe.atoms)
    return root


def _model_coordinates(path, model=1):
    """The xyz of one `MODEL` block in a series PDB, in nanometres -- the unit the record states lengths in.

    A PDB stores ångström, so the conversion lives here rather than in each assertion: a test that compared
    ångström with a record's nanometres would be a unit slip that looks like a tolerance.
    """
    blocks, current = [], None
    for line in path.read_text().splitlines():
        if line.startswith('MODEL'):
            current = []
            blocks.append(current)
        elif current is not None and line.startswith(('ATOM', 'HETATM')):
            current.append([float(value) for value in re.findall(r'-?\d+\.\d{3}', line)[:3]])
    return np.asarray(blocks[model - 1]) / 10.0


def _centroid_spread(path):
    """How far the models' centroids sit apart: the molecule's own translation, left in the file."""
    centroids = [block.mean(axis=0) for block in
                 [_model_coordinates(path, model) for model in range(1, 4)]]
    return float(np.linalg.norm(np.asarray(centroids) - centroids[0], axis=1).max())


def test_a_fitted_series_removes_the_molecules_own_translation(tmp_path):
    """Without a fit a moving molecule walks across the picture; the fit is what holds it still.

    The fixture moves the molecule a nanometre a frame, which is the motion a reader cannot tell from internal
    motion by eye. Measured: the raw series' centroids walk, the fitted series' do not, and the record states the
    fit it made.
    """
    shove = lambda frame, positions: positions + np.array([frame * 1.0, 0.0, 0.0])   # a nanometre a frame, x
    root = _moving_run(tmp_path / 'raw', shove)
    observability.generate(root, samples=3)
    raw = _centroid_spread(root / 'snapshots/CG-frames.pdb')

    fitted_root = _moving_run(tmp_path / 'fitted', shove)
    result = observability.generate(fitted_root, samples=3, align=True)
    fitted = _centroid_spread(fitted_root / 'snapshots/CG-frames.pdb')

    # The sampled frames are 0, 2 and 3 of four, so the raw series walks 3 nm; a trajectory stores nanometres, so
    # the fit's own residual is that format's precision rather than zero.
    assert raw == pytest.approx(3.0, abs=1e-3), f'the fixture did not move as asked: {raw} nm'
    assert fitted == pytest.approx(0.0, abs=1e-3), f'the fit left {fitted} nm of translation in the file'
    fit = result['series']['aligned']
    assert fit and fit['reference'] == 1 and fit['atoms'] == 4
    assert fit['rmsd_nm']['max'] == pytest.approx(0.0, abs=1e-3), fit['rmsd_nm']
    assert any('FITTED SERIES' in line for line in (fitted_root / 'snapshots/CG-frames.pdb').read_text().splitlines())


def test_a_fitted_series_removes_rotation_and_keeps_the_internal_motion(tmp_path):
    """A turning molecule is fitted away too, and what the fit cannot remove is the motion worth watching.

    Every frame is the same beads turned 18 degrees about the first bead and one bead displaced: the rotation is
    the fit's business, the displaced bead is not, so the series must come out still and the record must report the
    displacement that remains.
    """
    import numpy as np

    def turned(frame, positions):
        angle = np.radians(18.0 * frame)
        rotation = np.array([[np.cos(angle), -np.sin(angle), 0.0], [np.sin(angle), np.cos(angle), 0.0], [0.0, 0.0, 1.0]])
        moved = (positions - positions[0]) @ rotation.T + positions[0]
        if frame:
            moved = moved.copy()
            moved[3] = moved[3] + np.array([0.1 * frame, 0.0, 0.0])   # one bead drifts: the internal motion
        return moved

    root = _moving_run(tmp_path, turned)
    result = observability.generate(root, samples=3, align=True)

    series = root / 'snapshots/CG-frames.pdb'
    assert _centroid_spread(series) == pytest.approx(0.0, abs=1e-3), 'the fit left the rotation in the file'
    fit = result['series']['aligned']
    assert 0.0 < fit['rmsd_nm']['max'] <= 0.5, f"the displaced bead's motion is not in the record: {fit['rmsd_nm']}"
    # The raw series, for contrast, turns: the same fixture without the fit is not still.
    plain = _moving_run(tmp_path / 'plain', turned)
    observability.generate(plain, samples=3)
    assert _centroid_spread(plain / 'snapshots/CG-frames.pdb') > 0.01


def test_a_series_is_recorded_as_unaligned_unless_the_fit_was_asked_for(tmp_path):
    """The default is the run's own coordinates, and the record says so rather than leaving it to be assumed."""
    root = _moving_run(tmp_path, lambda frame, positions: positions)

    result = observability.generate(root, samples=2)

    assert result['series']['aligned'] is None
    assert 'FITTED SERIES' not in (root / 'snapshots/CG-frames.pdb').read_text()


def test_an_unknown_label_is_refused(tmp_path):
    with pytest.raises(ValueError, match='Unknown snapshot label'):
        observability.generate(_aa_only_run(tmp_path), labels=('first', 'every'))
