from dashboard.analysis.kinds import TABLE
from dashboard.analysis.metadata import describe


def test_graph_metadata_explains_metric_direction_and_units():
    score=describe('refinement-score',{'interaction_score':.2})
    assert score['units_or_direction'].startswith('native metric')
    assert 'lower-is-better' in score['ideal_result']
    sasa=describe('plots')
    assert 'SASA' in sasa['title'] and 'variability' in sasa['ideal_result']


def test_carbohydrate_evidence_metadata_names_physical_measurements():
    """The evidence sections the carbohydrate profile requires carry their own text, apart from the analysis kinds.

    These three are sections a report must contain, not analyses the worker can be asked to run, and they used to be
    described through the *kinds'* describer -- which is how a mapping of fourteen kinds came to hold seventeen
    entries, and why nothing noticed the three it should not have had.
    """
    from dashboard import features
    sections = features.evidence_sections()
    assert sections['mapped_geometry'][0] == 'Carbohydrate geometry and volume'
    assert 'osmotic' in sections['osmotic_pressure'][0].lower()


def test_the_bartender_fit_is_described_like_every_other_published_analysis():
    """The kind is in the worker's KINDS and has a queue route, but it was missing here, so its own report carried the
    generic fallback title. The description says what the metric is and that agreement is a check against our own
    reference, not experimental evidence."""
    described = describe('bartender-fit')
    assert described['title'] != 'Bartender Fit', 'the generic title is the fallback, not a registered description'
    assert 'reference' in described['ideal_result'] or 'ensemble' in described['ideal_result']


def test_the_overlap_analysis_is_registered_in_all_three_places():
    """A kind missing any one of them fails silently: without KINDS it is unreachable, without PATTERNS it is handed no
    inputs, and without a DESCRIPTION its own report renders under the generic fallback title."""
    assert 'overlap' in TABLE, 'the table is the registration the worker reads'
    described = describe('overlap')
    assert described['title'] != 'Overlap', 'the generic title is the fallback, not a registered description'
    assert 'reference' in described['ideal_result']

    staged = list(TABLE['overlap'].sources)
    # Both sides are bead trajectories: the mapped AA reference and the CG simulation. The all-atom `1_AA-reference`
    # files are not staged because their atom names are C/C1/LIG1, not the beads the comparison measures.
    assert '2_mapping/mapped.gro' in staged and '2_mapping/mapped.xtc' in staged
    assert TABLE['overlap'].reads_aa_reference is False
    assert '2_mapping/model.json' in staged
    assert '4_CG_sim/prod/lig_CG.gro' in staged and '4_CG_sim/prod/lig_CG.xtc' in staged
    assert not [path for path in staged if path.startswith('1_AA-reference')]
