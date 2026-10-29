"""The ownership axis: which distribution's tests a module is, enforced rather than trusted.

`areas.py` answers "what subject"; `modules.py` answers "which module is being changed". Since the split the directory
states it: `packages/<module>/tests/**` is that distribution's. These tests hold that claim honest -- every test file
lives under exactly one tree, every collected item carries exactly that tree's marker, and the cases imports cannot
decide (a browser test that opens a pdc page without importing the package, an engine contract test that imports both
features) are still owned by the tree that holds them.
"""
from pathlib import Path

import pytest

from tests.harness import modules
from tests.harness.support import PROJECT_ROOT

MODULE_NAMES = ('core', 'validation', 'pdc')
TREES = {name: PROJECT_ROOT / 'packages' / name / 'tests' for name in MODULE_NAMES}
FILES = sorted(path for tree in TREES.values() for path in tree.rglob('test_*.py'))


def tree_of(path):
    resolved = Path(path).resolve()
    owners = [name for name, tree in TREES.items() if tree.resolve() in resolved.parents]
    assert len(owners) == 1, (str(resolved), owners)
    return owners[0]


def test_every_module_lives_in_exactly_one_tree():
    for path in FILES:
        tree_of(path)


def test_the_tree_decides_the_owner():
    for path in FILES:
        assert modules.module_of(path) == tree_of(path), path


def test_every_collected_item_carries_its_trees_marker(request):
    """The hook adds the mark; a file that bypassed it, or a marker from a stale table, would show here."""
    for item in request.session.items:
        owners = {name for name, tree in TREES.items() if tree.resolve() in Path(item.path).resolve().parents}
        marked = {marker.name for marker in item.iter_markers()} & set(MODULE_NAMES)
        assert marked == owners, (item.nodeid, marked, owners)


@pytest.mark.parametrize('path, owner', [
    # A feature panel driven through the engine's browser harness, importing no feature package.
    ('packages/pdc/tests/browser/test_pdc_new_run_browser.py', 'pdc'),
    ('packages/validation/tests/browser/test_osmotic_series_browser.py', 'validation'),
    # An engine API the feature serves.
    ('packages/validation/tests/integration/test_mapping_consistency_api.py', 'validation'),
    # Engine contract tests import both features to prove a contract; they are not owned by either.
    ('packages/core/tests/unit/test_features.py', 'core'),
    ('packages/core/tests/unit/test_analysis_signature.py', 'core'),
    # The engine's own reader, whose inputs are the feature's data.
    ('packages/core/tests/unit/test_run_layout.py', 'core'),
])
def test_the_ambiguous_cases_are_where_the_tree_says(path, owner):
    assert modules.module_of(PROJECT_ROOT / path) == owner
