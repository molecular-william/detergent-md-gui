"""Read-only carbohydrate validation target registry."""

import json
from pathlib import Path

REGISTRY = Path('resources/validation/carbohydrates/targets-v1.json')


def _path(root):
    root = Path(root)
    direct = root / 'targets-v1.json'
    return direct if direct.is_file() else root / REGISTRY


def _read(root):
    path = _path(root)
    if not path.is_file():
        raise ValueError(f'Carbohydrate target registry is missing: {path}')
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError('Carbohydrate target registry is invalid') from exc
    if not isinstance(data.get('datasets'), list):
        raise ValueError('Carbohydrate target registry must contain datasets')
    return data


def catalog(root, molecule_id):
    datasets = [item for item in _read(root)['datasets'] if item.get('molecule_id') == molecule_id]
    return {'schema_version': 1, 'molecule_id': molecule_id, 'datasets': datasets}


def validate_selection(root, molecule_id, dataset_id):
    for item in catalog(root, molecule_id)['datasets']:
        if item.get('id') == dataset_id:
            if not item.get('citation'):
                raise ValueError('Carbohydrate target dataset is missing a citation')
            return item
    raise ValueError(f'Unknown carbohydrate target dataset: {dataset_id}')
