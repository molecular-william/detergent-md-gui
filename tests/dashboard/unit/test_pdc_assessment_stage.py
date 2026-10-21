"""The CG assessment phase: what the stage runs, and how long for.

The assessment leg is where a pdc build does its 100 ns of sampling, so its inputs are the ones a reader will want to
check: the duration converted into steps at the template's own timestep, the mdrun budget taken from the environment
rather than restated, and solvation delegated to the builder that decides the water radius, the ion names and the group
`genion` may replace. The three equilibration legs the pipeline gained in front of it are
`test_pdc_equilibration_stages.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard.execution.adapters import pdc, pdc_solvation
from dashboard.execution.scripts import pdc_solvate
from tests.dashboard.pdc_fixtures import prepared_run

TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'DDM', 'type': 'registered-template'}],
}
PROTEIN = 'molecules/DDM/protein.pdb'
TEMPLATE_PATH = 'molecules/DDM/micelle_template.json'
ASSESSMENT = Path(pdc.stage_by_name('CG assessment MD').relative).parent


def prepared(tmp_path: Path, **settings):
    # The construction is `pdc_fixtures`'; what stays here is what this file varies and which stage it reads.
    return prepared_run(tmp_path, settings={'assessment_ns': 100} | settings, suffix=ASSESSMENT)


def mdp_numbers(path: Path) -> dict:
    numbers = {}
    for raw in path.read_text().splitlines():
        line = raw.split(';', 1)[0].strip()
        if '=' in line:
            name, value = (part.strip() for part in line.split('=', 1))
            numbers[name.lower()] = value
    return numbers


def test_the_assessment_mdp_runs_the_requested_duration_at_the_templates_timestep(tmp_path):
    hundreds = mdp_numbers(prepared(tmp_path, assessment_ns=100) / 'assessment.mdp')
    short = mdp_numbers(prepared(tmp_path / 'short', assessment_ns=2) / 'assessment.mdp')

    timestep = float(hundreds['dt'])
    assert habits_are_the_templates(timestep)
    assert int(hundreds['nsteps']) == round(100_000 / timestep)
    assert int(short['nsteps']) == round(2_000 / timestep)


def habits_are_the_templates(timestep: float) -> bool:
    """The CG half integrates at Martini's own timestep; the template decides it, not this code."""
    template = pdc.TUTORIAL_TEMPLATE / '4_CG_sim' / 'inputs' / 'md.mdp'
    for raw in template.read_text().splitlines():
        line = raw.split(';', 1)[0].strip()
        if line.lower().startswith('dt'):
            return timestep == float(line.split('=')[1].strip())
    raise AssertionError('the CG template no longer sets dt')


def test_the_assessment_mdp_carries_the_cg_halfs_own_integration_settings(tmp_path):
    numbers = mdp_numbers(prepared(tmp_path) / 'assessment.mdp')

    # The coarse-grained half decides its own pressure coupling, and the template this file is copied from
    # asks for Parrinello-Rahman at 1 bar -- the protocol both Martini papers describe. This assertion used to
    # read `== 'no'`: the intent was right and the value was the defect, because `mdp_integration` stamped the
    # coupling off over every coarse-grained mdp.
    assert numbers['pcoupl'] == 'parrinello-rahman'
    assert numbers['ref_p'] == '1.0'
    assert numbers['nstxtcout'] == '100' and numbers['xtc-precision'] == '1000'
    assert numbers['nstenergy'] == '100'


def test_the_stage_script_is_the_workflows_own_and_is_production_only(tmp_path):
    """It is `pdc_assessment.sh`, and it is the production leg the three equilibration legs feed.

    It used to solvate, minimise and equilibrate from the built system -- work the legs in front of it now do, and
    doing it here again equilibrated every run twice (`test_pdc_assessment_production.py`).
    """
    stage = prepared(tmp_path)
    relative = Path(pdc.stage_by_name('CG assessment MD').relative)

    assert relative.name == 'pdc_assessment.sh', 'a stage runs a script this workflow owns'
    script = (stage / relative.name).read_text()
    assert 'python pdc_solvate.py' not in script and 'gmx solvate' not in script
    assert not (stage / 'pdc_solvate.py').exists(), "solvation is the minimisation leg's"
    assert 'pdc_snapshot.py' in script and '--phase assessment' in script
    assert (stage / 'pdc_snapshot.py').is_file()


def test_the_script_takes_its_mdrun_budget_from_the_environment_and_never_passes_ntmpi(tmp_path):
    stage = prepared(tmp_path)
    script = (stage / Path(pdc.stage_by_name('CG assessment MD').relative).name).read_text()
    executed = '\n'.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert '-ntmpi' not in executed, 'gmx here is an MPI-only build: -ntmpi aborts mdrun before the first step'
    assert '-ntmpi' in script, 'the comment that says why is allowed to name it'
    assert '${MDRUN_LAUNCHER:-}' in script and '${MDRUN_FLAGS:-' in script
    assert 'prod/run' in script, 'the four declared outputs of this stage come from mdrun -deffnm prod/run'


def test_the_assessment_stage_has_every_input_it_declares(tmp_path):
    """One mdp, and the NPT leg's system -- the equilibration legs own everything else.

    The stage used to carry the minimisation, equilibration and ion mdps and the water they need, because it ran
    them. It does not, so they are gone: a file left beside a stage that cannot use it is a reader's wrong turn.
    """
    stage = prepared(tmp_path)

    assert (stage / 'assessment.mdp').is_file()
    for name in pdc.stage_by_name('CG assessment MD').inputs:
        if not name.startswith('../'):
            assert (stage / name).is_file()
    for name in ('minimization.mdp', 'equilibration.mdp', 'ions.mdp', 'pdc_solvate.py'):
        assert not (stage / name).exists(), f'{name} was the work the three legs now do'
    assert not (stage / 'inputs' / 'water.gro').exists()


def test_the_back_map_stage_now_has_a_tool_and_an_invocation(tmp_path):
    stage = prepared(tmp_path).parent / Path(pdc.stage_by_name('Back-mapping (CG2AT2)').relative)

    script = stage.read_text()
    assert '-fg martini_3-0_charmm36' in script and '-silent' in script


class FakeRun:
    """A stand-in for `subprocess.run` that records what a stage would have executed."""

    def __init__(self):
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return None


def test_the_solvation_helper_runs_the_builders_commands_and_pipes_its_group(tmp_path, monkeypatch):
    stage = prepared(tmp_path)
    (stage / 'system.top').write_text('[ molecules ]\nDDM  8\nW  500\nNA  12\nCL  12\n')
    fake = FakeRun()
    monkeypatch.setattr(pdc_solvate.subprocess, 'run', fake)

    assert pdc_solvate.main(['--stage', str(stage), '--salt-molar', '0.15']) == 0

    expected = pdc_solvation.solvation_commands(str(stage / 'system.top'), str(stage / 'system.gro'),
                                                'system.tpr', salt_molar=0.15)
    assert [call[0] for call in fake.calls] == expected
    piped = [call for call in fake.calls if call[0][1] == 'genion']
    assert len(piped) == 1 and piped[0][1]['input'] == pdc_solvation.ion_group_selection()
    assert all(call[1]['input'] is None for call in fake.calls if call[0][1] != 'genion')

    record = json.loads((stage / pdc_solvate.OUTPUT_NAME).read_text())
    assert record['molecules'] == {'DDM': 8, 'W': 500, 'NA': 12, 'CL': 12}
    assert record['salt_molar'] == 0.15 and record['commands'] == expected


def test_a_topology_without_a_molecules_section_records_no_counts(tmp_path):
    topology = tmp_path / 'system.top'
    topology.write_text('#include "martini.itp"\n\n[ system ]\nname\n')

    assert pdc_solvate.molecules(topology) == {}
