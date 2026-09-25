"""AA sources cannot disappear underneath retained CG consumers."""
import pytest

from dashboard.store import Store


def test_pair_insertion_is_atomic_and_requires_source(tmp_path):
    store = Store(tmp_path/'jobs.sqlite3')
    source = {'id': '111111111111', 'run_type': 'aa_only', 'status': 'queued'}
    child = {'id': '222222222222', 'run_type': 'aa_cg', 'status': 'waiting',
             'reference_run_id': source['id']}
    with pytest.raises(ValueError, match='source'):
        store.insert(child)
    assert store.all() == []
    store.insert_many([source, child])
    assert store.get(child['id'])['reference_run_id'] == source['id']


def test_completed_consumers_protect_source_before_cleanup(tmp_path):
    store = Store(tmp_path/'jobs.sqlite3')
    source = {'id': '111111111111', 'run_type': 'aa_only', 'status': 'completed'}
    consumers = [{'id': f'{i:012x}', 'status': 'completed', 'reference_run_id': source['id']}
                 for i in (2, 3)]
    store.insert_many([source, *consumers])
    artifact = tmp_path/'trajectory.xtc'; artifact.write_bytes(b'immutable evidence')
    with pytest.raises(ValueError, match='depend'):
        store.delete_with_cleanup(source['id'], lambda: artifact.unlink())
    assert artifact.read_bytes() == b'immutable evidence'
    store.delete(consumers[0]['id'])
    with pytest.raises(ValueError, match='depend'):
        store.delete(source['id'])
    store.delete(consumers[1]['id'])
    store.delete_with_cleanup(source['id'], lambda: artifact.unlink())
    assert store.get(source['id']) is None
    assert not artifact.exists()


def test_cleanup_failure_retains_record_for_retry(tmp_path):
    store = Store(tmp_path/'jobs.sqlite3')
    store.insert({'id': '111111111111', 'status': 'completed'})
    def fail():
        raise OSError('read-only filesystem')
    with pytest.raises(OSError):
        store.delete_with_cleanup('111111111111', fail)
    assert store.get('111111111111') is not None


def test_http_delete_keeps_source_files_for_completed_consumer(dashboard):
    source = {'id': '111111111111', 'status': 'completed', 'layout_version': 2}
    dashboard.coordinator.database().insert_many([source, {'id': '222222222222', 'status': 'completed', 'reference_run_id': source['id']}])
    artifact = dashboard.coordinator.RUNS/source['id']/'trajectory.xtc'
    artifact.parent.mkdir(parents=True); artifact.write_bytes(b'source')
    response = dashboard.client.delete('/api/jobs/'+source['id'])
    assert response.status_code == 409
    assert artifact.read_bytes() == b'source'


class Deletions:
    """The deletion seam a cleanup call goes through: run the removal, record the id."""

    def __init__(self):
        self.deleted = []

    def delete_with_cleanup(self, jid, cleanup):
        cleanup()
        self.deleted.append(jid)


def test_temporary_retention_preserves_a_retained_reference(tmp_path):
    from datetime import datetime, timedelta, timezone

    from dashboard.execution.coordination import temporary
    now = datetime.now(timezone.utc)
    jobs = [{'id': f'{i:012x}', 'temporary_validation': True, 'status': 'completed',
             'ended_at': (now-timedelta(days=8+i)).isoformat()} for i in range(6)]
    source = jobs[-1]['id']
    jobs.append({'id': 'eeeeeeeeeeee', 'status': 'completed', 'reference_run_id': source})
    artifact = tmp_path/source/'trajectory.xtc'; artifact.parent.mkdir(); artifact.write_bytes(b'source')
    store = Deletions()
    temporary.cleanup(jobs, tmp_path, store, now=now)
    assert source not in store.deleted
    assert artifact.read_bytes() == b'source'
