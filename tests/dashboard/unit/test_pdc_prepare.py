"""The protein-detergent complex system-preparation stage.

`pdc.prepare` is what turns a panel's choice into a runnable stage, and it did not exist: the adapter declared six
stages and nothing wrote the scripts they name, so a pdc job could not be created at all. These tests pin what it
writes, what the generated script runs, and the two things the entry point refuses to guess (a template that
cannot build a system, and a topology whose molecule names nothing has produced yet).

They build their own molecule tree rather than reading `molecules/`: a test that read the developer's template
would report nothing about this code and would change meaning the day that file changed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from dashboard.execution.adapters import pdc
from dashboard.execution.scripts import pdc_build

TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'DDM', 'type': 'registered-template'}],
}
PROTEIN = 'molecules/DDM/protein.pdb'
TEMPLATE_PATH = 'molecules/DDM/micelle_template.json'


def gro_line(residue: str, name: str, number: int, xyz) -> str:
    return f'{number:5d}{residue:<5}{name:>5}{number:5d}{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}'


def write_gro(path: Path, atoms) -> Path:
    """A CG structure for the stage to read, so no test needs martinize2 to exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [gro_line(residue, name, index + 1, xyz) for index, (residue, name, xyz) in enumerate(atoms)]
    path.write_text('protein\n{0}\n{1}\n   4.00000   4.00000   4.00000\n'.format(len(lines), '\n'.join(lines)))
    return path


def molecule_tree(tmp_path: Path, template: dict | None = None) -> Path:
    """A molecule directory shaped like the ones the catalogue lists."""
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text('[ moleculetype ]\nDDM             1\n')
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE if template is None else template))
    (molecule / 'protein.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')
    return tmp_path


def prepared(tmp_path: Path, settings: dict | None = None, template: str = TEMPLATE_PATH):
    root = molecule_tree(tmp_path)
    numbers = {'seed': 20260930, 'aggregation_number': 8, 'box_margin_nm': 2.0, 'initial_z_nm': 6.0}
    numbers.update(settings or {})
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, protein=PROTEIN, template=template, settings=numbers, project_root=root)
    return run


def stage_directory(run: Path) -> Path:
    return run / Path(pdc.STAGES[0].relative).parent


def test_every_stage_directory_the_contract_names_exists(tmp_path):
    run = prepared(tmp_path)

    for stage in pdc.STAGES:
        assert (run / Path(stage.relative)).is_file(), f'{stage.name} has no script'


def test_the_system_stage_script_runs_the_entry_point_from_its_own_directory(tmp_path):
    script = (stage_directory(prepared(tmp_path)) / Path(pdc.STAGES[0].relative).name).read_text()

    assert 'set -eu' in script
    assert 'cd "$(dirname "$0")"' in script
    assert '-m dashboard.execution.scripts.pdc_build --stage .' in script
    assert str(sys.executable) in script, 'the script runs the interpreter that prepared it'
    assert f'PYTHONPATH={tmp_path}' in script, 'the entry point must import from the tree, whatever calls it'


def test_the_stages_that_have_no_script_say_so_instead_of_failing_obscurely(tmp_path):
    run = prepared(tmp_path)

    for stage in pdc.STAGES[2:]:
        script = (run / Path(stage.relative)).read_text()
        assert 'not written yet' in script, f'{stage.name} pretends to run'
        assert script.strip().endswith('exit 3')


def test_the_settings_carry_the_decisions_the_run_recorded(tmp_path):
    settings = json.loads((stage_directory(prepared(tmp_path)) / pdc.SETTINGS_NAME).read_text())

    assert settings['seed'] == 20260930 and settings['aggregation_number'] == 8
    assert (settings['box_margin_nm'], settings['initial_z_nm']) == (2.0, 6.0)
    assert settings['radius_nm'] > 0, 'the placement radius is a number, never a missing key'
    assert settings['protein'] == PROTEIN and settings['template'] == TEMPLATE_PATH
    assert Path(settings['project_root']) == tmp_path


def test_the_declared_inputs_are_written_before_the_stage_runs(tmp_path):
    stage = stage_directory(prepared(tmp_path))

    for name in pdc.STAGES[0].inputs:
        assert (stage / name).is_file(), f'{name} is declared an input and is missing'
    assert (stage / 'detergent.itp').read_text().startswith('[ moleculetype ]')


def test_a_seed_is_required_rather_than_defaulted(tmp_path):
    molecule_tree(tmp_path)
    (tmp_path / 'run').mkdir()

    with pytest.raises(ValueError, match='seed'):
        pdc.prepare(tmp_path / 'run', protein=PROTEIN, template=TEMPLATE_PATH,
                    settings={'aggregation_number': 8}, project_root=tmp_path)


def test_a_build_without_a_protein_says_what_is_missing(tmp_path):
    with pytest.raises(ValueError, match='protein and a detergent template'):
        pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=tmp_path)


def test_the_panels_setting_names_reach_the_builders_own(tmp_path):
    """The route hands over what the panel sends (`pdc_seed`); the settings file is spelled for the builders."""
    run = prepared(tmp_path, settings={'pdc_seed': 7654321, 'pdc_assessment_ns': 25})
    settings = json.loads((stage_directory(run) / pdc.SETTINGS_NAME).read_text())

    assert settings['seed'] == 7654321
    assert settings['assessment_ns'] == 25


def test_the_run_record_names_the_stages_and_the_limits(tmp_path):
    record = json.loads((prepared(tmp_path) / 'manifest.json').read_text())

    assert record['run_type'] == 'pdc'
    assert record['stage_plan'] == [[stage.name, stage.relative] for stage in pdc.STAGES]
    assert any('centre per molecule' in line for line in record['limitations'])
    assert set(record['tools']) == {'gmx', 'martinize2'}


def test_the_entry_point_applies_the_builders_rather_than_restating_them():
    source = Path(pdc_build.__file__).read_text()

    for call in ('pdc_box.initial_box', 'pdc_box.extended_box', 'pdc_placement.place_detergents',
                 'pdc_protein.martinize_command', 'pdc_view.read_gro'):
        assert call in source, f'{call} is the rule this stage must apply, not re-implement'
    assert '+ 2 *' not in source, 'the box arithmetic belongs to pdc_box'


def test_the_stage_builds_the_box_the_placement_and_the_report(tmp_path):
    """Without martinize2: the stage reads the CG structure it is given, places, and writes what it decided."""
    stage = stage_directory(prepared(tmp_path))
    write_gro(stage / pdc_build.CG_DIRECTORY / 'protein_CG.gro',
              [('PRO', 'B01', (0.0, 0.0, 0.0)), ('PRO', 'B02', (1.0, 0.0, 0.0)), ('PRO', 'B03', (0.0, 1.0, 0.0))])

    code = pdc_build.build(stage)
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    system = (stage / 'system.gro').read_text().splitlines()

    assert code == 3, 'the topology is the one thing this stage still refuses to write'
    assert report['valid'] is True and report['placed_detergents'] == 8
    assert report['protein_beads'] == 3 and report['protein_clearance_nm'] > 0
    assert report['box_nm'][2] >= report['box_nm_initial'][2], 'the box grows for the placed detergents'
    assert int(system[1]) == 11, 'three protein beads and eight detergent centres'
    assert report['system_top'].startswith('not written')


def test_the_reader_the_stage_uses_returns_the_shape_the_stage_indexes(tmp_path):
    """`read_gro` documented tuples and returned dicts, which is how this stage first read 'position' as letters."""
    from dashboard.execution.adapters import pdc_view

    path = write_gro(tmp_path / 'protein.gro', [('PRO', 'B01', (0.0, 0.0, 0.0))])
    atoms = pdc_view.read_gro(path)

    assert [sorted(atom) for atom in atoms] == [['name', 'position', 'residue']]
    assert atoms[0]['position'] == [0.0, 0.0, 0.0]


def test_a_template_that_cannot_build_a_system_refuses_before_placing(tmp_path):
    stage = stage_directory(prepared(tmp_path))
    (tmp_path / 'molecules' / 'DDM' / 'micelle_template.json').write_text(
        json.dumps({**TEMPLATE, 'beads': []}))

    code = pdc_build.build(stage)
    report = json.loads((stage / pdc.REPORT_NAME).read_text())

    assert code == 2 and report['valid'] is False
    assert report['template_issues'] == ['template has no beads']
    assert not (stage / 'system.gro').exists(), 'a refused build writes no system'
