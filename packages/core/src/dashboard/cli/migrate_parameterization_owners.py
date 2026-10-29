"""Give the parameterization records written before ownership existed a claim list, inferred from the saved drafts.

A record is addressed by content identity, so the drafts that carry that content are the mappings it belongs to. This
reads both stores and writes the claims -- nothing else: no revision, no hash, no path moves. A record whose content no
saved draft carries is reported `unclaimed` and left alone, because inventing an owner would put a delete in the wrong
hands; the fallback in `mappings.store` still answers for it from the drafts on disk.

Idempotent: a record that already names owners is `unchanged`, so a second run writes nothing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dashboard import files, paths
from dashboard.models import mappings
from dashboard.models.bonded import parameterization


def _workspace(root):
    return Path(root) if root is not None else Path(paths.current().workspace)


def _drafts_by_content():
    """The saved mappings, grouped by the content identity a parameterization record is addressed by."""
    grouped = {}
    for candidate in mappings.list_candidates():
        content = candidate.get('mapping_content_hash') or candidate.get('mapping_hash')
        if not content:
            continue
        grouped.setdefault(content, []).append(
            {'mapping_hash': candidate.get('mapping_hash'), 'name': candidate.get('name') or candidate.get('file')})
    return grouped


def plan(root=None):
    """What the migration would claim, per record. Reads only."""
    workspace = _workspace(root)
    grouped = _drafts_by_content()
    entries = []
    for path in sorted((workspace / 'parameterizations' / 'records').glob('*.json')):
        record = json.loads(path.read_text())
        content = record.get('mapping_content_hash') or path.stem
        existing = parameterization.owners(record)
        entry = {'content_hash': content, 'file': str(path), 'old': existing}
        if existing:
            entries.append({**entry, 'status': 'unchanged', 'new': None})
        elif grouped.get(content):
            entries.append({**entry, 'status': 'claim', 'new': grouped[content]})
        else:
            entries.append({**entry, 'status': 'unclaimed', 'new': None,
                            'why': 'no saved draft carries this content'})
    return entries


def apply(entries):
    written = []
    for entry in entries:
        if entry['status'] != 'claim':
            continue
        path = Path(entry['file'])
        record = json.loads(path.read_text())
        record['owners'] = entry['new']
        record['owners_inferred'] = True
        files.atomic_json(path, record)
        written.append(entry)
    return written


def summary(entries):
    counts = {}
    for entry in entries:
        counts[entry['status']] = counts.get(entry['status'], 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser(description='Claim parameterization records for the drafts that carry their content')
    parser.add_argument('--workspace', type=Path, default=None, help='a workspace to migrate (default: the live one)')
    parser.add_argument('--apply', action='store_true', help='write the claims (default: report only)')
    parser.add_argument('--report', type=Path, default=None, help='write the decided entries here as JSON')
    args = parser.parse_args()
    entries = plan(args.workspace)
    if args.apply:
        apply(entries)
    print(' '.join(f'{key}={value}' for key, value in sorted(summary(entries).items())))
    for entry in entries:
        if entry['status'] in ('claim', 'unclaimed'):
            names = ', '.join(item.get('name') or '?' for item in entry.get('new') or [])
            print(f"  {entry['status']:<10} {entry['content_hash'][:12]}  {names or entry.get('why') or ''}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(entries, indent=2) + '\n')
        print(f'report: {args.report}')


if __name__ == '__main__':
    main()
