"""Class-specific evidence profiles; execution is never validation by itself."""
PROFILES = {
    'carbohydrate': ('mapped_geometry', 'bonded_distributions', 'sasa'),
    'alkyl_tail': ('geometry', 'density'),
    'charged_headgroup': ('charge_balance', 'hydration'),
    'detergent': ('component_compatibility', 'bonded_distributions', 'hydration', 'aggregation'),
}
def evaluate(profile, results):
    required = PROFILES.get(profile)
    if required is None: raise ValueError(f'Unknown evidence profile: {profile}')
    results = results if isinstance(results, dict) else {}
    missing = [name for name in required if not results.get(name, {}).get('passed', False)]
    return {'profile': profile, 'required': list(required), 'missing': missing, 'validated': not missing,
            'reason': None if not missing else 'Required evidence is missing or failed'}
