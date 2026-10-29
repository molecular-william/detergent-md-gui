"""Which distribution owns a test module: `core`, `validation` or `pdc`.

`areas.py` answers "what subject", so `-m pdc` or `-m osmotic` can run a slice of the suite. This module answers a
second question: which module is being changed. Since the split, the directory is the claim -- a test under
`packages/<module>/tests` is that distribution's, and a file outside the three trees (the shared harness) is `core`.

The table that stood here before the move listed every feature-owned module by pattern. It is gone rather than kept
as a second source of truth: `test_test_modules.py` now checks the tree against the marker, so a test that lands in
the wrong directory fails instead of being silently re-owned.

Run one module's tests with `pytest packages/<module>/tests` or `scripts/test_module.sh <core|validation|pdc> [tier]`.
The `-m core|validation|pdc` markers stay as the alias, applied from this function by the collection hook.
"""
from pathlib import Path

MODULE_NAMES = ('core', 'validation', 'pdc')


def module_of(path):
    """The distribution a module's path belongs to; `core` when it is in none of the three trees."""
    parts = Path(path).resolve().parts
    for index in range(len(parts) - 3, 0, -1):
        if parts[index] == 'packages' and parts[index + 1] in MODULE_NAMES and parts[index + 2] == 'tests':
            return parts[index + 1]
    return 'core'
