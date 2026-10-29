"""The extension phase: continue the assessment trajectory for the run's second duration.

The two things worth pinning are that it *continues* (velocities are not regenerated, and it resumes from the
assessment phase's own checkpoint) and that the length it extends by is the run's setting rather than a number in
a script.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard.execution.adapters import pdc

from tests.dashboard.pdc_fixtures import inputs_dir, prepared_run, script_of

TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'}],
}
EXTENSION = 'CG extension MD'


def prepared(tmp_path: Path, **settings):
    return prepared_run(tmp_path, settings={'assessment_ns': 100, 'extension_ns': 900} | settings)


def extension_inputs(run: Path) -> Path:
    return inputs_dir(run)


def mdp_numbers(path: Path) -> dict:
    numbers = {}
    for raw in path.read_text().splitlines():
        line = raw.split(';', 1)[0].strip()
        if '=' in line:
            name, value = (part.strip() for part in line.split('=', 1))
            numbers[name.lower()] = value
    return numbers


def test_the_extension_continues_instead_of_starting_again(tmp_path):
    numbers = mdp_numbers(extension_inputs(prepared(tmp_path)) / 'extension.mdp')

    assert numbers['gen-vel'] == 'no', 'a continued trajectory does not regenerate velocities'
    assert 'gen-seed' in numbers


def test_the_extension_length_is_the_runs_setting_in_the_units_convert_tpr_takes(tmp_path):
    assert (extension_inputs(prepared(tmp_path, extension_ns=900)) / 'extension.ps').read_text().strip() == '900000'
    assert (extension_inputs(prepared(tmp_path / 'short', extension_ns=25)) / 'extension.ps').read_text().strip() == \
        '25000'


def test_the_script_hands_both_paths_to_the_helper(tmp_path):
    script = script_of(EXTENSION).read_text()
    executed = '\n'.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert 'dashboard.execution.scripts.pdc_extension' in executed
    assert '--assessment ../07_micelle_assessment' in executed
    assert '--assessment-stage ../06_assessment' in executed
    assert 'convert-tpr' not in executed and '-cpi' not in executed, 'both are the helper\'s decisions, not the script\'s'
    assert 'pdc_snapshot' not in executed, 'the extension no longer samples a snapshot series'
    prepared(tmp_path), 'the run prepares'


def test_the_stage_passes_no_ntmpi_and_leaves_the_budget_to_the_helper():
    script = script_of(EXTENSION).read_text()
    executed = '\n'.join(line for line in script.splitlines() if not line.strip().startswith('#'))
    helper = Path(pdc.__file__).resolve().parents[1] / 'scripts' / 'pdc_extension.py'

    assert '-ntmpi' not in executed, 'gmx here is an MPI-only build: -ntmpi aborts mdrun before the first step'
    assert 'MDRUN_FLAGS' in helper.read_text() and 'MDRUN_LAUNCHER' in helper.read_text(), \
        'the budget comes from the environment, in Python'


def test_the_extension_stage_declares_the_inputs_it_reads(tmp_path):
    run = prepared(tmp_path)

    assert (extension_inputs(run) / 'extension.mdp').is_file()
    assert (extension_inputs(run) / 'extension.ps').is_file()
    for name in pdc.stage_by_name(EXTENSION).inputs:
        if str(name).startswith('../../inputs/'):
            assert (extension_inputs(run) / str(name)[len('../../inputs/'):]).is_file(), name


def test_the_run_records_both_durations_it_will_spend(tmp_path):
    manifest = json.loads((prepared(tmp_path) / 'manifest.json').read_text())

    assert manifest['extension_ps'] == 900000
    assert manifest['assessment_steps'] > 0
