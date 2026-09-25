"""Re-export shim: these moved to tests/dashboard/support.py. Import from there.

Kept for exactly one commit so its importing files can move over; see Task 7.3. The docstring that
belongs with fast_forward_source -- unprovisioned sources must skip, never fail, so a missing
vendor tree cannot masquerade as a defect -- is on the function in support.py.
"""
from tests.dashboard.support import FAST_FORWARD_ROOT, fast_forward_source

__all__ = ['FAST_FORWARD_ROOT', 'fast_forward_source']
