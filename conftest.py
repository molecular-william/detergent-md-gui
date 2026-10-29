"""Test-suite configuration shared by every test tree.

The fixtures, the collection hook and the browser/server fixtures live in `tests/harness/` so any test tree can use
them, and so they can move with the packages later. This file only makes the repository importable and registers them,
which is what makes the arrangement work whether pytest is started at the repository root or inside a package.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest_plugins = ('tests.harness.plugin', 'tests.harness.browser_plugin')
