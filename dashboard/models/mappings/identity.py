"""One candidate identity implementation.

The canonical-JSON sha256 idiom -- sort the keys, drop the spaces, hash the bytes -- was
written out in four modules in this tree: the schema's mapping identity, the molecule
context's snapshot hash, the reference index and the composition identity. So a change to
the separators or the key order in one of them silently made the hashes the others stored
mean something else, and a candidate's stored hash is what a saved draft, a bonded state
and a review record all point at.

Identity is versioned on purpose. Schema 3 and above bind a candidate to the molecule
source it was built for; schemas 1 and 2 keep the payload they were first hashed with,
because those drafts are already on disk with that hash and the hash is data.
"""
import hashlib
import json

#: The first schema whose payload binds a candidate to its molecule source.
IDENTITY_VERSION = 3

#: Schema 1 and 2 drafts were hashed before that binding existed and keep their digest.
LEGACY_IDENTITY_VERSION = 2


def canonical_json(payload):
    """The one serialization identities are computed from: sorted keys, no spaces."""
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)


def canonical_sha256(payload):
    """Deterministic 64-hex digest of a JSON-serializable value."""
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def binds_molecule(candidate):
    """Whether this document's schema version binds it to its molecule source."""
    try:
        version = int(candidate.get('schema_version') or 0)
    except (TypeError, ValueError):
        return False
    return version >= IDENTITY_VERSION


def numbers_as_values(value):
    """The same JSON with every integral float written as an integer, so `1.0` and `1` hash alike.

    A candidate is read out of JSON by a browser and posted back, and JavaScript has no integer type: a stored
    `1.0` returns as `1`. Hashing the two spellings differently gave one mapping two content identities -- the
    store's, computed from the file, and the fit's, computed from the posted snapshot -- so a fit's revision was
    filed under a hash no saved mapping addressed. The panel then read "no parameterization" for a mapping it had
    just fitted, and its job poll, which asks by the mapping's own hash, found no job and stopped at `queued`.

    This canonicalises the *value* rather than the one field that showed it up: `rings[].scale` is where it was
    found, and any other integral number in a candidate would have done the same. `1.15` is left alone, and so is
    `True`, which is not a number here however much Python's `bool` inherits from `int`.

    Only `candidate_identity` normalises. `canonical_sha256` is also used for digests of file content, snapshots and
    the reference index, where an integer and a float are different bytes on purpose.
    """
    if isinstance(value, dict):
        return {key: numbers_as_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [numbers_as_values(item) for item in value]
    if isinstance(value, float) and not isinstance(value, bool) and value.is_integer():
        return int(value)
    return value


def _candidate_payload(candidate):
    payload = {key: candidate.get(key) for key in ('name', 'beads', 'rings', 'connections')}
    if binds_molecule(candidate):
        payload.update(identity_version=IDENTITY_VERSION, molecule_id=candidate.get('molecule_id'),
                       molecule_snapshot=candidate.get('molecule_snapshot'))
    if 'representation_mode' in candidate:
        payload['representation_mode'] = candidate.get('representation_mode')
    return payload


def candidate_identity(candidate):
    """Stable identity for a candidate's bead assignments and bonded connectivity."""
    return canonical_sha256(numbers_as_values(_candidate_payload(candidate)))


def content_identity(candidate):
    """The candidate identity without the user-facing name."""
    return candidate_identity({**candidate, 'name': ''})


def legacy_candidate_identity(candidate):
    """The identity as it was computed before numbers were normalised.

    A record, state or review written before that change is keyed by this digest. Reads try it second so a document
    already on disk is still found; nothing writes with it.
    """
    return canonical_sha256(_candidate_payload(candidate))


def legacy_content_identity(candidate):
    """`legacy_candidate_identity` without the user-facing name."""
    return legacy_candidate_identity({**candidate, 'name': ''})
