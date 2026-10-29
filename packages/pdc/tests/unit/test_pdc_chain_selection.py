"""Choosing which subunits of an assembly a protein-detergent run simulates.

A deposited OPM entry can be an assembly -- 1AT9 is a trimer -- and the estimate and the build took the whole file.
The plan (T9) makes the selection a setting of the run: the panel offers the entry's chains, the run records
`protein_chains`, the selection is validated against the file, and the build prepares the protein from the chosen
chains only. That last step is what makes a trimer runnable as a monomer.

These tests build their own molecule tree and their own multi-chain protein; nothing here reads the developer's
workspace, and the build is exercised without martinize2 (the CG structure it would produce is written in its place).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from detergent_pdc.execution.adapters import pdc, pdc_import
from detergent_pdc.execution.scripts import pdc_build

from tests.harness.pdc_fixtures import molecule_tree, prepared_run, settings_of, system_stage

TEMPLATE = {
    'name': 'DDM', 'residue': 'DDM', 'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp', 'beads': [{'name': 'DDM', 'type': 'registered-template'}],
}
# A two-subunit protein: the chains the selection is offered and validated against.
PROTEIN_TEXT = ('ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n'
                'ATOM      2  CA  LEU B   1       1.000   0.000   0.000  1.00  0.00           C\n'
                'END\n')


def prepared(tmp_path: Path, settings: dict | None = None):
    # The protein this file is about states its own chains; the construction is the shared one.
    return prepared_run(tmp_path, settings=settings, protein_text=PROTEIN_TEXT)


def stage_directory(run: Path) -> Path:
    return system_stage(run)


def gro_text(atoms, box=(8.0, 8.0, 8.0)) -> str:
    lines = ['system', str(len(atoms))]
    lines += [f'{1:5d}{residue:<5}{name:>5}{index:5d}{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}'
              for index, (residue, name, xyz) in enumerate(atoms, 1)]
    lines.append(''.join(f'{value:10.5f}' for value in box))
    return '\n'.join(lines) + '\n'


def write_cg_pdb(path: Path, atoms) -> Path:
    """The CG structure as martinize2 writes it (`-x`): `ATOM` records in Angstroms, read back by the stage."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'ATOM  {index:5d} {name:^4s} {residue:>3s} A{residue_id:4d}    '
             f'{xyz[0] * 10.0:8.3f}{xyz[1] * 10.0:8.3f}{xyz[2] * 10.0:8.3f}  1.00  0.00'
             for index, (residue_id, residue, name, xyz) in enumerate(atoms, 1)]
    path.write_text('\n'.join(lines) + '\nEND\n')
    return path


# --- the setting the run carries ---------------------------------------------------------------------------------

def test_the_run_carries_the_chain_selection_as_a_setting(tmp_path):
    run = prepared(tmp_path, {'protein_chains': ['A']})

    assert settings_of(run)['protein_chains'] == ['A']
    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['settings']['protein_chains'] == ['A'], 'the run records the selection it was built with'


def test_the_selection_defaults_to_every_chain_so_an_existing_caller_is_unaffected(tmp_path):
    run = prepared(tmp_path)

    assert settings_of(run)['protein_chains'] is None, 'no selection means the whole file, as before'


def test_a_chain_the_protein_does_not_have_is_refused_with_a_reason(tmp_path):
    root = molecule_tree(tmp_path)
    (tmp_path / 'run').mkdir()

    with pytest.raises(ValueError, match='Z'):
        pdc.prepare(tmp_path / 'run', protein='molecules/DDM/protein.pdb',
                    template='molecules/DDM/micelle_template.json',
                    settings={'seed': 1, 'aggregation_number': 4, 'protein_chains': ['A', 'Z']}, project_root=root)


def test_a_comma_separated_selection_is_accepted_and_normalised(tmp_path):
    run = prepared(tmp_path, {'protein_chains': 'A,B'})

    assert settings_of(run)['protein_chains'] == ['A', 'B']


def test_a_selection_that_is_not_a_chain_list_is_refused(tmp_path):
    with pytest.raises(ValueError, match='chain'):
        pdc.validate_payload({'template': 'ddm', 'seed': 1, 'aggregation_number': 4, 'protein_chains': 7})


def test_the_queue_route_keeps_the_selection_and_the_back_map_choice():
    """`runs.py:queue` builds a job's settings from the adapter's own vocabulary; a key it does not advertise is
    dropped silently, and the run is built on the default."""
    kept = set(pdc.PROTOCOL.settings_specs()) | set(pdc.PROTOCOL.choice_specs())

    assert {'protein_chains', 'backmap'} <= kept, 'the route would drop them before the job was created'
    assert pdc.CHOICE_SPECS['backmap'][1] == (True, False)


def test_a_posted_selection_and_a_switched_off_back_map_reach_the_job(tmp_path):
    from dashboard.app import create_app
    from dashboard.paths import Paths

    protein = tmp_path / 'prot.pdb'
    protein.write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n')
    app = create_app(Paths(workspace=tmp_path / 'ws'), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    client = app.test_client()

    response = client.post('/', json={'molecule_id': 'DDM', 'run_type': 'pdc', 'method': 'bartender',
                                      'template': 'molecules/DDM/micelle_template.json',
                                      'protein': str(protein), 'pdc_seed': 20261013,
                                      'aggregation_number': 4, 'protein_chains': ['A'], 'backmap': False})

    assert response.status_code == 201, response.get_data(as_text=True)
    settings = response.json['settings']
    assert settings['protein_chains'] == ['A']
    assert settings['backmap'] is False


# --- the build honours it ----------------------------------------------------------------------------------------

def test_the_build_writes_only_the_chosen_chains(tmp_path):
    run = prepared(tmp_path, {'protein_chains': ['A']})
    stage = stage_directory(run)
    (stage / pdc_build.CG_DIRECTORY).mkdir(exist_ok=True)
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb',
                 [(1, 'PRO', 'B01', (0.0, 0.0, 0.0))])

    pdc_build.build(stage)

    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    selected = stage / pdc_build.SELECTED_PROTEIN
    assert report['protein_chains'] == ['A']
    assert pdc_import.structure_chains(selected.read_text()) == ['A'], \
        'the protein that goes into the system is the chosen chain and nothing else'
    assert ('ALA A' in selected.read_text()) and ('LEU B' not in selected.read_text())


def test_the_build_points_the_cg_step_at_the_selected_chains(tmp_path, monkeypatch):
    """The file martinize2 reads is the filtered one -- that is what makes a trimer buildable as a monomer."""
    run = prepared(tmp_path, {'protein_chains': ['B']})
    stage = stage_directory(run)
    captured = {}

    def fake_martinize(protein, out):
        captured['protein'] = Path(protein)
        Path(out).mkdir(parents=True, exist_ok=True)
        structure = Path(out) / 'protein_cg.pdb'
        write_cg_pdb(structure, [(1, 'PRO', 'B01', (0.0, 0.0, 0.0))])
        return ['martinize2', '-f', str(protein), '-x', str(structure), '-o', str(Path(out) / 'protein.top')]

    monkeypatch.setattr(pdc_build.pdc_protein, 'martinize_command', fake_martinize)

    pdc_build.build(stage)

    assert captured['protein'].name == pdc_build.SELECTED_PROTEIN
    assert pdc_import.structure_chains(captured['protein'].read_text()) == ['B']


def test_the_build_with_no_selection_keeps_the_whole_file(tmp_path):
    run = prepared(tmp_path)
    stage = stage_directory(run)
    (stage / pdc_build.CG_DIRECTORY).mkdir(exist_ok=True)
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb',
                 [(1, 'PRO', 'B01', (0.0, 0.0, 0.0))])

    pdc_build.build(stage)

    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert report['protein_chains'] == 'all'
    assert not (stage / pdc_build.SELECTED_PROTEIN).exists(), 'no selection, so no filtered file is written'


def test_selecting_every_declared_chain_keeps_the_whole_file(tmp_path):
    """The panel's default is every chain: it must be the whole file, so nothing existing narrows by accident."""
    run = prepared(tmp_path, {'protein_chains': ['A', 'B']})
    stage = stage_directory(run)
    (stage / pdc_build.CG_DIRECTORY).mkdir(exist_ok=True)
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb',
                 [(1, 'PRO', 'B01', (0.0, 0.0, 0.0))])

    pdc_build.build(stage)

    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert report['protein_chains'] == ['A', 'B']
    assert report['protein_input'] is None
    assert not (stage / pdc_build.SELECTED_PROTEIN).exists(), 'every declared chain is the file, not a filter'


def test_a_chain_the_build_cannot_find_is_refused_rather_than_dropped(tmp_path):
    """The build is a separate process; it validates the selection again rather than trusting the settings blindly."""
    stage = tmp_path / 'stage'
    stage.mkdir()
    protein = stage / 'protein.pdb'
    protein.write_text(PROTEIN_TEXT)

    with pytest.raises(ValueError, match='Z'):
        pdc_build.select_protein(stage, protein, ['A', 'Z'])
