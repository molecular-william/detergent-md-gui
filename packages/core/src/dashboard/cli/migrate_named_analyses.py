"""Move every legacy analysis attempt to a sequence name and rebase the records that named it.

An attempt used to live in `analyses/<kind>/<signature>/<attempt>/`, where the signature was a digest of what the
analysis read and the attempt id was random. It now lives in `analyses/<kind>/<NNNN>-<YYYYMMDD>/`, where NNNN is the
run's next attempt number for that kind and the date is the attempt's own UTC day. A legacy tree stays readable as it
stands, but every reader has to know both shapes; this migration leaves one shape in the store.

What this does, per run, and only with `--apply`:

* every attempt directory under a legacy signature that carries its own `manifest.json` is renamed to the next free
  `NNNN-YYYYMMDD` in its kind: NNNN is one above the highest sequence already present for that run and kind, and is
  counted in date order so an older attempt keeps the smaller number. A date is the record's `created_at` in UTC, or
  the directory's own mtime when the record names none.
* the moved attempt's `manifest.json` `directory` field is rewritten to its new run-relative path, and the job row's
  `analyses[].directory` entries are rebased to match, together with any `log` or `outputs` string on the entry that
  starts with the old directory.
* a legacy attempt of a *stable* kind -- one that publishes one set at `Kind.stable_directory`, such as
  `frame-series` at `analyses/frame-series` -- is not moved at all. A sequenced directory under such a kind would be
  unreadable, because its published set lives at the kind root. Its entry is retired from the job row instead, so the
  root entry is the one the run shows, and every byte of the legacy tree stays on disk. A run that holds such an entry
  with neither a root row entry nor a root `manifest.json` is refused: dropping the entry would leave no published set.
* a signature directory that the moves emptied is removed. A signature directory that still holds anything (a
  published set file with no attempt directory, an attempt without a record) is left in place and reported: this
  migration never deletes data.

It refuses a run whose job row says `running`, or that owns a queued, running or cancelling analysis: a worker may
still be writing the tree. A dry run by default; `--apply` performs the moves and retirements and writes
`<workspace>/.named-migration/analyses.json`, which `--rollback` applies in reverse. Each backup record keeps its
move keys and names its `action` (`move` or `retire`), so rollback can put a retired row entry back exactly.
Idempotent: once applied, no legacy attempt is left to move or retire and a second `--apply` reports
`unchanged=<n>` without writing anything.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from dashboard import files, paths
from dashboard.analysis import kinds
from dashboard.analysis.runs import figures
from dashboard.store import Store

TOOL = 'dashboard.cli.migrate_named_analyses'
#: 2 adds each record's `action` (and a retirement's row `entry`); a version-1 backup is still read as all moves.
VERSION = 2
#: The backup `--apply` writes and `--rollback` reads, relative to the workspace.
BACKUP = Path('.named-migration') / 'analyses.json'
#: Analysis statuses whose worker may still be writing the attempt directory.
ACTIVE = ('queued', 'running', 'cancelling')


def _read(path):
    """The JSON object at `path`, or None when it does not parse as one."""
    try:
        record = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _stable(kind):
    """The kind's stable directory, or None when the kind keeps an attempt tree."""
    row = kinds.TABLE.get(kind)
    return row.stable_directory if row is not None else None


def _rebase(value, old, new):
    """`value` with its leading `old` directory replaced by `new`; anything else is returned unchanged."""
    if not isinstance(value, str):
        return value
    if value == old:
        return new
    if value.startswith(old + '/'):
        return new + value[len(old):]
    return value


def _stamp(record, attempt):
    """`(created, date)` for an attempt: its record's UTC `created_at`, else the directory's mtime.

    `created` is a sortable UTC ISO string and `date` is the `YYYYMMDD` the sequence name carries. A record written
    without a timezone is read as UTC; the filesystem fallback is what an attempt written before the record grew
    `created_at` has.
    """
    raw = record.get('created_at')
    try:
        when = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        when = None
    if when is None:
        when = datetime.fromtimestamp(attempt.stat().st_mtime, tz=timezone.utc)
    elif when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)
    return when.isoformat(), f'{when:%Y%m%d}'


def _entry(run_id, run_dir, store):
    """What this run's migration would be, or why it will not touch it. Reads only."""
    entry = {'id': run_id, 'run': str(run_dir), 'status': 'unchanged', 'why': None,
             'moves': [], 'retires': [], 'kept': [], 'removed': []}
    job = store.get(run_id) if store is not None else None
    if job is not None:
        if job.get('status') == 'running':
            return {**entry, 'status': 'refused', 'why': 'the run is running; stop it before migrating'}
        busy = next((task for task in job.get('analyses') or [] if task.get('status') in ACTIVE), None)
        if busy is not None:
            return {**entry, 'status': 'refused',
                    'why': f'the analysis {busy.get("kind")} is {busy.get("status")}; stop it before migrating'}
    tasks = list((job or {}).get('analyses') or [])
    directories = {}
    for task in tasks:
        directories.setdefault(str(task.get('directory') or '').rstrip('/'), task)
    # A stable kind publishes one set at its kind root, and a sequenced directory beside it would not be read. So a
    # job row written before the kind became stable -- or by an older form of this migration -- can still name legacy
    # attempts there: retire those entries instead of moving them, and keep every byte where it is.
    rooted, retires = set(), []
    for index, task in enumerate(tasks):
        directory = str(task.get('directory') or '').rstrip('/')
        parts = directory.split('/')
        if len(parts) != 4 or parts[0] != 'analyses':
            continue
        stable = _stable(parts[1])
        if stable is None or directory != f'{stable}/{parts[2]}/{parts[3]}':
            continue
        rooted.add(stable)
        retires.append({'action': 'retire', 'run': run_id, 'kind': parts[1], 'signature': parts[2],
                        'attempt': parts[3], 'old_path': directory, 'index': index,
                        'entry': copy.deepcopy(task)})
    for stable in sorted(rooted):
        if stable not in directories and not (run_dir / stable / 'manifest.json').is_file():
            return {**entry, 'status': 'refused',
                    'why': f'{stable} has no root entry or manifest; its legacy attempts cannot be retired'}
    entry['retires'] = retires
    analyses = run_dir / 'analyses'
    if not analyses.is_dir():
        return {**entry, 'why': 'no analyses tree'}
    if analyses.is_symlink():
        return {**entry, 'status': 'refused', 'why': 'analyses/ is a symbolic link'}
    for kind_dir in sorted(path for path in analyses.iterdir() if path.is_dir()):
        kind = kind_dir.name
        if kind_dir.is_symlink():
            return {**entry, 'status': 'refused', 'why': f'analyses/{kind} is a symbolic link'}
        if _stable(kind) is not None:
            # Its legacy attempts stay on disk; only the job row's entries for them are retired above.
            continue
        last, signatures = 0, []
        for child in sorted(kind_dir.iterdir()):
            match = figures.SEQUENCE.fullmatch(child.name)
            if match and child.is_dir():
                last = max(last, int(match.group(1)))
            elif child.is_dir():
                signatures.append(child)
        candidates = []
        for signature in signatures:
            if signature.is_symlink():
                return {**entry, 'status': 'refused', 'why': f'analyses/{kind}/{signature.name} is a symbolic link'}
            for attempt in sorted(path for path in signature.iterdir() if path.is_dir()):
                manifest = attempt / 'manifest.json'
                if not manifest.is_file():
                    continue
                if attempt.is_symlink():
                    return {**entry, 'status': 'refused',
                            'why': f'analyses/{kind}/{signature.name}/{attempt.name} is a symbolic link'}
                record = _read(manifest)
                if record is None:
                    return {**entry, 'status': 'refused',
                            'why': f'analyses/{kind}/{signature.name}/{attempt.name}/manifest.json is unreadable'}
                created, date = _stamp(record, attempt)
                candidates.append({'kind': kind, 'signature': signature.name, 'attempt': attempt.name,
                                   'old_path': attempt.relative_to(run_dir).as_posix(),
                                   'created': created, 'date': date})
        candidates.sort(key=lambda candidate: (candidate['created'], candidate['old_path']))
        for candidate in candidates:
            last += 1
            while (kind_dir / f'{last:04d}-{candidate["date"]}').exists():
                last += 1
            new_path = f'analyses/{kind}/{last:04d}-{candidate["date"]}'
            old_directory = candidate['old_path'] if candidate['old_path'] in directories else None
            move = {**candidate, 'action': 'move', 'run': run_id, 'new_path': new_path,
                    'old_directory': old_directory,
                    'new_directory': new_path if old_directory else None}
            if old_directory is not None:
                move['entry'] = copy.deepcopy(directories[old_directory])
            entry['moves'].append(move)
        moved = {candidate['attempt'] for candidate in candidates}
        for signature in signatures:
            remaining = sorted(path.name for path in signature.iterdir() if path.name not in moved)
            relative = f'analyses/{kind}/{signature.name}'
            if remaining:
                entry['kept'].append({'path': relative, 'entries': remaining})
            else:
                entry['removed'].append(relative)
    if entry['moves'] or entry['removed']:
        entry['status'] = 'move'
    elif entry['retires']:
        entry['status'] = 'retire'
    return entry


def _selected(workspace):
    """The (id, directory) pair of every run the workspace holds, by name."""
    runs = Path(workspace) / 'runs'
    if not runs.is_dir():
        return []
    return sorted((path.name, path) for path in runs.iterdir()
                  if path.is_dir() and not path.name.startswith('.'))


def plan(workspace):
    """What the migration would move in this workspace. Reads only, and never opens a missing database."""
    database = Path(workspace) / 'jobs.sqlite3'
    store = Store(database) if database.is_file() else None
    return [_entry(run_id, run_dir, store) for run_id, run_dir in _selected(workspace)]


def apply(entries, workspace):
    """Move every planned attempt, retire the stable kinds' legacy entries, and rewrite the records they named.

    The manifest is rewritten inside the moved directory. The job row is written once per run, after every one of its
    attempts moved or was retired, so a crash between two attempts leaves the row naming only directories that already
    moved. A retirement touches no file: the legacy tree keeps every byte and only the row loses the superseded entry.
    The backup is written last and only when something changed: a second `--apply` therefore writes nothing.
    """
    workspace = Path(workspace)
    database = workspace / 'jobs.sqlite3'
    store = Store(database) if database.is_file() else None
    done = []
    for entry in entries:
        if entry['status'] not in ('move', 'retire'):
            continue
        run_dir = workspace / 'runs' / entry['id']
        rebased = {}
        for move in entry['moves']:
            source, target = run_dir / move['old_path'], run_dir / move['new_path']
            if not source.is_dir():
                raise ValueError(f"{entry['id']}/{move['old_path']} is gone")
            if target.exists():
                raise ValueError(f"{entry['id']}/{move['new_path']} already exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            record = _read(target / 'manifest.json')
            if record is None:
                raise ValueError(f"{entry['id']}/{move['new_path']}/manifest.json is unreadable")
            record['directory'] = move['new_path']
            files.atomic_json(target / 'manifest.json', record)
            if move['old_directory'] is not None:
                rebased[move['old_directory']] = move['new_directory']
        if (rebased or entry['retires']) and store is not None:
            job = store.get(entry['id'])
            if job is not None:
                tasks = job.get('analyses') or []
                changed = False
                for task in tasks:
                    old = str(task.get('directory') or '')
                    new = rebased.get(old)
                    if new is None:
                        continue
                    task['directory'] = new
                    if 'log' in task:
                        task['log'] = _rebase(task['log'], old, new)
                    if isinstance(task.get('outputs'), list):
                        task['outputs'] = [_rebase(value, old, new) for value in task['outputs']]
                    changed = True
                retired = {retire['entry']['id']: retire for retire in entry['retires']}
                if retired:
                    kept = []
                    for index, task in enumerate(tasks):
                        record = retired.get(task.get('id'))
                        if record is None:
                            kept.append(task)
                            continue
                        # Keep the entry itself, and its place in the row, for `--rollback` to put back exactly.
                        record['index'] = index
                        record['entry'] = copy.deepcopy(task)
                        changed = True
                    tasks = kept
                if changed:
                    store.update(entry['id'], analyses=tasks)
        for relative in list(entry['removed']):
            try:
                (run_dir / relative).rmdir()
            except OSError:
                # A file was written since the plan read the tree: the directory now holds data, so it stays.
                entry['removed'].remove(relative)
                entry['kept'].append({'path': relative, 'entries': ['written after the plan']})
        done.extend(entry['moves'])
        done.extend(entry['retires'])
        entry['applied'] = True
    if done:
        files.atomic_json(workspace / BACKUP, {'tool': TOOL, 'version': VERSION,
                                               'created_at': files.now_iso(), 'moves': done})
    return done


def rollback(workspace):
    """Undo the moves and retirements in the backup, newest first; None when it cannot be applied cleanly.

    A record without an `action` is an older backup's move. A move puts its directory back; a retirement puts the row
    entry back where it was. Both restore the entry the backup recorded, so the row comes back exactly as it left.
    """
    workspace = Path(workspace)
    backup_path = workspace / BACKUP
    if not backup_path.is_file():
        print(f'no backup at {backup_path}')
        return None
    backup = json.loads(backup_path.read_text())
    records = [record for record in backup.get('moves') or [] if isinstance(record, dict)]
    moves = [record for record in records if record.get('action', 'move') != 'retire']
    retires = [record for record in records if record.get('action') == 'retire']
    runs = workspace / 'runs'
    missing = [move for move in moves if not (runs / move['run'] / move['new_path']).is_dir()]
    blocked = [move for move in moves if (runs / move['run'] / move['old_path']).exists()]
    for move in missing:
        print(f"missing {move['run']}/{move['new_path']}")
    for move in blocked:
        print(f"refused {move['run']}/{move['old_path']} already exists")
    if missing or blocked:
        return None
    database = workspace / 'jobs.sqlite3'
    store = Store(database) if database.is_file() else None
    rebased = {}
    for move in reversed(moves):
        run_dir = runs / move['run']
        source, target = run_dir / move['new_path'], run_dir / move['old_path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        record = _read(target / 'manifest.json')
        if record is not None:
            record['directory'] = move['old_path']
            files.atomic_json(target / 'manifest.json', record)
        if move.get('new_directory') is not None:
            rebased.setdefault(move['run'], {})[move['new_directory']] = move['old_directory']
    if store is not None:
        plans = {}
        for move in moves:
            changes = plans.setdefault(move['run'], {'replaced': {}, 'rebased': {}, 'inserted': []})
            if move.get('entry'):
                changes['replaced'][move['entry']['id']] = move['entry']
            elif move.get('new_directory') is not None:
                changes['rebased'][move['new_directory']] = move['old_directory']
        for retire in retires:
            if retire.get('entry'):
                plans.setdefault(retire['run'], {'replaced': {}, 'rebased': {}, 'inserted': []})
                plans[retire['run']]['inserted'].append(retire)
        for run_id, changes in plans.items():
            job = store.get(run_id)
            if job is None:
                continue
            kept = []
            for task in job.get('analyses') or []:
                replacement = changes['replaced'].get(task.get('id'))
                if replacement is not None:
                    kept.append(copy.deepcopy(replacement))
                    continue
                old = str(task.get('directory') or '')
                if old in changes['rebased']:
                    task['directory'] = changes['rebased'][old]
                kept.append(task)
            for retire in sorted(changes['inserted'], key=lambda record: record.get('index', len(kept))):
                kept.insert(min(int(retire.get('index') or 0), len(kept)), copy.deepcopy(retire['entry']))
            store.update(run_id, analyses=kept)
    return len(records)


def _line(entries, applied):
    """One line per action, one per signature directory left or removed, one per refusal."""
    for entry in entries:
        for move in entry['moves']:
            print(f'{("moved" if applied else "move")} {entry["id"]}/{move["kind"]}/'
                  f'{move["signature"]}/{move["attempt"]} -> {Path(move["new_path"]).name}')
        for retire in entry['retires']:
            print(f'{("retired" if applied else "retire")} {entry["id"]}/{retire["kind"]}/'
                  f'{retire["signature"]}/{retire["attempt"]}')
        for kept in entry['kept']:
            print(f'keep {entry["id"]}/{kept["path"].removeprefix("analyses/")} '
                  f'still holds {len(kept["entries"])}')
        for relative in entry['removed']:
            print(f'{("removed" if applied else "remove")} '
                  f'{entry["id"]}/{relative.removeprefix("analyses/")} (emptied)')
        if entry['status'] == 'refused':
            print(f'{entry["id"]} refused: {entry["why"]}')


def summary(entries):
    """`move=N unchanged=M`, with `retire=N` and `refused` when those happened."""
    counts = {'move': 0, 'unchanged': 0, 'retire': 0}
    for entry in entries:
        counts[entry['status']] = counts.get(entry['status'], 0) + 1
    text = f'move={counts["move"]} unchanged={counts["unchanged"]}'
    if counts.get('retire'):
        text += f' retire={counts["retire"]}'
    if counts.get('refused'):
        text += f' refused={counts["refused"]}'
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Rename legacy analysis attempts to sequence names and rebase the job rows (dry run by default)')
    parser.add_argument('--workspace', type=Path, default=None,
                        help='a workspace (the directory holding runs/ and jobs.sqlite3; default: the live one)')
    parser.add_argument('--apply', action='store_true',
                        help='perform the moves and retirements (default: report only)')
    parser.add_argument('--report', type=Path, default=None, help='write the planned entries here as JSON')
    parser.add_argument('--rollback', action='store_true',
                        help=f'apply the moves recorded in {BACKUP.as_posix()} in reverse')
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
        apply(entries, workspace)
    print(summary(entries))
    _line(entries, args.apply)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(entries, indent=2) + '\n')
        print(f'report: {args.report}')
    return 1 if any(entry['status'] == 'refused' for entry in entries) else 0


if __name__ == '__main__':
    raise SystemExit(main())
