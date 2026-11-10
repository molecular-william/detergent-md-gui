"""The CG-only sugar run's preview endpoint: what the New run form reads before a job exists.

The preview is the run type's own answer (`sugar_cg.preview`), not a second reading of the sugar package in the web
layer. It returns the candidate's bead layout, the conformance result, the published signature and the reference
provenance; the panel says "conforms" only when `reference.conform` returned no issues, and a blocking entry returns
the words a reader needs rather than a 500.
"""
from dashboard.web.routes.common import coordinator
from detergent_validation.execution.adapters import sugar_cg
from flask import Blueprint, abort, jsonify, request

blueprint = Blueprint('sugar_cg', __name__)


@blueprint.get('/api/sugar-cg/preview')
def preview_api():
    c = coordinator()
    molecule_id = (request.args.get('molecule_id') or request.args.get('detergent') or '').strip()
    if not molecule_id:
        abort(400, 'molecule_id is required to preview a CG sugar run')
    entry = (request.args.get('sugar_entry') or request.args.get('entry') or 'SUCR').strip()
    if entry not in sugar_cg.ENTRIES:
        abort(400, 'sugar_entry must be one of ' + ', '.join(sugar_cg.ENTRIES))
    try:
        answer = sugar_cg.preview(molecule_id, entry, molecule_root=c.ROOT / 'molecules')
    except ValueError as exc:
        abort(400, str(exc))
    return jsonify(answer)
