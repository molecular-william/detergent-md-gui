"""Class-specific evidence profiles; execution is never validation by itself."""
PROFILES = {
    'carbohydrate': ('mapped_geometry', 'transfer_free_energy', 'osmotic_pressure'),
    'alkyl_tail': ('geometry', 'density'),
    'charged_headgroup': ('charge_balance', 'hydration'),
    'detergent': ('component_compatibility', 'bonded_distributions', 'hydration', 'aggregation'),
}
def evaluate(profile, results):
    required = PROFILES.get(profile)
    if required is None: raise ValueError(f'Unknown evidence profile: {profile}')
    results = results if isinstance(results, dict) else {}
    missing = [name for name in required if not results.get(name, {}).get('passed', False)]
    insufficient = [name for name in missing if results.get(name, {}).get('status') == 'insufficient_data' or not results.get(name)]
    status = 'evidence_complete' if not missing else ('insufficient_data' if insufficient else 'failed')
    return {'profile': profile, 'required': list(required), 'missing': missing, 'validated': not missing,
            'status': status, 'reason': None if not missing else 'Required evidence is missing or failed'}
