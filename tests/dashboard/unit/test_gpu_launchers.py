"""The mdrun launchers carry no device of their own.

The device used to be a literal here: `aa_reference.sh` and `cg_simulation.sh` each wrote `-gpu_id 0` into their
own mdrun lines, beside the `-gpu_id 0` in the adapter's constants and in the pdc scripts' fallbacks. Three copies
of one decision. The decision is now `mdrun_gpu`, read by one builder (`aa.mdrun_command_flags`), and the
executor hands the built flags to every stage script as `MDRUN_FLAGS` / `MDRUN_FLAGS_PME`.

So what is pinned here is the negative, which is what makes the setting real: **no executed script states a
device**. The fallbacks are the case with no executor and no device named -- threads only -- and a fallback that
named device 0 would silently overrule a run that chose device 1 whenever the executor failed to export the
variable.
"""
from pathlib import Path

import detergent_pdc

from tests.dashboard.support import PACKAGE

SCRIPTS = PACKAGE / 'execution/scripts'
#: The pdc scripts moved to their feature distribution; a launcher is checked where the run would find it.
PDC_SCRIPTS = Path(detergent_pdc.__file__).resolve().parent / 'execution/scripts'


def _script(name):
    for directory in (PDC_SCRIPTS, SCRIPTS):
        if (directory / name).is_file():
            return directory / name
    raise FileNotFoundError(name)


def _mdrun_lines(name):
    text = _script(name).read_text()
    # The command may carry a launcher prefix (`${MDRUN_LAUNCHER:-}gmx mdrun`), so match the command itself
    # rather than the start of the line.
    return [line for line in text.splitlines() if 'gmx mdrun' in line]


def test_no_executed_launcher_states_a_gpu_device():
    """The device reaches mdrun through the builder's flags, and nowhere through a script's own text."""
    for name in ('aa_reference.sh', 'cg_simulation.sh', 'pdc_assessment.sh', 'osmotic_simulation.sh'):
        for line in _mdrun_lines(name):
            assert '-gpu_id' not in line, f'{name} states a device of its own: {line.strip()}'
            assert '-nb ' not in line, f'{name} states the offload scheme of its own: {line.strip()}'


def test_the_cg_launchers_take_the_executors_flags():
    """Nonbonded work may go to the GPU; PME stays on the CPU for the coarse-grained stages, and the executor's
    minimisation bracket is what says so -- these three lines only read it."""
    lines = _mdrun_lines('cg_simulation.sh')
    assert len(lines) == 3
    assert all('${MDRUN_LAUNCHER:-}gmx mdrun' in line for line in lines)
    assert all('${MDRUN_FLAGS:-' in line for line in lines)
    assert all('-pme' not in line for line in lines)


def test_the_aa_reference_launcher_reads_both_brackets():
    """Its minimisation keeps PME on the CPU and its dynamics put it on the GPU, so it reads both built brackets:
    one builder decides the device, and the two brackets differ only in the scheme they add."""
    vacuum, solvated, equilibration, production = _mdrun_lines('aa_reference.sh')
    assert '${MDRUN_FLAGS:-' in vacuum and '${MDRUN_FLAGS:-' in solvated
    assert '-pme' not in vacuum and '-pme' not in solvated
    assert '${MDRUN_FLAGS_PME:-' in equilibration and '${MDRUN_FLAGS_PME:-' in production
    assert '${MDRUN_LAUNCHER:-}' in production, 'the ranks the builder decided reach this stage too'
