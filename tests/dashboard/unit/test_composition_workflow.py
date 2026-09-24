from dashboard.execution import composition_workflow


def test_composition_stage_contract_is_cg_only():
    assert [stage[0] for stage in composition_workflow.STAGES] == ['CG simulation', 'CG assessment', 'CG SASA']
    assert composition_workflow.REQUIRED_INPUTS['CG simulation']
