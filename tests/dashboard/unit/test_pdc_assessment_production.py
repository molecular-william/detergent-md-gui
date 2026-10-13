"""The assessment leg is production only, and it samples the system the NPT leg left.

Measured before this change: the stage script solvated the built system, minimised it and equilibrated it before its
100 ns of production -- exactly the work the three legs the plan gained in front of it now do. A pdc run therefore
equilibrated twice, and the legs' output fed nothing: the phase that was supposed to read it re-derived the system
from `1_system/` instead.

What is pinned here: the leg runs one `grompp` and one `mdrun` and nothing else, its declared inputs are the NPT
leg's system, the solvation and equilibration inputs it used to carry are gone, and a run whose legs all skip still
satisfies the declaration -- the property the legs' prelude keeps by copying the system forward before their own
`set -e`.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from dashboard.execution import workflow
from dashboard.execution.adapters import pdc

TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'DDM', 'type': 'registered-template'}],
}
PROTEIN = 'molecules/DDM/protein.pdb'
TEMPLATE_PATH = 'molecules/DDM/micelle_template.json'
LEGS = ('Energy minimisation', 'NVT equilibration', 'NPT equilibration')
ASSESSMENT = 'CG assessment MD'
SCRIPT = 'pdc_assessment.sh'


def molecule_tree(tmp_path: Path) -> Path:
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text('[ moleculetype ]\nDDM             1\n')
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    (molecule / 'protein.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')
    return tmp_path


def prepared(tmp_path: Path, **settings) -> Path:
    root = molecule_tree(tmp_path)
    numbers = {'seed': 20260930, 'aggregation_number': 8}
    numbers.update(settings)
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, protein=PROTEIN, template=TEMPLATE_PATH, settings=numbers, project_root=root)
    return run


def stage_directory(run: Path, name: str) -> Path:
    return run / Path(pdc.stage_by_name(name).relative).parent


def executed(script: Path) -> str:
    """A stage script's lines minus its comments: what the stage actually runs."""
    return '\n'.join(line for line in script.read_text().splitlines() if not line.strip().startswith('#'))


def test_the_assessment_leg_solvates_minimises_and_equilibrates_nothing(tmp_path):
    lines = executed(stage_directory(prepared(tmp_path), ASSESSMENT) / SCRIPT)

    assert 'pdc_solvate' not in lines and 'gmx solvate' not in lines, "solvation is the minimisation leg's"
    assert 'minimisation.mdp' not in lines and 'minimization.mdp' not in lines
    assert 'equilibration.mdp' not in lines, 'the three legs in front of this stage are the equilibration'
    assert lines.count('gmx grompp') == 1 and lines.count('gmx mdrun') == 1, 'one production run, and one only'
    assert 'assessment.mdp' in lines


def test_the_assessment_leg_declares_the_system_the_npt_leg_left(tmp_path):
    run = prepared(tmp_path)
    declared = {str(entry) for entry in pdc.stage_by_name(ASSESSMENT).inputs}

    assert {'../4_npt/system.gro', '../4_npt/system.top'} <= declared, declared
    assert f'../4_npt/{pdc.DETERGENT_TOPOLOGY}' in declared
    for name in pdc.FORCEFIELD_FILES:
        assert f'../4_npt/{name}' in declared
    # The declaration is also what puts the system in the stage: the prelude is emitted from it, not restated here.
    assert 'cp -f ../4_npt/system.gro system.gro' in (stage_directory(run, ASSESSMENT) / SCRIPT).read_text()


def test_the_assessment_leg_no_longer_re_derives_the_system_from_the_build(tmp_path):
    declared = {str(entry) for entry in pdc.stage_by_name(ASSESSMENT).inputs}

    assert not any(entry.startswith('../1_system/') for entry in declared), \
        'the NPT leg is what left the system this stage samples'


def test_the_assessment_stage_carries_no_solvation_or_equilibration_inputs(tmp_path):
    stage = stage_directory(prepared(tmp_path), ASSESSMENT)

    for name in ('minimization.mdp', 'equilibration.mdp', 'ions.mdp', 'pdc_solvate.py'):
        assert not (stage / name).exists(), f'{name} was the work the three legs now do'
    assert not (stage / 'inputs' / 'water.gro').exists()
    assert (stage / 'assessment.mdp').is_file()


def test_the_assessment_leg_takes_the_npt_checkpoint_only_when_the_npt_leg_left_one(tmp_path):
    """The checkpoint carries the velocities the NPT leg equilibrated; a leg the run asked none of leaves none, so
    the file is read when it is there rather than declared as an input no skip path could satisfy."""
    run = prepared(tmp_path)
    script = (stage_directory(run, ASSESSMENT) / SCRIPT).read_text()
    declared = {str(entry) for entry in pdc.stage_by_name(ASSESSMENT).inputs}

    assert 'if [ -f ../4_npt/system.cpt ]' in script
    assert not any(str(entry).endswith('system.cpt') for entry in declared)


def test_the_assessment_leg_still_writes_the_series_and_a_molecule_whole_trajectory(tmp_path):
    script = (stage_directory(prepared(tmp_path), ASSESSMENT) / SCRIPT).read_text()

    assert '-pbc mol -center -o prod/whole.xtc' in script
    assert 'pdc_snapshot.py' in script and '--phase assessment' in script


def test_a_run_whose_equilibration_legs_all_skip_still_validates_the_assessment_leg(tmp_path):
    """The contract's fourth outcome must not break the chain: the executor validates a stage's declared inputs
    *before* it runs its script, so with every leg skipped the assessment leg still has to find the NPT system."""
    run = prepared(tmp_path, minimisation_steps=0, nvt_ps=0, npt_ps=0)
    build = run / '1_system'
    (build / 'system.gro').write_text('a built system\n')
    (build / 'system.top').write_text('[ molecules ]\nDDM  8\n')
    (build / pdc.DETERGENT_TOPOLOGY).write_text('[ moleculetype ]\nDDM_CG 1\n')

    for name in LEGS:
        stage = pdc.stage_by_name(name)
        directory = run / Path(stage.relative).parent
        result = subprocess.run(['bash', str(run / stage.relative)], cwd=directory, capture_output=True, text=True)

        assert result.returncode == 4, (name, result.stdout, result.stderr)
        assert (directory / Path(stage.relative).name).is_file()

    # What the executor does before it runs a stage. The legs' preludes copied the system forward past their own
    # skip paths, so the assessment leg's declaration is satisfied by the run that asked for no equilibration.
    _, required_inputs, _ = pdc.stage_contract()
    workflow.validate_stage_inputs(ASSESSMENT, stage_directory(run, ASSESSMENT), required_inputs)

    npt = stage_directory(run, 'NPT equilibration')
    assert (npt / 'system.gro').is_file() and (npt / 'system.top').is_file()
