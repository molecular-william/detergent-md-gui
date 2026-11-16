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

Version 3 names the molecule *version* rather than hashing its files. A molecule folder
that states a version directory is the change detector -- `molecules/<id>/<version>/` -- so
a candidate's binding is `{molecule_id, version}` and no file digest enters it. A draft
written before version directories names no version; its chemistry is then what names the
molecule, and its digest snapshot is still not hashed. The whole-snapshot payload the
previous version used survives in `legacy_candidate_identity`, for the migration CLI that
has to reproduce the digest a stored record carries.
"""
import hashlib

from ... import files

#: The first schema whose payload binds a candidate to its molecule source.
IDENTITY_VERSION = 3

#: The `identity_version` marker the whole-snapshot payload was hashed with. It stays 3 even when
#: `IDENTITY_VERSION` moves, so the old digest does not silently change: a stored record is data.
LEGACY_IDENTITY_VERSION = 3

#: The metadata fields that name a molecule's chemistry, as `analysis.runs.references.identity` reads them.
CHEMISTRY = ('force_field', 'water_model', 'molecule_type', 'net_charge')


def canonical_json(payload):
    """The one serialization identities are computed from -- `files.canonical_json`.

    This module used to restate the separators, beside a `files.json_sha256` that used different ones, so one document
    had two digests and only this one was ever compared. Delegating means there is nothing to keep in step.
    """
    return files.canonical_json(payload)


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

    Both identities normalise; `canonical_sha256` is also used for digests of file content, snapshots and the reference
    index, where an integer and a float are different bytes on purpose.
    """
    if isinstance(value, dict):
        return {key: numbers_as_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [numbers_as_values(item) for item in value]
    if isinstance(value, float) and not isinstance(value, bool) and value.is_integer():
        return int(value)
    return value


def _molecule_binding(candidate):
    """The molecule a candidate was built for: its id and the version directory it read.

    A named snapshot answers `{molecule_id, version}` and nothing else, so a file digest a document happens to carry
    beside the version cannot change an identity that names the same version. A draft read before its migration names
    no version: it gets `version: None` and the chemistry the reference identity also binds, because its files, not a
    version directory, were the only thing that identified it.
    """
    snapshot = candidate.get('molecule_snapshot')
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    molecule_id = candidate.get('molecule_id')
    if molecule_id is None:
        molecule_id = snapshot.get('molecule_id')
    version = snapshot.get('version')
    binding = {'molecule_id': molecule_id, 'version': version}
    if version is None:
        metadata = snapshot.get('metadata') if isinstance(snapshot.get('metadata'), dict) else {}
        binding['chemistry'] = {key: metadata.get(key) for key in CHEMISTRY if key in metadata}
    return binding


def _candidate_payload(candidate):
    payload = {key: candidate.get(key) for key in ('name', 'beads', 'rings', 'connections')}
    if binds_molecule(candidate):
        payload.update(identity_version=IDENTITY_VERSION, molecule=_molecule_binding(candidate))
    if 'representation_mode' in candidate:
        payload['representation_mode'] = candidate.get('representation_mode')
    return payload


def _legacy_candidate_payload(candidate):
    """The payload a stored v3 identity was hashed with: the whole molecule snapshot, digests included."""
    payload = {key: candidate.get(key) for key in ('name', 'beads', 'rings', 'connections')}
    if binds_molecule(candidate):
        payload.update(identity_version=LEGACY_IDENTITY_VERSION, molecule_id=candidate.get('molecule_id'),
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
    """The identity a candidate was stored under before its molecule version was named.

    A record or run row written before this payload changes is keyed by this digest, and the migration CLI needs it to
    recognise what it rewrites. Nothing writes with it.
    """
    return canonical_sha256(numbers_as_values(_legacy_candidate_payload(candidate)))


def legacy_content_identity(candidate):
    """`legacy_candidate_identity` without the user-facing name."""
    return legacy_candidate_identity({**candidate, 'name': ''})
