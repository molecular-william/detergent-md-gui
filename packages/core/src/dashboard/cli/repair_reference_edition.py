"""Repair one published AA reference so its edition can be pinned.

A reference published before editions records every artifact it read as a digest map. One launcher in that map --
the copied `run.sh` that layout 4 no longer writes -- may not be in the run. That missing entry blocks the stamp:
`migrate_named_records` refuses to publish an edition for a record that names an artifact the run does not hold, so
the source's consumer keeps the legacy digest pin instead.

This migration repairs one named run (default `dbc366ae772b`), and only it:

* every artifact/digest map entry whose named file is not in the run is dropped, but only when the name is a copied
  launcher (`.sh`, `.py`, or `run.sh`). The drop is recorded in the record's own `repaired` list, with the original
  map entries, so the repair is readable in the reference itself rather than only in this tool's ledger.
* a missing non-launcher artifact refuses the run and writes nothing: the reference cannot be re-pinned around a
  trajectory or topology the run does not hold.
* the record gets `edition` 1 and its molecule name from its own snapshot metadata, it is backed up in
  `<workspace>/.named-migration/reference-repair.json`, and `references.resolve(..., expected={'edition': 1})` must
  succeed before the run is reported repaired.

A dry run by default; `--apply` writes. `--rollback` restores every backed-up record from that ledger. Idempotent: a
record that already carries an edition is `unchanged` and nothing is written.

**After `--apply`, re-run `python -m dashboard.cli.migrate_named_records --apply`.** Its reference path will now stamp
the edition and re-pin the run's consumers; this tool does not invoke it.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from dashboard import files, paths, run_names
from dashboard.analysis.runs import references

TOOL = 'dashboard.cli.repair_reference_edition'
VERSION = 1
BACKUP = Path('.named-migration') / 'reference-repair.json'
#: The run this repair was written for: the DDM AA reference whose consumer cannot be re-pinned until it is stamped.
DEFAULT_RUN = 'dbc366ae772b'
RECORD = Path('stages/07_reference/reference.json')
#: A launcher a run used to carry as a copy. Layout 4 names the repository's script instead, so its absence is not
#: a missing artifact.
LAUNCHER_SUFFIXES = ('.sh', '.py')
NOTE = 'removed at {date}: the artifact is not in the run; a copied launcher is not used by layout 4'


def _read(path):
    """The JSON object at `path`, or None when it does not parse as one."""
    try:
        record = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _launcher(name):
    return str(name) == 'run.sh' or str(name).endswith(LAUNCHER_SUFFIXES)


def _molecule(record):
    """The molecule name the reference's own snapshot metadata records."""
    snapshot = record.get('molecule_snapshot')
    metadata = snapshot.get('metadata') if isinstance(snapshot, dict) else None
    name = metadata.get('name') if isinstance(metadata, dict) else None
    return name if isinstance(name, str) and name.strip() else None


def _entry(workspace, run_id):
    """What the repair would do to one run; `status` is `repair`, `unchanged` or `refused`."""
    run_dir = Path(workspace) / 'runs' / run_id
    base = {'run': run_id, 'path': RECORD.as_posix()}
    manifest = _read(run_dir / 'manifest.json')
    if manifest is None:
        return {**base, 'status': 'refused', 'reason': 'the run has no readable manifest.json'}
    if manifest.get('run_type') != 'aa_only' or manifest.get('status') != 'completed':
        return {**base, 'status': 'refused', 'reason': 'the reference must be a completed AA-only run'}
    record = _read(run_dir / RECORD)
    if record is None:
        return {**base, 'status': 'refused', 'reason': f'the run has no readable {RECORD.as_posix()}'}
    if record.get('reference_eligible') is not True:
        return {**base, 'status': 'refused', 'reason': 'the reference failed its technical checks'}
    if record.get('edition') is not None:
        return {**base, 'status': 'unchanged', 'edition': record['edition']}
    molecule = _molecule(record)
    if molecule is None:
        return {**base, 'status': 'refused', 'reason': "the reference's snapshot metadata names no molecule"}
    existing = record.get('repaired')
    if existing is not None and not isinstance(existing, list):
        return {**base, 'status': 'refused', 'reason': "the reference's repaired field is not a list"}
    artifacts = record.get('artifacts') if isinstance(record.get('artifacts'), dict) else {}
    hashes = record.get('sha256') if isinstance(record.get('sha256'), dict) else {}
    names = list(dict.fromkeys([*artifacts.values(), *hashes]))
    missing = [name for name in names if not (run_dir / name).exists()]
    blocked = [name for name in missing if not _launcher(name)]
    if blocked:
        return {**base, 'status': 'refused',
                'reason': 'non-launcher artifacts are missing: ' + ', '.join(blocked[:3])}
    removed = [name for name in missing if _launcher(name)]
    dropped = set(removed)
    document = copy.deepcopy(record)
    if 'artifacts' in record:
        document['artifacts'] = {key: value for key, value in artifacts.items() if value not in dropped}
    document['sha256'] = {key: digest for key, digest in hashes.items() if key not in dropped}
    date = files.now_iso().split('T', 1)[0]
    note = NOTE.format(date=date)
    repaired = list(existing or [])
    for name in removed:
        # The record keeps the removal and the map entries it dropped: the ledger's backup is for rollback, this is
        # what a reader of the published reference can check.
        repaired.append({'name': name, 'note': note,
                         'artifacts': {key: value for key, value in artifacts.items() if value == name},
                         'sha256': {key: digest for key, digest in hashes.items() if key == name}})
    if repaired:
        document['repaired'] = repaired
    document['edition'] = references.EDITION
    document['molecule'] = molecule
    return {**base, 'status': 'repair', 'edition': references.EDITION, 'molecule': molecule,
            'removed': removed, 'original': record, 'document': document}


def plan(workspace, run_id=DEFAULT_RUN):
    """What the repair would do to one run. Reads only."""
    run_names.validate(run_id, what='AA source run ID')
    return [_entry(workspace, run_id)]


def _ledger(workspace):
    document = _read(Path(workspace) / BACKUP) or {}
    if not isinstance(document.get('runs'), list):
        document['runs'] = []
    document.update(tool=TOOL, version=VERSION, created_at=document.get('created_at') or files.now_iso())
    return document


def apply(entries, workspace):
    """Repair each planned run, back its original up first, then verify the edition resolves.

    The ledger is written before the record, so a crash leaves the original recoverable by `--rollback`. A repair
    whose verification fails restores the original before raising.
    """
    workspace = Path(workspace)
    if any(entry['status'] == 'refused' for entry in entries):
        raise ValueError('a refused repair writes nothing')
    done = []
    for entry in entries:
        if entry['status'] != 'repair':
            continue
        record_path = workspace / 'runs' / entry['run'] / entry['path']
        document = _ledger(workspace)
        document['runs'] = [record for record in document['runs'] if record.get('run') != entry['run']]
        document['runs'].append({'run': entry['run'], 'path': entry['path'],
                                 'original': entry['original'], 'repaired': entry['document'],
                                 'applied_at': files.now_iso()})
        files.atomic_json(workspace / BACKUP, document)
        files.atomic_json(record_path, entry['document'])
        try:
            references.resolve(workspace / 'runs', entry['run'], expected={'edition': references.EDITION})
        except (OSError, ValueError) as exc:
            files.atomic_json(record_path, entry['original'])
            raise ValueError(f"{entry['run']}: the repaired reference does not resolve; the original is back: {exc}") from exc
        entry['applied'] = True
        done.append(entry)
    return done


def rollback(workspace):
    """Restore every record the ledger backed up; None when there is no ledger to roll back from."""
    workspace = Path(workspace)
    document = _read(workspace / BACKUP)
    if document is None:
        print(f'no ledger at {workspace / BACKUP}')
        return None
    restored = []
    for record in document.get('runs') or []:
        if not isinstance(record, dict) or not isinstance(record.get('original'), dict):
            continue
        run = str(record.get('run') or '')
        run_names.validate(run, what='AA source run ID')
        files.atomic_json(workspace / 'runs' / run / RECORD, record['original'])
        restored.append(run)
    return len(restored)


def summary(entries):
    """`repair=N unchanged=M`, with `refused` when a run could not be repaired."""
    counts = {'repair': 0, 'unchanged': 0, 'refused': 0}
    for entry in entries:
        counts[entry['status']] = counts.get(entry['status'], 0) + 1
    text = f'repair={counts["repair"]} unchanged={counts["unchanged"]}'
    if counts['refused']:
        text += f' refused={counts["refused"]}'
    return text


def _line(entries, applied):
    for entry in entries:
        if entry['status'] == 'repair':
            what = ', '.join(entry['removed']) or 'nothing to drop'
            print(f'{("repaired" if applied else "repair")} {entry["run"]}: {what} -> '
                  f'edition={entry["edition"]} molecule={entry["molecule"]}')
        elif entry['status'] == 'unchanged':
            print(f'unchanged {entry["run"]} edition={entry["edition"]}')
        else:
            print(f'{entry["run"]} refused: {entry["reason"]}')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Repair one published AA reference so it can carry an edition (dry run by default)')
    parser.add_argument('--workspace', type=Path, default=None,
                        help='a workspace (the directory holding runs/; default: the live one)')
    parser.add_argument('--run', default=DEFAULT_RUN, help=f'the AA reference run to repair (default: {DEFAULT_RUN})')
    parser.add_argument('--apply', action='store_true', help='write the repair (default: report only)')
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
    entries = plan(workspace, args.run)
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
