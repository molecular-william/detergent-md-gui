#!/usr/bin/env python3
"""Idempotently add environment-variable indirection to CG stage scripts.

See module docstring in the shipped version for full rationale. This revision
relaxes the migrated-check to a single sentinel so scripts that never
contained a topology literal still report as migrated after --apply.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

SCRIPTS = (
    'aa_reference.sh',
    'map_trajectory.sh',
    'fit_topology.sh',
    'cg_simulation.sh',
    'assess.sh',
    'sasa.sh',
)
HERE = Path(__file__).resolve().parent

REF_DIR_LINE_MARKER = 'AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"'
REF_DIR_LINE = REF_DIR_LINE_MARKER + '\n'

LITERAL_REPLACEMENTS = (
    ('DDM_initial.itp', '$INITIAL_ITP'),
    ('DDM.itp', '$FINAL_ITP'),
    ('../1_AA-reference/prod/', '$AA_REFERENCE_DIR/'),
)

# Bare DDM word: not preceded or followed by a word character, not preceded
# by '$', not part of an identifier. Excludes comment-only lines.
BARE_DDM = re.compile(r'(?<![$\w])DDM(?![.\w])')


def _split_shebang(text: str) -> tuple[str, str]:
    if text.startswith('#!'):
        newline = text.find('\n')
        if newline == -1:
            return text + '\n', ''
        return text[:newline + 1], text[newline + 1:]
    return '#!/bin/bash\n', text


def _migrate_text(text: str) -> tuple[str, list[str]]:
    report: list[str] = []
    shebang, body = _split_shebang(text)

    if REF_DIR_LINE_MARKER not in body:
        body = REF_DIR_LINE + body
        report.append('inserted AA_REFERENCE_DIR default after shebang')

    for old, new in LITERAL_REPLACEMENTS:
        if old in body:
            count = body.count(old)
            body = body.replace(old, new)
            report.append(f'{old} -> {new} ({count}x)')

    for line_number, line in enumerate(body.splitlines(), 1):
        code = line.split('#', 1)[0]
        if BARE_DDM.search(code):
            report.append(f'MANUAL: line {line_number}: {line.strip()}')

    return shebang + body, report


def _status(script: Path) -> str:
    return 'migrated' if REF_DIR_LINE_MARKER in script.read_text() else 'pending'


def _apply(script: Path, *, apply: bool) -> list[str]:
    original = script.read_text()
    migrated, report = _migrate_text(original)
    if migrated == original:
        return [f'{script.name}: already migrated']
    if apply:
        backup = script.with_suffix(script.suffix + '.pre-4.2.bak')
        if not backup.exists():
            shutil.copy2(script, backup)
        script.write_text(migrated)
        return [f'{script.name}: migrated (backup {backup.name})'] + [f'  {line}' for line in report]
    return [f'{script.name}: would migrate'] + [f'  {line}' for line in report]


def _check(scripts) -> int:
    pending = [s.name for s in scripts if _status(s) != 'migrated']
    if pending:
        print('Unmigrated scripts: ' + ', '.join(pending))
        return 1
    print('All six CG scripts are migrated.')
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--dry-run', action='store_true')
    group.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)

    scripts = [HERE / name for name in SCRIPTS]
    missing = [s.name for s in scripts if not s.is_file()]
    if missing:
        print('Missing scripts: ' + ', '.join(missing), file=sys.stderr)
        return 2

    if args.check:
        return _check(scripts)

    for script in scripts:
        for line in _apply(script, apply=args.apply):
            print(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())