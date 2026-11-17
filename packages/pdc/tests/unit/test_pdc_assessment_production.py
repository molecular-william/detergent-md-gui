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

from tests.harness.pdc_fixtures import inputs_dir, prepared_run, script_of

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
    fresh = '\n'.join(line for line in lines.splitlines() if '-cpi' not in line)
    assert fresh.count('gmx grompp') == 1 and fresh.count('gmx mdrun') == 1, \
        'one production run, and one only; the resume branch continues that same run'
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


def test_the_assessment_and_the_extension_share_the_shared_production_physics(tmp_path):
    """The two production files are written from the same profile, so one physics set reaches both.

    Their own durations stay their own: the extension still asks for `round(extension_ps / dt)` steps.
    """
    run = prepared(tmp_path, assessment_ns=100, extension_ns=900,
                   pdc_production_nstlist=80, pdc_production_ref_t=320, pdc_production_tau_t=2.0,
                   pdc_production_ref_p=2.0, pdc_production_tau_p=20.0,
                   pdc_production_compressibility=1e-4, pdc_extension_dt_fs=25)
    assessment = mdp_numbers(inputs_dir(run) / 'assessment.mdp')
    extension = mdp_numbers(inputs_dir(run) / 'extension.mdp')

    for key, value in (('nstlist', '80'), ('ref-t', '320'), ('tau-t', '2'), ('ref-p', '2'), ('tau-p', '20')):
        assert assessment[key] == extension[key] == value, key
    assert float(assessment['compressibility']) == float(extension['compressibility']) == 1e-4
    assert int(extension['nsteps']) == round(900_000 / 0.025), 'the extension keeps its own duration at its dt'
    assert int(assessment['nsteps']) == round(100_000 / 0.02)


def mdp_numbers(path: Path) -> dict:
    numbers = {}
    for raw in path.read_text().splitlines():
        line = raw.split(';', 1)[0].strip()
        if '=' in line:
            name, value = (part.strip() for part in line.split('=', 1))
            numbers[name.lower().replace('_', '-')] = value
    return numbers


def test_the_assessment_leg_integrates_at_its_own_timestep(tmp_path):
    run = prepared(tmp_path, assessment_ns=100, pdc_assessment_dt_fs=10)
    numbers = mdp_numbers(inputs_dir(run) / 'assessment.mdp')

    assert float(numbers['dt']) == 0.01
    assert int(numbers['nsteps']) == round(100_000 / 0.01)


def test_removal_off_folds_both_durations_at_the_assessment_timestep(tmp_path):
    """The one plain CG leg covers both requested times, and the assessment's dt converts the folded duration."""
    run = prepared(tmp_path, remove_out_of_micelle=False, assessment_ns=100, extension_ns=900,
                   pdc_assessment_dt_fs=10)
    numbers = mdp_numbers(inputs_dir(run) / 'assessment.mdp')

    assert float(numbers['dt']) == 0.01
    assert int(numbers['nsteps']) == round(1_000_000 / 0.01)


def test_the_extension_timestep_reaches_only_the_restarted_system(tmp_path):
    """The assessment keeps its own dt; `extension.mdp` is the restart's file, at the extension's dt and duration.

    The continue path extends the assessment tpr (`extension.ps`), so it keeps the assessment's dt -- the user chose
    that -- and only a restart, which rebuilds the system, reads `extension.mdp`.
    """
    run = prepared(tmp_path, assessment_ns=100, extension_ns=900,
                   pdc_assessment_dt_fs=10, pdc_extension_dt_fs=25)
    assessment = mdp_numbers(inputs_dir(run) / 'assessment.mdp')
    extension = mdp_numbers(inputs_dir(run) / 'extension.mdp')

    assert float(assessment['dt']) == 0.01 and int(assessment['nsteps']) == round(100_000 / 0.01)
    assert float(extension['dt']) == 0.025
    assert int(extension['nsteps']) == round(900_000 / 0.025), 'the restart duration at its own dt'
    assert (inputs_dir(run) / 'extension.ps').read_text().strip() == '900000', \
        'convert-tpr takes the extension duration itself, not a step count'
