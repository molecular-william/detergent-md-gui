"""One verdict for candidate usability.

"Does this finding matter?" was answered in five places: the graph checker kept two code
sets, the store's save message a third, the exporter's blocker list a fourth and the
molecule draft loader a fifth. The table lives in one module now, and these pin both the
shape callers get and that the checker really asks it.
"""
from dashboard.models.mappings import graph, verdict

STRUCTURE = {'atoms': [{'id': 1, 'heavy': True, 'xyz': [0.0, 0.0, 0.0], 'name': 'C1'},
                       {'id': 2, 'heavy': True, 'xyz': [1.0, 0.0, 0.0], 'name': 'C2'}],
             'bonds': [[1, 2]]}


def candidate(**overrides):
    document = {'name': 'candidate', 'beads': [
        {'name': 'BEAD01', 'size': 'R', 'type': 'P1', 'atoms': [1]},
        {'name': 'BEAD02', 'size': 'R', 'type': 'P1', 'atoms': [2]}]}
    document.update(overrides)
    return document


def test_verdict_is_one_shape_for_every_question():
    result = verdict.evaluate({'beads': []}, context=None)
    assert set(result) >= {'codes', 'issues', 'can_save', 'can_reuse', 'can_export', 'can_approve'}
    assert result['can_save'] is False


def test_a_document_that_does_not_parse_is_a_finding_not_an_exception():
    """The caller asks a question about the candidate; it should get the answer, not a raise."""
    result = verdict.evaluate({'beads': 'not a list'}, context=None)
    assert result['can_save'] is False and result['can_approve'] is False
    assert result['issues'] and result['issues'][0]['message']
    assert result['codes'] == [verdict.MALFORMED]


def test_an_advisory_blocks_approval_but_not_export_or_reuse():
    """Size and nominal-count findings describe conventions, not an incomplete graph."""
    findings = [{'code': 'size', 'message': 'nominal size', 'bead': 0}]
    assert verdict.derive(findings) == {'can_save': True, 'can_approve': False,
                                        'can_export': True, 'can_reuse': True}


def test_a_structural_finding_blocks_saving_and_a_draft_finding_does_not():
    for code in ('duplicate', 'unknown', 'hydrogen', 'name', 'virtual_ring', verdict.MALFORMED):
        assert verdict.derive([{'code': code, 'message': code}])['can_save'] is False, code
    for code in ('empty', 'disconnected', 'connections', 'sugar_fragment', 'missing'):
        assert verdict.derive([{'code': code, 'message': code}])['can_save'] is True, code


def test_the_graph_checker_reports_the_verdict_this_module_derives():
    """One shape, one table: the checker no longer keeps its own pair of code sets."""
    result = graph.validate(candidate(beads=[{'name': 'BEAD01', 'size': 'R', 'type': 'P1', 'atoms': [1]},
                                              {'name': 'BEAD01', 'size': 'R', 'type': 'P1', 'atoms': [2]}]),
                            structure=STRUCTURE)
    codes = [item['code'] for item in result['issues']]
    assert 'name' in codes, 'a structural finding'
    assert 'size' in codes or 'mismatch' in codes, 'and an advisory in the same verdict'
    assert {key: result[key] for key in verdict.RULES} == verdict.derive(result['issues'])
    assert result['can_save'] is False and result['can_export'] is False
