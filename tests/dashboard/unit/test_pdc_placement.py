"""Detergent placement: the builder's geometry plus the gates that decide whether a run may proceed.

The properties worth pinning are the ones a reader would otherwise have to trust: the count is exact, the same seed
gives the same positions while a different seed does not, every detergent is outside the protein, and an impossible
packing is reported as an issue rather than handed back as coordinates for a run to fail on later.
"""
import json

import numpy as np
import pytest

from dashboard.execution.adapters import pdc_placement
from micelle.registry import load_template

PROTEIN = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


def _template(tmp_path):
    (tmp_path / 'x.pdb').write_text('')
    (tmp_path / 'x.itp').write_text('')
    path = tmp_path / 'x.json'
    path.write_text(json.dumps({'name': 'X', 'residue': 'X', 'beads': [{'name': 'B1'}, {'name': 'B2'}],
                                'coordinates': 'x.pdb', 'topology': 'x.itp', 'tail_direction': [0, 0, -1]}))
    return load_template(path)


def test_placement_is_exact_deterministic_and_outside_the_protein(tmp_path):
    first = pdc_placement.place_detergents(PROTEIN, _template(tmp_path), 12, seed=7)
    again = pdc_placement.place_detergents(PROTEIN, _template(tmp_path), 12, seed=7)
    other = pdc_placement.place_detergents(PROTEIN, _template(tmp_path), 12, seed=8)

    assert first['valid'], first['issues']
    assert len(first['centers']) == 12, 'the requested count is the count that is placed'
    assert first['centers'] == again['centers'], 'the seed decides, not the clock'
    assert other['centers'] != first['centers'], 'a different seed must place differently'

    points = np.asarray(PROTEIN)
    for center in np.asarray(first['centers']):
        assert np.linalg.norm(center - points, axis=1).min() >= pdc_placement.MIN_CLEARANCE_NM
    assert first['protein_clearance_nm'] >= pdc_placement.MIN_CLEARANCE_NM


def test_an_empty_micelle_has_no_protein_to_clear(tmp_path):
    placed = pdc_placement.place_detergents(None, _template(tmp_path), 8, seed=3)
    assert placed['valid'] and placed['protein_free']
    assert len(placed['centers']) == 8 and placed['protein_clearance_nm'] is None


def test_an_impossible_packing_is_reported_rather_than_returned(tmp_path):
    """The builder's policy: an impossible request writes diagnostics and produces no run."""
    placed = pdc_placement.place_detergents(None, _template(tmp_path), 4, seed=1, radius_nm=0.1)
    assert not placed['valid']
    assert any('overlap' in issue for issue in placed['issues']), placed['issues']


def test_a_placement_refuses_impossible_input(tmp_path):
    with pytest.raises(ValueError, match='at least one detergent'):
        pdc_placement.place_detergents(None, _template(tmp_path), 0, seed=1)
    with pytest.raises(ValueError, match='radius must be positive'):
        pdc_placement.place_detergents(None, _template(tmp_path), 4, seed=1, radius_nm=0)
