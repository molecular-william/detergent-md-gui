"""Candidate persistence: storage root, listing, save, review and variants."""
import hashlib
import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache

from ... import paths
from ..molecules.packaged import SOURCE, molecule
from ..repository import JsonRepository
from . import verdict
from .context import as_structure
from .graph import validate
from .identity import candidate_identity, content_identity
from .schema import check_schema


class DuplicateMapping(ValueError):
    """A save whose content identity is already a saved mapping's.

    Not a validation failure: the document is well formed, and the thing it collides with has a name the caller needs in
    order to open it instead of saving a second copy. So the message says *which* mapping, and the route answers 409 with
    that name beside the sentence.
    """

    def __init__(self, existing):
        self.existing = existing
        super().__init__(f'An identical mapping already exists: {existing}')


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


def save_draft(data, *, context=None, in_place=False):
    validation = validate(data, context=context, allow_partial=bool(data.get('schema_version') == 3))
    if data.get('schema_version') == 3 and not validation['can_save']:
        raise ValueError('Cannot save malformed mapping: ' + '; '.join(item['message'] for item in verdict.blocking(validation['issues'], 'can_save')))
    draft = {k: data[k] for k in ('name', 'beads', 'rings', 'connections', 'bonded_options', 'bonded_overrides', 'schema_version', 'provenance', 'limitations', 'molecule_id', 'molecule_snapshot') if k in data}
    if isinstance(data.get('algorithm'), str): draft['algorithm'] = data['algorithm'][:2000]
    draft.update(status='candidate-unvalidated', martini_version='3',
                 source_structure=(context.get('path') if context else 'results/MMFF/lig1.pdb'), created_at=datetime.now(timezone.utc).isoformat(),
                 parent=data.get('file') if data.get('file') in candidate_paths() else None,
                 validation=validation)
    duplicate = _identical_mapping(draft, exclude=data.get('file') if in_place else None)
    if duplicate:
        raise DuplicateMapping(duplicate)
    storage_root().mkdir(parents=True, exist_ok=True)
    if in_place:
        # Overwrite the named candidate rather than minting a new one. The file keeps its identity and
        # only its content changes, so bonded states fitted for the old content stop matching it --
        # which is why the button warns before offering this.
        filename = data.get('file')
        if not filename or not (storage_root() / filename).is_file():
            raise ValueError('In-place save needs an existing candidate to overwrite')
        _repository().write(filename, draft, replace=True)
        return get(filename, context=context)
    filename = f'mapping_candidate_{uuid.uuid4().hex}.json'
    _repository().write(filename, draft, replace=False)
    path = storage_root() / filename
    return get(path.name, context=context)


def _identical_mapping(draft, exclude=None):
    """The saved mapping whose content this draft already is, or None.

    One identity per assignment: two saved mappings with the same beads, rings and connections are one model saved twice,
    and the catalogue, the parameterization address and the run's `composition_id` all treat that content as one thing.
    A second copy therefore makes the store answer two names for one model, which is what this refuses -- naming the
    mapping to open instead.

    `exclude` is the file being overwritten by an in-place save. Its own content is not a duplicate of itself, and a
    rename that changes only the name has to stay possible: the content, not the file, is what this compares.
    """
    content = content_identity(draft)
    for name in _content_holders(content):
        if name != exclude:
            return name
    return None


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
    """Remove one saved draft, and the bond interactions only it carried.

    The name goes through the validator the rest of the store uses and the path through
    the repository's containment check, so a name that escapes the drafts root is refused
    here rather than by a route-level pattern.

    The owner's rule is that deleting a mapping deletes its bond interactions, and the store's own
    doctrine makes that a question rather than a cascade: a parameterization is keyed by the mapping's
    *content* identity, which a copy saved under another name shares. So the identity is read off the
    draft before the file goes -- afterwards the draft can no longer say which model it was -- and the
    parameterization is forgotten only if nothing else still holds that content (`_forget_parameterization`).
    """
    path = _repository().path(name)
    if not path.is_file():
        raise KeyError(name)
    content = _draft_content_identity(path)
    path.unlink()
    return {'deleted': name, 'parameterization': _forget_parameterization(content, name)}


def _draft_content_identity(path):
    """The content identity the store stamps on a candidate it reads, for a draft that is about to go.

    `_read_candidate` computes exactly this (`content_identity`, the name blanked), but it is repeated
    here rather than called: reading through `get` also runs the graph validation against the packaged
    molecule, so a draft of another molecule would answer an error about a file this store is deleting
    either way. An unreadable draft answers None -- nothing addresses its bond interactions, so nothing
    is removed and the report says so.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return content_identity(data)
    except (TypeError, ValueError):
        return None


def _content_holders(content):
    """Every mapping still on disk -- packaged or drafted -- whose content identity is this one.

    `list_candidates` is deliberately not used: it validates each candidate against the packaged
    molecule's structure, so a draft of another molecule comes back as an error line with no hash and
    would look like a non-holder. The identity is a pure function of the file's own fields, which is
    all this decision needs and all it may ask.
    """
    holders = []
    for name, path in candidate_paths().items():
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            if content_identity(data) == content:
                holders.append(name)
        except (TypeError, ValueError):
            continue
    return sorted(holders)


def _forget_parameterization(content, name=None):
    """Delete the parameterization of `content` unless another saved mapping still carries it.

    The guard is the whole decision. Two saved drafts can hold identical content -- a copy under
    another name -- and therefore one content hash and one set of revisions; deleting either one must
    not destroy the other's bond interactions. So the record is removed only when no remaining mapping
    carries that content, and when one does the answer names the holders and says why it was kept.
    """
    if content is None:
        return {'content_hash': None, 'deleted': False, 'retained_by': [], 'revisions': [],
                'jobs': [], 'work': [],
                'reason': 'the draft could not be read, so no content identity addresses its bond interactions'}
    # Imported here and not at module scope: `bonded.parameterization` imports this package, and this
    # module is imported while the package is still initialising.
    from ..bonded import parameterization
    # The record's own claim list is the authority: this draft drops its claim, and the revisions go when the last one
    # does. A record written before claims existed has none to drop, and for that case the drafts on disk are asked.
    outcome = parameterization.release(content, name=name)
    if outcome.get('deleted') or outcome.get('released'):
        return {**outcome, 'retained_by': outcome.get('owners', []), 'reason': None}
    holders = _content_holders(content)
    if holders:
        return {'content_hash': content, 'deleted': False, 'retained_by': holders, 'revisions': [],
                'jobs': [], 'work': [],
                'reason': 'another saved mapping still carries this content'}
    return {**parameterization.delete(content), 'retained_by': [], 'reason': None}
