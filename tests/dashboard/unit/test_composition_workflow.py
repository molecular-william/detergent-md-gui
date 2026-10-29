"""A composition screening run: its stages are repository scripts, and it executes nothing.

The three screens the composition workflow used to write as generated `.sh` files inside the run are repository
scripts now, recorded in the manifest's `stage_scripts` by path and digest. The behaviour did not change: the first
copies the prepared geometry and the three declare that no GROMACS MD, assessment or SASA ran.
"""
import json
import os
import subprocess
import sys

from dashboard.execution import run_inputs, run_scripts
from dashboard.execution.adapters import composition
from dashboard.execution.environment import ROOT
from dashboard.models import compositions


def test_composition_stage_contract_is_cg_only():
    assert [stage[0] for stage in composition.STAGES] == ['CG simulation', 'CG assessment', 'CG SASA']
    assert composition.REQUIRED_INPUTS['CG simulation']


def test_each_composition_stage_runs_a_repository_script():
    """The code lives in one place, pinned: no `.sh` is generated into the run, and `Stage.script` names the file."""
    assert [stage.script for stage in composition.STAGE_DEFS] == [
        'dashboard/execution/scripts/composition_simulation.sh',
        'dashboard/execution/scripts/composition_assessment.sh',
        'dashboard/execution/scripts/composition_sasa.sh']
    for stage in composition.STAGE_DEFS:
        assert run_scripts.code_path(stage.script, root=ROOT).is_file(), stage.script
        # The stub says it executed nothing, in its own words -- a screening run must not look like MD.
        if stage.name != 'CG simulation':
            assert 'executed' in run_scripts.code_path(stage.script, root=ROOT).read_text()


def test_composition_screening_is_declared_and_its_scripts_are_recorded(tmp_path, monkeypatch):
    """A screening stub must not look like executed MD.

    The prepared scripts copied composition.gro into a cg.gro and wrote a cg.xtc and a
    sasa.xvg with printf, so the Runs tab showed three completed CG stages for a run in
    which no integrator ran. The stub declares itself, states its limitation, and emits no
    trajectory- or plot-shaped file that nothing produced.
    """
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
    # The artifacts are named by reference, not copied: inputs/ is a record, not a second store.
    record = json.loads((run / 'inputs' / 'inputs.json').read_text())
    assert {entry['label'] for entry in record['inputs']} == {
        'composition.gro', 'composition.itp', 'mapping.json', 'bonded-state.json'}
    assert all(entry['kind'] == 'store' for entry in record['inputs'])
    assert metadata['input_snapshot_sha256'] == run_inputs.digest(record['inputs'])
    assert metadata['layout_version'] == 3 and metadata['stage_plan'] == [name for name, _ in composition.STAGES]
    assert not (run / 'inputs' / 'composition.gro').exists(), 'a store artifact is not copied'

    # The code is the repository's, recorded by path and digest. The run holds no `.sh` and no `.py`.
    assert {name: record['path'] for name, record in metadata['stage_scripts'].items()} == {
        stage.name: stage.script for stage in composition.STAGE_DEFS}
    assert all(len(record['sha256']) == 64 for record in metadata['stage_scripts'].values())
    assert not list(run.rglob('*.sh')) and not list(run.rglob('*.py'))
    stages = run / 'stages'
    for stage in composition.STAGE_DEFS:
        assert (stages / stage.relative).parent.is_dir(), stage.name

    # Run the three repository scripts for real, with the stage directory as the working directory.
    env = {**os.environ, 'PYTHON': sys.executable}
    for stage in composition.STAGE_DEFS:
        completed = subprocess.run(['bash', str(run_scripts.code_path(stage.script, root=ROOT))], capture_output=True, text=True, check=False,
                                   cwd=(stages / stage.relative).parent, env=env)
        assert completed.returncode == 0, completed.stderr
    assert (stages / '1_CG-simulation' / 'cg.gro').read_text() == 'placeholder'
    assert json.loads((stages / '1_CG-simulation' / 'screening.json').read_text()) == {
        'stage': 'CG simulation', 'executed': False, 'execution_kind': 'screening-stub'}
    assert json.loads((stages / '2_CG-assessment' / 'validation.json').read_text()) == {
        'status': 'screened', 'executed': False, 'execution_kind': 'screening-stub',
        'scientifically_validated': False}
    assert json.loads((stages / '3_CG-SASA' / 'sasa.json').read_text()) == {
        'stage': 'CG SASA', 'executed': False, 'execution_kind': 'screening-stub'}
    assert not list(stages.rglob('*.xtc')), 'no integrator produced a trajectory here'
    assert not list(stages.rglob('*.xvg')), 'no analysis produced a plot here'
