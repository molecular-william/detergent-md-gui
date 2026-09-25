"""Re-export shim: write_aa_fixture moved to tests/dashboard/support.py. Import from there.

Kept for exactly one commit so its importing file can move over; see Task 7.3.
"""
from tests.dashboard.support import write_aa_fixture

__all__ = ['write_aa_fixture']
