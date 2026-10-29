"""The job store under concurrency: one journal-mode switch, and no lock error for a reader.

Every operation opens its own connection and takes `BEGIN IMMEDIATE`. The journal-mode switch is what this file
pins: it needs exclusive access, so doing it on every connection raced a threaded server's other connections and
surfaced as `sqlite3.OperationalError: database is locked` -- a 500 on `/api/jobs` under the browser tier's parallel
load. The mode persists in the file, so once is enough.
"""
import sqlite3
import threading

from dashboard.store import Store

JOB = 'a' * 12
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
        store.page(1, 20, '', '')

    switches = [statement for statement in trace if 'journal_mode' in statement.lower()]
    assert len(switches) == 1, trace


def test_a_writer_beside_several_readers_never_raises_the_lock_error(tmp_path):
    store = Store(tmp_path / 'jobs.sqlite3')
    store.insert({'id': JOB, 'status': 'running', 'created': CREATED})
    errors = []

    def read():
        for _ in range(25):
            try:
                store.page(1, 20, '', '')
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
