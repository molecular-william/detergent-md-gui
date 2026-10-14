"""The equilibration legs the protein-detergent pipeline gained in front of its assessment leg.

The protocol went from the built system straight into 100 ns of CG MD. Change 2 of the new-run panel plan
(`docs/superpowers/plans/2026-10-12-pdc-new-run-panel.md`, task T7) puts the standard sequence in front of it --
energy minimisation, then NVT, then NPT -- as stages of their own with their own mdp templates, so a leg is in the
run's record rather than buried in the assessment script's body, and a leg the run asks for none of records
`skipped` (exit 4) with its reason instead of quietly disappearing from the chain.

What is pinned here is the plan's order, the templates' own physics (the standing 5 fs equilibration timestep), the
chain a leg reads its system from, and the skip contract each leg keeps.

The tests build their own molecule tree; nothing here reads the developer's workspace.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from dashboard.execution.adapters import pdc
from dashboard.execution.environment import ROOT

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


def molecule_tree(tmp_path: Path) -> Path:
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text('[ moleculetype ]\nDDM             1\n')
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    (molecule / 'protein.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')
    return tmp_path


def prepared(tmp_path: Path, **settings):
    root = molecule_tree(tmp_path)
    numbers = {'seed': 20260930, 'aggregation_number': 8}
    numbers.update(settings)
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, protein=PROTEIN, template=TEMPLATE_PATH, settings=numbers, project_root=root)
    return run


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
    return run / Path(stage(name).relative).parent


def test_the_plan_gains_one_pair_per_step_in_order_before_the_assessment_leg():
    plan = [record.name for record in pdc.STAGES]

    assert plan == ['Protein preparation', 'System preparation', *LEGS, ASSESSMENT, 'Micelle assessment',
                    'CG extension MD', 'Final assessment', 'Back-mapping (CG2AT2)'], \
        'one pair per step, in order, before the assessment'
    order = {name: index for index, name in enumerate(plan)}
    assert order['Energy minimisation'] < order['NVT equilibration'] < order['NPT equilibration'] < order[ASSESSMENT]
    assert order['Protein preparation'] < order['System preparation'], \
        "the plan's step 1 landed in front of the build, not behind it"


def test_the_prepare_step_stands_in_front_of_the_chain_and_the_legs_keep_their_places():
    """The plan's step 1 landed after these tests were written, so the order it was written against is kept.

    Its own file pins the step itself (`test_pdc_prepare_step.py`); this is the half that belongs to this chain: the
    legs and the assessment still follow each other, with one step in front of the system build.
    """
    order = {record.name: index for index, record in enumerate(pdc.STAGES)}

    assert order['Protein preparation'] < order['System preparation'] < order[ASSESSMENT]
    assert order['Energy minimisation'] < order['NVT equilibration'] < order['NPT equilibration']


def test_every_stage_name_that_existed_before_is_still_here_with_its_own_directory():
    relative = {record.name: record.relative for record in pdc.STAGES}

    assert relative['System preparation'] == '1_system/prepare_system.sh'
    for name, path in (('CG assessment MD', '2_assessment/pdc_assessment.sh'),
                       ('Micelle assessment', '3_assessment/pdc_assess.sh'),
                       ('CG extension MD', '4_extension/pdc_extension.sh'),
                       ('Final assessment', '5_assessment/pdc_assess.sh'),
                       ('Back-mapping (CG2AT2)', '6_backmap/pdc_backmap.sh')):
        assert relative[name] == path, 'each stage keeps its own directory, and runs a script this workflow owns'


def test_each_leg_runs_its_own_mdp_template_from_the_resources(tmp_path):
    run = prepared(tmp_path)

    for name, mdp in (('Energy minimisation', 'minimisation.mdp'), ('NVT equilibration', 'nvt.mdp'),
                      ('NPT equilibration', 'npt.mdp')):
        template = TEMPLATE_DIR / mdp
        assert template.is_file(), f'{mdp} is the leg template and lives under resources/templates/'
        assert (leg_directory(run, name) / mdp).is_file(), f'{name} declares {mdp} and it is not beside its script'
        # The adapter stamps the run's own numbers into the copy; everything else is the template's, verbatim.
        prepared_numbers = mdp_numbers(leg_directory(run, name) / mdp)
        template_numbers = mdp_numbers(template)
        for key in ('integrator', 'dt', 'rlist', 'rcoulomb', 'rvdw', 'epsilon-r', 'ref-t', 'tcoupl'):
            assert prepared_numbers.get(key) == template_numbers.get(key), (mdp, key)


def test_the_minimisation_leg_runs_the_runs_own_step_count(tmp_path):
    default = prepared(tmp_path)
    short = prepared(tmp_path / 'short', minimisation_steps=500)

    assert int(mdp_numbers(leg_directory(default, 'Energy minimisation') / 'minimisation.mdp')['nsteps']) == 200000
    assert int(mdp_numbers(leg_directory(short, 'Energy minimisation') / 'minimisation.mdp')['nsteps']) == 500


def test_the_nvt_leg_holds_the_volume_at_the_standing_equilibration_timestep(tmp_path):
    numbers = mdp_numbers(leg_directory(prepared(tmp_path, nvt_ps=500), 'NVT equilibration') / 'nvt.mdp')

    assert float(numbers['dt']) == 0.005, '5 fs is the standing decision for the CG equilibration half'
    assert numbers['pcoupl'] == 'no' and numbers['gen-vel'] == 'yes'
    assert int(numbers['nsteps']) == round(500 / 0.005)
    assert numbers['tcoupl'] == 'v-rescale' and float(numbers['ref-t']) == 300


def test_the_npt_leg_pressures_the_system_with_the_equilibration_coupling(tmp_path):
    numbers = mdp_numbers(leg_directory(prepared(tmp_path, npt_ps=4500), 'NPT equilibration') / 'npt.mdp')

    assert float(numbers['dt']) == 0.005
    assert numbers['pcoupl'] == 'c-rescale' and float(numbers['ref-p']) == 1.0
    assert int(numbers['nsteps']) == round(4500 / 0.005)
    assert numbers['gen-vel'] == 'no', 'the NPT leg continues the NVT leg rather than re-drawing its velocities'


def test_each_leg_reads_the_system_the_leg_before_it_left(tmp_path):
    run = prepared(tmp_path)
    chain = {'Energy minimisation': '../1_system', 'NVT equilibration': '../2_minimisation',
             'NPT equilibration': '../3_nvt'}

    for name, source in chain.items():
        declared = {str(entry) for entry in stage(name).inputs}
        assert f'{source}/system.gro' in declared and f'{source}/system.top' in declared, name
        assert f'{source}/{pdc.DETERGENT_TOPOLOGY}' in declared
        script = (run / stage(name).relative).read_text()
        assert f'cp -f {source}/system.gro ' in script, f'{name} never copies in the system it equilibrates'


def test_the_legs_are_a_chain_the_skip_path_cannot_break(tmp_path):
    """A leg the run asks for none of skips, and the leg after it still has the files its own skip path reads.

    The copies are emitted from the stage's own declaration and they run before the stage's `set -e`, so a leg that
    declines to work still hands its own directory the system the next leg's validation looks for.
    """
    run = prepared(tmp_path, minimisation_steps=0, nvt_ps=0, npt_ps=0)
    # The build's artefacts, so the first leg's copy is the only thing that could be missing.
    (run / '1_system' / 'system.gro').write_text('a built system\n')
    (run / '1_system' / 'system.top').write_text('[ molecules ]\nDDM  8\n')

    for name, mdp in (('Energy minimisation', 'minimisation.mdp'), ('NVT equilibration', 'nvt.mdp'),
                      ('NPT equilibration', 'npt.mdp')):
        directory = leg_directory(run, name)
        result = subprocess.run(['bash', str(run / stage(name).relative)], cwd=directory,
                                capture_output=True, text=True)

        assert result.returncode == 4, (name, result.stdout, result.stderr)
        record = json.loads((directory / 'skip.json').read_text())
        assert record['skipped'] is True and record['reason']
        assert 'nothing to do' in record['reason']
        assert (directory / 'system.gro').is_file(), f'{name} leaves no system for the leg after it'


def test_the_skip_reason_names_the_leg_the_run_asked_none_of(tmp_path):
    run = prepared(tmp_path, minimisation_steps=0, nvt_ps=0, npt_ps=0)

    reasons = {}
    for name in LEGS:
        directory = leg_directory(run, name)
        subprocess.run(['bash', str(run / stage(name).relative)], cwd=directory, capture_output=True, text=True)
        reasons[name] = json.loads((directory / 'skip.json').read_text())['reason']

    assert 'minimisation' in reasons['Energy minimisation']
    assert 'NVT' in reasons['NVT equilibration'] and 'minimisation' not in reasons['NVT equilibration']
    assert 'NPT' in reasons['NPT equilibration']


def test_a_leg_that_has_work_runs_grompp_and_mdrun_without_asking_mdrun_for_thread_mpi_ranks(tmp_path):
    run = prepared(tmp_path)

    for name, mdp in (('Energy minimisation', 'minimisation.mdp'), ('NVT equilibration', 'nvt.mdp'),
                      ('NPT equilibration', 'npt.mdp')):
        script = (run / stage(name).relative).read_text()
        executed = '\n'.join(line for line in script.splitlines() if not line.strip().startswith('#'))
        assert f'gmx grompp -f {mdp} -p system.top -c system.gro' in executed, name
        assert 'gmx mdrun -deffnm system' in executed, name
        assert '-ntmpi' not in executed, 'gmx here is an MPI-only build: -ntmpi aborts mdrun before the first step'
        assert '${MDRUN_LAUNCHER:-}' in script and '${MDRUN_FLAGS:-' in script


def test_the_minimisation_leg_solvates_through_the_builder_rather_than_restating_it(tmp_path):
    run = prepared(tmp_path)
    script = (run / stage('Energy minimisation').relative).read_text()

    assert 'python pdc_solvate.py' in script and 'gmx solvate' not in script
    assert (leg_directory(run, 'Energy minimisation') / 'pdc_solvate.py').is_file()
    assert '--salt-molar' in script, 'the run records a salt concentration and this is the leg that uses it'


def test_the_npt_leg_takes_the_nvt_legs_checkpoint_only_when_one_was_left(tmp_path):
    """The checkpoint carries the velocities the thermostat equilibrated; a leg asked for none leaves none, so it is
    read when it is there rather than declared as an input no skip path could satisfy."""
    run = prepared(tmp_path)
    script = (run / stage('NPT equilibration').relative).read_text()
    declared = {str(entry) for entry in stage('NPT equilibration').inputs}

    assert 'if [ -f ../3_nvt/system.cpt ]' in script
    assert not any(entry.endswith('system.cpt') for entry in declared)


def test_the_mdp_a_leg_declares_is_the_one_its_script_runs(tmp_path):
    """The declaration, the script builder and the template all name one mdp; nothing here guesses a filename."""
    run = prepared(tmp_path)

    for name, leg in pdc.LEGS.items():
        declared = {str(entry) for entry in stage(name).inputs}
        assert leg['mdp'] in declared, (name, leg['mdp'])
        assert leg['mdp'] in (run / stage(name).relative).read_text(), name


def test_the_run_record_carries_the_legs_step_counts(tmp_path):
    record = json.loads((prepared(tmp_path, minimisation_steps=500, nvt_ps=100, npt_ps=100) / 'manifest.json').read_text())

    assert record['equilibration_steps'] == {'minimisation': 500, 'nvt': round(100 / 0.005),
                                            'npt': round(100 / 0.005)}
    assert record['stage_plan'][0][0] == 'Protein preparation'
    assert record['stage_plan'][2][0] == 'Energy minimisation', \
        'the legs start after the system build, and the plan says so by name'
