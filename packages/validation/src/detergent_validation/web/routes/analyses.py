"""The carbohydrate-validation body contract, validated before the coordinator sees it."""
from dashboard.analysis.validation import carbohydrate_targets
from dashboard.models import mappings
from flask import abort


def payload(c, jid, body):
    """Validate and derive one carbohydrate-validation request; abort with the reason it cannot run."""
    job = c.lookup(jid)
    if job.get('status') != 'completed':
        abort(409, 'Carbohydrate validation requires a completed source run')
    if body.get('tier') not in ('setup', 'evidence'):
        abort(400, 'Validation tier must be setup or evidence')
    if body.get('representation_mode') not in ('tc4', 'physical_only_ring_constrained'):
        abort(400, 'Unknown carbohydrate representation')
    mapping = body.get('mapping_snapshot')
    molecule_id = body.get('molecule_id') or job.get('molecule_id')
    dataset_id = body.get('target_dataset_id')
    if not isinstance(mapping, dict) or not molecule_id or not dataset_id:
        abort(400, 'Validation requires molecule_id, mapping_snapshot, and target_dataset_id')
    try:
        mappings.validate_representation(mapping, body['representation_mode'])
        dataset = carbohydrate_targets.validate_selection(c.ROOT, molecule_id, dataset_id)
    except (ValueError, OSError) as exc:
        abort(400, str(exc))
    return {**body, 'molecule_id': molecule_id, 'target_dataset': dataset}
