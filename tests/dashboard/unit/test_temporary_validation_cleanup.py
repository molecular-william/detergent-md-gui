from datetime import datetime, timedelta, timezone
from pathlib import Path

from dashboard.execution.coordination import temporary


class Recorder:
    """Stands in for the store: the one seam a deletion may go through.

    The real store checks retained dependencies under the DB lock before it removes the
    files and the record, which is why the callable pair became an object.
    """

    def __init__(self):
        self.deleted = []
        self.removed_files = []

    def delete_with_cleanup(self, jid, cleanup):
        cleanup()
        self.deleted.append(jid)
        self.removed_files.append(True)


def test_cleanup_protects_latest_five_and_applies_age_cutoffs(tmp_path):
    now = datetime.now(timezone.utc)
    jobs = []
    for i in range(6):
        jobs.append({'id': f'{i:012x}', 'temporary_validation': True, 'bonded_state_id': 's',
                     'status': 'completed', 'ended_at': (now - timedelta(days=8) + timedelta(minutes=i)).isoformat()})
    store = Recorder()
    result = temporary.cleanup(jobs, tmp_path, store, now=now)
    assert store.deleted == ['000000000000'], 'the oldest of six goes; the latest five are protected'
    assert any(x['status'] == 'deleted' for x in result)
    recent = {'id': 'recent000001', 'temporary_validation': True, 'bonded_state_id': 's',
              'status': 'completed', 'ended_at': (now - timedelta(days=1)).isoformat()}
    assert temporary.cleanup([recent], tmp_path, store, now=now) == []
    assert store.deleted == ['000000000000'], 'a run inside its retention window is left alone'


def test_a_deleted_run_loses_its_files_through_the_same_seam(tmp_path):
    now = datetime.now(timezone.utc)
    jobs = []
    for i in range(6):
        jobs.append({'id': f'{i:012x}', 'temporary_validation': True, 'bonded_state_id': 's',
                     'status': 'completed', 'ended_at': (now - timedelta(days=8) + timedelta(minutes=i)).isoformat()})
    doomed = tmp_path / '000000000000'
    doomed.mkdir()
    (doomed / 'manifest.json').write_text('{}')
    store = Recorder()
    temporary.cleanup(jobs, tmp_path, store, now=now)
    assert store.removed_files == [True], 'the files are removed by the callback the store runs'
    assert not Path(doomed).exists()
