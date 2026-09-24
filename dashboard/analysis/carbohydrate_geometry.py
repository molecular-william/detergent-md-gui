"""Geometry and molecular-volume evidence for carbohydrate attempts."""

from pathlib import Path
import math

import numpy as np


def block_summary(values, block_count=5):
    values = np.asarray(list(values), dtype=float)
    if values.size == 0 or not np.isfinite(values).all():
        raise ValueError('Geometry values must be finite and non-empty')
    blocks = min(max(1, int(block_count)), values.size)
    block_values = np.array_split(values, blocks)
    means = np.array([block.mean() for block in block_values], dtype=float)
    stderr = float(means.std(ddof=1) / math.sqrt(len(means))) if len(means) > 1 else 0.0
    return {'samples': int(values.size), 'blocks': int(len(means)),
            'mean': float(values.mean()), 'std': float(values.std()), 'stderr': stderr}


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
    from . import surfaces
    report = surfaces.generate(work_dir)
    return {'status': 'diagnostic_only' if diagnostic_only else 'complete',
            'passed': not diagnostic_only, 'diagnostic_only': diagnostic_only,
            'representation_mode': representation.get('representation_mode', 'tc4'),
            'surface': report}
