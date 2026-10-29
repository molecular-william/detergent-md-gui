"""Which distribution owns a test module: `core`, `validation` or `pdc`.

`areas.py` answers "what subject", so `-m pdc` or `-m osmotic` can run a slice of the suite. This table answers a
second question: which module is being changed. A test of a panel's behaviour belongs to the distribution that ships
the panel, even when it drives it through the engine's browser harness; an engine test that merely imports a feature
to prove a contract (discovery, code fingerprint, a run type matrix) stays `core`.

The split is a table rather than a heuristic on imports, because imports lie in both directions: every browser test
opens a server with all features installed but may import none of them, and an engine contract test imports both
features without being owned by either. `unit/test_test_modules.py` checks that every pattern matches a real module
and that no module is claimed twice; `tests/dashboard/unit/test_test_areas.py` still owns the subject axis.

Run one module's tests with `scripts/test_module.sh <core|validation|pdc> [fast|browser|slow]`.
"""
import fnmatch
from pathlib import Path

from .areas import TESTS_ROOT

#: Paths (inside `tests/dashboard`) owned by a feature. An unlisted module is `core`.
VALIDATION = (
    # The osmotic series: adapter, box/MDP, series runner, catalogue API, panel.
    'unit/test_osmotic_*', 'integration/test_osmotic_*', 'browser/test_osmotic_*',
    # The comparison and validation analyses, and the panel APIs the feature serves.
    'browser/test_mapping_validation_browser.py',
    'unit/test_mapping_consistency*', 'integration/test_mapping_consistency*',
    'unit/test_transferability_reader.py', 'integration/test_transferability_api.py',
    'unit/test_transfer_free_energy.py',
    'unit/test_consistency_*', 'unit/test_overlap_analysis.py', 'unit/test_overlap_reader.py',
    'unit/test_draft_geometry.py', 'unit/test_sugar_ensemble.py',
    'unit/test_carbohydrate_geometry.py', 'unit/test_carbohydrate_validation_worker.py',
    'unit/test_carbohydrate_targets_registry.py',
)

PDC = (
    # The ten-stage pipeline, its scripts, placement science and the panels it ships.
    'unit/test_pdc_*', 'integration/test_pdc_*', 'browser/test_pdc_*',
    'unit/test_cg2at_fragment.py', 'unit/test_micelle_*', 'integration/test_micelle_api.py',
    'unit/test_detergent_cg.py',
    # Readers whose subject is the pdc layout or segmenter (the engine keeps the mechanism, the feature the data).
    'unit/test_run_segments.py', 'unit/test_stage_view_plan.py',
)

#: The table, in match order: a feature claims its paths, everything else is the engine.
MODULES = {'validation': VALIDATION, 'pdc': PDC}


def module_of(path):
    """The distribution a module's path belongs to; `core` when no feature claims it."""
    try:
        relative = Path(path).resolve().relative_to(TESTS_ROOT).as_posix()
    except (ValueError, OSError):
        return 'core'
    for name, patterns in MODULES.items():
        if any(fnmatch.fnmatch(relative, pattern) for pattern in patterns):
            return name
    return 'core'
