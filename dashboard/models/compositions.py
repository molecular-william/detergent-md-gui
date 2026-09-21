"""Immutable fragment compositions and attachment-map validation."""
from .. import files, paths
import json
import uuid
from pathlib import Path
import re
from . import model_registry
from .json_repository import JsonRepository

ROOT = paths.DEFAULT.project_root


def storage_root():
    return paths.current().compositions


def _id(): return uuid.uuid4().hex[:16]


def _path(cid):
    return _repository().path(cid)


def _validate_id(cid):
    if not isinstance(cid, str) or not re.fullmatch(r'[a-f0-9]{16}', cid):
        raise ValueError('Invalid composition ID')
    return cid


def _repository():
    return JsonRepository(storage_root(), '{id}.json', _validate_id)


def all_compositions():
    return _repository().list(skip_invalid=True)


def get(cid): return _repository().get(cid)


def validate(payload):
    if not isinstance(payload, dict): raise ValueError('Composition must be an object')
    fragments = payload.get('fragments')
    if not isinstance(fragments, list) or not fragments: raise ValueError('Composition needs fragments')
    ids = [f.get('id') if isinstance(f, dict) else f for f in fragments]
    if len(set(ids)) != len(ids): raise ValueError('Composition cannot repeat a fragment')
    records = {f['id']: f for f in model_registry.fragments()}
    if any(i not in records for i in ids): raise ValueError('Composition references an unknown fragment')
    attachments = payload.get('attachments', [])
    if not isinstance(attachments, list): raise ValueError('attachments must be a list')
    seen = set()
    for item in attachments:
        if not isinstance(item, dict): raise ValueError('Each attachment must be an object')
        required = ('left_fragment','right_fragment','left_atom','right_atom')
        if any(k not in item for k in required): raise ValueError('Attachment is missing fragment or atom ownership')
        if item['left_fragment'] not in ids or item['right_fragment'] not in ids: raise ValueError('Attachment references an unselected fragment')
        key = tuple(item[k] for k in required)
        if key in seen: raise ValueError('Duplicate attachment')
        seen.add(key)
        if item['left_fragment'] == item['right_fragment']: raise ValueError('Attachment must connect distinct fragments')
    return {'ok': True, 'fragment_ids': ids, 'attachment_count': len(attachments)}


def create(payload):
    validate(payload)
    body = json.loads(json.dumps(payload, sort_keys=True))
    record = {'id': _id(), 'kind': 'composition', 'created_at': files.now_iso(), 'snapshot_hash': files.json_sha256(body), 'validation': validate(body), 'snapshot': body}
    _repository().write(record['id'], record)
    return record
