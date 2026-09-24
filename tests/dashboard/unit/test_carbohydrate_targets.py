import json

import pytest

from dashboard.analysis.carbohydrate_targets import catalog, validate_selection
from dashboard.models.evidence import evaluate


def test_carbohydrate_profile_requires_three_physical_evidence_keys():
    report = evaluate('carbohydrate', {'mapped_geometry': {'passed': True}})
    assert report['missing'] == ['transfer_free_energy', 'osmotic_pressure']
    assert report['status'] == 'insufficient_data'


def test_target_catalog_rejects_unknown_dataset(tmp_path):
    (tmp_path / 'targets-v1.json').write_text(json.dumps({'datasets': []}))
    with pytest.raises(ValueError, match='dataset'):
        validate_selection(tmp_path, 'Maltose', 'missing')


def test_target_catalog_exposes_citation_and_availability(tmp_path):
    (tmp_path / 'targets-v1.json').write_text(json.dumps({'datasets': [{
        'id': 'maltose-pilot-v1', 'molecule_id': 'Maltose', 'citation': 'doi:test',
        'targets': [], 'availability': 'metadata_only'
    }]}))
    result = validate_selection(tmp_path, 'Maltose', 'maltose-pilot-v1')
    assert result['citation'] == 'doi:test'
    assert result['availability'] == 'metadata_only'
    assert catalog(tmp_path, 'Maltose')['datasets'][0]['id'] == 'maltose-pilot-v1'
