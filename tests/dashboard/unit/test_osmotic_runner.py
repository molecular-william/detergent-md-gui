"""The osmotic runner's retry: a failed stage resumes from its own checkpoint, bounded at a ceiling.

Two subjects, and they are different:

* **What the runner executes.** Read off the script's own non-comment lines, because the script legitimately names
  the flag it must pass in the comment that explains why -- an assertion on the whole file would pass on a change
  that removed the flag. `test_the_runner_resumes_a_failed_stage_from_its_own_checkpoint` is that reading.
* **What the runner does.** A stub `gmx` fails the equilibration every time, writing a checkpoint as it dies; the
  script is then run for real, and the third failure has to end the condition with no fourth `mdrun`.

The stub writes `eq.cpt` because that is what a real equilibration does when it dies mid-run, and it is the only way
to exercise *both* branches: attempt 1 has no checkpoint (restart cleanly) and attempts 2 and 3 resume. The single
question a stub cannot answer is whether GROMACS itself integrates -- it does not here, and this test does not claim
it: the subject is the runner's control flow, not the engine.
"""
import json
import os
import subprocess
from pathlib import Path

from dashboard.execution.adapters import osmotic

SCRIPTS = Path(osmotic.__file__).resolve().parents[1] / 'scripts'
MAPPING = {'beads': [{'name': 'S1A', 'type': 'SP1r', 'atoms': [1, 2, 3]},
                     {'name': 'S1B', 'type': 'SP4r', 'atoms': [4, 5, 6]},
                     {'name': 'S1C', 'type': 'SP1r', 'atoms': [7, 8, 9]},
                     {'name': 'VS1', 'type': 'TC4', 'atoms': []}]}

#: A stub engine. `insert-molecules` writes the solvent the runner goes on to read; `mdrun` records each launch and
#: fails the equilibration after writing its checkpoint; every other subcommand (`grompp`) succeeds without a file.
STUB = r'''#!/bin/sh
sub="$1"
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
  mdrun)
    stage="$3"                       # $2 is -deffnm, $3 the stage
    echo "$stage" >> "$STUB_DIR/mdrun_calls"
    if [ "$stage" = eq ]; then : > eq.cpt; exit 1; fi
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


def test_the_third_failure_ends_the_condition_and_no_fourth_mdrun_is_launched(tmp_path):
    """The ceiling is the condition's, not the stage's: three launches of the failing stage and no more."""
    solute = _solute_root(tmp_path)
    osmotic.prepare(tmp_path, {'molecule_id': 'Maltose', 'solute_root': str(solute),
                               'mapping_snapshot': MAPPING,
                               'settings': {'osmotic_molality': 1.0}, 'profile': 'standard'})
    stage = tmp_path / '01_simulate'
    stub = tmp_path / 'gmx'
    stub.write_text(STUB)
    stub.chmod(0o755)
    # The stage runs under the workspace's own virtualenv, which is where the real executor points `python`:
    # `tools.search_path` puts `dashboard/.venv/bin` first, and this script imports `dashboard`.
    venv = Path(osmotic.__file__).resolve().parents[2] / '.venv' / 'bin'
    result = subprocess.run(['bash', str(stage / 'run.sh')], cwd=stage, capture_output=True, text=True, check=False,
                            env={**os.environ, 'GROMACS': str(stub), 'MDRUN_LAUNCHER': '', 'STUB_DIR': str(tmp_path),
                                 'PATH': f'{venv}:{os.environ["PATH"]}'})

    launches = (tmp_path / 'mdrun_calls').read_text().split()
    assert launches == ['min', 'eq', 'eq', 'eq'], launches
    assert result.returncode != 0, 'a condition whose equilibration never succeeds ends failed'

    attempts = json.loads((stage / 'attempts.json').read_text())['attempts']
    equilibration = [record for record in attempts if record['stage'] == 'eq']
    assert [record['attempt'] for record in equilibration] == [1, 2, 3]
    assert [record['resumed'] for record in equilibration] == [False, True, True], (
        'attempt 1 found no checkpoint and restarted; the two after it resumed the one the failure wrote')
    assert all(record['checkpoint'] == 'eq.cpt' for record in equilibration)
    assert all(record['outcome'] == 'failed' for record in equilibration)
    assert all(record['attempts_max'] == osmotic.DEFAULTS['osmotic_attempts_max'] for record in attempts)
    assert [record['stage'] for record in attempts] == ['min', 'eq', 'eq', 'eq']
    assert attempts[0]['outcome'] == 'ok', 'the minimization succeeded and is recorded as such'
