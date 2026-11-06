"""A trajectory's frame count and span, read from its header rather than by walking it.

The measured cost is the point of the module: 0.045 s to open a 1.7 GB, 45,001-frame extension and 0.001 s to seek
its last frame, against about 43 s to walk the file. The fixture writes one frame per 100 ps, so four frames span
0.3 ns -- last frame time minus the first, which is what GROMACS' own total time reports.
"""
import pytest
from dashboard.analysis.runs import trajectory_header

from tests.harness.support import cg_fixture_run

POSITIONS = ((0.1, 0.2, 0.3), (0.4, 0.5, 0.6), (0.7, 0.8, 0.9), (1.0, 1.1, 1.2))


def written(tmp_path, frames=4):
    _run, trajectory, structure, _topology = cg_fixture_run(
        tmp_path, POSITIONS, names=('B01', 'B02', 'B03', 'B04'), frames=frames, frame_ps=100.0)
    return structure, trajectory


def test_a_header_states_the_frame_count_and_the_span(tmp_path):
    structure, trajectory = written(tmp_path)

    answer = trajectory_header.read(structure, trajectory)

    assert answer['frames'] == 4
    assert answer['time_ns'] == pytest.approx(0.3)
    # The window/interval arithmetic in the panel uses these two: the first frame's own time and the stated step.
    assert answer['first_ns'] == pytest.approx(0.0)
    assert answer['dt_ps'] == pytest.approx(100.0)


def test_a_missing_trajectory_answers_none_instead_of_raising(tmp_path):
    structure, _trajectory = written(tmp_path)

    assert trajectory_header.read(structure, tmp_path / 'absent.xtc') is None


def test_an_unreadable_header_answers_none_instead_of_raising(tmp_path):
    structure, trajectory = written(tmp_path)
    trajectory.write_bytes(b'not a trajectory')

    assert trajectory_header.read(structure, trajectory) is None


def test_a_replaced_file_is_a_new_key_not_a_stale_answer(tmp_path):
    structure, trajectory = written(tmp_path, frames=2)
    assert trajectory_header.read(structure, trajectory)['frames'] == 2

    _structure, trajectory = written(tmp_path, frames=5)

    assert trajectory_header.read(structure, trajectory)['frames'] == 5
