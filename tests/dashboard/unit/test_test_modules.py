"""The ownership axis: which distribution's tests a module is, enforced rather than trusted.

`areas.py` answers "what subject"; `modules.py` answers "which module is being changed". These tests keep the second
table honest: every pattern must name a real module (a rename leaves no silent dangling claim), the three groups must
cover the suite, and the cases that imports cannot decide -- a browser test that opens a pdc page without importing
the package, an engine contract test that imports both features -- stay where the table says.
"""
import fnmatch
from pathlib import Path

import pytest

from tests.dashboard import modules

TESTS_ROOT = Path(__file__).resolve().parents[1]
FILES = sorted(TESTS_ROOT.rglob('test_*.py'))
MODULE_NAMES = ('core', 'validation', 'pdc')


def relative(path):
    return Path(path).resolve().relative_to(TESTS_ROOT).as_posix()


def test_every_pattern_names_a_real_module():
    for name, patterns in modules.MODULES.items():
        for pattern in patterns:
            assert any(fnmatch.fnmatch(relative(path), pattern) for path in FILES), (
                f'{name}: pattern {pattern!r} matches no test module -- a rename left a dangling claim')


def test_every_module_has_exactly_one_owner():
    for path in FILES:
        assert modules.module_of(path) in MODULE_NAMES, path


def test_the_three_groups_partition_the_suite():
    groups = {name: [] for name in MODULE_NAMES}
    for path in FILES:
        groups[modules.module_of(path)].append(path)
    assert set(groups) == set(MODULE_NAMES)
    assert sum(len(paths) for paths in groups.values()) == len(FILES), 'a module was counted twice'
    for name, paths in groups.items():
        assert paths, f'{name} owns no tests'


@pytest.mark.parametrize('path, owner', [
    # A feature panel driven through the engine's browser harness, importing no feature package.
    ('browser/test_pdc_new_run_browser.py', 'pdc'),
    ('browser/test_osmotic_series_browser.py', 'validation'),
    # An engine API the feature serves.
    ('integration/test_mapping_consistency_api.py', 'validation'),
    # Engine contract tests import both features to prove a contract; they are not owned by either.
    ('unit/test_features.py', 'core'),
    ('unit/test_analysis_signature.py', 'core'),
    # The engine's own reader, whose inputs are the feature's data.
    ('unit/test_run_layout.py', 'core'),
])
def test_the_ambiguous_cases_are_where_the_table_says(path, owner):
    assert modules.module_of(TESTS_ROOT / path) == owner


def test_this_module_is_marked_core(request):
    """The collection hook adds the mark from this table; a test file that bypasses it would show here."""
    marked = {marker.name for marker in request.node.own_markers} & set(MODULE_NAMES)
    assert marked == {'core'}, marked
