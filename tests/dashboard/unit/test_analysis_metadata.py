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


def test_the_bartender_fit_is_described_like_every_other_published_analysis():
    """The kind is in the worker's KINDS and has a queue route, but it was missing here, so its own report carried the
    generic fallback title. The description says what the metric is and that agreement is a check against our own
    reference, not experimental evidence."""
    described = describe('bartender-fit')
    assert described['title'] != 'Bartender Fit', 'the generic title is the fallback, not a registered description'
    assert 'reference' in described['ideal_result'] or 'ensemble' in described['ideal_result']
