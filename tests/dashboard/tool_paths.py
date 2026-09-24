"""Locate vendored third-party sources; unprovisioned sources skip, never fail.

The Fast_Forward Python source tree under ``resources/parameterizers`` is not
part of this checkout. Tests that load it must resolve it through this module
and skip with a reason, so a missing vendor tree never masquerades as a defect
in the code under test.
"""
from pathlib import Path

from tests.dashboard.fixtures import PROJECT_ROOT

FAST_FORWARD_ROOT = PROJECT_ROOT / 'resources/parameterizers/fast_forward/fast_forward'


def fast_forward_source(*parts):
    """Return a Fast_Forward Python source file, or None when unprovisioned."""
    candidate = FAST_FORWARD_ROOT.joinpath(*parts)
    return candidate if candidate.is_file() else None
