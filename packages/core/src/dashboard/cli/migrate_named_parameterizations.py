"""Move the parameterization records addressed by content hash to the name their mapping goes by.

A record used to be `records/<content_hash>.json` because the hash was the address. It is now
`records/<slug>.json`, where the slug is `run_names.slug` of the mapping's display name, and the
`<hash>.revisions/` directory moves to `<slug>.revisions/` beside it. The hash stays on the record as
`legacy_hash`, so a run manifest or a reference that still names it can be traced, and the revision
directories it records are rewritten to where they now live -- otherwise a migrated record's recorded
baselines and starting coordinates would point at a directory that no longer exists.

The draft name is resolved from the record's own claim list (`owners`, written when ownership was how
a record knew its mappings) and, for a record that has none, from the saved drafts carrying its content.
A record two names claim is reported `ambiguous` and left for a person: choosing one would hand the
other mapping's revisions to the wrong model. A record no name claims is `unclaimed` and left alone.

Dry run by default; `--apply` moves. Idempotent: a record already named is `unchanged`, so a second run
writes nothing. Nothing is deleted: the old file is removed only as the second half of a completed
move, and a target that already exists is reported rather than overwritten.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from contextlib import contextmanager
from pathlib import Path

from dashboard import files, paths, run_names
from dashboard.models import mappings
from dashboard.models.bonded import parameterization

_HASH = re.compile(r'[a-f0-9]{64}')


@contextmanager
def _selected(root=None):
    """Read and write one workspace's store, named or the live one."""
    if root is None:
        yield Path(paths.current().workspace)
        return
    workspace = Path(root)
    with paths.use(paths.Paths(workspace=workspace)):
        yield workspace


def _drafts_by_content():
    """The saved mappings, grouped by the content identity a parameterization record is addressed by."""
    grouped = {}
    for candidate in mappings.list_candidates():
        if candidate.get('error') or not candidate.get('mapping_content_hash'):
            continue
        grouped.setdefault(candidate['mapping_content_hash'], []).append({
            'mapping_hash': candidate.get('mapping_hash'),
            'name': candidate.get('name') or candidate.get('file'),
            'slug': candidate.get('parameterization_name') or run_names.slug(candidate.get('name')
                                                                            or candidate.get('file')),
        })
    return grouped


def _claim_slugs(record, drafts):
    """The distinct record names this record's mappings go by, from its claims and then from the drafts."""
    names = [entry.get('name') for entry in parameterization.owners(record) if entry.get('name')]
    if not names:
        names = [entry.get('name') for entry in drafts if entry.get('name')]
    return sorted({run_names.slug(name) for name in names if name})


def _rebase(record, old, new):
    """Point the revision records' own directories at the directory the revisions are moving to."""
    prefix, target = f'records/{old}.revisions', f'records/{new}.revisions'
    changed = False
    for item in record.get('revisions') or []:
        if not isinstance(item, dict):
            continue
        for key in ('coordinates', 'distributions'):
            block = item.get(key)
            if isinstance(block, dict) and isinstance(block.get('directory'), str) \
                    and block['directory'].startswith(prefix):
                block['directory'] = target + block['directory'][len(prefix):]
                changed = True
    return changed


def plan(root=None):
    """What the migration would move, per record. Reads only."""
    with _selected(root) as workspace:
        records_root = workspace / 'parameterizations' / 'records'
        drafts = _drafts_by_content()
        entries = []
        for path in sorted(records_root.glob('*.json')) if records_root.is_dir() else []:
            if not _HASH.fullmatch(path.stem):
                entries.append({'status': 'unchanged', 'file': str(path), 'name': path.stem,
                                'why': 'already named'})
                continue
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError):
                entries.append({'status': 'unreadable', 'file': str(path), 'legacy_hash': path.stem,
                                'why': 'the record does not parse'})
                continue
            content = record.get('mapping_content_hash') or path.stem
            base = {'file': str(path), 'content_hash': content, 'legacy_hash': path.stem}
            names = _claim_slugs(record, drafts.get(content) or [])
            if not names:
                entries.append({**base, 'status': 'unclaimed',
                                'why': 'no saved draft or claim names this record'})
                continue
            if len(names) > 1:
                entries.append({**base, 'status': 'ambiguous', 'names': names,
                                'why': 'two names claim this record; a person must choose'})
                continue
            name = names[0]
            target = records_root / f'{name}.json'
            moved = records_root / f'{name}.revisions'
            if target.exists() or moved.exists():
                entries.append({**base, 'status': 'conflict', 'name': name,
                                'why': 'a record or revision directory already answers this name'})
                continue
            entries.append({**base, 'status': 'move', 'name': name})
        return entries


def apply(entries):
    """Move every `move` entry: the revision directory, then the record, stamped with its old hash."""
    written = []
    for entry in entries:
        if entry['status'] != 'move':
            continue
        old = Path(entry['file'])
        old_revisions = old.parent / f'{entry["legacy_hash"]}.revisions'
        new_revisions = old.parent / f'{entry["name"]}.revisions'
        record = json.loads(old.read_text())
        if old_revisions.is_dir() and not new_revisions.exists():
            shutil.move(str(old_revisions), str(new_revisions))
        record['legacy_hash'] = entry['legacy_hash']
        record['name'] = entry['name']
        _rebase(record, entry['legacy_hash'], entry['name'])
        target = old.parent / f'{entry["name"]}.json'
        files.atomic_json(target, record)
        old.unlink(missing_ok=True)
        written.append(entry)
    return written


def summary(entries):
    counts = {}
    for entry in entries:
        counts[entry['status']] = counts.get(entry['status'], 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser(description='Move parameterization records from content-hash names to mapping names')
    parser.add_argument('--workspace', type=Path, default=None, help='a workspace to migrate (default: the live one)')
    parser.add_argument('--apply', action='store_true', help='move the records (default: report only)')
    parser.add_argument('--report', type=Path, default=None, help='write the decided entries here as JSON')
    args = parser.parse_args()
    entries = plan(args.workspace)
    if args.apply:
        apply(entries)
    print(' '.join(f'{key}={value}' for key, value in sorted(summary(entries).items())))
    for entry in entries:
        if entry['status'] in ('move', 'unclaimed', 'ambiguous', 'conflict', 'unreadable'):
            names = ', '.join(entry.get('names') or [entry.get('name') or '']) if entry.get('names') or entry.get('name') else ''
            print(f"  {entry['status']:<10} {entry.get('legacy_hash', '')[:12]:<12} {names}"
                  + (f"  ({entry['why']})" if entry.get('why') else ''))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(entries, indent=2) + '\n')
        print(f'report: {args.report}')


if __name__ == '__main__':
    main()
