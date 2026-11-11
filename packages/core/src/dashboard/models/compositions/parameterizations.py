"""A saved composition's parameterization: the derived revision 0 and the hand-edited revisions above it.

A saved composition is immutable, and so are its four artifacts -- `models/compositions/__init__.py` hashes them
into the record and refuses a changed byte. Its **derived** model is therefore revision 0 and is never rewritten.
An edit of the bonded terms appends a revision here, seeded from that derived topology, and the store says which
revision is current. That is the same "revisions + one current" shape the mapping store keeps
(`models/bonded/parameterization.py`), keyed by the composition instead of a mapping because a composition has no
mapping content identity.

The record is one document beside the composition artifacts:

    workspace/compositions/parameterizations/<composition_id>.json

and holds the history, not the generated model: revision 0 lives in `compositions/<id>/composition.itp`, and each
revision above it holds the complete topology text a run stages plus the overrides that produced it. Applying an
edit to the *derived base* rather than to the previous revision keeps every revision independently readable and
makes removing an override return to the derived value.

Nothing here decides what a run consumes: the adapter resolves the revision a payload names, then this store's
current one, then revision 0 (`revision`). The panel's `Save in place` is `save` -- append and make current.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ... import files, paths
from .. import bonded
from ..bonded import PARAMETER_RANGES
from . import derived_parameterization, get, term_counts

#: The one engine a saved edit names. It is not a fit: the terms are a reader's numbers applied to the derived
#: topology, so the record says `composition-edit` rather than borrowing an engine name from the fitting store.
ENGINE = 'composition-edit'
#: What a revision was seeded from, in the record's own words.
BASE = 'derived-revision-0'
STATUS = 'candidate-unvalidated'
DIRECTORY = 'parameterizations'
#: The temperature `bonded.refine` asks for. Only its circular-harmonic branch reads it, and an edit never asks for
#: that model -- the record carries `torsion_model: legacy`, so the value is inert here.
REFINE_TEMPERATURE = 300.0


class StaleRevision(ValueError):
    """The record moved on since the caller read it. The route answers 409, not 400."""


def storage_root() -> Path:
    return paths.current().compositions / DIRECTORY


def record_path(composition_id) -> Path:
    return storage_root() / f'{composition_id}.json'


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _derived_sha(composition_id) -> str:
    return derived_parameterization(composition_id)['topology']['sha256']


def _derived(composition_id) -> dict:
    """Revision 0: the immutable derived model, read from the composition's own `.itp`."""
    row = derived_parameterization(composition_id)
    text = Path(row['topology']['path']).read_text()
    record = get(composition_id)
    return {'revision': 0, 'engine': 'composition-derivation', 'base': 'derived',
            'source': row['source'], 'head_molecule_id': row['head_molecule_id'],
            'topology': text, 'topology_sha256': row['topology']['sha256'],
            'beads': row['topology']['beads'], 'terms': row['topology']['terms'],
            'coordinates': row['coordinates'], 'overrides': [],
            'status': record.get('status', STATUS), 'scientifically_validated': False}


def _empty(composition_id, record=None) -> dict:
    record = record or get(composition_id)
    return {'composition_id': composition_id,
            'composition_identity': record.get('identity'),
            'composition_snapshot_sha256': record.get('snapshot_hash'),
            'base_sha256': _derived_sha(composition_id),
            'revision': 0, 'current': 0, 'revisions': []}


def _read(composition_id):
    """The stored document, or None when this composition has no saved revision yet.

    A document whose composition or base topology has changed is refused by name rather than read as another
    model's history: a composition is immutable, so a mismatch means a damaged or copied record.
    """
    path = record_path(composition_id)
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f'Unreadable composition parameterization record: {path.name}') from exc
    if not isinstance(document, dict) or document.get('composition_id') != composition_id:
        raise ValueError('Composition parameterization record belongs to another composition')
    if document.get('base_sha256') != _derived_sha(composition_id):
        raise ValueError('Composition parameterization was recorded against a different composition topology')
    if document.get('composition_snapshot_sha256') != get(composition_id).get('snapshot_hash'):
        raise ValueError('Composition parameterization was recorded for a different composition record')
    return document


def _normalise_overrides(overrides):
    """Check the shape of a complete override list at the trust boundary, before the bonded validators read it.

    A request is JSON from a browser or an API client: a missing key would otherwise leave as a 404/500, and a bead
    list would reach `bonded.validate` as something that is not a list of names. Values, sections, functions and
    ranges are still the bonded module's to judge; this only guarantees the shapes it reads.
    """
    if not isinstance(overrides, list) or len(overrides) > 300:
        raise ValueError('overrides must be a list of at most 300 terms')
    normalised = []
    for item in overrides:
        if not isinstance(item, dict) or set(item) != {'section', 'beads', 'function', 'parameters'}:
            raise ValueError('Each override needs section, beads, function and parameters')
        section, beads = item['section'], item['beads']
        if not isinstance(section, str) or not section:
            raise ValueError('Each override needs a section name')
        if (not isinstance(beads, list) or not 1 < len(beads) <= 4
                or not all(isinstance(bead, str) and bead for bead in beads)):
            raise ValueError('Each override needs its bead names')
        function = item['function']
        if isinstance(function, bool) or not isinstance(function, int):
            raise ValueError('Each override needs an integer function')
        if not isinstance(item['parameters'], list):
            raise ValueError('Each override needs a parameter list')
        normalised.append({'section': section, 'beads': list(beads), 'function': function,
                           'parameters': list(item['parameters'])})
    return normalised


def _apply(record, derived, overrides):
    """Rewrite the derived topology's flexible terms from `overrides`, through the shared validator and writer."""
    mapping = (record.get('snapshot') or {}).get('mapping') or {}
    data = {'beads': mapping.get('beads') or [], 'rings': [],
            'bonded_overrides': overrides, 'bonded_options': {'torsion_model': 'legacy'}}
    # The bonded module owns the ranges, the physical-bead rule and the ring-constraint refusal, so this store
    # restates none of them. It also collapses a multi-line interaction to one term, which is why an override of a
    # multi-term topology refuses below rather than rewriting each line.
    bonded.validate(data)
    return bonded.refine(derived['topology'], data, None, REFINE_TEMPERATURE)[0]


def save(composition_id, payload, *, expected_revision=None) -> dict:
    """Append a revision built from the payload's overrides and make it current.

    `expected_revision` is the optimistic check the panel needs: two readers editing the same shown revision must
    not silently replace each other, so a record that moved on raises `StaleRevision` and the route answers 409.
    `payload` carries `overrides` -- the complete list the table shows as changed -- keyed by `(section, beads)`.
    """
    if not isinstance(payload, dict):
        raise ValueError('A composition parameterization revision must be an object')
    overrides = _normalise_overrides(payload.get('overrides', []))
    record = get(composition_id)
    document = _read(composition_id) or _empty(composition_id, record)
    if expected_revision is not None:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError('expected_revision must be an integer')
        if expected_revision != document['current']:
            raise StaleRevision('This composition parameterization changed; reload it before saving')
    derived = _derived(composition_id)
    topology = _apply(record, derived, overrides)
    beads, terms = term_counts(topology)
    revision = document['revision'] + 1
    item = {'revision': revision, 'created_at': files.now_iso(), 'engine': ENGINE, 'base': BASE,
            'base_sha256': document['base_sha256'], 'overrides': overrides,
            'topology': topology, 'topology_sha256': _sha256_text(topology),
            'beads': beads, 'terms': terms,
            'status': STATUS, 'scientifically_validated': False}
    document['revisions'].append(item)
    document.update(revision=revision, current=revision, updated_at=files.now_iso())
    files.atomic_json(record_path(composition_id), document)
    return item


def revision(composition_id, wanted=None) -> dict:
    """One revision of a composition's parameterization; `None` is the current one, and 0 is the derived model.

    A named revision that the record does not hold is refused rather than falling back to current: a run that
    asked for revision 3 and got revision 1 would simulate a model nobody chose.
    """
    document = _read(composition_id)
    if wanted is None:
        wanted = (document or {}).get('current') or 0
    if isinstance(wanted, bool) or not isinstance(wanted, int) or wanted < 0:
        raise ValueError('composition_revision must be a non-negative integer')
    if wanted == 0:
        return _derived(composition_id)
    for item in (document or {}).get('revisions') or []:
        if item.get('revision') == wanted:
            if item.get('base_sha256') != _derived_sha(composition_id):
                raise ValueError(f'Composition parameterization revision {wanted} was seeded from a different '
                                 'composition topology')
            return item
    raise ValueError(f'Unknown composition parameterization revision: {wanted}')


def descriptor(composition_id) -> dict:
    """The current model in the CG catalog's row shape, so the catalogue, the panel and a run agree."""
    row = derived_parameterization(composition_id)
    item = revision(composition_id, (_read(composition_id) or {}).get('current') or 0)
    if item['revision'] == 0:
        return {**row, 'base': 'derived', 'source': item['source'], 'head_molecule_id': item['head_molecule_id'],
                'status': item['status'], 'scientifically_validated': False}
    return {'kind': 'composition', 'revision': item['revision'], 'engine': ENGINE, 'base': 'edited',
            'source': item['source'] if item.get('source') else row['source'],
            'head_molecule_id': row['head_molecule_id'],
            'topology': {'sha256': item['topology_sha256'], 'beads': item['beads'], 'terms': item['terms']},
            'coordinates': row['coordinates'],
            'status': item['status'], 'scientifically_validated': False}


def _term_rows(item) -> list:
    """The revision's interactions, in the Bond Interactions table's shape, with the edit visible in `source`."""
    from ..bonded import parse_interactions
    rows = parse_interactions(item['topology'])
    edited = {(term['section'], frozenset(term['beads'])) for term in item.get('overrides') or []}
    for row in rows:
        # A virtual site is not a flexible term: `parse_interactions` only tags the flexible sections, so the
        # read-only defaults are stated here rather than left for the panel to guess.
        row.setdefault('editable', False)
        row.setdefault('function_options', [])
        row.setdefault('parameter_labels', [])
        row['source'] = 'manual' if (row['kind'], frozenset(row['beads'])) in edited else 'composition-derivation'
    return rows


def view(composition_id) -> dict:
    """Everything the terms card reads: history, the current topology text, and the current revision's rows."""
    record = get(composition_id)
    document = _read(composition_id)
    derived = _derived(composition_id)
    current = revision(composition_id, (document or {}).get('current') or 0)
    return {'composition_id': composition_id,
            'composition_identity': record.get('identity'),
            'composition_snapshot_sha256': record.get('snapshot_hash'),
            'current': current['revision'], 'revision': current['revision'],
            'edited': bool(document and document.get('revisions')),
            'derived': {key: derived[key] for key in
                        ('revision', 'engine', 'base', 'topology', 'topology_sha256', 'beads', 'terms',
                         'coordinates', 'source')},
            'current_parameterization': {**{key: current[key] for key in
                                             ('revision', 'engine', 'topology', 'topology_sha256',
                                              'beads', 'terms')},
                                         # `base` is the display state a panel prints; the stored `base` on a
                                         # revision is what it was seeded from, which is the manifest's word.
                                         'base': 'derived' if current['revision'] == 0 else 'edited',
                                         'seed': current.get('base')},
            'revisions': list((document or {}).get('revisions') or []),
            'terms': _term_rows(current),
            # The one range table, from the module that owns it; the panel restates no number.
            'ranges': PARAMETER_RANGES}