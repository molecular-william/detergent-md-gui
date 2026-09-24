from pathlib import Path
import pytest

from dashboard.models.composition_topology import (
    build_preview, composition_identity, expand_tail, load_sugar_catalog,
)

ROOT = Path(__file__).resolve().parents[3]


def payload(**overrides):
    result = {'head_fragment_id': 'builtin:martini-sugars-v2:GLC',
              'tail_recipe_id': 'linear-c1', 'carbon_count': 12,
              'head_endpoint': {'bead': 'C'}, 'tail_endpoint': {'bead': 'C01'},
              'linkage_profile_id': 'sugar-alkyl-ether-ddm-transfer'}
    result.update(overrides)
    return result


def test_sugar_catalog_contains_all_reference_residues():
    catalog = load_sugar_catalog(ROOT / 'references' / 'martini_v3.0.0_sugars_v2.itp')
    assert set(catalog) == {'GLC', 'MAN', 'GAL', 'FRUF', 'LFUC', 'LRHA', 'RIBF', 'XYL', 'INO', 'GLA', 'GYN', 'NMC', 'LAC', 'SUCR', 'TREH'}
    assert catalog['GLC']['virtual_sites']
    assert catalog['GLC']['source_sha256']


def test_linear_c1_expands_carbon_ranges_deterministically():
    result = expand_tail('linear-c1', 12)
    assert [item['type'] for item in result['beads']] == ['C1', 'C1', 'C1']
    assert [item['carbon_range'] for item in result['beads']] == [[1, 4], [5, 8], [9, 12]]
    assert result == expand_tail('linear-c1', 12)


def test_preview_preserves_virtual_sites_and_identity_ignores_display_name():
    first = build_preview(payload(display_name='A'), ROOT)
    second = build_preview(payload(display_name='B'), ROOT)
    assert first['topology']['virtual_sites']
    assert first['topology']['exclusions']
    assert composition_identity(first) == composition_identity(second)


def test_invalid_carbon_count_is_rejected():
    with pytest.raises(ValueError, match='carbon count'):
        expand_tail('linear-c1', 0)
