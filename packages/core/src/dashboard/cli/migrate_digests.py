"""Rewrite the digests stored before this tree had one JSON serializer, proving each rewrite first.

`files.json_sha256` used default separators (`", "`, `": "`) while `models/mappings/identity.canonical_json` used compact
ones, so one document had two digests: a composition's `snapshot_hash` and a mapping's content identity. Only the
mapping's is ever *compared* — a stored parameterization is found by it — so the compact form is the survivor and the
records holding the other are rewritten here.

The old serializer is kept in this module as the oracle, and **nothing is written that cannot be proved**: each record's
body is re-serialized with the old function and must reproduce the stored digest exactly. A record whose body is absent,
or whose stored digest is not its body's, is reported and left alone — a migration that guesses is worse than one that
says what it could not read.

Run it twice and the second run reports everything `unchanged`, which is the property the tests assert.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from dashboard import files, paths
from dashboard.store import Store

#: Where the field can appear. `snapshot_hash` is a record's own body digest; the other is a copy of one.
FIELD = 'composition_snapshot_sha256'
BODY_FIELD = 'snapshot_hash'


def legacy_sha256(value):
    """The serializer this migration replaces: sorted keys, *default* separators.

    Kept as the oracle for the rewrite, never used to compute a digest that will be stored.
    """
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _workspace(root):
    return Path(root) if root is not None else Path(paths.current().workspace)


def _database(root):
    """The job store's file, asked of `paths` rather than spelled here: the name has changed once already."""
    if root is None:
        return paths.current().database
    return paths.Paths(project_root=paths.DEFAULT.project_root, workspace=Path(root)).database


def _entry(store, record_id, path, status, *, old=None, new=None, why=None):
    return {'store': store, 'id': record_id, 'file': str(path), 'status': status,
            'old': old, 'new': new, 'why': why}


def _judged(store, record_id, path, stored, body):
    """One decision: rewrite, unchanged, or the record cannot be read."""
    if not stored:
        return _entry(store, record_id, path, 'absent', why='no digest recorded')
    if not isinstance(body, dict):
        return _entry(store, record_id, path, 'unreconstructible', old=stored,
                      why='the record keeps no body to recompute from')
    new = files.json_sha256(body)
    if new == stored:
        return _entry(store, record_id, path, 'unchanged', old=stored, new=new)
    if legacy_sha256(body) != stored:
        return _entry(store, record_id, path, 'unreconstructible', old=stored,
                      why="the stored digest is not this body's, so a rewrite would invent one")
    return _entry(store, record_id, path, 'rewrite', old=stored, new=new)


def _fragment_body(record):
    """A fragment's body is its record without the wrapper fields -- the record spreads `**body` in.

    Two candidate reconstructions, because `created_at` is the one wrapper key a payload may legitimately have carried;
    the one that reproduces the stored digest is the body that was hashed, and neither reproducing it means no rewrite.
    """
    stored = record.get(BODY_FIELD)
    for dropped in (('id', 'kind', BODY_FIELD, 'created_at'), ('id', 'kind', BODY_FIELD)):
        body = {key: value for key, value in record.items() if key not in dropped}
        # Either serializer reproducing the stored digest identifies the body: the second run of this migration must
        # recognise what the first one wrote, or it reports the whole workspace as unreadable.
        if stored and (legacy_sha256(body) == stored or files.json_sha256(body) == stored):
            return body
    return None


def plan(root=None):
    """What the migration would change. Reads only; returns the entries it decided."""
    workspace = _workspace(root)
    entries, rewritten = [], {}

    for path in sorted((workspace / 'compositions').glob('*.json')):
        record = json.loads(path.read_text())
        entry = _judged('composition', record.get('id'), path, record.get(BODY_FIELD), record.get('snapshot'))
        entries.append(entry)
        if entry['status'] in ('rewrite', 'unchanged'):
            rewritten[record.get('id')] = entry['new']

    for path in sorted((workspace / 'model_registry' / 'fragments').glob('*.json')):
        record = json.loads(path.read_text())
        entries.append(_judged('fragment', record.get('id'), path, record.get(BODY_FIELD), _fragment_body(record)))

    copies = []
    database = _database(root)
    if Path(database).is_file():
        for record in Store(database).all():
            if record.get(FIELD):
                copies.append(('job', record['id'], None, record))
    for path in sorted((workspace / 'runs').glob('*/manifest.json')):
        record = json.loads(path.read_text())
        if record.get(FIELD):
            copies.append(('manifest', record.get('id'), path, record))

    for store, record_id, path, record in copies:
        old = record[FIELD]
        new = rewritten.get(record.get('composition_id'))
        if new is None:
            entries.append(_entry(store, record_id, path, 'unattributable', old=old,
                                  why='the composition it copies is not in this workspace'))
        elif new == old:
            entries.append(_entry(store, record_id, path, 'unchanged', old=old, new=new))
        else:
            entries.append(_entry(store, record_id, path, 'rewrite', old=old, new=new,
                                  why=f'copies composition {record.get("composition_id")}'))
    return entries


def apply(entries, root=None):
    """Perform the rewrites `plan` proposed and return the entries that were written."""
    database = _database(root)
    written = []
    for entry in entries:
        if entry['status'] != 'rewrite':
            continue
        if entry['store'] == 'job':
            Store(database).update(entry['id'], **{FIELD: entry['new']})
        else:
            record = json.loads(Path(entry['file']).read_text())
            path = Path(entry['file'])
            # A record's own body digest is `snapshot_hash`; a manifest holds a *copy* of a composition's.
            record[FIELD if entry['store'] == 'manifest' else BODY_FIELD] = entry['new']
            files.atomic_json(path, record)
        written.append(entry)
    return written


def summary(entries):
    counts = {}
    for entry in entries:
        counts[entry['status']] = counts.get(entry['status'], 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser(description='Rewrite stored snapshot digests to the canonical serialization')
    parser.add_argument('--workspace', type=Path, default=None, help='a workspace to migrate (default: the live one)')
    parser.add_argument('--apply', action='store_true', help='write the rewrites (default: report only)')
    parser.add_argument('--report', type=Path, default=None, help='write the decided entries here as JSON')
    args = parser.parse_args()
    entries = plan(args.workspace)
    if args.apply:
        entries = entries + [dict(entry, status='written') for entry in apply(entries, args.workspace)]
    counts = summary(entries)
    printable = {key: value for key, value in counts.items() if key != 'written'}
    print(' '.join(f'{key}={value}' for key, value in sorted(printable.items())))
    for entry in entries:
        if entry['status'] in ('rewrite', 'unreconstructible', 'unattributable'):
            print(f"  {entry['status']:<18} {entry['store']:<12} {entry['id']}  {entry.get('why') or ''}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(entries, indent=2) + '\n')
        print(f'report: {args.report}')


if __name__ == '__main__':
    main()
