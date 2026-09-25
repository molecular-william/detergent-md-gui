from dashboard.execution.adapters import composition


def test_composition_stage_contract_is_cg_only():
    assert [stage[0] for stage in composition.STAGES] == ['CG simulation', 'CG assessment', 'CG SASA']
    assert composition.REQUIRED_INPUTS['CG simulation']


def test_composition_screening_is_declared(tmp_path, monkeypatch):
    """A screening stub must not look like executed MD.

    The prepared scripts copied composition.gro into a cg.gro and wrote a cg.xtc and a
    sasa.xvg with printf, so the Runs tab showed three completed CG stages for a run in
    which no integrator ran. The stub declares itself, states its limitation, and emits no
    trajectory- or plot-shaped file that nothing produced.
    """
    import json
    from dashboard.execution.adapters import composition
    from dashboard.models import compositions

    artifacts = tmp_path / 'artifacts'; artifacts.mkdir()
    for name in ('composition.gro', 'composition.itp', 'mapping.json', 'bonded-state.json'):
        (artifacts / name).write_text('placeholder')
    monkeypatch.setattr(compositions, 'get', lambda composition_id: {
        'artifact_root': str(artifacts), 'snapshot_hash': 'sha256', 'identity': 'identity'})

    run = tmp_path / 'run'
    composition.prepare_run(run, 'abcdef123456', settings=None)

    metadata = json.loads((run / 'manifest.json').read_text())
    assert metadata['execution_kind'] == 'screening-stub'
    assert metadata['limitations'], 'a stub must state its limitation'
    assert metadata['scientifically_validated'] is False

    stages = run / 'stages'
    for name, relative in composition.STAGES:
        script = stages / relative
        assert script.is_file(), (name, str(script))
        text = script.read_text()
        assert 'mdrun' not in text and 'gmx ' not in text, f'{name} pretends to run MD: {text}'
    assert not list(stages.rglob('*.xtc')), 'no integrator produced a trajectory here'
    assert not list(stages.rglob('*.xvg')), 'no analysis produced a plot here'
