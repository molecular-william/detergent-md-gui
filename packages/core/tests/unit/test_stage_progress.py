"""How far a script stage has got: legs counted, and the step within the current one.

`cg_simulation.sh` runs three mdrun legs in a row, and `ff_assess` prints no step at all. GROMACS' own "remaining wall
clock time" describes one leg, so for two thirds of a three-leg stage the run card has nothing to show; these tests pin
the counting that fills that gap, against logs shaped like the ones the stages actually write (the step block uses
carriage returns, and `grompp` lines carry the mdp each leg was built from).
"""
import os
from pathlib import Path

from dashboard.web.progress import progress_from_file

THREE_LEGS = """\
+ gmx grompp -f inputs/minimization.mdp -p system.top -c solvated.gro -o min.tpr
+ gmx mdrun -deffnm min -ntomp 8
starting mdrun 'DDM draft in pure water'
step 0
step 100, remaining wall clock time: 28 s
Finished mdrun on rank 0
+ gmx grompp -f inputs/eq.mdp -p system.top -c min.gro -o eq.tpr
+ gmx mdrun -deffnm eq -ntomp 8
starting mdrun 'DDM draft in pure water'
step 0
+ gmx grompp -f inputs/md.mdp -p system.top -c eq.gro -o md.tpr -t eq.cpt
+ gmx mdrun -deffnm md -ntomp 8
starting mdrun 'DDM draft in pure water'
step 0
step 100, remaining wall clock time:    9 s
step 200, remaining wall clock time:    8 s
"""

MDPS = {'minimization.mdp': 'integrator = steep\nnsteps = 500\n',
        'eq.mdp': 'nsteps = 10000\ndt = 0.01\n', 'md.mdp': 'nsteps = 400\ndt = 0.01\n'}


def log_reading(stage_name, directory, text):
    """One reading of a log on disk: the shape every stage's log reaches the dashboard in."""
    path = Path(directory) / 'log.txt'
    path.write_text(text)
    return progress_from_file(stage_name, directory, path)


def stage_dir(tmp_path):
    inputs = tmp_path / 'inputs'
    inputs.mkdir(exist_ok=True)
    for name, text in MDPS.items():
        (inputs / name).write_text(text)
    return tmp_path


def test_three_legs_count_to_the_step_within_the_last_one(tmp_path):
    """Two legs done and half of the third is 83%, and the reading names the leg it came from."""
    reading = log_reading('CG simulation', stage_dir(tmp_path), THREE_LEGS)
    assert (reading['stage'], reading['leg'], reading['legs']) == ('CG simulation', 'md', 3)
    assert reading['step'] == 200 and reading['steps'] == 400 and reading['measured'] is True
    assert reading['percent'] == 83, reading
    # eq ran 10 000 steps at 10 fs, then md printed 200 at the same timestep; minimisation contributes no time.
    assert reading['ns_done'] == 0.102, reading


def test_a_leg_with_no_reading_yet_reports_the_legs_already_done(tmp_path):
    """A leg that has not printed a step yet is *running*: no number is claimed, and `0` is not guessed at."""
    log = ("+ gmx grompp -f inputs/minimization.mdp -p system.top -c solvated.gro -o min.tpr\n"
           "+ gmx mdrun -deffnm min\nstarting mdrun 'x'\n")
    reading = log_reading('CG simulation', stage_dir(tmp_path), log)
    assert (reading['leg'], reading['legs'], reading['measured']) == ('min', 1, False), reading
    assert reading['percent'] is None, reading
    # Once the counter prints, the leg has a fraction: this log holds one leg, so 100 of its 500 steps is a fifth.
    reading = log_reading('CG simulation', stage_dir(tmp_path),
                          log + 'step 0\nstep 100, remaining wall clock time: 3 s\n')
    assert reading['percent'] == 20, reading


def test_a_leg_whose_mdp_cannot_be_read_falls_back_to_the_legs_already_done(tmp_path):
    """An unknown length is not a finished leg: the fraction within the leg is dropped, the legs are not."""
    reading = log_reading('CG simulation', tmp_path, THREE_LEGS)
    assert (reading['legs'], reading['measured'], reading['percent']) == (3, False, 67), reading


def test_a_stage_with_no_mdrun_legs_has_nothing_to_count(tmp_path):
    """`assess.sh` runs a tool that prints no steps; the panel says "running" rather than inventing a fraction."""
    assert log_reading('CG assessment (ff_assess)', tmp_path, '+ ff_assess -f x.xtc -s x.gro\n') == {}


def test_a_resumed_leg_is_read_from_the_log_it_was_given(tmp_path):
    """The count is a reading of one log file and the mdp lengths it names; nothing else on disk is consulted."""
    log = THREE_LEGS + 'step 300, remaining wall clock time: 1 s\n'
    reading = log_reading('CG simulation', stage_dir(tmp_path), log)
    assert reading['percent'] == 92, reading
    assert Path(reading['leg']).name == 'md'


def test_an_appended_log_reads_only_the_new_lines_and_agrees_with_a_full_scan(tmp_path):
    """A poll after an append counts the new leg and steps exactly as a fresh pass over the whole file would."""
    directory = stage_dir(tmp_path)
    path = directory / 'log.txt'
    # The first write ends mid-line: the trailing partial line must already be counted, and the append must complete
    # it rather than count it twice.
    path.write_text('+ gmx grompp -f inputs/eq.mdp -p system.top -c solvated.gro -o eq.tpr\n'
                    '+ gmx mdrun -deffnm eq -ntomp 8\n'
                    'step 0\n'
                    'step 100')
    first = progress_from_file('CG simulation', directory, path)
    assert (first['leg'], first['step'], first['legs']) == ('eq', 100, 1), first

    path.write_text(path.read_text()
                    + '\nstep 200, remaining wall clock time: 4 s\n'
                    + '+ gmx grompp -f inputs/md.mdp -p system.top -c eq.gro -o md.tpr\n'
                    + '+ gmx mdrun -deffnm md -ntomp 8\n'
                    + "starting mdrun 'x'\n"
                    + 'step 0\nstep 40, remaining wall clock time: 2 s\n')
    incremental = progress_from_file('CG simulation', directory, path)

    fresh_path = directory / 'fresh.log'
    fresh_path.write_text(path.read_text())
    fresh = progress_from_file('CG simulation', directory, fresh_path)
    assert incremental == fresh
    assert (incremental['leg'], incremental['step'], incremental['legs']) == ('md', 40, 2), incremental


def test_a_truncated_or_replaced_log_is_rescanned_not_continued(tmp_path):
    """A rewrite is a new file, not an append: its readings start again even when the path is the same."""
    directory = stage_dir(tmp_path)
    path = directory / 'log.txt'
    path.write_text(THREE_LEGS)
    assert progress_from_file('CG simulation', directory, path)['legs'] == 3

    shorter = ('+ gmx grompp -f inputs/minimization.mdp -p system.top -c solvated.gro -o min.tpr\n'
               '+ gmx mdrun -deffnm min\nstep 0\nstep 10\n')
    path.write_text(shorter)
    truncated = progress_from_file('CG simulation', directory, path)
    assert (truncated['legs'], truncated['leg']) == (1, 'min'), truncated

    replacement = directory / 'replacement.log'
    replacement.write_text(THREE_LEGS)
    os.replace(replacement, path)
    replaced = progress_from_file('CG simulation', directory, path)
    assert (replaced['legs'], replaced['leg']) == (3, 'md'), replaced


def test_two_polls_with_no_write_are_identical(tmp_path):
    """An unchanged file costs no read and its reading must not drift, including the trailing partial line."""
    directory = stage_dir(tmp_path)
    path = directory / 'log.txt'
    path.write_text(THREE_LEGS + 'step 300')
    first = progress_from_file('CG simulation', directory, path)
    second = progress_from_file('CG simulation', directory, path)
    assert first == second
    assert first['step'] == 300, first
