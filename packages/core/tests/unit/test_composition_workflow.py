"""A composition CG run: one real CG simulation, one stage that states there is nothing to score.

The composition workflow used to be three screening stubs that copied the artifact and wrote `executed: false`. It is
now the same CG build the sugar and AA-to-CG runs execute, over the composition's own topology and coordinates: the
`CG simulation` stage runs the repository's `cg_simulation.sh`, and the `CG assessment` stage records `skipped` with
its reason because a composition has no AA reference distribution to score against. Nothing here runs mdrun: the
command construction is proved with a fake `gmx` on `PATH`.
"""
import json
import os
import subprocess
import sys

import pytest
from dashboard.execution import protocol, run_inputs, run_scripts
from dashboard.execution.adapters import cg, cg_run, composition
from dashboard.execution.environment import ROOT
from dashboard.models import compositions

PAYLOAD = {'head_fragment_id': 'builtin:martini-sugars-v2:GLC', 'tail_recipe_id': 'linear-c1',
           'carbon_count': 12, 'head_endpoint': {'bead': 'C'}, 'tail_endpoint': {'bead': 'C01'},
           'linkage_profile_id': 'sugar-alkyl-ether-ddm-transfer', 'display_name': 'Glucose C12',
           'molecule_name': 'GLC-C12'}


@pytest.fixture(autouse=True)
def no_tool_probe(monkeypatch):
    """`prepare` records the resolved gmx; these tests are about the files, not the host's GROMACS."""
    monkeypatch.setattr(composition, 'tool_metadata', lambda: {})


@pytest.fixture
def saved():
    """One immutable composition in the test workspace's own store."""
    return compositions.create_composition(dict(PAYLOAD))


def _prepare(run, record, *, settings=None, profile='draft-smoke-reference', molecule_id=None):
    metadata = {'composition_id': record['id'], 'profile': profile, 'settings': settings or {},
                'parameterization': {'kind': 'composition', 'composition_id': record['id']}}
    if molecule_id is not None:
        metadata['molecule_id'] = molecule_id
    return cg_run.PROTOCOL.prepare(run, metadata)


def _mdp_value(path, key):
    for line in path.read_text().splitlines():
        raw = line.split(';', 1)[0]
        if '=' in raw and raw.split('=', 1)[0].strip() == key:
            return raw.split('=', 1)[1].strip()
    raise AssertionError(f'{path}: no {key}')


def test_the_two_stages_are_a_real_cg_simulation_and_a_skipping_assessment():
    assert [name for name, _ in composition.STAGES] == ['CG simulation', 'CG assessment']
    assert composition.SIMULATION_SCRIPT == 'dashboard/execution/scripts/cg_simulation.sh'
    assert [stage.script for stage in composition.STAGE_DEFS] == [
        composition.SIMULATION_SCRIPT, composition.ASSESSMENT_SCRIPT]
    for stage in composition.STAGE_DEFS:
        assert run_scripts.code_path(stage.script, root=ROOT).is_file(), stage.script
    # The assessment must skip by the contract (exit 4 plus skip.json), never print a score.
    assert composition.NO_REFERENCE in \
        run_scripts.code_path(composition.ASSESSMENT_SCRIPT, root=ROOT).read_text()
    assert composition.REQUIRED_INPUTS['CG simulation']


def test_prepare_writes_the_cg_build_the_script_reads(tmp_path, saved):
    run = tmp_path / 'run'
    settings = composition.normalize_settings({'temperature_k': 310, 'cg_seed': 7}, 'draft-smoke-reference')
    _prepare(run, saved, settings={'temperature_k': 310, 'cg_seed': 7})

    artifacts = compositions.artifacts(compositions.get(saved['id']))
    stages = run / 'stages'
    assert (stages / '2_mapping/mapped.gro').read_bytes() == artifacts['composition.gro'].read_bytes()
    assert (stages / '3_initial_CG/GLC.itp').read_bytes() == artifacts['composition.itp'].read_bytes()
    system = (stages / '4_CG_sim/system_EMPTY.top').read_text()
    assert 'martini_v3.0.0.itp' in system and 'martini_v3.0.0_solvents_v1.itp' in system
    assert '#include "GLC.itp"' in system
    assert '[ molecules ]\nGLC 1' in system
    for name in ('minimization', 'eq', 'md'):
        assert (stages / f'4_CG_sim/inputs/{name}.mdp').is_file(), name

    # The run's numbers are real: the reviewed CG profiles at the run's own durations, temperature and seed.
    eq = stages / '4_CG_sim/inputs/eq.mdp'
    md = stages / '4_CG_sim/inputs/md.mdp'
    assert _mdp_value(eq, 'nsteps') == str(round(settings['cg_equil_ps'] / 0.005))
    assert _mdp_value(md, 'nsteps') == str(round(settings['cg_production_ps'] / 0.02))
    assert float(_mdp_value(md, 'ref-t')) == settings['temperature_k']
    assert int(_mdp_value(md, 'gen-seed')) == settings['cg_seed']

    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['run_type'] == 'cg' and manifest['execution_kind'] == 'cg-simulation'
    assert manifest['composition_id'] == saved['id'] and manifest['composition_identity'] == saved['identity']
    assert manifest['parameterization'] == {'kind': 'composition', 'composition_id': saved['id'],
                                            'molecule_id': saved['id'], 'head_molecule_id': None}
    assert manifest['cg_names'] == {'residue_name': 'GLC', 'initial_itp': 'GLC.itp', 'final_itp': 'GLC.itp'}
    assert manifest['stage_plan'] == [name for name, _ in composition.STAGES]
    assert manifest['scientifically_validated'] is False
    assert any('not fitted' in limitation for limitation in manifest['limitations'])
    assert manifest['settings'] == settings
    assert manifest['mdp_profiles'] == composition.MDP_PROFILES
    # The build's inputs are named, by reference where they are immutable store files and by value where prepare
    # generated them; the input snapshot is what the executor re-verifies before each stage.
    record = json.loads((run / 'inputs/inputs.json').read_text())
    kinds = {entry['label']: entry['kind'] for entry in record['inputs']}
    assert kinds['composition.gro'] == 'store' and kinds['composition.itp'] == 'store'
    assert kinds['2_mapping/mapped.gro'] == 'generated'
    assert kinds['3_initial_CG/GLC.itp'] == 'generated'
    assert kinds['4_CG_sim/system_EMPTY.top'] == 'generated'
    assert manifest['input_snapshot_sha256'] == run_inputs.digest(record['inputs'])
    assert not list(run.rglob('*.sh')) and not list(run.rglob('*.py')), 'a run holds no code of its own'


def test_the_simulation_script_constructs_the_real_gromacs_commands(tmp_path, saved):
    """A fake `gmx` records argv: no mdrun runs, and every leg of the real CG build is constructed."""
    run = tmp_path / 'run'
    _prepare(run, saved)
    fake = tmp_path / 'bin'
    fake.mkdir()
    log = tmp_path / 'gmx.log'
    (fake / 'gmx').write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$GMX_LOG"\n')
    (fake / 'gmx').chmod(0o755)
    env = {**os.environ, 'PATH': f'{fake}{os.pathsep}{os.environ["PATH"]}',
           'PYTHON': sys.executable, 'PROJECT_ROOT': str(ROOT), 'GMX_LOG': str(log),
           'MOLECULE_TYPE': 'GLC', 'FINAL_ITP': 'GLC.itp', 'MDRUN_FLAGS': '-ntomp 4'}
    stage = run / 'stages/4_CG_sim'
    completed = subprocess.run(['bash', str(run_scripts.code_path(composition.SIMULATION_SCRIPT, root=ROOT))],
                               cwd=stage, env=env, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    commands = log.read_text().splitlines()
    assert commands[0] == 'editconf -f ../2_mapping/mapped.gro -c -d 1.5 -bt dodecahedron -o boxed.gro'
    assert any(line.startswith('solvate ') and '-p system.top' in line for line in commands)
    assert 'grompp -f inputs/minimization.mdp -p system.top -c solvated.gro -o min.tpr' in commands
    assert 'mdrun -deffnm min -ntomp 4 -v' in commands
    assert 'grompp -f inputs/eq.mdp -p system.top -c min.gro -o eq.tpr -maxwarn 1' in commands
    assert 'grompp -f inputs/md.mdp -p system.top -c eq.gro -t eq.cpt -o md.tpr -maxwarn 1' in commands
    assert 'mdrun -deffnm md -ntomp 4 -v' in commands
    assert any(line.startswith('trjconv ') and 'prod/lig_CG.xtc' in line for line in commands)
    assert 'convert-tpr -s md.tpr -o prod/lig_CG.tpr' in commands


def test_the_assessment_stage_skips_with_its_reason(tmp_path, saved):
    run = tmp_path / 'run'
    _prepare(run, saved)
    stage = run / 'stages/5_assessment'
    completed = subprocess.run(['bash', str(run_scripts.code_path(composition.ASSESSMENT_SCRIPT, root=ROOT))],
                               cwd=stage, capture_output=True, text=True, check=False)
    assert completed.returncode == 4
    assert [path.name for path in stage.iterdir()] == ['skip.json'], 'the skip record is the only file written'
    skip = json.loads((stage / 'skip.json').read_text())
    assert skip['reason'] == composition.NO_REFERENCE
    assert skip['executed'] is False and skip['scientifically_validated'] is False


def test_prepare_refuses_a_tampered_or_symlinked_artifact(tmp_path, saved):
    artifacts = compositions.artifacts(compositions.get(saved['id']))
    topology = artifacts['composition.itp']
    topology.write_text(topology.read_text() + '\n; edited after the save\n')
    with pytest.raises(ValueError, match='changed since it was saved'):
        _prepare(tmp_path / 'run', saved)

    topology.unlink()
    topology.symlink_to(artifacts['composition.gro'])
    with pytest.raises(ValueError):
        _prepare(tmp_path / 'run-two', saved)


def test_prepare_refuses_a_composition_bound_to_another_molecule(tmp_path, saved):
    with pytest.raises(ValueError, match=f'belongs to {saved["id"]}'):
        _prepare(tmp_path / 'run', saved, molecule_id='GLC')
    # Naming the composition's own molecule is the accepted case.
    _prepare(tmp_path / 'run-two', saved, molecule_id=saved['molecule_id'])
    assert (tmp_path / 'run-two/manifest.json').is_file()


def test_the_settings_are_the_cg_dialect_and_are_advertised():
    values = composition.normalize_settings({'cg_production_ps': 100, 'temperature_k': 310, 'cg_seed': 7},
                                            'draft-smoke-reference')
    assert values['cg_production_ps'] == 100.0 and values['temperature_k'] == 310.0 and values['cg_seed'] == 7
    assert values['mdrun_ntomp'] == 8 and values['mdrun_ranks'] == 1
    # A composition has no AA half: the AA durations and the AA-only probe are not its vocabulary.
    for key in ('aa_equil_ps', 'aa_production_ps', 'sasa_probe_nm', 'box_nm', 'force_field'):
        assert key not in composition.SETTING_SPECS, key
    with pytest.raises(ValueError, match='Unknown composition CG setting: aa_production_ps'):
        composition.normalize_settings({'aa_production_ps': 10})
    with pytest.raises(ValueError, match='Trajectory interval must not exceed the CG production duration'):
        composition.normalize_settings({'cg_production_ps': 5, 'output_interval_ps': 10})
    # The run type's one form advertises the union, so the route keeps these keys.
    specs = cg_run.PROTOCOL.settings_specs()
    for key in ('cg_equil_ps', 'cg_production_ps', 'temperature_k', 'cg_seed', 'mdrun_ntomp'):
        assert key in specs, key
    assert {'mdrun_nb', 'mdrun_pme'} <= set(cg_run.PROTOCOL.choice_specs())
    profile = protocol.profile_for_run_type('cg')
    defaults = cg_run.defaults_for('composition')
    assert defaults['values']['cg_production_ps'] == cg.stage_defaults(profile)['values']['cg_production_ps']
