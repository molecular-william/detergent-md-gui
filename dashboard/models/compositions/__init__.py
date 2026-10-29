"""Immutable fragment compositions and attachment-map validation."""
import json
import re
import uuid

from ... import files, paths
from ..molecules import registry as model_registry
from ..repository import JsonRepository
from . import topology as composition_topology


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


def catalog(project_root=None):
    """Return the immutable choices exposed by Molecule Combination."""
    sugars = composition_topology.load_sugar_catalog(composition_topology._sugar_source(project_root))
    return {
        'sugars': [{'id': key, 'name': key, 'source_sha256': value['source_sha256'],
                    'beads': value['bead_names'],
                    'endpoints': [atom['name'] for atom in value['atoms'] if not atom['virtual']]}
                   for key, value in sugars.items()],
        'tail_recipes': composition_topology.tail_recipe_catalog(),
        'linkage_profiles': composition_topology.linkage_profile_catalog(),
    }


def preview(payload, project_root=None):
    result = composition_topology.build_preview(payload, project_root)
    composition_topology.validate_preview(result)
    result['geometry'] = composition_topology.preview_geometry(result)
    # The panel hands this straight to the NGL viewer, so the browser needs no second request and no route of
    # its own. It is derived, like `geometry`: composition_identity hashes mapping/topology/tail/profile, so a
    # rendering convenience cannot change a composition's identity.
    result['pdb'] = composition_topology.render_pdb(result)
    return result


def create_composition(payload, project_root=None):
    result = preview(payload, project_root)
    identity = result['identity']
    for record in all_compositions():
        if record.get('identity') == identity:
            raise ValueError(f'Composition already exists: {record["id"]}')
    cid = _id()
    root = storage_root() / cid
    root.mkdir(parents=True, exist_ok=False)
    try:
        artifacts = {'composition.itp': result['itp'], 'composition.gro': result['gro'],
                     'mapping.json': json.dumps(result['mapping'], indent=2),
                     'bonded-state.json': json.dumps({'mapping': result['mapping'],
                         'topology': result['topology'], 'status': 'complete',
                         'origin': 'composition-generated'}, indent=2)}
        for name, content in artifacts.items():
            (root / name).write_text(content)
        snapshot = {'payload': dict(payload), 'identity': identity,
                    'mapping': result['mapping'], 'topology': result['topology'],
                    'tail': result['tail'], 'profile': result['profile'],
                    'artifacts': {name: files.sha256(root / name) for name in artifacts}}
        record = {'id': cid, 'kind': 'composition', 'name': result['mapping']['name'],
                  'created_at': files.now_iso(), 'identity': identity,
                  'snapshot_hash': files.json_sha256(snapshot),
                  'status': 'candidate-unvalidated', 'scientifically_validated': False,
                  'artifact_root': str(root),
                  'snapshot': snapshot}
        _repository().write(cid, record, replace=False)
        return record
    except Exception:
        for path in sorted(root.rglob('*'), reverse=True):
            if path.is_file(): path.unlink()
        root.rmdir()
        raise


def composition_detail(cid, project_root=None):
    record = get(cid)
    return {**record, **record.get('snapshot', {}), 'composition_id': cid}


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
    """Write a composition record without artifacts; the root-free validation entry point.

    Tests that exercise fragment and attachment validation use this, because they need no
    molecule workspace. It writes a record with no composition.itp, composition.gro,
    mapping.json or bonded-state.json, so nothing that resolves a composition's artifacts can
    consume it: `create_composition` is the one the API and the catalog use, and the route
    that called this was unreachable code until Task 6.6 deleted it.
    """
    validate(payload)
    body = json.loads(json.dumps(payload, sort_keys=True))
    record = {'id': _id(), 'kind': 'composition', 'created_at': files.now_iso(), 'snapshot_hash': files.json_sha256(body), 'validation': validate(body), 'snapshot': body}
    _repository().write(record['id'], record)
    return record
