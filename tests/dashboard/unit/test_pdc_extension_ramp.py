"""The extension restarts through a short lower-dt ramp, and says so in its record.

The first real extension died at 13.04 ns on a LINCS failure inside one DDM headgroup's rigid triangle, with the bulk healthy
to the last saved frame and a clean equilibration: a local event at the 5 fs -> 20 fs step-up rather than a drifting system,
and a reseeded retry passed 32 ns without a warning. So the step-up is softened, not the fit: 100 ps at 10 fs, then the
production the run asked for.
"""
import importlib

ext = importlib.import_module('dashboard.execution.scripts.pdc_extension')

MDP = """title = Martini

integrator = md
dt = 0.02 ; 20 fs, the coarse-grained half's timestep
nsteps = 5000000

tcoupl = v-rescale
tau_t = 1.0
ref_t = 300
gen-vel = no
gen-seed = 20260911
continuation = yes
"""


def test_the_ramp_halves_the_step_and_keeps_the_physics():
    ramp = ext.ramp_mdp(MDP, dt_ps=0.01, ps=100.0)

    assert 'dt = 0.01 ; the extension ramp' in ramp
    assert 'nsteps = 10000 ; the extension ramp' in ramp, '100 ps at 10 fs, not a second duration setting'
    kept = [line for line in MDP.splitlines() if line.split('=')[0].strip() not in ('dt', 'nsteps')]
    assert [line for line in ramp.splitlines() if line.split('=')[0].strip() not in ('dt', 'nsteps')] == kept


def test_the_ramp_default_is_a_hundred_picoseconds_at_ten_femtoseconds():
    ramp = ext.ramp_mdp(MDP)

    assert f'dt = {ext.RAMP_DT_PS} ;' in ramp and 'nsteps = 10000 ;' in ramp


def test_an_mdp_without_a_step_is_refused():
    import pytest

    with pytest.raises(ValueError, match='nsteps'):
        ext.ramp_mdp('title = Martini\ndt = 0.02\n')


def test_the_plan_ramps_between_the_equilibration_and_the_production():
    plan = ext.restart_plan()

    assert [command[1] for command in plan] == [
        'grompp', 'mdrun', 'grompp', 'mdrun', 'grompp', 'mdrun', 'grompp', 'mdrun'
    ]
    legs = [command[3] for command in plan if command[1] == 'mdrun']
    assert legs == ['min', 'eq', 'ramp', 'prod/run'], 'the ramp is the third leg, before production'

    ramp_grompp = plan[4]
    assert ramp_grompp[3] == ext.RAMP_MDP and '-t' in ramp_grompp and 'eq.cpt' in ramp_grompp
    prod_grompp = plan[6]
    assert 'ramp.gro' in prod_grompp and 'ramp.cpt' in prod_grompp, 'production continues from the ramp, not the eq'
    assert prod_grompp[3] == ext.RESTART_MDP


def test_each_mdrun_continues_the_tpr_its_own_grompp_wrote():
    plan = ext.restart_plan(launcher='mpirun -n 2 ')

    for grompp, mdrun in zip(plan[0::2], plan[1::2]):
        written = grompp[grompp.index('-o') + 1]
        assert written == f'{mdrun[3]}.tpr', f'{mdrun[3]} would run a topology {written} does not describe'
        assert mdrun[0] == 'mpirun -n 2 gmx'
