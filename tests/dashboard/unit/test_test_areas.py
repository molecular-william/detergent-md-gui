"""Every test module belongs to exactly one area, so a subset run is the whole of that area.

The areas exist so the suite can be asked a narrower question than "all of it" -- `-m pdc` while changing a build stage,
`-m mapping` while changing the bead editor. That is only trustworthy if the table in `tests/dashboard/areas.py` covers
the tree: a module no pattern names would run in the full suite and in no subset, which is how a category quietly stops
being a category. So a new test file fails here until it is given an area, and the count assertion below is what makes
"the subsets add up to the suite" checkable rather than assumed.
"""
import fnmatch

from tests.dashboard import areas
from tests.dashboard.areas import TESTS_ROOT


def modules():
    return sorted(path.relative_to(TESTS_ROOT).as_posix() for path in TESTS_ROOT.rglob('test_*.py'))


def test_every_module_is_named_by_one_area():
    unnamed = [module for module in modules() if areas.area_of(TESTS_ROOT / module) is None]

    assert unnamed == [], 'give each of these an area in tests/dashboard/areas.py'


def test_the_areas_cover_the_tree_without_a_module_in_two():
    """First match wins, and the first match is the only one: a module claimed twice is a table mistake, not a choice."""
    doubled = {}
    for module in modules():
        hits = [name for name, patterns in areas.AREAS.items()
                if any(fnmatch.fnmatch(module, pattern) for pattern in patterns)]
        if len(hits) > 1:
            doubled[module] = hits

    assert doubled == {}, str(doubled)


def test_every_area_has_modules():
    """An area with no module is a category that runs nothing -- the name would answer `no tests ran`."""
    empty = [name for name, patterns in areas.AREAS.items()
             if not any(any(fnmatch.fnmatch(module, pattern) for pattern in patterns) for module in modules())]

    assert empty == [], f'areas with no module: {empty}'


def test_the_narrow_name_wins_over_the_broad_one():
    """`test_cg_mapping_script.py` is mapping work and `test_cg_models.py` a parameterization; the adapter is `runs`."""
    assert areas.area_of(TESTS_ROOT / 'unit/test_cg_mapping_script.py') == 'mapping'
    assert areas.area_of(TESTS_ROOT / 'unit/test_cg_models.py') == 'bonded'
    assert areas.area_of(TESTS_ROOT / 'unit/test_cg_adapter_molecule_scoped.py') == 'runs'


def test_a_module_outside_the_tree_has_no_area():
    assert areas.area_of(TESTS_ROOT / '../../setup.py') is None
