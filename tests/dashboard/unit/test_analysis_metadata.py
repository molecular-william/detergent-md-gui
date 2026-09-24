from dashboard.analysis.metadata import describe


def test_graph_metadata_explains_metric_direction_and_units():
    score=describe('refinement-score',{'interaction_score':.2})
    assert score['units_or_direction'].startswith('native metric')
    assert 'lower-is-better' in score['ideal_result']
    sasa=describe('plots')
    assert 'SASA' in sasa['title'] and 'variability' in sasa['ideal_result']


def test_legacy_metadata_is_explicit():
    assert describe('distance-distributions',legacy=True)['legacy'] is True


def test_carbohydrate_evidence_metadata_names_physical_measurements():
    assert describe('mapped_geometry')['title'] == 'Carbohydrate geometry and volume'
    assert 'osmotic' in describe('osmotic_pressure')['title'].lower()
