"""Detergent placement: the builder's geometry, with the gates that decide whether a run may proceed.

`micelle.packing` owns the geometry and `micelle.validation` owns the overlap and count gates; this module owns the
protein-relative clearance and the decision to stop. That split is deliberate: the builder's design says an
impossible packing writes diagnostics and produces no run, and a placement is exactly where that has to be decided.
"""
import numpy as np

from micelle.packing import pack_micelle
from micelle.validation import validate_positions

MIN_CLEARANCE_NM = 0.5
DEFAULT_RADIUS_NM = 3.0


def place_detergents(protein_points, template, aggregation_number, seed, *, radius_nm=DEFAULT_RADIUS_NM,
                     min_clearance_nm=MIN_CLEARANCE_NM):
    """Place `aggregation_number` detergents around the protein (or around nothing, for an empty micelle).

    Deterministic in the seed through the builder's own direction generator, and gated before anything runs: the
    returned mapping carries the positions *and* the issues, so a caller cannot proceed past a failed gate without
    acknowledging it. What this cannot yet check is the detergent's own bead shape -- the clearance uses the placed
    centres against the protein coordinates, and a template whose headgroup reaches further than that needs the
    bead geometry to say so.
    """
    if aggregation_number < 1:
        raise ValueError('a placement needs at least one detergent')
    if radius_nm <= 0 or min_clearance_nm < 0:
        raise ValueError('the placement radius must be positive and the clearance cannot be negative')
    points = np.asarray([[float(value) for value in point] for point in protein_points]) if protein_points else None
    if points is not None and points.ndim != 2:
        raise ValueError('protein coordinates must be a list of points')

    centers, directions = pack_micelle(points, template, aggregation_number, seed, radius=radius_nm)
    issues = list(validate_positions(centers, aggregation_number)['issues'])
    clearance = None
    if points is not None and len(points):
        clearance = min(float(np.linalg.norm(center - points, axis=1).min()) for center in centers)
        if clearance < min_clearance_nm:
            issues.append(f'detergent too close to the protein: {clearance:.3f} nm < {min_clearance_nm} nm')
    return {'centers': centers.tolist(), 'directions': directions.tolist(),
            'aggregation_number': aggregation_number, 'radius_nm': radius_nm, 'seed': seed,
            'protein_free': points is None or not len(points), 'protein_clearance_nm': clearance,
            'issues': issues, 'valid': not issues}
