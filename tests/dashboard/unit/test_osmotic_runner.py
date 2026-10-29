"""The osmotic runner: a condition resumes from its own checkpoint, and the series drives its conditions.

Three subjects, and they are different:

* **What the runner executes.** Read off the script's own non-comment lines, because the script legitimately
  names the flag it must pass in the comment that explains why -- an assertion on the whole file would pass on a
  change that removed the flag.
* **What one condition does.** A stub `gmx` fails the equilibration every time, writing a checkpoint as it dies;
  the condition's own entry into the runner then has to end `failed` after three attempts with no fourth launch.
* **What the series does.** The stage is one driver over N condition directories. A condition that fails does
  not take the ones after it with it unless the run asked to stop, and a condition that already finished is not
  entered again -- which is what makes a second entry into the series a *resume* rather than a restart.

The stub writes `eq.cpt` because that is what a real equilibration does when it dies mid-run, and it is the only
way to exercise *both* branches: attempt 1 has no checkpoint (restart cleanly) and attempts 2 and 3 resume. The
single question a stub cannot answer is whether GROMACS itself integrates -- it does not here, and these tests do
not claim it: the subject is the runner's control flow, not the engine.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest
from detergent_validation.execution.adapters import osmotic

SCRIPTS = Path(osmotic.__file__).resolve().parents[1] / 'scripts'
MAPPING = {'beads': [{'name': 'S1A', 'type': 'SP1r', 'atoms': [1, 2, 3]},
                     {'name': 'S1B', 'type': 'SP4r', 'atoms': [4, 5, 6]},
                     {'name': 'S1C', 'type': 'SP1r', 'atoms': [7, 8, 9]},
                     {'name': 'VS1', 'type': 'TC4', 'atoms': []}]}

#: A stub engine. `insert-molecules` writes the solvent the runner goes on to read; `mdrun` records each launch,
#: naming the condition directory it is working in, and fails the equilibration of the conditions named in
#: `$STUB_FAIL` after writing that condition's checkpoint. Every other subcommand succeeds; `trjconv` writes the
#: file it was asked for, because the stage's own output check reads it.
STUB = r'''#!/bin/sh
sub="$1"
condition="$(basename "$PWD")"
case "$sub" in
  insert-molecules)
    python - "$PWD" <<'PY'
import sys
from pathlib import Path

work = Path(sys.argv[1])
lines = (work / 'system.gro').read_text().splitlines()
count = int(lines[1])
atoms, box = lines[2:2 + count], lines[2 + count]
water = f'{"    1W":<10}{"W":<5}{count + 1:5d}{1.0:8.3f}{1.0:8.3f}{1.0:8.3f}'
out = lines[:2] + atoms + [water, box]
out[1] = f'{count + 1:5d}'
(work / 'solvated.gro').write_text('\n'.join(out) + '\n')
print('Added 1 molecules')
PY
    ;;
  grompp) exit 0 ;;
  trjconv)
    shift
    while [ $# -gt 0 ]; do
      [ "$1" = -o ] && : > "$2"
      shift
    done
    exit 0
    ;;
  mdrun)
    stage="$3"                       # $2 is -deffnm, $3 the stage
    echo "$condition:$stage" >> "$STUB_DIR/mdrun_calls"
    if [ "$stage" = eq ] && echo ",$STUB_FAIL," | grep -q ",$condition,"; then : > eq.cpt; exit 1; fi
    exit 0
    ;;
  *) exit 0 ;;
esac
'''


def _executed_lines(text):
    """The lines the shell actually runs, with the comment lines that explain them stripped out."""
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]


def _solute_root(tmp_path):
    root = tmp_path / 'solute'
    root.mkdir()
    (root / 'solute.gro').write_text('a written molecule\n    2\n'
                                     '    1LIG1   B01    1   1.000   1.000   1.000\n'
                                     '    1LIG1   B02    2   1.260   1.000   1.000\n'
                                     '   4.00000   4.00000   4.00000\n')
    (root / 'solute.itp').write_text('[ moleculetype ]\nLIG1 1\n\n[ atoms ]\n'
                                     '1  SP1r  1  LIG1  B01  1  0.0  36.0\n'
                                     '2  SP1r  1  LIG1  B02  1  0.0  36.0\n')
    # A tile with a real second atom line: the runner reads `lines[2]` out of this file to make its one-bead
    # insertion template, so a one-line placeholder stops the script before it ever reaches a stage.
    (root / 'water.gro').write_text('a water tile\n    2\n'
                                    '    1W   W01    1   1.000   1.000   1.000\n'
                                    '    1W   W02    2   1.500   1.500   1.500\n'
                                    '   3.64428   3.64428   3.64428\n')
    (root / 'martini_v3.0.0_solvents_v1.itp').write_text('placeholder\n')
    return root


def _prepare(tmp_path, molalities, **settings):
    """A prepared series on disk, with the stub engine beside it."""
    osmotic.prepare(tmp_path, {'molecule_id': 'Maltose', 'solute_root': str(_solute_root(tmp_path)),
                               'mapping_snapshot': MAPPING,
                               'settings': dict({'molalities': molalities}, **settings),
                               'profile': 'standard'})
    stub = tmp_path / 'gmx'
    stub.write_text(STUB)
    stub.chmod(0o755)
    return stub


def _run(tmp_path, failing=()):
    """Run the series stage for real, with the stub standing in for GROMACS.

    The stage runs the repository script, as the executor does -- `stage_scripts` names it and the stage directory is
    the working directory. It runs under the checkout's virtualenv, which is where the real executor points
    `python` (`tools.search_path` puts `.venv/bin` first), and the runner derives the checkout from the environment
    the executor sets or, by hand, from its own location.
    """
    from dashboard import paths

    stage = tmp_path / 'stages' / '01_simulate'
    venv = paths.PROJECT_ROOT / '.venv' / 'bin'
    return subprocess.run(['bash', str(SCRIPTS / 'osmotic_simulation.sh')], cwd=stage, capture_output=True,
                          text=True, check=False,
                          env={**os.environ, 'GROMACS': str(tmp_path / 'gmx'), 'MDRUN_LAUNCHER': '',
                               'STUB_DIR': str(tmp_path), 'STUB_FAIL': ','.join(failing),
                               'PATH': f'{venv}:{os.environ["PATH"]}'})


def _launches(tmp_path):
    path = tmp_path / 'mdrun_calls'
    return path.read_text().split() if path.is_file() else []


def _condition(tmp_path, directory):
    return tmp_path / 'stages' / '01_simulate' / 'conditions' / directory


def _status(tmp_path, directory):
    """The condition's own terminal record, which is what a second entry into the series reads."""
    path = _condition(tmp_path, directory) / 'condition.json'
    return json.loads(path.read_text())['status'] if path.is_file() else None


def test_the_runner_reads_its_ceiling_and_checkout_from_the_environment_and_the_run_record():
    """No per-run value is stamped into the repository script: the executor's variables and the run's own record
    carry them, so the file that runs is the file the manifest recorded."""
    executed = _executed_lines((SCRIPTS / 'osmotic_simulation.sh').read_text())
    text = '\n'.join(executed)

    assert 'RUN_SETTING_OSMOTIC_ATTEMPTS_MAX' in text
    assert 'PYTHON="${PYTHON:-python}"' in executed
    assert 'PROJECT_ROOT' in text, 'the checkout is read from the executor, not stamped'
    assert 'REPO_ROOT="."' not in text, 'the old prepare-time stamp must be gone'


def test_the_runner_resumes_a_failed_stage_from_its_own_checkpoint():
    """`-cpi <stage>.cpt` is how the pdc extension stage continues, and it is how this runner must.

    Asserted on the executed lines rather than the whole file, because the comment beside the flag names it: a bare
    `'-cpi' in text` would pass on a runner that documented the flag and never passed it.
    """
    executed = _executed_lines((SCRIPTS / 'osmotic_simulation.sh').read_text())
    mdrun = [line for line in executed if 'mdrun' in line]

    assert mdrun, 'the runner launches mdrun'
    for line in mdrun:
        assert '-cpi ' in line, line
        assert '-cpi "$stage.cpt"' in line, line
    # The comment that says what a missing checkpoint means is part of the artefact and stays.
    script = (SCRIPTS / 'osmotic_simulation.sh').read_text()
    assert 'if no checkpoint file is found' in script


@pytest.mark.slow
def test_the_third_failure_ends_the_condition_and_no_fourth_mdrun_is_launched(tmp_path):
    """The ceiling is the condition's, not the stage's: three launches of the failing stage and no more."""
    _prepare(tmp_path, [1.0])
    result = _run(tmp_path, failing=('00_1molal',))

    launches = _launches(tmp_path)
    assert launches == ['00_1molal:min', '00_1molal:eq', '00_1molal:eq', '00_1molal:eq'], launches
    assert result.returncode != 0, 'a condition whose equilibration never succeeds ends the series failed'

    attempts = json.loads((_condition(tmp_path, '00_1molal') / 'attempts.json').read_text())['attempts']
    equilibration = [record for record in attempts if record['stage'] == 'eq']
    assert [record['attempt'] for record in equilibration] == [1, 2, 3]
    assert [record['resumed'] for record in equilibration] == [False, True, True], (
        'attempt 1 found no checkpoint and restarted; the two after it resumed the one the failure wrote')
    assert all(record['checkpoint'] == 'eq.cpt' for record in equilibration)
    assert all(record['outcome'] == 'failed' for record in equilibration)
    assert all(record['attempts_max'] == osmotic.DEFAULTS['osmotic_attempts_max'] for record in attempts)
    assert [record['stage'] for record in attempts] == ['min', 'eq', 'eq', 'eq']
    assert attempts[0]['outcome'] == 'ok', 'the minimization succeeded and is recorded as such'
    assert _status(tmp_path, '00_1molal') == 'failed'


@pytest.mark.slow
def test_a_series_runs_its_conditions_one_at_a_time_in_order(tmp_path):
    """One at a time is the stage's own loop: each condition's three stages, then the next condition."""
    _prepare(tmp_path, [0.5, 1.0])
    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr[-2000:]
    assert _launches(tmp_path) == ['00_0.5molal:min', '00_0.5molal:eq', '00_0.5molal:md',
                                   '01_1molal:min', '01_1molal:eq', '01_1molal:md']
    assert [_status(tmp_path, name) for name in ('00_0.5molal', '01_1molal')] == ['complete', 'complete']


@pytest.mark.slow
def test_a_failed_condition_does_not_take_the_conditions_after_it_with_it(tmp_path):
    """`carry_on` is the series' contract, and in one run it is the driver that has to honour it.

    The failed condition is *recorded* -- it is the gap the reader shows -- and the ones after it still run.
    """
    _prepare(tmp_path, [0.5, 1.0, 1.5])
    result = _run(tmp_path, failing=('01_1molal',))

    assert [_status(tmp_path, name) for name in ('00_0.5molal', '01_1molal', '02_1.5molal')] == \
           ['complete', 'failed', 'complete']
    assert '02_1.5molal:md' in _launches(tmp_path), 'the condition after the failure ran'
    assert result.returncode != 0, 'the series ran to its end, and one of its conditions failed'


@pytest.mark.slow
def test_a_series_asked_to_stop_does_not_run_the_conditions_after_the_failure(tmp_path):
    """`stop` is the other choice: the first condition that ends failed ends the series."""
    _prepare(tmp_path, [0.5, 1.0, 1.5], series_on_failure='stop')
    result = _run(tmp_path, failing=('01_1molal',))

    assert result.returncode != 0
    assert [_status(tmp_path, name) for name in ('00_0.5molal', '01_1molal', '02_1.5molal')] == \
           ['complete', 'failed', None], 'the third condition was never entered'
    assert not [line for line in _launches(tmp_path) if line.startswith('02_1.5molal')], _launches(tmp_path)


@pytest.mark.slow
def test_a_condition_that_already_finished_is_not_run_again_and_a_failed_one_resumes(tmp_path):
    """The whole point of a checkpoint per concentration, in one flow.

    A second entry into the series -- which is what resuming the run does -- enters only the condition that did
    not finish: the completed ones are skipped by their own record, and the failed one continues from the
    checkpoint its failure wrote rather than repeating what it had already integrated.

    `min` runs again inside the condition, and that is the documented ceiling rather than a leak: a steep
    minimization writes no checkpoint (it has no velocities to carry), so there is nothing for it to continue
    from. The equilibration and the production -- where a 500 ns condition spends its wall clock -- do resume.
    """
    _prepare(tmp_path, [0.5, 1.0])
    _run(tmp_path, failing=('00_0.5molal',))
    first = _launches(tmp_path)
    assert first == ['00_0.5molal:min', '00_0.5molal:eq', '00_0.5molal:eq', '00_0.5molal:eq',
                     '01_1molal:min', '01_1molal:eq', '01_1molal:md']
    (tmp_path / 'mdrun_calls').unlink()

    second = _run(tmp_path)
    assert second.returncode == 0, second.stderr[-2000:]
    assert _launches(tmp_path) == ['00_0.5molal:min', '00_0.5molal:eq', '00_0.5molal:md'], (
        'the finished condition is not entered again; the failed one resumes from its own checkpoint')
    # `resumed` is the flag that says the retry continued rather than restarted: the equilibration found the
    # checkpoint its own failure wrote, and the minimization had none to find.
    attempts = json.loads((_condition(tmp_path, '00_0.5molal') / 'attempts.json').read_text())['attempts']
    assert [(record['stage'], record['resumed']) for record in attempts[-3:]] == \
           [('min', False), ('eq', True), ('md', False)]
    assert [_status(tmp_path, name) for name in ('00_0.5molal', '01_1molal')] == ['complete', 'complete']
