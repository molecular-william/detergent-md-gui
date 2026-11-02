"""Extraction: whole molecules, dropped ones counted, and the local frame the library stores.

The properties a reader would otherwise have to trust are pinned here: a molecule written across the periodic
boundary comes back whole, a broken or non-finite one is dropped and counted, the beads keep the geometry's order,
and every stored molecule sits head-at-origin with its axis along +z.

An `.xtc` cannot hold a non-finite coordinate -- its fixed-point compression has no value for one, and the writer's
in-place arithmetic overruns its buffer -- so the non-finite case is injected where a corrupt frame would put it: at
the frame the extraction reads.
"""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from detergent_pdc.conformations import extract, sources
from detergent_pdc.conformations.sources import TOPOLOGY

from tests.harness.conformation_fixtures import BEADS, itp_text, run_tree


def candidates(tmp_path, **fixture):
    fixture.setdefault('molecules', 4)
    fixture.setdefault('frames', 2)
    run_tree(tmp_path, 'b920391735dd', **fixture)
    return extract.candidates(tmp_path, sources(tmp_path, ['b920391735dd'])[0])


def geometry_points():
    return np.asarray([position for _name, _type, position in BEADS], dtype=float)


def distances(points):
    return np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)


def test_local_frame_head_at_origin_axis_plus_z(tmp_path):
    entries, _counts = candidates(tmp_path)
    beads = np.asarray([entry['beads'] for entry in entries])
    assert beads.shape[1:] == (len(BEADS), 3)
    assert beads[:, :, 2].max() == pytest.approx(0.0, abs=1e-9)
    assert (beads[:, :, 2] <= 0.0).all()
    assert np.isfinite(beads).all()


def test_a_split_molecule_is_made_whole(tmp_path):
    """The first molecule crosses a box face; every stored molecule keeps its geometry's own distances."""
    entries, counts = candidates(tmp_path)
    reference = distances(geometry_points())
    assert len(entries) == counts['kept']
    for entry in entries:
        measured = distances(np.asarray(entry['beads']))
        assert np.allclose(measured, reference, atol=2e-3), entry['source']


def test_descriptors_are_the_four_the_plan_states(tmp_path):
    entries, _counts = candidates(tmp_path)
    for entry in entries:
        length, radius, reach, radial = entry['descriptors']
        beads = np.asarray(entry['beads'])
        # The stored beads are rounded to 1e-4 nm, so a descriptor recomputed from them can differ by that much.
        assert length == pytest.approx(-beads[:, 2].min(), abs=2e-4)
        assert radius == pytest.approx(np.sqrt((beads * beads).sum(axis=1).mean()), abs=2e-4)
        assert reach == pytest.approx(np.linalg.norm(beads, axis=1).max(), abs=2e-4)
        assert radial == pytest.approx(np.hypot(beads[:, 0], beads[:, 1]).max(), abs=2e-4)
        assert 0.0 < length <= reach and 0.0 < radius <= reach and 0.0 < radial <= reach


def test_positions_and_descriptors_are_rounded(tmp_path):
    entries, _counts = candidates(tmp_path)
    for entry in entries:
        for point in entry['beads']:
            for value in point:
                assert value == round(value, 4)
        for value in entry['descriptors']:
            assert value == round(value, 6)


def test_a_broken_molecule_is_dropped_and_counted(tmp_path):
    entries, counts = candidates(tmp_path, broken_molecule=1)
    assert counts == {'kept': 6, 'broken': 2, 'non_finite': 0, 'frames': 2, 'pool': 8, 'stride': 1}
    assert {entry['source']['resid'] for entry in entries} == {1, 3, 4}


def test_a_stretched_bond_is_the_one_dropped(tmp_path):
    """One molecule's own bead is moved 0.3 nm, so its stated bond leaves the band: only that molecule drops."""
    run_tree(tmp_path, 'b920391735dd', molecules=4, frames=1, broken_molecule=1)
    entries, counts = extract.candidates(tmp_path, sources(tmp_path, ['b920391735dd'])[0])
    assert counts == {'kept': 3, 'broken': 1, 'non_finite': 0, 'frames': 1, 'pool': 4, 'stride': 1}
    assert {entry['source']['resid'] for entry in entries} == {1, 3, 4}


def test_the_topologys_stated_length_is_the_reference(tmp_path):
    """The geometry would call these molecules whole; the run's own b0 says the pair is stretched, so they drop.

    This is the reference run's defect in miniature: its 2-5 states 0.334 while the geometry implies 0.2696, so a
    geometry reference drops molecules a frame supports. Here the stated length is moved away from the geometry and
    the extraction follows the statement.
    """
    fixture = run_tree(tmp_path, 'b920391735dd', molecules=2, frames=1)
    (fixture['inputs'] / TOPOLOGY).write_text(itp_text(overrides={(2, 5): 0.5392}))
    entries, counts = extract.candidates(tmp_path, sources(tmp_path, ['b920391735dd'])[0])
    assert entries == []
    assert counts['kept'] == 0 and counts['broken'] == counts['pool']


def test_a_non_finite_molecule_is_dropped_and_counted(tmp_path, monkeypatch):
    """A corrupt frame's NaN bead drops its molecule and no other; the rest of the frame is still used."""
    run_tree(tmp_path, 'b920391735dd', molecules=4, frames=2)
    record = sources(tmp_path, ['b920391735dd'])[0]
    opened = extract._universe

    def corrupting(mda, source, directory):
        universe, residues, fragments = opened(mda, source, directory)
        return SimpleNamespace(trajectory=_Corrupting(universe, residues[2][1][0]), atoms=universe.atoms), \
            residues, fragments

    monkeypatch.setattr(extract, '_universe', corrupting)
    entries, counts = extract.candidates(tmp_path, record)
    assert counts == {'kept': 7, 'broken': 0, 'non_finite': 1, 'frames': 2, 'pool': 8, 'stride': 1}
    # Frame 0 still holds all four molecules; only residue 3 is gone from the corrupted second frame.
    assert [entry['source']['resid'] for entry in entries if entry['source']['time_ns'] > 0.0] == [1, 2, 4]


class _Corrupting:
    """One trajectory whose second frame carries a NaN bead, as a torn `.xtc` frame would.

    It supports the stride slice the extraction takes, so the injection happens on the frames that are actually read.
    """

    def __init__(self, universe, atom, frames=None):
        self.universe = universe
        self.atom = atom
        self.frames = frames if frames is not None else universe.trajectory

    def __getitem__(self, selection):
        return _Corrupting(self.universe, self.atom, self.universe.trajectory[selection])

    def __len__(self):
        return len(self.frames)

    def __iter__(self):
        for timestep in self.frames:
            if timestep.frame == 1:
                positions = self.universe.atoms.positions
                positions[self.atom] = np.nan
                self.universe.atoms.positions = positions
            yield timestep


def test_counts_add_up_and_name_the_source(tmp_path):
    entries, counts = candidates(tmp_path)
    assert counts['frames'] == 2
    assert counts['pool'] == 8
    assert counts['kept'] + counts['broken'] + counts['non_finite'] == counts['pool']
    times = sorted({entry['source']['time_ns'] for entry in entries})
    assert times == [0.0, 0.1]
    assert counts['stride'] == 1  # a short trajectory is read frame by frame
    assert [entry['source']['run'] for entry in entries] == [0] * len(entries)
    assert [entry['source']['resid'] for entry in entries] == [1, 2, 3, 4, 1, 2, 3, 4]


def test_more_frames_than_the_cap_are_sampled_evenly(tmp_path):
    """The cap is a stride, not a prefix: the pool reaches the last frame, and the step is recorded."""
    run_tree(tmp_path, 'b920391735dd', molecules=2, frames=401)
    record = sources(tmp_path, ['b920391735dd'])[0]
    entries, counts = extract.candidates(tmp_path, record)
    assert counts['stride'] == 2
    assert counts['frames'] == extract.MAX_FRAMES + 1
    assert counts['pool'] == counts['frames'] * 2
    assert counts['kept'] == counts['pool']
    times = sorted({entry['source']['time_ns'] for entry in entries})
    assert len(times) == extract.MAX_FRAMES + 1
    assert times[0] == pytest.approx(0.0)
    assert times[1] == pytest.approx(0.2), 'frame 1 is skipped, so the step is two written frames'
    assert times[-1] == pytest.approx(40.0), 'the last written frame, not the 201st from the start'


def test_extraction_leaves_the_run_directory_untouched(tmp_path):
    """A run's stage files are immutable; MDAnalysis' offsets cache belongs in the build's temp directory."""
    fixture = run_tree(tmp_path, 'b920391735dd', molecules=2, frames=2)
    record = sources(tmp_path, ['b920391735dd'])[0]
    prod = fixture['stage_root'] / '06_assessment' / 'prod'
    before = snapshot(prod)
    assert not any('offsets' in name for name in before)
    extract.candidates(tmp_path, record)
    assert snapshot(prod) == before


def snapshot(directory):
    return {path.name: (path.stat().st_mtime_ns, path.stat().st_size) for path in Path(directory).iterdir()}


def test_a_trajectory_without_a_box_is_refused(tmp_path):
    """Without a box no molecule can be made whole, so the run is refused rather than read as if it were."""
    run_tree(tmp_path, 'b920391735dd', boxed=False)
    with pytest.raises(ValueError) as error:
        extract.candidates(tmp_path, sources(tmp_path, ['b920391735dd'])[0])
    assert 'states no box' in str(error.value)
    assert 'b920391735dd' in str(error.value)


def test_a_geometry_the_trajectory_does_not_hold_is_refused(tmp_path):
    run_tree(tmp_path, 'b920391735dd', molecules=2, frames=1)
    found = sources(tmp_path, ['b920391735dd'])[0]
    found['beads'] = [*found['beads'], {'name': 'GHOST', 'type': 'C1', 'position': [0.0, 0.0, 0.0]}]
    with pytest.raises(ValueError) as error:
        extract.candidates(tmp_path, found)
    assert 'GHOST' in str(error.value)
