"""The stored library: schema, key derivation, canonical bytes, sidecar, store layout and the listing.

A library is a pinned input, so these tests pin the things a pin rests on: the bytes are a pure function of the
sources and the selection (rebuilding the same sources writes the same file), the sidecar is the file's own digest,
a copied directory is accepted and a changed one is refused, and a valid copy is never replaced under a key a run
may have recorded.
"""
import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from detergent_pdc.conformations import (
    DEFAULT_SIZE,
    DESCRIPTORS,
    FORMAT,
    MAX_SIZE,
    METHOD,
    available,
    build,
    canonical_bytes,
    key_for,
    key_of_document,
    load,
    normalise_spec,
    resolve,
    store,
    store_dir,
    store_root,
    verify,
)

from tests.harness.conformation_fixtures import copy_libraries, run_tree

RUN = 'b920391735dd'


def built(tmp_path, **spec):
    workspace = tmp_path / 'workspace'
    run_tree(workspace, RUN, molecules=4, frames=2)
    settings = {'runs': [RUN], 'size': 3, 'seed': 0, **spec}
    library, _record = build(workspace, settings)
    return workspace, library


def test_spec_spellings():
    assert normalise_spec(None) is None
    assert normalise_spec({'runs': ['a']}) == {'mode': 'build', 'runs': ['a'], 'size': DEFAULT_SIZE, 'seed': 0}
    assert normalise_spec(normalise_spec({'runs': ['a'], 'size': 2, 'seed': 5}))['seed'] == 5
    reference = normalise_spec({'key': 'ab' * 8, 'sha256': 'CD' * 32})
    assert reference == {'mode': 'reference', 'key': 'ab' * 8, 'sha256': 'cd' * 32}
    assert normalise_spec(reference) == reference


def test_a_bad_spec_names_what_is_wrong():
    for spec, sentence in (
        ({'runs': ['a'], 'key': 'ab' * 8, 'sha256': 'cd' * 32}, 'either runs'),
        ({'runs': ['a'], 'size': 0}, 'size must be between'),
        ({'runs': ['a'], 'size': MAX_SIZE + 1}, 'size must be between'),
        ({'runs': ['a'], 'seed': 'zero'}, 'seed must be an integer'),
        ({'runs': [], 'size': 1}, 'at least one'),
        ({'runs': 'a,b'}, 'must be a list'),
        ({'runs': ['a'], 'extra': 1}, 'not extra'),
        ({'key': 'ab' * 8}, 'both key and sha256'),
        ({'key': 'xy' * 8, 'sha256': 'cd' * 32}, 'key must be 16 hexadecimal'),
        ({'key': 'ab' * 8, 'sha256': 'zz' * 32}, 'sha256 must be 64 hexadecimal'),
        ('runs', 'not'),
    ):
        with pytest.raises(ValueError) as error:
            normalise_spec(spec)
        assert sentence in str(error.value), (spec, str(error.value))


def test_key_is_independent_of_run_order_and_of_the_seed(tmp_path):
    workspace = tmp_path / 'workspace'
    run_tree(workspace, 'one', molecules=2, frames=1)
    run_tree(workspace, 'two', molecules=2, frames=1)
    assert key_for(workspace, {'runs': ['one', 'two'], 'size': 2}) == \
        key_for(workspace, {'runs': ['two', 'one'], 'size': 2})
    assert key_for(workspace, {'runs': ['one'], 'size': 2, 'seed': 0}) != \
        key_for(workspace, {'runs': ['one'], 'size': 2, 'seed': 1})
    assert key_for(workspace, {'runs': ['one'], 'size': 2}) != key_for(workspace, {'runs': ['one'], 'size': 3})
    library, _record = build(workspace, {'runs': ['one'], 'size': 2})
    assert key_for(workspace, {'key': library.key, 'sha256': library.sha256}) == library.key


def test_document_schema_and_canonical_order(tmp_path):
    _workspace, library = built(tmp_path)
    document = library.document
    assert document['format'] == FORMAT
    assert document['detergent']['residue'] == 'DDM'
    assert document['detergent']['mapping_sha256']
    assert document['selection'] == {'size': 3, 'seed': 0, 'method': METHOD, 'descriptors': list(DESCRIPTORS)}
    assert document['pool'] == 8 and len(document['entries']) == 3
    assert [entry['source'] for entry in document['entries']] == sorted(
        (entry['source'] for entry in document['entries']),
        key=lambda source: (source['run'], source['time_ns'], source['resid']))
    assert document['sources'][0]['run_id'] == RUN
    assert document['sources'][0]['frames'] == 2 and document['sources'][0]['pool'] == 8
    assert document['sources'][0]['stride'] == 1
    assert document['sources'][0]['protein'] is False
    assert document['sources'][0]['trajectory'] == '06_assessment/prod/whole.xtc'
    for entry in document['entries']:
        assert len(entry['beads']) == 11 and len(entry['descriptors']) == 4
        assert all(value == round(value, 4) for point in entry['beads'] for value in point)
        assert all(value == round(value, 6) for value in entry['descriptors'])
        assert all(point[2] <= 0.0 for point in entry['beads'])
        assert entry['source']['time_ns'] == round(entry['source']['time_ns'], 6)
    assert key_of_document(document) == library.key


def test_canonical_bytes_are_a_pure_function_of_the_sources(tmp_path):
    workspace, library = built(tmp_path)
    first = library.path.read_bytes()
    assert first == canonical_bytes(library.document)
    assert first.endswith(b'\n') and b'\n' not in first[:-1]
    shutil.rmtree(library.path.parent)
    again = resolve(workspace, {'runs': [RUN], 'size': 3, 'seed': 0})
    assert again.key == library.key
    assert again.path.read_bytes() == first
    assert again.sha256 == hashlib.sha256(first).hexdigest()


def test_sidecar_is_the_file_digest(tmp_path):
    _workspace, library = built(tmp_path)
    sidecar = library.path.parent / 'library.sha256'
    assert sidecar.read_text() == library.sha256 + '\n'
    assert library.sha256 == hashlib.sha256(library.path.read_bytes()).hexdigest()


def test_load_round_trip(tmp_path):
    _workspace, library = built(tmp_path)
    loaded = load(library.path)
    assert loaded.key == library.key and loaded.sha256 == library.sha256
    assert loaded.residue == 'DDM' and loaded.size == 3 and len(loaded.entries) == 3
    offsets = loaded.offsets()
    assert offsets.shape == (3, 11, 3) and offsets.dtype == np.float64
    assert np.isfinite(offsets).all()
    conformations = loaded.conformations()
    assert conformations.key == library.key and conformations.size == 3
    assert len(conformations.profiles) == 3
    for profile in conformations.profiles:
        assert profile['axis'] == [0.0, 0.0, 1.0]
        assert profile['bead_count'] == 11
        assert profile['source'] == 'conformations' and profile['head_source'] == 'library'
        assert profile['offsets'].shape == (11, 3)
        assert profile['length_nm'] == pytest.approx(-profile['offsets'][:, 2].min(), abs=2e-4)
    assert load(library.path.parent).key == library.key


def test_assert_matches_names_the_difference(tmp_path):
    _workspace, library = built(tmp_path)
    library.assert_matches(residue='DDM', beads=library.beads, mapping_sha256=library.mapping_sha256)
    with pytest.raises(ValueError) as error:
        library.assert_matches(residue='LIP', beads=library.beads, mapping_sha256=library.mapping_sha256)
    assert 'residue' in str(error.value) and 'LIP' in str(error.value)
    with pytest.raises(ValueError, match='11 beads'):
        library.assert_matches(residue='DDM', beads=library.beads[:-1], mapping_sha256=library.mapping_sha256)
    other = list(library.beads)
    other[2] = 'OTHER'
    with pytest.raises(ValueError) as error:
        library.assert_matches(residue='DDM', beads=other, mapping_sha256=library.mapping_sha256)
    assert "bead 3 is 'S1C'" in str(error.value) and 'OTHER' in str(error.value)
    with pytest.raises(ValueError, match='mapping'):
        library.assert_matches(residue='DDM', beads=library.beads, mapping_sha256='0' * 64)


def test_a_tampered_file_is_refused(tmp_path):
    _workspace, library = built(tmp_path)
    library.path.write_text(library.path.read_text().replace('"size":3', '"size":4'))
    with pytest.raises(ValueError) as error:
        verify(load(library.path))
    assert 'library.sha256 states' in str(error.value)


def test_available_lists_only_verified_libraries(tmp_path):
    workspace, library = built(tmp_path)
    listed = available(workspace)
    assert [entry['key'] for entry in listed] == [library.key]
    assert listed[0]['residue'] == 'DDM' and listed[0]['size'] == 3
    assert listed[0]['sources'] == [RUN]
    assert available(workspace, residue='LIP') == []

    second = tmp_path / 'second'
    copied = copy_libraries(workspace, second)
    assert [entry['key'] for entry in available(second)] == [library.key]
    assert copied[0] == store_dir(second, 'DDM', library.key)

    missing = tmp_path / 'missing'
    copy_libraries(workspace, missing)
    (store_dir(missing, 'DDM', library.key) / 'library.sha256').unlink()
    assert available(missing) == []

    wrong = tmp_path / 'wrong'
    copy_libraries(workspace, wrong)
    (store_dir(wrong, 'DDM', library.key) / 'library.sha256').write_text('0' * 64 + '\n')
    assert available(wrong) == []


def test_the_store_refuses_to_replace_a_valid_library(tmp_path):
    workspace, library = built(tmp_path)
    changed = {**library.document, 'pool': library.document['pool'] + 1}
    with pytest.raises(ValueError, match='refusing to replace'):
        store(workspace, library.residue, library.key, changed)
    assert load(library.path).sha256 == library.sha256


def test_two_callers_end_with_one_library(tmp_path):
    workspace = tmp_path / 'workspace'
    run_tree(workspace, RUN, molecules=4, frames=2)
    spec = {'runs': [RUN], 'size': 3, 'seed': 0}
    with ThreadPoolExecutor(max_workers=2) as pool:
        libraries = list(pool.map(lambda _call: resolve(workspace, spec), range(2)))
    assert {library.key for library in libraries} == {libraries[0].key}
    assert {library.sha256 for library in libraries} == {libraries[0].sha256}
    directory = libraries[0].path.parent
    assert sorted(path.name for path in directory.iterdir()) == ['library.json', 'library.sha256']
    assert json.loads((directory / 'library.json').read_text())['entries']
    assert store_root(workspace) == tmp_path / 'workspace' / 'conformations'
