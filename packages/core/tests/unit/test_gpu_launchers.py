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
import detergent_validation

from tests.harness.pdc_fixtures import run_script
from tests.harness.support import PACKAGE

SCRIPTS = PACKAGE / 'execution/scripts'
#: The pdc scripts moved to their feature distribution; a launcher is checked where the run would find it.
PDC_SCRIPTS = Path(detergent_pdc.__file__).resolve().parent / 'execution/scripts'
VALIDATION_SCRIPTS = Path(detergent_validation.__file__).resolve().parent / 'execution/scripts'


def _script(name):
    for directory in (PDC_SCRIPTS, VALIDATION_SCRIPTS, SCRIPTS):
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
    brackets are what say so -- these three lines only read them. The minimisation reads the auto bracket, so the
    Other run options cannot reach it; the two dynamics legs read the run's choices. The resume line is the same leg
    continued, so it is checked where the continue contract is (`test_a_resumed_cg_simulation_...`)."""
    lines = [line for line in _mdrun_lines('cg_simulation.sh') if '-cpi' not in line]
    assert len(lines) == 3
    assert all('${MDRUN_LAUNCHER:-}gmx mdrun' in line for line in lines)
    assert '${MDRUN_FLAGS_AUTO:-' in lines[0]
    assert all('${MDRUN_FLAGS:-' in line for line in lines[1:])
    assert all('-pme' not in line for line in lines)


def test_the_aa_reference_launcher_reads_all_three_brackets():
    """Its two minimisations read the auto bracket and keep PME on the CPU; its equilibration and production put PME
    on the GPU, so they read the dynamics bracket. One builder decides the device, and the brackets differ only in
    the schemes they add. The resume line is the production leg continued, so it is excluded here."""
    lines = [line for line in _mdrun_lines('aa_reference.sh') if '-cpi' not in line]
    vacuum, solvated, equilibration, production = lines
    assert '${MDRUN_FLAGS_AUTO:-' in vacuum and '${MDRUN_FLAGS_AUTO:-' in solvated
    assert '-pme' not in vacuum and '-pme' not in solvated
    assert '${MDRUN_FLAGS_PME:-' in equilibration and '${MDRUN_FLAGS_PME:-' in production
    assert '${MDRUN_LAUNCHER:-}' in production, 'the ranks the builder decided reach this stage too'


def cg_workspace(tmp_path):
    """The files `cg_simulation.sh` reads before its mdrun, so the plain path can run without a real build."""
    stage = tmp_path / 'stage'
    stage.mkdir()
    (tmp_path / '3_initial_CG').mkdir()
    (tmp_path / '3_initial_CG' / 'lig.itp').write_text('#include "martini.itp"\n')
    (tmp_path / '2_mapping').mkdir()
    (tmp_path / '2_mapping' / 'mapped.gro').write_text('system\n0\n   1.00000   1.00000   1.00000\n')
    (stage / 'system_EMPTY.top').write_text('[ molecules ]\n')
    return stage


def aa_workspace(tmp_path):
    stage = tmp_path / 'stage'
    stage.mkdir()
    for name in ('system_EMPTY.top', 'molecule.pdb', 'em.mdp', 'eq.mdp', 'run.mdp'):
        (stage / name).write_text('molecule\n')
    return stage


def test_a_resumed_cg_simulation_runs_only_its_production_leg(tmp_path):
    checkpoint = tmp_path / 'md.cpt'

    done = run_script(SCRIPTS / 'cg_simulation.sh', tmp_path,
                      environment={'MDRUN_CONTINUE': str(checkpoint)})

    assert done.returncode == 0, done.stderr
    assert f'+ gmx mdrun -deffnm md -cpi {checkpoint} -append -ntomp 8 -v' in done.stderr
    assert 'grompp' not in done.stderr and 'editconf' not in done.stderr and 'solvate' not in done.stderr
    assert 'convert-tpr' not in done.stderr and 'trjconv' not in done.stderr


def test_a_cg_simulation_without_a_continue_checkpoint_runs_the_commands_it_always_did(tmp_path):
    stage = cg_workspace(tmp_path)

    done = run_script(SCRIPTS / 'cg_simulation.sh', stage,
                      environment={'FINAL_ITP': 'lig.itp', 'MOLECULE_TYPE': 'DDM'})

    assert done.returncode == 0, done.stderr
    for command in ('+ cp ../3_initial_CG/lig.itp lig.itp',
                    '+ gmx grompp -f inputs/minimization.mdp -p system.top -c solvated.gro -o min.tpr',
                    '+ gmx mdrun -deffnm min -ntomp 8 -v',
                    '+ gmx grompp -f inputs/eq.mdp -p system.top -c min.gro -o eq.tpr -maxwarn 1',
                    '+ gmx mdrun -deffnm eq -ntomp 8 -v',
                    '+ gmx grompp -f inputs/md.mdp -p system.top -c eq.gro -t eq.cpt -o md.tpr -maxwarn 1',
                    '+ gmx mdrun -deffnm md -ntomp 8 -v',
                    '+ gmx trjconv -f md.xtc -s md.tpr -pbc mol -center -o prod/lig_CG.xtc'):
        assert command in done.stderr, (command, done.stderr)
    assert '-cpi' not in done.stderr and '-append' not in done.stderr


def test_a_resumed_aa_reference_runs_only_its_production_leg(tmp_path):
    checkpoint = tmp_path / '3-run.cpt'

    done = run_script(SCRIPTS / 'aa_reference.sh', tmp_path,
                      environment={'MDRUN_CONTINUE': str(checkpoint)})

    assert done.returncode == 0, done.stderr
    assert f'+ gmx mdrun -deffnm 3-run -cpi {checkpoint} -append -ntomp 8 -v' in done.stderr
    assert 'grompp' not in done.stderr and 'editconf' not in done.stderr and 'solvate' not in done.stderr


def test_an_aa_reference_without_a_continue_checkpoint_runs_the_commands_it_always_did(tmp_path):
    stage = aa_workspace(tmp_path)

    done = run_script(SCRIPTS / 'aa_reference.sh', stage)

    assert done.returncode == 0, done.stderr
    for command in ('+ gmx grompp -f em.mdp -c boxed.gro -p system.top -o vacuum.tpr',
                    '+ gmx mdrun -deffnm vacuum -ntomp 8 -v',
                    '+ gmx grompp -f run.mdp -c 2-eq.gro -t 2-eq.cpt -p system.top -o 3-run.tpr',
                    '+ gmx mdrun -deffnm 3-run -ntomp 8 -v'):
        assert command in done.stderr, (command, done.stderr)
    assert '-cpi' not in done.stderr and '-append' not in done.stderr
