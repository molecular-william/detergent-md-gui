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
from detergent_pdc.execution import pdc_preview
from detergent_pdc.execution.adapters import pdc, pdc_box, pdc_placement
from detergent_pdc.execution.adapters.pdc_placement import MIN_CLEARANCE_NM
from detergent_pdc.execution.scripts import pdc_build
from micelle.registry import load_template

from tests.harness.pdc_fixtures import TEMPLATE, system_stage, write_cg_pdb

TEMPLATE_PATH = 'molecules/DDM/micelle_template.json'
PROTEIN = 'molecules/DDM/protein.pdb'
REMARK = 'REMARK      1/2 of bilayer thickness:   14.8\n'
# The stage's own membrane plane statement, for the assertions below: 14.8 A stated is 1.48 nm stated.
HALF_THICKNESS_NM = 1.48
# A transmembrane bundle inside the slab: two rings of radius 1.0 nm at z = -1 and +1, so its principal axis is
# the file's z (the frame normal) rather than an arbitrary in-plane direction.
CG_BEADS = [(1, 'PRO', 'B01', (1.0, 0.0, -1.0)), (1, 'PRO', 'B02', (-1.0, 0.0, -1.0)),
            (1, 'PRO', 'B03', (0.0, 1.0, -1.0)), (1, 'PRO', 'B04', (0.0, -1.0, -1.0)),
            (1, 'PRO', 'B05', (1.0, 0.0, 1.0)), (1, 'PRO', 'B06', (-1.0, 0.0, 1.0)),
            (1, 'PRO', 'B07', (0.0, 1.0, 1.0)), (1, 'PRO', 'B08', (0.0, -1.0, 1.0))]
# The molecule's own length, written into the fixture structure: the tube's radius is measured from it. Two atoms,
# 2.4 nm apart, which is the scale a DDM's own structure states (measured 2.1431 nm for the packaged molecule).
MOLECULE_LENGTH_NM = 2.4


def molecule_records(length_nm: float = MOLECULE_LENGTH_NM) -> str:
    span = length_nm * 10.0
    return ('HETATM    1  C1  DDM A   1       0.000   0.000   0.000  1.00  0.00\n'
            f'HETATM    2  C2  DDM A   1   {span:8.3f}   0.000   0.000  1.00  0.00\n')


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


def prepared(tmp_path: Path, *, remark: bool = True, settings: dict | None = None):
    """A prepared run whose stage 1 is ready to run: the molecule tree, the settings, and nothing else."""
    root = molecule_tree(tmp_path, remark=remark)
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, protein=PROTEIN, template=TEMPLATE_PATH,
                settings={'seed': 20260930, 'aggregation_number': 8, 'box_margin_nm': 2.0, 'initial_z_nm': 6.0}
                | (settings or {}),
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


def distance_to_axis(sites, axis, origin) -> np.ndarray:
    """Each site's radial distance from the cylinder's axis, the way the placement measures it."""
    sites = np.asarray(sites, dtype=float)
    axis = np.asarray(axis, dtype=float)
    relative = sites - np.asarray(origin, dtype=float)
    axial = relative @ axis
    return np.linalg.norm(relative - np.outer(axial, axis), axis=1)


def test_the_stage_reads_the_structures_own_membrane_and_places_the_belt_on_its_cylinder(tmp_path):
    stage = stage_directory(prepared(tmp_path))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb', CG_BEADS)

    code = pdc_build.build(stage)
    report = report_of(stage)

    assert code == 3, 'the topology is still the step this stage refuses to write without a mapping'
    assert report['membrane_frame']['half_thickness_nm'] == HALF_THICKNESS_NM
    assert report['membrane_frame']['axis'] == [0.0, 0.0, 1.0]
    assert 'protein.pdb' in report['membrane_frame']['source'], 'traceable to the file that stated it'
    assert report['placement_shape'] == 'belt-cylinder'
    # The measured cylinder is the bundle's own 1.0 nm radius, and the belt now follows that measurement: the sphere's
    # 3.0 nm default is not a belt floor any more. The stand-off is the detergent's length, measured from the
    # molecule's own structure (2.4 nm here).
    band = report['placement_band']
    assert band['slab_radius_nm'] == 1.0
    assert band['cylinder']['radius_nm'] == 1.0
    assert band['cylinder']['atom_count'] == len(CG_BEADS)
    assert band['cylinder']['axis'] == [0.0, 0.0, 1.0]
    assert band['radius_nm'] == 1.0 and band['radius_source'] == 'measured'
    assert band['detergent_length_nm'] == MOLECULE_LENGTH_NM
    assert report['protein_clearance_nm'] >= MIN_CLEARANCE_NM

    centres = detergent_centres(stage)
    assert len(centres) == 8
    # The file the stage writes is a `.gro`: three decimals, so a reader gets the cylinder's distances to that
    # resolution -- which is the tolerance these assertions are made at.
    distances = distance_to_axis(centres, band['cylinder']['axis'], band['cylinder']['origin_nm'])
    assert np.allclose(distances, band['radius_nm'] + MOLECULE_LENGTH_NM, atol=1e-3), \
        "every placed head stands the detergent's own length outside the cylinder surface"
    plane_z = report['membrane_frame']['centre_nm']
    relative_z = centres[:, 2] - plane_z
    assert np.all(np.abs(relative_z) <= band['vertical_half_band_nm'] + 1e-3), \
        'the belt stays inside the spread vertical band'
    assert np.max(np.abs(relative_z)) > 0.85 * band['vertical_half_band_nm'], \
        'and the same count covers that band, not one height'


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


def test_the_band_builds_a_box_whose_z_clears_whichever_reaches_further(tmp_path):
    """`membrane_box`'s z is 2 x (the furthest thing from the plane + the margin), protein or belt.

    A bead at +5 nm reaches past the slab; with the default 2.0x vertical spread the belt can reach further still,
    and the box has to contain whichever of the two does.
    """
    stage = stage_directory(prepared(tmp_path))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb',
                 CG_BEADS + [(1, 'PRO', 'B09', (0.0, 0.0, 5.0))])

    code = pdc_build.build(stage)
    report = report_of(stage)

    assert code == 3
    furthest = max(5.0, report['placement_band']['belt_reach_nm'])
    assert report['box_nm'][2] == pytest.approx(2 * (furthest + 2.0)), \
        'z clears the furthest protein bead or the belt, whichever reaches further'


def test_the_box_contains_the_belt_that_reaches_past_the_slab(tmp_path):
    """The spread band's consequence for the box: the belt now reaches 1.5x the old half-height either side.

    A `.gro` this stage writes with a belt whose own z extent (up to 3.6 nm here) is further from the plane than
    either the slab (1.48 nm) or the protein's beads (0.9 nm) must have a box whose z contains it: 2 x (the belt's
    recorded reach + 2.0) nm, and not the slab's 2 x (1.48 + 2.0) that the belt-inside-the-slab rule gave.
    """
    stage = stage_directory(prepared(tmp_path))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb',
                 [(1, 'PRO', 'B01', (1.0, 0.0, -0.9)), (1, 'PRO', 'B02', (-1.0, 0.0, -0.9)),
                  (1, 'PRO', 'B03', (0.0, 1.0, -0.9)), (1, 'PRO', 'B04', (0.0, -1.0, -0.9)),
                  (1, 'PRO', 'B05', (1.0, 0.0, 0.9)), (1, 'PRO', 'B06', (-1.0, 0.0, 0.9)),
                  (1, 'PRO', 'B07', (0.0, 1.0, 0.9)), (1, 'PRO', 'B08', (0.0, -1.0, 0.9))])

    code = pdc_build.build(stage)
    report = report_of(stage)
    centres = detergent_centres(stage)

    assert code == 3
    band = report['placement_band']
    plane_z = report['membrane_frame']['centre_nm']
    belt_reach = float(np.abs(centres[:, 2] - plane_z).max())
    assert belt_reach > 1.4, 'this belt reaches past the slab, which is what makes the box rule matter'
    assert band['belt_reach_nm'] > MOLECULE_LENGTH_NM, 'the spread band reaches further than the old half-height'
    assert band['belt_reach_nm'] >= belt_reach - 1e-3, 'and the record includes the body the build stamps'
    assert report['box_nm'][2] == pytest.approx(2 * (band['belt_reach_nm'] + 2.0)), \
        "the box's z contains the belt's own reach, not only the slab the belt used to sit inside"
    assert report['box_nm'][2] / 2 - 2.0 >= belt_reach - 1e-3, \
        'and the belt is inside it by the margin the run asked for'
    assert np.all((centres[:, 2] > 0) & (centres[:, 2] < report['box_nm'][2])), \
        'every placed centre is inside the box'


def test_the_build_widens_the_belt_box_in_x_and_y_and_records_the_growth(tmp_path):
    """Item 2 in the stage's own report: x/y clear the belt's radial surface plus the detergent's length.

    The band is measured before the box, and a belt's volume is its torus's own (`radius_nm` plus the detergent's
    length through the band's height), so the widening does not change the recorded density. The report states both
    boxes and the growth between them, so a reader sees the widening rather than having to subtract two fields.
    """
    stage = stage_directory(prepared(tmp_path))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb', CG_BEADS)

    code = pdc_build.build(stage)
    report = report_of(stage)

    assert code == 3
    band = report['placement_band']
    belt_radius = band['radius_max_nm'] + band['detergent_length_nm']
    initial = report['box_nm_initial']
    expected = [round(max(initial[0], 2 * belt_radius) + 2 * 2.0, 6),
                round(max(initial[1], 2 * belt_radius) + 2 * 2.0, 6), report['box_nm'][2]]
    assert report['box_nm'] == expected, 'x and y carry the belt reach; z still clears the protein and the belt'
    old = pdc_box.membrane_box([list(bead[3]) for bead in CG_BEADS], half_thickness_nm=HALF_THICKNESS_NM,
                               margin_nm=2.0, initial_z_nm=6.0, belt_reach_nm=band['belt_reach_nm'])
    assert report['box_nm'][:2] > old[:2], 'and they are wider than the footprint-plus-margin rule item 2 replaces'
    assert report['box_widening_nm'] == [round(report['box_nm'][index] - initial[index], 6) for index in (0, 1)]
    assert report['box_widening_nm'][0] > 0


def test_a_self_assembled_build_keeps_the_box_its_generator_sampled_in(tmp_path):
    """Self-assembly samples inside the initial box, so its placement and its cell must not be widened.

    The cloud is compared with a fresh self-assembly placement over the same beads and settings, and the box's x/y
    with the initial box: this is the path the density policy leaves byte-identical.
    """
    stage = stage_directory(prepared(tmp_path, settings={'placement_mode': 'self-assembly'}))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb', CG_BEADS)

    code = pdc_build.build(stage)
    report = report_of(stage)

    assert code == 3 and report['placement_mode'] == 'self-assembly'
    assert report['placement_band'] is None
    assert report['box_nm'][:2] == report['box_nm_initial'][:2], 'the cell x/y is the one the cloud was sampled in'
    assert report['box_widening_nm'] == [0.0, 0.0]
    settings = json.loads((stage / pdc.SETTINGS_NAME).read_text())
    points = [list(bead[3]) for bead in CG_BEADS]
    placement = pdc_placement.place_detergents(points, load_template(tmp_path / 'molecules' / 'DDM'
                                                                     / 'micelle_template.json'),
                                               settings['aggregation_number'], settings['seed'],
                                               radius_nm=settings['radius_nm'], mode='self-assembly',
                                               margin_nm=settings['box_margin_nm'],
                                               initial_z_nm=settings['initial_z_nm'], body_profile=None)
    centres = detergent_centres(stage) - np.asarray(report['centring']['shift_nm'])
    assert np.allclose(centres, np.asarray(placement['centers']), atol=1e-3), \
        'the built cloud is the generator\'s own, unchanged by the box work'


def test_a_stated_initial_xy_that_is_below_the_footprint_does_not_shrink_the_box(tmp_path):
    """The box rule's floor, measured through the stage's own record: stated x/y cannot put a face through the protein.

    The CG beads span 2 x 2 nm, so with a 2 nm margin the derived x/y are 6 nm. A stated 1 nm is below that and the
    build writes 6 nm (and its initial box, which the widening is measured from, is that same derived value); a stated
    8 x 9 is the caller's wider cell. No membrane here, so the sphere path passes `initial_box`'s x/y straight through.
    """
    root = molecule_tree(tmp_path, remark=False)
    for name, stated, expected in (('floor', (1.0, 1.0), [6.0, 6.0]),
                                   ('stated', (8.0, 9.0), [8.0, 9.0])):
        run = tmp_path / name
        run.mkdir()
        pdc.prepare(run, protein=PROTEIN, template=TEMPLATE_PATH,
                    settings={'seed': 20260930, 'aggregation_number': 8, 'box_margin_nm': 2.0,
                              'initial_z_nm': 6.0, 'initial_x_nm': stated[0], 'initial_y_nm': stated[1]},
                    project_root=root)
        stage = system_stage(run)
        write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb', CG_BEADS)

        assert pdc_build.build(stage) == 3
        report = report_of(stage)
        assert report['initial_x_nm'] == stated[0] and report['initial_y_nm'] == stated[1]
        assert report['box_nm_initial'][:2] == expected, f'{name}: the stated floor was read as a ceiling'
        assert report['box_nm'][:2] == expected, f'{name}: the sphere cell passes the initial x/y through'
        assert report['box_widening_nm'] == [0.0, 0.0], 'a sphere path is never widened by the belt rule'


def test_the_preview_and_the_build_agree_on_a_belts_box(tmp_path, monkeypatch):
    """One rule, two callers: the preview's `basis['box_nm']` is the box the same placement makes the stage write.

    The stated initial x/y travel through both callers as floors, so the agreement holds for a run that states its
    starting cell as well as for one that leaves it blank.
    """
    run = prepared(tmp_path, settings={'initial_x_nm': 11.0, 'initial_y_nm': 12.0})
    stage = system_stage(run)
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb', CG_BEADS)
    code = pdc_build.build(stage)
    report = report_of(stage)
    assert code == 3

    beads = [{'residue_id': residue_id, 'residue': residue, 'name': name, 'position': list(position)}
             for residue_id, residue, name, position in CG_BEADS]
    monkeypatch.setattr(pdc_preview, 'coarse_grained',
                        lambda *args, **kwargs: (beads, {'cached': False, 'seconds': 0.0, 'key': 'stub',
                                                         'path': '', 'beads_bytes': 0}))
    monkeypatch.setattr(pdc_preview, '_solvent', lambda *args, **kwargs: None)

    answer = pdc_preview.preview(project_root=tmp_path, cache_root=tmp_path / 'cache', template=TEMPLATE_PATH,
                                 seed=20260930, protein=PROTEIN, chains=['A'], mapping=None,
                                 aggregation_number=8, box_margin_nm=2.0, initial_z_nm=6.0,
                                 initial_x_nm=11.0, initial_y_nm=12.0)

    assert answer['valid'], answer['reasons']
    assert answer['basis']['box_nm'] == report['box_nm']


def test_a_protein_that_states_no_membrane_builds_the_sphere_it_always_did(tmp_path):
    stage = stage_directory(prepared(tmp_path, remark=False))
    write_cg_pdb(stage / pdc_build.CG_DIRECTORY / 'protein_cg.pdb', CG_BEADS)

    code = pdc_build.build(stage)
    report = report_of(stage)

    assert code == 3
    assert report['membrane_frame'] is None, 'a thickness nobody states is not a frame'
    assert report['placement_shape'] == 'sphere' and report['placement_band'] is None
    assert report['box_nm'][:2] == report['box_nm_initial'][:2]
    assert report['box_widening_nm'] == [0.0, 0.0], 'no belt, no widening: today\'s box exactly'


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
    assert report['box_nm'][:2] == report['box_nm_initial'][:2], 'a protein-free build is the sphere path, unchanged'
    assert report['box_widening_nm'] == [0.0, 0.0]
    assert np.allclose(centres.mean(axis=0), np.asarray(report['box_nm']) / 2, atol=1e-3), \
        'the box is centred on the detergent cloud the build placed'
    original = centres - np.asarray(report['centring']['shift_nm'])
    assert np.allclose(np.linalg.norm(original, axis=1), 3.0, atol=1e-3), \
        'and the simple sphere the empty micelle had is unchanged under the centring shift'


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
