"""The assessment leg is production only, and it samples the system the NPT leg left.

Measured before this change: the stage script solvated the built system, minimised it and equilibrated it before its
100 ns of production -- exactly the work the three legs the plan gained in front of it now do. A pdc run therefore
equilibrated twice, and the legs' output fed nothing: the phase that was supposed to read it re-derived the system
from `02_system/` instead.

What is pinned here: the shared script runs one `grompp` and one `mdrun` and nothing else, its declared inputs are the
NPT leg's system, the solvation and equilibration inputs it used to carry are gone, and a run whose legs all skip is a
run whose stages have no directories at all -- the manifest, not a stage, records the skip.
"""
from __future__ import annotations

import json
from pathlib import Path

from detergent_pdc.execution.adapters import pdc

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


def prepared(tmp_path: Path, **settings) -> Path:
    return prepared_run(tmp_path, settings=settings)


def executed(script: Path) -> str:
    """A stage script's lines minus its comments: what the stage actually runs."""
    return '\n'.join(line for line in script.read_text().splitlines() if not line.strip().startswith('#'))


def test_the_assessment_leg_solvates_minimises_and_equilibrates_nothing():
    lines = executed(script_of(ASSESSMENT))

    assert 'pdc_solvate' not in lines and 'gmx solvate' not in lines, "solvation is the minimisation leg's"
    assert 'minimisation.mdp' not in lines and 'minimization.mdp' not in lines
    assert 'equilibration.mdp' not in lines, 'the three legs in front of this stage are the equilibration'
    assert lines.count('gmx grompp') == 1 and lines.count('gmx mdrun') == 1, 'one production run, and one only'
    assert 'assessment.mdp' in lines


def test_the_assessment_leg_declares_the_system_the_npt_leg_left():
    declared = {str(entry) for entry in pdc.stage_by_name(ASSESSMENT).inputs}

    assert {'../05_npt/system.gro', '../05_npt/system.top'} <= declared, declared
    assert f'../02_system/{pdc.PROTEIN_TOPOLOGY_DIRECTORY}/' in declared
    # The detergent's topology is the run's generated `inputs/detergent_CG.itp`, already a recorded input and verified
    # before every stage -- so this stage declares neither a copy nor a path for it.
    assert not any(str(entry).endswith(pdc.DETERGENT_TOPOLOGY) for entry in declared)
    # The stage is handed the NPT system by its own copy, not by a prepare-time prelude.
    assert 'cp -f ../05_npt/system.gro ../05_npt/system.top' in script_of(ASSESSMENT).read_text()


def test_the_assessment_leg_no_longer_re_derives_the_system_from_the_build():
    declared = {str(entry) for entry in pdc.stage_by_name(ASSESSMENT).inputs}

    assert [entry for entry in declared if entry.startswith('../02_system/')] == \
        [f'../02_system/{pdc.PROTEIN_TOPOLOGY_DIRECTORY}/'], \
        'only the protein tree is shared from the build; the system itself comes from the NPT leg'


def test_the_assessment_stage_carries_no_solvation_or_equilibration_inputs(tmp_path):
    """The restart mdps are the extension's generated data; the assessment stage itself reads only its own mdp."""
    run = prepared(tmp_path)
    stage = run / pdc.STAGES_DIRECTORY / '06_assessment'
    declared = {str(entry) for entry in pdc.stage_by_name(ASSESSMENT).inputs}

    assert (inputs_dir(run) / 'assessment.mdp').is_file()
    assert list(stage.iterdir()) == [], 'the stage directory is filled by the stage, not by prepare'
    for name in ('minimization.mdp', 'equilibration.mdp', 'ions.mdp', 'water.gro'):
        assert not any(str(entry).endswith(name) for entry in declared), f'{name} is not this stage\'s input'


def test_the_assessment_leg_takes_the_npt_checkpoint_only_when_the_npt_leg_left_one():
    """The checkpoint carries the velocities the NPT leg equilibrated; a leg the run asked none of leaves none, so
    the file is read when it is there rather than declared as an input no skip path could satisfy."""
    script = script_of(ASSESSMENT).read_text()
    declared = {str(entry) for entry in pdc.stage_by_name(ASSESSMENT).inputs}

    assert 'if [ -f ../05_npt/system.cpt ]' in script
    assert not any(str(entry).endswith('system.cpt') for entry in declared)


def test_the_assessment_leg_still_writes_a_molecule_whole_trajectory():
    script = script_of(ASSESSMENT).read_text()

    assert '-pbc mol -center -o prod/whole.xtc' in script
    assert 'pdc_snapshot' not in script, 'the assessment no longer samples a snapshot series'


def test_a_run_whose_equilibration_legs_all_skip_writes_no_leg_directory(tmp_path):
    """The contract's fourth outcome at prepare time: a leg the settings say will not run leaves nothing on disk.

    The stage scripts no longer decide a settings-driven skip, so a run that asks for none of the equilibration has
    three skipped stages in its manifest, three absent directories, and the same record every other skipped stage gets.
    """
    run = prepared(tmp_path, minimisation_steps=0, nvt_ps=0, npt_ps=0)
    record = json.loads((run / 'manifest.json').read_text())

    assert set(record['skipped_stages']) >= set(LEGS)
    for name in LEGS:
        stage = pdc.stage_by_name(name)
        assert not (run / pdc.STAGES_DIRECTORY / Path(stage.relative).parent).exists(), name
        assert record['skipped_stages'][name]


def test_removal_off_folds_both_requested_durations_into_one_cg_leg(tmp_path):
    """No removal means no second leg: the assessment stage is the whole CG MD, for both requested times."""
    run = prepared(tmp_path, remove_out_of_micelle=False, assessment_ns=100, extension_ns=900)
    mdp = (inputs_dir(run) / 'assessment.mdp').read_text()
    dt = next(float(line.split('=')[1].split()[0]) for line in mdp.splitlines() if line.strip().startswith('dt'))
    nsteps = next(int(line.split('=')[1].split()[0]) for line in mdp.splitlines() if line.strip().startswith('nsteps'))

    assert dt == 0.02
    assert nsteps == 50_000_000, '100 + 900 ns at 0.02 ps is one 1 us leg, not two legs'
    record = json.loads((run / 'manifest.json').read_text())
    assert {'Micelle assessment', 'CG extension MD', 'Final assessment'} <= set(record['skipped_stages'])
    for directory in ('07_micelle_assessment', '08_extension', '09_final_assessment'):
        assert not (run / pdc.STAGES_DIRECTORY / directory).exists(), directory
    assert (inputs_dir(run) / pdc.SETTINGS_NAME).is_file(), 'the settings still record the removal choice'
