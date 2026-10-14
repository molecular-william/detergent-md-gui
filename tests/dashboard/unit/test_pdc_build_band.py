"""The system-preparation stage in the membrane frame the structure states for itself.

The placement's own tests (`test_pdc_placement.py`) pin the band's geometry; these pin where the *stage* gets the
frame from and what it records about it. The frame is the protein file's own `REMARK 1/2 of bilayer thickness`,
read through `micelle.frame` -- the file's statement travels with its coordinates, which is why the structure is the
authority and a catalogue entry is not.

Every structure here is written by the test: its REMARK included, no test reads the developer's workspace, and no
test runs martinize2 (the CG structure it would write is written by the test instead).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from dashboard.execution.adapters import pdc, pdc_view
from dashboard.execution.adapters.pdc_placement import MIN_CLEARANCE_NM
from dashboard.execution.scripts import pdc_build

TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'DDM', 'type': 'registered-template'}],
}
TEMPLATE_PATH = 'molecules/DDM/micelle_template.json'
PROTEIN = 'molecules/DDM/protein.pdb'
REMARK = 'REMARK      1/2 of bilayer thickness:   14.8\n'
# The stage's own membrane plane statement, for the assertions below: 14.8 A stated is 1.48 nm stated.
HALF_THICKNESS_NM = 1.48
# Three beads inside the slab, the furthest 1.0 nm from the membrane axis (the file's z is the normal).
CG_BEADS = [(1, 'PRO', 'B01', (1.0, 0.0, 0.2)), (1, 'PRO', 'B02', (-1.0, 0.0, 0.2)),
            (1, 'PRO', 'B03', (0.0, 1.0, -0.2))]


def write_cg_pdb(path: Path, atoms) -> Path:
    """The CG structure as martinize2 writes it (`-x`): `ATOM` records in Angstroms, the stage reads them back."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'ATOM  {index:5d} {name:^4s} {residue:>3s} A{residue_id:4d}    '
             f'{xyz[0] * 10.0:8.3f}{xyz[1] * 10.0:8.3f}{xyz[2] * 10.0:8.3f}  1.00  0.00'
             for index, (residue_id, residue, name, xyz) in enumerate(atoms, 1)]
    path.write_text('\n'.join(lines) + '\nEND\n')
    return path


def protein_records(remark: bool) -> str:
    """A protein file: a ring of atoms in the slab, and -- when the case wants one -- its own membrane statement."""
    lines = [REMARK] if remark else []
    for index, angle in enumerate(np.linspace(0.0, 2.0 * np.pi, 12, endpoint=False), 1):
        lines.append(f'ATOM  {index:5d}  CA  ALA A{1:4d}    '
                     f'{10.0 * np.cos(angle):8.3f}{10.0 * np.sin(angle):8.3f}{2.0:8.3f}  1.00  0.00')
    return '\n'.join(lines) + '\n'


def molecule_tree(tmp_path: Path, *, remark: bool = True) -> Path:
    """A molecule directory shaped like the ones the catalogue lists, with a protein that does or does not state."""
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True)
    (molecule / 'results/MMFF/lig1.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (molecule / 'results/MMFF/lig1.itp').write_text('[ moleculetype ]\nDDM             1\n')
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    (molecule / 'protein.pdb').write_text(protein_records(remark))
    return tmp_path


def prepared(tmp_path: Path, *, remark: bool = True):
    """A prepared run whose stage 1 is ready to run: the molecule tree, the settings, and nothing else."""
    root = molecule_tree(tmp_path, remark=remark)
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, protein=PROTEIN, template=TEMPLATE_PATH,
                settings={'seed': 20260930, 'aggregation_number': 8, 'box_margin_nm': 2.0, 'initial_z_nm': 6.0},
                project_root=root)
    return run


def stage_directory(run: Path) -> Path:
    return run / Path(pdc.STAGES[0].relative).parent


def report_of(stage: Path) -> dict:
    return json.loads((stage / pdc.REPORT_NAME).read_text())


def detergent_centres(stage: Path) -> np.ndarray:
    """The centres the build actually wrote into `system.gro`, read back with the stage's own reader."""
    atoms = pdc_view.read_gro(stage / 'system.gro')
    return np.asarray([atom['position'] for atom in atoms if str(atom['name']).startswith('DD')])


def test_the_stage_reads_the_structures_own_membrane_and_places_the_belt_on_its_band(tmp_path):
    stage = stage_directory(prepared(tmp_path))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb', CG_BEADS)

    code = pdc_build.build(stage)
    report = report_of(stage)

    assert code == 3, 'the topology is still the step this stage refuses to write without a mapping'
    assert report['membrane_frame']['half_thickness_nm'] == HALF_THICKNESS_NM
    assert report['membrane_frame']['axis'] == [0.0, 0.0, 1.0]
    assert 'protein.pdb' in report['membrane_frame']['source'], 'traceable to the file that stated it'
    assert report['placement_shape'] == 'belt-band'
    # The measured radius is the slab's 1.0 nm plus the 0.5 nm gate -- but the run's own radius (3.0 nm, the sphere's
    # number) is a floor under it, so the belt this build makes is the larger of the two.
    assert report['placement_band']['slab_radius_nm'] == 1.0
    assert report['placement_band']['radius_nm'] == 3.0
    assert report['protein_clearance_nm'] >= MIN_CLEARANCE_NM

    centres = detergent_centres(stage)
    assert len(centres) == 8
    # The file the stage writes is a `.gro`: three decimals, so a reader gets the band's radius to that resolution.
    assert np.all(np.abs(centres[:, 2]) < HALF_THICKNESS_NM), 'the belt is in the membrane plane the structure stated'
    assert np.allclose(np.hypot(centres[:, 0], centres[:, 1]), 3.0, atol=1e-3), 'and at the belt\'s own radius'


def test_the_band_builds_a_box_whose_z_clears_the_protein_rather_than_the_belt(tmp_path):
    """The box's z margin is the protein's: the belt sits inside the slab and is thinner than the protein here.

    Phase C1: `membrane_box`'s z is 2 x (the furthest bead from the plane + the margin). The rule it replaces took
    the placed centres' span instead -- on 1AT9 that is the 2.96 nm slab against a protein whose own z span is
    6.03 nm -- so a protein reaching past the belt got a fraction of the margin the run asked every face to clear it
    by. A bead at +2.5 nm makes the protein the further thing, and the box has to follow it.
    """
    stage = stage_directory(prepared(tmp_path))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb',
                 CG_BEADS + [(1, 'PRO', 'B04', (0.0, 0.0, 2.5))])

    code = pdc_build.build(stage)
    report = report_of(stage)

    assert code == 3
    assert report['box_nm'][2] == pytest.approx(2 * (2.5 + 2.0)), \
        'z clears the furthest protein bead, not the belt the placement was given'


def test_a_protein_that_states_no_membrane_builds_the_sphere_it_always_did(tmp_path):
    stage = stage_directory(prepared(tmp_path, remark=False))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb', CG_BEADS)

    code = pdc_build.build(stage)
    report = report_of(stage)

    assert code == 3
    assert report['membrane_frame'] is None, 'a thickness nobody states is not a frame'
    assert report['placement_shape'] == 'sphere' and report['placement_band'] is None


def test_an_empty_micelle_build_states_no_membrane_and_places_the_sphere(tmp_path):
    """The user's decision, end to end: no protein, a simple sphere, and nothing invented about a bilayer."""
    root = molecule_tree(tmp_path)
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, template=TEMPLATE_PATH, settings={'seed': 20260930, 'aggregation_number': 6},
                project_root=root)
    stage = stage_directory(run)

    code = pdc_build.build(stage)
    report = report_of(stage)
    centres = detergent_centres(stage)

    assert code == 3
    assert report['protein_free'] is True and report['placed_detergents'] == 6
    assert report['membrane_frame'] is None and report['placement_band'] is None
    assert report['placement_shape'] == 'sphere'
    assert np.allclose(np.linalg.norm(centres, axis=1), 3.0, atol=1e-3), 'the simple sphere the empty micelle had'
