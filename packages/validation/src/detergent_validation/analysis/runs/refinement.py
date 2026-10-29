"""Diagnostic aggregation for mapping refinement evidence."""
import json
from pathlib import Path


def score(run_dir):
    root = Path(run_dir); metrics = []
    validation = root / '5_assessment/validation.json'
    if validation.is_file():
        data = json.loads(validation.read_text())
        for key, label in (('cog_rmsd_nm','COG error'), ('interaction_score','interaction score'), ('pair_distance_score','pair-distance score')):
            if key in data and isinstance(data[key], (int,float)):
                value = float(data[key]); metrics.append({'name': label, 'value': value, 'source': str(validation.relative_to(root))})
    stability = root / 'analysis/numerical_stability.json'
    if stability.is_file():
        data = json.loads(stability.read_text()); warnings = sum(x.get('warnings', 0) for x in data.get('lincs_warnings', []))
        metrics.append({'name': 'LINCS warnings', 'value': warnings, 'source': str(stability.relative_to(root))})
    # Scores are reported as evidence; no cross-metric normalization is invented.
    report = {'schema_version': 1, 'metrics': metrics, 'missing': ['experimental targets'] if not (root/'analysis/experimental_targets.json').is_file() else [], 'diagnostic_only': True,
              'scientifically_validated': False, 'interpretation': 'Metrics retain native units/scales; ranking requires an explicitly chosen protocol and weights.'}
    out = root / 'analysis/refinement_score.json'; out.parent.mkdir(exist_ok=True); out.write_text(json.dumps(report, indent=2)); return report
