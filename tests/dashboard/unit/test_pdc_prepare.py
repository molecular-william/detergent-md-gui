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
from pathlib import Path

import pytest

from dashboard import martini3
from dashboard.execution.adapters import pdc
from dashboard.execution.scripts import pdc_build
from tests.dashboard.pdc_fixtures import inputs_dir, molecule_tree, prepared_run, script_of, settings_of, stage_dir, system_stage

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
#: The stages that hand a topology to `grompp`; every one of them reads `system.top` from its own directory.
GROMPP_STAGES = ('Energy minimisation', 'NVT equilibration', 'NPT equilibration', 'CG assessment MD',
                 'CG extension MD')
#: A detergent topology as `prepare` writes one for a mapped build: one molecule type with one bead.
DETERGENT_ITP = '[ moleculetype ]\nDDM_CG 1\n\n[ atoms ]\n1 C1 1 DDM_CG DDM 1 0 72\n'


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
    return run / pdc.STAGES_DIRECTORY / Path(pdc.stage_by_name(SYSTEM_STAGE).relative).parent


def built_system_topology(run: Path) -> Path:
    """The system stage's topology as the build writes it, with the run's generated detergent and a protein tree.

    The test writes martinize2's shape (one molecule in `cg/`) rather than running the tool: what this is for is the
    topology's includes, which are the installed Martini 3 set, the detergent in `inputs/`, and the protein's itps
    reached from the build stage. The build stage holds that tree; no other stage carries a copy.
    """
    detergent = run / pdc.INPUTS_DIRECTORY / pdc.DETERGENT_TOPOLOGY
    detergent.write_text(DETERGENT_ITP)
    system = system_stage(run)
    cg = system / pdc.PROTEIN_TOPOLOGY_DIRECTORY
    cg.mkdir(exist_ok=True)
    (cg / 'molecule_0.itp').write_text('[ moleculetype ]\nPROT 1\n\n[ atoms ]\n1 C1 1 PROT B01 1 0 72\n')
    (cg / 'protein.top').write_text('#include "molecule_0.itp"\n\n[ system ]\nTitle\n\n[ molecules ]\n'
                                    'molecule_0 1\n')
    pdc_build.write_topologies(system, cg / 'protein.top', detergent, 6)
    return system


def assert_topology_includes_resolve(run: Path, system: Path) -> None:
    """Every include of the built `system.top` resolves from each grompp stage's own directory.

    The topology is copied forward as the writable working copy, so the stage that reads it is the directory
    `grompp` resolves its includes in. Nothing -- the Martini set, the detergent or the protein tree -- is copied
    beside it: each is named where it lies.
    """
    includes = re.findall(r'#include "([^"]+)"', (system / 'system.top').read_text())
    assert includes, 'the built topology names no include, so this checks nothing'
    for name in GROMPP_STAGES:
        directory = stage_dir(run, name)
        for include in includes:
            assert (directory / include).is_file(), \
                f'{name} runs grompp on a topology including {include}, which does not resolve from its directory'


def test_only_the_stages_that_will_run_get_a_directory(tmp_path):
    """A prepared run's `stages/` holds one empty directory per stage that will run, and nothing for the rest.

    The script is a repository file recorded in `stage_scripts`, so nothing is written inside a stage directory
    either: what lives there is what the stage itself writes when it runs.
    """
    run = prepared(tmp_path)

    recorded = json.loads((run / 'manifest.json').read_text())
    assert recorded['skipped_stages'] == {}
    for stage in pdc.STAGES:
        directory = run / pdc.STAGES_DIRECTORY / Path(stage.relative).parent
        assert directory.is_dir(), f'{stage.name} has no directory'
        assert list(directory.iterdir()) == [], f'{stage.name} has files nothing wrote'


def test_the_system_stage_script_is_the_repositorys_and_runs_the_entry_point(tmp_path):
    run = prepared(tmp_path)
    script = script_of(SYSTEM_STAGE).read_text()

    assert '-m dashboard.execution.scripts.pdc_build --stage .' in script
    assert '${PYTHON:-python}' in script, 'the executor may hand the interpreter over; the venv python is the default'
    assert 'REPO_ROOT' in script and 'PYTHONPATH' in script, 'the entry point must import from the tree'
    recorded = json.loads((run / 'manifest.json').read_text())['stage_scripts'][SYSTEM_STAGE]
    assert recorded['path'] == pdc.stage_by_name(SYSTEM_STAGE).script
    assert len(recorded['sha256']) == 64


def test_every_stage_records_a_repository_script_and_the_back_map_names_its_tool(tmp_path):
    run = prepared(tmp_path)
    recorded = json.loads((run / 'manifest.json').read_text())['stage_scripts']

    for stage in pdc.STAGES:
        assert recorded[stage.name]['path'] == stage.script
        assert script_of(stage.name).read_text().startswith('#!'), f'{stage.name} has no runnable script'
    backmap = script_of('Back-mapping (CG2AT2)').read_text()
    assert 'CG2AT' in backmap and '-o align' in backmap, 'the back-map names its tool and its method'
    assert not list(run.glob('**/*.py')), 'no code is copied into the run'
    assert not list(run.glob('**/*.sh')), 'no code is copied into the run'


def test_the_settings_carry_the_decisions_the_run_recorded(tmp_path):
    settings = settings_of(prepared(tmp_path))

    assert settings['seed'] == 20260930 and settings['aggregation_number'] == 8
    assert (settings['box_margin_nm'], settings['initial_z_nm']) == (2.0, 6.0)
    assert settings['radius_nm'] > 0, 'the placement radius is a number, never a missing key'
    assert settings['protein'] == PROTEIN and settings['template'] == TEMPLATE_PATH
    assert Path(settings['project_root']) == tmp_path


def test_prepare_writes_its_generated_data_into_a_recorded_inputs_tree(tmp_path):
    """Everything `prepare` synthesizes is written by value into `inputs/` and named in the run's input record."""
    run = prepared(tmp_path)
    record = json.loads((run / 'manifest.json').read_text())

    assert record['layout_version'] == 3
    assert (run / 'inputs' / pdc.SETTINGS_NAME).is_file()
    assert (run / pdc.STAGES_DIRECTORY).is_dir()
    generated = {entry['label'] for entry in record['inputs'] if entry['kind'] == 'generated'}
    for name in (pdc.SETTINGS_NAME, 'system_EMPTY.top', 'minimisation.mdp', 'nvt.mdp', 'npt.mdp',
                 'assessment.mdp', 'extension.mdp', 'extension.ps', '03_minimisation.json'):
        assert name in generated, f'{name} is generated data and is not recorded'
    assert not (run / 'inputs' / 'detergent.itp').exists(), 'the template topology is referenced, not copied'


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
    assert (tmp_path / 'run/inputs/protein.pdb').read_text().startswith('; no protein')
    skipped = json.loads((tmp_path / 'run/manifest.json').read_text())['skipped_stages']
    assert set(skipped) == {'Protein preparation', 'Back-mapping (CG2AT2)'}
    assert not (tmp_path / 'run/stages/01_prepare').exists()
    assert not (tmp_path / 'run/stages/10_backmap').exists()

    readiness = pdc.readiness(template=TEMPLATE_PATH, project_root=root)
    assert readiness['ready'] is True and readiness['blockers'] == []
    assert any('empty micelle' in str(check.get('path')) for check in readiness['checks'])


def test_the_panels_setting_names_reach_the_builders_own(tmp_path):
    """The route hands over what the panel sends (`pdc_seed`); the settings file is spelled for the builders."""
    run = prepared(tmp_path, settings={'pdc_seed': 7654321, 'pdc_assessment_ns': 25})
    settings = settings_of(run)

    assert settings['seed'] == 7654321
    assert settings['assessment_ns'] == 25


def test_the_run_record_names_the_stages_and_the_limits(tmp_path):
    record = json.loads((prepared(tmp_path) / 'manifest.json').read_text())

    assert record['run_type'] == 'pdc'
    assert record['stage_plan'] == [[stage.name, stage.relative] for stage in pdc.STAGES]
    assert record['layout_version'] == 3 and record['skipped_stages'] == {}
    assert record['input_snapshot_sha256']
    assert any('centre per molecule' in line for line in record['limitations'])
    assert set(record['tools']) == {'gmx', 'martinize2', 'pdb2pqr'}, \
        'the preparer the optional prepare step runs is recorded with the tools the run always resolves'


def test_a_mapped_build_does_not_call_itself_one_centre_per_molecule():
    """The limit follows what the build did: a mapping supplies the beads, so that sentence would be false.

    And no run's record may say the assessment, removal, extension or back-mapping scripts are unimplemented -- they
    are copied into every run, so that sentence told a reader the pipeline was not there.
    """
    mapped = pdc._limitations({'mapping': 'mapping_candidate_0123456789abcdef0123456789abcdef.json'})
    unmapped = pdc._limitations({'mapping': None})

    assert any('mapping_candidate_0123456789abcdef0123456789abcdef.json' in line for line in mapped), mapped
    assert not any('centre per molecule' in line for line in mapped), mapped
    assert any('centre per molecule' in line for line in unmapped), unmapped
    for line in mapped + unmapped:
        assert 'B7b' not in line, line
        assert 'not implemented' not in line.lower(), line


def test_the_catalogue_says_what_the_template_lacks_not_that_the_pipeline_is_a_placeholder(tmp_path):
    """The one shipped template states a single bead at its origin and no shape; that is the template's limit.

    Calling it a "skeleton placeholder template, not a fitted detergent model" under the picker read as a verdict on
    the protein-detergent pipeline, which builds with a mapping's beads and runs its stages.
    """
    templates = pdc._templates(molecule_tree(tmp_path))
    assert templates, 'the fixture tree lists no template'
    for entry in templates:
        assert entry['files_present'], entry
        joined = ' '.join(entry['limitations'])
        assert 'bead shape' in joined, joined
        assert 'skeleton placeholder' not in joined, joined
        assert 'not a fitted detergent model' not in joined, joined


def test_the_entry_point_applies_the_builders_rather_than_restating_them():
    source = Path(pdc_build.__file__).read_text()

    for call in ('pdc_box.initial_box', 'pdc_box.extended_box', 'pdc_placement.place_detergents',
                 'pdc_protein.martinize_command', 'pdc_import.structure_atoms'):
        assert call in source, f'{call} is the rule this stage must apply, not re-implement'
    assert '+ 2 *' not in source, 'the box arithmetic belongs to pdc_box'


def test_the_stage_builds_the_box_the_placement_and_the_report(tmp_path):
    """Without martinize2: the stage reads the CG structure it is given, places, and writes what it decided."""
    stage = system_stage(prepared(tmp_path))
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
    # The stage writes the built system and nothing called a snapshot: the preview derives its own frame, and a
    # run no longer records a placement picture in a snapshot index.
    assert not (stage / 'snapshots.json').exists()
    assert not (stage / 'snapshots').exists()


def test_the_reader_the_stage_uses_returns_the_shape_the_stage_indexes(tmp_path):
    """`read_gro` documented tuples and returned dicts, which is how this stage first read 'position' as letters."""
    from dashboard.execution.adapters import pdc_view

    path = write_gro(tmp_path / 'protein.gro', [('PRO', 'B01', (0.0, 0.0, 0.0))])
    atoms = pdc_view.read_gro(path)

    assert [sorted(atom) for atom in atoms] == [['name', 'position', 'residue', 'residue_id']]
    assert atoms[0]['position'] == [0.0, 0.0, 0.0]


def test_a_template_that_cannot_build_a_system_refuses_before_placing(tmp_path):
    stage = system_stage(prepared(tmp_path))
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


def test_every_shared_stage_script_runs_under_an_interpreter_the_executor_can_choose(tmp_path):
    """A stage that calls python calls `$PYTHON`, which the executor may provide and the virtualenv python answers.

    The scripts are repository files now, so there is one place to check rather than one generated copy per run: every
    `pdc_*` shell script that calls an interpreter names `$PYTHON`, and none carries a bare `python` in an executed
    line.
    """
    del tmp_path
    scripts = sorted(script_of(stage.name) for stage in pdc.STAGES)
    assert scripts, 'the stages run no scripts'
    for script in scripts:
        text = script.read_text()
        executed = '\n'.join(line for line in text.splitlines() if not line.strip().startswith('#'))
        assert '\npython ' not in executed and not executed.startswith('python '), \
            f'{script.name} still calls a bare python'
        if ' -m dashboard.execution.scripts.' in executed:
            assert '${PYTHON:-python}' in text, f'{script.name} calls a python it does not let the executor choose'


def test_each_stage_declares_what_it_reads_and_no_stage_bakes_in_a_copy(tmp_path):
    """A stage's declarations name the run's own paths: generated data in `inputs/`, and the phase before it.

    Nothing is copied at prepare time, so every declared input either exists when the run is prepared (`inputs/`) or
    is a declared output of the stage before it.
    """
    run = prepared(tmp_path)
    outputs = {stage.name: {str(path) for path in stage.outputs} for stage in pdc.STAGES}

    for index, stage in enumerate(pdc.STAGES):
        earlier = [output for other in pdc.STAGES[:index] for output in outputs[other.name]]
        for entry in stage.inputs:
            entry = str(entry)
            if entry.startswith('../../inputs/'):
                relative = entry[len('../../inputs/'):]
                assert (inputs_dir(run) / relative).exists(), f'{stage.name} declares {entry}, which prepare did not write'
            elif entry.startswith('../'):
                relative = entry.split('/', 2)[2] if entry.count('/') >= 2 else entry
                assert any(item == relative or item.startswith(relative) for item in earlier), \
                    f'{stage.name} declares {entry}, which no earlier stage writes'
            else:
                assert any(item == entry or item.startswith(entry) for item in earlier), \
                    f'{stage.name} declares {entry} and no earlier stage writes it'


def test_the_published_set_is_recorded_as_installed_and_no_grompp_stage_copies_it_in(tmp_path):
    """`grompp` refused the solvated system because molecule type `W` was never defined anywhere.

    The set is the published Martini 3 lipid one: the bead types the detergent's own beads need, the solvents file
    that defines water as `W`, and the ions file that defines `NA` and `CL`. It is installed once under the workspace
    (`dashboard.martini3`), and the run records each file by path and digest rather than carrying a copy. No leg
    copies it into its working directory: the topology names it from where it is read, so the include resolves in
    place from every stage that runs `grompp`.
    """
    run = prepared(tmp_path)
    record = json.loads((run / 'manifest.json').read_text())
    installed = {entry['label']: entry for entry in record['inputs'] if entry['role'] == 'force_field'}
    assert set(installed) == set(pdc.FORCEFIELD_FILES)
    for name, entry in installed.items():
        assert entry['kind'] == 'published', entry
        assert entry['root'] == 'absolute', \
            'the test suite installs the set outside the workspace, so it has no workspace-relative spelling'
        assert Path(entry['path']) == martini3.path(name).resolve(), \
            'the record names the installed file every stage reads'
    assert settings_of(run)['force_field']['files'].keys() == set(pdc.FORCEFIELD_FILES)
    for name in GROMPP_STAGES:
        copied = script_of(name).read_text()
        for force_field in pdc.FORCEFIELD_FILES:
            assert force_field not in copied, f'{name} runs grompp and copies {force_field} in'
    assert_topology_includes_resolve(run, built_system_topology(run))


def test_the_run_records_where_its_parameters_came_from(tmp_path):
    """Provenance is the point of using a published set: a run names its version, not just its files."""
    root = molecule_tree(tmp_path)
    pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root)

    settings = settings_of(tmp_path / 'run')
    recorded = settings['detergent_model']
    force_field = settings['force_field']

    assert force_field['doi'] == '10.1021/acscentsci.5c00755'
    assert force_field['commit'] and force_field['repository'].startswith('https://github.com/')
    assert set(force_field['files']) == set(pdc.FORCEFIELD_FILES)
    assert all(entry['sha256'] and entry['bytes'] > 0 for entry in force_field['files'].values())
    assert recorded['mapping'] is None or 'mapping' in recorded


def test_a_stage_that_runs_grompp_gets_every_include_of_its_topology(tmp_path):
    """`grompp` reads the topology's includes from the directory the topology is in, so each one has to resolve there.

    Stage 1 writes `system.top`, which includes the installed Martini 3 set, the run's generated detergent topology
    and the protein's itps in `cg/`. Nothing is copied in beside it: the set is named from its install, the
    detergent from `inputs/`, and the protein tree from the build stage (`../02_system/cg/`). Those are the same
    spellings from every sibling stage under `stages/`, so the writable copy a leg carries forward still resolves
    every include from its own directory.
    """
    run = prepared(tmp_path)
    assert_topology_includes_resolve(run, built_system_topology(run))


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

    settings = settings_of(tmp_path / 'run')
    assert settings['tail_beads'] == ['TAIL1', 'TAIL2'], 'the aliphatic beads, and not the sugar bead'
    assert 'mapping' in settings['tail_beads_source']
    record = json.loads((tmp_path / 'run' / 'manifest.json').read_text())
    kinds = {entry['label']: entry['kind'] for entry in record['inputs']}
    assert kinds[pdc.DETERGENT_TOPOLOGY] == 'generated'
    assert kinds[pdc.DETERGENT_GEOMETRY] == 'generated'
    assert any(entry['role'] == 'mapping' and entry['kind'] == 'store' for entry in record['inputs']), \
        'the mapping lives outside the workspace here, so it is recorded absolutely'


def test_a_template_that_names_its_own_tail_roles_is_believed_first(tmp_path):
    """The template is the long-term home for this; the mapping is only the fallback."""
    root = molecule_tree(tmp_path)
    template = json.loads((root / 'molecules' / 'DDM' / 'micelle_template.json').read_text())
    template['beads'] = [{'name': 'HEAD', 'role': 'head'}, {'name': 'TAIL', 'role': 'tail'}]
    (root / 'molecules' / 'DDM' / 'micelle_template.json').write_text(json.dumps(template))

    # No mapping: this case is about which source is believed, and the template's own roles are the one that wins.
    pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root)

    settings = settings_of(tmp_path / 'run')
    assert settings['tail_beads'] == ['TAIL']
    assert settings['tail_beads_source'] == 'the template, from its bead roles'

def test_a_prepared_protein_free_micelle_has_the_uniform_layout(tmp_path):
    """The acceptance shape: running stage directories, an `inputs/` with its record, and one manifest."""
    root = molecule_tree(tmp_path)
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root)

    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['layout_version'] == 3
    assert {'inputs', 'stage_scripts', 'skipped_stages'} <= set(manifest)
    assert manifest['inputs'] and manifest['input_snapshot_sha256']
    assert set(manifest['skipped_stages']) == {'Protein preparation', 'Back-mapping (CG2AT2)'}
    assert {path.name for path in (run / pdc.STAGES_DIRECTORY).iterdir()} == {
        '02_system', '03_minimisation', '04_nvt', '05_npt', '06_assessment', '07_micelle_assessment',
        '08_extension', '09_final_assessment'}
    assert (run / 'inputs' / 'inputs.json').is_file()
    assert not (run / '1_system').exists()
    assert not list(run.glob('**/*.py')) and not list(run.glob('**/*.sh'))


def test_the_executor_records_a_prepare_time_skip_without_a_directory(tmp_path):
    """`workflow.run` reads `skipped_stages` before the directory would be used: nothing ran, and it says why."""
    from dashboard import paths
    from dashboard.execution import workflow

    root = molecule_tree(tmp_path)
    run = tmp_path / 'run'
    run.mkdir()
    (run / 'logs').mkdir()
    # The upstream set is the repository's (`references/`), so `prepare` resolves it from the application's paths; the
    # record names its repository-owned sources against the project root the run was prepared in, so the executor's
    # verification runs under that same root. The installed Martini set is absolute: the test suite installs it
    # outside any workspace.
    pdc.prepare(run, template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root)
    with paths.use(paths.Paths(project_root=root, workspace=tmp_path / 'workspace')):
        workflow.run(run, run / 'logs' / 'console.log', stop_after='Protein preparation')

    entry = json.loads((run / 'manifest.json').read_text())['stages'][0]
    assert entry['name'] == 'Protein preparation' and entry['status'] == 'skipped'
    assert 'no protein' in entry['reason'] and entry['command'] == []
