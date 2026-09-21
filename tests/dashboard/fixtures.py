"""Self-contained mapping inputs for tests; never depend on saved user drafts."""
from werkzeug.serving import WSGIRequestHandler
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
from dashboard.models import mappings


def physical_mapping():
    """COG format fixture without virtual sites, for the basic FF mapper tests."""
    generated=mappings.automatic_candidate(mappings.molecule(), 'DDM')
    return {'name':'Physical COG format fixture','beads':[b for b in generated['beads'] if not b.get('virtual_site')]}


class QuietHandler(WSGIRequestHandler):
    """Suppress routine loopback HTTP request logging in browser tests."""
    def log_request(self, *args):
        pass
