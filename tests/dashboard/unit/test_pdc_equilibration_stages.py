"""The equilibration legs the protein-detergent pipeline gained in front of its assessment leg.

The protocol went from the built system straight into 100 ns of CG MD. Change 2 of the new-run panel plan
(`docs/plans/2026-10-12-pdc-new-run-panel.md`, task T7) puts the standard sequence in front of it --
energy minimisation, then NVT, then NPT -- as stages of their own with their own mdp templates, so a leg is in the
run's record rather than buried in the assessment script's body.

The three legs run one shared repository script, `pdc_leg.sh`, and each leg's numbers travel in
`inputs/<stage directory>.json`: its mdp, the phase whose system it copies in, whether its opening act is solvation,
and the checkpoint it continues from. A leg the run asks none of gets no directory, no record and no script, and the
manifest records the skip with its reason.

What is pinned here is the plan's order, the templates' own physics (the standing 5 fs equilibration timestep), the
chain a leg reads its system from, and the skip contract each leg keeps.

The tests build their own molecule tree; nothing here reads the developer's workspace.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard.execution.adapters import pdc
from dashboard.execution.environment import ROOT

from tests.dashboard.pdc_fixtures import inputs_dir, prepared_run, script_of

TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'DDM', 'type': 'registered-template'}],
}
PROTEIN = 'molecules/DDM/protein.pdb'
TEMPLATE_PATH = 'molecules/DDM/micelle_template.json'
LEGS = ('Energy minimisation', 'NVT equilibration', 'NPT equilibration')
ASSESSMENT = 'CG assessment MD'
TEMPLATE_DIR = ROOT / 'resources' / 'templates' / 'protein_detergent'
#: The shared script every leg runs, and the phase each leg's numbers say it copies its system from.
LEG_SCRIPT = 'dashboard/execution/scripts/pdc_leg.sh'
LEG_FROM = {'Energy minimisation': '../02_system', 'NVT equilibration': '../03_minimisation',
            'NPT equilibration': '../04_nvt'}


def prepared(tmp_path: Path, **settings):
    return prepared_run(tmp_path, settings=settings)


def stage(name: str):
    """The stage record of this protocol by name; the plan's positions are data and moved when the legs landed."""
    return pdc.stage_by_name(name)


def mdp_numbers(path: Path) -> dict:
    numbers = {}
    for raw in path.read_text().splitlines():
        line = raw.split(';', 1)[0].strip()
        if '=' in line:
            name, value = (part.strip() for part in line.split('=', 1))
            numbers[name.lower().replace('_', '-')] = value
    return numbers


def leg_directory(run: Path, name: str) -> Path:
    return run / pdc.STAGES_DIRECTORY / Path(stage(name).relative).parent


def leg_record(run: Path, name: str) -> dict:
    return json.loads((inputs_dir(run) / (Path(stage(name).relative).parent.name + '.json')).read_text())


def leg_mdp(run: Path, name: str) -> Path:
    return inputs_dir(run) / leg_record(run, name)['mdp']


def test_the_plan_gains_one_pair_per_step_in_order_before_the_assessment_leg():
    plan = [record.name for record in pdc.STAGES]

    assert plan == ['Protein preparation', 'System preparation', *LEGS, ASSESSMENT, 'Micelle assessment',
                    'CG extension MD', 'Final assessment', 'Back-mapping (CG2AT2)'], \
        'one pair per step, in order, before the assessment'
    order = {name: index for index, name in enumerate(plan)}
    assert order['Energy minimisation'] < order['NVT equilibration'] < order['NPT equilibration'] < order[ASSESSMENT]
    assert order['Protein preparation'] < order['System preparation'], \
        "the plan's step 1 landed in front of the build, not behind it"


def test_every_stage_name_that_existed_before_is_still_here_with_its_own_directory():
    relative = {record.name: record.relative for record in pdc.STAGES}

    assert relative['System preparation'] == '02_system/pdc_system.sh'
    for name, path in (('CG assessment MD', '06_assessment/pdc_assessment.sh'),
                       ('Micelle assessment', '07_micelle_assessment/pdc_assess.sh'),
                       ('CG extension MD', '08_extension/pdc_extension.sh'),
                       ('Final assessment', '09_final_assessment/pdc_assess.sh'),
                       ('Back-mapping (CG2AT2)', '10_backmap/pdc_backmap.sh')):
        assert relative[name] == path, 'one directory per stage, numbered in execution order'


def test_each_leg_runs_its_own_mdp_template_from_the_resources(tmp_path):
    run = prepared(tmp_path)

    for name, mdp in (('Energy minimisation', 'minimisation.mdp'), ('NVT equilibration', 'nvt.mdp'),
                      ('NPT equilibration', 'npt.mdp')):
        template = TEMPLATE_DIR / mdp
        assert template.is_file(), f'{mdp} is the leg template and lives under resources/templates/'
        assert leg_record(run, name)['mdp'] == mdp
        written = leg_mdp(run, name)
        # The profile carries the template's physics; only the run's own numbers replace its None entries.
        prepared_numbers = mdp_numbers(written)
        template_numbers = mdp_numbers(template)
        for key in ('integrator', 'dt', 'rcoulomb', 'rvdw', 'epsilon-r', 'ref-t', 'tcoupl'):
            assert prepared_numbers.get(key) == template_numbers.get(key), (mdp, key)
        if name == 'Energy minimisation':
            # Nothing is integrated, so this leg keeps the template's pinned list.
            assert prepared_numbers.get('rlist') == template_numbers.get('rlist')
        else:
            # The reviewed departure in `profiles.py`: 40 steps, and a buffer GROMACS sizes from the tolerance.
            assert prepared_numbers['nstlist'] == '40', mdp
            assert prepared_numbers['verlet-buffer-tolerance'] == '0.005', mdp
            assert 'rlist' not in prepared_numbers, mdp
    # Every leg's file names the reviewed profile it was written from, in the run's own record.
    profiles = json.loads((run / 'manifest.json').read_text())['mdp_profiles']
    assert profiles['minimisation.mdp'] == 'pdc-minimisation-v1'
    assert profiles['nvt.mdp'] == 'pdc-nvt-v1' and profiles['npt.mdp'] == 'pdc-npt-v1'
    # Every leg runs the one shared script, which copies `$MDP` out of `inputs/` when it starts.
    for name in LEGS:
        assert stage(name).script == LEG_SCRIPT
        assert 'cp -f "../../inputs/$MDP" .' in script_of(name).read_text()


def test_the_minimisation_leg_runs_the_runs_own_step_count(tmp_path):
    default = prepared(tmp_path)
    short = prepared(tmp_path / 'short', minimisation_steps=500)

    assert int(mdp_numbers(leg_mdp(default, 'Energy minimisation'))['nsteps']) == 200000
    assert int(mdp_numbers(leg_mdp(short, 'Energy minimisation'))['nsteps']) == 500


def test_the_nvt_leg_holds_the_volume_at_the_standing_equilibration_timestep(tmp_path):
    numbers = mdp_numbers(leg_mdp(prepared(tmp_path, nvt_ps=500), 'NVT equilibration'))

    assert float(numbers['dt']) == 0.005, '5 fs is the standing decision for the CG equilibration half'
    assert numbers['pcoupl'] == 'no' and numbers['gen-vel'] == 'yes'
    assert int(numbers['nsteps']) == round(500 / 0.005)
    assert numbers['tcoupl'] == 'v-rescale' and float(numbers['ref-t']) == 300


def test_the_npt_leg_pressures_the_system_with_the_equilibration_coupling(tmp_path):
    numbers = mdp_numbers(leg_mdp(prepared(tmp_path, npt_ps=4500), 'NPT equilibration'))

    assert float(numbers['dt']) == 0.005
    assert numbers['pcoupl'] == 'c-rescale' and float(numbers['ref-p']) == 1.0
    assert int(numbers['nsteps']) == round(4500 / 0.005)
    assert numbers['gen-vel'] == 'no', 'the NPT leg continues the NVT leg rather than re-drawing its velocities'


def test_each_leg_reads_the_system_the_leg_before_it_left(tmp_path):
    run = prepared(tmp_path)

    for name, source in LEG_FROM.items():
        declared = {str(entry) for entry in stage(name).inputs}
        assert f'{source}/system.gro' in declared and f'{source}/system.top' in declared, name
        # The detergent's topology and the protein's tree are read where the run keeps them -- `inputs/` and the build
        # stage -- so a leg declares the tree and never a copy of either.
        assert f'{source}/{pdc.DETERGENT_TOPOLOGY}' not in declared, name
        assert f'../02_system/{pdc.PROTEIN_TOPOLOGY_DIRECTORY}/' in declared, name
        assert leg_record(run, name)['from'] == source
        script = script_of(name).read_text()
        assert 'cp -f "$FROM/system.gro" "$FROM/system.top"' in script, f'{name} never copies in the system it equilibrates'


def test_a_leg_the_settings_skip_gets_no_directory_and_the_manifest_says_why(tmp_path):
    """The contract's fourth outcome is decided at prepare time now, not by a stage script.

    A leg the run asks for none of gets no directory, no script, no `skip.json` and no generated record; the run's
    manifest carries the stage's name and the reason, and the executor records it skipped without writing anything.
    """
    run = prepared(tmp_path, minimisation_steps=0, nvt_ps=0, npt_ps=0)
    record = json.loads((run / 'manifest.json').read_text())

    reasons = record['skipped_stages']
    assert 'minimisation' in reasons['Energy minimisation']
    assert 'NVT' in reasons['NVT equilibration'] and 'minimisation' not in reasons['NVT equilibration']
    assert 'NPT' in reasons['NPT equilibration']
    for name in LEGS:
        directory = leg_directory(run, name)
        assert not directory.exists(), name
        assert not (inputs_dir(run) / (Path(stage(name).relative).parent.name + '.json')).exists()
        assert not (inputs_dir(run) / leg_record_name(name)).exists()


def leg_record_name(name: str) -> str:
    return Path(stage(name).relative).parent.name + '.json'


def test_a_leg_that_has_work_runs_grompp_and_mdrun_without_asking_mdrun_for_thread_mpi_ranks(tmp_path):
    prepared(tmp_path)
    script = script_of('Energy minimisation').read_text()
    executed = '\n'.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert 'gmx grompp -f "$MDP" -p system.top -c system.gro' in executed
    assert 'gmx mdrun -deffnm system' in executed
    assert '-ntmpi' not in executed, 'gmx here is an MPI-only build: -ntmpi aborts mdrun before the first step'
    assert '${MDRUN_LAUNCHER:-}' in script and '${MDRUN_FLAGS:-' in script


def test_the_minimisation_leg_solvates_through_the_builder_rather_than_restating_it(tmp_path):
    run = prepared(tmp_path)
    script = script_of('Energy minimisation').read_text()

    assert 'dashboard.execution.scripts.pdc_solvate' in script and 'gmx solvate' not in script
    assert '--salt-molar' in script, 'the run records a salt concentration and this is the leg that uses it'
    assert leg_record(run, 'Energy minimisation')['solvate'] is True
    assert leg_record(run, 'NVT equilibration')['solvate'] is False


def test_the_npt_leg_takes_the_nvt_legs_checkpoint_only_when_one_was_left(tmp_path):
    """The checkpoint carries the velocities the thermostat equilibrated; a leg asked for none leaves none, so it is
    read when it is there rather than declared as an input no skip path could satisfy."""
    run = prepared(tmp_path)
    script = script_of('NPT equilibration').read_text()
    declared = {str(entry) for entry in stage('NPT equilibration').inputs}

    assert leg_record(run, 'NPT equilibration')['checkpoint'] == '../04_nvt/system.cpt'
    assert 'if [ -n "$CHECKPOINT_FILE" ] && [ -f "$CHECKPOINT_FILE" ]' in script
    assert not any(entry.endswith('system.cpt') for entry in declared)


def test_the_mdp_a_leg_declares_is_the_one_its_record_names(tmp_path):
    """The declaration, the generated record and the shared script all name one mdp; nothing here guesses a filename."""
    run = prepared(tmp_path)

    for name, leg in pdc.LEGS.items():
        declared = {str(entry) for entry in stage(name).inputs}
        assert f'../../inputs/{leg["mdp"]}' in declared, (name, leg['mdp'])
        assert leg_record(run, name)['mdp'] == leg['mdp']


def test_the_run_record_carries_the_legs_step_counts(tmp_path):
    record = json.loads((prepared(tmp_path, minimisation_steps=500, nvt_ps=100, npt_ps=100) / 'manifest.json').read_text())

    assert record['equilibration_steps'] == {'minimisation': 500, 'nvt': round(100 / 0.005),
                                            'npt': round(100 / 0.005)}
    assert record['stage_plan'][0][0] == 'Protein preparation'
    assert record['stage_plan'][2][0] == 'Energy minimisation', \
        'the legs start after the system build, and the plan says so by name'
