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


def _job(index, candidate, ended, status='completed'):
    """One temporary-validation record, keyed on the field the cleanup groups by.

    `mapping_candidate` is the mapping's file name, which is what a job record carries since D1; the grouping
    `temporary.cleanup` does -- five protected per group, not five overall -- rests on it and on nothing else.
    """
    return {'id': f'{candidate[0]}{index:011d}', 'temporary_validation': True,
            'mapping_candidate': candidate, 'status': status, 'ended_at': ended.isoformat()}


def test_cleanup_protects_latest_five_per_mapping_candidate_and_applies_age_cutoffs(tmp_path):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=8)
    jobs = []
    for candidate in ('a-mapping.json', 'b-mapping.json'):
        jobs.extend(_job(index, candidate, old + timedelta(minutes=index)) for index in range(6))
    # A third mapping with fewer than five terminal jobs: every one of them is inside the protected count,
    # whatever its age.
    jobs.extend(_job(index, 'c-mapping.json', old + timedelta(minutes=index)) for index in range(4))
    store = Recorder()

    result = temporary.cleanup(jobs, tmp_path, store, now=now)

    assert store.deleted == ['a00000000000', 'b00000000000'], \
        'one group, one deletion: the latest five of each mapping are protected, and the short group keeps all four'
    assert sorted(entry['id'] for entry in result) == store.deleted
    assert [entry['status'] for entry in result] == ['deleted', 'deleted']

    recent = _job(0, 'a-mapping.json', now - timedelta(days=1))
    assert temporary.cleanup([recent], tmp_path, store, now=now) == []
    assert store.deleted == ['a00000000000', 'b00000000000'], 'a run inside its retention window is left alone'


def test_a_deleted_run_loses_its_files_through_the_same_seam(tmp_path):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=8)
    jobs = [_job(index, 'a-mapping.json', old + timedelta(minutes=index)) for index in range(6)]
    doomed = tmp_path / jobs[0]['id']
    doomed.mkdir()
    (doomed / 'manifest.json').write_text('{}')
    store = Recorder()

    temporary.cleanup(jobs, tmp_path, store, now=now)

    assert store.removed_files == [True], 'the files are removed by the callback the store runs'
    assert not Path(doomed).exists()
