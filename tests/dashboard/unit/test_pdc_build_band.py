"""The system-preparation stage in the membrane frame the structure states for itself.

The placement's own tests (`test_pdc_placement.py`) pin the tube's geometry; these pin where the *stage* gets the
frame from, what it records about it, and that the box it writes contains the belt the placement made. The frame is
the protein file's own `REMARK 1/2 of bilayer thickness`, read through `micelle.frame` -- the file's statement
travels with its coordinates, which is why the structure is the authority and a catalogue entry is not.

Every structure here is written by the test: its REMARK included, no test reads the developer's workspace, and no
test runs martinize2 (the CG structure it would write is written by the test instead).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from dashboard.analysis.runs import structures as pdc_view
from detergent_pdc.execution.adapters import pdc, pdc_placement
from detergent_pdc.execution.adapters.pdc_placement import MIN_CLEARANCE_NM
from detergent_pdc.execution.scripts import pdc_build

from tests.harness.pdc_fixtures import system_stage

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
# The molecule's own length, written into the fixture structure: the tube's radius is measured from it. Two atoms,
# 2.4 nm apart, which is the scale a DDM's own structure states (measured 2.1431 nm for the packaged molecule).
MOLECULE_LENGTH_NM = 2.4


def molecule_records(length_nm: float = MOLECULE_LENGTH_NM) -> str:
    span = length_nm * 10.0
    return ('HETATM    1  C1  DDM A   1       0.000   0.000   0.000  1.00  0.00\n'
            f'HETATM    2  C2  DDM A   1   {span:8.3f}   0.000   0.000  1.00  0.00\n')


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
    (molecule / 'results/MMFF/lig1.pdb').write_text(molecule_records())
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
    return system_stage(run)


def report_of(stage: Path) -> dict:
    return json.loads((stage / pdc.REPORT_NAME).read_text())


def detergent_centres(stage: Path) -> np.ndarray:
    """The centres the build actually wrote into `system.gro`, read back with the stage's own reader."""
    atoms = pdc_view.read_gro(stage / 'system.gro')
    return np.asarray([atom['position'] for atom in atoms if str(atom['name']).startswith('DD')])


def distance_to_centre_line(sites, centre_radius: float, centre_nm: float = 0.0) -> np.ndarray:
    """Each site's distance to the tube's centre-line: the circle of `centre_radius` in the frame's own plane."""
    sites = np.asarray(sites, dtype=float)
    radial = np.hypot(sites[:, 0], sites[:, 1]) - centre_radius
    return np.hypot(radial, sites[:, 2] - centre_nm)


def test_the_stage_reads_the_structures_own_membrane_and_places_the_belt_on_its_tube(tmp_path):
    stage = stage_directory(prepared(tmp_path))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb', CG_BEADS)

    code = pdc_build.build(stage)
    report = report_of(stage)

    assert code == 3, 'the topology is still the step this stage refuses to write without a mapping'
    assert report['membrane_frame']['half_thickness_nm'] == HALF_THICKNESS_NM
    assert report['membrane_frame']['axis'] == [0.0, 0.0, 1.0]
    assert 'protein.pdb' in report['membrane_frame']['source'], 'traceable to the file that stated it'
    assert report['placement_shape'] == 'belt-torus'
    # The measured cylinder is the slab's 1.0 nm and the run's own radius_nm (3.0 nm, the sphere's number) is a floor
    # under it, so the centre-line this build uses is the larger of the two. The tube's own radius is nobody's
    # setting: it is the detergent's length, measured from the molecule's own structure (2.4 nm here).
    assert report['placement_band']['slab_radius_nm'] == 1.0
    assert report['placement_band']['centre_line_radius_nm'] == 3.0
    assert report['placement_band']['tube_radius_nm'] == MOLECULE_LENGTH_NM
    assert report['protein_clearance_nm'] >= MIN_CLEARANCE_NM

    centres = detergent_centres(stage)
    assert len(centres) == 8
    # The file the stage writes is a `.gro`: three decimals, so a reader gets the tube's distances to that
    # resolution -- which is the tolerance these assertions are made at.
    distances = distance_to_centre_line(centres, 3.0)
    assert np.allclose(distances, MOLECULE_LENGTH_NM, atol=1e-3), \
        "every placed detergent stands the detergent's own length from the centre-line"
    assert np.all(np.abs(centres[:, 2]) < MOLECULE_LENGTH_NM + 1e-3), \
        'the belt reaches the detergent length either side of the membrane centre, and no further'


def test_the_stage_refuses_a_cg_protein_whose_beads_have_no_position(tmp_path):
    """The run's own words, not only the preview's: a `nan` bead stops the stage with a reason and writes no system.

    martinize2 leaves a bead at `nan` where the structure holds no coordinates for the residue it averages -- 4iar,
    the user's own import of 2026-10-14, has 20 of its 928 beads that way -- and a distance to a bead with no
    position is not a distance. The placement's gate refuses it, so the stage exits 2 with the sentence in its report
    rather than writing a `system.gro` whose coordinates are `nan` for `grompp` to die on with nothing said.
    """
    stage = stage_directory(prepared(tmp_path))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb',
                 [*CG_BEADS, (1, 'PRO', 'B04', (float('nan'), float('nan'), float('nan')))])

    code = pdc_build.build(stage)
    report = report_of(stage)

    assert code == 2, 'a gate refused, and the report names which'
    assert [issue for issue in report['reasons'] if 'without a position' in issue], report['reasons']
    assert report['valid'] is False and report['protein_clearance_nm'] is None
    assert not (stage / 'system.gro').exists(), 'nothing was placed, so there is no system to write'


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


def test_the_box_contains_the_belt_that_reaches_past_the_slab(tmp_path):
    """The correction's consequence for the box: the belt now reaches the detergent length either side of the plane.

    A `.gro` this stage writes with a belt whose own z extent (2.4 nm) is further from the plane than either the
    slab (1.48 nm) or the protein's beads (0.2 nm) must have a box whose z contains it: 2 x (2.4 + 2.0) nm, and not
    the slab's 2 x (1.48 + 2.0) that the belt-inside-the-slab rule gave.
    """
    stage = stage_directory(prepared(tmp_path))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb',
                 [(1, 'PRO', 'B01', (1.0, 0.0, 0.2)), (1, 'PRO', 'B02', (-1.0, 0.0, 0.2)),
                  (1, 'PRO', 'B03', (0.0, 1.0, -0.2)), (1, 'PRO', 'B04', (0.0, 0.0, 0.2))])

    code = pdc_build.build(stage)
    report = report_of(stage)
    centres = detergent_centres(stage)

    assert code == 3
    assert report['placement_band']['belt_reach_nm'] == MOLECULE_LENGTH_NM
    belt_reach = float(np.abs(detergent_centres(stage)[:, 2]).max())
    assert belt_reach > 1.4, 'this belt reaches past the slab, which is what makes the box rule matter'
    assert report['box_nm'][2] == pytest.approx(2 * (report['placement_band']['belt_reach_nm'] + 2.0)), \
        "the box's z contains the belt's own reach, not only the slab the belt used to sit inside"
    assert report['box_nm'][2] / 2 - 2.0 >= belt_reach, 'and the belt is inside it by the margin the run asked for'
    assert np.all(np.abs(centres[:, 2]) < report['box_nm'][2] / 2), 'every placed centre is inside the box'


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


def test_the_report_carries_the_shell_it_measured_and_the_orientation_policy(tmp_path):
    """A run's record says which number sized its shell: the protein's measurement, not a setting and not a silence.

    `place_detergents` measures the sphere from the selection it was handed -- extent about the centroid, plus the
    clearance, plus the detergent's own reach -- and records `radius_source` on the way. Neither number reached a
    report before, so a run whose shell was measured was indistinguishable from one built at the fixed 3 nm setting.
    The shell and the capacity are what a later reader needs to tell the two apart, so both travel in the report
    beside the band, and `orientation_policy` says how the molecules were aimed.
    """
    stage = stage_directory(prepared(tmp_path, remark=False))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb', CG_BEADS)

    code = pdc_build.build(stage)
    report = report_of(stage)

    assert code == 3
    shell = report['placement_shell']
    assert shell['shape'] == pdc_placement.SHAPE_SPHERE
    # The beads reach 1.06 nm from their centroid, the clearance is 0.5 nm and the molecule's own length 2.4 nm, so
    # the measurement (3.96 nm) is what the shell is -- above the 3.0 nm setting that is only its floor. That the two
    # numbers differ is the whole point of the field: without `radius_source` a reader cannot tell them apart.
    assert shell['radius_source'] == pdc_placement.RADIUS_MEASURED
    assert shell['radius_nm'] > shell['radius_floor_nm'] == 3.0
    assert report['orientation_policy'] == pdc_placement.ORIENTATION_RADIAL
    # A build the gates accepted measured no capacity: the field is there, and `None` is its answer.
    assert report['placement_capacity'] is None
