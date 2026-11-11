"""Transactional SQLite job records."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

#: Database files already switched to WAL, and the lock that serializes the switch. A Store is built per
#: `coordinator.database()` call, so this cannot be instance state.
_WAL = set()
_WAL_LOCK = threading.Lock()


def _enable_wal(db, path):
    """Switch a database file to WAL once, not once per connection.

    Changing journal mode needs exclusive access to the database. Doing it on every connection -- which is what this
    store used to do -- races the concurrent connections a threaded server opens, and the request that loses raises
    `sqlite3.OperationalError: database is locked` before it has read anything. The mode persists in the file, so the
    first connection that can set it is enough.
    """
    key = str(Path(path).resolve())
    if key in _WAL:
        return
    with _WAL_LOCK:
        if key in _WAL:
            return
        db.execute('PRAGMA journal_mode=WAL')
        _WAL.add(key)


class Store:
    def __init__(self, database):
        self.path = Path(database)

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        try:
            _enable_wal(db, self.path)
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1)')
            db.execute('CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, data TEXT, updated REAL)')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def all(self):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM jobs ORDER BY json_extract(data,'$.created') DESC, rowid DESC")]

    def get(self, jid):
        with self.connection() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=?', (jid,)).fetchone()
            return json.loads(row[0]) if row else None

    def replace(self, rows):
        """Replace all records for isolated setup and controlled resets."""
        with self.connection() as db:
            db.execute('DELETE FROM jobs')
            db.executemany('INSERT INTO jobs(id,data) VALUES (?,?)', [(r['id'], json.dumps(r)) for r in rows])

    def insert(self, job):
        self.insert_many([job])

    def insert_many(self, jobs):
        """Attach an AA source and its consumers in the same transaction."""
        with self.connection() as db:
            for job in jobs:
                db.execute('INSERT INTO jobs(id,data) VALUES (?,?)', (job['id'], json.dumps(job)))
            for job in jobs:
                source = job.get('reference_run_id')
                if source and (source == job['id'] or not db.execute('SELECT 1 FROM jobs WHERE id=?', (source,)).fetchone()):
                    raise ValueError('AA reference source is unavailable')

    def update(self, jid, **fields):
        with self.connection() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=?', (jid,)).fetchone()
            if not row: raise KeyError(jid)
            job = json.loads(row[0]); job.update(fields)
            db.execute('UPDATE jobs SET data=?, revision=revision+1 WHERE id=?', (json.dumps(job), jid))
            return job

    def delete(self, jid):
        self.delete_with_cleanup(jid, lambda: None)

    def delete_with_cleanup(self, jid, cleanup):
        """Check retained dependencies before filesystem removal under the DB lock.

        A failed cleanup leaves the job record available for a retry. Attachments
        through insert_many cannot race the guard and acquire a deleted source.
        """
        with self.connection() as db:
            dependent = db.execute("SELECT id FROM jobs WHERE json_extract(data,'$.reference_run_id')=? LIMIT 1", (jid,)).fetchone()
            if dependent:
                raise ValueError(f'Run {dependent[0]} depends on this source; delete its consumers first')
            cleanup()
            db.execute('DELETE FROM jobs WHERE id=?', (jid,))
            db.execute('DELETE FROM artifacts WHERE id=?', (jid,))

    def page(self, page=1, limit=20, statuses=(), search='', run_types=(), methods=()):
        """One page of run records, optionally narrowed by status, run type and fitting method.

        This is the one place the run list's ordering, its search clause and its narrowing clauses are decided.

        Each parameter is a sequence because the Runs panel offers checkboxes: several values in one group are an *or*
        (an `IN` clause) and the groups are an *and*. The values are never interpolated -- one placeholder per value.
        A group with no values contributes no clause, which is why "no box ticked" is "everything".

        An absent `run_type` on a record is the historical combined AA-to-CG job, which the run-type migration
        rewrites to `cg` (`protocol.run_type_of` and `cli/migrate_run_types` agree on that default), so filtering for
        `cg` finds those too rather than reporting them as nothing.
        """
        statuses, run_types, methods = tuple(statuses), tuple(run_types), tuple(methods)
        tests = ["(?='' OR instr(lower(data),lower(?))>0)"]
        args = [search, search]
        for column, values in (("json_extract(data,'$.status')", statuses),
                               ("COALESCE(json_extract(data,'$.run_type'),'cg')", run_types),
                               ("json_extract(data,'$.method')", methods)):
            if values:
                tests.append(f'{column} IN ({",".join("?" * len(values))})')
                args.extend(values)
        clause = 'WHERE ' + ' AND '.join(tests)
        with self.connection() as db:
            count = db.execute('SELECT count(*) FROM jobs ' + clause, args).fetchone()[0]
            rows = db.execute("SELECT data,revision FROM jobs " + clause
                              + " ORDER BY json_extract(data,'$.created') DESC, rowid DESC LIMIT ? OFFSET ?",
                              (*args, limit, (page-1)*limit)).fetchall()
            return [(json.loads(row[0]), row[1]) for row in rows], count

    def artifacts(self, jid, entries=None):
        import time
        with self.connection() as db:
            if entries is not None:
                db.execute('INSERT OR REPLACE INTO artifacts VALUES (?,?,?)', (jid, json.dumps(entries), time.time()))
            row = db.execute('SELECT data,updated FROM artifacts WHERE id=?', (jid,)).fetchone()
            return (json.loads(row[0]), row[1]) if row else (None, 0)
