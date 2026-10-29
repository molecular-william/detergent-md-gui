"""The CG protein step: what martinize2 is asked for, what the stage reads back, and the secondary structure behind it.

Three things this step had wrong, each measured on the tool before it was changed:

* it read `*.gro` out of `cg/`, while the command is `-x <out>/protein_cg.pdb` and martinize2 writes no `.gro` at all
  -- so the step raised on "the CG protein step left 0 structures" however well the tool had run. What is read now
  is the file the command itself names, so the two cannot drift;
* the command carried no secondary-structure flag, so martinize2 logged "topology will be created without secondary
  structure information", counted it as a warning and exited 2 with *nothing* written. The copy now asks for the
  assignment the way the Martini 3 tutorial's own martinize2 invocation does -- `-dssp`, bare, which vermouth answers
  with mdtraj (`AnnotateDSSP(executable=None)` binds `run_mdtraj`) -- and `-maxwarn 1` is the tool's own documented
  room for its one warning when no assignment can be made at all;
* martinize2 writes the molecule's own `.itp` into its *working directory* (`molecule_0.itp`, which the `.top` it
  writes includes by that name), so the step runs it inside `cg/` -- run anywhere else, the topology the next step
  needs lands beside the stage instead.

`-dssp` is one of two mutually exclusive flags, and the fallback is the other one: `-ss <letters>`, with the letters
assigned here by MDAnalysis (`MDAnalysis.analysis.dssp`), which is what every earlier run used and what a virtualenv
without mdtraj still gets. Which of the two was used is recorded in the report, so a reader never has to guess.

The fixtures build their own molecule tree and their own protein; nothing here reads the developer's workspace, and
the tool itself is stubbed, because what is tested is the stage's own command and read-back. The two assignment
sources are *not* stubbed where a test is about which one answers: mdtraj and MDAnalysis are both declared
dependencies of this repository, and a test that asserted a route without them would assert nothing about it.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from dashboard.execution.adapters import pdc
from dashboard.execution.scripts import pdc_build

from tests.dashboard.pdc_fixtures import prepared_run, system_stage

TEMPLATE = {
    'name': 'DDM', 'residue': 'DDM', 'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp', 'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'},
                                                   {'name': 'HEAD', 'type': 'SN6', 'role': 'head'}],
}


def peptide(residues: int = 6) -> str:
    """A peptide with an ideal backbone, so a secondary-structure assignment has something to read.

    Six residues is the shortest fixture both sources answer: MDAnalysis' DSSP implementation raises below five
    residues (measured), and mdtraj reads every length and calls a straight backbone coil.
    """
    records, serial = [], 0
    for index in range(1, residues + 1):
        z = 1.5 * index
        for name, xyz, element in (('N', (0.0, 0.0, z), 'N'), ('CA', (1.46, 0.0, z + 0.5), 'C'),
                                   ('C', (2.0, 1.4, z + 1.0), 'C'), ('O', (2.9, 1.5, z + 1.2), 'O'),
                                   ('CB', (1.9, -1.2, z + 0.2), 'C')):
            serial += 1
            records.append(f'ATOM  {serial:5d} {name:^4s} ALA A{index:4d}    '
                           f'{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00  0.00          {element:>2s}')
    return '\n'.join(records) + '\nEND\n'


def pdb_text(atoms) -> str:
    """A CG structure as martinize2 writes one: `ATOM` records, one bead per line, Angstroms.

    The positions handed in are nanometres, which is what the stage's builders work in, so they are scaled here the
    way the tool would write them -- and the reader scales them back.
    """
    records = [f'ATOM  {index:5d} {name:^4s} {residue:>3s} A{residue_id:4d}    '
               f'{xyz[0] * 10.0:8.3f}{xyz[1] * 10.0:8.3f}{xyz[2] * 10.0:8.3f}  1.00  0.00'
               for index, (residue_id, residue, name, xyz) in enumerate(atoms, 1)]
    return '\n'.join(records) + '\nEND\n'


def prepared(tmp_path: Path, protein: str | None = None):
    """A run whose protein is the one this test is about: the peptide builder's output unless one is passed."""
    run = prepared_run(tmp_path, settings={'seed': 20261014, 'aggregation_number': 4},
                       protein_text=protein if protein is not None else peptide())
    return run, system_stage(run)


def cg_directory(stage: Path) -> Path:
    return stage / pdc_build.CG_DIRECTORY


def cg_structure(stage: Path) -> Path:
    """Where the step's own command puts the CG structure, so a fixture writes where the stage reads."""
    command = pdc_build.pdc_protein.martinize_command(stage / 'protein.pdb', cg_directory(stage))
    return Path(command[command.index('-x') + 1])


THREE_BEADS = [(1, 'PRO', 'B01', (0.0, 0.0, 0.0)), (1, 'PRO', 'B02', (1.0, 0.0, 0.0)),
               (1, 'PRO', 'B03', (0.0, 1.0, 0.0))]


def stubbed_run(calls, beads=3):
    """A martinize2 that writes exactly what its command names, and records how it was called."""
    def run(command, **kwargs):
        calls.append({'command': list(command), **kwargs})
        structure = Path(command[command.index('-x') + 1])
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(pdb_text([(1, 'PRO', f'B{index:02d}', (float(index), 0.0, 0.0))
                                       for index in range(1, beads + 1)]))
        return subprocess.CompletedProcess(command, 0)
    return run


def report(stage: Path) -> dict:
    return json.loads((stage / pdc.REPORT_NAME).read_text())


# --- what is read back ------------------------------------------------------------------------------------------

def test_the_cg_step_reads_the_structure_its_own_command_names(tmp_path, monkeypatch):
    """`-x` is the tool's only structure output, and it is a PDB: reading a name written down here could drift."""
    _, stage = prepared(tmp_path)
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_run(calls))

    assert pdc_build.build(stage) == 3

    assert report(stage)['protein_beads'] == 3, 'the beads are the ones the tool wrote where the command said'
    assert Path(calls[0]['command'][calls[0]['command'].index('-x') + 1]).is_file()


def test_a_gro_in_the_directory_is_not_what_the_cg_step_reads(tmp_path):
    """The step used to glob `*.gro`, a name martinize2 never writes -- and the fixture tests wrote it too."""
    _, stage = prepared(tmp_path)
    cg_directory(stage).mkdir(exist_ok=True)
    (cg_directory(stage) / 'protein_CG.gro').write_text(
        'protein\n5\n' + ''.join(f'{1:5d}{"PRO":<5}{f"B{index:02d}":>5}{index:5d}'
                                 f'{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}\n' for index in range(1, 6))
        + '   8.00000   8.00000   8.00000\n')
    cg_structure(stage).write_text(pdb_text(THREE_BEADS))

    assert pdc_build.build(stage) == 3

    assert report(stage)['protein_beads'] == 3, 'the five beads of the .gro are not this step\'s protein'


def test_a_structure_the_tool_never_writes_is_not_taken_for_a_built_step(tmp_path, monkeypatch):
    """The gate on running martinize2 again is the file it writes, not any structure that happens to be there."""
    _, stage = prepared(tmp_path)
    cg_directory(stage).mkdir(exist_ok=True)
    (cg_directory(stage) / 'protein_CG.gro').write_text('a structure this tool never wrote\n')
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_run(calls))

    pdc_build.build(stage)

    assert calls, 'the step read the .gro as if martinize2 had produced it'


def test_a_step_that_was_built_before_does_not_run_martinize2_again(tmp_path, monkeypatch):
    _, stage = prepared(tmp_path)
    cg_directory(stage).mkdir(exist_ok=True)
    cg_structure(stage).write_text(pdb_text(THREE_BEADS))
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_run(calls))

    assert pdc_build.build(stage) == 3

    recorded = report(stage)
    assert calls == [] and recorded['cg_command'] is None
    assert recorded['protein_beads'] == 3
    assert recorded['secondary_structure']['source'] is None, 'nothing was assigned: the tool was not run'


# --- the command -----------------------------------------------------------------------------------------------

def test_martinize2_runs_in_the_directory_it_writes_its_own_topology_into(tmp_path, monkeypatch):
    """Its molecule `.itp` is written beside itself, so the working directory is where the topology has to land."""
    _, stage = prepared(tmp_path)
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_run(calls))

    pdc_build.build(stage)

    command, cwd = calls[0]['command'], calls[0]['cwd']
    assert Path(cwd) == cg_directory(stage)
    for flag in ('-x', '-o'):
        assert Path(command[command.index(flag) + 1]).parent == Path(cwd), \
            f'{flag} writes outside the directory the tool is run in'


def test_the_command_asks_martinize2_to_assign_the_structure_itself(tmp_path, monkeypatch):
    """`-dssp` bare is the documented route: vermouth answers it with mdtraj, so the tool assigns the structure.

    The flag is asserted *bare* -- nothing follows it -- because an argument would make vermouth run an external DSSP
    binary instead, and vermouth trusts only versions 2.2.1 and 3.0.0 of one (`SUPPORTED_DSSP_VERSIONS`), which is
    not what this box carries.
    """
    _, stage = prepared(tmp_path)
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_run(calls))

    pdc_build.build(stage)

    command = calls[0]['command']
    assert command[-1] == '-dssp', 'the bare flag is what makes vermouth use mdtraj'
    assert '-ss' not in command, 'the tool declares the two flags mutually exclusive'
    assert command[command.index('-maxwarn') + 1] == '1'


def test_martinize2_is_handed_the_letters_only_when_mdtraj_cannot_assign_them(tmp_path, monkeypatch):
    """A virtualenv without mdtraj still builds, with the source every earlier run used: MDAnalysis' letters."""
    _, stage = prepared(tmp_path)
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_run(calls))
    monkeypatch.setattr(pdc_build, '_mdtraj_letters', lambda structure: (None, 'mdtraj is not importable: nope'))

    pdc_build.build(stage)

    command = calls[0]['command']
    assert '-dssp' not in command, 'the route with no library behind it is not asked for'
    sequence = command[command.index('-ss') + 1]
    assert len(sequence) == 6, 'one letter per residue of the protein it was given'
    assert set(sequence) <= set('HEC'), 'the letters martinize2 takes, and no others'

    recorded = report(stage)['secondary_structure']
    assert recorded['source'] == pdc_build.SS_FALLBACK_SOURCE and recorded['route'] == '-ss'


def test_a_structure_neither_source_can_assign_still_builds_and_names_both_reasons(tmp_path, monkeypatch):
    """No secondary structure is martinize2's own documented case (`-maxwarn`), so it is recorded, not invented."""
    _, stage = prepared(tmp_path)
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_run(calls))
    monkeypatch.setattr(pdc_build, '_mdtraj_letters', lambda structure: (None, 'mdtraj says no'))
    monkeypatch.setattr(pdc_build, '_mdanalysis_letters', lambda structure: (None, 'MDAnalysis says no'))

    assert pdc_build.build(stage) == 3

    command = calls[0]['command']
    assert '-dssp' not in command and '-ss' not in command, 'a flag with no assignment behind it is not asked for'
    assert command[command.index('-maxwarn') + 1] == '1'

    recorded = report(stage)['secondary_structure']
    assert recorded['source'] is None and recorded['route'] is None
    assert 'mdtraj says no' in recorded['detail'] and 'MDAnalysis says no' in recorded['detail']


def test_the_command_handed_to_martinize2_names_absolute_paths(tmp_path, monkeypatch):
    """It is run from `cg/`, so a stage-relative path would be looked for *inside* `cg/` and not found.

    Measured on the real tool: run from `cg/` with `-f run/1_system/protein_selected.pdb`, martinize2 stopped at
    `FileNotFoundError: 'run/1_system/protein_selected.pdb'` and wrote nothing.
    """
    monkeypatch.chdir(tmp_path)
    _, stage = prepared(tmp_path)
    relative = stage.relative_to(tmp_path)
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_run(calls))

    pdc_build.build(relative)

    command = calls[0]['command']
    for flag in ('-f', '-x', '-o'):
        assert Path(command[command.index(flag) + 1]).is_absolute(), f'{flag} is not a file name cg/ can resolve'


def test_a_ligand_in_the_protein_chain_is_dropped_and_the_report_names_it(tmp_path, monkeypatch):
    """1AT9's retinal rides in the protein's own chain; without this the tool deletes the whole molecule."""
    ligand = ('ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n'
              'HETATM    2  C1  RET A 249A      0.500   0.000   0.000  1.00 15.00           C\n')
    _, stage = prepared(tmp_path, protein=ligand)
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_run(calls))

    pdc_build.build(stage)

    recorded = report(stage)
    assert recorded['protein_dropped_residues'] == ['RET']
    assert recorded['protein_input'] == pdc_build.SELECTED_PROTEIN, \
        'the file martinize2 reads is the filtered one, not the run\'s own protein.pdb'
    handed = Path(calls[0]['command'][calls[0]['command'].index('-f') + 1])
    assert 'HETATM' not in handed.read_text(), 'the ligand never reaches martinize2'


def test_a_command_that_names_no_structure_output_is_refused(tmp_path):
    """The file to read is taken from the command, so a command without one is an error and not a guess."""
    with pytest.raises(SystemExit, match='-x'):
        pdc_build._output_path(['true'], '-x')


# --- the assignment itself -------------------------------------------------------------------------------------

def test_the_three_state_assignment_becomes_the_letters_martinize2_takes():
    """MDAnalysis assigns helix/extended/unordered; martinize2 takes DSSP letters, where unordered is `C`."""
    assert pdc_build.ss_sequence(['H', 'E', '-', '-', 'H']) == 'HECCH'


def test_a_letter_martinize2_does_not_take_is_refused_rather_than_translated():
    assert pdc_build.ss_sequence(['H', 'X']) is None
    assert pdc_build.ss_sequence([]) is None


def test_the_assignment_names_the_source_and_the_flag_it_is_wired_with(tmp_path):
    """The report says which library assigned and which flag martinize2 was handed, so a reader need not guess."""
    path = tmp_path / 'protein.pdb'
    path.write_text(peptide())

    record = pdc_build.secondary_structure(path)

    assert record['source'] == pdc_build.SS_SOURCE and record['route'] == '-dssp'
    assert record['residues'] == 6 and len(record['letters']) == 6
    assert record['helix'] + record['extended'] + record['coil'] == 6


def test_the_recorded_letters_are_the_assignment_the_source_made(tmp_path):
    """The record is auditable: its letters are the assignment itself, not a summary of it."""
    path = tmp_path / 'protein.pdb'
    path.write_text(peptide())

    letters, reason = pdc_build._mdtraj_letters(path)
    record = pdc_build.secondary_structure(path)

    assert reason is None and record['letters'] == ''.join(letters)


def test_the_three_classes_are_martinis_own_reading_of_the_letters():
    """`H G I` are all helices to martinize2 (vermouth's `SS_CG`), `E B` both extended, and the rest is coil."""
    assert pdc_build.martini_classes(['H', 'G', 'I', 'E', 'B', 'T', 'S', 'C']) == \
        {'helix': 3, 'extended': 2, 'coil': 3}


def test_the_secondary_structure_the_run_used_reaches_the_report(tmp_path, monkeypatch):
    _, stage = prepared(tmp_path)
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_run([]))

    pdc_build.build(stage)

    recorded = report(stage)['secondary_structure']
    assert recorded['source'] == pdc_build.SS_SOURCE and recorded['residues'] == 6
    assert recorded['coil'] == 6, 'the fixture is a straight peptide'


def test_the_report_carries_the_whole_command_the_stage_ran(tmp_path, monkeypatch):
    _, stage = prepared(tmp_path)
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_run(calls))

    pdc_build.build(stage)

    assert report(stage)['cg_command'] == calls[0]['command']
