"""Rewrite a workspace's run records to the named contract: inputs, code, molecules and references by name.

The named-identity phases replaced change-detection digests with names a reader can follow: a file by the root and
path it is read from, code by a registry name and version, a molecule by its id and version, and a shared AA
reference by its edition. A run prepared before those phases still carries the old spellings, and every reader keeps
the legacy branch for it. This migration is the one step that rewrites the records themselves, so the legacy
branches can later be deleted.

It is deliberately a repair of the records, not of the science: stage outputs, analysis results and a run's recorded
artifact digests are left exactly as they are. What it changes is:

* a reference record (stages/07_reference/reference.json) that lacks an edition gains edition and the molecule's
  name, after its artifact names are shown to exist;
* the workspace's Martini 3 set gains a versioned copy at martini3/<version>/, beside the flat install, which is
  never rewritten;
* each run's manifest.json and inputs/inputs.json become layout 4: every input names its root and path, the
  input snapshot and per-entry digests are dropped, stage_scripts/python_modules name the code registry entry,
  a martini3/<file> input points at the versioned copy, a molecule input still spelled at the flat path is
  rebased onto the version the folder states, a shared_reference pins the source's edition, and a
  molecule_snapshot becomes the named selection;
* a provenance.json is written beside the manifest;
* each job row's molecule_snapshot becomes the named selection, but only after it is proved to describe the same
  molecule, inputs, atom count, metadata and adapter/kind.

Dry run by default; --apply writes. Every original file and job row is backed up under
<workspace>/.named-migration/ before it is touched, and --rollback reverses the recorded changes. The operation
is idempotent (a rewritten record is reported unchanged and nothing is written again), and it refuses to run while
a run or an analysis is queued or running.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from dashboard import files, martini3, paths
from dashboard.analysis.runs import references
from dashboard.execution import protocol, run_inputs, run_scripts
from dashboard.models.molecules import aa as aa_molecules
from dashboard.store import Store

BACKUP_DIRECTORY = '.named-migration'
RECORDS_NAME = 'records.json'
REFERENCE_BACKUP_DIRECTORY = 'references'

#: A status that means a run or an analysis is working. The database is the record of both.
BUSY = ('queued', 'running', 'cancelling')

#: The code fields a prepared manifest may carry, each a mapping of stage/module to its code record.
CODE_FIELDS = ('stage_scripts', 'python_modules')


class Refusal(ValueError):
    """One record cannot be rewritten without losing what it says; it is reported and left alone."""


@contextmanager
def _selected(root=None, project_root=None):
    """Read and write one workspace's store, named or the live one."""
    base = Path(project_root) if project_root is not None else paths.current().project_root
    workspace = Path(root) if root is not None else Path(paths.current().workspace)
    with paths.use(paths.Paths(project_root=base, workspace=workspace)):
        yield Path(workspace)


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


def _read_text(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def _read_json(path):
    return json.loads(Path(path).read_text())


def _read_json_quiet(path):
    try:
        return _read_json(path)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# The backup ledger


def _records_path(workspace):
    return Path(workspace) / BACKUP_DIRECTORY / RECORDS_NAME


def _load_records(workspace):
    path = _records_path(workspace)
    if not path.is_file():
        return {'tool': 'dashboard.cli.migrate_named_records', 'version': 1,
                'workspace': str(workspace), 'references': {}, 'manifests': {}, 'jobs': {}}
    return _read_json(path)


def _save_records(workspace, records):
    files.atomic_json(_records_path(workspace), records)


def _backup_reference(workspace, entry, records):
    """Copy a reference record's original bytes under the backup directory, once."""
    run = entry['run']
    recorded = records['references'].setdefault(
        run, {'path': entry['path'], 'backup': f'{REFERENCE_BACKUP_DIRECTORY}/{run}.json'})
    backup = Path(workspace) / BACKUP_DIRECTORY / recorded['backup']
    if not backup.is_file():
        backup.parent.mkdir(parents=True, exist_ok=True)
        files.atomic_copy(Path(workspace) / 'runs' / run / entry['path'], backup)


def _backup_manifest(workspace, entry, records):
    """Keep the manifest, its inputs record and its provenance exactly as they were, once."""
    run_dir = Path(workspace) / 'runs' / entry['run']
    recorded = records['manifests'].setdefault(entry['run'], {
        'manifest': 'manifest.json',
        'inputs': 'inputs/inputs.json',
    })
    if 'manifest_text' not in recorded:
        recorded['manifest_text'] = _read_text(run_dir / 'manifest.json')
        recorded['inputs_text'] = _read_text(run_dir / 'inputs' / run_inputs.RECORD_NAME)
        recorded['provenance_text'] = _read_text(run_dir / 'provenance.json')


def _job_rows(workspace):
    """Every job row's stored text and revision, or none when the workspace has no database."""
    database = Path(workspace) / 'jobs.sqlite3'
    if not database.is_file():
        return []
    store = Store(database)
    with store.connection() as db:
        return [{'text': row[0], 'data': json.loads(row[0]), 'revision': row[1]}
                for row in db.execute('SELECT data, revision FROM jobs ORDER BY rowid')]


def _backup_job(workspace, entry, rows, records):
    row = rows.get(entry['run'])
    if row is None:
        raise Refusal(f'job row {entry["run"]} is missing')
    records['jobs'].setdefault(entry['run'], {'text': row['text'], 'revision': row['revision']})


# ---------------------------------------------------------------------------
# Planning


def _busy(workspace):
    busy = []
    for row in _job_rows(workspace):
        job = row['data']
        if job.get('status') in BUSY:
            busy.append(job.get('id'))
        for task in job.get('analyses') or []:
            if isinstance(task, dict) and task.get('status') in BUSY:
                busy.append(f'{job.get("id")}/{task.get("id")}')
    return [name for name in busy if name]


def _artifact_names(record):
    """The paths a reference record claims, from its artifact map and its digest map."""
    names = []
    artifacts = record.get('artifacts')
    if isinstance(artifacts, dict):
        names.extend(str(value) for value in artifacts.values() if value)
    hashes = record.get('sha256')
    if isinstance(hashes, dict):
        names.extend(str(key) for key in hashes)
    return list(dict.fromkeys(names))


def _reference_molecule(record):
    """The molecule name a reference records: its own field, then the selection it published."""
    name = record.get('molecule')
    if isinstance(name, str) and name.strip():
        return name
    snapshot = record.get('molecule_snapshot')
    metadata = (snapshot or {}).get('metadata') if isinstance(snapshot, dict) else None
    name = (metadata or {}).get('name')
    if isinstance(name, str) and name.strip():
        return name
    return None


def _plan_references(workspace):
    entries = []
    runs = Path(workspace) / 'runs'
    for run_dir in sorted(runs.iterdir()) if runs.is_dir() else []:
        if run_dir.is_symlink() or not run_dir.is_dir():
            continue
        path = run_dir / 'stages/07_reference/reference.json'
        if not path.is_file() or path.is_symlink():
            continue
        run = run_dir.name
        base = {'run': run, 'path': 'stages/07_reference/reference.json'}
        try:
            original = _read_json(path)
        except (OSError, ValueError) as exc:
            entries.append({**base, 'status': 'blocked', 'reason': f'the reference record does not parse: {exc}'})
            continue
        if original.get('edition') is not None:
            entries.append({**base, 'status': 'unchanged', 'edition': original['edition']})
            continue
        names = _artifact_names(original)
        missing = [name for name in names if not (run_dir / name).exists()]
        if not names:
            entries.append({**base, 'status': 'blocked',
                            'reason': 'the reference record names no artifact to check'})
            continue
        if missing:
            entries.append({**base, 'status': 'blocked',
                            'reason': 'the reference artifacts are missing: ' + ', '.join(missing[:3])})
            continue
        molecule = _reference_molecule(original)
        if molecule is None:
            entries.append({**base, 'status': 'blocked',
                            'reason': 'the reference record names no molecule'})
            continue
        document = copy.deepcopy(original)
        document['edition'] = references.EDITION
        document['molecule'] = molecule
        entries.append({**base, 'status': 'edition', 'edition': references.EDITION,
                        'molecule': molecule, 'document': document})
    return entries


def _plan_martini(workspace):
    base = Path(workspace) / martini3.DIRECTORY
    try:
        installed = martini3.versions(installation=base)
    except (OSError, ValueError) as exc:
        return {'version': martini3.VERSION, 'status': 'blocked', 'reason': str(exc),
                'directory': f'{martini3.DIRECTORY}/{martini3.VERSION}'}
    if martini3.VERSION in installed:
        return {'version': martini3.VERSION, 'status': 'present',
                'directory': f'{martini3.DIRECTORY}/{martini3.VERSION}'}
    return {'version': martini3.VERSION, 'status': 'install',
            'directory': f'{martini3.DIRECTORY}/{martini3.VERSION}'}


def _code_name(declared, root):
    """The registry name a recorded code path names, or None when no entry claims it."""
    text = str(declared)
    for name, entry in run_scripts.CODE_VERSIONS.items():
        if entry['path'] == text:
            return name
    try:
        resolved = run_scripts.code_path(text, root=root).resolve()
    except (OSError, ValueError):
        return None
    for name, entry in run_scripts.CODE_VERSIONS.items():
        try:
            if run_scripts.code_path(entry['path'], root=root).resolve() == resolved:
                return name
        except (OSError, ValueError):
            continue
    return None


def _convert_code(block, root, field):
    """{stage: {path, sha256}} -> {stage: {name, version}}, refusing a path nobody registered."""
    if not isinstance(block, dict):
        raise Refusal(f'{field} is not an object')
    converted = {}
    for stage, entry in block.items():
        if not isinstance(entry, dict):
            raise Refusal(f'{field}.{stage} is not an object')
        if 'sha256' not in entry and entry.get('name'):
            converted[stage] = {'name': entry['name'], 'version': entry.get('version')}
            continue
        path = entry.get('path')
        name = _code_name(path, root) if path else None
        if name is None:
            raise Refusal(f'{field}.{stage}: no code version is registered for {path!r}')
        converted[stage] = {'name': name, 'version': int(run_scripts.CODE_VERSIONS[name]['version'])}
    return converted


def _store_names(workspace):
    """The parameterization records by the legacy content hash each was migrated from.

    A prepared run names a revision's own histogram files under the store. The store was renamed first, so a
    manifest written before that rename still spells `records/<legacy hash>.revisions/...`; this is the map that
    rebases it onto the record's name.
    """
    directory = Path(workspace) / 'parameterizations' / 'records'
    names = {}
    if directory.is_dir():
        for path in sorted(directory.glob('*.json')):
            try:
                record = _read_json_quiet(path)
            except (OSError, ValueError):
                continue
            if isinstance(record, dict) and record.get('legacy_hash'):
                names[str(record['legacy_hash'])] = path.stem
    return names


def _versioned_molecule(path, root, *, repo_root=None, workspace_root=None):
    """`molecules/<id>/<rest>` rebased onto `molecules/<id>/v1/<rest>` when only the versioned file exists.

    The molecule-version migration moved each live folder to `v1`, but a manifest written before it still names the
    flat path. The rewrite is proved by the filesystem: the versioned file must exist and the flat one must not.
    """
    parts = path.split('/')
    if len(parts) < 3 or parts[0] != 'molecules' or not parts[1]:
        return path
    if root == 'repo':
        base = Path(repo_root) if repo_root is not None else paths.current().project_root
    elif root == 'workspace':
        base = Path(workspace_root) if workspace_root is not None else paths.current().workspace
    else:
        return path
    candidate = '/'.join([parts[0], parts[1], 'v1', *parts[2:]])
    if (base / candidate).is_file() and not (base / path).exists():
        return candidate
    return path


def _convert_input(entry, store_names=None, *, repo_root=None, workspace_root=None):
    """One input entry by name: a workspace Martini path points at the versioned copy, a store path at the record's
    name rather than the legacy hash it was written under, and a flat molecule path at the installed version."""
    if not isinstance(entry, dict):
        raise Refusal('an input entry is not an object')
    missing = [key for key in ('role', 'label', 'kind', 'root', 'path') if not entry.get(key)]
    if missing:
        raise Refusal('an input entry is missing ' + ', '.join(missing))
    path = str(entry['path'])
    prefix = 'parameterizations/records/'
    if entry['root'] == 'workspace' and path.startswith(prefix):
        head, separator, rest = path[len(prefix):].partition('/')
        token = head.split('.', 1)[0]
        name = (store_names or {}).get(token)
        if name:
            path = prefix + name + head[len(token):] + separator + rest
    if entry['root'] == 'workspace' and path.startswith(f'{martini3.DIRECTORY}/'):
        rest = path[len(martini3.DIRECTORY) + 1:]
        if not rest.startswith(f'{martini3.VERSION}/'):
            path = f'{martini3.DIRECTORY}/{martini3.VERSION}/{rest}'
    if entry['root'] in ('repo', 'workspace'):
        path = _versioned_molecule(path, entry['root'], repo_root=repo_root, workspace_root=workspace_root)
    return {'role': str(entry['role']), 'label': str(entry['label']), 'kind': entry['kind'],
            'root': entry['root'], 'path': path}


def _snapshot_run_type(snapshot):
    """The run type a legacy selection was made as, read the way verify_selection reads it."""
    if snapshot.get('kind') == 'cg':
        return 'cg'
    if snapshot.get('adapter') == 'aa-charmm36':
        return 'aa_only'
    return 'aa_cg'


def _snapshot_difference(old, new):
    """The first structural field on which a converted selection and the legacy snapshot disagree."""
    if old.get('id') != new.get('id'):
        return f'id {old.get("id")!r} != {new.get("id")!r}'
    for key in ('atom_count', 'metadata'):
        if key in old and old.get(key) != new.get(key):
            return f'{key} differs'
    old_inputs, new_inputs = old.get('inputs') or {}, new.get('inputs') or {}
    for key in ('topology', 'coordinates'):
        if key in old_inputs and old_inputs.get(key) != new_inputs.get(key):
            return f'inputs.{key} differs'
    for key in ('adapter', 'kind', 'cg_residue_name'):
        if key in old and key in new and old.get(key) != new.get(key):
            return f'{key} differs'
    return None


def _convert_snapshot(snapshot, project_root):
    """A legacy molecule snapshot as the named selection, proved to describe the same molecule."""
    if not isinstance(snapshot, dict):
        raise Refusal('molecule_snapshot is not an object')
    if 'sha256' not in snapshot and 'reference_sha256' not in snapshot and 'name' not in snapshot \
            and 'version' in snapshot:
        return snapshot
    run_type = _snapshot_run_type(snapshot)
    try:
        selected = aa_molecules.selection(Path(project_root) / 'molecules', snapshot.get('id'), run_type,
                                          version=snapshot.get('version'))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Refusal(f'the molecule cannot be selected: {exc}') from exc
    difference = _snapshot_difference(snapshot, selected)
    if difference:
        raise Refusal(f'the legacy molecule snapshot does not match the molecule: {difference}')
    return selected


def _reference_edition(workspace, source_id):
    if not source_id:
        return None
    path = Path(workspace) / 'runs' / str(source_id) / 'stages/07_reference/reference.json'
    try:
        return _read_json(path).get('edition')
    except (OSError, ValueError):
        return None


def _convert_shared_reference(workspace, block, planned_editions):
    """Pin a shared reference by the source's edition, keeping its source run id."""
    if not isinstance(block, dict):
        raise Refusal('shared_reference is not an object')
    if block.get('edition') is not None:
        return block, None
    source = block.get('source_run_id')
    edition = planned_editions.get(source) if source else None
    if edition is None:
        edition = _reference_edition(workspace, source)
    if edition is None:
        return block, 'the source reference has no edition; the legacy digest map is kept'
    return {'source_run_id': source, 'edition': edition}, None


def _convert_manifest(workspace, run_dir, manifest, project_root, planned_editions):
    """The layout-4 manifest and the inputs record beside it, refusing anything that cannot be named."""
    document = copy.deepcopy(manifest)
    document['layout_version'] = run_inputs.LAYOUT
    document.pop('input_snapshot_sha256', None)

    inputs = document.get('inputs')
    record_path = run_dir / 'inputs' / run_inputs.RECORD_NAME
    try:
        recorded = _read_json(record_path) if record_path.is_file() else None
    except (OSError, ValueError) as exc:
        raise Refusal(f'inputs/inputs.json does not parse: {exc}') from exc
    if inputs is not None:
        if recorded is None:
            raise Refusal('the manifest names inputs but inputs/inputs.json is missing')
        if recorded.get('inputs') != inputs:
            raise Refusal('the manifest and inputs/inputs.json disagree about the inputs')
        store_names = _store_names(workspace)
        inputs = [_convert_input(entry, store_names, repo_root=project_root, workspace_root=workspace)
                  for entry in inputs]
        document['inputs'] = inputs
        recorded = {**recorded, 'inputs': inputs}
    elif recorded is not None and isinstance(recorded.get('inputs'), list):
        # A layout-2 run whose inputs record survived: name them too rather than dropping the only record.
        store_names = _store_names(workspace)
        inputs = [_convert_input(entry, store_names, repo_root=project_root, workspace_root=workspace)
                  for entry in recorded['inputs']]
        document['inputs'] = inputs
        recorded = {**recorded, 'inputs': inputs}
    else:
        # A run that recorded no inputs still gets a layout-4 record: an empty list says it named none, where a
        # missing key would leave the record unverifiable.
        inputs = []
        recorded = {'inputs': []}
        document['inputs'] = inputs

    for field in CODE_FIELDS:
        if field in document:
            document[field] = _convert_code(document[field], project_root, field)

    notes = []
    if 'molecule_snapshot' in document:
        try:
            document['molecule_snapshot'] = _convert_snapshot(document['molecule_snapshot'], project_root)
        except Refusal as exc:
            raise Refusal(f'the manifest molecule snapshot cannot be named: {exc}') from exc

    if 'shared_reference' in document:
        try:
            document['shared_reference'], note = _convert_shared_reference(
                workspace, document['shared_reference'], planned_editions)
        except Refusal as exc:
            raise Refusal(f'the shared reference cannot be pinned: {exc}') from exc
        if note:
            notes.append(note)

    provenance = protocol._provenance(document, inputs)
    return document, recorded, provenance, notes


def _plan_manifests(workspace, project_root, planned_editions):
    entries = []
    runs = Path(workspace) / 'runs'
    for run_dir in sorted(runs.iterdir()) if runs.is_dir() else []:
        if run_dir.is_symlink() or not run_dir.is_dir():
            continue
        path = run_dir / 'manifest.json'
        if not path.is_file() or path.is_symlink():
            continue
        run = run_dir.name
        base = {'run': run, 'path': 'manifest.json'}
        try:
            manifest = _read_json(path)
        except (OSError, ValueError) as exc:
            entries.append({**base, 'status': 'blocked', 'reason': f'the manifest does not parse: {exc}'})
            continue
        if not isinstance(manifest, dict):
            entries.append({**base, 'status': 'blocked', 'reason': 'the manifest is not an object'})
            continue
        try:
            document, inputs_record, provenance, notes = _convert_manifest(
                workspace, run_dir, manifest, project_root, planned_editions)
        except Refusal as exc:
            entries.append({**base, 'status': 'blocked', 'reason': str(exc)})
            continue
        provenance_path = run_dir / 'provenance.json'
        unchanged = (manifest == document and inputs_record == _read_json_quiet(
            run_dir / 'inputs' / run_inputs.RECORD_NAME)
            and provenance_path.is_file() and _read_json_quiet(provenance_path) == provenance)
        if unchanged:
            entries.append({**base, 'status': 'unchanged', 'notes': notes})
            continue
        entries.append({**base, 'status': 'write', 'notes': notes,
                        'manifest': document, 'inputs_record': inputs_record, 'provenance': provenance})
    return entries


def _plan_jobs(workspace, project_root):
    entries = []
    for row in _job_rows(workspace):
        job = row['data']
        run = job.get('id')
        snapshot = job.get('molecule_snapshot')
        if snapshot is None:
            entries.append({'run': run, 'status': 'unchanged'})
            continue
        if not isinstance(snapshot, dict):
            entries.append({'run': run, 'status': 'blocked', 'reason': 'molecule_snapshot is not an object'})
            continue
        if 'sha256' not in snapshot and 'reference_sha256' not in snapshot and 'name' not in snapshot \
                and 'version' in snapshot:
            entries.append({'run': run, 'status': 'unchanged'})
            continue
        try:
            selected = _convert_snapshot(snapshot, project_root)
        except Refusal as exc:
            entries.append({'run': run, 'status': 'blocked', 'reason': str(exc)})
            continue
        if selected == snapshot:
            entries.append({'run': run, 'status': 'unchanged'})
        else:
            entries.append({'run': run, 'status': 'write', 'snapshot': selected})
    return entries


def _plan(workspace, project_root):
    reference_entries = _plan_references(workspace)
    planned_editions = {entry['run']: entry['edition'] for entry in reference_entries
                        if entry['status'] == 'edition'}
    return {
        'tool': 'dashboard.cli.migrate_named_records',
        'version': 1,
        'workspace': str(workspace),
        'project_root': str(project_root),
        'busy': _busy(workspace),
        'references': reference_entries,
        'martini': _plan_martini(workspace),
        'manifests': _plan_manifests(workspace, project_root, planned_editions),
        'jobs': _plan_jobs(workspace, project_root),
    }


def plan(root=None, *, project_root=None):
    """What the migration would rewrite, per record. Reads only."""
    with _selected(root, project_root) as workspace:
        return _plan(workspace, paths.current().project_root)


# ---------------------------------------------------------------------------
# Applying


def _apply_references(workspace, entries):
    written = []
    for entry in entries:
        if entry['status'] != 'edition':
            continue
        path = Path(workspace) / 'runs' / entry['run'] / entry['path']
        files.atomic_json(path, entry['document'])
        written.append(entry)
    return written


def _apply_martini(workspace, entry):
    if entry['status'] != 'install':
        return entry
    base = Path(workspace) / martini3.DIRECTORY
    try:
        # martini3.ensure either serves the version this code names or proves the flat install; it has no entry
        # point that installs a new version beside an existing one, so the migration calls the module's own
        # versioned install rather than restating the copy-and-witness procedure.
        martini3._install_version(base, martini3.VERSION, project_root=paths.current().project_root)
    except (OSError, ValueError) as exc:
        return {**entry, 'status': 'blocked', 'reason': f'the Martini 3 set could not be installed: {exc}'}
    return {**entry, 'status': 'installed'}


def _apply_manifests(workspace, entries):
    written = []
    for entry in entries:
        if entry['status'] != 'write':
            continue
        run_dir = Path(workspace) / 'runs' / entry['run']
        files.atomic_json(run_dir / 'manifest.json', entry['manifest'])
        if entry['inputs_record'] is not None:
            files.atomic_json(run_dir / 'inputs' / run_inputs.RECORD_NAME, entry['inputs_record'])
        files.atomic_json(run_dir / 'provenance.json', entry['provenance'])
        written.append(entry)
    return written


def _apply_jobs(workspace, entries):
    database = Path(workspace) / 'jobs.sqlite3'
    if not database.is_file():
        return []
    store = Store(database)
    written = []
    for entry in entries:
        if entry['status'] != 'write':
            continue
        store.update(entry['run'], molecule_snapshot=entry['snapshot'])
        written.append(entry)
    return written


def apply(entries, root=None, *, project_root=None):
    """Rewrite the planned records, backing every original up first, then verify them."""
    workspace_root = root if root is not None else entries.get('workspace')
    project = project_root if project_root is not None else entries.get('project_root')
    with _selected(workspace_root, project) as workspace:
        busy = _busy(workspace)
        if busy:
            raise RuntimeError('a run or analysis is working: ' + ', '.join(busy))
        records = _load_records(workspace)
        before_records = json.dumps(records, sort_keys=True)
        rows = {row['data'].get('id'): row for row in _job_rows(workspace)}

        for entry in entries['references']:
            if entry['status'] == 'edition':
                _backup_reference(workspace, entry, records)
        for entry in entries['manifests']:
            if entry['status'] == 'write':
                _backup_manifest(workspace, entry, records)
        for entry in entries['jobs']:
            if entry['status'] == 'write':
                _backup_job(workspace, entry, rows, records)
        if entries['martini']['status'] == 'install':
            base = Path(workspace) / martini3.DIRECTORY
            records.setdefault('martini', {'version': entries['martini']['version'],
                                           'directory': entries['martini']['directory'],
                                           'created': not (base / martini3.VERSION).exists(),
                                           'base_created': not base.exists(),
                                           'lock_created': not (base / '.install.lock').exists()})
        if json.dumps(records, sort_keys=True) != before_records:
            # A second apply over a migrated workspace records nothing new; leaving the ledger's bytes alone is
            # what makes "the second run writes nothing" true rather than nearly true.
            _save_records(workspace, records)

        written_references = _apply_references(workspace, entries['references'])
        martini_entry = _apply_martini(workspace, entries['martini'])
        written_manifests, written_jobs = [], []
        manifests, jobs = entries['manifests'], entries['jobs']
        if martini_entry['status'] == 'blocked':
            # The inputs were going to point at the versioned install; without it the rewritten names would not
            # resolve, so the manifest and row rewrites wait for a successful install.
            reason = 'the Martini 3 install did not happen: ' + str(martini_entry.get('reason'))
            manifests = [{**entry, 'status': 'blocked', 'reason': reason}
                         if entry['status'] == 'write' else entry for entry in manifests]
            jobs = [{**entry, 'status': 'blocked', 'reason': reason}
                    if entry['status'] == 'write' else entry for entry in jobs]
        else:
            written_manifests = _apply_manifests(workspace, manifests)
            written_jobs = _apply_jobs(workspace, jobs)
        result = {
            **entries,
            'martini': martini_entry,
            'references': entries['references'],
            'manifests': manifests,
            'jobs': jobs,
            'written': {'references': [entry['run'] for entry in written_references],
                        'manifests': [entry['run'] for entry in written_manifests],
                        'jobs': [entry['run'] for entry in written_jobs]},
        }
        result['verification'] = _verify(workspace, result)
        return result


# ---------------------------------------------------------------------------
# Verification


def _verify(workspace, entries):
    """Read every rewritten record through the project's own readers; a refusal is reported, not raised."""
    workspace = Path(workspace)
    refusals = []
    editions = {entry['run']: entry['edition'] for entry in entries['references']
                if entry['status'] == 'edition'}
    for run, edition in editions.items():
        try:
            references.resolve(workspace / 'runs', run, expected={'edition': edition})
        except (OSError, ValueError) as exc:
            refusals.append({'run': run, 'check': 'references.resolve', 'error': str(exc)})
    for entry in entries['manifests']:
        if entry['status'] != 'write':
            continue
        run_dir = workspace / 'runs' / entry['run']
        try:
            manifest = _read_json(run_dir / 'manifest.json')
            run_inputs.verify_manifest(run_dir, manifest)
        except (OSError, ValueError) as exc:
            refusals.append({'run': entry['run'], 'check': 'run_inputs.verify_manifest', 'error': str(exc)})
            continue
        try:
            protocol.run_type_of(manifest)
            protocol.plan_pairs(manifest)
        except (OSError, ValueError, TypeError) as exc:
            refusals.append({'run': entry['run'], 'check': 'protocol.plan_pairs', 'error': str(exc)})
        shared = manifest.get('shared_reference')
        if isinstance(shared, dict) and shared.get('edition') is not None:
            try:
                references.resolve(workspace / 'runs', shared.get('source_run_id'),
                                   expected={'edition': shared['edition']})
            except (OSError, ValueError) as exc:
                refusals.append({'run': entry['run'], 'check': 'references.resolve(shared)', 'error': str(exc)})
    database = workspace / 'jobs.sqlite3'
    if database.is_file():
        store = Store(database)
        for entry in entries['jobs']:
            if entry['status'] != 'write':
                continue
            try:
                row = store.get(entry['run'])
                if row is None or row.get('molecule_snapshot') != entry['snapshot']:
                    raise ValueError('the rewritten job row does not carry the selection')
            except (OSError, ValueError) as exc:
                refusals.append({'run': entry['run'], 'check': 'Store.get', 'error': str(exc)})
    return refusals


# ---------------------------------------------------------------------------
# Rolling back


def rollback(root=None, *, project_root=None):
    """Reverse every recorded rewrite: job rows, manifests, the versioned install, then references."""
    with _selected(root, project_root) as workspace:
        busy = _busy(workspace)
        if busy:
            raise RuntimeError('a run or analysis is working: ' + ', '.join(busy))
        path = _records_path(workspace)
        if not path.is_file():
            return {'status': 'nothing', 'reason': f'no {RECORDS_NAME} to roll back from'}
        records = _read_json(path)
        database = Path(workspace) / 'jobs.sqlite3'
        warnings = []
        restored = {'jobs': [], 'manifests': [], 'references': [], 'martini': None}

        if database.is_file():
            store = Store(database)
            with store.connection() as db:
                for run, entry in (records.get('jobs') or {}).items():
                    db.execute('UPDATE jobs SET data=?, revision=? WHERE id=?',
                               (entry['text'], entry['revision'], run))
                    restored['jobs'].append(run)

        for run, entry in (records.get('manifests') or {}).items():
            run_dir = Path(workspace) / 'runs' / run
            _atomic_text(run_dir / entry.get('manifest', 'manifest.json'), entry['manifest_text'])
            inputs_path = run_dir / entry.get('inputs', 'inputs/inputs.json')
            if entry.get('inputs_text') is not None:
                _atomic_text(inputs_path, entry['inputs_text'])
            else:
                # The migration created this record for a run that named no inputs; the original had none.
                inputs_path.unlink(missing_ok=True)
                if inputs_path.parent.is_dir() and not any(inputs_path.parent.iterdir()):
                    inputs_path.parent.rmdir()
            provenance = run_dir / 'provenance.json'
            if entry.get('provenance_text') is not None:
                _atomic_text(provenance, entry['provenance_text'])
            else:
                provenance.unlink(missing_ok=True)
            restored['manifests'].append(run)

        martini = records.get('martini')
        if martini and martini.get('created'):
            target = Path(workspace) / martini['directory']
            witness = target / martini3.MANIFEST_NAME
            try:
                stated = _read_json(witness).get('version')
            except (OSError, ValueError):
                stated = None
            if stated == martini.get('version'):
                shutil.rmtree(target)
                restored['martini'] = martini['directory']
                if martini.get('lock_created'):
                    (Path(workspace) / martini3.DIRECTORY / '.install.lock').unlink(missing_ok=True)
                if martini.get('base_created'):
                    base = Path(workspace) / martini3.DIRECTORY
                    if base.is_dir() and not any(base.iterdir()):
                        base.rmdir()
            else:
                warnings.append({'status': 'warning',
                                 'reason': f'{target} is not the install the migration created; it is left alone'})

        for run, entry in (records.get('references') or {}).items():
            backup = Path(workspace) / BACKUP_DIRECTORY / entry['backup']
            if not backup.is_file():
                warnings.append({'status': 'warning', 'reason': f'the reference backup for {run} is missing'})
                continue
            files.atomic_copy(backup, Path(workspace) / 'runs' / run / entry['path'])
            restored['references'].append(run)

        records['rolled_back_at'] = files.now_iso()
        _save_records(workspace, records)
        return {'status': 'rolled-back', 'restored': restored, 'warnings': warnings}


# ---------------------------------------------------------------------------
# Command line


def summary(entries):
    counts = {}
    for category in ('references', 'manifests', 'jobs'):
        for entry in entries.get(category) or []:
            key = f'{category}:{entry["status"]}'
            counts[key] = counts.get(key, 0) + 1
    counts[f'martini:{entries["martini"]["status"]}'] = 1
    return counts


def _reported(entries):
    """The plan without the full documents apply carries, so a report stays readable."""
    private = ('manifest', 'inputs_record', 'provenance', 'snapshot', 'document')
    reported = {key: value for key, value in entries.items() if key not in ('references', 'manifests', 'jobs')}
    for category in ('references', 'manifests', 'jobs'):
        reported[category] = [{key: value for key, value in entry.items() if key not in private}
                              for entry in entries.get(category) or []]
    return reported


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Rewrite prepared run records to the named (layout 4) contract')
    parser.add_argument('--workspace', type=Path, default=None, help='a workspace to migrate (default: the live one)')
    parser.add_argument('--project-root', type=Path, default=None,
                        help='the data root holding molecules/ and references/ (default: the checkout)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='rewrite the records (default: report only)')
    mode.add_argument('--rollback', action='store_true', help='reverse a previous apply from its backup')
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
        for warning in result.get('warnings') or []:
            print(f"  warning    {warning['reason']}")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, indent=2) + '\n')
            print(f'report: {args.report}')
        return 0

    entries = plan(args.workspace, project_root=args.project_root)
    if entries.get('busy'):
        print('refused: a run or analysis is working: ' + ', '.join(entries['busy']))
        return 1
    if args.apply:
        try:
            result = apply(entries, args.workspace, project_root=args.project_root)
        except RuntimeError as exc:
            print(f'refused: {exc}')
            return 1
    else:
        result = entries
    print(' '.join(f'{key}={value}' for key, value in sorted(summary(result).items())))
    for category in ('references', 'manifests', 'jobs'):
        for entry in result.get(category) or []:
            if entry['status'] in ('write', 'edition', 'blocked'):
                note = entry.get('reason') or entry.get('notes')
                print(f'  {category:<10} {entry["status"]:<9} {entry["run"]:<14}'
                      + (f'  ({note})' if note else ''))
    for refusal in result.get('verification') or []:
        print(f'  refusal    {refusal["run"]:<14} {refusal["check"]}: {refusal["error"]}')
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(_reported(result), indent=2) + '\n')
        print(f'report: {args.report}')
    # A blocked record is reported and left alone, not a command failure; a reader that finds a rewritten record
    # unreadable after the fact is.
    return 1 if result.get('verification') else 0


if __name__ == '__main__':
    raise SystemExit(main())
