from pathlib import Path

import pytest

from dashboard.cli.reset_workspace import reset_workspace


def test_reset_removes_only_generated_targets(tmp_path):
    (tmp_path / 'runs' / 'abc').mkdir(parents=True)
    (tmp_path / 'runs' / 'abc' / 'output.dat').write_text('generated')
    (tmp_path / 'jobs.sqlite3').write_bytes(b'state')
    (tmp_path / 'molecules').mkdir()
    (tmp_path / 'molecules' / 'source.pdb').write_text('canonical')
    report = reset_workspace(tmp_path, confirm=True, now=lambda: '2026-09-21T00:00:00+00:00')
    assert 'runs' in report['deleted']
    assert not (tmp_path / 'runs' / 'abc').exists()
    assert (tmp_path / 'molecules' / 'source.pdb').read_text() == 'canonical'
    assert (tmp_path / 'reset-record.json').is_file()
    assert all((tmp_path / name).is_dir() for name in report['recreated'])


def test_reset_requires_confirmation_and_rejects_active_service(tmp_path):
    with pytest.raises(ValueError, match='confirm'):
        reset_workspace(tmp_path, confirm=False)
    lock = tmp_path / 'jobs.service.lock'
    lock.write_text('')
    with lock.open('r+') as stream:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='active'):
            reset_workspace(tmp_path, confirm=True)
