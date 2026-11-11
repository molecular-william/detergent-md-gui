"""Migrate run records from the retired run types to the one `cg` type.

`aa_cg`, `sugar_cg` and `cg_composition` are gone as run types. Their runs are not gone: this rewrites the two
records that name a run type -- `runs/<id>/manifest.json` and the row in `jobs.sqlite3` -- into a `cg` record that
keeps its stage plan, settings, mapping snapshot, stages and outputs untouched, and states where it came from:

    legacy_run_type  the retired type this record was written under
    cg_model_kind    the parameterization kind the CG run reads: revision, reference or composition

The old values are archived first, under `runs/<id>/migration_history/`, and the manifest is written atomically. A
dry run by default; `--apply` performs it. A second apply is a no-op because `legacy_run_type` is the marker.

The migration never touches a stage directory, a trajectory, an analysis or a mapping. It refuses a run that is
still active rather than rewriting a record a worker owns.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from dashboard import files, paths
from dashboard.store import Store

TOOL = 'dashboard.cli.migrate_run_types'
VERSION = 1
RECORD = 'run-type-migration.json'
HISTORY = 'migration_history'

#: The retired type, and the `cg` kind its runs become. The three are different shapes of one user-facing run type:
#: a saved mapping's revision, a published Martini 3 reference, and a composed CG model.
RETIRED = {'aa_cg': ('revision', 'cg-v1'),
           'sugar_cg': ('reference', 'cg-reference-v1'),
           'cg_composition': ('composition', 'cg-composition-v1')}

ACTIVE = ('queued', 'waiting', 'running', 'cancelling')


def _status(run_id, run_dir, status, *, why=None, old=None, kind=None):
    return {'id': run_id, 'run': str(run_dir), 'status': status, 'why': why,
            'from': old, 'to': 'cg' if old else None, 'kind': kind}


def _selected(workspace, run_ids=None):
    runs = Path(workspace) / 'runs'
    if run_ids:
        return [(run_id, runs / run_id) for run_id in run_ids]
    return sorted(((path.parent.name, path.parent) for path in runs.glob('*/manifest.json')),
                  key=lambda pair: pair[0])


def _entry(run_id, run_dir, store):
    """What this run's migration would be, or why it will not guess."""
    manifest_path = Path(run_dir) / 'manifest.json'
    if not manifest_path.is_file():
        return _status(run_id, run_dir, 'refused', why='manifest.json is missing')
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        return _status(run_id, run_dir, 'refused', why=f'manifest.json is unreadable: {exc}')
    if not isinstance(manifest, dict):
        return _status(run_id, run_dir, 'refused', why='manifest.json is not an object')
    # A record that names no run type is the historical combined AA-to-CG job, which *is* `aa_cg`: the default
    # `protocol.run_type_of` used before the registry carried the name, and the reason `run_type_of` may default an
    # absent type to `cg` after this migration -- every absent record is rewritten here too.
    old = manifest.get('run_type') or 'aa_cg'
    if manifest.get('legacy_run_type'):
        return _status(run_id, run_dir, 'unchanged', why=f'already migrated from {manifest["legacy_run_type"]}')
    if old not in RETIRED:
        return _status(run_id, run_dir, 'unchanged', why=f'{old!r} is not a retired run type')
    record = store.get(run_id)
    if record is None:
        return _status(run_id, run_dir, 'refused', why='the job record is missing', old=old)
    if record.get('status') in ACTIVE:
        return _status(run_id, run_dir, 'refused', why=f'the run is {record["status"]}; stop it before migrating',
                       old=old)
    kind, workflow_version = RETIRED[old]
    return {**_status(run_id, run_dir, 'planned', old=old, kind=kind),
            'workflow_version': workflow_version, 'manifest': manifest, 'record': record}


def plan(workspace, run_ids=None):
    """What the migration would do to each run. Reads only."""
    store = Store(Path(workspace) / 'jobs.sqlite3')
    return [_entry(run_id, run_dir, store) for run_id, run_dir in _selected(workspace, run_ids)]


def _rewrite(entry, workspace):
    """Archive the old records, then write both new ones; return what changed."""
    run_dir = Path(entry['run'])
    run_id = entry['id']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    history = run_dir / HISTORY
    history.mkdir(parents=True, exist_ok=True)
    archive = history / f'run-type-{stamp}.json'
    files.atomic_json(archive, {'tool': TOOL, 'version': VERSION, 'from': entry['from'], 'to': 'cg',
                                'manifest': entry['manifest'], 'job': entry['record']})
    fields = {'run_type': 'cg', 'workflow_version': entry['workflow_version'],
              'legacy_run_type': entry['from'], 'cg_model_kind': entry['kind'],
              'run_type_migrated_at': stamp}
    manifest = {**entry['manifest'], **fields}
    files.atomic_json(run_dir / 'manifest.json', manifest)
    # The row is rewritten after the manifest so a crash between the two leaves the marker in the file and the
    # dry run of a retry reports the record as already migrated; the job row is then the only half left.
    Store(Path(workspace) / 'jobs.sqlite3').update(run_id, **fields)
    files.atomic_json(run_dir / RECORD, {'tool': TOOL, 'version': VERSION, 'migrated_at': stamp,
                                         'from': entry['from'], 'to': 'cg', 'kind': entry['kind'],
                                         'archive': str(archive.relative_to(run_dir)),
                                         'archive_sha256': files.sha256(archive)})
    return {'id': run_id, 'from': entry['from'], 'to': 'cg', 'kind': entry['kind'],
            'archive': str(archive.relative_to(run_dir)), 'archive_sha256': files.sha256(archive)}


def apply(entries, workspace):
    """Perform the planned migrations; unchanged and refused entries are left alone."""
    done = []
    for entry in entries:
        if entry['status'] != 'planned':
            continue
        done.append(_rewrite(entry, workspace))
        entry['applied'] = True
    return done


def _line(entry):
    if entry['status'] == 'planned':
        verb = 'migrated    ' if entry.get('applied') else 'would migrate'
        return (f'{entry["id"]}  {verb}  {entry["from"]} -> cg ({entry["kind"]}), '
                f'stage plan kept ({len((entry.get("manifest") or {}).get("stage_plan") or [])} stages)')
    if entry['status'] == 'unchanged':
        return f'{entry["id"]}  unchanged      {entry.get("why") or ""}'
    return f'{entry["id"]}  {entry["status"]:<12} {entry.get("why") or ""}'


def summary(entries):
    return [_line(entry) for entry in entries]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Migrate aa_cg/sugar_cg/cg_composition run records to the cg run type (dry run by default)')
    parser.add_argument('--workspace', type=Path, default=None,
                        help='a workspace (the directory holding runs/ and jobs.sqlite3; default: the live one)')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--run', action='append', dest='runs', default=[], metavar='ID',
                           help='migrate this run (repeatable)')
    selection.add_argument('--all', action='store_true', help='every run in the workspace (the default)')
    parser.add_argument('--apply', action='store_true', help='perform the migration (default: report only)')
    args = parser.parse_args(argv)

    workspace = args.workspace if args.workspace is not None else Path(paths.current().workspace)
    entries = plan(workspace, args.runs or None)
    if args.apply:
        apply(entries, workspace)
    for line in summary(entries):
        print(line)
    return 1 if any(entry['status'] == 'refused' for entry in entries) else 0


if __name__ == '__main__':
    raise SystemExit(main())
