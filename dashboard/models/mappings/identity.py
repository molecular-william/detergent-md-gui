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


def candidate_identity(candidate):
    """Stable identity for a candidate's bead assignments and bonded connectivity."""
    payload = {key: candidate.get(key) for key in ('name', 'beads', 'rings', 'connections')}
    if binds_molecule(candidate):
        payload.update(identity_version=IDENTITY_VERSION, molecule_id=candidate.get('molecule_id'),
                       molecule_snapshot=candidate.get('molecule_snapshot'))
    if 'representation_mode' in candidate:
        payload['representation_mode'] = candidate.get('representation_mode')
    return canonical_sha256(payload)


def content_identity(candidate):
    """The candidate identity without the user-facing name."""
    return candidate_identity({**candidate, 'name': ''})
