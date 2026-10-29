"""The experimental targets a validation run was scored against, as the panel reads them."""
import json

from dashboard.analysis.runs import layout
from dashboard.web.routes.common import coordinator
from detergent_validation.analysis.validation import targets
from flask import Blueprint, jsonify

blueprint = Blueprint('targets', __name__)


@blueprint.get('/api/jobs/<jid>/targets')
def targets_get(jid):
    c = coordinator()
    job = c.lookup(jid)
    path = c.analysis_coordinator.dependencies(job).get('experimental_targets.json')
    return jsonify(json.loads((c.run_path(job) / path).read_text()) if path
                   else targets.read(layout.stage_root(c.run_path(job))))
