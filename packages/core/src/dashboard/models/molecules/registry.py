"""Immutable reference and fragment registry for Martini detergent models."""
import re
from pathlib import Path

from ... import files, paths
from ..repository import JsonRepository

ROOT = paths.DEFAULT.project_root


def storage_root():
    return paths.current().model_registry


def _safe_id(value):
    if not re.fullmatch(r'[a-f0-9]{16}', value): raise ValueError('Invalid model ID')
    return value


def _repository(kind):
    return JsonRepository(storage_root() / kind, '{id}.json', _safe_id)


def _all(kind):
    return _repository(kind).list(skip_invalid=True)


def references(): return sorted(_all('references'), key=lambda x: x.get('created_at',''), reverse=True)
def fragments(): return sorted(_all('fragments'), key=lambda x: x.get('created_at',''), reverse=True)
def get(kind, item_id): return _repository(kind).get(item_id)




def check_reference(record):
    path = Path(record['source_path'])
    if not path.is_file() or path.is_symlink(): return {'ok': False, 'reason': 'source is missing or symlink'}
    actual = files.sha256(path)
    return {'ok': actual == record.get('sha256'), 'expected': record.get('sha256'), 'actual': actual,
            'reason': None if actual == record.get('sha256') else 'source hash changed'}
