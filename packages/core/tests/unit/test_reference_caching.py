"""The reference indexes are cached on their sources, not on time.

Both indexes hash and parse a corpus (the sugar reference ITPs, the small-molecule ITP, the
M3-Bible workbook, every bonded reference ITP) and both were built again on every request
and every generate. A stamp-keyed memo makes a repeat call free and makes a changed source
invalidate it -- an lru_cache keyed on nothing would serve a stale index after an edit.

The key is each source path with its mtime and size, which is what the plan asked for: it
is cheap (no hashing to decide whether to hash) and it sees every ordinary edit. An edit
that preserves both the size and the timestamp is not seen, which is true of any such key
and is why the tests change the size.
"""
from dashboard.models.bonded import generation
from dashboard.models.mappings import references


def reference_tree(root):
    """A minimal corpus: one sugar ITP the mapping index reads, one ITP the bonded walk reads."""
    (root / 'references').mkdir(parents=True, exist_ok=True)
    sugar = root / 'references' / 'martini_v3.0.0_sugars_v2.itp'
    sugar.write_text('[ moleculetype ]\nGL0 1\n\n[ atoms ]\n1 SP1 1 GL0 1 1 0 72\n')
    bonded = root / 'references' / 'martini_bonds.itp'
    bonded.write_text('[ bonds ]\nSP1 SP1 1 0.30 5000\n')
    return sugar


def test_the_mapping_index_is_built_once_and_rebuilt_when_a_source_changes(tmp_path, monkeypatch):
    sugar = reference_tree(tmp_path)
    builds = []
    monkeypatch.setattr(references, '_build_index', lambda root: builds.append(1) or {'records': [], 'sources': [], 'diagnostics': []})
    references._INDEX_CACHE.clear()
    references.load_index(tmp_path)
    references.load_index(tmp_path)
    assert len(builds) == 1, 'the second call is served from the memo'
    sugar.write_text(sugar.read_text() + '; edited\n')
    references.load_index(tmp_path)
    assert len(builds) == 2, 'a changed source invalidates the memo'


def test_the_bonded_index_is_built_once_and_rebuilt_when_a_source_changes(tmp_path, monkeypatch):
    reference_tree(tmp_path)
    builds = []
    monkeypatch.setattr(generation, '_build_bond_index', lambda root: builds.append(1) or {'bonds': {}, 'angles': {}, 'dihedrals': {}, 'diagnostics': []})
    generation._BOND_INDEX_CACHE.clear()
    generation.reference_bond_index(tmp_path)
    generation.reference_bond_index(tmp_path)
    assert len(builds) == 1
    (tmp_path / 'references' / 'martini_bonds.itp').write_text('[ bonds ]\nSP1 SP1 1 0.31 5000\n; longer\n')
    generation.reference_bond_index(tmp_path)
    assert len(builds) == 2


def test_a_cache_key_follows_the_file_not_the_clock(tmp_path):
    path = tmp_path / 'x.itp'
    path.write_text('a')
    first = references.files.stamp([path])
    assert references.files.stamp([path]) == first, 'an unchanged file keeps its stamp'
    path.write_text('ab')
    assert references.files.stamp([path]) != first, 'a rewrite changes it'
    assert references.files.stamp([tmp_path / 'missing.itp']) == (), 'a missing file contributes nothing'
