"""The extension phase: continue the assessment trajectory for the run's second duration.

The two things worth pinning are that it *continues* (velocities are not regenerated, and it resumes from the
assessment phase's own checkpoint) and that the length it extends by is the run's setting rather than a number in
a script.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard.execution.adapters import pdc

TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'}],
}
EXTENSION = Path(pdc.STAGES[3].relative).parent


def molecule_tree(tmp_path: Path) -> Path:
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text('[ moleculetype ]\nDDM             1\n')
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    (molecule / 'protein.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')
    return tmp_path


def prepared(tmp_path: Path, **settings):
    root = molecule_tree(tmp_path)
    numbers = {'seed': 20260930, 'aggregation_number': 8, 'assessment_ns': 100, 'extension_ns': 900}
    numbers.update(settings)
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, protein='molecules/DDM/protein.pdb', template='molecules/DDM/micelle_template.json',
                settings=numbers, project_root=root)
    return run / EXTENSION


def mdp_numbers(path: Path) -> dict:
    numbers = {}
    for raw in path.read_text().splitlines():
        line = raw.split(';', 1)[0].strip()
        if '=' in line:
            name, value = (part.strip() for part in line.split('=', 1))
            numbers[name.lower()] = value
    return numbers


def test_the_extension_continues_instead_of_starting_again(tmp_path):
    numbers = mdp_numbers(prepared(tmp_path) / 'extension.mdp')

    assert numbers['gen-vel'] == 'no', 'a continued trajectory does not regenerate velocities'
    assert 'gen-seed' in numbers


def test_the_extension_length_is_the_runs_setting_in_the_units_convert_tpr_takes(tmp_path):
    stage = prepared(tmp_path, extension_ns=900)

    assert (stage / 'extension.ps').read_text().strip() == '900000'
    assert (prepared(tmp_path / 'short', extension_ns=25) / 'extension.ps').read_text().strip() == '25000'


def test_the_script_hands_both_paths_to_the_helper(tmp_path):
    stage = prepared(tmp_path)
    script = (stage / Path(pdc.STAGES[3].relative).name).read_text()
    executed = '\n'.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert 'python pdc_extension.py' in executed and '--assessment ../3_assessment' in executed
    assert 'convert-tpr' not in executed and '-cpi' not in executed, 'both are the helper\'s decisions, not the script\'s'
    assert (stage / 'pdc_extension.py').is_file() and (stage / 'pdc_solvate.py').is_file()
    assert 'python pdc_snapshot.py' in executed and '--phase extension' in executed
    assert (stage / 'pdc_snapshot.py').is_file()


def test_the_stage_passes_no_ntmpi_and_leaves_the_budget_to_the_helper(tmp_path):
    stage = prepared(tmp_path)
    script = (stage / Path(pdc.STAGES[3].relative).name).read_text()
    executed = '\n'.join(line for line in script.splitlines() if not line.strip().startswith('#'))
    helper = (stage / 'pdc_extension.py').read_text()

    assert '-ntmpi' not in executed, 'gmx here is an MPI-only build: -ntmpi aborts mdrun before the first step'
    assert 'MDRUN_FLAGS' in helper and 'MDRUN_LAUNCHER' in helper, 'the budget comes from the environment, in Python'


def test_the_extension_stage_declares_the_inputs_it_reads(tmp_path):
    stage = prepared(tmp_path)

    assert (stage / 'extension.mdp').is_file() and (stage / 'extension.ps').is_file()
    for name in pdc.STAGES[3].inputs:
        if not name.startswith('../'):
            assert (stage / name).is_file(), f'{name} is declared an input of this stage'


def test_the_run_records_both_durations_it_will_spend(tmp_path):
    manifest = json.loads((prepared(tmp_path).parent / 'manifest.json').read_text())

    assert manifest['extension_ps'] == 900000
    assert manifest['assessment_steps'] > 0
