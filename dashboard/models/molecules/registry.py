"""Immutable reference and fragment registry for Martini detergent models."""
from ... import files, paths
import json
from pathlib import Path
import re
import uuid
from ..repository import JsonRepository

ROOT = paths.DEFAULT.project_root


def storage_root():
    return paths.current().model_registry


def _id(): return uuid.uuid4().hex[:16]


def _safe_id(value):
    if not re.fullmatch(r'[a-f0-9]{16}', value): raise ValueError('Invalid model ID')
    return value


def _repository(kind):
    return JsonRepository(storage_root() / kind, '{id}.json', _safe_id)


def _write(kind, record):
    _repository(kind).write(record['id'], record, replace=False)
    return record


def _all(kind):
    return _repository(kind).list(skip_invalid=True)


def references(): return sorted(_all('references'), key=lambda x: x.get('created_at',''), reverse=True)
def fragments(): return sorted(_all('fragments'), key=lambda x: x.get('created_at',''), reverse=True)
def get(kind, item_id): return _repository(kind).get(item_id)


def register_reference(payload, source_root=ROOT):
    if not isinstance(payload, dict): raise ValueError('Reference must be an object')
    source = payload.get('source_path')
    if not isinstance(source, str) or not source: raise ValueError('Reference source_path is required')
    path = Path(source).expanduser()
    if not path.is_absolute(): path = (Path(source_root) / path).resolve()
    else: path = path.resolve()
    if not path.is_file() or path.is_symlink(): raise ValueError('Reference source must be a regular file')
    record = {'id': _id(), 'kind': 'reference', 'name': str(payload.get('name') or path.stem),
              'source_path': str(path), 'sha256': files.sha256(path),
              'molecule': payload.get('molecule', {}), 'force_field': payload.get('force_field', {}),
              'model_kind': payload.get('model_kind', 'reference'), 'citation': payload.get('citation',''),
              'license': payload.get('license',''), 'evidence_status': payload.get('evidence_status','unvalidated'),
              'created_at': files.now_iso()}
    duplicate = [x for x in references() if x['sha256'] == record['sha256'] and x.get('source_path') == record['source_path']]
    if duplicate: raise ValueError(f"Reference already registered: {duplicate[0]['id']}")
    return _write('references', record)


def check_reference(record):
    path = Path(record['source_path'])
    if not path.is_file() or path.is_symlink(): return {'ok': False, 'reason': 'source is missing or symlink'}
    actual = files.sha256(path)
    return {'ok': actual == record.get('sha256'), 'expected': record.get('sha256'), 'actual': actual,
            'reason': None if actual == record.get('sha256') else 'source hash changed'}


def register_fragment(payload):
    if not isinstance(payload, dict): raise ValueError('Fragment must be an object')
    if not payload.get('name'): raise ValueError('Fragment name is required')
    source_ids = payload.get('reference_ids', [])
    if not isinstance(source_ids, list) or any(not isinstance(x, str) for x in source_ids): raise ValueError('reference_ids must be a list')
    for item in source_ids: get('references', item)
    body = dict(payload); body.pop('id', None); body.pop('created_at', None)
    record = {'id': _id(), 'kind': 'fragment', 'name': payload['name'], 'snapshot_hash': files.json_sha256(body),
              'created_at': files.now_iso(), **body}
    return _write('fragments', record)
