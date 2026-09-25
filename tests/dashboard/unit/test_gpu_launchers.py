from tests.dashboard.support import PROJECT_ROOT


def _mdrun_lines(name):
    text = (PROJECT_ROOT / 'dashboard/execution/scripts' / name).read_text()
    return [line for line in text.splitlines() if line.startswith('gmx mdrun')]


def test_cg_launchers_only_offload_supported_nonbonded_work():
    lines = _mdrun_lines('cg_simulation.sh')
    assert len(lines) == 3
    assert all('-gpu_id 0 -nb gpu -pin on' in line for line in lines)
    assert all('-pme gpu' not in line and '-pmefft gpu' not in line for line in lines)


def test_legacy_aa_launcher_keeps_minimization_pme_on_cpu():
    vacuum, solvated, equilibration, production = _mdrun_lines('aa_reference.sh')
    assert all('-gpu_id 0 -nb gpu -pin on' in line for line in (vacuum, solvated))
    assert all('-pme gpu' not in line and '-pmefft gpu' not in line
               for line in (vacuum, solvated))
    assert all('-gpu_id 0 -nb gpu -pme gpu -pmefft gpu -pin on' in line
               for line in (equilibration, production))
