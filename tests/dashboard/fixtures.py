"""Re-export shim: the fixtures moved to tests/dashboard/support.py. Import from there.

Kept for exactly one commit so the importing files can move over in a single sweep; see Task 7.3.
"""
from tests.dashboard.support import PROJECT_ROOT, QuietHandler, physical_mapping

__all__ = ['PROJECT_ROOT', 'QuietHandler', 'physical_mapping']
