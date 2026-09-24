"""Aggregate the three carbohydrate evidence calculations into one report."""

from pathlib import Path

from dashboard.models.carbohydrate_validation import derive_representation
from . import carbohydrate_geometry, osmotic_pressure, transfer_free_energy


def _insufficient(message):
    return {'status': 'insufficient_data', 'passed': False, 'missing': [message]}


def run(work_dir, payload):
    work_dir = Path(work_dir)
    mode = payload.get('representation_mode', 'tc4')
    mapping = payload.get('mapping_snapshot') or {}
    try:
        representation = derive_representation(mapping, mode)
    except (TypeError, ValueError) as exc:
        representation = {'representation_mode': mode}
        transform_error = _insufficient(str(exc))
    else:
        transform_error = None
    tier = payload.get('tier', 'setup')
    protocol = dict(payload.get('protocol') or {}, tier=tier,
                    duration_ns=payload.get('duration_ns', (200 if tier == 'evidence' else 1)))
    geometry = transform_error or carbohydrate_geometry.run(work_dir, representation, protocol)
    try:
        transfer = transfer_free_energy.run(work_dir, payload)
    except ValueError as exc:
        transfer = _insufficient(str(exc))
    osmotic = osmotic_pressure.run(work_dir, dict(payload, tier=tier))
    sections = {'mapped_geometry': geometry, 'transfer_free_energy': transfer, 'osmotic_pressure': osmotic}
    if tier != 'evidence':
        status = 'diagnostic_only'
    elif all(item.get('status') in ('complete', 'evidence_complete') and item.get('passed') for item in sections.values()):
        status = 'evidence_complete'
    elif any(item.get('status') == 'failed' for item in sections.values()):
        status = 'failed'
    else:
        status = 'insufficient_data'
    return {'status': status, 'representation': {
                'mode': mode,
                'source_mapping_hash': representation.get('source_mapping_hash'),
                'transformation': representation.get('transformation')},
            **sections, 'provenance': {
                'target_dataset': (payload.get('target_dataset') or {}).get('id'),
                'target_citation': (payload.get('target_dataset') or {}).get('citation'),
                'tier': tier}}
