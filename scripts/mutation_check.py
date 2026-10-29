#!/usr/bin/env python3
"""Which of these tests are load-bearing, measured by breaking the code one line at a time.

The fast tier's count says how many tests there are and nothing about which of them would notice a
change. This applies one mutation at a time from `scripts/mutants.json` to a module under
`analysis/` or `execution/adapters/` (engine or feature, as the mutant's path says), runs the test selection that mutant names,
and reports whether the suite caught it.

    scripts/mutation_check.py [--only <id>] [--json <path>] [--timeout <seconds>]

Every expectation is "caught" except the control, a mutant whose replacement is its own target: a
harness that cannot report a *survivor* cannot tell "the tests caught this" from "the tests never
ran", so the control has to come back surviving or the run is void -- the same rule this repository
states for a scratch harness whose control fails.

Three things this keeps, each of them a way this instrument could lie:

* **The mutant is the file's own text, applied once or not at all.** A target that does not occur
  exactly once is reported as `stale` and fails the run, because a mutant whose line moved is not a
  passing mutant.
* **The file goes back byte for byte, and the restore is verified by hash.** A failure here stops the
  run loudly rather than leaving a mutated module behind.
* **A file with an uncommitted change is refused**, because restoring from the bytes read first would
  discard somebody's edit -- the one way this instrument could destroy work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).resolve().parent / 'mutants.json'
INTERPRETER = ROOT / '.venv/bin/python'


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def has_uncommitted_changes(path: Path) -> bool:
    """True when git holds a change there -- a restore would discard it."""
    done = subprocess.run(['git', 'status', '--porcelain', '--', str(path.relative_to(ROOT))],
                          cwd=ROOT, capture_output=True, text=True, check=False)
    return bool(done.stdout.strip())


def run_selection(selection: str, timeout: float):
    """(verdict, seconds, last line of output) for one test selection."""
    started = time.monotonic()
    try:
        done = subprocess.run([str(INTERPRETER), '-m', 'pytest', selection, '-q', '-n', '0',
                               '-p', 'no:cacheprovider'],
                              cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 'error', time.monotonic() - started, f'timed out after {timeout:.0f}s'
    lines = (done.stdout or done.stderr or '').strip().splitlines()
    return ('caught' if done.returncode != 0 else 'survived'), time.monotonic() - started, lines[-1] if lines else ''


def check_one(mutant, timeout):
    """Result dict for one mutant: apply, run, restore, verify."""
    path = ROOT / mutant['file']
    result = {key: mutant[key] for key in ('id', 'file', 'why', 'tests', 'expect')}
    if not path.is_file():
        result.update(verdict='stale', detail=f"no such file: {mutant['file']}")
        return result
    if has_uncommitted_changes(path):
        result.update(verdict='stale',
                      detail=f"refused: {mutant['file']} has uncommitted changes a restore would discard")
        return result

    original = path.read_text()
    occurrences = original.count(mutant['old'])
    if occurrences != 1:
        result.update(verdict='stale', detail=f"the target occurs {occurrences} times in {mutant['file']}")
        return result

    before = digest(original)
    path.write_text(original.replace(mutant['old'], mutant['new'], 1))
    try:
        verdict, seconds, tail = run_selection(mutant['tests'], timeout)
    finally:
        path.write_text(original)
        restored = digest(path.read_text())
    if restored != before:
        result.update(verdict='restore-failed',
                      detail=f'{mutant["file"]} is not byte-identical to what was read: do not trust the tree')
        return result

    result.update(verdict=verdict, seconds=round(seconds, 2), detail=tail,
                  expectation_met=verdict == mutant['expect'])
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--only', help='run the mutants whose id contains this text')
    parser.add_argument('--json', help='write the results here as JSON')
    parser.add_argument('--timeout', type=float, default=300.0, help='seconds per mutant (default 300)')
    args = parser.parse_args(argv)

    mutants = [m for m in json.loads(MANIFEST.read_text())['mutants'] if not args.only or args.only in m['id']]
    if not mutants:
        print(f'no mutant matches --only {args.only}')
        return 2

    results = []
    for mutant in mutants:
        result = check_one(mutant, args.timeout)
        results.append(result)
        mark = '' if result.get('expectation_met') is not False else '   <-- NOT MET'
        print(f'{result["id"]:44} {result["verdict"]:9} {result.get("seconds", ""):>6}  '
              f'expected {result["expect"]:8}{mark}  {str(result.get("detail", ""))[:90]}')
        if result['verdict'] == 'restore-failed':
            print('\nSTOPPING: a restore did not verify. Check the module by hand before anything else.')
            return 3

    counts = {name: sum(1 for r in results if r['verdict'] == name)
              for name in ('caught', 'survived', 'error', 'stale', 'restore-failed')}
    print(f'\n{len(results)} mutants: {counts["caught"]} caught, {counts["survived"]} survived, '
          f'{counts["error"]} error, {counts["stale"]} stale')
    failures = [r['id'] for r in results if r.get('expectation_met') is False]
    if args.json:
        Path(args.json).write_text(json.dumps({'results': results, 'failures': failures}, indent=2))
        print(f'written to {args.json}')
    if failures:
        print(f'\nNOT MET: {", ".join(failures)}')
        return 1
    print('\nevery mutant behaved as its entry says')
    return 0


if __name__ == '__main__':
    sys.exit(main())
