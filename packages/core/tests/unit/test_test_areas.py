"""Every test module belongs to exactly one area, so a subset run is the whole of that area.

The areas exist so the suite can be asked a narrower question than "all of it" -- `-m pdc` while changing a build stage,
`-m mapping` while changing the bead editor. That is only trustworthy if the table in `tests/harness/areas.py` covers
every tree: a module no pattern names would run in the full suite and in no subset, which is how a category quietly
stops being a category. Patterns are matched from each tree's tier directory (`unit/...`), so one table serves
`packages/core/tests` and the feature trees alike.
"""
import fnmatch

from tests.harness import areas
from tests.harness.support import PROJECT_ROOT

TREES = {name: PROJECT_ROOT / 'packages' / name / 'tests' for name in ('core', 'validation', 'pdc')}
FILES = sorted(path for tree in TREES.values() for path in tree.rglob('test_*.py'))


def shapes():
    """Each module once per distinct path shape: both trees can hold a `unit/test_pdc_build_band.py`."""
    return sorted({areas.tree_relative(path) for path in FILES})


def test_every_module_is_named_by_one_area():
    unnamed = [str(path.relative_to(PROJECT_ROOT)) for path in FILES if areas.area_of(path) is None]

    assert unnamed == [], 'give each of these an area in tests/harness/areas.py'


def test_the_areas_cover_the_tree_without_a_module_in_two():
    """First match wins, and the first match is the only one: a module claimed twice is a table mistake, not a choice."""
    doubled = {}
    for shape in shapes():
        hits = [name for name, patterns in areas.AREAS.items()
                if any(fnmatch.fnmatch(shape, pattern) for pattern in patterns)]
        if len(hits) > 1:
            doubled[shape] = hits

    assert doubled == {}, str(doubled)



def test_every_pattern_names_a_module():
    """A pattern that matches nothing is dead weight: the module it was written for was renamed or removed."""
    present = shapes()
    dead = [(name, pattern) for name, patterns in areas.AREAS.items() for pattern in patterns
            if not any(fnmatch.fnmatch(shape, pattern) for shape in present)]

    assert dead == [], f'patterns with no module: {dead}'


def test_the_narrow_name_wins_over_the_broad_one():
    """`test_cg_mapping_script.py` is mapping work and `test_cg_models.py` a parameterization; the adapter is `runs`."""
    unit = TREES['core'] / 'unit'
    assert areas.area_of(unit / 'test_cg_mapping_script.py') == 'mapping'
    assert areas.area_of(unit / 'test_cg_models.py') == 'bonded'
    assert areas.area_of(unit / 'test_cg_adapter_molecule_scoped.py') == 'runs'

