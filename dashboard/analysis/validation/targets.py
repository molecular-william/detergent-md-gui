"""Validated experimental targets and uncertainty-aware residuals."""
from pathlib import Path
import json
import math
from datetime import datetime, timezone

ALLOWED = {'transfer_free_energy', 'partition_free_energy', 'density', 'phase_transition',
           'dimerization', 'miscibility', 'hydrogen_bond'}

def build(run_dir, payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('targets'), list):
        raise ValueError('targets must be a list')
    rows = []
    for item in payload['targets']:
        if not isinstance(item, dict) or item.get('kind') not in ALLOWED:
            raise ValueError('Unknown target kind')
        try:
            value = float(item['value']); uncertainty = float(item['uncertainty'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Each target needs numeric value and uncertainty') from exc
        if not math.isfinite(value) or not math.isfinite(uncertainty) or uncertainty <= 0:
            raise ValueError('Target value must be finite and uncertainty must be positive')
        rows.append({k: item[k] for k in ('id','kind','name','value','uncertainty','unit','conditions','citation') if k in item})
        rows[-1].update(value=value, uncertainty=uncertainty)
        if 'measured' in item:
            measured = float(item['measured'])
            if not math.isfinite(measured): raise ValueError('Measured value must be finite')
            rows[-1].update(measured=measured, residual=measured-value,
                            standardized_residual=(measured-value)/uncertainty)
    report = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
              'targets': rows, 'scientifically_validated': False,
              'interpretation': 'Residuals are diagnostic; missing measurements remain missing and are never treated as zero.'}
    target = Path(run_dir) / 'analysis'; target.mkdir(exist_ok=True)
    (target / 'experimental_targets.json').write_text(json.dumps(report, indent=2))
    return report

def read(run_dir):
    path = Path(run_dir) / 'analysis/experimental_targets.json'
    if not path.is_file(): return {'targets': [], 'scientifically_validated': False}
    return json.loads(path.read_text())
