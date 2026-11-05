"""What a run's trajectories weigh, as the Runs panel states it to inform deletion.

The size is a directory fact, not a manifest fact: a run interrupted mid-stage, or one migrated from an older
layout, may hold a trajectory file its stage record does not name, and the number exists to tell a reader what
deleting the run would free. So the test writes the files a run really writes and asks the reader what it sees.
"""
from dashboard.analysis.runs import layout


def sparse(path, size):
    """A file of `size` bytes without writing them: the panel reads `st_size`, and a test should not pay disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as handle:
        handle.truncate(size)
    return path


def test_it_sums_every_trajectory_spelling_and_ignores_the_rest(tmp_path):
    layout.clear_trajectory_cache()
    root = tmp_path / 'run'
    sparse(root / 'stages/07_reference/lig.xtc', 1000)
    sparse(root / 'stages/04_nvt/prod/run.trr', 2000)
    sparse(root / 'stages/04_nvt/prod/run.tng', 3000)
    sparse(root / 'stages/04_nvt/prod/run.h5', 4000)
    sparse(root / 'stages/04_nvt/prod/run.edr', 50000)
    sparse(root / 'stages/04_nvt/prod/run.gro', 60000)
    sparse(root / 'stages/04_nvt/prod/run.cpt', 70000)

    assert layout.trajectory_bytes(root) == 10000


def test_it_never_follows_a_symlink(tmp_path):
    layout.clear_trajectory_cache()
    root = tmp_path / 'run'
    sparse(root / 'stages/04_nvt/prod/run.xtc', 1000)
    outside = sparse(tmp_path / 'outside.xtc', 9000)
    (root / 'stages/04_nvt/prod/link.xtc').symlink_to(outside)
    outside_dir = tmp_path / 'outside-dir'
    sparse(outside_dir / 'run.xtc', 7000)
    (root / 'stages/linked').symlink_to(outside_dir, target_is_directory=True)

    assert layout.trajectory_bytes(root) == 1000, 'a symlink is not this run\'s file'


def test_a_missing_run_is_zero_rather_than_an_error(tmp_path):
    layout.clear_trajectory_cache()
    assert layout.trajectory_bytes(tmp_path / 'not-a-run') == 0


def test_the_answer_is_remembered_briefly_and_can_be_forgotten(tmp_path):
    layout.clear_trajectory_cache()
    root = tmp_path / 'run'
    sparse(root / 'run.xtc', 1000)
    assert layout.trajectory_bytes(root) == 1000
    sparse(root / 'run.trr', 2000)
    assert layout.trajectory_bytes(root) == 1000, 'the poll re-reads the directory on every card, so it is cached'
    layout.clear_trajectory_cache()
    assert layout.trajectory_bytes(root) == 3000
