"""Class-specific evidence profiles; execution is never validation by itself.

The engine owns the profiles that are molecule-class vocabulary -- a tail's geometry, a headgroup's charge balance, a
detergent's compatibility. A profile whose report a feature owns is registered by that feature, so `PROFILES` is a live
view: a module-level dict would be frozen before any feature registers.
"""
from collections.abc import Mapping

from ... import features

_CORE_PROFILES = {
    'alkyl_tail': ('geometry', 'density'),
    'charged_headgroup': ('charge_balance', 'hydration'),
    'detergent': ('component_compatibility', 'bonded_distributions', 'hydration', 'aggregation'),
}


def profiles():
    """Every evidence profile an installed distribution defines, merged with the engine's own.

    A feature claiming a profile the engine owns is an error, like two features claiming the same name: the profile
    decides what a report must carry, and a second definition would silently replace the first.
    """
    merged = dict(_CORE_PROFILES)
    for name, required in features.molecule_profiles().items():
        if name in merged:
            raise ValueError(f'molecule profile {name!r} is claimed by the engine and a feature')
        merged[name] = required
    return merged


class _Profiles(Mapping):
    """`PROFILES` read at access time, so a feature's profile is visible once its distribution is installed."""

    def __getitem__(self, name):
        return profiles()[name]

    def __iter__(self):
        return iter(profiles())

    def __len__(self):
        return len(profiles())


PROFILES = _Profiles()


def evaluate(profile, results):
    required = profiles().get(profile)
    if required is None: raise ValueError(f'Unknown evidence profile: {profile}')
    results = results if isinstance(results, dict) else {}
    missing = [name for name in required if not results.get(name, {}).get('passed', False)]
    insufficient = [name for name in missing if results.get(name, {}).get('status') == 'insufficient_data' or not results.get(name)]
    status = 'evidence_complete' if not missing else ('insufficient_data' if insufficient else 'failed')
    return {'profile': profile, 'required': list(required), 'missing': missing, 'validated': not missing,
            'status': status, 'reason': None if not missing else 'Required evidence is missing or failed'}
