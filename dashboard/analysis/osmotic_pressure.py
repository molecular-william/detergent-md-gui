"""Concentration-series osmotic-pressure evidence."""

import math


REQUIRED_MOLAL = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5)


def pressure_from_force(force_kj_nm, area_nm2):
    force = float(force_kj_nm)
    area = float(area_nm2)
    if not math.isfinite(force):
        raise ValueError('Force must be finite')
    if not math.isfinite(area) or area <= 0:
        raise ValueError('area must be finite and greater than zero')
    return force / area


def validate_series(points, tier):
    if not isinstance(points, list):
        raise ValueError('Osmotic pressure points must be a list')
    by_molal = {}
    for point in points:
        try:
            molal = round(float(point['molal']), 6)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Each osmotic point needs a molal concentration') from exc
        if not 0 <= molal <= 2.5:
            raise ValueError('Osmotic concentrations must span 0–2.5 molal')
        by_molal[molal] = point
    missing = [value for value in REQUIRED_MOLAL if value not in by_molal]
    if tier == 'evidence':
        short = [value for value, point in by_molal.items() if float(point.get('duration_ns', 0)) < 500]
        missing += [f'{value} molal requires 500 ns' for value in short]
        missing += [f'{value} molal target value and uncertainty' for value, point in by_molal.items()
                    if point.get('target_pressure') is None or point.get('target_uncertainty') is None]
    invalid = [value for value, point in by_molal.items()
               if point.get('flat_bottom_restraint') is not True or point.get('pressure_coupling') not in (None, 'z')]
    missing += [f'{value} molal restraint/coupling metadata' for value in invalid]
    return {'points': list(by_molal.values()), 'missing': missing,
            'complete': not missing, 'diagnostic_only': tier != 'evidence'}


def run(work_dir, payload):
    series = validate_series(payload.get('points', []), payload.get('tier', 'setup'))
    if not series['complete']:
        return {'status': 'insufficient_data', 'passed': False, **series}
    rows = []
    for point in series['points']:
        pressure = pressure_from_force(point['force_kj_nm'], point['area_nm2'])
        target = point.get('target_pressure')
        rows.append({'molal': point['molal'], 'pressure': pressure,
                     'uncertainty': float(point.get('uncertainty', 0)),
                     'target_pressure': target,
                     'target_residual': pressure - float(target) if target is not None else None})
    return {'status': 'complete', 'passed': True, **series, 'results': rows}
