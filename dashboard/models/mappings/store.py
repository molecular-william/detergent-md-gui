"""Candidate persistence: storage root, listing, save, review and variants."""
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import uuid

from ... import paths
from .context import as_structure
from ..molecules.packaged import SOURCE, molecule
from . import verdict
from .graph import require_usable, validate
from .identity import candidate_identity, content_identity
from .schema import check_schema
from ..repository import JsonRepository


def storage_root():
    return paths.current().mapping_drafts


def _validate_filename(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
        raise ValueError('Invalid mapping record ID')
    return value


def _repository(root=None):
    return JsonRepository(root or storage_root(), '{id}', _validate_filename)


def reviews_root():
    """Where immutable review records live: under the drafts root, never beside it."""
    return storage_root() / 'reviews'


def candidate_paths():
    return {p.name: p for root in (SOURCE, storage_root()) for p in sorted(root.glob('mapping_candidate*.json'))}


def get(name, *, context=None):
    path = candidate_paths().get(name)
    if path is None:
        raise FileNotFoundError(name)
    structure = json.dumps(as_structure(context), sort_keys=True) if context else json.dumps(molecule(), sort_keys=True)
    return _read_candidate(path, name, structure)


def _read_candidate(path, name, structure):
    raw = path.read_text()
    data = json.loads(raw)
    data['file'] = name
    data['sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    data['mapping_hash'] = candidate_identity(data)
    data['mapping_content_hash'] = content_identity(data)
    data['validation'] = deepcopy(_validation(raw, structure, bool(data.get('schema_version') == 3)))
    return data


@lru_cache(maxsize=256)
def _validation(raw, structure, allow_partial=False):
    return validate(json.loads(raw), json.loads(structure), allow_partial=allow_partial)


def list_candidates(summary=False, *, context=None):
    result = []
    structure = json.dumps(as_structure(context), sort_keys=True) if context else json.dumps(molecule(), sort_keys=True)
    for name, path in candidate_paths().items():
        try:
            data = _read_candidate(path, name, structure)
            if context and (data.get('molecule_id') != context.get('molecule_id') or data.get('molecule_snapshot') != context.get('snapshot')):
                continue
            if summary:
                data = {k: data[k] for k in ('file','name','status','sha256','mapping_hash','mapping_content_hash','validation') if k in data}
            result.append(data)
        except (ValueError, OSError) as exc:
            result.append({'file': name, 'name': name, 'error': str(exc)})
    return result


def save_draft(data, *, context=None):
    validation = validate(data, context=context, allow_partial=bool(data.get('schema_version') == 3))
    if data.get('schema_version') == 3 and not validation['can_save']:
        raise ValueError('Cannot save malformed mapping: ' + '; '.join(item['message'] for item in verdict.blocking(validation['issues'], 'can_save')))
    draft = {k: data[k] for k in ('name', 'beads', 'rings', 'connections', 'bonded_options', 'bonded_overrides', 'schema_version', 'provenance', 'limitations', 'molecule_id', 'molecule_snapshot') if k in data}
    if isinstance(data.get('algorithm'), str): draft['algorithm'] = data['algorithm'][:2000]
    draft.update(status='candidate-unvalidated', martini_version='3',
                 source_structure=(context.get('path') if context else 'results/MMFF/lig1.pdb'), created_at=datetime.now(timezone.utc).isoformat(),
                 parent=data.get('file') if data.get('file') in candidate_paths() else None,
                 validation=validation)
    storage_root().mkdir(parents=True, exist_ok=True)
    filename = f'mapping_candidate_{uuid.uuid4().hex}.json'
    _repository().write(filename, draft, replace=False)
    path = storage_root() / filename
    return get(path.name, context=context)


def generate_variants(data, limit=8):
    """Generate bounded deterministic label variants with explicit provenance."""
    check_schema(data)
    if not isinstance(limit, int) or limit < 1 or limit > 32:
        raise ValueError('Variant limit must be between 1 and 32')
    variants = []
    labels = ('d', 'a', 'e', 'v')
    for index, bead in enumerate(data['beads']):
        for label in labels:
            if len(variants) >= limit: break
            if bead.get('label') == label: continue
            candidate = json.loads(json.dumps(data)); candidate['name'] = f"{data['name']} · {bead['name']}={label}"
            candidate['beads'][index]['label'] = label
            candidate['parent_candidate'] = data.get('file') or data.get('name')
            candidate['transformation'] = {'type': 'label_variant', 'bead_index': index, 'label': label}
            variants.append(save_draft(candidate))
        if len(variants) >= limit: break
    return variants


def record_review(data, state, reviewer='', notes='', *, context=None):
    """Persist an immutable review record; never mutate packaged candidates."""
    if state not in ('draft', 'needs-review', 'approved', 'rejected'):
        raise ValueError('Invalid review state')
    check_schema(data, allow_empty=bool(data.get('schema_version') == 3)); validation = validate(data, context=context, allow_partial=bool(data.get('schema_version') == 3))
    if state == 'approved' and not validation['can_approve']:
        raise ValueError('Cannot approve mapping: ' + '; '.join(item['message'] for item in verdict.blocking(validation['issues'], 'can_approve')))
    source = data.get('file', data.get('name', 'candidate'))
    safe = re.sub(r'[^A-Za-z0-9_.-]', '_', str(source))[:120]
    storage_root().mkdir(parents=True, exist_ok=True)
    reviews = reviews_root(); reviews.mkdir(exist_ok=True)
    record = {'candidate': source, 'state': state, 'reviewer': str(reviewer)[:160],
              'notes': str(notes)[:2000], 'reviewed_at': datetime.now(timezone.utc).isoformat(),
              'validation': validation, 'scientifically_validated': False}
    filename = f'{safe}-{uuid.uuid4().hex[:10]}.json'
    _repository(reviews).write(filename, record, replace=False)
    return record


def list_reviews():
    """Every readable review record, read through this store's own repository.

    A record whose name the validator refuses, or whose JSON does not parse, is skipped:
    the review list is a view of what is there, and one bad file must not blank it.
    """
    directory = reviews_root()
    return _repository(directory).list(skip_invalid=True) if directory.is_dir() else []


def delete_draft(name):
    """Remove one saved draft, or raise KeyError when there is no such file.

    The name goes through the validator the rest of the store uses and the path through
    the repository's containment check, so a name that escapes the drafts root is refused
    here rather than by a route-level pattern.
    """
    path = _repository().path(name)
    if not path.is_file():
        raise KeyError(name)
    path.unlink()
    return name
