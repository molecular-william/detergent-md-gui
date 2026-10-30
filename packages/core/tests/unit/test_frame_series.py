"""The frame-series producer: the frames it samples, the fit and assembly it records, and what it refuses.

The work directory is the one the analysis subprocess is handed: the chosen trajectory and structure at the keys the
payload names, `manifest.json`, and whatever the source hook staged beside them. Each fixture builds a real `.gro` and
`.xtc` with MDAnalysis, so the assertions are against a trajectory the test made rather than a run in the developer's
workspace. Positions are ångström (MDAnalysis's unit) and the file states nanometres, so a unit slip is what the
tolerances catch.
"""
import json
import re
import shutil
from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pytest
from dashboard.analysis.runs import frame_series, segments

NAMES = ('B01', 'B02', 'B03', 'B04')


def _trajectory(directory, positions_by_frame, *, names=NAMES, resindex=None, resnames=None, resids=None,
                box=None, dt_ps=10.0, stem='traj'):
    """Write `<stem>.gro` and `<stem>.xtc`: positions in ångström, frames `dt_ps` apart, a box in ångström."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    names = list(names)
    resindex = resindex if resindex is not None else [0] * len(names)
    resnames = resnames if resnames is not None else ['DDM']
    resids = resids if resids is not None else [1]
    universe = mda.Universe.empty(len(names), n_residues=len(resnames), atom_resindex=resindex, trajectory=True)
    universe.add_TopologyAttr('names', names)
    universe.add_TopologyAttr('resnames', resnames)
    universe.add_TopologyAttr('resids', resids)
    with mda.Writer(str(directory / f'{stem}.xtc'), n_atoms=len(names)) as writer:
        for frame, positions in enumerate(positions_by_frame):
            universe.atoms.positions = np.asarray(positions, dtype=float)
            universe.trajectory.ts.time = frame * dt_ps
            if box is not None:
                universe.dimensions = [*box, 90.0, 90.0, 90.0]
            if frame == 0:
                universe.atoms.write(str(directory / f'{stem}.gro'))
            writer.write(universe.atoms)
    return directory / f'{stem}.xtc', directory / f'{stem}.gro'


def _moved(frames=5, atoms=4):
    """Distinct positions per frame, a whole 10 ångström apart so the nanometres stay exact."""
    base = np.arange(atoms * 3, dtype=float).reshape(atoms, 3) * 10.0
    return [base + frame * 10.0 for frame in range(frames)]


def _models(path):
    """Every model's coordinates in ångström, in file order, read from the PDB's own columns."""
    blocks, current = [], None
    for line in Path(path).read_text().splitlines():
        if line.startswith('MODEL'):
            current = []
        elif line.startswith('ENDMDL'):
            blocks.append(current)
            current = None
        elif current is not None and line.startswith('HETATM'):
            current.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
    return np.asarray(blocks, dtype=float)


def _payload(**overrides):
    payload = {'trajectory': 'traj.xtc', 'structure': 'traj.gro'}
    payload.update(overrides)
    return payload


#: A non-collinear molecule: a fit on a line would leave the rotation about it undetermined, so the fixture's shape is
#: part of what the assertions measure.
BASE = np.array([[0.0, 0.0, 0.0], [4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 6.0], [0.0, 0.0, 12.0]])


def _turned(positions, degrees, shift=(0.0, 0.0, 0.0)):
    """One rigid copy of `positions`: turned about z and translated."""
    angle = np.radians(degrees)
    rotation = np.array([[np.cos(angle), -np.sin(angle), 0.0],
                         [np.sin(angle), np.cos(angle), 0.0],
                         [0.0, 0.0, 1.0]])
    return np.asarray(positions, dtype=float) @ rotation.T + np.asarray(shift, dtype=float)



def test_a_series_holds_the_frames_it_was_asked_for_and_states_their_times(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _moved(5), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    result = frame_series.run(work, _payload(stride=2))

    text = (work / 'run-frames.pdb').read_text()
    assert len(re.findall(r'^MODEL', text, re.M)) == 3
    assert 'REMARK 950 MODEL 1 TIME 0.000000 NS' in text
    assert 'REMARK 950 MODEL 2 TIME 0.020000 NS' in text
    assert 'REMARK 950 MODEL 3 TIME 0.040000 NS' in text
    record = json.loads((work / 'frames.json').read_text())
    assert record['args'] == _payload(stride=2)
    assert record['indices'] == [0, 2, 4]
    assert record['times_ns'] == [0.0, 0.02, 0.04]
    assert record['models'] == result['models'] == 3
    assert record['atoms'] == result['atoms'] == 4
    assert record['trajectory_identity'] == segments.identity(work / 'traj.xtc')
    assert record['structure_identity'] == segments.identity(work / 'traj.gro')
    assert record['bytes'] == (work / 'run-frames.pdb').stat().st_size
    assert record['cadence_ns'] == pytest.approx(0.02)
    assert record['fit'] is None and record['assembled'] is False
    assert result['times'] == 3 and result['files'] == ['run-frames.pdb', 'frames.json']
    # A run with no topology, mapping or protein is still a run of coordinates, and the file says so.
    assert 'NO BONDS RECORDED' in text


def test_a_time_window_selects_the_frames_between_its_ends(tmp_path):
    """Inclusive at both ends, and the first selected frame is always in the series."""
    work = tmp_path / 'work'
    _trajectory(work, _moved(5), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    frame_series.run(work, _payload(start_ns=0.01, end_ns=0.03, stride=2))

    record = json.loads((work / 'frames.json').read_text())
    assert record['indices'] == [1, 3]
    assert record['times_ns'] == [0.01, 0.03]


def test_auto_stride_aims_at_the_model_budget(tmp_path):
    """A stride of `None`/`'auto'` is what a panel offers first; it must not ask for hundreds of models."""
    work = tmp_path / 'work'
    _trajectory(work, _moved(200), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    frame_series.run(work, _payload())

    record = json.loads((work / 'frames.json').read_text())
    assert record['models'] == 100 <= frame_series.AUTO_MODELS
    assert record['indices'][:3] == [0, 2, 4] and record['indices'][-1] == 198


def test_more_models_than_the_cap_are_refused_naming_both_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(frame_series, 'MAX_MODELS', 2)
    work = tmp_path / 'work'
    _trajectory(work, _moved(4), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    with pytest.raises(ValueError) as refused:
        frame_series.run(work, _payload(stride=1))

    message = str(refused.value)
    assert '4 models' in message and 'at most 2' in message, message


def test_an_estimated_series_over_the_size_cap_is_refused_naming_both_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(frame_series, 'MAX_BYTES', 1_000)
    work = tmp_path / 'work'
    _trajectory(work, _moved(4), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    with pytest.raises(ValueError) as refused:
        frame_series.run(work, _payload(stride=1))

    message = str(refused.value)
    assert '4 models of 4 atoms' in message and '1920' in message and '1000' in message, message


def _rigid_frames(frames=4):
    """Every frame the same molecule turned and translated: motion a fit must remove entirely."""
    return [_turned(BASE[:4], 20.0 * frame, (10.0 * frame, 0.0, 0.0)) for frame in range(frames)]


def test_the_fit_superposes_every_model_on_the_first(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _rigid_frames(), resindex=[0] * 4, resnames=['ALA'], resids=[1])
    frame_series.run(work, _payload(stride=1))
    raw = _models(work / 'run-frames.pdb')
    assert np.abs(raw[-1] - raw[0]).max() > 10.0, 'the fixture did not move as asked'

    result = frame_series.run(work, _payload(stride=1, fit='protein'))

    fitted = _models(work / 'run-frames.pdb')
    assert np.abs(fitted[-1] - fitted[0]).max() < 1e-2, 'the fit left the rigid motion in the file'
    record = json.loads((work / 'frames.json').read_text())
    assert record['fit']['reference'] == 1
    assert record['fit']['atoms'] == 4 and record['fit']['of'] == 4
    assert record['fit']['rmsd_nm']['max'] == pytest.approx(0.0, abs=1e-3)
    assert result['fit']['reference'] == 1
    assert 'FITTED SERIES' in (work / 'run-frames.pdb').read_text()


def test_a_bead_fit_holds_the_named_fragment_and_records_the_motion_of_the_rest(tmp_path):
    """The fit's own atoms are fragment A; A's small wobble is the recorded RMSD and B's swing is what moves."""
    names = ('B01', 'B02', 'B03', 'B04', 'B05')
    positions = []
    for frame in range(3):
        moved = _turned(BASE, 20.0 * frame, (10.0 * frame, 0.0, 0.0))
        if frame:
            moved[1] = moved[1] + np.array([0.3 * frame, 0.0, 0.0])   # A's own bead wobbles: a fitted RMSD
            moved[4] = moved[4] + np.array([3.0 * frame, 0.0, 0.0])   # the other fragment swings out
        positions.append(moved)
    work = tmp_path / 'work'
    _trajectory(work, positions, names=names, resindex=[0] * 5, resnames=['SUCR'], resids=[1])
    mapping = work / '2_mapping' / 'model.json'
    mapping.parent.mkdir(parents=True)
    mapping.write_text(json.dumps({'beads': [
        {'export_name': 'B01', 'letter': 'A'}, {'export_name': 'B02', 'letter': 'A'},
        {'export_name': 'B03', 'letter': 'A'}, {'export_name': 'B04', 'letter': 'B'},
        {'export_name': 'B05', 'letter': 'B'}]}))

    frame_series.run(work, _payload(fit='beads', fragment='A'))

    record = json.loads((work / 'frames.json').read_text())
    assert record['fit']['target'] == 'A'
    assert record['fit']['atoms'] == 3 and record['fit']['of'] == 5
    assert record['fit']['rmsd_nm']['max'] > 0.0, 'A\'s own wobble is not in the recorded fit'
    text = (work / 'run-frames.pdb').read_text()
    assert '3 beads of fragment A' in text and 'CHAIN LETTERS' in text
    models = _models(work / 'run-frames.pdb')
    assert np.abs(models[-1][:3] - models[0][:3]).max() < 1.0, 'the fragment the fit named did not hold still'
    assert np.abs(models[-1][3:] - models[0][3:]).max() > 2.0, 'the other fragment did not move relative to it'


def test_a_fragment_the_mapping_does_not_state_is_refused_with_what_it_does_state(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _moved(3), resindex=[0] * 4, resnames=['SUCR'], resids=[1])
    mapping = work / '2_mapping' / 'model.json'
    mapping.parent.mkdir(parents=True)
    mapping.write_text(json.dumps({'beads': [
        {'export_name': 'B01', 'letter': 'A'}, {'export_name': 'B02', 'letter': 'A'},
        {'export_name': 'B03', 'letter': 'B'}, {'export_name': 'B04', 'letter': 'B'}]}))

    with pytest.raises(ValueError) as refused:
        frame_series.run(work, _payload(fit='beads', fragment='Z'))

    message = str(refused.value)
    assert "places no bead in fragment 'Z'" in message and 'A (B01, B02)' in message, message


def test_assembly_wraps_whole_molecules_and_centres_the_anchor(tmp_path):
    """A display view: each molecule takes the periodic image nearest the protein, which is then centred."""
    positions = [[1.0, 1.0, 1.0], [2.0, 1.0, 1.0], [1.0, 2.0, 1.0], [95.0, 1.0, 1.0]]
    work = tmp_path / 'work'
    _trajectory(work, [positions, positions], resindex=[0, 0, 0, 1],
                resnames=['ALA', 'DDM'], resids=[1, 2], box=(100.0, 100.0, 100.0))
    frame_series.run(work, _payload(stride=1))
    raw = _models(work / 'run-frames.pdb')
    assert raw[0][3][0] == pytest.approx(95.0, abs=1e-2), 'the fixture did not place the second molecule at the edge'

    result = frame_series.run(work, _payload(stride=1, assembled=True))

    assembled = _models(work / 'run-frames.pdb')
    # 95 A wrapped to the nearest image of the protein centroid (4/3 A), then the protein centred at the origin.
    assert assembled[0][3][0] == pytest.approx(-5.0 - 4.0 / 3.0, abs=1e-2), \
        'the second molecule was not wrapped to the nearest image'
    assert assembled[0][:3].mean(axis=0) == pytest.approx([0.0, 0.0, 0.0], abs=1e-2), 'the anchor is not centred'
    assert result['assembled'] is True
    record = json.loads((work / 'frames.json').read_text())
    assert record['assembled'] is True
    assert 'PERIODIC-IMAGE ASSEMBLED AND CENTRED FOR DISPLAY' in (work / 'run-frames.pdb').read_text()


def test_assembly_without_a_box_is_refused(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _moved(2), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    with pytest.raises(ValueError, match='needs a box'):
        frame_series.run(work, _payload(assembled=True))


def test_ca_atoms_are_written_alone_and_claim_no_bonds(tmp_path):
    """An atomistic backbone is a subset of the system, and the CG moleculetype beside it must not bond it."""
    work = tmp_path / 'work'
    names = ('CA', 'CB', 'N', 'CA')
    positions = [[0.0, 0.0, 0.0], [4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [8.0, 0.0, 0.0]]
    _trajectory(work, [positions, positions], names=names, resindex=[0] * 4, resnames=['ALA'], resids=[1])
    (work / '3_initial_CG').mkdir()
    (work / '3_initial_CG' / 'LIG_initial.itp').write_text(
        '[ moleculetype ]\nLIG 1\n\n[ atoms ]\n'
        '1 SP1r 1 ALA CA 1 0 54\n2 SP1r 1 ALA CB 2 0 54\n'
        '3 SP1r 1 ALA N 3 0 54\n4 SP1r 1 ALA CA 4 0 54\n\n[ bonds ]\n1 2 1 0.4 5000\n')
    (work / 'manifest.json').write_text(json.dumps(
        {'run_type': 'aa_cg', 'stages': [{'environment': {'FINAL_ITP': 'LIG_initial.itp'}}]}))

    frame_series.run(work, _payload(stride=1))
    assert 'CONECT' in (work / 'run-frames.pdb').read_text(), 'the fixture does not bond the all-atom series'

    result = frame_series.run(work, _payload(stride=1, atoms='ca'))

    text = (work / 'run-frames.pdb').read_text()
    assert 'CONECT' not in text, 'a CA-only series claims no bonds'
    assert _models(work / 'run-frames.pdb').shape == (2, 2, 3), 'the file holds both CA atoms of both models'
    assert result['atoms'] == 2


def _run_tree(root):
    """A current-layout protein-detergent run: its extension trajectory, its mapping, detergent and protein models."""
    root = Path(root)
    (root / 'stages/4_CG_sim/prod').mkdir(parents=True)
    (root / 'stages/4_CG_sim/prod/lig_CG.xtc').write_bytes(b'xtc bytes')
    (root / 'stages/4_CG_sim/prod/lig_CG.gro').write_text('coarse\n    1\n')
    (root / 'stages/2_mapping').mkdir(parents=True)
    (root / 'stages/2_mapping/model.json').write_text(json.dumps(
        {'beads': [{'export_name': 'B01', 'letter': 'A'}]}))
    (root / 'stages/02_system/cg').mkdir(parents=True)
    (root / 'stages/02_system/detergent_CG.itp').write_text(
        '[ moleculetype ]\nDDM 1\n\n[ atoms ]\n1 C1 1 DDM B01 1 0 54\n')
    (root / 'stages/02_system/cg/molecule_1.itp').write_text(
        '[ moleculetype ]\nPRO 1\n\n[ atoms ]\n1 BB 1 ALA BB 1 0 54\n')
    (root / 'manifest.json').write_text(json.dumps(
        {'run_type': 'pdc', 'stages': [{'environment': {'FINAL_ITP': 'detergent_CG.itp'}}]}))
    return root


PAYLOAD_STAGES = {'trajectory': 'stages/4_CG_sim/prod/lig_CG.xtc', 'structure': 'stages/4_CG_sim/prod/lig_CG.gro'}


def test_sources_are_the_chosen_pair_and_the_writer_inputs_the_run_holds(tmp_path):
    root = _run_tree(tmp_path / 'run')

    entries = frame_series.sources(root, dict(PAYLOAD_STAGES, colour='blue'))

    assert set(entries) == {*PAYLOAD_STAGES.values(), 'stages/2_mapping/model.json',
                            'stages/02_system/detergent_CG.itp', 'stages/02_system/cg/molecule_1.itp'}, sorted(entries)
    assert entries[PAYLOAD_STAGES['trajectory']] == root / PAYLOAD_STAGES['trajectory']
    assert entries['stages/2_mapping/model.json'] == root / 'stages/2_mapping/model.json'
    assert entries['stages/02_system/detergent_CG.itp'] == root / 'stages/02_system/detergent_CG.itp'


def test_missing_writer_inputs_are_not_an_error(tmp_path):
    root = tmp_path / 'run'
    (root / 'stages/4_CG_sim/prod').mkdir(parents=True)
    (root / 'stages/4_CG_sim/prod/lig_CG.xtc').write_bytes(b'xtc bytes')
    (root / 'stages/4_CG_sim/prod/lig_CG.gro').write_text('coarse\n    1\n')
    (root / 'manifest.json').write_text('{"run_type": "pdc"}')

    entries = frame_series.sources(root, PAYLOAD_STAGES)

    assert set(entries) == set(PAYLOAD_STAGES.values())


def test_a_payload_path_that_leaves_the_run_is_refused(tmp_path):
    root = _run_tree(tmp_path / 'run')
    outside = tmp_path / 'outside.xtc'
    outside.write_bytes(b'not this run')
    for trajectory in ('../outside.xtc', str(outside)):
        with pytest.raises(ValueError) as refused:
            frame_series.sources(root, dict(PAYLOAD_STAGES, trajectory=trajectory))
        assert 'inside this run' in str(refused.value), str(refused.value)


def test_a_symlinked_payload_file_is_refused_even_when_it_points_inside(tmp_path):
    root = _run_tree(tmp_path / 'run')
    link = root / 'stages/4_CG_sim/prod/link.xtc'
    link.symlink_to(root / 'stages/4_CG_sim/prod/lig_CG.xtc')

    with pytest.raises(ValueError) as refused:
        frame_series.sources(root, dict(PAYLOAD_STAGES, trajectory='stages/4_CG_sim/prod/link.xtc'))

    assert 'is not a file inside this run' in str(refused.value), str(refused.value)


def test_a_payload_file_the_run_does_not_hold_is_refused(tmp_path):
    root = _run_tree(tmp_path / 'run')

    with pytest.raises(ValueError) as refused:
        frame_series.sources(root, dict(PAYLOAD_STAGES, structure='stages/4_CG_sim/prod/missing.gro'))

    assert 'is not a file inside this run' in str(refused.value), str(refused.value)


def test_the_hook_and_the_producer_agree_on_the_staged_keys(tmp_path):
    """The keys `sources` hands the worker are the names `run` reads back, extras included.

    A staged copy preserving the hook's keys is exactly what `worker.execute` makes, so this is the one check that
    the two halves of the module speak the same spelling -- including the `stages/` prefix of a current run.
    """
    root = _run_tree(tmp_path / 'run')
    _trajectory(root / 'stages/4_CG_sim/prod', _moved(3), names=NAMES, resindex=[0] * 4,
                resnames=['DDM'], resids=[1], stem='lig_CG')
    (root / 'stages/02_system/detergent_CG.itp').write_text(
        '[ moleculetype ]\nDDM 1\n\n[ atoms ]\n'
        + ''.join(f'{index} C1 1 DDM {name} {index} 0 54\n' for index, name in enumerate(NAMES, 1))
        + '\n[ bonds ]\n1 2 1 0.4 5000\n')
    (root / 'stages/2_mapping/model.json').write_text(json.dumps(
        {'beads': [{'export_name': name, 'letter': 'A'} for name in NAMES]}))
    work = tmp_path / 'work'
    for relative, path in frame_series.sources(root, dict(PAYLOAD_STAGES)).items():
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy2(root / 'manifest.json', work / 'manifest.json')

    result = frame_series.run(work, dict(PAYLOAD_STAGES))

    assert result['models'] == 3 and result['atoms'] == 4
    assert result['trajectory_identity'] == segments.identity(work / PAYLOAD_STAGES['trajectory'])
    text = (work / 'run-frames.pdb').read_text()
    assert 'CONECT' in text, 'the staged moleculetype did not reach the writer'
    record = json.loads((work / 'frames.json').read_text())
    assert record['trajectory'] == PAYLOAD_STAGES['trajectory']
    assert record['structure'] == PAYLOAD_STAGES['structure']


@pytest.mark.parametrize('payload, expected', [
    ({'structure': 'traj.gro'}, 'trajectory'),
    ({'trajectory': '', 'structure': 'traj.gro'}, 'trajectory'),
    ({'trajectory': 7, 'structure': 'traj.gro'}, 'trajectory'),
    ({'trajectory': 'traj.xtc'}, 'structure'),
    ({'trajectory': 'traj.xtc', 'structure': None}, 'structure'),
    (_payload(start_ns='soon'), 'start_ns'),
    (_payload(start_ns=True), 'start_ns'),
    (_payload(end_ns=float('inf')), 'end_ns'),
    (_payload(start_ns=5.0, end_ns=1.0), 'start_ns'),
    (_payload(stride=0), 'stride'),
    (_payload(stride=1.5), 'stride'),
    (_payload(stride=True), 'stride'),
    (_payload(stride='slow'), 'stride'),
    (_payload(fit='all'), 'fit'),
    (_payload(fit=None), 'fit'),
    (_payload(fit='beads'), 'fragment'),
    (_payload(fit='beads', fragment='AB'), 'fragment'),
    (_payload(fit='beads', fragment='2'), 'fragment'),
    (_payload(atoms='water'), 'atoms'),
    (_payload(assembled='yes'), 'assembled'),
])
def test_a_malformed_payload_is_refused(tmp_path, payload, expected):
    root = tmp_path / 'run'
    root.mkdir()
    (root / 'traj.xtc').write_bytes(b'x')
    (root / 'traj.gro').write_text('x\n')

    with pytest.raises(ValueError) as refused:
        frame_series.sources(root, payload)

    assert expected in str(refused.value), str(refused.value)


def test_a_recorded_topology_may_be_a_symlink_inside_the_run(tmp_path):
    """Measured on `b920391735dd`: the stage's `detergent_CG.itp` is a link into the run's `inputs/`.

    The writer needs that moleculetype for the detergent's bonds, so a series built from such a run would come out
    unbonded beside a structure picture that draws them. The link is staged under its stage spelling (the copy follows
    it), because that is where the producer's layout resolver looks.
    """
    root = _run_tree(tmp_path / 'run')
    staged = root / 'stages/02_system/detergent_CG.itp'
    target = root / 'inputs/detergent_CG.itp'
    target.parent.mkdir()
    target.write_text(staged.read_text())
    staged.unlink()
    staged.symlink_to(target)

    entries = frame_series.sources(root, dict(PAYLOAD_STAGES))

    assert entries['stages/02_system/detergent_CG.itp'] == staged


def test_a_recorded_topology_that_leaves_the_run_is_not_staged(tmp_path):
    root = _run_tree(tmp_path / 'run')
    outside = tmp_path / 'outside.itp'
    outside.write_text('[ moleculetype ]\nDDM 1\n')
    staged = root / 'stages/02_system/detergent_CG.itp'
    staged.unlink()
    staged.symlink_to(outside)

    entries = frame_series.sources(root, dict(PAYLOAD_STAGES))

    assert 'stages/02_system/detergent_CG.itp' not in entries
