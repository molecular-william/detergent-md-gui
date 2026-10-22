"""Progress and the ETA read the log that has GROMACS in it, not the one the manifest happens to name.

A live AA-to-CG run showed the failure this pins: `progress: {}` and no ETA on a run whose own
`logs/4_CG_sim.log` said 93% of the third leg with 94 s remaining. The stage entry recorded
`logs/console.log` -- a file that exists, is readable, and carries none of GROMACS' output -- and the reader took the
first file that opened.

Existence is not evidence. Prepare records the run's console log against a stage that has not started, and `run()`
replaces it with the stage's own file, so a run prepared one way and executed another records the wrong one and both
files exist. These tests build exactly that shape and require the reader to choose by content.
"""

import pytest

from dashboard.web import views

STAGE_LOG = '\n'.join([
    '+ gmx grompp -f inputs/min.mdp -o min.tpr',
    '+ gmx mdrun -deffnm min -ntomp 8',
    'Steepest Descents converged to Fmax < 1000',
    '+ gmx grompp -f inputs/eq.mdp -o eq.tpr',
    '+ gmx mdrun -deffnm eq -ntomp 8',
    '+ gmx grompp -f inputs/md.mdp -o md.tpr',
    '+ gmx mdrun -deffnm md -ntomp 8',
    'starting mdrun',
    'step 500',
    'remaining wall clock time: 94.2 s',
]) + '\n'
CONSOLE_LOG = 'queued CG simulation\nconsole chatter with no step counter\n'


@pytest.fixture
def run_dir(tmp_path):
    # Under `runs/<id>/` because a recorded log is an absolute path anchored on the last `runs/<id>` pair; without that
    # shape `resolve_stage_log` refuses it and the fixture would not be the case this file is about.
    run = tmp_path / 'runs' / 'ce1318485197'
    (run / 'logs').mkdir(parents=True)
    stage = run / 'stages' / '4_CG_sim' / 'inputs'
    stage.mkdir(parents=True)
    (stage / 'md.mdp').write_text('integrator = md\nnsteps = 1000\n')
    (run / 'logs' / 'console.log').write_text(CONSOLE_LOG)
    (run / 'logs' / '4_CG_sim.log').write_text(STAGE_LOG)
    return run


def stage_records(run, log_name='console.log'):
    """The shape the manifest holds: the running stage, naming one log -- here the console one."""
    return {'run_type': 'aa_cg', 'status': 'running', 'id': run.name}, [
        {'name': 'CG simulation', 'status': 'running', 'log': str(run / 'logs' / log_name)}]


def test_progress_reads_the_stage_log_when_the_recorded_one_is_the_console_log(run_dir):
    job, stages = stage_records(run_dir)
    reading = views.progress(job, stages, run_dir=run_dir)
    assert reading['legs'] == 3 and reading['leg'] == 'md'
    assert reading['measured'] is True
    # two legs done of three, and half of the third leg's 1000 steps
    assert reading['percent'] == 83


def test_the_eta_comes_from_the_log_that_states_one(run_dir):
    job, stages = stage_records(run_dir)
    assert views.eta(job, stages, run_dir=run_dir)['gromacs_remaining_seconds'] == pytest.approx(94.2)


def test_a_stage_with_no_legs_anywhere_reports_nothing_rather_than_a_zero(run_dir):
    """Unchanged where it was right: a tool stage declares no legs, and the bar says "running", never 0%."""
    (run_dir / 'logs' / '4_CG_sim.log').write_text('ff_assess: reading mapped.xtc\n')
    job, stages = stage_records(run_dir)
    assert views.progress(job, stages, run_dir=run_dir) == {}
    assert views.eta(job, stages, run_dir=run_dir) == {}


def test_the_console_tail_still_reads_the_recorded_file(run_dir):
    """The console panel is not this fix's business: it shows the file the writer named, legs or no legs."""
    job, stages = stage_records(run_dir)
    current, stage_dir = views.running_stage(job, stages)
    path = views.stage_log_file(job, current, stage_dir, run_dir=run_dir)
    assert path == run_dir / 'logs' / 'console.log'
    assert 'console chatter' in views.stage_log(job, current, stage_dir, run_dir=run_dir)


def test_a_manifest_that_names_no_log_at_all_still_finds_the_stage_log(run_dir):
    job, stages = stage_records(run_dir, log_name='../nowhere.log')
    stages[0].pop('log')
    reading = views.progress(job, stages, run_dir=run_dir)
    assert reading['percent'] == 83


# A protein-detergent stage announces its leg the same way -- `+ gmx mdrun -deffnm system` under `set -x` -- but its
# directory sits at the run root (`2_minimisation/`), not under `stages/`. The reader looked only under `stages/`, so
# the mdp whose `nsteps` the step counter is divided by was never found, `percent` stayed `None`, and the bar on a
# running pdc build could not move however many steps it printed.
PDC_LOG = '\n'.join([
    '+ gmx grompp -f minimisation.mdp -p system.top -c system.gro -o system.tpr -maxwarn 1',
    '+ gmx mdrun -deffnm system -ntomp 8 -v',
    'starting mdrun',
    'step 50000',
]) + '\n'


@pytest.fixture
def pdc_run_dir(tmp_path):
    run = tmp_path / 'runs' / '5f9296d00cf0'
    (run / 'logs').mkdir(parents=True)
    stage = run / '2_minimisation'
    stage.mkdir()
    (stage / 'minimisation.mdp').write_text('integrator = steep\nnsteps = 200000\n')
    (run / 'logs' / '2_minimisation.log').write_text(PDC_LOG)
    return run


def test_a_protein_detergent_stage_is_measured_where_its_mdp_lives(pdc_run_dir):
    job = {'run_type': 'pdc', 'status': 'running', 'id': pdc_run_dir.name}
    stages = [{'name': 'Energy minimisation', 'status': 'running',
               'log': str(pdc_run_dir / 'logs' / '2_minimisation.log')}]

    reading = views.progress(job, stages, run_dir=pdc_run_dir)

    assert reading['leg'] == 'system' and reading['legs'] == 1
    assert reading['step'] == 50000 and reading['steps'] == 200000
    assert reading['percent'] == 25
    assert reading['measured'] is True


def test_the_stage_directory_is_found_in_either_spelling(pdc_run_dir, run_dir):
    assert views.stage_directory(pdc_run_dir, '2_minimisation') == pdc_run_dir / '2_minimisation'
    assert views.stage_directory(run_dir, '4_CG_sim') == run_dir / 'stages' / '4_CG_sim'
