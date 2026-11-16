"""Re-pin the stored parameterization revisions by their AA reference's edition.

`references.verify`/`resolve` no longer read a digest as a pin: a consumer pins the edition its reference publishes,
and a digest (`reference_sha256`) or an artifact map is refused. A revision written before the named identity still
carries the digest, so a run that consumes it cannot resolve its source. This migration rewrites those records once:

* for every record under `parameterizations/records/*.json`, each revision whose `aa_reference` has
  `reference_sha256` and no edition gains `reference_edition` -- the edition the referenced run's own
  `stages/07_reference/reference.json` publishes, never a guess -- and loses `reference_sha256`; the record's
  `current` copy of that revision is changed with it. The run id and the fit's own provenance stay.
* every stored revision's reference must resolve by its edition afterwards; a revision a migration cannot pin
  refuses the whole run of the tool rather than leaving half a store on the new pin.
* each original document is kept in `<workspace>/.named-migration/reference-pins.json`, and `--rollback` restores
  it.

A referenced run whose published reference has no edition refuses the migration and writes nothing: there is no
edition to pin, and rewriting its consumers would let a run claim a pin it does not have. `repair_reference_edition`
is the tool that gives such a run its edition first. Dry run by default; `--apply` writes. Idempotent: a record
already pinned by edition is reported unchanged and nothing is written.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from dashboard import files, paths, run_names
from dashboard.analysis.runs import references

TOOL = 'dashboard.cli.migrate_reference_pins'
VERSION = 1
BACKUP = Path('.named-migration') / 'reference-pins.json'
RECORDS = Path('parameterizations') / 'records'
RUNS = Path('runs')
REFERENCE = Path('stages/07_reference/reference.json')


class Refusal(ValueError):
    """One revision cannot be re-pinned without losing what it says; the whole migration writes nothing."""


def _read(path):
    """The JSON at `path`; a file that does not parse is a refusal that names it."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise Refusal(f'{Path(path).name}: {exc}') from exc


def _ledger_entry(workspace):
    """The ledger this workspace holds, or None when there is none to read."""
    try:
        document = json.loads((Path(workspace) / BACKUP).read_text())
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _number(revision, fallback):
    """The revision's own number, or `fallback` for a record that does not state one."""
    if isinstance(revision, dict):
        number = revision.get('revision')
        if isinstance(number, int) and not isinstance(number, bool):
            return number
    return fallback


def _resolve(workspace, run_id, edition, label):
    """Prove one reference resolves under the edition the record will pin."""
    try:
        references.resolve(Path(workspace) / RUNS, run_id, expected={'edition': edition})
    except (OSError, ValueError) as exc:
        raise Refusal(f'{label}: its reference does not resolve by edition {edition}: {exc}') from exc


def _published_edition(workspace, run_id):
    """The edition the referenced run publishes, after proving the reference resolves under it."""
    try:
        run_names.validate(run_id, what='AA source run ID')
    except ValueError as exc:
        raise Refusal(f'the AA reference run is invalid: {exc}') from exc
    path = Path(workspace) / RUNS / run_id / REFERENCE
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Refusal(f'run {run_id} has no readable {REFERENCE.as_posix()}: {exc}') from exc
    if not isinstance(record, dict):
        raise Refusal(f'run {run_id}\'s {REFERENCE.as_posix()} is not an object')
    edition = record.get('edition')
    if edition is None:
        raise Refusal(f'run {run_id} publishes no edition, so its consumers cannot be re-pinned')
    _resolve(workspace, run_id, edition, f'run {run_id}')
    return edition


def _migrate_revision(revision, workspace, editions, changes, label):
    """`(reference, changed)` for one revision: the block as it should be stored, and whether it was rewritten."""
    if not isinstance(revision, dict):
        raise Refusal(f'{label} is not an object')
    reference = revision.get('aa_reference')
    if not isinstance(reference, dict):
        return reference, False
    run_id = reference.get('run_id')
    if not isinstance(run_id, str) or not run_id:
        raise Refusal(f'{label} names no AA reference run')
    # `reference_edition` is this tool's spelling; `edition` is the one a fit writes. Either is already a pin.
    pinned = reference.get('reference_edition')
    if pinned is None:
        pinned = reference.get('edition')
    if pinned is not None:
        _resolve(workspace, run_id, pinned, label)
        return reference, False
    if 'reference_sha256' not in reference:
        raise Refusal(f'{label} records no edition and no legacy digest to migrate')
    if run_id not in editions:
        editions[run_id] = _published_edition(workspace, run_id)
    edition = editions[run_id]
    rewritten = copy.deepcopy(reference)
    rewritten.pop('reference_sha256', None)
    # A null `edition` claims nothing; it is the empty slot this migration fills.
    rewritten.pop('edition', None)
    rewritten['reference_edition'] = edition
    changes.append({'revision': revision.get('revision'), 'run': run_id, 'edition': edition})
    return rewritten, True


def _plan_record(workspace, path):
    """What the migration would do to one stored record; `status` is `write`, `unchanged` or `refused`."""
    base = {'record': path.stem, 'path': (RECORDS / path.name).as_posix()}
    try:
        record = _read(path)
    except Refusal as exc:
        return {**base, 'status': 'refused', 'reason': str(exc)}
    if not isinstance(record, dict):
        return {**base, 'status': 'refused', 'reason': 'the record is not an object'}
    if not isinstance(record.get('revisions'), list):
        return {**base, 'status': 'refused', 'reason': 'the record has no revisions list'}
    document = copy.deepcopy(record)
    editions = {}
    changes = []
    try:
        for index, revision in enumerate(document['revisions']):
            label = f'{path.stem} revision {_number(revision, index + 1)}'
            reference, changed = _migrate_revision(revision, workspace, editions, changes, label)
            if changed:
                document['revisions'][index]['aa_reference'] = reference
        current = document.get('current')
        if isinstance(current, dict):
            label = f'{path.stem} revision {_number(current, "current")} (current)'
            reference, changed = _migrate_revision(current, workspace, editions, changes, label)
            if changed:
                document['current']['aa_reference'] = reference
        elif current is not None:
            raise Refusal('the record has a current revision that is not an object')
    except Refusal as exc:
        return {**base, 'status': 'refused', 'reason': str(exc)}
    if document == record:
        return {**base, 'status': 'unchanged'}
    # `current` duplicates one revision; the report names that revision once.
    unique = list({(change['revision'], change['run']): change for change in changes}.values())
    return {**base, 'status': 'write', 'original': record, 'document': document, 'changes': unique}


def plan(workspace):
    """What the migration would do to every stored record. Reads and resolves only."""
    root = Path(workspace) / RECORDS
    found = sorted(root.glob('*.json')) if root.is_dir() else []
    return [_plan_record(Path(workspace), path) for path in found if path.is_file() and not path.is_symlink()]


def _verify(workspace, entries):
    """Every stored revision of every planned record resolves by the edition it now pins."""
    for entry in entries:
        if entry['status'] not in ('write', 'unchanged'):
            continue
        document = _read(Path(workspace) / entry['path'])
        if not isinstance(document, dict):
            raise ValueError(f'{entry["record"]}: the stored record is not an object')
        revisions = list(document.get('revisions') or [])
        if isinstance(document.get('current'), dict):
            revisions.append(document['current'])
        for revision in revisions:
            if not isinstance(revision, dict):
                continue
            reference = revision.get('aa_reference')
            if not isinstance(reference, dict):
                continue
            edition = reference.get('reference_edition')
            if edition is None:
                edition = reference.get('edition')
            if edition is None:
                raise ValueError(f'{entry["record"]}: revision {_number(revision, "?")} is not pinned by edition')
            try:
                references.resolve(Path(workspace) / RUNS, reference.get('run_id'), expected={'edition': edition})
            except (OSError, ValueError) as exc:
                raise ValueError(f'{entry["record"]}: revision {_number(revision, "?")} does not resolve: '
                                 f'{exc}') from exc


def _ledger(workspace):
    document = _ledger_entry(workspace) or {}
    if not isinstance(document.get('records'), dict):
        document['records'] = {}
    document.update(tool=TOOL, version=VERSION, workspace=str(workspace),
                    created_at=document.get('created_at') or files.now_iso())
    return document


def apply(entries, workspace):
    """Rewrite each planned record, back its original up first, then verify every revision resolves.

    The ledger is written before the records, so a crash leaves every original recoverable by `--rollback`. A
    verification that fails restores the originals written by this call before raising.
    """
    workspace = Path(workspace)
    if any(entry['status'] == 'refused' for entry in entries):
        raise ValueError('a refused migration writes nothing')
    writes = [entry for entry in entries if entry['status'] == 'write']
    if not writes:
        return []
    ledger = _ledger(workspace)
    for entry in writes:
        previous = ledger['records'].get(entry['record'])
        original = previous.get('original') if isinstance(previous, dict) else None
        ledger['records'][entry['record']] = {
            'path': entry['path'],
            # A re-apply must not replace the pre-migration bytes with already-migrated ones.
            'original': original if isinstance(original, dict) else entry['original'],
            'migrated': entry['document'],
            'applied_at': files.now_iso(),
        }
    files.atomic_json(workspace / BACKUP, ledger)
    written = []
    try:
        for entry in writes:
            files.atomic_json(workspace / entry['path'], entry['document'])
            written.append(entry)
        _verify(workspace, entries)
    except (OSError, ValueError) as exc:
        for entry in written:
            files.atomic_json(workspace / entry['path'], entry['original'])
        raise ValueError(f'the migrated records do not resolve; the originals are back: {exc}') from exc
    return written


def rollback(workspace):
    """Restore every record the ledger backed up; None when there is no ledger to roll back from."""
    workspace = Path(workspace)
    document = _ledger_entry(workspace)
    if document is None:
        print(f'no ledger at {workspace / BACKUP}')
        return None
    restored = []
    for name, entry in (document.get('records') or {}).items():
        if not isinstance(entry, dict) or not isinstance(entry.get('original'), dict):
            continue
        path = entry.get('path') or (RECORDS / f'{name}.json').as_posix()
        files.atomic_json(workspace / path, entry['original'])
        restored.append(name)
    return len(restored)


def summary(entries):
    """`write=N unchanged=M`, with `refused` when a record could not be re-pinned."""
    counts = {'write': 0, 'unchanged': 0, 'refused': 0}
    for entry in entries:
        counts[entry['status']] = counts.get(entry['status'], 0) + 1
    text = f'write={counts["write"]} unchanged={counts["unchanged"]}'
    if counts['refused']:
        text += f' refused={counts["refused"]}'
    return text


def _line(entries, applied):
    for entry in entries:
        if entry['status'] == 'write':
            changes = ', '.join(f'revision {change["revision"]} -> edition {change["edition"]}'
                                for change in entry.get('changes') or [])
            print(f'{"migrated" if applied else "migrate"} {entry["record"]}: {changes}')
        elif entry['status'] == 'unchanged':
            print(f'unchanged {entry["record"]}')
        else:
            print(f'{entry["record"]} refused: {entry["reason"]}')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Re-pin stored parameterization revisions by their AA reference edition (dry run by default)')
    parser.add_argument('--workspace', type=Path, default=None,
                        help='a workspace (the directory holding runs/; default: the live one)')
    parser.add_argument('--apply', action='store_true', help='write the migration (default: report only)')
    parser.add_argument('--rollback', action='store_true',
                        help=f'restore the records backed up in {BACKUP.as_posix()}')
    args = parser.parse_args(argv)
    workspace = args.workspace if args.workspace is not None else Path(paths.current().workspace)
    if args.rollback:
        undone = rollback(workspace)
        if undone is None:
            return 1
        print(f'rollback={undone}')
        return 0
    entries = plan(workspace)
    if args.apply:
        if any(entry['status'] == 'refused' for entry in entries):
            print(summary(entries))
            _line(entries, False)
            return 1
        try:
            apply(entries, workspace)
        except (OSError, ValueError) as exc:
            print(f'refused: {exc}')
            return 1
    print(summary(entries))
    _line(entries, args.apply)
    return 1 if any(entry['status'] == 'refused' for entry in entries) else 0


if __name__ == '__main__':
    raise SystemExit(main())
