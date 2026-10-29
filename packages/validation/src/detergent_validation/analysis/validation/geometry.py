"""Geometry and molecular-volume evidence for carbohydrate attempts."""

from pathlib import Path


def run(work_dir, representation, protocol):
    work_dir = Path(work_dir)
    tier = protocol.get('tier', 'setup')
    duration_ns = float(protocol.get('duration_ns', 0))
    if tier == 'evidence' and duration_ns < 200:
        raise ValueError('Geometry evidence requires at least 200 ns')
    diagnostic_only = tier != 'evidence'
    aa = work_dir / '1_AA-reference/prod/lig.xtc'
    cg = work_dir / '4_CG_sim/prod/lig_CG.xtc'
    if not aa.is_file() or not cg.is_file():
        return {'status': 'insufficient_data', 'passed': False, 'diagnostic_only': diagnostic_only,
                'representation_mode': representation.get('representation_mode', 'tc4'),
                'missing': [str(path.relative_to(work_dir)) for path in (aa, cg) if not path.is_file()]}
    from detergent_validation.analysis.runs import surfaces
    report = surfaces.generate(work_dir)
    return {'status': 'diagnostic_only' if diagnostic_only else 'complete',
            'passed': not diagnostic_only, 'diagnostic_only': diagnostic_only,
            'representation_mode': representation.get('representation_mode', 'tc4'),
            'surface': report}
