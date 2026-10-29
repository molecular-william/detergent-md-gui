"""Read-only catalog shared by the mapping and composition workspaces."""
from . import compositions, mappings


def list_models(view='summary'):
    rows = []
    for item in mappings.list_candidates(summary=True):
        rows.append({'kind': 'mapping', 'id': item.get('file'), 'name': item.get('name') or item.get('file'),
                     'mapping_hash': item.get('mapping_hash') or item.get('mapping_content_hash'),
                     'status': item.get('status', 'candidate'), 'origin': 'mapping',
                     'scientifically_validated': bool(item.get('scientifically_validated', False))})
    for item in compositions.all_compositions():
        rows.append({'kind': 'composition', 'id': item['id'], 'name': item.get('name', item['id']),
                     'mapping_hash': item.get('identity'),
                     'status': item.get('status', 'candidate-unvalidated'), 'origin': 'composition',
                     'scientifically_validated': False})
    return rows


def get_model(kind, identifier):
    if kind == 'composition':
        return compositions.composition_detail(identifier)
    if kind == 'mapping':
        return mappings.get(identifier)
    raise ValueError('Unknown CG model kind')
