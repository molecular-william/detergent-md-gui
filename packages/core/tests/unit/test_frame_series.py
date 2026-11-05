"""The frame-series producer: the frames it samples, the view it applies, and what it refuses.

The work directory is the one the analysis subprocess is handed: the chosen trajectory and structure at the keys the
payload names, `manifest.json`, and whatever the source hook staged beside them. Each fixture builds a real `.gro` and
`.xtc` with MDAnalysis, so the assertions are against a trajectory the test made rather than a run in the developer's
workspace. Positions are ångström (MDAnalysis's unit) and the file states nanometres, so a unit slip is what the
tolerances catch.

The last test compares the producer with `gmx trjconv` itself; it is marked slow and skips, with the reason stated,
when the declared GROMACS is not installed.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pytest
from dashboard.analysis import worker
from dashboard.analysis.kinds import Kind
from dashboard.analysis.runs import frame_series, segments, structures
from dashboard.execution import tools

from tests.harness.support import DDM_BEADS, ddm_moleculetype

NAMES = ('B01', 'B02', 'B03', 'B04')
GMX = tools.tool_path('gmx')


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
    dimensions = None if box is None else ([*box, 90.0, 90.0, 90.0] if len(box) == 3 else list(box))
    with mda.Writer(str(directory / f'{stem}.xtc'), n_atoms=len(names)) as writer:
        for frame, positions in enumerate(positions_by_frame):
            universe.atoms.positions = np.asarray(positions, dtype=float)
            universe.trajectory.ts.time = frame * dt_ps
            if dimensions is not None:
                universe.dimensions = dimensions
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


DEFAULTS = {'pbc': 'none', 'center': False, 'boxcenter': 'tric', 'fit': 'none', 'group': 'solute'}


def test_a_series_holds_the_frames_the_interval_asks_for_and_states_their_times(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _moved(5), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    result = frame_series.run(work, _payload(interval_ns=0.02))

    text = (work / 'run-frames.pdb').read_text()
    assert len(re.findall(r'^MODEL', text, re.M)) == 3
    assert 'REMARK 950 MODEL 1 TIME 0.000000 NS' in text
    assert 'REMARK 950 MODEL 2 TIME 0.020000 NS' in text
    assert 'REMARK 950 MODEL 3 TIME 0.040000 NS' in text
    assert 'one model every 0.02 ns' in text, 'the build sentence does not read in nanoseconds'
    assert 'VIEW MODIFICATIONS' not in text, 'a raw series claims a modification it did not make'
    record = json.loads((work / 'frames.json').read_text())
    assert record['args'] == _payload(interval_ns=0.02)
    assert record['indices'] == [0, 2, 4]
    assert record['times_ns'] == [0.0, 0.02, 0.04]
    assert record['models'] == result['models'] == 3
    assert record['atoms'] == result['atoms'] == 4
    assert record['trajectory_identity'] == segments.identity(work / 'traj.xtc')
    assert record['structure_identity'] == segments.identity(work / 'traj.gro')
    assert record['bytes'] == (work / 'run-frames.pdb').stat().st_size
    assert record['cadence_ns'] == pytest.approx(0.02)
    assert record['interval_ns'] == 0.02 and record['stride'] == 2
    assert record['view'] == DEFAULTS and record['legacy'] == []
    assert record['view']['boxcenter'] == 'tric', 'an attempt that never sent boxcenter did not record the default'
    assert record['fit'] is None
    assert result['interval_ns'] == 0.02 and result['stride'] == 2
    assert result['view'] == DEFAULTS
    assert result['times'] == 3 and result['files'] == ['run-frames.pdb', 'frames.json']
    # A run with no topology, mapping or protein is still a run of coordinates, and the file says so.
    assert 'NO BONDS RECORDED' in text


def test_a_time_window_selects_the_frames_between_its_ends(tmp_path):
    """Inclusive at both ends, and the first selected frame is always in the series."""
    work = tmp_path / 'work'
    _trajectory(work, _moved(5), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    frame_series.run(work, _payload(start_ns=0.01, end_ns=0.03, interval_ns=0.02))

    record = json.loads((work / 'frames.json').read_text())
    assert record['indices'] == [1, 3]
    assert record['times_ns'] == [0.01, 0.03]


def test_the_auto_cadence_aims_at_the_model_budget(tmp_path):
    """A null/absent interval is what a panel offers first; it must not ask for hundreds of models."""
    work = tmp_path / 'work'
    _trajectory(work, _moved(200), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    frame_series.run(work, _payload())

    record = json.loads((work / 'frames.json').read_text())
    assert record['models'] == 100 <= frame_series.AUTO_MODELS
    assert record['indices'][:3] == [0, 2, 4] and record['indices'][-1] == 198
    assert record['interval_ns'] is None and record['stride'] == 2


def test_an_interval_that_is_an_exact_multiple_of_the_step_uses_that_stride(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _moved(5), resindex=[0] * 4, resnames=['DDM'], resids=[1])  # dt = 0.01 ns

    frame_series.run(work, _payload(interval_ns=0.03))

    record = json.loads((work / 'frames.json').read_text())
    assert record['stride'] == 3 and record['indices'] == [0, 3]
    assert record['cadence_ns'] == pytest.approx(0.03)


def test_an_interval_that_is_not_a_multiple_records_the_step_it_rounded_to(tmp_path):
    """3.5 steps rounds to 4 frames, so the effective cadence is 0.04 ns, not the 0.035 ns that was asked for."""
    work = tmp_path / 'work'
    _trajectory(work, _moved(5), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    frame_series.run(work, _payload(interval_ns=0.035))

    record = json.loads((work / 'frames.json').read_text())
    assert record['args']['interval_ns'] == 0.035, 'the request is not what was recorded'
    assert record['stride'] == 4 and record['indices'] == [0, 4]
    assert record['cadence_ns'] == pytest.approx(0.04)
    assert 'one model every 0.04 ns' in (work / 'run-frames.pdb').read_text()


def test_an_interval_finer_than_the_step_is_one_frame_at_the_step(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _moved(3), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    frame_series.run(work, _payload(interval_ns=0.004))

    record = json.loads((work / 'frames.json').read_text())
    assert record['stride'] == 1 and record['indices'] == [0, 1, 2]
    assert record['cadence_ns'] == pytest.approx(0.01), 'the recorded cadence is the request, not the frame step'
    assert 'one model every 0.01 ns' in (work / 'run-frames.pdb').read_text()


def test_an_interval_without_a_time_step_is_refused(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _moved(3), resindex=[0] * 4, resnames=['DDM'], resids=[1], dt_ps=0.0)

    with pytest.raises(ValueError) as refused:
        frame_series.run(work, _payload(interval_ns=0.1))

    assert 'states no time step' in str(refused.value), str(refused.value)


def test_the_old_stride_argument_is_still_read_for_an_attempt_built_before_the_interval(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _moved(5), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    result = frame_series.run(work, _payload(stride=2))

    record = json.loads((work / 'frames.json').read_text())
    assert record['indices'] == [0, 2, 4] and record['stride'] == 2
    assert record['interval_ns'] is None
    assert record['cadence_ns'] == pytest.approx(0.02)
    assert record['args'] == _payload(stride=2)
    assert result['stride'] == 2


def test_more_models_than_the_cap_are_refused_naming_both_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(frame_series, 'MAX_MODELS', 2)
    work = tmp_path / 'work'
    _trajectory(work, _moved(4), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    with pytest.raises(ValueError) as refused:
        frame_series.run(work, _payload(interval_ns=0.01))

    message = str(refused.value)
    assert '4 models' in message and 'at most 2' in message, message


def test_an_estimated_series_over_the_size_cap_is_refused_naming_both_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(frame_series, 'MAX_BYTES', 1_000)
    work = tmp_path / 'work'
    _trajectory(work, _moved(4), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    with pytest.raises(ValueError) as refused:
        frame_series.run(work, _payload(interval_ns=0.01))

    message = str(refused.value)
    assert '4 models of 4 atoms' in message and '1920' in message and '1000' in message, message


def _rigid_frames(frames=4):
    """Every frame the same molecule turned and translated: motion a fit must remove entirely."""
    return [_turned(BASE[:4], 20.0 * frame, (10.0 * frame, 0.0, 0.0)) for frame in range(frames)]


def test_the_fit_superposes_every_model_on_the_first(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _rigid_frames(), resindex=[0] * 4, resnames=['ALA'], resids=[1])
    frame_series.run(work, _payload())
    raw = _models(work / 'run-frames.pdb')
    assert np.abs(raw[-1] - raw[0]).max() > 10.0, 'the fixture did not move as asked'

    result = frame_series.run(work, _payload(fit='rot+trans', group='protein'))

    fitted = _models(work / 'run-frames.pdb')
    assert np.abs(fitted[-1] - fitted[0]).max() < 1e-2, 'the fit left the rigid motion in the file'
    record = json.loads((work / 'frames.json').read_text())
    assert record['view'] == dict(DEFAULTS, fit='rot+trans', group='protein')
    assert record['fit']['reference'] == 1 and record['fit']['fit'] == 'rot+trans'
    assert record['fit']['group'] == 'protein'
    assert record['fit']['atoms'] == 4 and record['fit']['of'] == 4
    assert record['fit']['rmsd_nm']['max'] == pytest.approx(0.0, abs=1e-3)
    assert result['fit']['reference'] == 1
    text = (work / 'run-frames.pdb').read_text()
    assert 'FITTED SERIES' in text and 'VIEW MODIFICATIONS' in text
    assert 'fit rot+trans against the protein group' in text


def test_a_translation_only_fit_keeps_the_rotation(tmp_path):
    """`trans` removes where the group is, not how it is turned; a rot+trans fit on the same frames would remove both."""
    work = tmp_path / 'work'
    _trajectory(work, _rigid_frames(), resindex=[0] * 4, resnames=['ALA'], resids=[1])

    frame_series.run(work, _payload(fit='trans', group='protein'))

    models = _models(work / 'run-frames.pdb')
    assert models[-1].mean(axis=0) == pytest.approx(models[0].mean(axis=0), abs=1e-2), 'the translation stayed'
    assert np.abs(models[-1] - models[0]).max() > 1.0, 'the rotation was removed by a translation-only fit'
    record = json.loads((work / 'frames.json').read_text())
    assert record['fit']['fit'] == 'trans'
    assert 'translation those beads do are removed' in (work / 'run-frames.pdb').read_text()


def test_a_legacy_protein_fit_is_read_as_rot_trans_on_the_protein_group(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _rigid_frames(), resindex=[0] * 4, resnames=['ALA'], resids=[1])

    frame_series.run(work, _payload(fit='protein'))

    record = json.loads((work / 'frames.json').read_text())
    assert record['args'] == _payload(fit='protein'), 'the old request was rewritten in the record'
    assert record['view'] == dict(DEFAULTS, fit='rot+trans', group='protein')
    assert record['legacy'] == ["fit 'protein'"]
    assert record['fit']['group'] == 'protein' and record['fit']['fit'] == 'rot+trans'
    assert "requested as the old fit 'protein'" in (work / 'run-frames.pdb').read_text()


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
    assert record['view'] == dict(DEFAULTS, fit='rot+trans', group='fragment:A')
    assert record['legacy'] == ["fit 'beads' fragment A"]
    assert record['fit']['target'] == 'A' and record['fit']['group'] == 'fragment:A'
    assert record['fit']['atoms'] == 3 and record['fit']['of'] == 5
    assert record['fit']['rmsd_nm']['max'] > 0.0, 'A\'s own wobble is not in the recorded fit'
    text = (work / 'run-frames.pdb').read_text()
    assert '3 beads of fragment A' in text and 'CHAIN LETTERS' in text
    models = _models(work / 'run-frames.pdb')
    assert np.abs(models[-1][:3] - models[0][:3]).max() < 1.0, 'the fragment the fit named did not hold still'
    assert np.abs(models[-1][3:] - models[0][3:]).max() > 2.0, 'the other fragment did not move relative to it'


def test_a_fragment_group_is_named_without_the_old_fit_key(tmp_path):
    names = ('B01', 'B02', 'B03', 'B04')
    work = tmp_path / 'work'
    _trajectory(work, _moved(3), names=names, resindex=[0] * 4, resnames=['SUCR'], resids=[1])
    mapping = work / '2_mapping' / 'model.json'
    mapping.parent.mkdir(parents=True)
    mapping.write_text(json.dumps({'beads': [
        {'export_name': 'B01', 'letter': 'A'}, {'export_name': 'B02', 'letter': 'A'},
        {'export_name': 'B03', 'letter': 'B'}, {'export_name': 'B04', 'letter': 'B'}]}))

    frame_series.run(work, _payload(fit='rot+trans', group='fragment:A'))

    record = json.loads((work / 'frames.json').read_text())
    assert record['view'] == dict(DEFAULTS, fit='rot+trans', group='fragment:A')
    assert record['legacy'] == [] and record['fit']['target'] == 'A'


def test_a_fragment_the_mapping_does_not_state_is_refused_with_what_it_does_state(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _moved(3), resindex=[0] * 4, resnames=['SUCR'], resids=[1])
    mapping = work / '2_mapping' / 'model.json'
    mapping.parent.mkdir(parents=True)
    mapping.write_text(json.dumps({'beads': [
        {'export_name': 'B01', 'letter': 'A'}, {'export_name': 'B02', 'letter': 'A'},
        {'export_name': 'B03', 'letter': 'B'}, {'export_name': 'B04', 'letter': 'B'}]}))

    with pytest.raises(ValueError) as refused:
        frame_series.run(work, _payload(fit='rot+trans', group='fragment:Z'))

    message = str(refused.value)
    assert "places no bead in fragment 'Z'" in message and 'A (B01, B02)' in message, message


def test_the_solute_group_is_what_the_writer_keeps_water_excluded(tmp_path):
    names = ('B01', 'B02', 'B03', 'B04', 'W1', 'W2')
    positions = [np.vstack([_turned(BASE[:4], 20.0 * frame, (10.0 * frame, 0.0, 0.0)),
                            np.array([[90.0, 90.0, 90.0], [92.0, 90.0, 90.0]])]) for frame in range(3)]
    work = tmp_path / 'work'
    _trajectory(work, positions, names=names, resindex=[0, 0, 0, 0, 1, 1],
                resnames=['ALA', 'W'], resids=[1, 2])

    frame_series.run(work, _payload(fit='rot+trans', group='solute'))

    record = json.loads((work / 'frames.json').read_text())
    assert record['fit']['atoms'] == 4 and record['fit']['of'] == 6, 'the solute fit counted water'
    assert _models(work / 'run-frames.pdb').shape == (3, 4, 3), 'the writer stopped dropping water'
    assert 'the solute group' in (work / 'run-frames.pdb').read_text()


def _crossing(directory):
    """One molecule split over the x boundary and then carried further: the shapes `-pbc` and `-nojump` differ on."""
    frames = [np.array([[2.0, 2.0, 2.0], [3.0, 2.0, 2.0], [4.0, 2.0, 2.0], [5.0, 2.0, 2.0]]),
              np.array([[29.5, 2.0, 2.0], [0.5, 2.0, 2.0], [1.5, 2.0, 2.0], [2.5, 2.0, 2.0]]),
              np.array([[27.5, 2.0, 2.0], [28.5, 2.0, 2.0], [29.5, 2.0, 2.0], [0.5, 2.0, 2.0]])]
    _trajectory(directory, frames, names=NAMES, resindex=[0] * 4, resnames=['ALA'], resids=[1], box=(30.0,) * 3)


def test_pbc_mol_makes_a_split_molecule_whole_and_wraps_its_centre_into_the_box(tmp_path):
    work = tmp_path / 'work'
    _crossing(work)

    frame_series.run(work, _payload(pbc='mol'))

    models = _models(work / 'run-frames.pdb')
    assert models[1][:, 0] == pytest.approx([-0.5, 0.5, 1.5, 2.5], abs=1e-2), \
        'the split molecule was not made whole and moved to its nearest image'
    assert models[2][:, 0] == pytest.approx([27.5, 28.5, 29.5, 30.5], abs=1e-2)
    assert 'pbc mol' in (work / 'run-frames.pdb').read_text()
    record = json.loads((work / 'frames.json').read_text())
    assert record['view']['pbc'] == 'mol'


def test_pbc_whole_makes_the_molecule_whole_and_leaves_its_image_where_it_is(tmp_path):
    work = tmp_path / 'work'
    _crossing(work)

    frame_series.run(work, _payload(pbc='whole'))

    models = _models(work / 'run-frames.pdb')
    assert models[1][:, 0] == pytest.approx([29.5, 30.5, 31.5, 32.5], abs=1e-2)
    assert models[2][:, 0] == pytest.approx([27.5, 28.5, 29.5, 30.5], abs=1e-2)


def test_nojump_reads_every_frame_of_the_window_not_only_the_sampled_ones(tmp_path):
    """The molecule travels 10 Å a frame; sampling every second frame would read a 20 Å jump and move it a box back."""
    frames = [np.array([[2.0 + 10.0 * step, 2.0, 2.0], [3.0 + 10.0 * step, 2.0, 2.0],
                        [4.0 + 10.0 * step, 2.0, 2.0], [5.0 + 10.0 * step, 2.0, 2.0]]) for step in range(3)]
    work = tmp_path / 'work'
    _trajectory(work, frames, names=NAMES, resindex=[0] * 4, resnames=['ALA'], resids=[1], box=(30.0,) * 3)

    frame_series.run(work, _payload(pbc='nojump', interval_ns=0.02))

    models = _models(work / 'run-frames.pdb')
    assert models[-1][:, 0] == pytest.approx([22.0, 23.0, 24.0, 25.0], abs=1e-2), \
        'nojump was applied only to the sampled frames, so its history is not the one `gmx trjconv` reads'


def test_centre_puts_the_group_at_the_box_centre(tmp_path):
    work = tmp_path / 'work'
    _crossing(work)

    frame_series.run(work, _payload(center=True, group='solute'))

    models = _models(work / 'run-frames.pdb')
    assert models[0].mean(axis=0) == pytest.approx([15.0, 15.0, 15.0], abs=1e-2)
    text = (work / 'run-frames.pdb').read_text()
    assert 'centred the solute group at the box centre' in text
    assert 'pbc' not in text.split('VIEW MODIFICATIONS')[1].split('\n')[0]


def test_centre_uses_the_trajectorys_triclinic_box_vectors(tmp_path):
    """The old display assembly assumed an orthogonal box; MDAnalysis's centre uses the box it is handed."""
    work = tmp_path / 'work'
    frames = [np.array([[2.0, 2.0, 2.0], [3.0, 2.0, 2.0], [4.0, 2.0, 2.0], [5.0, 2.0, 2.0]])] * 2
    _trajectory(work, frames, names=NAMES, resindex=[0] * 4, resnames=['ALA'], resids=[1],
                box=(30.0, 30.0, 30.0, 60.0, 70.0, 80.0))
    probe = mda.Universe(str(work / 'traj.gro'), str(work / 'traj.xtc'))
    probe.trajectory[0]
    expected = np.asarray(probe.trajectory.ts.triclinic_dimensions, dtype=float).sum(axis=0) / 2.0

    frame_series.run(work, _payload(center=True, group='solute'))

    assert _models(work / 'run-frames.pdb')[0].mean(axis=0) == pytest.approx(expected, abs=1e-2)


def test_boxcenter_rect_and_zero_move_the_group_to_their_own_centre(tmp_path):
    """`rect` is half the box diagonal, `zero` the origin; both are recorded and named in the file."""
    work = tmp_path / 'work'
    _crossing(work)

    frame_series.run(work, _payload(center=True, group='solute', boxcenter='rect'))
    record = json.loads((work / 'frames.json').read_text())
    assert record['view']['boxcenter'] == 'rect'
    assert _models(work / 'run-frames.pdb')[0].mean(axis=0) == pytest.approx([15.0, 15.0, 15.0], abs=1e-2)
    assert 'boxcenter rect' in (work / 'run-frames.pdb').read_text()

    frame_series.run(work, _payload(center=True, group='solute', boxcenter='zero'))
    assert _models(work / 'run-frames.pdb')[0].mean(axis=0) == pytest.approx([0.0, 0.0, 0.0], abs=1e-2)
    text = (work / 'run-frames.pdb').read_text()
    assert 'centred the solute group at the origin (boxcenter zero)' in text


def test_boxcenter_does_nothing_without_centre(tmp_path):
    work = tmp_path / 'work'
    _crossing(work)
    frame_series.run(work, _payload(pbc='mol'))
    expected = _models(work / 'run-frames.pdb')

    frame_series.run(work, _payload(pbc='mol', boxcenter='rect'))

    assert _models(work / 'run-frames.pdb') == pytest.approx(expected, abs=0.0), \
        'boxcenter moved a wrapped series that was not centred'
    assert 'boxcenter' not in (work / 'run-frames.pdb').read_text()


def test_a_pbc_or_centre_request_without_a_box_is_refused(tmp_path):
    work = tmp_path / 'work'
    _trajectory(work, _moved(2), resindex=[0] * 4, resnames=['DDM'], resids=[1])

    for payload in (_payload(pbc='mol'), _payload(center=True)):
        with pytest.raises(ValueError, match='needs a box'):
            frame_series.run(work, payload)


def test_a_legacy_assembled_request_is_read_as_pbc_mol_and_centre(tmp_path):
    work = tmp_path / 'work'
    _crossing(work)
    frame_series.run(work, _payload(pbc='mol', center=True))
    expected = _models(work / 'run-frames.pdb')

    result = frame_series.run(work, _payload(assembled=True))

    assert _models(work / 'run-frames.pdb') == pytest.approx(expected, abs=0.0), \
        'assembled no longer maps to the pbc/centre view it stood for'
    record = json.loads((work / 'frames.json').read_text())
    assert record['args'] == _payload(assembled=True), 'the old payload was relabelled in the record'
    assert record['view'] == dict(DEFAULTS, pbc='mol', center=True)
    assert record['legacy'] == ['assembled']
    assert result['legacy'] == ['assembled'] and result['view']['pbc'] == 'mol'
    text = (work / 'run-frames.pdb').read_text()
    assert 'VIEW MODIFICATIONS' in text and 'pbc mol' in text
    assert "requested as the old assembled" in text


def test_default_arguments_write_the_trajectorys_own_coordinates(tmp_path):
    work = tmp_path / 'work'
    _crossing(work)

    frame_series.run(work, _payload())

    models = _models(work / 'run-frames.pdb')
    assert models[1][:, 0] == pytest.approx([29.5, 0.5, 1.5, 2.5], abs=1e-2)
    assert 'VIEW MODIFICATIONS' not in (work / 'run-frames.pdb').read_text()


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

    frame_series.run(work, _payload(interval_ns=0.01))
    assert 'CONECT' in (work / 'run-frames.pdb').read_text(), 'the fixture does not bond the all-atom series'

    result = frame_series.run(work, _payload(interval_ns=0.01, atoms='ca'))

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
VIEW_KEYS = {'interval_ns': 0.5, 'pbc': 'nojump', 'center': True, 'fit': 'rot+trans', 'group': 'protein'}


def test_sources_are_the_chosen_pair_and_the_writer_inputs_the_run_holds(tmp_path):
    root = _run_tree(tmp_path / 'run')

    entries = frame_series.sources(root, dict(PAYLOAD_STAGES, colour='blue', **VIEW_KEYS))

    assert set(entries) == {*PAYLOAD_STAGES.values(), 'stages/2_mapping/model.json',
                            'stages/02_system/detergent_CG.itp', 'stages/02_system/cg/molecule_1.itp'}, sorted(entries)
    assert entries[PAYLOAD_STAGES['trajectory']] == root / PAYLOAD_STAGES['trajectory']
    assert entries['stages/2_mapping/model.json'] == root / 'stages/2_mapping/model.json'
    assert entries['stages/02_system/detergent_CG.itp'] == root / 'stages/02_system/detergent_CG.itp'


def test_a_cluster_request_stages_the_run_input_beside_the_trajectory(tmp_path):
    root = _run_tree(tmp_path / 'run')
    tpr = root / 'stages/4_CG_sim/prod/lig_CG.tpr'
    tpr.write_bytes(b'tpr bytes')

    entries = frame_series.sources(root, dict(PAYLOAD_STAGES, pbc='cluster'))

    assert entries['stages/4_CG_sim/prod/lig_CG.tpr'] == tpr

    plain = frame_series.sources(root, dict(PAYLOAD_STAGES, pbc='mol'))
    assert 'stages/4_CG_sim/prod/lig_CG.tpr' not in plain, 'a non-cluster request staged a tpr it never reads'


def test_a_cluster_request_without_a_run_input_is_refused_at_queue_time(tmp_path):
    root = _run_tree(tmp_path / 'run')

    with pytest.raises(ValueError) as refused:
        frame_series.sources(root, dict(PAYLOAD_STAGES, pbc='cluster'))

    message = str(refused.value)
    assert 'no .tpr' in message and 'cluster' in message, message


def test_the_run_input_falls_back_to_run_then_topol(tmp_path):
    root = _run_tree(tmp_path / 'run')
    directory = root / 'stages/4_CG_sim/prod'
    (directory / 'run.tpr').write_bytes(b'tpr bytes')
    assert frame_series.sources(root, dict(PAYLOAD_STAGES, pbc='cluster'))[
        'stages/4_CG_sim/prod/run.tpr'] == directory / 'run.tpr'
    (directory / 'run.tpr').unlink()
    (directory / 'topol.tpr').write_bytes(b'tpr bytes')
    assert frame_series.sources(root, dict(PAYLOAD_STAGES, pbc='cluster'))[
        'stages/4_CG_sim/prod/topol.tpr'] == directory / 'topol.tpr'


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
    (_payload(interval_ns=0), 'interval_ns'),
    (_payload(interval_ns=-0.1), 'interval_ns'),
    (_payload(interval_ns=float('inf')), 'interval_ns'),
    (_payload(interval_ns=True), 'interval_ns'),
    (_payload(interval_ns='soon'), 'interval_ns'),
    (_payload(stride=0), 'stride'),
    (_payload(stride=1.5), 'stride'),
    (_payload(stride=True), 'stride'),
    (_payload(stride='slow'), 'stride'),
    (_payload(pbc='compact'), 'pbc'),
    (_payload(boxcenter='compact'), 'boxcenter'),
    (_payload(boxcenter=None), 'boxcenter'),
    (_payload(center='yes'), 'center'),
    (_payload(fit='all'), 'fit'),
    (_payload(fit=None), 'fit'),
    (_payload(fit='beads'), 'fragment'),
    (_payload(fit='beads', fragment='AB'), 'fragment'),
    (_payload(fit='beads', fragment='2'), 'fragment'),
    (_payload(group='water'), 'group'),
    (_payload(group='fragment:AB'), 'group'),
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


# --- An all-atom run's own topology: its shim, the include it follows, and the one CONECT block a series writes ----

AA_STAGES = {'trajectory': 'stages/07_reference/lig.xtc', 'structure': 'stages/07_reference/lig.gro'}


def _aa_run_tree(root):
    """An `aa_only` run as `aa.prepare_run` writes it: the solute pair and a one-line topology shim over the store.

    The shim's include is absolute on a real run -- the molecule is read where it is stored rather than copied -- so
    the stored molecule here sits in the run's own tree and the shim points at it by absolute path, which is the
    shape the live LMNG run `619ab118abd6` holds.
    """
    root = Path(root)
    (root / 'stages/common/molecule').mkdir(parents=True)
    stored = root / 'molecules/DDM/lig1.itp'
    stored.parent.mkdir(parents=True)
    stored.write_text(ddm_moleculetype())
    (root / 'stages/common/molecule/molecule.itp').write_text(f'#include "{stored}"\n')
    (root / 'manifest.json').write_text(json.dumps({'run_type': 'aa_only', 'stages': []}))
    _trajectory(root / 'stages/07_reference', _moved(3, atoms=len(DDM_BEADS)), names=DDM_BEADS,
                resindex=[0] * len(DDM_BEADS), resnames=['DDM'], resids=[1], stem='lig')
    return root


def _stage(root, work, payload):
    """The work directory the worker makes: every source the hook names, under its own run-relative spelling."""
    for relative, path in frame_series.sources(root, payload).items():
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy2(root / 'manifest.json', work / 'manifest.json')
    return work


def _molecule_pairs(topology):
    """The moleculetype's bonds as the PDB's serials, in the order the writer emits them for one molecule."""
    return [(first, second) for first, second in (*topology['bonds'], *topology['constraints'])]


def test_an_aa_only_run_stages_the_moleculetype_its_shim_includes(tmp_path):
    """The run's own `common/molecule/molecule.itp` is the entry point, and one include names the molecule.

    Measured on `619ab118abd6` (an `aa_only` LMNG run): `analyses/frame-series/run-frames.pdb` holds 157 atoms a model
    and 0 CONECT, because the layout had no `aa_only` resolver, so the writer was handed no topology at all -- and
    with one, the shim states no atoms until its include is followed.
    """
    root = _aa_run_tree(tmp_path / 'run')

    entries = frame_series.sources(root, AA_STAGES)

    assert entries['stages/common/molecule/molecule.itp'] == root / 'stages/common/molecule/molecule.itp'


def test_an_aa_only_series_carries_its_moleculetypes_bonds_in_one_block(tmp_path):
    """The whole AA path: the shim resolves, the include follows, and the bonds reach the file once, for every model."""
    root = _aa_run_tree(tmp_path / 'run')
    work = _stage(root, tmp_path / 'work', AA_STAGES)
    topology = structures.read_moleculetype(root / 'stages/common/molecule/molecule.itp')

    frame_series.run(work, AA_STAGES)

    lines = (work / 'run-frames.pdb').read_text().splitlines()
    assert len([line for line in lines if line.startswith('MODEL')]) == 3
    conect = [line for line in lines if line.startswith('CONECT')]
    assert conect == [f'CONECT{first:5d}{second:5d}' for first, second in _molecule_pairs(topology)], \
        'the series does not carry the moleculetype as its own bonds'
    assert len(conect) == len(topology['bonds']) + len(topology['constraints'])
    last_model = max(index for index, line in enumerate(lines) if line.startswith('ENDMDL'))
    assert min(index for index, line in enumerate(lines) if line.startswith('CONECT')) > last_model, \
        'a CONECT record sits inside a model, where the writer no longer states bonds'


def test_a_shims_include_that_climbs_is_refused(tmp_path):
    shim = tmp_path / 'molecule.itp'
    shim.write_text('#include "../elsewhere.itp"\n')

    with pytest.raises(ValueError) as refused:
        structures.read_moleculetype(shim)

    assert 'climbs' in str(refused.value), str(refused.value)


def test_a_shims_included_file_that_is_a_symlink_is_refused(tmp_path):
    target = tmp_path / 'real.itp'
    target.write_text(ddm_moleculetype())
    link = tmp_path / 'link.itp'
    link.symlink_to(target)
    shim = tmp_path / 'molecule.itp'
    shim.write_text(f'#include "{link.name}"\n')

    with pytest.raises(ValueError) as refused:
        structures.read_moleculetype(shim)

    assert 'symlink' in str(refused.value), str(refused.value)


def test_a_moleculetype_that_states_its_own_atoms_does_not_follow_its_include(tmp_path):
    """A real moleculetype's include names a force field or a library; reading that in would bond another molecule."""
    library = tmp_path / 'library.itp'
    library.write_text('[ moleculetype ]\nOTHER 1\n\n[ atoms ]\n1 C1 1 X A 1 0 54\n\n[ bonds ]\n1 2 1 0.4 5000\n')
    molecule = tmp_path / 'molecule.itp'
    molecule.write_text(f'#include "{library.name}"\n\n[ moleculetype ]\nDDM 1\n\n[ atoms ]\n'
                        '1 SP1r 1 DDM S1A 1 0 54\n')

    model = structures.read_moleculetype(molecule)

    assert model['atoms'] == ['S1A'], 'an include was spliced into a moleculetype that states its own atoms'
    assert model['bonds'] == []


# --- The differential check: the same atoms, within PDB rounding, as `gmx trjconv` ------------------------------

TOPOLOGY = """[ defaults ]
1 1 no 1.0 1.0

[ atomtypes ]
B01    6       1.0   0.0     A      0.0 0.0

[ moleculetype ]
MOL 3

[ atoms ]
1 B01 1 ALA B01 1 0.0 1.0
2 B01 1 ALA B02 2 0.0 1.0
3 B01 1 ALA B03 3 0.0 1.0
4 B01 1 ALA B04 4 0.0 1.0

[ bonds ]
1 2 1 0.1 1000
2 3 1 0.1 1000
3 4 1 0.1 1000

[ system ]
test system

[ molecules ]
MOL 1
"""

MDP = """integrator = md
nsteps = 0
cutoff-scheme = Verlet
"""


def _gmx(cwd, *arguments, selection='0\n0\n'):
    """Run a GROMACS command in the fixture directory; a non-zero exit is the test's failure with its own output."""
    done = subprocess.run([GMX, *arguments], cwd=str(cwd), input=selection, capture_output=True, text=True)
    assert done.returncode == 0, f'{arguments[0]} failed:\n{done.stdout}\n{done.stderr}'
    return done


def _gmx_models(path):
    """Every model's coordinates in ångström from a PDB: GROMACS writes `ATOM`, this writer `HETATM`."""
    blocks, current = [], None
    for line in Path(path).read_text().splitlines():
        if line.startswith('MODEL'):
            current = []
        elif line.startswith('ENDMDL'):
            blocks.append(current)
            current = None
        elif current is not None and (line.startswith('ATOM') or line.startswith('HETATM')):
            current.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
    return np.asarray(blocks, dtype=float)


def _gmx_fixture(directory, *, cross=True):
    """The crossing molecule as `_crossing`, or a compact one, plus a topology file `gmx trjconv` can read.

    The compact variant stays away from the boundary: `gmx trjconv -center -boxcenter zero` answers an atom on a box
    face with the upper image, which is a case the differential check deliberately does not ask about.
    """
    directory = Path(directory)
    if cross:
        _crossing(directory)
    else:
        frames = [np.array([[2.0, 2.0, 2.0], [3.0, 2.0, 2.0], [4.0, 2.0, 2.0], [5.0, 2.0, 2.0]]),
                  np.array([[6.0, 2.0, 2.0], [7.0, 2.0, 2.0], [8.0, 2.0, 2.0], [9.0, 2.0, 2.0]])]
        _trajectory(directory, frames, names=NAMES, resindex=[0] * 4, resnames=['ALA'], resids=[1],
                    box=(30.0, 30.0, 30.0))
    (directory / 'topol.top').write_text(TOPOLOGY)
    (directory / 'grompp.mdp').write_text(MDP)
    _gmx(directory, 'grompp', '-f', 'grompp.mdp', '-c', 'traj.gro', '-p', 'topol.top', '-o', 'topol.tpr',
         '-maxwarn', '2', selection='')


def _producer(directory, work, **view):
    directory, work = Path(directory), Path(work)
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy2(directory / 'traj.xtc', work / 'traj.xtc')
    shutil.copy2(directory / 'traj.gro', work / 'traj.gro')
    payload = {'trajectory': 'traj.xtc', 'structure': 'traj.gro'}
    payload.update(view)
    frame_series.run(work, payload)
    return _models(work / 'run-frames.pdb')


@pytest.mark.slow
@pytest.mark.skipif(GMX is None, reason='gmx is not resolvable from config/tools.json; the trjconv differential check '
                                        'needs GROMACS')
def test_pbc_mol_and_centre_match_gmx_trjconv(tmp_path):
    directory = tmp_path / 'gmx'
    _gmx_fixture(directory)
    _gmx(directory, 'trjconv', '-s', 'topol.tpr', '-f', 'traj.xtc', '-o', 'reference.pdb', '-pbc', 'mol', '-center')
    reference = _gmx_models(directory / 'reference.pdb')

    ours = _producer(directory, tmp_path / 'work', pbc='mol', center=True)

    deviation = float(np.abs(ours - reference).max())
    assert ours.shape == reference.shape
    assert deviation <= 0.001, f'the same atoms differ by {deviation:.6f} Å from gmx trjconv'


@pytest.mark.slow
@pytest.mark.skipif(GMX is None, reason='gmx is not resolvable from config/tools.json; the trjconv differential check '
                                        'needs GROMACS')
def test_pbc_nojump_matches_gmx_trjconv(tmp_path):
    directory = tmp_path / 'gmx'
    _gmx_fixture(directory)
    _gmx(directory, 'trjconv', '-s', 'topol.tpr', '-f', 'traj.xtc', '-o', 'reference.pdb', '-pbc', 'nojump')
    reference = _gmx_models(directory / 'reference.pdb')

    ours = _producer(directory, tmp_path / 'work', pbc='nojump')

    deviation = float(np.abs(ours - reference).max())
    assert ours.shape == reference.shape
    assert deviation <= 0.001, f'the same atoms differ by {deviation:.6f} Å from gmx trjconv'


def _gmx_cluster(directory, group=None, n_atoms=4):
    """`gmx trjconv -pbc cluster` on the whole fixture, with the same two index groups the producer builds.

    `-n` replaces GROMACS' default groups, so the output group has to be in the file too; a file naming only the
    clustering group made the live empty-micelle build write 1,650 of its 8,604 atoms.
    """
    group = list(group) if group is not None else list(range(1, n_atoms + 1))
    members = ' '.join(str(index) for index in group)
    everyone = ' '.join(str(index) for index in range(1, n_atoms + 1))
    (directory / 'view.ndx').write_text(f'[ view ]\n{members}\n[ System ]\n{everyone}\n')
    done = subprocess.run([GMX, 'trjconv', '-s', 'topol.tpr', '-f', 'traj.xtc', '-o', 'reference.pdb',
                           '-pbc', 'cluster', '-n', 'view.ndx'],
                          cwd=str(directory), input='0\n1\n', capture_output=True, text=True)
    assert done.returncode == 0, f'trjconv -pbc cluster failed:\n{done.stdout}\n{done.stderr}'
    return _gmx_models(directory / 'reference.pdb')


def _clustered_producer(directory, work, **view):
    """The producer with a `.tpr` staged beside the trajectory, as `sources` would stage it for cluster."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    for name in ('traj.xtc', 'traj.gro'):
        shutil.copy2(Path(directory) / name, work / name)
    shutil.copy2(Path(directory) / 'topol.tpr', work / 'traj.tpr')
    payload = {'trajectory': 'traj.xtc', 'structure': 'traj.gro'}
    payload.update(view)
    frame_series.run(work, payload)
    return _models(work / 'run-frames.pdb')


WATER_TOPOLOGY = """[ defaults ]
1 1 no 1.0 1.0

[ atomtypes ]
B01    6       1.0   0.0     A      0.0 0.0

[ moleculetype ]
MOL 3

[ atoms ]
1 B01 1 ALA B01 1 0.0 1.0
2 B01 1 ALA B02 2 0.0 1.0
3 B01 1 ALA B03 3 0.0 1.0
4 B01 1 ALA B04 4 0.0 1.0

[ bonds ]
1 2 1 0.1 1000
2 3 1 0.1 1000
3 4 1 0.1 1000

[ moleculetype ]
W 1

[ atoms ]
1 B01 1 W B01 1 0.0 1.0
2 B01 1 W B02 2 0.0 1.0

[ bonds ]
1 2 1 0.1 1000

[ system ]
test system with water

[ molecules ]
MOL 1
W 1
"""


def _water_fixture(directory):
    """A solute molecule and a water molecule: `group: solute` is then a strict subset of the system.

    The live empty-micelle build clustered its 1,650 solute atoms and wrote 1,650 back instead of the 8,604-atom
    system, because the index file named only the clustering group. This fixture is the smallest system that makes
    that difference visible.
    """
    directory = Path(directory)
    frames = [np.array([[2.0, 2.0, 2.0], [3.0, 2.0, 2.0], [4.0, 2.0, 2.0], [5.0, 2.0, 2.0],
                        [10.0, 10.0, 10.0], [11.0, 10.0, 10.0]]),
              np.array([[2.5, 2.0, 2.0], [3.5, 2.0, 2.0], [4.5, 2.0, 2.0], [5.5, 2.0, 2.0],
                        [10.5, 10.0, 10.0], [11.5, 10.0, 10.0]])]
    _trajectory(directory, frames, names=['B01'] * 4 + ['B01'] * 2, resindex=[0] * 4 + [1] * 2,
                resnames=['ALA', 'W'], resids=[1, 2], box=(30.0, 30.0, 30.0))
    (directory / 'topol.top').write_text(WATER_TOPOLOGY)
    (directory / 'grompp.mdp').write_text(MDP)
    _gmx(directory, 'grompp', '-f', 'grompp.mdp', '-c', 'traj.gro', '-p', 'topol.top', '-o', 'topol.tpr',
         '-maxwarn', '2', selection='')


@pytest.mark.slow
@pytest.mark.skipif(GMX is None, reason='gmx is not resolvable from config/tools.json; the trjconv differential check '
                                        'needs GROMACS')
def test_cluster_writes_the_whole_system_even_when_the_group_is_a_subset(tmp_path):
    """The regression: a clustering group that is only the solute must still produce every atom, not the solute alone.

    The producer refuses an output whose atom count does not match the topology, so failing before the index file
    named the output group was a hard error on the live run; this fixture proves the written system is whole.
    """
    directory = tmp_path / 'gmx'
    _water_fixture(directory)
    work = tmp_path / 'work'

    ours = _clustered_producer(directory, work, pbc='cluster', group='solute')

    assert ours.shape[1] == 4, 'the writer keeps the solute and drops water'
    record = json.loads((work / 'frames.json').read_text())
    assert record['view']['pbc'] == 'cluster'
    assert not list(work.glob('frame-series-cluster-*')), 'a cluster temp file was published as an output'


def test_the_cluster_index_names_the_view_and_the_whole_system(tmp_path):
    """`-n` replaces GROMACS' default groups, so the output group has to be written into the index file too."""
    path = tmp_path / 'view.ndx'
    frame_series._write_ndx(path, np.array([0, 2]), 4)
    text = path.read_text()
    view = text.split('[ view ]', 1)[1].split('[ System ]', 1)[0].split()
    system = text.split('[ System ]', 1)[1].split()
    assert view == ['1', '3']
    assert system == ['1', '2', '3', '4']


@pytest.mark.slow
@pytest.mark.skipif(GMX is None, reason='gmx is not resolvable from config/tools.json; the trjconv differential check '
                                        'needs GROMACS')
@pytest.mark.parametrize('mode', ['res', 'atom'])
def test_pbc_res_and_atom_match_gmx_trjconv(tmp_path, mode):
    directory = tmp_path / 'gmx'
    _gmx_fixture(directory)
    _gmx(directory, 'trjconv', '-s', 'topol.tpr', '-f', 'traj.xtc', '-o', 'reference.pdb', '-pbc', mode)
    reference = _gmx_models(directory / 'reference.pdb')

    ours = _producer(directory, tmp_path / 'work', pbc=mode)

    deviation = float(np.abs(ours - reference).max())
    assert ours.shape == reference.shape
    assert deviation <= 0.001, f'pbc {mode} differs by {deviation:.6f} Å from gmx trjconv'
    assert f'pbc {mode}' in (tmp_path / 'work' / 'run-frames.pdb').read_text()


@pytest.mark.slow
@pytest.mark.skipif(GMX is None, reason='gmx is not resolvable from config/tools.json; the trjconv differential check '
                                        'needs GROMACS')
@pytest.mark.parametrize('boxcenter', ['tric', 'rect'])
def test_centre_boxcenter_matches_gmx_trjconv(tmp_path, boxcenter):
    directory = tmp_path / 'gmx'
    _gmx_fixture(directory)
    _gmx(directory, 'trjconv', '-s', 'topol.tpr', '-f', 'traj.xtc', '-o', 'reference.pdb',
         '-pbc', 'mol', '-center', '-boxcenter', boxcenter)
    reference = _gmx_models(directory / 'reference.pdb')

    ours = _producer(directory, tmp_path / 'work', pbc='mol', center=True, boxcenter=boxcenter)

    deviation = float(np.abs(ours - reference).max())
    assert ours.shape == reference.shape
    assert deviation <= 0.001, f'centre with boxcenter {boxcenter} differs by {deviation:.6f} Å from gmx trjconv'


@pytest.mark.slow
@pytest.mark.skipif(GMX is None, reason='gmx is not resolvable from config/tools.json; the trjconv differential check '
                                        'needs GROMACS')
def test_centre_boxcenter_zero_matches_gmx_trjconv(tmp_path):
    """A molecule away from the boundary: a centred COM exactly on one is the case GROMACS answers with an upper image."""
    directory = tmp_path / 'gmx'
    _gmx_fixture(directory, cross=False)
    _gmx(directory, 'trjconv', '-s', 'topol.tpr', '-f', 'traj.xtc', '-o', 'reference.pdb',
         '-pbc', 'mol', '-center', '-boxcenter', 'zero')
    reference = _gmx_models(directory / 'reference.pdb')

    ours = _producer(directory, tmp_path / 'work', pbc='mol', center=True, boxcenter='zero')

    deviation = float(np.abs(ours - reference).max())
    assert ours.shape == reference.shape
    assert deviation <= 0.001, f'centre with boxcenter zero differs by {deviation:.6f} Å from gmx trjconv'


@pytest.mark.slow
@pytest.mark.skipif(GMX is None, reason='gmx is not resolvable from config/tools.json; the trjconv differential check '
                                        'needs GROMACS')
def test_pbc_cluster_matches_gmx_trjconv_and_leaves_no_temp_files(tmp_path):
    directory = tmp_path / 'gmx'
    _gmx_fixture(directory)
    reference = _gmx_cluster(directory)

    work = tmp_path / 'work'
    ours = _clustered_producer(directory, work, pbc='cluster', group='solute')

    deviation = float(np.abs(ours - reference).max())
    assert ours.shape == reference.shape
    assert deviation <= 0.001, f'pbc cluster differs by {deviation:.6f} Å from gmx trjconv'
    text = (work / 'run-frames.pdb').read_text()
    assert 'pbc cluster' in text, 'the file does not say it clustered the frames'
    assert not list(work.glob('frame-series-cluster-*')), 'a cluster temp file was published as an output'
    assert (work / 'run-frames.pdb').is_file() and (work / 'frames.json').is_file()
    # MDAnalysis' own `.xtc_offsets.npz`/`.lock` sidecars are dotted too; a file named for the cluster build is
    # the producer's temporary and must not survive.
    assert not [path for path in work.iterdir() if 'frame-series-cluster' in path.name]


@pytest.mark.skipif(GMX is None, reason='this check asserts the refusal an installed gmx would otherwise satisfy')
def test_a_cluster_request_without_a_run_input_is_refused(tmp_path):
    work = tmp_path / 'work'
    _crossing(work)

    with pytest.raises(ValueError) as refused:
        frame_series.run(work, _payload(pbc='cluster'))

    message = str(refused.value)
    assert 'no .tpr' in message and 'cluster' in message, message
    assert not list(work.glob('frame-series-cluster-*')), 'a refused cluster left a temp file behind'


def test_a_cluster_request_without_gmx_is_refused_with_a_sentence(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    _crossing(work)
    monkeypatch.setattr(frame_series.tools, 'tool_path', lambda *args, **kwargs: None)

    with pytest.raises(ValueError) as refused:
        frame_series.run(work, _payload(pbc='cluster'))

    message = str(refused.value)
    assert 'gmx is not available' in message and 'cluster' in message, message
    assert not list(work.glob('frame-series-cluster-*')), 'a refused cluster left a temp file behind'


def test_a_stable_kind_replaces_its_series_in_place_and_keeps_it_on_failure(tmp_path, monkeypatch):
    """The worker's half of "one stored series per run": the producer's files land in the kind's one directory.

    `execute` is the subprocess the coordinator starts, so calling it here is the same path a real build takes. The
    second build writes different bytes and replaces the pair; the third raises before publishing and leaves the
    second build's bytes -- and its record -- exactly where they were.
    """
    run = tmp_path / 'run'
    (run / 'stages').mkdir(parents=True)

    def produce(work, payload):
        if payload.get('fail'):
            raise ValueError('the trajectory was replaced mid-build')
        (work / 'run-frames.pdb').write_text(payload['body'])
        (work / 'frames.json').write_text(json.dumps({'args': payload}))
        return {'files': ['run-frames.pdb', 'frames.json']}

    monkeypatch.setitem(worker.TABLE, 'stable-fixture',
                        Kind('stable-fixture', (), produce, 'Stable fixture', 'in place', 'unit',
                             stable_directory='analyses/stable-fixture'))
    request = run / 'analyses' / 'stable-fixture' / 'request.json'
    request.parent.mkdir(parents=True)

    def build(payload):
        request.write_text(json.dumps({'run': str(run), 'kind': 'stable-fixture', 'payload': payload,
                                       'code_signature': 'fixture'}))
        worker.execute(request)

    build({'body': 'first pair'})
    directory = run / 'analyses' / 'stable-fixture'
    assert (directory / 'run-frames.pdb').read_text() == 'first pair'
    assert json.loads((directory / 'frames.json').read_text())['args'] == {'body': 'first pair'}
    result = json.loads((directory / 'result.json').read_text())
    assert result['output_directory'] == '.', 'a stable kind must not publish under a content hash'
    assert {'run-frames.pdb', 'frames.json'} <= set(result['outputs_sha256'])
    assert not (directory / 'output').exists(), 'a stable kind minted an attempt tree'
    assert not list(directory.glob('.*.tmp')), 'a publish left its temporary file behind'

    build({'body': 'second pair'})
    assert (directory / 'run-frames.pdb').read_text() == 'second pair'
    assert json.loads((directory / 'frames.json').read_text())['args'] == {'body': 'second pair'}

    with pytest.raises(ValueError):
        build({'fail': True})
    assert (directory / 'run-frames.pdb').read_text() == 'second pair', 'a failed rebuild replaced the series'
    assert json.loads((directory / 'frames.json').read_text())['args'] == {'body': 'second pair'}


def _atoms(names):
    """Three atoms of one residue, shaped as the writer reads them."""
    return [{'name': name, 'residue': 'LIG', 'residue_id': 1, 'position': (0.1 * index, 0.0, 0.0)}
            for index, name in enumerate(names)]


def test_an_all_atom_series_states_each_atoms_own_element():
    """A PDB's element column is what a viewer colours and sizes from; an all-atom file must state the chemistry.

    Measured on `619ab118abd6` before this change: every one of the 157 atoms a model carried was written `C`, so NGL
    drew a molecule of grey spheres whatever the atom was. The size-class stand-in belongs to a coarse-grained file.
    """
    text = structures.series_pdb([_atoms(['C1', 'O1', 'H1'])], atomistic=True, title='atoms')
    records = [line for line in text.splitlines() if line.startswith('HETATM')]

    assert [line[76:78].strip() for line in records] == ['C', 'O', 'H'], records
    assert all(line[60:66].strip() == '0.00' for line in records), 'an all-atom file claims a Martini family'
    assert 'ALL-ATOM SYSTEM AS SET UP' in text
    assert 'ELEMENTS ARE THE ATOMS OWN CHEMICAL ELEMENTS' in text


def test_a_coarse_grained_series_keeps_the_size_class_stand_in():
    """The same names in a bead file are beads, not atoms: its element column stays the model's size-class stand-in."""
    text = structures.series_pdb([_atoms(['C1', 'O1', 'H1'])], atomistic=False, title='beads')
    records = [line for line in text.splitlines() if line.startswith('HETATM')]

    assert [line[76:78].strip() for line in records] == ['C', 'C', 'C'], records
    assert 'COARSE-GRAINED SYSTEM AS SET UP' in text
    assert 'ELEMENTS ARE RADIUS STAND-INS' in text
