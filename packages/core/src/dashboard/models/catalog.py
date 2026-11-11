"""Read-only catalog shared by the mapping and composition workspaces.

A composition is listed as a **named CG model**: its row carries the molecule it is listed under (`molecule_id`),
the name it was saved with (`molecule_name`), the atomistic molecule its head came from (`head_molecule_id`), its
status, and the parameterization a CG run consumes: the composition's **current** revision, which is the derived
model until a reader edits its bonded terms in Combinations. `compositions.parameterization` is the one answer the
catalogue, the panel and a run read.
"""
from . import compositions, mappings


def _composition_row(item):
    cid = item['id']
    try:
        parameterization = compositions.parameterization(cid)
    except (OSError, ValueError):
        # A record with no readable artifacts (the validation-only records `create` writes, or a damaged store
        # directory) is listed without a model rather than breaking every row behind it.
        parameterization = None
    return {'kind': 'composition', 'id': cid,
            'name': compositions.molecule_name(item),
            'molecule_id': compositions.molecule_id(item),
            'molecule_name': compositions.molecule_name(item),
            'head_molecule_id': item.get('head_molecule_id'),
            'mapping_hash': item.get('identity'),
            'status': item.get('status', 'candidate-unvalidated'), 'origin': 'composition',
            'parameterization': parameterization,
            'scientifically_validated': False}


def list_models():
    rows = []
    for item in mappings.list_candidates(summary=True):
        rows.append({'kind': 'mapping', 'id': item.get('file'), 'name': item.get('name') or item.get('file'),
                     'mapping_hash': item.get('mapping_hash') or item.get('mapping_content_hash'),
                     'status': item.get('status', 'candidate'), 'origin': 'mapping',
                     'scientifically_validated': bool(item.get('scientifically_validated', False))})
    for item in compositions.all_compositions():
        rows.append(_composition_row(item))
    return rows


def get_model(kind, identifier):
    if kind == 'composition':
        return compositions.composition_detail(identifier)
    if kind == 'mapping':
        return mappings.get(identifier)
    raise ValueError('Unknown CG model kind')
