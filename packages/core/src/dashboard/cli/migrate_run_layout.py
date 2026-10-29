"""Migrate the runs prepared before this tree had one layout: `stages/` plus a data-only `inputs/`.

Eleven runs predate the layout. Nine `aa_only`/`aa_cg` runs keep a byte copy of their prepared stage tree in `inputs/`
and copied `.py`/`.sh` helpers inside their stages. Two `pdc` runs keep their stage directories at the run root and have
no `stages/`, no `inputs/` and no `input_snapshot_sha256`. Neither shape is repaired by rewriting a manifest: the old
bytes have to be archived and the live tree moved, never destroyed.

What this does, per run, and only with `--apply`:

* `pdc`: archive the stage directories to `legacy_evidence/run-tree-<date>.tar.gz`, then move them under `stages/`.
  `manifest.json`, `logs/`, `analyses/` and every other file are left exactly as they were.
* `aa_only`/`aa_cg`: archive `inputs/` and every copied `.py`/`.sh` inside `stages/` to `legacy_evidence.tar.gz`, then
  delete those live copies. Every stage output, every generated data file, `manifest.json`, `logs/` and `analyses/`
  stay. `pdc` stage scripts are not touched: they are not copies of a prepared `inputs/` tree.

Every touched run gets `legacy_layout.json` naming what moved, what was deleted, and the archive with its sha256.
`manifest.json` is never rewritten; its `input_snapshot_sha256` stops verifying because the directory it digested was
archived, and the record says so.

It reports rather than guesses: a symlinked run directory or stage directory, a run matching neither legacy shape, a
`pdc` run that already has `stages/`, and a run carrying `legacy_layout.json` (skipped, so a second run is a no-op).
A symlink nested inside a *moved* stage directory travels with it and is archived as a link -- the pdc back-map tree
holds 100 of them, pointing into the tool checkout, and refusing them would make the migration impossible. A symlink
anywhere in a tree this migration *deletes* is refused: deletion is the one operation that cannot be undone in place.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from dashboard import files, paths

TOOL = 'dashboard.cli.migrate_run_layout'
VERSION = 1

#: What every touched run records, whatever its shape.
RECORD = 'legacy_layout.json'

#: The stage directories a legacy pdc run leaves at its root, named as that run's manifest named them.
LEGACY_PDC_STAGES = (
    '0_prepare', '1_system', '2_minimisation', '3_nvt', '4_npt',
    '2_assessment', '3_assessment', '4_extension', '5_assessment', '6_backmap',
)

NOTE = ("The manifest's input_snapshot_sha256 no longer verifies because its directory was archived; "
        'manifest.json was not rewritten.')


def _status(run_id, run_dir, status, *, why=None, moved=(), moved_to=(), deleted=(), archive=None, date=None):
    return {'id': run_id, 'run': str(run_dir), 'status': status, 'why': why,
            'moved': list(moved), 'moved_to': list(moved_to), 'deleted': list(deleted),
            'archive': archive, 'date': date}


def _legacy_pdc_stages(run_dir):
    """The known pdc stage directories present at the run root."""
    return [name for name in LEGACY_PDC_STAGES if (run_dir / name).is_dir()]


def _symlink_inside(root):
    """The first symbolic link below `root`, or None; a link to a directory is never walked through."""
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(dirs)
        for name in sorted(dirs + names):
            candidate = Path(directory) / name
            if candidate.is_symlink():
                return candidate
    return None


def _code_files(root):
    """Every copied `.py`/`.sh` under a stage tree: the helpers phase 2 replaced with repository modules."""
    found = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(dirs)
        found += [Path(directory) / name for name in sorted(names) if name.endswith(('.py', '.sh'))]
    return found


def _entry(run_id, run_dir):
    """What this run's migration would be, or why it will not guess."""
    if not run_id or Path(run_id).name != run_id:
        return _status(run_id, run_dir, 'refused', why='invalid run id')
    if run_dir.is_symlink():
        return _status(run_id, run_dir, 'refused', why='the run directory is a symbolic link')
    if not run_dir.is_dir():
        return _status(run_id, run_dir, 'refused', why='no such run directory')
    if (run_dir / RECORD).exists():
        return _status(run_id, run_dir, 'skipped', why=f'{RECORD} present: already migrated')

    stages, inputs = run_dir / 'stages', run_dir / 'inputs'
    for name, path in (('stages', stages), ('inputs', inputs)):
        if path.is_symlink():
            return _status(run_id, run_dir, 'refused', why=f'{name} is a symbolic link')
    for name in LEGACY_PDC_STAGES:
        if (run_dir / name).is_symlink():
            return _status(run_id, run_dir, 'refused', why=f'the legacy stage directory {name} is a symbolic link')

    legacy = _legacy_pdc_stages(run_dir)
    date = files.now_iso()
    if legacy:
        if stages.exists():
            return _status(run_id, run_dir, 'refused',
                           why='legacy pdc stage directories beside a stages/ tree: refusing to guess which is live')
        if inputs.exists():
            return _status(run_id, run_dir, 'refused',
                           why='legacy pdc stage directories beside an inputs/ directory: not a shape this migration knows')
        return _status(run_id, run_dir, 'moved', moved=legacy,
                       moved_to=[f'stages/{name}' for name in legacy],
                       archive=f'legacy_evidence/run-tree-{date[:10]}.tar.gz', date=date)

    if not (stages.is_dir() and inputs.is_dir()):
        return _status(run_id, run_dir, 'unknown',
                       why='neither the pdc stage tree nor the stages/ + inputs/ pair is present')
    if (inputs / 'inputs.json').is_file():
        return _status(run_id, run_dir, 'skipped', why='inputs/ holds inputs.json: already on the current layout')

    link = _symlink_inside(inputs)
    if link is not None:
        return _status(run_id, run_dir, 'refused',
                       why=f'a symbolic link is inside the inputs/ tree being deleted: {link.relative_to(run_dir).as_posix()}')
    code = _code_files(stages)
    for path in code:
        if path.is_symlink():
            return _status(run_id, run_dir, 'refused',
                           why=f'copied code {path.relative_to(run_dir).as_posix()} is a symbolic link')
    return _status(run_id, run_dir, 'trimmed', deleted=['inputs'] + [path.relative_to(run_dir).as_posix() for path in code],
                   archive='legacy_evidence.tar.gz', date=date)


def _selected(workspace, run_ids=None):
    """The (id, directory) pairs to consider: the named runs, or every run in the workspace."""
    root = Path(workspace) / 'runs'
    if run_ids:
        return [(run_id, root / run_id) for run_id in run_ids]
    if not root.is_dir():
        return []
    return [(path.name, path) for path in sorted(root.iterdir()) if path.is_dir() or path.is_symlink()]


def plan(workspace, run_ids=None):
    """What the migration would do to each run. Reads only."""
    return [_entry(run_id, run_dir) for run_id, run_dir in _selected(workspace, run_ids)]


def _expected(run_dir, relatives):
    """The archive's own table of contents, taken from the tree as it stands now."""
    expected = {}
    for relative in relatives:
        root = run_dir / relative
        if root.is_symlink():
            expected[relative] = ('link', os.readlink(root))
        elif root.is_file():
            expected[relative] = ('file', files.sha256(root))
        elif root.is_dir():
            for directory, dirs, names in os.walk(root, followlinks=False):
                dirs[:] = sorted(dirs)
                for name in sorted(dirs + names):
                    path = Path(directory) / name
                    key = path.relative_to(run_dir).as_posix()
                    if path.is_symlink():
                        expected[key] = ('link', os.readlink(path))
                    elif path.is_file():
                        expected[key] = ('file', files.sha256(path))
    return expected


def _proved(run_dir, archive_path, relatives):
    """Refuse an archive that does not read back as the tree it was made from, before anything is deleted."""
    expected = _expected(run_dir, relatives)
    found = set()
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive:
            if member.isdir():
                continue
            found.add(member.name)
            if member.issym():
                actual = ('link', member.linkname)
            else:
                actual = ('file', hashlib.sha256(archive.extractfile(member).read()).hexdigest())
            if expected.get(member.name) != actual:
                raise ValueError(f'the archive does not round-trip: {member.name}')
    if set(expected) != found:
        raise ValueError(f'the archive is missing or adds entries: {sorted(set(expected) ^ found)}')


def _pack(run_dir, relatives, temporary):
    """Write one gzip tarball, using pigz when it is installed.

    A legacy pdc tree is tens of gigabytes of already-compressed XTC; the compressor is therefore a throughput
    decision, not a ratio one. `pigz` spreads that over every core and still writes a standard gzip stream, so the
    proof step reads the same archive either way. Level 1 is deliberate for the same reason.
    """
    pigz = shutil.which('pigz')
    if pigz is None:
        with tarfile.open(temporary, 'w:gz', compresslevel=1) as archive:
            for relative in relatives:
                archive.add(run_dir / relative, arcname=relative, recursive=True)
        return
    with open(temporary, 'wb') as raw:
        process = subprocess.Popen([pigz, '-1', '-c'], stdin=subprocess.PIPE, stdout=raw)
        try:
            with tarfile.open(fileobj=process.stdin, mode='w|') as archive:
                for relative in relatives:
                    archive.add(run_dir / relative, arcname=relative, recursive=True)
        finally:
            process.stdin.close()
            code = process.wait()
        if code != 0:
            raise RuntimeError(f'pigz exited {code} while archiving {run_dir.name}')


def _archive(run_dir, relatives, destination):
    """Pack these run-relative paths into a gzip tarball, then prove it before publishing it."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + destination.name, suffix='.tmp', dir=destination.parent)
    os.close(fd)
    try:
        _pack(run_dir, relatives, temporary)
        _proved(run_dir, temporary, relatives)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def _record(run_dir, entry, action):
    """The migration's own note beside the run; the manifest is not part of it."""
    archive = run_dir / entry['archive']
    record = {'tool': TOOL, 'version': VERSION, 'date': entry['date'], 'action': action,
              'moved': entry['moved'], 'moved_to': entry['moved_to'], 'deleted': entry['deleted'],
              'archive': entry['archive'], 'archive_sha256': files.sha256(archive), 'note': NOTE}
    files.atomic_json(run_dir / RECORD, record)
    return record


def _move(run_dir, entry):
    _archive(run_dir, entry['moved'], run_dir / entry['archive'])
    (run_dir / 'stages').mkdir()
    for relative in entry['moved']:
        shutil.move(str(run_dir / relative), str(run_dir / 'stages' / relative))


def _trim(run_dir, entry):
    _archive(run_dir, entry['deleted'], run_dir / entry['archive'])
    for relative in entry['deleted']:
        path = run_dir / relative
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def apply(entries):
    """Archive, then move or delete what `plan` decided; return the records written."""
    records = []
    for entry in entries:
        if entry['status'] not in ('moved', 'trimmed'):
            continue
        run_dir = Path(entry['run'])
        if entry['status'] == 'moved':
            _move(run_dir, entry)
        else:
            _trim(run_dir, entry)
        record = _record(run_dir, entry, entry['status'])
        entry['applied'] = True
        entry['archive_sha256'] = record['archive_sha256']
        records.append({'id': entry['id'], **record})
    return records


def _line(entry):
    """One line per run: what would happen, or what did."""
    applied = entry.get('applied', False)
    if entry['status'] == 'moved':
        verb = 'moved' if applied else 'would move'
        detail = f'{len(entry["moved"])} stage directories -> stages/ ; archive {entry["archive"]}'
    elif entry['status'] == 'trimmed':
        verb = 'trimmed' if applied else 'would trim'
        detail = f'{len(entry["deleted"]) - 1} code files and inputs/ -> {entry["archive"]}'
    else:
        verb, detail = entry['status'], entry.get('why') or ''
    return f'{entry["id"]}  {verb:<11} {detail}'


def summary(entries):
    return [_line(entry) for entry in entries]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Move legacy run trees to stages/ and archive the copied inputs and helper code (dry run by default)')
    parser.add_argument('--workspace', type=Path, default=None, help='a workspace to migrate (default: the live one)')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--run', action='append', dest='runs', default=[], metavar='ID',
                           help='migrate this run (repeatable)')
    selection.add_argument('--all', action='store_true', help='every run in the workspace (the default)')
    parser.add_argument('--apply', action='store_true', help='perform the migration (default: report only)')
    args = parser.parse_args(argv)

    workspace = args.workspace if args.workspace is not None else Path(paths.current().workspace)
    entries = plan(workspace, args.runs or None)
    if args.apply:
        apply(entries)
    for line in summary(entries):
        print(line)
    return 1 if any(entry['status'] in ('refused', 'unknown') for entry in entries) else 0


if __name__ == '__main__':
    raise SystemExit(main())
