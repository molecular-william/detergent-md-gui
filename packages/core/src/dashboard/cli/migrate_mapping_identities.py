"""Rewrite a workspace's stored mapping identities to the named molecule version.

Identity version 3 names the molecule version directory instead of hashing the molecule's files. A draft written
before that change carries a digest snapshot and a digest identity, and every parameterization record, job row and
prepared run that stamped it still does. This migration rewrites those documents once:

* each saved draft under `mapping_drafts/`: its `molecule_snapshot` becomes `{molecule_id, version}`, resolved from
  the molecule folder (never guessed); its beads, rings, connections and name are left alone, and nothing else in the
  file is recomputed;
* each parameterization record under `parameterizations/records/`: `mapping_hash` and `mapping_content_hash`, and the
  same two stamps on every revision, become the identity of the draft the record's name addresses. A record whose name
  no saved draft answers, or whose stamps are neither the old digest identity nor the new one, is refused: there is no
  model to compute an identity from, or the record belongs to another one;
* each job row's and each prepared manifest's `parameterization` block: the same two stamps;
* each mapping document embedded in a job row (`mapping_snapshot`) or a prepared manifest: the nested
  `molecule_snapshot` it carries, renamed to `{molecule_id, version}` and opened through the draft reader a Retry or
  Clone calls on it. A document whose rewritten mapping cannot load refuses the whole run: nothing of it is written.

Dry run by default; `--apply` writes. Every original document and job row is kept in
`<workspace>/.named-migration/identities.json`, and `--rollback` restores them. A second apply writes nothing: a
draft that already names its version and a record whose stamps already equal its identity are reported unchanged.

The named identity only exists once the molecule folders are versioned (`molecules/<id>/v1/` with
`metadata.version`); a draft whose molecule still has the unversioned shape is blocked rather than given a version
guess.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from dashboard import files, paths, run_names
from dashboard.models.bonded import parameterization
from dashboard.models.mappings import identity
from dashboard.models.molecules import aa as aa_molecules
from dashboard.models.molecules import draft as draft_model
from dashboard.store import Store

BACKUP_DIRECTORY = '.named-migration'
RECORDS_NAME = 'identities.json'
MANIFEST = 'manifest.json'
#: The keys a job row or a prepared manifest keeps an embedded mapping document under. A job row names a saved draft
#: with `mapping_candidate`, so the shape -- a document carrying `molecule_snapshot` -- is what selects one.
SNAPSHOTS = ('mapping_snapshot', 'mapping_candidate', 'mapping')

#: A status that means a run or an analysis is working. The database is the record of both.
BUSY = ('queued', 'running', 'cancelling')


class Refusal(ValueError):
    """One record cannot be rewritten without losing what it says; it is reported and left alone."""


@contextmanager
def _selected(root=None, project_root=None):
    """Read and write one workspace's store, named or the live one."""
    base = Path(project_root) if project_root is not None else paths.current().project_root
    workspace = Path(root) if root is not None else Path(paths.current().workspace)
    with paths.use(paths.Paths(project_root=base, workspace=workspace)):
        yield Path(workspace)


def _read_json(path):
    return json.loads(Path(path).read_text())


def _atomic_text(path, text):
    """Replace a file with exactly these bytes, through a temporary file in its own directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


# ---------------------------------------------------------------------------
# The backup ledger


def _records_path(workspace):
    return Path(workspace) / BACKUP_DIRECTORY / RECORDS_NAME


def _load_records(workspace):
    path = _records_path(workspace)
    if not path.is_file():
        return {'tool': 'dashboard.cli.migrate_mapping_identities', 'version': 1,
                'workspace': str(workspace), 'drafts': {}, 'records': {}, 'jobs': {}, 'manifests': {}}
    return _read_json(path)


def _save_records(workspace, records):
    files.atomic_json(_records_path(workspace), records)


def _job_rows(workspace):
    """Every job row's stored text, data and revision, or none when the workspace has no database."""
    database = Path(workspace) / 'jobs.sqlite3'
    if not database.is_file():
        return []
    store = Store(database)
    with store.connection() as db:
        return [{'text': row[0], 'data': json.loads(row[0]), 'revision': row[1]}
                for row in db.execute('SELECT data, revision FROM jobs ORDER BY rowid')]


def _busy(workspace):
    busy = []
    for row in _job_rows(workspace):
        job = row['data']
        if job.get('status') in BUSY:
            busy.append(str(job.get('id')))
        for task in job.get('analyses') or []:
            if isinstance(task, dict) and task.get('status') in BUSY:
                busy.append(f'{job.get("id")}/{task.get("id")}')
    return [name for name in busy if name]


# ---------------------------------------------------------------------------
# Planning


def _named_snapshot(document, project_root):
    """The `{molecule_id, version}` a draft's molecule folder states now, or a Refusal."""
    molecule_id = document.get('molecule_id')
    if not isinstance(molecule_id, str) or not molecule_id:
        raise Refusal('the draft names no molecule_id')
    try:
        _folder, version = aa_molecules.resolve(Path(project_root) / 'molecules', molecule_id)
    except (OSError, ValueError) as exc:
        raise Refusal(f'molecules/{molecule_id} cannot be resolved: {exc}') from exc
    if version is None:
        raise Refusal(f'molecules/{molecule_id} is still the unversioned shape; migrate the molecule folders first')
    return {'molecule_id': molecule_id, 'version': version}


def _already_named(snapshot, molecule_id):
    return (isinstance(snapshot, dict) and isinstance(molecule_id, str)
            and snapshot == {'molecule_id': molecule_id, 'version': snapshot.get('version')}
            and isinstance(snapshot.get('version'), str))


def _plan_drafts(workspace, project_root):
    entries = []
    root = Path(workspace) / 'mapping_drafts'
    for path in sorted(root.glob('mapping_candidate*.json')) if root.is_dir() else []:
        if path.is_symlink() or not path.is_file():
            continue
        base = {'file': path.name}
        try:
            original = _read_json(path)
        except (OSError, ValueError) as exc:
            entries.append({**base, 'status': 'blocked', 'reason': f'the draft does not parse: {exc}'})
            continue
        if not isinstance(original, dict):
            entries.append({**base, 'status': 'blocked', 'reason': 'the draft is not an object'})
            continue
        molecule_id = original.get('molecule_id')
        if _already_named(original.get('molecule_snapshot'), molecule_id):
            entries.append({**base, 'status': 'unchanged', 'snapshot': original['molecule_snapshot'],
                            'document': original, 'original': original, 'text': path.read_text()})
            continue
        try:
            snapshot = _named_snapshot(original, project_root)
        except Refusal as exc:
            entries.append({**base, 'status': 'blocked', 'reason': str(exc)})
            continue
        document = {**original, 'molecule_snapshot': snapshot}
        entries.append({**base, 'status': 'write', 'snapshot': snapshot, 'document': document,
                        'original': original, 'text': path.read_text()})
    return entries


def _drafts_by_slug(entries):
    """Each saved draft by the name its parameterization record is addressed with; a shared name stays a list."""
    grouped = {}
    for entry in entries:
        if entry['status'] not in ('write', 'unchanged'):
            continue
        slug = run_names.slug(entry['document'].get('name') or entry['file'])
        grouped.setdefault(slug, []).append(entry)
    return grouped


def _drafts_by_file(entries):
    return {entry['file']: entry for entry in entries if entry['status'] in ('write', 'unchanged')}


def _addressed_draft(block, drafts_by_slug, drafts_by_file):
    """The saved draft a stamp-carrying block names, by record name first and mapping file second."""
    slug = block.get('mapping')
    found = drafts_by_slug.get(slug) if isinstance(slug, str) else None
    if found:
        return found[0] if len(found) == 1 else None
    name = block.get('mapping_candidate')
    if isinstance(name, str):
        return drafts_by_file.get(name)
    return None


def _identities(document):
    return {'mapping_hash': identity.candidate_identity(document),
            'mapping_content_hash': identity.content_identity(document)}


def _previous_identities(entry):
    """The digest identity the draft was stored under before its molecule version was named."""
    return {'mapping_hash': identity.legacy_candidate_identity(entry['original']),
            'mapping_content_hash': identity.legacy_content_identity(entry['original'])}


def _has_identities(value, wanted):
    """Whether a record and every revision it lists already carry these stamps."""
    if not isinstance(value, dict):
        return False
    if any(value.get(key) != stamp for key, stamp in wanted.items()):
        return False
    for item in [value.get('current'), *(value.get('revisions') or [])]:
        if isinstance(item, dict) and any(item.get(key) != stamp for key, stamp in wanted.items()):
            return False
    return True


def _matches_old_or_new(value, previous, wanted):
    """Whether every stamp a document carries is the old identity or the new one.

    A stamp that is neither is another model's: the block or record belongs to content this draft does not name, and
    rewriting it would make a run or a fit read as if it had always been this model's.
    """
    if not isinstance(value, dict):
        return False
    for key in ('mapping_hash', 'mapping_content_hash'):
        if key in value and value[key] not in (previous[key], wanted[key]):
            return False
    return True


def _rewritable(value, previous, wanted):
    """Whether a record and every revision it lists stamp the old identity or the new one."""
    if not _matches_old_or_new(value, previous, wanted):
        return False
    for item in [value.get('current'), *(value.get('revisions') or [])]:
        if isinstance(item, dict) and not _matches_old_or_new(item, previous, wanted):
            return False
    return True


def _restamp(value, wanted):
    """A copy of a record with its own and every revision's identity stamps replaced."""
    document = json.loads(json.dumps(value))
    document.update(wanted)
    if isinstance(document.get('current'), dict):
        document['current'].update(wanted)
    for item in document.get('revisions') or []:
        if isinstance(item, dict):
            item.update(wanted)
    return document


def _plan_records(workspace, drafts_by_slug):
    entries = []
    root = Path(workspace) / 'parameterizations' / 'records'
    for path in sorted(root.glob('*.json')) if root.is_dir() else []:
        if path.is_symlink() or not path.is_file():
            continue
        base = {'record': path.stem}
        try:
            original = _read_json(path)
        except (OSError, ValueError) as exc:
            entries.append({**base, 'status': 'blocked', 'reason': f'the record does not parse: {exc}'})
            continue
        if not isinstance(original, dict):
            entries.append({**base, 'status': 'blocked', 'reason': 'the record is not an object'})
            continue
        found = drafts_by_slug.get(path.stem) or []
        if not found:
            entries.append({**base, 'status': 'blocked',
                            'reason': "no saved mapping draft answers this record's name"})
            continue
        if len(found) > 1:
            entries.append({**base, 'status': 'blocked', 'reason': 'more than one saved draft carries this name'})
            continue
        draft = found[0]
        if draft['status'] == 'blocked':
            entries.append({**base, 'status': 'blocked',
                            'reason': f"its draft cannot be migrated: {draft['reason']}"})
            continue
        wanted = _identities(draft['document'])
        if _has_identities(original, wanted):
            entries.append({**base, 'status': 'unchanged', 'identities': wanted})
            continue
        previous = _previous_identities(draft)
        if not _rewritable(original, previous, wanted):
            entries.append({**base, 'status': 'blocked',
                            'reason': 'the record stamps an identity this mapping no longer computes; it belongs '
                                      'to another model'})
            continue
        entries.append({**base, 'status': 'write', 'identities': wanted, 'previous': previous,
                        'document': _restamp(original, wanted), 'text': path.read_text()})
    return entries


def _plan_snapshots(document, project_root):
    """The embedded mapping documents the migration renames, the refusals, and whether it carries any at all.

    A mapping document stamped beside a run keeps the snapshot its draft was written with: the digest shape when it
    predates version directories. Only that nested snapshot is replaced; its beads, rings, connections, name and every
    other field stay untouched, so the run still records the model it simulated.
    """
    updates, refusals, seen = {}, [], False
    for key in SNAPSHOTS:
        mapping = document.get(key)
        if not isinstance(mapping, dict) or not isinstance(mapping.get('molecule_snapshot'), dict):
            continue
        seen = True
        if 'version' in mapping['molecule_snapshot']:
            continue
        try:
            wanted = _named_snapshot(mapping, project_root)
            rewritten = json.loads(json.dumps(mapping))
            rewritten['molecule_snapshot'] = wanted
            # Refuse before anything is written: the reader a Retry or Clone calls on this document is the proof the
            # rewritten run could still be built, and a document that cannot open leaves its run exactly as it was.
            draft_model.load(rewritten, molecule_root=Path(project_root) / 'molecules')
        except Refusal as exc:
            refusals.append(f'{key}: {exc}')
            continue
        except (OSError, ValueError, KeyError) as exc:
            refusals.append(f'{key}: the rewritten mapping cannot load: {exc}')
            continue
        updates[key] = wanted
    return updates, refusals, seen


def _plan_document(base, document, drafts_by_slug, drafts_by_file, project_root):
    """One job row or manifest: its `parameterization` stamps and every embedded mapping snapshot."""
    block = document.get('parameterization')
    stamped = _plan_block(base, block, document, drafts_by_slug, drafts_by_file) if isinstance(block, dict) else None
    updates, refusals, seen = _plan_snapshots(document, project_root)
    if stamped is None and not seen:
        return None
    reasons = ([stamped['reason']] if stamped and stamped['status'] == 'blocked' else []) + refusals
    if reasons:
        return {**base, 'status': 'blocked', 'reason': '; '.join(reasons)}
    writing = bool(updates) or bool(stamped and stamped['status'] == 'write')
    if not writing:
        entry = {**base, 'status': 'unchanged'}
        if stamped is not None and 'identities' in stamped:
            entry['identities'] = stamped['identities']
        return entry
    restamped = stamped['document'] if stamped and stamped['status'] == 'write' else None
    rewritten = restamped if restamped is not None else json.loads(json.dumps(document))
    for key, snapshot in updates.items():
        rewritten[key] = {**rewritten[key], 'molecule_snapshot': snapshot}
    entry = {**base, 'status': 'write', 'document': rewritten}
    if updates:
        entry['snapshots'] = updates
    if stamped is not None and 'identities' in stamped:
        entry['identities'] = stamped['identities']
        if stamped['status'] == 'write':
            entry['previous'] = stamped['previous']
    return entry


def _plan_stamped(workspace, drafts_by_slug, drafts_by_file, project_root):
    """Job rows and prepared manifests whose stamps or embedded mapping document the migration rewrites."""
    jobs, manifests = [], []
    for row in _job_rows(workspace):
        job = row['data']
        entry = _plan_document({'job': str(job.get('id'))}, job, drafts_by_slug, drafts_by_file, project_root)
        if entry is not None:
            jobs.append({**entry, 'row': row})
    runs = Path(workspace) / 'runs'
    for path in sorted(runs.glob('*/' + MANIFEST)) if runs.is_dir() else []:
        if path.is_symlink() or not path.is_file():
            continue
        run = path.parent.name
        try:
            original = _read_json(path)
        except (OSError, ValueError) as exc:
            manifests.append({'run': run, 'status': 'blocked', 'reason': f'the manifest does not parse: {exc}'})
            continue
        if not isinstance(original, dict):
            manifests.append({'run': run, 'status': 'blocked', 'reason': 'the manifest is not an object'})
            continue
        entry = _plan_document({'run': run}, original, drafts_by_slug, drafts_by_file, project_root)
        if entry is not None:
            if entry['status'] == 'write':
                entry['text'] = path.read_text()
            manifests.append(entry)
    return jobs, manifests


def _plan_block(base, block, document, drafts_by_slug, drafts_by_file):
    if 'mapping_hash' not in block and 'mapping_content_hash' not in block:
        return {**base, 'status': 'unchanged'}
    draft = _addressed_draft(block, drafts_by_slug, drafts_by_file)
    if draft is None:
        return {**base, 'status': 'blocked',
                'reason': 'no saved mapping draft answers the model this block names'}
    if draft['status'] == 'blocked':
        return {**base, 'status': 'blocked',
                'reason': f"its draft cannot be migrated: {draft['reason']}"}
    wanted = _identities(draft['document'])
    if _has_identities(block, wanted):
        return {**base, 'status': 'unchanged', 'identities': wanted}
    previous = _previous_identities(draft)
    if not _rewritable(block, previous, wanted):
        return {**base, 'status': 'blocked',
                'reason': 'the block stamps an identity this mapping no longer computes; it belongs to another model'}
    restamped = json.loads(json.dumps(document))
    restamped['parameterization'] = _restamp(block, wanted)
    return {**base, 'status': 'write', 'identities': wanted, 'previous': previous, 'document': restamped}


def plan(root=None, *, project_root=None):
    """What the migration would change, as drafts, records, job rows and manifests."""
    with _selected(root, project_root) as workspace:
        project = Path(project_root) if project_root is not None else paths.current().project_root
        drafts = _plan_drafts(workspace, project)
        by_slug = _drafts_by_slug(drafts)
        records = _plan_records(workspace, by_slug)
        jobs, manifests = _plan_stamped(workspace, by_slug, _drafts_by_file(drafts), project)
        return {'workspace': str(workspace), 'project_root': str(project), 'busy': _busy(workspace),
                'drafts': drafts, 'records': records, 'jobs': jobs, 'manifests': manifests}


# ---------------------------------------------------------------------------
# Applying


def _backup(records, entries):
    for entry in entries['drafts']:
        if entry['status'] == 'write':
            records['drafts'].setdefault(entry['file'], {'text': entry['text']})
    for entry in entries['records']:
        if entry['status'] == 'write':
            records['records'].setdefault(entry['record'], {'text': entry['text']})
    for entry in entries['jobs']:
        if entry['status'] == 'write':
            row = entry['row']
            records['jobs'].setdefault(entry['job'], {'text': row['text'], 'revision': row['revision']})
    for entry in entries['manifests']:
        if entry['status'] == 'write':
            records['manifests'].setdefault(entry['run'], {'path': MANIFEST, 'text': entry['text']})


def _write_documents(workspace, entries):
    written = {'drafts': [], 'records': [], 'jobs': [], 'manifests': []}
    # Records, job rows and manifests are written before the drafts, so a crash between the two leaves the draft
    # carrying the identity its rewritten records already name: a second apply finishes rather than refusing.
    for entry in entries['records']:
        if entry['status'] == 'write':
            files.atomic_json(Path(workspace) / 'parameterizations' / 'records' / f"{entry['record']}.json",
                              entry['document'])
            written['records'].append(entry['record'])
    database = Path(workspace) / 'jobs.sqlite3'
    if database.is_file():
        store = Store(database)
        with store.connection() as db:
            for entry in entries['jobs']:
                if entry['status'] != 'write':
                    continue
                db.execute('UPDATE jobs SET data=?, revision=revision+1 WHERE id=?',
                           (json.dumps(entry['document']), entry['job']))
                written['jobs'].append(entry['job'])
    for entry in entries['manifests']:
        if entry['status'] == 'write':
            files.atomic_json(Path(workspace) / 'runs' / entry['run'] / MANIFEST, entry['document'])
            written['manifests'].append(entry['run'])
    for entry in entries['drafts']:
        if entry['status'] == 'write':
            files.atomic_json(Path(workspace) / 'mapping_drafts' / entry['file'], entry['document'])
            written['drafts'].append(entry['file'])
    return written


def apply(entries, root=None, *, project_root=None):
    """Rewrite every planned document, keeping each original in the ledger first."""
    if entries.get('busy'):
        raise RuntimeError('a run or analysis is working: ' + ', '.join(entries['busy']))
    with _selected(root, project_root) as workspace:
        records = _load_records(workspace)
        before = json.dumps(records, sort_keys=True)
        _backup(records, entries)
        if json.dumps(records, sort_keys=True) != before:
            _save_records(workspace, records)
        written = _write_documents(workspace, entries)
        return {**entries, 'written': written, 'verification': _verify(workspace, entries)}


# ---------------------------------------------------------------------------
# Verification


def _verify(workspace, entries):
    """Open every rewritten draft and record through the project's readers; a refusal is reported, not raised."""
    refusals = []
    molecule_root = paths.current().project_root / 'molecules'
    drafts = {}
    for entry in entries['drafts']:
        if entry['status'] not in ('write', 'unchanged'):
            continue
        try:
            drafts[entry['file']] = _read_json(Path(workspace) / 'mapping_drafts' / entry['file'])
        except (OSError, ValueError) as exc:
            refusals.append({'check': 'draft', 'file': entry['file'], 'error': str(exc)})
    for name, document in drafts.items():
        try:
            draft_model.load(document, molecule_root=molecule_root)
        except (OSError, ValueError, KeyError) as exc:
            refusals.append({'check': 'draft_model.load', 'file': name, 'error': str(exc)})
    for entry in entries['records']:
        if entry['status'] not in ('write', 'unchanged'):
            continue
        try:
            parameterization.one(entry['record'])
        except (OSError, ValueError, KeyError) as exc:
            refusals.append({'check': 'parameterization.one', 'record': entry['record'], 'error': str(exc)})
            continue
        draft = next((document for name, document in drafts.items()
                      if run_names.slug(document.get('name') or name) == entry['record']), None)
        if draft is None:
            continue
        try:
            parameterization.document(draft)
        except (OSError, ValueError, KeyError) as exc:
            refusals.append({'check': 'parameterization.document', 'record': entry['record'], 'error': str(exc)})
    database = Path(workspace) / 'jobs.sqlite3'
    if database.is_file():
        store = Store(database)
        for entry in entries['jobs']:
            if entry['status'] != 'write':
                continue
            try:
                row = store.get(entry['job'])
                if row is None:
                    raise ValueError('the rewritten job row is gone')
                if 'identities' in entry and not _has_identities(row.get('parameterization'), entry['identities']):
                    raise ValueError('the rewritten job row does not carry the new identity')
                for key in entry.get('snapshots') or {}:
                    draft_model.load(row[key], molecule_root=molecule_root)
            except (OSError, ValueError, KeyError) as exc:
                refusals.append({'check': 'Store.get', 'job': entry['job'], 'error': str(exc)})
    for entry in entries['manifests']:
        if entry['status'] != 'write':
            continue
        try:
            manifest = _read_json(Path(workspace) / 'runs' / entry['run'] / MANIFEST)
            if 'identities' in entry and not _has_identities(manifest.get('parameterization'), entry['identities']):
                raise ValueError('the rewritten manifest does not carry the new identity')
            for key in entry.get('snapshots') or {}:
                draft_model.load(manifest[key], molecule_root=molecule_root)
        except (OSError, ValueError, KeyError) as exc:
            refusals.append({'check': 'manifest', 'run': entry['run'], 'error': str(exc)})
    return refusals


# ---------------------------------------------------------------------------
# Rolling back


def rollback(root=None, *, project_root=None):
    """Restore every document and job row the ledger recorded."""
    with _selected(root, project_root) as workspace:
        busy = _busy(workspace)
        if busy:
            raise RuntimeError('a run or analysis is working: ' + ', '.join(busy))
        path = _records_path(workspace)
        if not path.is_file():
            return {'status': 'nothing', 'reason': f'no {RECORDS_NAME} to roll back from'}
        records = _read_json(path)
        restored = {'drafts': [], 'records': [], 'jobs': [], 'manifests': []}
        for name, entry in (records.get('drafts') or {}).items():
            _atomic_text(Path(workspace) / 'mapping_drafts' / name, entry['text'])
            restored['drafts'].append(name)
        for name, entry in (records.get('records') or {}).items():
            _atomic_text(Path(workspace) / 'parameterizations' / 'records' / f'{name}.json', entry['text'])
            restored['records'].append(name)
        database = Path(workspace) / 'jobs.sqlite3'
        if database.is_file():
            store = Store(database)
            with store.connection() as db:
                for name, entry in (records.get('jobs') or {}).items():
                    db.execute('UPDATE jobs SET data=?, revision=? WHERE id=?',
                               (entry['text'], entry['revision'], name))
                    restored['jobs'].append(name)
        for name, entry in (records.get('manifests') or {}).items():
            _atomic_text(Path(workspace) / 'runs' / name / entry.get('path', MANIFEST), entry['text'])
            restored['manifests'].append(name)
        records['rolled_back_at'] = files.now_iso()
        _save_records(workspace, records)
        return {'status': 'rolled-back', 'restored': restored}


# ---------------------------------------------------------------------------
# Command line


def summary(entries):
    counts = {}
    for category in ('drafts', 'records', 'jobs', 'manifests'):
        for entry in entries.get(category) or []:
            key = f'{category}:{entry["status"]}'
            counts[key] = counts.get(key, 0) + 1
    return counts


def _reported(entries):
    """The plan without the full documents apply carries, so a report stays readable."""
    private = ('document', 'original', 'text', 'row')
    reported = {key: value for key, value in entries.items()
                if key not in ('drafts', 'records', 'jobs', 'manifests')}
    for category in ('drafts', 'records', 'jobs', 'manifests'):
        reported[category] = [{key: value for key, value in entry.items() if key not in private}
                              for entry in entries.get(category) or []]
    return reported


def _change(entry):
    """What one planned write changes, so a dry run names it without dumping the whole document."""
    parts = []
    if entry.get('snapshots'):
        parts.append('snapshot -> ' + ', '.join(f'{key}={value["molecule_id"]}/{value["version"]}'
                                                 for key, value in entry['snapshots'].items()))
    if entry.get('identities'):
        parts.append('identity -> ' + entry['identities']['mapping_hash'][:16])
    return '; '.join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Rewrite saved mapping identities to the named molecule version (identity 3)')
    parser.add_argument('--workspace', type=Path, default=None, help='a workspace to migrate (default: the live one)')
    parser.add_argument('--project-root', type=Path, default=None,
                        help='the data root holding molecules/ (default: the checkout)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='rewrite the documents (default: report only)')
    mode.add_argument('--rollback', action='store_true', help='reverse a previous apply from its ledger')
    parser.add_argument('--report', type=Path, default=None, help='write the planned entries here as JSON')
    args = parser.parse_args(argv)

    if args.rollback:
        try:
            result = rollback(args.workspace, project_root=args.project_root)
        except RuntimeError as exc:
            print(f'refused: {exc}')
            return 1
        print(' '.join(f'{key}={len(value)}' for key, value in sorted((result.get('restored') or {}).items())
                       if isinstance(value, list)))
        if result.get('reason'):
            print('  ' + result['reason'])
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, indent=2) + '\n')
            print(f'report: {args.report}')
        return 0

    entries = plan(args.workspace, project_root=args.project_root)
    if args.apply:
        try:
            result = apply(entries, args.workspace, project_root=args.project_root)
        except RuntimeError as exc:
            print(f'refused: {exc}')
            return 1
    else:
        result = entries
        if entries.get('busy'):
            print('refused: a run or analysis is working: ' + ', '.join(entries['busy']))
            return 1
    print(' '.join(f'{key}={value}' for key, value in sorted(summary(result).items())))
    for category in ('drafts', 'records', 'jobs', 'manifests'):
        for entry in result.get(category) or []:
            if entry['status'] == 'write':
                name = entry.get('file') or entry.get('record') or entry.get('job') or entry.get('run')
                print(f'  {category:<10} write     {name:<44}  ({_change(entry)})')
    for category in ('drafts', 'records', 'jobs', 'manifests'):
        for entry in result.get(category) or []:
            if entry['status'] == 'blocked':
                name = entry.get('file') or entry.get('record') or entry.get('job') or entry.get('run')
                print(f'  {category:<10} blocked   {name:<44}  ({entry["reason"]})')
    for refusal in result.get('verification') or []:
        print(f'  refusal    {refusal["check"]}: {refusal["error"]}')
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(_reported(result), indent=2) + '\n')
        print(f'report: {args.report}')
    # A blocked record is reported and left alone, not a command failure; a rewritten document its own reader
    # cannot open afterwards is.
    return 1 if result.get('verification') else 0


if __name__ == '__main__':
    raise SystemExit(main())
