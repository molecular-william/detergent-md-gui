"""`references.identity` reads the per-file map a molecule *selection* carries, in either spelling it is written in.

Two spellings exist -- `reference_sha256` (what `molecules/aa.py` writes) and the older `sha256` -- and one name is
shared with something that is not a map: a reference block states `reference_sha256` as a single digest. The reader
used an eager default (`snapshot.get('reference_sha256', snapshot['sha256'])`), so a selection carrying only the key
it asked for raised `KeyError('sha256')`, and the scalar raised `AttributeError` on `.items()`. Both are now answered:
the map is read from either spelling, and a scalar is refused with a sentence rather than an accident.
"""
import hashlib
import json

import pytest

from dashboard.analysis.runs import references

METADATA = {'force_field': 'charmm36-jul2022', 'water_model': 'tip3p', 'molecule_type': 'protein', 'net_charge': 0}
FILES = {'protein.pdb': '11' * 32, 'metadata.json': '22' * 32}


def expected(digests):
    body = {'files': {k: v for k, v in digests.items() if k != 'metadata.json'},
            'chemistry': {k: METADATA[k] for k in ('force_field', 'water_model', 'molecule_type', 'net_charge')}}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def test_the_selection_spelling_is_read():
    assert references.identity({'metadata': METADATA, 'reference_sha256': FILES}) == expected(FILES)


def test_the_older_spelling_is_the_same_identity():
    """One map, two names: a record written before the rename must keep the identity it had."""
    assert references.identity({'metadata': METADATA, 'sha256': FILES}) == expected(FILES)


def test_metadata_json_is_not_part_of_the_identity():
    """It travels with the reference but describes the run, not the chemistry the mapping is measured against."""
    assert references.identity({'metadata': METADATA,
                                'reference_sha256': {'protein.pdb': FILES['protein.pdb']}}) == expected(
        {'protein.pdb': FILES['protein.pdb'], 'metadata.json': 'ignored'})


def test_a_single_digest_is_refused_by_name():
    """A reference block's `reference_sha256` is one digest; it is not this function's input, and says so."""
    with pytest.raises(ValueError) as refused:
        references.identity({'metadata': METADATA, 'reference_sha256': 'ab' * 32})

    assert 'per-file digests' in str(refused.value)
