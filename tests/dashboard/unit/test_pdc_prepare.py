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
import re
import sys
from pathlib import Path

import pytest

from dashboard.execution.adapters import pdc
from dashboard.execution.scripts import pdc_build
from tests.dashboard.pdc_fixtures import molecule_tree, prepared_run

TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'DDM', 'type': 'registered-template'}],
}
PROTEIN = 'molecules/DDM/protein.pdb'
TEMPLATE_PATH = 'molecules/DDM/micelle_template.json'
#: The stage these tests are about, by name: the plan's positions are data and the prepare step landed in front of
#: this one, so a test that counted its way to `STAGES[0]` would now be describing a different stage.
SYSTEM_STAGE = 'System preparation'


def gro_line(residue: str, name: str, number: int, xyz) -> str:
    return f'{number:5d}{residue:<5}{name:>5}{number:5d}{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}'


def write_gro(path: Path, atoms) -> Path:
    """A CG structure for the stage to read, so no test needs martinize2 to exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [gro_line(residue, name, index + 1, xyz) for index, (residue, name, xyz) in enumerate(atoms)]
    path.write_text('protein\n{0}\n{1}\n   4.00000   4.00000   4.00000\n'.format(len(lines), '\n'.join(lines)))
    return path


def write_cg_pdb(path: Path, atoms) -> Path:
    """The CG structure as martinize2 writes it: `-x` is a PDB, one `ATOM` record per bead, Angstroms.

    The positions handed in are nanometres -- what the stage's builders work in -- so they are written the way the
    tool writes them and read back by the stage's own reader.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'ATOM  {index:5d} {name:^4s} {residue:>3s} A{residue_id:4d}    '
             f'{xyz[0] * 10.0:8.3f}{xyz[1] * 10.0:8.3f}{xyz[2] * 10.0:8.3f}  1.00  0.00'
             for index, (residue_id, residue, name, xyz) in enumerate(atoms, 1)]
    path.write_text('\n'.join(lines) + '\nEND\n')
    return path


def prepared(tmp_path: Path, settings: dict | None = None, template: str = TEMPLATE_PATH):
    # The box margins this file reads are explicit: they are what several of its assertions are about.
    return prepared_run(tmp_path, settings={'box_margin_nm': 2.0, 'initial_z_nm': 6.0} | (settings or {}),
                        template=template)


def stage_directory(run: Path) -> Path:
    return run / Path(pdc.stage_by_name(SYSTEM_STAGE).relative).parent


def test_every_stage_directory_the_contract_names_exists(tmp_path):
    run = prepared(tmp_path)

    for stage in pdc.STAGES:
        assert (run / Path(stage.relative)).is_file(), f'{stage.name} has no script'


def test_the_system_stage_script_runs_the_entry_point_from_its_own_directory(tmp_path):
    script = (stage_directory(prepared(tmp_path)) / Path(pdc.stage_by_name(SYSTEM_STAGE).relative).name).read_text()

    assert 'set -eu' in script
    assert 'cd "$(dirname "$0")"' in script
    assert '-m dashboard.execution.scripts.pdc_build --stage .' in script
    assert str(sys.executable) in script, 'the script runs the interpreter that prepared it'
    assert f'PYTHONPATH={tmp_path}' in script, 'the entry point must import from the tree, whatever calls it'


def test_every_stage_has_a_script_and_the_back_map_names_its_tool(tmp_path):
    run = prepared(tmp_path)

    for stage in pdc.STAGES:
        script = (run / Path(stage.relative)).read_text()
        assert script.startswith('#!'), f'{stage.name} has no runnable script'
    backmap = (run / Path(pdc.stage_by_name('Back-mapping (CG2AT2)').relative)).read_text()
    assert 'CG2AT' in backmap and '-o align' in backmap, 'the back-map names its tool and its method'


def test_the_settings_carry_the_decisions_the_run_recorded(tmp_path):
    settings = json.loads((stage_directory(prepared(tmp_path)) / pdc.SETTINGS_NAME).read_text())

    assert settings['seed'] == 20260930 and settings['aggregation_number'] == 8
    assert (settings['box_margin_nm'], settings['initial_z_nm']) == (2.0, 6.0)
    assert settings['radius_nm'] > 0, 'the placement radius is a number, never a missing key'
    assert settings['protein'] == PROTEIN and settings['template'] == TEMPLATE_PATH
    assert Path(settings['project_root']) == tmp_path


def test_the_declared_inputs_are_written_before_the_stage_runs(tmp_path):
    stage = stage_directory(prepared(tmp_path))

    for name in pdc.stage_by_name(SYSTEM_STAGE).inputs:
        assert (stage / name).is_file(), f'{name} is declared an input and is missing'
    assert (stage / 'detergent.itp').read_text().startswith('[ moleculetype ]')


def test_a_seed_is_required_rather_than_defaulted(tmp_path):
    molecule_tree(tmp_path)
    (tmp_path / 'run').mkdir()

    with pytest.raises(ValueError, match='seed'):
        pdc.prepare(tmp_path / 'run', protein=PROTEIN, template=TEMPLATE_PATH,
                    settings={'aggregation_number': 8}, project_root=tmp_path)


def test_a_build_without_a_template_says_what_is_missing(tmp_path):
    """A missing template is the oversight; a template with no protein is the empty micelle, below."""
    with pytest.raises(ValueError, match='needs a detergent template'):
        pdc.prepare(tmp_path / 'run', settings={'seed': 1}, project_root=tmp_path)


def test_an_empty_micelle_is_a_stated_choice_rather_than_a_missing_protein(tmp_path):
    """The spec's protein-free build: an absence that is a choice, told apart from one that is an oversight."""
    root = molecule_tree(tmp_path)

    pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root)
    assert (tmp_path / 'run/1_system/protein.pdb').read_text().startswith('; no protein')

    readiness = pdc.readiness(template=TEMPLATE_PATH, project_root=root)
    assert readiness['ready'] is True and readiness['blockers'] == []
    assert any('empty micelle' in str(check.get('path')) for check in readiness['checks'])


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
    assert set(record['tools']) == {'gmx', 'martinize2', 'pdb2pqr'}, \
        'the preparer the optional prepare step runs is recorded with the tools the run always resolves'


def test_the_entry_point_applies_the_builders_rather_than_restating_them():
    source = Path(pdc_build.__file__).read_text()

    for call in ('pdc_box.initial_box', 'pdc_box.extended_box', 'pdc_placement.place_detergents',
                 'pdc_protein.martinize_command', 'pdc_import.structure_atoms'):
        assert call in source, f'{call} is the rule this stage must apply, not re-implement'
    assert '+ 2 *' not in source, 'the box arithmetic belongs to pdc_box'


def test_the_stage_builds_the_box_the_placement_and_the_report(tmp_path):
    """Without martinize2: the stage reads the CG structure it is given, places, and writes what it decided."""
    stage = stage_directory(prepared(tmp_path))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb',
                 [(1, 'PRO', 'B01', (0.0, 0.0, 0.0)), (1, 'PRO', 'B02', (1.0, 0.0, 0.0)),
                  (1, 'PRO', 'B03', (0.0, 1.0, 0.0))])

    code = pdc_build.build(stage)
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    system = (stage / 'system.gro').read_text().splitlines()

    assert code == 3, 'the topology is the one thing this stage still refuses to write'
    assert report['valid'] is True and report['placed_detergents'] == 8
    assert report['protein_beads'] == 3 and report['protein_clearance_nm'] > 0
    assert report['box_nm'][2] >= report['box_nm_initial'][2], 'the box grows for the placed detergents'
    assert int(system[1]) == 11, 'three protein beads and eight detergent centres'
    assert report['system_top'].startswith('not written')
    # The state before dynamics is recorded even though the stage stops here: it is the frame a reader judges the
    # placement from, and the one snapshot no run may be without.
    index = json.loads((stage / 'snapshots.json').read_text())
    assert [entry['name'] for entry in index['snapshots']] == ['placement']


def test_the_reader_the_stage_uses_returns_the_shape_the_stage_indexes(tmp_path):
    """`read_gro` documented tuples and returned dicts, which is how this stage first read 'position' as letters."""
    from dashboard.execution.adapters import pdc_view

    path = write_gro(tmp_path / 'protein.gro', [('PRO', 'B01', (0.0, 0.0, 0.0))])
    atoms = pdc_view.read_gro(path)

    assert [sorted(atom) for atom in atoms] == [['name', 'position', 'residue', 'residue_id']]
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


def test_a_protein_free_build_writes_topologies_with_no_protein_row(tmp_path):
    """The same two files with no protein row, so a reader downstream needs no special case."""
    from dashboard.execution.scripts import pdc_build

    stage = tmp_path / 'stage'
    stage.mkdir()
    (stage / 'det.itp').write_text('[ moleculetype ]\nDDM_CG 1\n')

    info = pdc_build.write_topologies(stage, None, stage / 'det.itp', 6)

    assert info == {'protein_molecule': None, 'detergent_molecule': 'DDM_CG', 'detergents': 6}
    assert 'DDM_CG\t6' in (stage / 'system.top').read_text()
    empty = (stage / 'system_EMPTY.top').read_text()
    assert empty.split('[ molecules ]')[1].strip() == '', 'the empty-micelle topology lists no molecule'


def test_every_copied_stage_script_runs_under_this_interpreters_own_python(tmp_path):
    """`python` on PATH is not the venv that carries this repository, which cost a run at its second stage.

    A stage that calls python at all has to call *this* interpreter -- which is what the check reads out of its
    executed lines. The generated equilibration legs call none: they are grompp and mdrun, with the step count read
    by awk, so there is no interpreter in them to get wrong.
    """
    import sys

    root = molecule_tree(tmp_path)
    pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root)

    scripts = sorted((tmp_path / 'run').glob('*/*.sh'))
    assert scripts, 'the run should hold stage scripts'
    for script in scripts:
        text = script.read_text()
        assert '\npython ' not in text and not text.startswith('python '), \
            f'{script.name} still calls a bare python'
        executed = '\n'.join(line for line in text.splitlines() if not line.strip().startswith('#'))
        if 'python ' in executed:
            assert sys.executable in text, f'{script.name} calls a python that is not this application\'s'


def test_each_stage_copies_in_the_inputs_it_declares(tmp_path):
    """A stage reads the phase before it; nothing else puts a file in its directory, which cost a run at stage 2."""
    root = molecule_tree(tmp_path)
    pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root)

    for stage in pdc.STAGES:
        script = tmp_path / 'run' / stage.relative
        text = script.read_text()
        for entry in stage.inputs:
            if str(entry).startswith('../'):
                # The phase before it stays immutable, so the script copies the input in itself.
                assert f'cp -f {entry} ' in text, f'{stage.relative} never copies its declared input {entry}'
            else:
                # A local input is one this stage already has when it starts, which is checkable here.
                assert (script.parent / str(entry)).is_file(), \
                    f'{stage.relative} declares {entry}, which is not in its directory when the run is prepared'


def test_the_topologies_carry_the_published_set_that_defines_water_and_ions(tmp_path):
    """`grompp` refused the solvated system because molecule type `W` was never defined anywhere.

    The set is the published Martini 3 lipid one: the bead types the detergent's own beads need, the solvents file
    that defines water as `W`, and the ions file that defines `NA` and `CL`. Each file is checked for what it is
    there to provide, so a set that quietly lost its ions fails here rather than in a run's second stage.
    """
    root = molecule_tree(tmp_path)
    pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root)

    system = tmp_path / 'run' / '1_system'
    # Each file is here for something specific, and that is what is checked: the main file defines *bead types*
    # (its `[ moleculetype ]` blocks are molecules, of which it has none), while the solvents and ions files define
    # the molecules a solvated system lists.
    beads, solvents, ions = pdc.FORCEFIELD_FILES
    expectations = ((beads, 'bead', 'C1'), (solvents, 'molecule', 'W'),
                    (ions, 'molecule', 'NA'), (ions, 'molecule', 'CL'))

    from dashboard.execution.scripts import pdc_build

    (system / 'det.itp').write_text('[ moleculetype ]\nDDM_CG 1\n')
    pdc_build.write_topologies(system, None, system / 'det.itp', 6)

    for name in ('system.top', 'system_EMPTY.top'):
        text = (system / name).read_text()
        for forcefield in pdc.FORCEFIELD_FILES:
            assert f'#include "{forcefield}"' in text, f'{name} does not include {forcefield}'

    for forcefield, kind, name in expectations:
        assert (system / forcefield).is_file(), f'the run has to carry {forcefield}'
        text = (system / forcefield).read_text(errors='replace')
        if kind == 'molecule':
            pattern = r'\[\s*moleculetype\s*\](?:\s*;[^\n]*\n|\s*\n)*\s*' + name + r'\b'
        else:
            pattern = r'^\s*' + name + r'\s+\S+\s+1\s'
        assert re.search(pattern, text, re.M), f'{forcefield} does not define {kind} {name}'


def test_the_run_records_where_its_parameters_came_from(tmp_path):
    """Provenance is the point of using a published set: a run names its version, not just its files."""
    root = molecule_tree(tmp_path)
    pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root)

    recorded = json.loads((tmp_path / 'run' / '1_system' / 'pdc-settings.json').read_text())['detergent_model']
    force_field = json.loads((tmp_path / 'run' / '1_system' / 'pdc-settings.json').read_text())['force_field']

    assert force_field['doi'] == '10.1021/acscentsci.5c00755'
    assert force_field['commit'] and force_field['repository'].startswith('https://github.com/')
    assert set(force_field['files']) == set(pdc.FORCEFIELD_FILES)
    assert all(entry['sha256'] and entry['bytes'] > 0 for entry in force_field['files'].values())
    assert recorded['mapping'] is None or 'mapping' in recorded


def test_a_stage_that_runs_grompp_gets_every_include_of_its_topology(tmp_path):
    """`grompp` reads the topology's includes from the stage directory, so each one has to be there.

    Stage 1 writes `system.top`, which includes the detergent's own CG topology and the force field; the stage that
    solvates it edits a copy in its own directory, and grompp resolves the includes beside that copy. The detergent
    topology is produced by stage 1 rather than by the preparation, which is why it has to be declared.
    """
    root = molecule_tree(tmp_path)
    pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root)

    from dashboard.execution.scripts import pdc_build

    system = tmp_path / 'run' / '1_system'
    detergent = system / pdc.DETERGENT_TOPOLOGY
    detergent.write_text('[ moleculetype ]\nDDM_CG 1\n')
    pdc_build.write_topologies(system, None, detergent, 6)
    includes = re.findall(r'#include "([^"]+)"', (system / 'system.top').read_text())

    for stage in (pdc.stage_by_name('Energy minimisation'), pdc.stage_by_name('NPT equilibration'),
                  pdc.stage_by_name('CG assessment MD'), pdc.stage_by_name('CG extension MD')):
        declared = {str(entry).split('/')[-1] for entry in stage.inputs}
        copied = (tmp_path / 'run' / stage.relative).read_text()
        for include in includes:
            assert include in declared or include in copied, \
                f'{stage.relative} runs grompp on a topology including {include}, which is neither declared nor copied'


def test_the_mapping_answers_for_the_tail_when_the_template_names_none(tmp_path):
    """The criterion refuses a run that names no tail beads, and the skeleton template names none.

    Measured: a prepared run reached production and then stopped at "the run records no tail beads, so the criterion
    cannot tell a micelle from a crowd". The template is a placeholder -- one bead, no roles -- while the run's own
    mapping does know the tail, so the mapping answers and the settings say which source was used.
    """
    # The repository's own DDM is a tracked asset with a real topology; the mapping is the record the test builds.
    root = Path(__file__).resolve().parents[3]
    candidate = tmp_path / 'candidate.json'
    candidate.write_text(json.dumps({
        'schema_version': 3, 'molecule_id': 'DDM', 'name': 'a sugar bead and a tail bead', 'martini_version': 3,
        'beads': [{'name': 'S1A', 'type': 'SP1r', 'atoms': [1, 2]},
                  {'name': 'TAIL1', 'type': 'C1', 'atoms': [3, 4]},
                  {'name': 'TAIL2', 'type': 'C1', 'atoms': [5, 6]}],
        'connections': [['S1A', 'TAIL1'], ['TAIL1', 'TAIL2']]}))

    pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root,
                mapping=str(candidate))

    settings = json.loads((tmp_path / 'run' / '1_system' / 'pdc-settings.json').read_text())
    assert settings['tail_beads'] == ['TAIL1', 'TAIL2'], 'the aliphatic beads, and not the sugar bead'
    assert 'mapping' in settings['tail_beads_source']


def test_a_template_that_names_its_own_tail_roles_is_believed_first(tmp_path):
    """The template is the long-term home for this; the mapping is only the fallback."""
    root = molecule_tree(tmp_path)
    template = json.loads((root / 'molecules' / 'DDM' / 'micelle_template.json').read_text())
    template['beads'] = [{'name': 'HEAD', 'role': 'head'}, {'name': 'TAIL', 'role': 'tail'}]
    (root / 'molecules' / 'DDM' / 'micelle_template.json').write_text(json.dumps(template))

    # No mapping: this case is about which source is believed, and the template's own roles are the one that wins.
    pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root)

    settings = json.loads((tmp_path / 'run' / '1_system' / 'pdc-settings.json').read_text())
    assert settings['tail_beads'] == ['TAIL']
    assert settings['tail_beads_source'] == 'the template, from its bead roles'