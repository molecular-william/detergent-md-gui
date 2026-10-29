"""One candidate identity implementation.

The canonical-JSON sha256 idiom -- sort the keys, drop the spaces, hash the bytes -- was
written out in four modules in this tree: the schema's mapping identity, the molecule
context's snapshot hash, the reference index and the composition identity. Identity is
data: a change to the separators in one of them silently makes the hashes the others
stored mean something else, and a candidate's stored hash is what a saved draft, a bonded
state and a review record all point at.

These pin the one implementation, the versioning rule (schema 3 and above bind the
candidate to its molecule source; earlier drafts keep the payload they were first hashed
with) and the historical digests of documents that are already on disk.
"""
import ast
import json

from dashboard.models.compositions import topology
from dashboard.models.mappings import identity

from tests.harness.support import PACKAGE

LEGACY_V2 = {'schema_version': 2, 'name': 'legacy',
             'beads': [{'name': 'A', 'size': 'R', 'type': 'P1', 'atoms': [1]}],
             'rings': [], 'connections': []}
BOUND_V3 = {**LEGACY_V2, 'schema_version': 3, 'molecule_id': 'DDM',
            'molecule_snapshot': {'snapshot_sha256': 'x'}}
# Captured from the implementation this one replaces, before it moved.
V2_IDENTITY = '9b687ef22a6f2719c874619129dbd58f1f7b6e3adca9d0d71a07b4af14fa808e'
V2_CONTENT = '36df01e018007cbc9ca837a28c6e6e1c40cdc42ea8663c89299abf2724fb6b6f'
V3_IDENTITY = 'a486b49df646f76e80914e36b2df71441c85122b274a1128f3f8ab3ee9acb88b'
MODELS = PACKAGE / 'models'


def test_a_candidate_that_differs_only_in_molecule_id_hashes_differently():
    """Schema 3 and above, not schema 3 only: a later schema must not lose the binding."""
    for version in (3, 4):
        bound = {**BOUND_V3, 'schema_version': version}
        other = {**bound, 'molecule_id': 'DPPC'}
        assert identity.candidate_identity(bound) != identity.candidate_identity(other), version


def test_documents_already_on_disk_keep_their_digest():
    """The stored hash is what a saved draft points at, so the move may not renumber it."""
    assert identity.candidate_identity(LEGACY_V2) == V2_IDENTITY
    assert identity.content_identity(LEGACY_V2) == V2_CONTENT
    assert identity.candidate_identity(BOUND_V3) == V3_IDENTITY


def test_identical_content_hashes_equal():
    copy = json.loads(json.dumps(LEGACY_V2))
    assert identity.candidate_identity(copy) == identity.candidate_identity(LEGACY_V2)
    assert identity.content_identity({**LEGACY_V2, 'name': 'renamed'}) == identity.content_identity(LEGACY_V2)
    assert identity.candidate_identity(LEGACY_V2) != identity.content_identity(LEGACY_V2)


def test_every_identity_in_the_mapping_cluster_is_a_sha256():
    composition = topology.composition_identity({})
    for value in (identity.canonical_sha256({'a': 1}), identity.candidate_identity(LEGACY_V2),
                  identity.content_identity(LEGACY_V2), composition):
        assert len(value) == 64 and set(value) <= set('0123456789abcdef')


def test_the_compact_json_digest_lives_in_one_module():
    """A second `sha256(json.dumps(..., separators=(',', ':')))` is how the two drift apart.

    Only the models tree is scanned: the ETag and revision digests in the web and analysis
    layers use the default separators on purpose and are not candidate identities.
    """
    offenders = []
    for path in sorted(MODELS.rglob('*.py')):
        if path.name == 'identity.py' or 'checkpoints' in str(path):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == 'sha256' and _compact_dumps(node):
                offenders.append(f'{path}:{node.lineno}')
    assert not offenders, 'compute identities in identity.py: ' + ', '.join(offenders)


def _compact_dumps(node):
    dumps = next((child for child in ast.walk(node) if isinstance(child, ast.Call)
                  and isinstance(child.func, ast.Attribute) and child.func.attr == 'dumps'), None)
    if dumps is None:
        return False
    return any(keyword.arg == 'separators' and ast.literal_eval(keyword.value) == (',', ':')
               for keyword in dumps.keywords)


def test_a_number_is_hashed_as_its_value_and_not_as_the_text_a_writer_chose():
    """`1.0` and `1` are the same number, and a browser posts the second one whatever the file said.

    The panel reads a mapping as JSON, hands it to JavaScript and posts it back; JS has no integer type, so a stored
    ring scale of `1.0` returns as `1`. Hashing the spellings differently gave one mapping two content identities --
    and a fit filed under the digest the file never produced.
    """
    floaty = {**BOUND_V3, 'rings': [{'name': 'R1', 'atoms': [1, 2, 3], 'scale': 1.0}]}
    integral = {**BOUND_V3, 'rings': [{'name': 'R1', 'atoms': [1, 2, 3], 'scale': 1}]}

    assert identity.candidate_identity(floaty) == identity.candidate_identity(integral)
    assert identity.content_identity(floaty) == identity.content_identity(integral)
    # The legacy digest is what a record on disk still carries, and it is the one that differs.
    assert identity.legacy_candidate_identity(floaty) != identity.legacy_candidate_identity(integral)

    # A number that is not integral is left alone, and a boolean is not a number here.
    assert identity.candidate_identity({**BOUND_V3, 'rings': [{'scale': 1.15}]}) != \
        identity.candidate_identity({**BOUND_V3, 'rings': [{'scale': 1}]})
    assert identity.numbers_as_values({'a': True, 'b': 1.0, 'c': [2.5, 3.0]}) == \
        {'a': True, 'b': 1, 'c': [2.5, 3]}
