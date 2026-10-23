"""The extension's bar reads because it announces its calls in the shape the reader already parses.

`pdc_extension.py` is the only stage that launches GROMACS from Python, and Python traces nothing: no `+ gmx grompp ...
-o prod/run.tpr`, no `+ gmx mdrun -deffnm prod/run`. The dashboard reads a leg's start and the mdp its step count is out of
from exactly those two lines, so the run's longest stage -- a 5 ns equilibration and a 100 ns production -- reported an
empty bar while its log carried 16,520 step lines.
"""
import importlib

from dashboard.web import progress

ext = importlib.import_module('dashboard.execution.scripts.pdc_extension')


def test_the_extension_announces_a_grompp_and_a_leg_the_reader_can_measure(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ext.subprocess, 'run', lambda command, **kwargs: None)
    (tmp_path / 'extension.restart.mdp').write_text('dt = 0.02\nnsteps = 5000000\n')

    ext.run(['gmx', 'grompp', '-f', 'extension.restart.mdp', '-p', 'system.top', '-o', 'prod/run.tpr',
             '-maxwarn', '1'])
    ext.run(['gmx', 'mdrun', '-deffnm', 'prod/run', '-v'])

    announced = capsys.readouterr().err
    assert '+ gmx grompp -f extension.restart.mdp' in announced
    assert '+ gmx mdrun -deffnm prod/run -v' in announced

    reading = progress.progress_from_log('CG extension MD', tmp_path, announced + 'step 2500000\n')

    assert reading['leg'] == 'prod/run'
    assert reading['steps'] == 5000000 and reading['step'] == 2500000
    assert reading['percent'] == 50 and reading['measured'] is True


def test_the_announced_line_is_the_call_that_runs(tmp_path, monkeypatch):
    """The announcement is not a description of the call beside it: it is made from the same argv."""
    seen = []
    monkeypatch.setattr(ext.subprocess, 'run', lambda command, **kwargs: seen.append(list(command)))

    argv = ['gmx', 'mdrun', '-deffnm', 'prod/run', '-ntomp', '8', '-v']
    ext.run(argv)

    assert seen == [argv]
