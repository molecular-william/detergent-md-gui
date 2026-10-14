"""The prepare step: the residues a deposited structure left incomplete, rebuilt, and the protein protonated.

The plan's step 1 (`docs/superpowers/plans/2026-10-12-pdc-new-run-panel.md`) is optional and is the whole answer to a
structure the build refuses for a reason that is not about the placement at all: 4iar's deposited assembly is missing
side-chain atoms for 6 arginines, 9 lysines and a tryptophan, so 20 of its 928 coarse-grained beads have no position
and `pdc_placement` refuses the whole build rather than placing a belt against a protein no distance can be measured
to. The step named for it is PDB2PQR -- `pdb2pqr`'s own rebuild and protonation -- and the fix is that step, not a
placement that tolerates absent atoms.

What is pinned here: the step is a **stage** of its own, in front of every other stage, optional, recording `skipped`
(exit 4) with its reason when a run does not ask for it; it refuses by name when it is asked for and its tool cannot
be resolved; the structure it writes is the one the coarse-graining reads *and* it keeps the file's own membrane
statement, without which a stated bilayer would silently become the sphere; and its record's numbers are the tool's
own log lines rather than a count this repository made up.

Fixtures are built here and nothing reads the developer's workspace. Two tests run the real `pdb2pqr` (the declared
preparer), skipped where it cannot be resolved, because "do not invent a rebuild if a tested implementation exists"
is only true if the implementation is exercised.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from dashboard.execution import tools
from dashboard.execution.adapters import pdc, pdc_preparation
from dashboard.execution.scripts import pdc_build, pdc_prepare
from micelle.frame import stated_half_thickness_nm
from tests.dashboard.support import PROJECT_ROOT

STAGE = 'Protein preparation'
SYSTEM = 'System preparation'
TEMPLATE = {
    'name': 'DDM', 'residue': 'DDM', 'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp', 'beads': [{'name': 'DDM', 'type': 'registered-template'}],
}
#: The `REMARK` OPM writes into every structure it serves, which is where the belt's frame comes from. A prepared
#: structure that loses it makes a stated bilayer into the sphere the placement falls back on.
MEMBRANE_REMARK = 'REMARK      1/2 of bilayer thickness:   16.8'
PROTEIN_TEXT = (f'{MEMBRANE_REMARK}\n'
                'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n'
                'END\n')
#: A tool log as the real one reads, with the two things this step's record is made of: the version line, and one
#: `Added atom` line per heavy atom the rebuild actually built.
TOOL_LOG = ('INFO:PDB2PQR v3.7.1: biomolecular structure conversion software.\n'
            'INFO:Created biomolecule object with 379 residues and 2933 atoms.\n'
            'WARNING:Gap in backbone detected between ALA A 190 and SER A 197!\n'
            'INFO:Added atom CE to residue LYS A 1085 at coordinates -0.474, -13.297, -70.328\n'
            'INFO:Added atom NZ to residue LYS A 1085 at coordinates 0.208, -13.176, -71.642\n'
            'INFO:Added atom CH2 to residue TRP A 345 at coordinates -0.597, -18.371, 11.337\n'
            'INFO:Adding hydrogens to biomolecule.\n')


def molecule_tree(tmp_path: Path) -> Path:
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text(
        'HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text('[ moleculetype ]\nDDM             1\n')
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    (molecule / 'protein.pdb').write_text(PROTEIN_TEXT)
    return tmp_path


def prepared(tmp_path: Path, **settings):
    """A run, prepared with the fixture tree: the adapter's own `prepare`, not a hand-written settings file."""
    root = molecule_tree(tmp_path)
    run = tmp_path / 'run'
    run.mkdir()
    numbers = {'seed': 20261014, 'aggregation_number': 4}
    numbers.update(settings)
    pdc.prepare(run, protein='molecules/DDM/protein.pdb', template='molecules/DDM/micelle_template.json',
                settings=numbers, project_root=root)
    return run


def stage_directory(run: Path, name: str = STAGE) -> Path:
    """A stage's directory, by the stage's own name: the plan's positions moved when this stage landed."""
    return run / Path(pdc.stage_by_name(name).relative).parent


def settings_of(run: Path) -> dict:
    return json.loads((stage_directory(run, SYSTEM) / pdc.SETTINGS_NAME).read_text())


def stage_environment() -> dict:
    """The environment a stage runs under, with the repository importable the way a real run's root makes it."""
    return {**os.environ, 'PYTHONPATH': os.pathsep.join([str(PROJECT_ROOT), os.environ.get('PYTHONPATH', '')])}


def run_stage(run: Path, name: str = STAGE) -> subprocess.CompletedProcess:
    directory = stage_directory(run, name)
    return subprocess.run(['bash', str(run / pdc.stage_by_name(name).relative)], cwd=directory,
                          env=stage_environment(), capture_output=True, text=True)


def fake_pdb2pqr(*, added=None, returncode: int = 0, write_output: bool = True, log: str | None = None):
    """A `pdb2pqr` that writes exactly what its own command names, and the log the real one writes.

    It is handed the same things the real process is -- the command, and a working directory to log in -- so the
    command under test is the command that ran, flag for flag.
    """
    atoms = [('CE', 'LYS', 'A', '1085'), ('NZ', 'LYS', 'A', '1085')] if added is None else list(added)

    def run(argv, **kwargs):
        directory = Path(kwargs.get('cwd') or '.')
        output = Path(argv[argv.index('--pdb-output') + 1])
        if returncode == 0 and write_output:
            output.write_text('ATOM      1  N   LYS A1085       0.000   0.000   0.000  1.00  0.00           N\n'
                              'ATOM      2  CE  LYS A1085       0.100   0.000   0.000  1.00  0.00           C\n'
                              'ATOM      3  NZ  LYS A1085       0.200   0.000   0.000  1.00  0.00           N\n'
                              'END\n')
        text = log if log is not None else (
            'INFO:PDB2PQR v3.7.1: biomolecular structure conversion software.\n'
            + ''.join(f'INFO:Added atom {name} to residue {residue} {chain} {number} at coordinates 0, 0, 0\n'
                      for name, residue, chain, number in atoms))
        (directory / pdc_preparation.LOG_NAME).write_text(text)
        return subprocess.CompletedProcess(argv, returncode)

    return run


def cg_pdb(atoms) -> str:
    """A coarse-grained structure as martinize2 writes one: `ATOM` records in Angstroms, read back by the stage."""
    return '\n'.join(f'ATOM  {index:5d} {name:^4s} {residue:>3s} A{residue_id:4d}    '
                     f'{xyz[0] * 10.0:8.3f}{xyz[1] * 10.0:8.3f}{xyz[2] * 10.0:8.3f}  1.00  0.00'
                     for index, (residue_id, residue, name, xyz) in enumerate(atoms, 1)) + '\nEND\n'


def write_cg_pdb(path: Path, atoms=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cg_pdb(atoms if atoms is not None else [(1, 'PRO', 'B01', (0.0, 0.0, 0.0))]))
    return path


# --- the plan: one stage, first, and nothing existing moves ------------------------------------------------------

def test_the_plan_gains_the_preparation_first_and_no_existing_stage_moves():
    plan = [record.name for record in pdc.STAGES]

    assert plan[0] == STAGE, "the plan's step 1 runs before everything else"
    assert plan[1:] == ['System preparation', 'Energy minimisation', 'NVT equilibration', 'NPT equilibration',
                        'CG assessment MD', 'Micelle assessment', 'CG extension MD', 'Final assessment',
                        'Back-mapping (CG2AT2)']
    assert pdc.stage_by_name(STAGE).relative == '0_prepare/pdc_prepare.sh'
    assert pdc.stage_by_name(SYSTEM).relative == '1_system/prepare_system.sh', \
        'the stage that existed keeps its own directory and script'


def test_the_preparation_is_a_choice_a_run_states_and_it_is_off_by_default():
    """The plan's step 1 is *optional*, so a caller that never heard of it builds exactly what it built before."""
    assert pdc.DEFAULTS['prepare_protein'] is False
    choices = pdc.validate_payload({'seed': 1, 'prepare_protein': True})
    assert choices['prepare_protein'] is True
    assert pdc.validate_payload({'seed': 1})['prepare_protein'] is False
    with pytest.raises(ValueError, match='protein-preparation'):
        pdc.validate_payload({'seed': 1, 'prepare_protein': 'yes'})


def test_the_queue_route_advertises_the_choice_so_a_posted_one_is_not_dropped():
    kept = set(pdc.PROTOCOL.settings_specs()) | set(pdc.PROTOCOL.choice_specs())

    assert 'prepare_protein' in kept, 'the route would drop it before the job was created'
    assert pdc.CHOICE_SPECS['prepare_protein'][1] == (True, False)


def test_the_run_records_the_choice_the_stage_reads(tmp_path):
    run = prepared(tmp_path, prepare_protein=True)

    assert settings_of(run)['prepare_protein'] is True
    assert json.loads((run / 'manifest.json').read_text())['settings']['prepare_protein'] is True


def test_a_posted_choice_reaches_the_job_the_panel_queues(tmp_path):
    """The route keeps only the keys an adapter advertises; a key it does not is dropped without an error.

    That is the defect the placement mode had (`pdc_placement_mode` was sent, dropped, and every run was built on the
    default), so the panel's own POST is what proves a reader who ticks this control gets the run they asked for.
    """
    from dashboard.app import create_app
    from dashboard.paths import Paths

    protein = tmp_path / 'prot.pdb'
    protein.write_text(PROTEIN_TEXT)
    app = create_app(Paths(workspace=tmp_path / 'ws'), {'TESTING': True, 'DISABLE_COORDINATOR': True})

    response = app.test_client().post('/', json={'molecule_id': 'DDM', 'run_type': 'pdc', 'method': 'bartender',
                                                'template': 'molecules/DDM/micelle_template.json',
                                                'protein': str(protein), 'pdc_seed': 20261014,
                                                'aggregation_number': 4, 'prepare_protein': True})

    assert response.status_code == 201, response.get_data(as_text=True)
    assert response.json['settings']['prepare_protein'] is True


def test_a_protein_free_run_cannot_ask_for_a_preparation_there_is_nothing_to_prepare(tmp_path):
    """A request that cannot be honoured is refused at the door, with the file's own reason -- as a chain is."""
    molecule_tree(tmp_path)
    (tmp_path / 'run').mkdir()

    with pytest.raises(ValueError, match='no protein'):
        pdc.prepare(tmp_path / 'run', template='molecules/DDM/micelle_template.json',
                    settings={'seed': 1, 'aggregation_number': 4, 'prepare_protein': True}, project_root=tmp_path)


# --- the skip path -----------------------------------------------------------------------------------------------

def test_a_run_that_does_not_ask_for_the_preparation_records_skipped_with_its_reason(tmp_path):
    run = prepared(tmp_path)

    result = run_stage(run)

    assert result.returncode == 4, (result.stdout, result.stderr)
    record = json.loads((stage_directory(run) / 'skip.json').read_text())
    assert record['skipped'] is True
    assert 'does not ask' in record['reason'], record['reason']
    assert not (stage_directory(run) / pdc_preparation.PREPARED_NAME).exists(), \
        'a skipped step writes no prepared structure'
    assert not (stage_directory(run) / pdc_preparation.RECORD_NAME).exists(), 'nothing owed, nothing written'


def test_a_run_with_no_protein_skips_the_step_and_says_what_it_has_nothing_to_do_with(tmp_path):
    """The adapter refuses the pair at the door, so this is the backstop: a settings file that says so anyway.

    Nothing is attempted and nothing is owed, which is the house contract's fourth outcome -- not a failure, and not
    a prepared structure built from a file that holds no coordinates. The stage is entered in process, because the
    executor's own prelude is what copies the run's protein in, and this case is a run whose protein is no protein.
    """
    run = prepared(tmp_path)
    settings = settings_of(run)
    directory = stage_directory(run)
    (directory / pdc_prepare.DECLARED_INPUT).write_text('; no protein: this is an empty-micelle build\n')
    settings['prepare_protein'] = True
    (stage_directory(run, SYSTEM) / pdc.SETTINGS_NAME).write_text(json.dumps(settings))

    code = pdc_prepare.main(['--stage', str(directory)])

    assert code == 4, code
    assert 'no protein' in json.loads((directory / 'skip.json').read_text())['reason']


# --- the refusal path ---------------------------------------------------------------------------------------------

def test_the_step_refuses_by_name_when_the_preparer_cannot_be_resolved(tmp_path, monkeypatch):
    run = prepared(tmp_path, prepare_protein=True)
    monkeypatch.setattr(pdc_preparation, 'resolve_tool', lambda: None)

    code = pdc_prepare.main(['--stage', str(stage_directory(run))])

    assert code == 2, 'a step the run asked for and the machine cannot run is a refusal, never a skip'
    record = json.loads((stage_directory(run) / pdc_preparation.RECORD_NAME).read_text())
    assert record['ok'] is False
    assert 'pdb2pqr' in record['reason'] and 'resolvable' in record['reason']
    assert not (stage_directory(run) / 'skip.json').exists()


def test_a_preparer_that_exits_non_zero_is_a_refusal_that_carries_its_own_log(tmp_path, monkeypatch):
    run = prepared(tmp_path, prepare_protein=True)
    monkeypatch.setattr(pdc_preparation, 'resolve_tool', lambda: '/usr/bin/pdb2pqr')
    monkeypatch.setattr(pdc_preparation.subprocess, 'run',
                        fake_pdb2pqr(returncode=1, write_output=False))

    code = pdc_prepare.main(['--stage', str(stage_directory(run))])

    assert code == 2
    record = json.loads((stage_directory(run) / pdc_preparation.RECORD_NAME).read_text())
    assert record['ok'] is False and '1' in record['reason']
    assert (stage_directory(run) / pdc_preparation.LOG_NAME).is_file(), 'the log is what a reader has to read'


# --- what the step runs -------------------------------------------------------------------------------------------

def test_the_command_asks_the_preparer_for_a_pdb_the_coarse_graining_can_read(tmp_path):
    command = pdc_preparation.command(Path('protein_input.pdb'), Path('protein_prepared.pdb'), Path('prepared.pqr'),
                                      executable='/usr/bin/pdb2pqr')

    assert command[0] == '/usr/bin/pdb2pqr'
    assert f'--ff={pdc_preparation.FORCE_FIELD}' in command, 'the rebuild and the protonation come from a force field'
    assert '--keep-chain' in command, 'a chain id is what a subunit selection is spelled with'
    assert command[command.index('--pdb-output') + 1] == 'protein_prepared.pdb'
    assert command[-2:] == ['protein_input.pdb', 'prepared.pqr'], \
        'the PQR is the tool\'s own output and nothing here consumes its charges'


def test_the_prepared_structure_is_martinized_and_the_input_it_was_built_from_is_the_runs_own(tmp_path, monkeypatch):
    """`protein_input.pdb` is the deposited file with its `HETATM` records dropped and the selection applied.

    The same rule the build applies before martinize2 (`pdc_import.filter_chains`): a ligand or a crystallisation
    additive is not a residue the preparer can place in a force field, and handing it one is how the CG step came to
    exit 1 with no topology at all.
    """
    run = prepared(tmp_path, prepare_protein=True)
    directory = stage_directory(run)
    (directory / 'protein.pdb').write_text(
        f'{MEMBRANE_REMARK}\n'
        'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n'
        'HETATM    2  C1  DUM A 999       1.000   0.000   0.000  1.00  0.00           C\n'
        'END\n')
    monkeypatch.setattr(pdc_preparation, 'resolve_tool', lambda: '/usr/bin/pdb2pqr')
    monkeypatch.setattr(pdc_preparation.subprocess, 'run', fake_pdb2pqr())

    assert pdc_prepare.main(['--stage', str(directory)]) == 0

    given = (directory / pdc_preparation.INPUT_NAME).read_text()
    assert 'DUM' not in given and 'ALA' in given, 'the preparer was handed the polymer and nothing else'
    assert (directory / pdc_preparation.PREPARED_NAME).is_file()


def test_the_prepared_structure_carries_the_files_own_membrane_statement(tmp_path, monkeypatch):
    """Without this the belt silently stops being a band in the membrane plane.

    A prepared structure is built by the tool from the coordinates, and the tool writes no `REMARK` records: measured
    on 4iar, `--pdb-output` holds 0 of the source's 161 header lines. The frame a build places in is read from the
    file martinize2 is handed, so the source's own statements are carried over -- the same rule
    `pdc_import.filter_chains` keeps them by.
    """
    run = prepared(tmp_path, prepare_protein=True)
    directory = stage_directory(run)
    (directory / 'protein.pdb').write_text(PROTEIN_TEXT)
    monkeypatch.setattr(pdc_preparation, 'resolve_tool', lambda: '/usr/bin/pdb2pqr')
    monkeypatch.setattr(pdc_preparation.subprocess, 'run', fake_pdb2pqr())

    assert pdc_prepare.main(['--stage', str(directory)]) == 0

    text = (directory / pdc_preparation.PREPARED_NAME).read_text()
    assert MEMBRANE_REMARK in text, 'the file its own membrane statement is the frame the belt is placed in'
    assert stated_half_thickness_nm(text) == 1.68
    assert 'ATOM' in text and 'CE  LYS' in text, 'and the atoms the preparer built are there with it'


def test_the_preparer_writes_where_it_was_asked_to_whatever_spelling_it_was_handed(tmp_path, monkeypatch):
    """A relative directory must not move the tool's own output, and PDB2PQR moves its log when it thinks it can.

    Measured: handed a relative `--pdb-output`, PDB2PQR builds its log path out of it, looks for `<dir>/<dir>/
    prepared.log`, and exits 1 before reading a single atom -- so the command this module builds names absolute
    paths, whatever the caller passed.
    """
    monkeypatch.chdir(tmp_path)
    molecule_tree(tmp_path)
    monkeypatch.setattr(pdc_preparation, 'resolve_tool', lambda: '/usr/bin/pdb2pqr')

    record = pdc_preparation.prepare(tmp_path / 'molecules/DDM/protein.pdb', Path('prepared'))

    assert record['ok'] is False, 'the stub tool wrote nothing, so this is the refusal path'
    outputs = [part for part in record['command'] if part.endswith(('.pdb', '.pqr'))]
    assert outputs and all(Path(part).is_absolute() for part in outputs), record['command']
    assert Path(record['command'][record['command'].index('--pdb-output') + 1]).parent == Path('prepared').resolve()
    assert (tmp_path / 'prepared' / pdc_preparation.LOG_NAME).is_file(), \
        'the tool was given a directory it can write its own log in'


def test_the_records_numbers_are_the_tools_own_log_lines(tmp_path):
    record = pdc_preparation.log_record(TOOL_LOG)

    assert record['residues_rebuilt'] == ['LYS A 1085', 'TRP A 345']
    assert record['heavy_atoms_added'] == 3
    assert record['tool_version'] == '3.7.1'
    assert record['gaps'] == ['ALA A 190 -> SER A 197']


def test_the_stage_record_carries_the_tool_the_version_its_command_and_its_cost(tmp_path, monkeypatch):
    run = prepared(tmp_path, prepare_protein=True)
    monkeypatch.setattr(pdc_preparation, 'resolve_tool', lambda: '/usr/bin/pdb2pqr')
    monkeypatch.setattr(pdc_preparation.subprocess, 'run', fake_pdb2pqr())

    assert pdc_prepare.main(['--stage', str(stage_directory(run))]) == 0

    record = json.loads((stage_directory(run) / pdc_preparation.RECORD_NAME).read_text())
    assert record['ok'] is True
    assert record['tool'] == 'pdb2pqr' and record['executable'] == '/usr/bin/pdb2pqr'
    assert record['tool_version'] == '3.7.1'
    assert record['force_field'] == pdc_preparation.FORCE_FIELD
    assert record['command'][0] == '/usr/bin/pdb2pqr'
    assert record['heavy_atoms_added'] == 2 and record['residues_rebuilt'] == ['LYS A 1085']
    assert record['atoms_before'] == 1 and record['atoms_after'] == 3
    assert record['hydrogens_added'] == 0, 'the tool added no hydrogen here, and the record says zero, not a guess'
    assert isinstance(record['seconds'], float) and record['seconds'] >= 0.0


# --- the structure is what the coarse-graining reads ---------------------------------------------------------------

def test_the_build_reads_the_prepared_structure_when_the_stage_left_one(tmp_path, monkeypatch):
    run = prepared(tmp_path, prepare_protein=True)
    directory = stage_directory(run)
    (directory / 'protein.pdb').write_text(PROTEIN_TEXT)
    monkeypatch.setattr(pdc_preparation, 'resolve_tool', lambda: '/usr/bin/pdb2pqr')
    monkeypatch.setattr(pdc_preparation.subprocess, 'run', fake_pdb2pqr())
    assert pdc_prepare.main(['--stage', str(directory)]) == 0

    stage = stage_directory(run, SYSTEM)
    # The CG step's own gate is the file its command names, so the structure it would have written is written here:
    # what is under test is the file it was *handed*, which the command names.
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb')
    captured = {}

    def fake_martinize(protein, out):
        captured['protein'] = Path(protein)
        return ['martinize2', '-f', str(protein), '-x', str(Path(out) / 'protein_cg.pdb'),
                '-o', str(Path(out) / 'protein.top')]

    monkeypatch.setattr(pdc_build.pdc_protein, 'martinize_command', fake_martinize)

    assert pdc_build.build(stage) == 3, 'the fixture template has one bead, so the build stops at centres-only'

    assert captured['protein'] == directory / pdc_preparation.PREPARED_NAME
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert report['protein_prepared'] == str(directory / pdc_preparation.PREPARED_NAME)
    assert report['membrane_frame']['half_thickness_nm'] == 1.68, \
        'the prepared structure carried the statement, so the belt keeps the frame'


def test_the_build_finds_the_prepared_structure_through_the_spelling_a_stage_script_uses(tmp_path, monkeypatch):
    """`--stage .` is what the generated script passes, and `Path('.').parent` is not the run.

    The bug this pins cost a real run: the prepare stage wrote its structure beside the system stage's directory, the
    build was handed `.` by its own script, and `.parent` resolved to the stage's own directory -- so the sibling
    lookup found nothing and the build coarse-grained the deposited file the step existed to replace. The stage
    script is what a run runs, so the entry point is what is exercised here, from inside the stage directory.
    """
    run = prepared(tmp_path, prepare_protein=True)
    directory = stage_directory(run)
    (directory / 'protein.pdb').write_text(PROTEIN_TEXT)
    monkeypatch.setattr(pdc_preparation, 'resolve_tool', lambda: '/usr/bin/pdb2pqr')
    monkeypatch.setattr(pdc_preparation.subprocess, 'run', fake_pdb2pqr())
    assert pdc_prepare.main(['--stage', str(directory)]) == 0

    stage = stage_directory(run, SYSTEM)
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb')
    captured = {}

    def fake_martinize(protein, out):
        captured['protein'] = Path(protein)
        return ['martinize2', '-f', str(protein), '-x', str(Path(out) / 'protein_cg.pdb'),
                '-o', str(Path(out) / 'protein.top')]

    monkeypatch.setattr(pdc_build.pdc_protein, 'martinize_command', fake_martinize)
    monkeypatch.chdir(stage)

    assert pdc_build.main(['--stage', '.']) == 3

    assert captured['protein'] == stage_directory(run) / pdc_preparation.PREPARED_NAME
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert report['protein_prepared'] == str(stage_directory(run) / pdc_preparation.PREPARED_NAME)


def test_the_build_reads_the_deposited_file_when_the_preparation_did_not_run(tmp_path, monkeypatch):
    run = prepared(tmp_path)
    stage = stage_directory(run, SYSTEM)
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb')
    captured = {}

    def fake_martinize(protein, out):
        captured['protein'] = Path(protein)
        return ['martinize2', '-f', str(protein), '-x', str(Path(out) / 'protein_cg.pdb'),
                '-o', str(Path(out) / 'protein.top')]

    monkeypatch.setattr(pdc_build.pdc_protein, 'martinize_command', fake_martinize)

    pdc_build.build(stage)

    assert captured['protein'] == tmp_path / 'molecules/DDM/protein.pdb', \
        'the run\'s own file, resolved from the settings, is what the coarse-graining reads'
    assert json.loads((stage / pdc.REPORT_NAME).read_text())['protein_prepared'] is None


def test_the_run_manifest_records_the_preparer_and_never_substitutes_one_is_not_there(tmp_path, monkeypatch):
    """A tool that is not resolvable is recorded as unresolved -- the declaration rule, not a fallback."""
    monkeypatch.setattr(tools, 'tool_path', lambda name, *args, **kwargs: None if name == 'pdb2pqr' else '/bin/true')
    monkeypatch.setattr('dashboard.execution.adapters.pdc.tools.tool_path', tools.tool_path)
    run = prepared(tmp_path, prepare_protein=True)

    recorded = json.loads((run / 'manifest.json').read_text())['tools']

    assert recorded['pdb2pqr']['ready'] is False
    assert recorded['pdb2pqr']['path'] == 'pdb2pqr'
    assert recorded['gmx']['path'] == '/bin/true', 'and the tools the run always needs are untouched'


def test_the_readiness_checks_name_the_preparer_without_blocking_a_run_that_does_not_ask_for_it(tmp_path, monkeypatch):
    root = molecule_tree(tmp_path)
    monkeypatch.setattr(tools, 'tool_path', lambda name, *args, **kwargs: None if name == 'pdb2pqr' else '/bin/true')
    monkeypatch.setattr(pdc.tools, 'tool_path', tools.tool_path)
    monkeypatch.setattr('dashboard.execution.environment.probe_tool', lambda executable: (True, 'found'))

    answer = pdc.readiness(protein='molecules/DDM/protein.pdb', template='molecules/DDM/micelle_template.json',
                           project_root=root)

    check = next(entry for entry in answer['checks'] if entry['label'] == 'pdb2pqr')
    assert check['ready'] is False and 'preparation' in check['detail']
    assert not any('pdb2pqr' in blocker for blocker in answer['blockers']), \
        'the step is optional: a run that does not ask for it is not blocked by the tool it would need'


# --- the preview, which is where the reader meets the refusal -----------------------------------------------------

def preview_repo(tmp_path, **kwargs):
    """The preview over the fixture tree, with its cache in the test's own directory."""
    from dashboard.execution import pdc_preview

    arguments = {'project_root': tmp_path, 'cache_root': tmp_path / 'cache', 'seed': 20261014,
                 'aggregation_number': 4, 'template': str(tmp_path / 'molecules/DDM/micelle_template.json'),
                 'protein': str(tmp_path / 'molecules/DDM/protein.pdb')}
    arguments.update(kwargs)
    return pdc_preview.preview(**arguments)


def test_the_preview_runs_the_preparer_only_when_the_form_asks_for_it(tmp_path, monkeypatch):
    """The preview and the run must make the same choice: the picture is of the file the run would coarse-grain.

    Both halves of the build are substituted the way the preview's own tests do it -- the preparer at
    `pdc_preparation.prepare`, the coarse-graining at `subprocess` -- and what is measured is which file each was
    handed, because that is the whole claim: the prepared structure is what martinize2 reads.
    """
    from dashboard.execution import pdc_preview

    molecule_tree(tmp_path)
    martinize_calls = []

    def fake_martinize(command, **kwargs):
        martinize_calls.append([str(part) for part in command])
        structure = Path(command[command.index('-x') + 1])
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(cg_pdb([(1, 'PRO', 'B01', (0.0, 0.0, 0.0))]))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(pdc_build.subprocess, 'run', fake_martinize)
    prepared_calls = []

    def fake_prepare(source, directory, **kwargs):
        prepared_calls.append(Path(source))
        target = Path(directory) / pdc_preparation.PREPARED_NAME
        target.write_text(PROTEIN_TEXT)
        return {'ok': True, 'path': str(target), 'tool': 'pdb2pqr', 'executable': '/usr/bin/pdb2pqr',
                'tool_version': '3.7.1', 'force_field': 'CHARMM', 'command': ['pdb2pqr'],
                'seconds': 1.5, 'heavy_atoms_added': 2, 'residues_rebuilt': ['LYS A 1085'],
                'atoms_before': 1, 'atoms_after': 3, 'hydrogens_added': 0,
                'log': str(Path(directory) / pdc_preparation.LOG_NAME)}
    monkeypatch.setattr(pdc_preview.pdc_preparation, 'prepare', fake_prepare)

    off = preview_repo(tmp_path)

    assert off['valid'], off['reasons']
    assert not prepared_calls, 'the form did not ask for it, so the preparer was not run'
    assert off['basis']['prepare_protein'] is False and off['cost']['prepare_seconds'] == 0.0

    on = preview_repo(tmp_path, prepare_protein=True)

    assert on['valid'], on['reasons']
    assert [str(path) for path in prepared_calls] == [str(tmp_path / 'molecules/DDM/protein.pdb')], \
        'the preparer is handed the polymer the build would coarse-grain, and only when it is asked for'
    assert on['basis']['prepare_protein'] is True
    assert on['cost']['prepare_seconds'] == 1.5
    assert on['basis']['prepare']['residues_rebuilt'] == ['LYS A 1085']
    assert on['basis']['prepare']['tool_version'] == '3.7.1'
    # The file each coarse-graining was handed: the run's own polymer without the step, the prepared one with it.
    assert [Path(call[call.index('-f') + 1]).name for call in martinize_calls] == ['protein.pdb',
                                                                                  pdc_preparation.PREPARED_NAME]
    prepared_at = Path(martinize_calls[1][martinize_calls[1].index('-f') + 1])
    assert prepared_at.parent.name == on['cost']['cg_key'], "the prepared structure lives in the derive's own entry"
    assert Path(martinize_calls[0][martinize_calls[0].index('-f') + 1]).parent.name != on['cost']['cg_key'], \
        'the two are different cache entries: one derives from the file as deposited and one from the rebuilt one'


def test_the_preview_runs_no_preparer_twice_for_one_entry(tmp_path, monkeypatch):
    """A cached entry re-derives without paying the step again -- it is the expensive half's own rule, extended."""
    from dashboard.execution import pdc_preview

    molecule_tree(tmp_path)
    calls = []

    def fake_martinize(command, **kwargs):
        structure = Path(command[command.index('-x') + 1])
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(cg_pdb([(1, 'PRO', 'B01', (0.0, 0.0, 0.0))]))
        return subprocess.CompletedProcess(command, 0)

    def fake_prepare(source, directory, **kwargs):
        calls.append(Path(source))
        target = Path(directory) / pdc_preparation.PREPARED_NAME
        target.write_text(PROTEIN_TEXT)
        return {'ok': True, 'path': str(target), 'tool': 'pdb2pqr', 'executable': '/usr/bin/pdb2pqr',
                'tool_version': '3.7.1', 'force_field': 'CHARMM', 'command': [], 'seconds': 1.5,
                'heavy_atoms_added': 0, 'residues_rebuilt': [], 'atoms_before': 1, 'atoms_after': 1,
                'hydrogens_added': 0, 'log': ''}

    monkeypatch.setattr(pdc_build.subprocess, 'run', fake_martinize)
    monkeypatch.setattr(pdc_preview.pdc_preparation, 'prepare', fake_prepare)

    first = preview_repo(tmp_path, prepare_protein=True)
    second = preview_repo(tmp_path, prepare_protein=True, aggregation_number=6)

    assert first['valid'] and second['valid'], (first['reasons'], second['reasons'])
    assert len(calls) == 1, 'the second derive read the entry the first one left'
    assert second['basis']['prepare_protein'] is True
    assert second['cost']['prepare_seconds'] == 0.0, 'and it paid nothing for a step that had already run'


def test_a_prepared_entry_and_an_unprepared_one_are_different_cache_entries(tmp_path):
    from dashboard.execution import pdc_preview

    protein = tmp_path / 'protein.pdb'
    protein.write_text(PROTEIN_TEXT)

    plain = pdc_preview.cache_key(protein, None, '/usr/bin/martinize2')
    prepared_key = pdc_preview.cache_key(protein, None, '/usr/bin/martinize2', prepare=True,
                                        prepare_executable='/usr/bin/pdb2pqr')

    other = pdc_preview.cache_key(protein, None, '/usr/bin/martinize2', prepare=True,
                                  prepare_executable='/usr/bin/pdb2pqr-3.6')
    assert plain != prepared_key, 'an unprepared frame must never be read as one the preparer had a hand in'
    assert prepared_key != other, 'a different preparer builds different atoms, so it is a different entry'


def test_a_preparation_the_tool_refuses_is_a_refusal_that_names_that_step(tmp_path, monkeypatch):
    from dashboard.execution import pdc_preview

    molecule_tree(tmp_path)

    def refuses(source, directory, **kwargs):
        return {'ok': False, 'reason': 'pdb2pqr is not resolvable on this machine', 'seconds': 0.0}

    monkeypatch.setattr(pdc_preview.pdc_preparation, 'prepare', refuses)

    answer = preview_repo(tmp_path, prepare_protein=True)

    assert answer['valid'] is False and answer['pdb'] is None
    assert answer['step'] == 'protein preparation'
    assert answer['reasons'] == ['pdb2pqr is not resolvable on this machine']


# --- the preparer actually rebuilds (the real tool, where it is here) ----------------------------------------------

def real_tool():
    return tools.tool_path(pdc_preparation.TOOL)


#: Seven residues of the deposited 4iar chain A, residues 1040-1046, as the file writes them: `(residue number,
#: residue name, atom name, x, y, z)`. Frozen here rather than read from the workspace, which is where the file a
#: user downloaded lives and is not a test's input. LYS 1042 carries its backbone and CB only -- the deposit omits
#: CG, CD, CE and NZ -- which is the defect this step exists for, and the geometry is real, which is what the
#: preparer's own debumping needs to walk a rebuilt side chain.
DEPOSITED_EXCERPT = (
    ('1040', 'ALA', 'N', -7.282, -10.148, -39.551), ('1040', 'ALA', 'CA', -6.019, -10.167, -38.801),
    ('1040', 'ALA', 'C', -5.842, -8.845, -38.059), ('1040', 'ALA', 'O', -5.449, -8.840, -36.889),
    ('1040', 'ALA', 'CB', -4.847, -10.411, -39.742), ('1041', 'GLN', 'N', -6.226, -7.732, -38.739),
    ('1041', 'GLN', 'CA', -6.202, -6.356, -38.241), ('1041', 'GLN', 'C', -7.107, -6.174, -37.002),
    ('1041', 'GLN', 'O', -6.759, -5.386, -36.142), ('1041', 'GLN', 'CB', -6.625, -5.378, -39.356),
    ('1041', 'GLN', 'CG', -6.147, -3.937, -39.141), ('1041', 'GLN', 'CD', -6.543, -3.014, -40.271),
    ('1041', 'GLN', 'OE1', -7.718, -2.684, -40.468), ('1041', 'GLN', 'NE2', -5.559, -2.540, -41.018),
    ('1042', 'LYS', 'N', -8.263, -6.855, -36.924), ('1042', 'LYS', 'CA', -9.158, -6.737, -35.764),
    ('1042', 'LYS', 'C', -8.751, -7.724, -34.657), ('1042', 'LYS', 'O', -8.949, -7.431, -33.473),
    ('1042', 'LYS', 'CB', -10.627, -6.959, -36.154), ('1043', 'ALA', 'N', -8.177, -8.883, -35.048),
    ('1043', 'ALA', 'CA', -7.739, -9.947, -34.147), ('1043', 'ALA', 'C', -6.564, -9.513, -33.286),
    ('1043', 'ALA', 'O', -6.542, -9.858, -32.112), ('1043', 'ALA', 'CB', -7.365, -11.189, -34.944),
    ('1044', 'THR', 'N', -5.597, -8.755, -33.857), ('1044', 'THR', 'CA', -4.382, -8.286, -33.176),
    ('1044', 'THR', 'C', -4.760, -7.512, -31.873), ('1044', 'THR', 'O', -5.408, -6.458, -31.941),
    ('1044', 'THR', 'CB', -3.428, -7.508, -34.132), ('1044', 'THR', 'OG1', -2.365, -6.925, -33.381),
    ('1044', 'THR', 'CG2', -4.111, -6.422, -34.936), ('1045', 'PRO', 'N', -4.417, -8.084, -30.683),
    ('1045', 'PRO', 'CA', -4.787, -7.424, -29.416), ('1045', 'PRO', 'C', -4.062, -6.080, -29.197),
    ('1045', 'PRO', 'O', -3.024, -5.827, -29.836), ('1045', 'PRO', 'CB', -4.407, -8.461, -28.342),
    ('1045', 'PRO', 'CG', -3.367, -9.295, -28.951), ('1045', 'PRO', 'CD', -3.690, -9.349, -30.432),
    ('1046', 'PRO', 'N', -4.606, -5.193, -28.310), ('1046', 'PRO', 'CA', -3.940, -3.904, -28.065),
    ('1046', 'PRO', 'C', -2.559, -4.067, -27.434), ('1046', 'PRO', 'O', -2.316, -4.987, -26.649),
    ('1046', 'PRO', 'CB', -4.897, -3.179, -27.104), ('1046', 'PRO', 'CG', -6.189, -3.902, -27.180),
    ('1046', 'PRO', 'CD', -5.829, -5.320, -27.484),
)


def deposited_excerpt() -> str:
    """The excerpt above as PDB text, in the columns the preparer and `pdc_import` both read."""
    lines = []
    for serial, (number, residue, name, x, y, z) in enumerate(DEPOSITED_EXCERPT, 1):
        element = {'N': 'N', 'O': 'O'}.get(name, 'C')
        lines.append(f'ATOM  {serial:5d} {name:^4s} {residue:>3s} A{number:>4s}    '
                     f'{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element:>2s}')
    return '\n'.join(lines) + '\nEND\n'


@pytest.mark.skipif(real_tool() is None, reason='pdb2pqr is not resolvable in this checkout')
def test_the_real_preparer_rebuilds_a_deposited_side_chain_and_protonates_it(tmp_path):
    """The whole claim of the task, run rather than described: a deposited side chain the file omits, rebuilt.

    "Do not invent a rebuild of your own if a tested implementation exists" is only a fact if the implementation is
    exercised, so PDB2PQR is run on a fixture whose own defect is the one 4iar's file has: a lysine with no
    side-chain atoms past CB. What it built is read out of the structure it wrote, and the count is its own log's.
    """
    source = tmp_path / 'incomplete.pdb'
    source.write_text(deposited_excerpt())

    record = pdc_preparation.prepare(source, tmp_path / 'prepared')

    assert record['ok'] is True, record.get('reason')
    text = Path(record['path']).read_text()
    for atom in (' CG ', ' CD ', ' CE ', ' NZ '):
        assert atom in text, f'LYS 1042 is still missing {atom.strip()}'
    assert record['residues_rebuilt'] == ['LYS A 1042', 'PRO A 1046'], record
    # CG, CD, CE and NZ for the lysine, and the C-terminal OXT no deposited file carries.
    assert record['heavy_atoms_added'] == 5, record
    assert record['tool_version'].startswith('3.'), record
    assert record['hydrogens_added'] > 0, 'protonation is the other half of this step'
    assert record['atoms_after'] - record['atoms_before'] == record['heavy_atoms_added'] \
        + record['hydrogens_added'], 'the record adds up'
