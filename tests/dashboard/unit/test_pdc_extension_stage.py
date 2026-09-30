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


def test_the_script_resumes_from_the_assessment_phases_own_outputs(tmp_path):
    stage = prepared(tmp_path)
    script = (stage / Path(pdc.STAGES[3].relative).name).read_text()

    assert 'cp "../2_assessment/prod/$name" "$name"' in script
    assert 'gmx convert-tpr -s run.tpr -extend "$EXTENSION_PS"' in script
    assert '-cpi run.cpt' in script, 'the extension continues the assessment phase rather than restarting it'
    assert 'cp run.xtc prod/run.xtc' in script, 'the declared outputs are prod/run.gro and prod/run.xtc'
    assert 'python pdc_snapshot.py' in script and '--phase extension' in script
    assert (stage / 'pdc_snapshot.py').is_file()


def test_the_script_takes_the_budget_from_the_environment_and_passes_no_ntmpi(tmp_path):
    script = (prepared(tmp_path) / Path(pdc.STAGES[3].relative).name).read_text()
    executed = '\n'.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert '${MDRUN_LAUNCHER:-}' in script and '${MDRUN_FLAGS:-' in script
    assert '-ntmpi' not in executed


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
