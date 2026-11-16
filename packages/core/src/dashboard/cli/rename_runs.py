"""Rename each legacy hex-id run to the slug of its own label, with a reversible ledger.

A run's name is its identity: the directory runs/<name>, the job row primary key and its JSON id, and every
cross-reference a prepared record keeps (run_id, source_run_id, reference_run_id, and an inputs entry whose root is
runs). The ten runs on disk still carry a random hex id; this migration is the one-time act that moves them to the
name a reader can recognise, and retires the old id so a later run can never inherit it.

Dry run by default: it prints one line per rename and writes nothing. --apply renames one run at a time -- the run
directory first, then its row and the records that name it -- and stops on the first failure. Every original file
text and job row is kept in <workspace>/.named-migration/run-rename.json; --rollback restores the names, the row
texts/revisions, the file texts and the retired entries from it. A second --apply reports nothing to do.

What a run's rename rewrites:

* runs/<old> to runs/<new>, refusing an existing or symbolic-link target;
* the job row primary key, its JSON id and its cross-references, every other job row's cross-references to the
  old id (all stored rows, not only the renamed one), and the renamed row's own path strings (console log, command);
* every run's manifest.json, inputs/inputs.json and provenance.json cross-references, the renamed run's manifest id,
  each inputs path under root runs that begins with <old>/, and every string value in the renamed run's own
  manifest/inputs/provenance and analyses records that names runs/<old> (an absolute stage log/cwd/command, an
  analysis command, resume_history, an environment value) -- another run's strings are left alone;
* every analyses/<kind>/<seq>/{request,manifest,result,progress}.json and every stages/07_reference/reference.json,
  by exact text replacement;
* every parameterization record's and job's run cross-references;
* the run is retired (retired_runs) once its files and row are written.

A name is run_names.slug(label), suffixed by run_names.unique when it collides casefolded with any other live job id
or another new name. A run whose id is already that slug (or its -N suffix) is left alone. The migration refuses to
run while any job or analysis is queued, running or cancelling.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

from dashboard import files, paths, run_names
from dashboard.analysis.runs import references
from dashboard.execution import run_inputs
from dashboard.store import Store

TOOL = 'dashboard.cli.rename_runs'
VERSION = 1
LEDGER = Path('.named-migration') / 'run-rename.json'
RUNS = 'runs'
MANIFEST = 'manifest.json'
INPUTS = 'inputs/inputs.json'
PROVENANCE = 'provenance.json'
REFERENCE = 'stages/07_reference/reference.json'
ANALYSIS_FILES = ('request.json', 'manifest.json', 'result.json', 'progress.json')
PARAMETERIZATION_DIRECTORIES = ('parameterizations/records', 'parameterizations/jobs')
KEYS = ('run_id', 'source_run_id', 'reference_run_id')
BUSY = ('queued', 'running', 'cancelling')


def _workspace(root=None):
    return Path(root) if root is not None else Path(paths.current().workspace)


def _database(workspace):
    return Path(workspace) / 'jobs.sqlite3'


def _ledger_path(workspace):
    return Path(workspace) / LEDGER


def _read_rows(database, *, immutable=False):
    """Every job row as stored (id, text, data, revision), oldest first, without opening the store for writing.

    A dry run reads with SQLite's immutable flag: a WAL database answered by an ordinary read-only connection creates
    the -shm/-wal side files, which is exactly the write a dry run must not make. Apply and rollback read the live
    journal after their own busy check.
    """
    database = Path(database)
    if not database.is_file():
        return []
    query = '?mode=ro&immutable=1' if immutable else '?mode=ro'
    try:
        connection = sqlite3.connect(f'{database.resolve().as_uri()}{query}', uri=True)
        try:
            return [{'id': row[0], 'text': row[1], 'data': json.loads(row[1]), 'revision': row[2]}
                    for row in connection.execute(
                        "SELECT id, data, revision FROM jobs ORDER BY json_extract(data,'$.created'), rowid")]
        finally:
            connection.close()
    except (sqlite3.Error, ValueError) as exc:
        raise ValueError(f'{database} cannot be read: {exc}') from exc


def _read_retired(database, *, immutable=False):
    database = Path(database)
    if not database.is_file():
        return []
    query = '?mode=ro&immutable=1' if immutable else '?mode=ro'
    try:
        connection = sqlite3.connect(f'{database.resolve().as_uri()}{query}', uri=True)
        try:
            return [row[0] for row in connection.execute('SELECT name FROM retired_runs')]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValueError(f'{database} has no readable retired names: {exc}') from exc


def _busy(rows):
    """Every working run or analysis this store records; the migration refuses to touch a live workspace."""
    working = []
    for row in rows:
        job = row['data']
        if job.get('status') in BUSY:
            working.append(str(job.get('id')))
        for task in job.get('analyses') or []:
            if isinstance(task, dict) and task.get('status') in BUSY:
                working.append(f'{job.get("id")}/{task.get("id")}')
    return working


def _unique_name(base, number):
    """The nth candidate run_names.unique would try, so an id it already gave a run is recognised."""
    tail = '' if number == 1 else f'-{number}'
    stem = base[:run_names.MAX - len(tail)].rstrip('-_') or 'run'
    return f'{stem}{tail}'


def _named(name, base):
    """Whether a run already carries its label's slug, including the -N suffix run_names.unique adds."""
    if name == base:
        return True
    match = re.fullmatch(r'.*-([0-9]+)', name)
    return bool(match and int(match.group(1)) >= 2 and _unique_name(base, int(match.group(1))) == name)


def _rewrite_references(node, old, new):
    """Replace every run cross-reference in this document; return how many values changed.

    The keys are the one spelling a run reference has, and an inputs entry under root runs names the run in its path.
    Everything else -- a stage command, a log path, a parameterization work directory -- is history and is left alone.
    """
    changed = 0
    if isinstance(node, dict):
        if node.get('root') == 'runs' and isinstance(node.get('path'), str) and node['path'].startswith(old + '/'):
            node['path'] = new + node['path'][len(old):]
            changed += 1
        for key, value in node.items():
            if key in KEYS and isinstance(value, str) and old in value:
                node[key] = value.replace(old, new)
                changed += 1
            elif isinstance(value, (dict, list)):
                changed += _rewrite_references(value, old, new)
    elif isinstance(node, list):
        for item in node:
            changed += _rewrite_references(item, old, new)
    return changed


def _reference_leaks(node, old, path=''):
    """The dotted paths where this document still holds the old run reference."""
    found = []
    if isinstance(node, dict):
        if node.get('root') == 'runs' and isinstance(node.get('path'), str) and node['path'].startswith(old + '/'):
            found.append(f'{path}.path')
        for key, value in node.items():
            if key in KEYS and isinstance(value, str) and old in value:
                found.append(f'{path}.{key}')
            elif isinstance(value, (dict, list)):
                found.extend(_reference_leaks(value, old, f'{path}.{key}'))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(_reference_leaks(item, old, f'{path}[{index}]'))
    return found


def _rewrite_own_strings(node, old, new):
    """Replace every string value naming this run's own old directory; a longer run name is not a match.

    A renamed run's manifest keeps absolute stage log/cwd/command paths, its analyses commands, resume_history and
    environment values; they name the run by its directory, so they follow the rename. Only the renamed run's own
    records are passed here, and another run's strings are never rewritten by it.
    """
    pattern = re.compile(rf'runs/{re.escape(old)}(?![A-Za-z0-9_.-])')
    replacement = f'runs/{new}'
    changed = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                rewritten, count = pattern.subn(replacement, value)
                if count:
                    node[key] = rewritten
                    changed += count
            elif isinstance(value, (dict, list)):
                changed += _rewrite_own_strings(value, old, new)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, str):
                rewritten, count = pattern.subn(replacement, value)
                if count:
                    node[index] = rewritten
                    changed += count
            elif isinstance(value, (dict, list)):
                changed += _rewrite_own_strings(value, old, new)
    return changed


def _text_rewritten(text, *, kind, manifest, old, new, own=False):
    """The rewritten bytes of one record, or the same text when it holds nothing to change."""
    if kind == 'text':
        return text.replace(old, new)
    document = json.loads(text)
    changed = _rewrite_references(document, old, new)
    if own:
        changed += _rewrite_own_strings(document, old, new)
    if manifest and document.get('id') == old:
        document['id'] = new
        changed += 1
    if not changed:
        return text
    return json.dumps(document, indent=2)


def _atomic_text(path, text):
    """Replace a file with exactly these bytes, through a temporary file in its own directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _snapshot(owner, relative, kind, manifest, text):
    return {'owner': owner, 'path': Path(relative).as_posix(), 'kind': kind, 'manifest': manifest, 'text': text}


def _collect_files(workspace, old, new):
    """Every record this rename would change, with its original text."""
    workspace = Path(workspace)
    found = []

    def add(owner, base, relative, kind, manifest=False):
        path = Path(base) / relative
        if path.is_symlink() or not path.is_file():
            return
        try:
            text = path.read_text()
        except OSError:
            return
        if old not in text:
            return
        if _text_rewritten(text, kind=kind, manifest=manifest, old=old, new=new, own=owner == old) == text:
            return
        found.append(_snapshot(owner, relative, kind, manifest, text))

    runs = workspace / RUNS
    if runs.is_dir():
        for run_dir in sorted(runs.iterdir()):
            if run_dir.is_symlink() or not run_dir.is_dir():
                continue
            owner = run_dir.name
            add(owner, run_dir, MANIFEST, 'reference', True)
            add(owner, run_dir, PROVENANCE, 'reference')
            add(owner, run_dir, INPUTS, 'reference')
            add(owner, run_dir, REFERENCE, 'text')
            analyses = run_dir / 'analyses'
            if analyses.is_dir() and not analyses.is_symlink():
                for path in sorted(analyses.rglob('*')):
                    if path.name not in ANALYSIS_FILES or path.is_symlink() or not path.is_file():
                        continue
                    relative = path.relative_to(run_dir)
                    if 'output' in relative.parts:
                        continue
                    add(owner, run_dir, relative, 'text')
    for name in PARAMETERIZATION_DIRECTORIES:
        directory = workspace / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob('*.json')):
            if path.is_symlink() or not path.is_file():
                continue
            add(None, workspace, path.relative_to(workspace), 'reference')
    return found


def _target_path(workspace, snapshot, current):
    """Where one ledger file lives now: the owning run's current name, or its own workspace path."""
    if snapshot['owner'] is None:
        return Path(workspace) / snapshot['path']
    owner = current.get(snapshot['owner'], snapshot['owner'])
    return Path(workspace) / RUNS / owner / snapshot['path']


def _load_ledger(workspace):
    path = _ledger_path(workspace)
    if not path.is_file():
        return {'tool': TOOL, 'version': VERSION, 'workspace': str(Path(workspace)),
                'created_at': files.now_iso(), 'runs': [], 'rows': []}
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or document.get('tool') != TOOL:
        raise ValueError(f'{path} is not a {TOOL} ledger')
    document.setdefault('runs', [])
    document.setdefault('rows', [])
    return document


def _save_ledger(workspace, document):
    files.atomic_json(_ledger_path(workspace), document)


def plan(root=None):
    """The renames this migration would make, in created order, and why it will not run.

    Reads only: the store is opened read-only and no path is created. A run already carrying its slug (or the suffix
    run_names.unique gave it) is not a rename; a missing or symbolic-link run directory and an existing target are
    refused before anything is written.
    """
    workspace = _workspace(root)
    rows = _read_rows(_database(workspace), immutable=True)
    ids = [row['id'] for row in rows]
    retired = {name.casefold() for name in _read_retired(_database(workspace), immutable=True)}
    assigned = {}
    entries = []
    for row in rows:
        job, old = row['data'], row['id']
        base = run_names.slug(job.get('label'))
        try:
            run_names.validate(old, what='Run name')
        except ValueError as exc:
            entries.append({'old': old, 'new': None, 'status': 'refused', 'why': str(exc)})
            continue
        if _named(old, base):
            continue
        others = {other.casefold() for other in ids if other != old}
        others |= {name.casefold() for name in assigned.values()}
        others |= retired
        try:
            new = run_names.unique(base, lambda candidate: candidate.casefold() in others)
            run_names.validate(new)
        except ValueError as exc:
            entries.append({'old': old, 'new': None, 'status': 'refused', 'why': str(exc)})
            continue
        source, target = workspace / RUNS / old, workspace / RUNS / new
        entry = {'old': old, 'new': new, 'status': 'rename', 'analyses': len(job.get('analyses') or []),
                 'run_type': job.get('run_type')}
        if source.is_symlink():
            entry.update(status='refused', why='the run directory is a symbolic link')
        elif not source.is_dir():
            entry.update(status='refused', why='the run directory is missing')
        elif target.exists() or target.is_symlink():
            entry.update(status='refused', why=f'runs/{new} already exists')
        else:
            assigned[old] = new
        entries.append(entry)
    return {'workspace': str(workspace), 'busy': _busy(rows), 'runs': entries}


def _rewrite_rows(workspace, old, new):
    """Rename the row and rewrite every row's cross-references, each changed row bumping its revision.

    The renamed row also has its own path strings (console log, command) rewritten; another row's history is left
    alone and only the cross-reference keys are updated.
    """
    store = Store(_database(workspace))

    def own(job):
        _rewrite_references(job, old, new)
        _rewrite_own_strings(job, old, new)

    store.rename(old, new, own)
    with store.connection() as database:
        for jid, text in database.execute('SELECT id, data FROM jobs ORDER BY rowid').fetchall():
            if jid == new:
                continue
            job = json.loads(text)
            if _rewrite_references(job, old, new):
                database.execute('UPDATE jobs SET data=?, revision=revision+1 WHERE id=?', (json.dumps(job), jid))


def _apply_one(workspace, entry, ledger):
    """Rename one run: keep the originals in the ledger, move the directory, then rewrite rows and files."""
    workspace = Path(workspace)
    old, new = entry['old'], entry['new']
    source, target = workspace / RUNS / old, workspace / RUNS / new
    record = next((item for item in ledger['runs'] if item['old'] == old), None)
    if record is None:
        record = {'old': old, 'new': new, 'files': _collect_files(workspace, old, new)}
        ledger['runs'].append(record)
    elif record.get('new') != new:
        raise RuntimeError(f'the ledger names {old} as {record.get("new")!r}, not {new!r}')
    if target.exists() or target.is_symlink():
        raise RuntimeError(f'refusing to rename {old}: runs/{new} already exists')
    moving = source.is_dir() and not source.is_symlink()
    if moving:
        inode = source.stat().st_ino
        _save_ledger(workspace, ledger)
        os.replace(source, target)
        if not target.is_dir() or target.is_symlink() or target.stat().st_ino != inode or source.exists():
            raise RuntimeError(f'renaming {old} did not leave the same directory at runs/{new}')
    elif not (target.is_dir() and not target.is_symlink()):
        raise RuntimeError(f'refusing to rename {old}: no directory at runs/{old} or runs/{new}')
    else:
        _save_ledger(workspace, ledger)
    _rewrite_rows(workspace, old, new)
    current = {item['old']: item['new'] for item in ledger['runs']}
    for snapshot in record['files']:
        text = _text_rewritten(snapshot['text'], kind=snapshot['kind'], manifest=snapshot['manifest'],
                               old=old, new=new, own=snapshot['owner'] == old)
        if text != snapshot['text']:
            _atomic_text(_target_path(workspace, snapshot, current), text)
    Store(_database(workspace)).retire(old)
    _save_ledger(workspace, ledger)


def _analyses_paths(workspace):
    """Every analysis record path under the workspace, run by run, skipping an output tree."""
    runs = Path(workspace) / RUNS
    if not runs.is_dir():
        return
    for run_dir in sorted(runs.iterdir()):
        if run_dir.is_symlink() or not run_dir.is_dir():
            continue
        analyses = run_dir / 'analyses'
        if not analyses.is_dir() or analyses.is_symlink():
            continue
        for path in sorted(analyses.rglob('*')):
            if path.name not in ANALYSIS_FILES or path.is_symlink() or not path.is_file():
                continue
            if 'output' in path.relative_to(run_dir).parts:
                continue
            yield path


def leftovers(workspace, names):
    """The records still naming one of these ids as a run cross-reference, after apply.

    The rewrite surface is the one this migration owns: job rows, run manifests, inputs records, provenance, the
    analysis records and reference publications, and parameterization records and jobs. A stage command, a log path or
    a parameterization work directory is execution history, not a run reference, and is not reported here.
    """
    workspace = Path(workspace)
    messages = []
    for row in _read_rows(_database(workspace)):
        for old in names:
            for where in _reference_leaks(row['data'], old):
                messages.append(f'{row["id"]}: {where} still names {old}')
    runs = workspace / RUNS
    if runs.is_dir():
        for run_dir in sorted(runs.iterdir()):
            if run_dir.is_symlink() or not run_dir.is_dir():
                continue
            owner = run_dir.name
            for relative, manifest in ((MANIFEST, True), (PROVENANCE, False), (INPUTS, False)):
                path = run_dir / relative
                if path.is_symlink() or not path.is_file():
                    continue
                document = json.loads(path.read_text())
                if manifest and document.get('id') in names:
                    messages.append(f'runs/{owner}/{relative}: id is still {document["id"]}')
                for old in names:
                    for where in _reference_leaks(document, old):
                        messages.append(f'runs/{owner}/{relative}: {where} still names {old}')
            reference = run_dir / REFERENCE
            if reference.is_file() and not reference.is_symlink():
                text = reference.read_text()
                for old in names:
                    if old in text:
                        messages.append(f'runs/{owner}/{REFERENCE} still names {old}')
    for path in _analyses_paths(workspace):
        text = path.read_text()
        for old in names:
            if old in text:
                messages.append(f'{path.relative_to(workspace).as_posix()} still names {old}')
    for name in PARAMETERIZATION_DIRECTORIES:
        directory = workspace / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob('*.json')):
            if path.is_symlink() or not path.is_file():
                continue
            document = json.loads(path.read_text())
            for old in names:
                for where in _reference_leaks(document, old):
                    messages.append(f'{path.relative_to(workspace).as_posix()}: {where} still names {old}')
    return messages


def verify(workspace, entries, olds):
    """Open each renamed run through the project's readers; a failure is reported, not raised."""
    workspace = Path(workspace)
    failures = []
    store = Store(_database(workspace))
    run_root = workspace / RUNS
    with paths.use(paths.Paths(workspace=workspace)):
        for entry in entries:
            new = entry['new']
            job = store.get(new)
            if job is None or job.get('id') != new:
                failures.append(f'{new}: the job row does not carry the new id')
                continue
            if len(job.get('analyses') or []) != entry.get('analyses', len(job.get('analyses') or [])):
                failures.append(f'{new}: the analyses count changed')
            run_dir = run_root / new
            try:
                manifest = json.loads((run_dir / MANIFEST).read_text())
                if not isinstance(manifest, dict):
                    raise ValueError('the manifest is not an object')
                run_inputs.verify_manifest(run_dir, manifest)
            except (OSError, ValueError, KeyError) as exc:
                failures.append(f'{new}: inputs do not verify: {exc}')
            if job.get('run_type') == 'aa_only':
                try:
                    references.resolve(run_root, new)
                except (OSError, ValueError, KeyError) as exc:
                    failures.append(f'{new}: the AA reference does not resolve: {exc}')
    failures.extend(leftovers(workspace, olds))
    return failures


def apply(result, root=None):
    """Rename every planned run, keeping each original in the ledger first; stop on the first failure."""
    workspace = Path(result.get('workspace') or _workspace(root))
    if result.get('busy'):
        raise RuntimeError('a run or analysis is working: ' + ', '.join(result['busy']))
    refused = [entry for entry in result['runs'] if entry['status'] == 'refused']
    if refused:
        raise RuntimeError('refusing to rename while a target is in the way: ' +
                           '; '.join(f'{entry["old"]} -> {entry["new"]}: {entry["why"]}' for entry in refused))
    renames = [entry for entry in result['runs'] if entry['status'] == 'rename']
    if not renames:
        return {'applied': [], 'verification': []}
    working = _busy(_read_rows(_database(workspace)))
    if working:
        raise RuntimeError('a run or analysis is working: ' + ', '.join(working))
    ledger = _load_ledger(workspace)
    if not ledger['rows']:
        ledger['rows'] = [{'id': row['id'], 'text': row['text'], 'revision': row['revision']}
                          for row in _read_rows(_database(workspace))]
        _save_ledger(workspace, ledger)
    for entry in renames:
        _apply_one(workspace, entry, ledger)
    olds = [entry['old'] for entry in ledger['runs']]
    return {'applied': renames, 'verification': verify(workspace, renames, olds)}


def rollback(root=None):
    """Restore the directories, row texts/revisions, file texts and retired entries the ledger recorded."""
    workspace = _workspace(root)
    working = _busy(_read_rows(_database(workspace)))
    if working:
        raise RuntimeError('a run or analysis is working: ' + ', '.join(working))
    ledger = _load_ledger(workspace)
    if not ledger['runs']:
        raise RuntimeError(f'no renames recorded at {_ledger_path(workspace)}')
    restored = {'runs': 0, 'files': 0, 'rows': 0, 'retired': 0}
    for entry in reversed(ledger['runs']):
        source, target = workspace / RUNS / entry['old'], workspace / RUNS / entry['new']
        if target.exists() or target.is_symlink():
            if source.exists() or source.is_symlink():
                raise RuntimeError(f'both runs/{entry["old"]} and runs/{entry["new"]} exist; refusing to guess')
            os.replace(target, source)
            restored['runs'] += 1
        elif not (source.is_dir() and not source.is_symlink()):
            raise RuntimeError(f'neither runs/{entry["old"]} nor runs/{entry["new"]} exists')
    for entry in reversed(ledger['runs']):
        for snapshot in entry['files']:
            _atomic_text(_target_path(workspace, snapshot, {}), snapshot['text'])
            restored['files'] += 1
    store = Store(_database(workspace))
    with store.connection() as database:
        for snapshot in ledger['rows']:
            row = database.execute('SELECT id FROM jobs WHERE id=?', (snapshot['id'],)).fetchone()
            if row is None:
                renamed = next((entry for entry in ledger['runs'] if entry['old'] == snapshot['id']), None)
                if renamed is not None:
                    row = database.execute('SELECT id FROM jobs WHERE id=?', (renamed['new'],)).fetchone()
            if row is None:
                raise RuntimeError(f'the job row {snapshot["id"]} is gone; refusing to write a half restore')
            database.execute('UPDATE jobs SET id=?, data=?, revision=? WHERE id=?',
                             (snapshot['id'], snapshot['text'], snapshot['revision'], row[0]))
            restored['rows'] += 1
        for entry in ledger['runs']:
            database.execute('DELETE FROM retired_runs WHERE name=?', (entry['old'],))
            restored['retired'] += 1
    ledger['rolled_back_at'] = files.now_iso()
    _save_ledger(workspace, ledger)
    return restored


def _line(entry, applied=False):
    verb = 'renamed' if applied else 'rename'
    return f'{verb} {entry["old"]} -> {entry["new"]}'


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Rename legacy hex-id runs to their labels slug, with a reversible ledger (dry run by default)')
    parser.add_argument('--workspace', type=Path, default=None,
                        help='a workspace (the directory holding runs/ and jobs.sqlite3; default: the live one)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='rename the runs and rewrite their records')
    mode.add_argument('--rollback', action='store_true',
                      help=f'restore the names and texts recorded in {LEDGER.as_posix()}')
    args = parser.parse_args(argv)
    workspace = args.workspace if args.workspace is not None else Path(paths.current().workspace)
    if args.rollback:
        try:
            restored = rollback(workspace)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f'refused: {exc}')
            return 1
        print(' '.join(f'{key}={value}' for key, value in restored.items()))
        return 0
    try:
        result = plan(workspace)
    except (OSError, ValueError) as exc:
        print(f'refused: {exc}')
        return 1
    if result['busy']:
        print('refused: a run or analysis is working: ' + ', '.join(result['busy']))
        return 1
    refused = [entry for entry in result['runs'] if entry['status'] == 'refused']
    if refused:
        for entry in refused:
            print(f'refused {entry["old"]} -> {entry["new"]}: {entry["why"]}')
        return 1
    if args.apply:
        try:
            outcome = apply(result, workspace)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            print(f'refused: {exc}')
            return 1
        if not outcome['applied']:
            print('nothing to do')
            return 0
        for entry in outcome['applied']:
            print(_line(entry, applied=True))
        for failure in outcome['verification']:
            print(f'verify {failure}')
        return 1 if outcome['verification'] else 0
    for entry in result['runs']:
        if entry['status'] == 'rename':
            print(_line(entry))
    if not any(entry['status'] == 'rename' for entry in result['runs']):
        print('nothing to do')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
