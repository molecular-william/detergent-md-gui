"""The block-averaged summary two comparisons report: mean, spread and a standard error over blocks.

Both the CG topology comparison and the validation geometry report quote these numbers, so the arithmetic lives in
one place. A block summary is evidence with a stated block count, not a confidence interval: the blocks describe how
the samples were averaged, and the caller's own report says which count it used.
"""
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
