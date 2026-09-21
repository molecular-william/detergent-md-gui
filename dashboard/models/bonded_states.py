"""Versioned bonded-state records for mappings.

State files are immutable revisions; the small JSON index is rebuilt safely by
atomic replacement. Simulation jobs retain their own state snapshots.

Topology parsing and rewriting live in bonded.py; this module re-exports them
so historical callers using bonded_states.parse_interactions keep working.
"""
from .. import files, paths
import json
import re
import uuid
from . import mappings
from .json_repository import JsonRepository
from .bonded import parse_interactions, apply_interaction_edits, apply_interaction_parameters  # noqa: F401  (façade re-export)

ROOT = paths.DEFAULT.project_root


def storage_root():
    return paths.current().bonded_states


def _path(state_id):
    return _repository().path(state_id)


def _validate_id(state_id):
    if not re.fullmatch(r'[a-f0-9]{16}', state_id):
        raise ValueError('Invalid bonded state ID')
    return state_id


def _repository():
    return JsonRepository(storage_root(), '{id}.json', _validate_id)


def _write(path, record):
    _repository().write(path.stem, record)


def all_states():
    result = _repository().list(skip_invalid=True)
    return sorted(result, key=lambda x:x.get('updated_at',''), reverse=True)


def get(state_id, revision=None):
    record = _repository().get(state_id)
    if revision is None or revision == record.get('revision'): return record
    for item in record.get('revisions',[]):
        if item.get('revision') == int(revision): return item
    raise KeyError(f'Unknown bonded state revision: {state_id}/{revision}')


def validate_payload(mapping, payload, complete=False):
    if not isinstance(payload, dict): raise ValueError('Bonded state payload must be an object')
    mapping_hash = mappings.mapping_identity(mapping)
    if payload.get('mapping_hash') != mapping_hash:
        raise ValueError('Bonded state belongs to a different bead mapping')
    topology = payload.get('topology')
    if complete and (not isinstance(topology,str) or '[ moleculetype ]' not in topology or '[ atoms ]' not in topology):
        raise ValueError('A reusable bonded state needs a complete ITP topology')
    if payload.get('status') in ('failed','incomplete') and complete:
        raise ValueError('Failed or incomplete bonded states cannot be reused')
    return mapping_hash


def _validate_revision_payload(record, payload):
    if payload.get('mapping_hash') != record['mapping_hash']:
        raise ValueError('Bonded state mapping identity cannot change')
    if payload.get('status') == 'complete' and (
        not isinstance(payload.get('topology'), str)
        or '[ moleculetype ]' not in payload['topology']
        or '[ atoms ]' not in payload['topology']
    ):
        raise ValueError('A reusable bonded state needs a complete ITP topology')


def create(mapping, name, kind='mapping-only', source=None, topology=None, status='incomplete'):
    if kind not in ('mapping-only','fast-forward-fit','manual-edit','legacy','short-validation'):
        raise ValueError('Unknown bonded state origin')
    mapping_hash = mappings.mapping_identity(mapping)
    state_id=uuid.uuid4().hex[:16]
    payload={'mapping_hash':mapping_hash,'topology':topology,'status':status,'origin':kind,'source':source or {},'name':name}
    _validate_revision_payload({'mapping_hash': mapping_hash}, payload)
    record={'state_id':state_id,'name':name or f'Bonded state {state_id[:6]}','mapping_hash':mapping_hash,
            'revision':1,'created_at':files.now_iso(),'updated_at':files.now_iso(),'current':payload,
            'revisions':[{'revision':1,'created_at':files.now_iso(),**payload}]}
    _write(_path(state_id),record); return record


def revise(state_id, patch, expected_revision=None, in_place=False):
    record=get(state_id)
    if expected_revision is not None and int(expected_revision)!=record['revision']:
        raise ValueError('Bonded state changed; reload it before editing')
    patch = dict(patch)
    interaction_edits = patch.pop('interaction_edits', None)
    interaction_parameters = patch.pop('interaction_parameters', None)
    current=dict(record['current'])
    if interaction_edits is not None:
        current['topology'] = apply_interaction_edits(current.get('topology'), interaction_edits)
    elif interaction_parameters is not None:
        current['topology'] = apply_interaction_parameters(current.get('topology'), interaction_parameters)
    current.update(patch)
    _validate_revision_payload(record, current)
    if not in_place:
        new_id = uuid.uuid4().hex[:16]
        now = files.now_iso()
        name = current.get('name') or f"{record['name']} copy"
        current['name'] = name
        item = {'revision': 1, 'created_at': now, **current}
        created = {'state_id': new_id, 'name': name, 'mapping_hash': record['mapping_hash'],
                   'revision': 1, 'created_at': now, 'updated_at': now,
                   'parent_state_id': state_id, 'parent_revision': record['revision'],
                   'current': current, 'revisions': [item]}
        _write(_path(new_id), created)
        return created
    revision=record['revision']+1; item={'revision':revision,'created_at':files.now_iso(),**current}
    record['revisions'].append(item);record['revision']=revision;record['current']=current;record['updated_at']=files.now_iso()
    _write(_path(state_id),record);return record


def references(state_id, jobs):
    state = get(state_id)
    source_run = state.get('current',{}).get('source',{}).get('run_id')
    return [j for j in jobs if j.get('bonded_state_id')==state_id or j.get('bonded_state_snapshot',{}).get('state_id')==state_id or (source_run and j.get('id')==source_run)]


def delete(state_id, jobs):
    refs=references(state_id,jobs)
    if refs: raise ValueError('Bonded state is referenced by: '+', '.join(j.get('id','unknown') for j in refs))
    path=_path(state_id);path.unlink()
    return state_id
