"""Water-to-octanol transfer free-energy protocol and BAR parsing."""

import math
import re
from pathlib import Path

_WINDOWS = (0.0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.24, 0.32,
            0.40, 0.50, 0.60, 0.68, 0.76, 0.84, 0.92, 0.96, 0.98, 1.0)


def lambda_windows(count=19):
    if count != 19:
        raise ValueError('Transfer protocol requires exactly 19 lambda windows')
    return list(_WINDOWS)


def build_protocol(payload):
    payload = payload if isinstance(payload, dict) else {}
    solvents = payload.get('solvents', ['water', 'octanol'])
    if set(solvents) != {'water', 'octanol'}:
        raise ValueError('Transfer protocol requires water and octanol')
    windows = payload.get('lambda_windows', lambda_windows())
    if list(windows) != lambda_windows():
        raise ValueError('Transfer protocol requires the canonical 19 lambda windows')
    if payload.get('soft_core_lj', True) is not True:
        raise ValueError('Transfer protocol requires soft-core LJ')
    if payload.get('ensemble', 'NpT') != 'NpT':
        raise ValueError('Transfer protocol requires NpT sampling')
    return {'solvents': ['water', 'octanol'], 'lambda_windows': list(windows),
            'soft_core_lj': True, 'ensemble': 'NpT'}


def parse_bar(output):
    pattern = re.compile(r'(?:Delta\s*G|dG)\s*=\s*([-+]?\d+(?:\.\d+)?)\s*(?:kJ/mol)?\s*(?:\+/-|±)\s*([-+]?\d+(?:\.\d+)?)', re.I)
    match = pattern.search(output or '')
    if not match:
        raise ValueError('BAR output must include free energy and uncertainty')
    value, uncertainty = map(float, match.groups())
    if not math.isfinite(value) or not math.isfinite(uncertainty) or uncertainty < 0:
        raise ValueError('BAR free energy and uncertainty must be finite')
    return {'value_kj_mol': value, 'uncertainty_kj_mol': uncertainty}


def run(work_dir, payload):
    protocol = build_protocol(payload)
    if not (Path(work_dir) / 'octanol').exists() and not payload.get('octanol_output'):
        raise ValueError('Transfer analysis requires octanol parameters and output')
    target = payload.get('target')
    if not target:
        return {'status': 'insufficient_data', 'passed': False, 'missing': ['transfer target']}
    water = payload.get('water_output')
    octanol = payload.get('octanol_output')
    if not water or not octanol:
        return {'status': 'insufficient_data', 'passed': False, 'protocol': protocol,
                'missing': ['water BAR output', 'octanol BAR output']}
    water_result = parse_bar(water)
    octanol_result = parse_bar(octanol)
    transfer = octanol_result['value_kj_mol'] - water_result['value_kj_mol']
    uncertainty = math.sqrt(water_result['uncertainty_kj_mol'] ** 2 + octanol_result['uncertainty_kj_mol'] ** 2)
    residual = transfer - float(target['value'])
    return {'status': 'complete', 'passed': True, 'protocol': protocol,
            'water': water_result, 'octanol': octanol_result,
            'transfer_kj_mol': transfer, 'uncertainty_kj_mol': uncertainty,
            'target_residual_kj_mol': residual}
