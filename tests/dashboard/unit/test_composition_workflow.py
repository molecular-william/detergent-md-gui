from dashboard.execution.adapters import composition


def test_composition_stage_contract_is_cg_only():
    assert [stage[0] for stage in composition.STAGES] == ['CG simulation', 'CG assessment', 'CG SASA']
    assert composition.REQUIRED_INPUTS['CG simulation']
