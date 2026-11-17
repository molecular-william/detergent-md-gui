"""The job store under concurrency: one journal-mode switch, one schema creation, and no lock error for a reader.

Every operation opens its own connection. `read()` is a deferred transaction with no DDL and no write lock;
`connection()` keeps `BEGIN IMMEDIATE` and is the only creator of the schema. The journal-mode switch is what the
first test pins: it needs exclusive access, so doing it on every connection raced a threaded server's other
connections and surfaced as `sqlite3.OperationalError: database is locked` -- a 500 on `/api/jobs` under the browser
tier's parallel load. The mode persists in the file, so once is enough.
"""
import json
import sqlite3
import threading

from dashboard.store import Store

JOB = 'a' * 12
OTHER = 'b' * 12
CREATED = '2026-01-01T00:00:00+00:00'


def test_the_journal_mode_is_switched_once_not_once_per_connection(tmp_path, monkeypatch):
    trace = []
    real_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        db = real_connect(database, *args, **kwargs)
        db.set_trace_callback(trace.append)
        return db

    monkeypatch.setattr('dashboard.store.sqlite3.connect', connect)
    store = Store(tmp_path / 'jobs.sqlite3')
    store.insert({'id': JOB, 'status': 'running', 'created': CREATED})
    for _ in range(5):
        store.page(1, 20)

    switches = [statement for statement in trace if 'journal_mode' in statement.lower()]
    assert len(switches) == 1, trace


def test_a_writer_beside_several_readers_never_raises_the_lock_error(tmp_path):
    store = Store(tmp_path / 'jobs.sqlite3')
    store.insert({'id': JOB, 'status': 'running', 'created': CREATED})
    errors = []

    def read():
        for _ in range(25):
            try:
                store.page(1, 20)
            except Exception as error:  # noqa: BLE001 - the assertion reports what a caller would have seen
                errors.append(error)

    def write():
        for index in range(25):
            try:
                store.update(JOB, label=f'update {index}')
            except Exception as error:  # noqa: BLE001
                errors.append(error)

    threads = [threading.Thread(target=read) for _ in range(4)]
    threads.append(threading.Thread(target=write))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == [], errors
    assert store.get(JOB)['label'] == 'update 24'


def test_a_read_on_a_fresh_path_falls_back_to_the_write_path_once(tmp_path):
    path = tmp_path / 'nested' / 'jobs.sqlite3'  # no parent directory and no database file yet
    store = Store(path)

    assert store.get(JOB) is None
    assert store.all() == []
    assert path.exists()


def test_reads_do_no_mkdir_and_no_ddl(tmp_path, monkeypatch):
    store = Store(tmp_path / 'jobs.sqlite3')
    store.insert({'id': JOB, 'status': 'running', 'created': CREATED})

    def fail_mkdir(*args, **kwargs):
        raise AssertionError('a read must not create directories')

    trace = []
    real_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        db = real_connect(database, *args, **kwargs)
        db.set_trace_callback(trace.append)
        return db

    monkeypatch.setattr('dashboard.store.Path.mkdir', fail_mkdir)
    monkeypatch.setattr('dashboard.store.sqlite3.connect', connect)
    # A new Store, like the one `coordinator.database()` builds per call: the schema cache is per path, not per instance.
    Store(store.path).page(1, 20)
    store.all()
    store.names()
    store.retired_names()

    ddl = [statement for statement in trace if statement.lstrip().upper().startswith(('CREATE', 'BEGIN IMMEDIATE'))]
    assert ddl == [], trace


def test_a_read_succeeds_beside_an_open_write_transaction_and_sees_committed_rows(tmp_path):
    store = Store(tmp_path / 'jobs.sqlite3')
    store.insert({'id': JOB, 'status': 'running', 'created': CREATED})

    writer = sqlite3.connect(store.path, timeout=30)
    try:
        writer.execute('BEGIN IMMEDIATE')
        writer.execute('INSERT INTO jobs(id,data) VALUES (?,?)', (OTHER, json.dumps({'id': OTHER, 'created': CREATED})))

        assert store.get(JOB)['id'] == JOB
        assert store.get(OTHER) is None  # the writer's row is not committed yet
        rows, count = store.page(1, 20)
        assert (count, [row['id'] for row, _ in rows]) == (1, [JOB])
    finally:
        writer.rollback()
        writer.close()

    assert store.get(OTHER) is None


def test_artifacts_writes_under_the_write_lock_and_reads_deferred(tmp_path):
    store = Store(tmp_path / 'jobs.sqlite3')
    store.insert({'id': JOB, 'status': 'running', 'created': CREATED})

    assert store.artifacts(JOB) == (None, 0)
    stored, updated = store.artifacts(JOB, entries=[{'path': 'a.log'}])
    assert stored == [{'path': 'a.log'}] and updated > 0
    assert store.artifacts(JOB) == (stored, updated)
