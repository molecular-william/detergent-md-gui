"""Detergent placement: the builder's geometry plus the gates that decide whether a run may proceed.

The properties worth pinning are the ones a reader would otherwise have to trust: the count is exact, the same seed
gives the same positions while a different seed does not, every detergent is outside the protein, and an impossible
packing is reported as an issue rather than handed back as coordinates for a run to fail on later.

The belt's own shape is the *transmembrane cylinder* the user decided on (2026-11-16): the in-slab protein atoms'
principal axis, furthest radius and axial extent are the cylinder, every head stands the molecule's own length
outside that surface on the outward normal, and every body is that normal tilted by the documented angle so its tail
sits nearer the axis. These tests measure that shape rather than describe it.
"""
import hashlib
import json

import numpy as np
import pytest
from detergent_pdc.execution.adapters import pdc_placement
from detergent_pdc.execution.adapters.pdc_box import initial_box
from detergent_pdc.execution.scripts import pdc_build
from micelle.frame import frame_from_structure
from micelle.packing import golden_angle_directions
from micelle.registry import load_template

PROTEIN = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
#: The fixture molecule's own length: its structure is two atoms this far apart, which is how far outside the
#: cylinder every head stands. A molecule nobody can measure -- `length_nm=None` -- is the case that keeps the sphere.
MOLECULE_LENGTH_NM = 2.0
#: The stated tolerance on "the head end stands outside the cylinder's surface". The placement's own sites are exact; the
#: *stamped* molecule's beads are rounded to five decimals (`pdc_build.stamp`) and the `.gro` the build writes rounds
#: again to a thousandth of a nanometre, which is where the two assertions below sit.
SURFACE_TOLERANCE_NM = 1e-5
#: A two-bead detergent of the shape `stamp` orients: one C-type tail bead and one head bead, 0.5 nm apart.
DRAFT = {'residue': 'DDM', 'beads': [{'name': 'TAIL1', 'type': 'C1', 'position': [0.0, 0.0, 0.0]},
                                     {'name': 'HEAD', 'type': 'SN6', 'position': [0.5, 0.0, 0.0]}]}


def molecule_records(length_nm: float | None = MOLECULE_LENGTH_NM) -> str:
    """A molecule's own structure: two atoms `length_nm` apart, written in a PDB's Angstrom columns."""
    span = 0.0 if length_nm is None else length_nm * 10.0
    return ('HETATM    1  C1  DDM A   1       0.000   0.000   0.000  1.00  0.00\n'
            f'HETATM    2  C2  DDM A   1   {span:8.3f}   0.000   0.000  1.00  0.00\n')


def _template(tmp_path, length_nm: float | None = MOLECULE_LENGTH_NM):
    """A template whose molecule states its own length: the structure's two atoms are `length_nm` apart."""
    (tmp_path / 'x.pdb').write_text('REMARK  a molecule with no coordinate records\n' if length_nm is None
                                    else molecule_records(length_nm))
    (tmp_path / 'x.itp').write_text('')
    path = tmp_path / 'x.json'
    path.write_text(json.dumps({'name': 'X', 'residue': 'X', 'beads': [{'name': 'B1'}, {'name': 'B2'}],
                                'coordinates': 'x.pdb', 'topology': 'x.itp', 'tail_direction': [0, 0, -1]}))
    return load_template(path)


def test_placement_is_exact_deterministic_and_outside_the_protein(tmp_path):
    first = pdc_placement.place_detergents(PROTEIN, _template(tmp_path), 12, seed=7)
    again = pdc_placement.place_detergents(PROTEIN, _template(tmp_path), 12, seed=7)
    other = pdc_placement.place_detergents(PROTEIN, _template(tmp_path), 12, seed=8)

    assert first['valid'], first['issues']
    assert len(first['centers']) == 12, 'the requested count is the count that is placed'
    assert first['centers'] == again['centers'], 'the seed decides, not the clock'
    assert other['centers'] != first['centers'], 'a different seed must place differently'

    points = np.asarray(PROTEIN)
    for center in np.asarray(first['centers']):
        assert np.linalg.norm(center - points, axis=1).min() >= pdc_placement.MIN_CLEARANCE_NM
    assert first['protein_clearance_nm'] >= pdc_placement.MIN_CLEARANCE_NM


def test_an_empty_micelle_has_no_protein_to_clear(tmp_path):
    placed = pdc_placement.place_detergents(None, _template(tmp_path), 8, seed=3)
    assert placed['valid'] and placed['protein_free']
    assert len(placed['centers']) == 8 and placed['protein_clearance_nm'] is None


def test_an_impossible_packing_is_reported_rather_than_returned(tmp_path):
    """The builder's policy: an impossible request writes diagnostics and produces no run."""
    placed = pdc_placement.place_detergents(None, _template(tmp_path), 4, seed=1, radius_nm=0.1)
    assert not placed['valid']
    assert any('overlap' in issue for issue in placed['issues']), placed['issues']


def test_a_placement_refuses_impossible_input(tmp_path):
    with pytest.raises(ValueError, match='at least one detergent'):
        pdc_placement.place_detergents(None, _template(tmp_path), 0, seed=1)
    with pytest.raises(ValueError, match='radius must be positive'):
        pdc_placement.place_detergents(None, _template(tmp_path), 4, seed=1, radius_nm=0)


def test_the_aliphatic_tail_is_every_carbon_family_bead_that_is_not_a_virtual_site():
    """Martini 3 spells a small or tiny apolar bead with the same C family as a regular one.

    `SC1`-`SC6` and `TC1`-`TC6` are the small/tiny spellings (`structures.bead_family` is the engine's one reader),
    so a detergent whose tail is drawn with them must still have a forward end and a hydrophobic core. A ring
    interaction site is a virtual `TC4`, whose family letter is C but which sits at the sugar head -- treating it as
    the tail would turn the whole molecule around.
    """
    assert pdc_placement.tail_bead({'name': 'T1', 'type': 'C1'})
    assert pdc_placement.tail_bead({'name': 'T2', 'type': 'SC3'})
    assert pdc_placement.tail_bead({'name': 'T3', 'type': 'TC2'})
    assert not pdc_placement.tail_bead({'name': 'S1VS', 'type': 'TC4', 'virtual_site': {'function': 1}})
    assert not pdc_placement.tail_bead({'name': 'H1', 'type': 'SP1r'})
    assert not pdc_placement.tail_bead({'name': 'H2', 'type': 'SN6'})


def test_the_placement_direction_is_outward_from_the_micelle_centre(tmp_path):
    """The one convention `stamp` has to orient against, pinned so it cannot be flipped in the wrong place.

    On the lattice the centres *are* the micelle's own middle plus the direction times the radius
    (`pack_micelle`), so a direction cannot be re-signed here without moving every detergent off its own shell:
    whatever a detergent's head is aimed with, it is aimed along this vector. Measured before the fix: the frames
    this pipeline produced put the head beads on the inward side of it, which is how a micelle came to be drawn
    inside out.
    """
    template = _template(tmp_path)
    placed = pdc_placement.place_detergents(PROTEIN, template, 24, seed=20260501, mode='lattice')

    centres = np.asarray(placed['centers'])
    directions = np.asarray(placed['directions'])
    middle = np.asarray(PROTEIN).mean(axis=0)
    for centre, direction in zip(centres, directions):
        outward = (centre - middle) / np.linalg.norm(centre - middle)
        assert np.allclose(direction, outward), \
            'the lattice direction is the way out of the micelle, not through it'
        assert np.dot(centre - middle, direction) > 0, 'every direction points away from the centre'


def test_the_self_assembly_direction_faces_out_of_the_cloud(tmp_path):
    """The convention `stamp` orients against, after the sampler stopped handing every detergent the same radial.

    The direction is *drawn* now (`test_self_assembled_orientations_are_not_all_one_direction`), so it is no longer
    the centre's own heading; what still has to hold -- because `pdc_build.stamp` puts the head end along it -- is
    that it points away from the cloud rather than through it. The empty micelle's region is centred on the origin,
    so "away" is measured against the site's own offset from that centre.
    """
    template = _template(tmp_path)
    placed = pdc_placement.place_detergents(None, template, 24, seed=20260502, mode='self-assembly',
                                            radius_nm=3.0)

    centres = np.asarray(placed['centers'])
    directions = np.asarray(placed['directions'])
    assert len(centres) == 24
    assert np.allclose(np.linalg.norm(directions, axis=1), 1.0)
    assert np.all((centres * directions).sum(axis=1) > 0), 'a head drawn facing into the cloud was flipped'
    assert not np.allclose(directions, centres / np.linalg.norm(centres, axis=1)[:, None]), \
        'one radial for the whole cloud is the behaviour this replaces'


# --- the cylinder: the shape a protein that states its own membrane is placed in ----------------------------

def _frame(half_thickness_nm=1.0, axis=(0.0, 0.0, 1.0)):
    """The frame `micelle.frame` builds from a structure's own REMARK -- the module the placement reads it from."""
    return frame_from_structure(half_thickness_nm, axis=axis, source="the structure's own REMARK")


def _ring(radius, z, count=12):
    angles = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False)
    return [[radius * np.cos(angle), radius * np.sin(angle), z] for angle in angles]


def _asymmetric_protein():
    """A belt inside the slab and a fat soluble domain above it: the protein whose centroid is not on the membrane.

    Its atoms reach 1.0 nm radially inside the bilayer and 5.0 nm transversely *outside* it, so a rule that measures
    the belt from the centroid or from the protein's whole extent gives a different radius from the slab's own.
    """
    return _ring(1.0, 0.2) + _ring(5.0, 3.0)


def distance_to_axis(sites, axis, origin=(0.0, 0.0, 0.0)):
    """Each site's radial distance from the cylinder's axis: the line through `origin` along `axis`."""
    sites = np.asarray(sites, dtype=float)
    axis = np.asarray(axis, dtype=float)
    relative = sites - np.asarray(origin, dtype=float)
    axial = relative @ axis
    return np.linalg.norm(relative - np.outer(axial, axis), axis=1)


def test_a_protein_bead_with_no_position_refuses_rather_than_measuring_a_clearance_of_nan(tmp_path):
    """martinize2 leaves a bead at `nan` where its structure holds no coordinates for the residue.

    Measured on the user's own 4iar (2026-10-14): 20 of the 928 beads its CG step wrote carry `nan` -- the
    deposited assembly is missing the side-chain atoms of 16 residues (ARG, LYS and one TRP), so the bead
    martinize2 averages them into has no position. `nan` is not a distance: `nan < gate` is False, so the clearance
    gate passed every site without measuring one, and the clearance the placement reported was itself a `nan` --
    a number no browser's `JSON.parse` will read, which is how the sentence the build answered with went missing
    from the panel and came back as "the build gave no reason". A protein nothing can be measured against is
    refused, with the count of its unplaced beads, and reports no clearance at all.
    """
    protein = PROTEIN + [[float('nan'), float('nan'), float('nan')]]

    placement = pdc_placement.place_detergents(protein, _template(tmp_path), 12, seed=7)

    assert placement['valid'] is False
    assert [issue for issue in placement['issues'] if 'without a position' in issue], placement['issues']
    assert placement['protein_clearance_nm'] is None, 'an unmeasurable clearance is not a number to report'
    assert placement['centers'] == [], 'a refused placement places nothing'
    assert placement['placement_shape'] is None, 'nothing was drawn, so there is no shape to name'


def test_a_protein_with_no_position_does_not_make_the_self_assembling_sampler_raise(tmp_path):
    """The same gate on the other branch: `numpy` refuses an unbounded uniform draw, and the builder must not 500.

    `_self_assemble` centres its box on the protein's atom-mean, which is a `nan` when any bead has no position;
    `Generator.uniform` then raises `OverflowError: Range exceeds valid bounds` -- measured on 4iar in
    `self-assembly` style, an exception no caller catches and no browser parses. The finiteness gate runs before the
    draw, so that branch never sees the `nan` and the refusal is the gate's own sentence.
    """
    protein = PROTEIN + [[float('nan'), float('nan'), float('nan')]]

    placement = pdc_placement.place_detergents(protein, _template(tmp_path), 12, seed=7, mode='self-assembly')

    assert placement['valid'] is False
    assert [issue for issue in placement['issues'] if 'without a position' in issue], placement['issues']


def test_a_stated_membrane_puts_the_placement_on_the_cylinders_own_surface(tmp_path):
    """The cylinder is measured from the transmembrane atoms, and every head stands a length outside it.

    The frame states which atoms are transmembrane; their principal axis, furthest radius and axial extent are the
    cylinder. Every head site is that surface radius plus the molecule's own length along the outward normal, at its
    own height from the golden-angle ladder -- not one shared meridian around a tube.
    """
    points = _asymmetric_protein()
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame())

    band = placed['band']
    cylinder = band['cylinder']
    centres = np.asarray(placed['centers'])
    axis = np.asarray(cylinder['axis'])
    origin = np.asarray(cylinder['origin_nm'])
    relative = centres - origin
    axial = relative @ axis
    radial = distance_to_axis(centres, axis, origin)

    assert placed['valid'], placed['issues']
    assert placed['placement_shape'] == 'belt-cylinder'
    assert cylinder['atom_count'] == 12, 'the in-slab ring is the transmembrane cloud'
    assert np.allclose(axis, [0.0, 0.0, 1.0])
    assert cylinder['axis_source'] == 'frame-normal', 'the axis is always the membrane normal'
    assert cylinder['radius_nm'] == pytest.approx(1.0)
    assert cylinder['height_nm'] == pytest.approx(2.0), 'the axial extent widened to the stated slab thickness'
    # The surface is the measured 1.0 nm, and the sphere's radius is not a belt floor any more.
    assert band['radius_nm'] == 1.0 and band['radius_floor_nm'] == 0.0
    assert band['radius_source'] == 'measured'
    assert band['slab_radius_nm'] == 1.0, 'the old frame-axis measurement is kept beside the cylinder'
    assert band['detergent_length_nm'] == MOLECULE_LENGTH_NM
    assert band['vertical_half_band_nm'] == pytest.approx(pdc_placement.VERTICAL_SPREAD * MOLECULE_LENGTH_NM)
    assert (band['plane_low_nm'], band['plane_high_nm']) == (-1.0, 1.0)
    # Acceptance (e): the record names the cylinder and how the orientations were come by.
    assert band['orientation'] == {'policy': pdc_placement.ORIENTATION_CYLINDER_TILTED,
                                   'tilt_deg': pdc_placement.TILT_DEGREES,
                                   'axis_source': cylinder['axis_source']}
    assert band['tilt_deg'] == pdc_placement.TILT_DEGREES
    assert placed['orientation_policy'] == pdc_placement.ORIENTATION_CYLINDER_TILTED

    assert np.allclose(radial, cylinder['surface_radius_nm'] + MOLECULE_LENGTH_NM, atol=1e-9), \
        "every head is the molecule's own length outside the cylinder surface"
    assert np.all(np.abs(axial) <= band['vertical_half_band_nm'] + 1e-9), 'no site leaves the stated band'
    assert axial.max() - axial.min() > 0.9 * 2.0 * band['vertical_half_band_nm'], \
        'the same count covers the whole band, not one height'
    assert placed['protein_clearance_nm'] >= pdc_placement.MIN_CLEARANCE_NM


def test_the_vertical_spread_is_a_half_height_in_nm_when_stated(tmp_path):
    """Blank keeps the retired multiple of the detergent's own length; a stated number is the band's exact half-height.

    The setting changed units on 2026-11-24: the panel asks for nm, and the adapter still reads the old multiple for a
    payload or preset written before that, so the blank path has to place the band it always did.
    """
    points = _asymmetric_protein()
    template = _template(tmp_path)
    blank = pdc_placement.place_detergents(points, template, 12, seed=4, frame=_frame(),
                                           vertical_spread=pdc_placement.DEFAULT_BELT_VERTICAL_SPREAD)
    stated = pdc_placement.place_detergents(points, template, 12, seed=4, frame=_frame(),
                                            vertical_spread=pdc_placement.DEFAULT_BELT_VERTICAL_SPREAD,
                                            vertical_half_nm=3.25)

    assert blank['band']['vertical_half_band_nm'] == pytest.approx(
        pdc_placement.DEFAULT_BELT_VERTICAL_SPREAD * MOLECULE_LENGTH_NM)
    assert blank['band']['vertical_half_nm'] is None, 'a blank states no number of its own'
    assert stated['band']['vertical_half_nm'] == pytest.approx(3.25)
    assert stated['band']['vertical_half_band_nm'] == pytest.approx(3.25),         'the stated nm is the half-height, not a multiple of the length'
    heights = np.abs(np.asarray(stated['centers']) @ np.asarray(stated['band']['cylinder']['axis'])
                     - np.asarray(stated['band']['cylinder']['origin_nm'])
                     @ np.asarray(stated['band']['cylinder']['axis']))
    assert heights.max() <= 3.25 + 1e-9, 'no site leaves the stated band'
    assert heights.max() > 0.85 * 3.25, 'the same count still covers the whole band'


def test_a_tilted_transmembrane_bundle_still_uses_the_frame_normal(tmp_path):
    """Acceptance (a): the axis is the membrane frame's normal even for a tilted bundle.

    The frame normal is the slab's +z. The bundle's atoms run along a tilted direction and all sit inside the slab;
    the cylinder keeps the membrane's own direction (the user's decision), and the radius is the furthest atom from
    that axis's line, measured about the atoms' centroid.
    """
    tilt = np.asarray([0.45, 0.0, 1.0])
    tilt = tilt / np.linalg.norm(tilt)
    across = np.asarray([1.0, 0.0, 0.0])
    across = across - tilt * float(across @ tilt)
    across = across / np.linalg.norm(across)
    around = np.asarray([0.0, 1.0, 0.0])
    heights = np.linspace(-0.65, 0.65, 14)
    points = [list(height * tilt + 0.35 * across * np.cos(angle) + 0.35 * around * np.sin(angle))
              for height in heights for angle in np.linspace(0.0, 2.0 * np.pi, 8, endpoint=False)]
    placed = pdc_placement.place_detergents(points, _template(tmp_path, length_nm=0.5), 8, seed=2,
                                            frame=_frame(), belt_floor_nm=1.0)

    cylinder = placed['band']['cylinder']
    axis = np.asarray(cylinder['axis'])
    assert placed['placement_shape'] == 'belt-cylinder' and placed['valid'], placed['issues']
    assert cylinder['axis_source'] == 'frame-normal'
    assert np.allclose(axis, [0.0, 0.0, 1.0]), 'the axis is the membrane normal, not the bundle direction'
    assert cylinder['atom_count'] == len(points)
    cloud = np.asarray(points, dtype=float)
    relative = cloud - cloud.mean(axis=0)
    radial = relative - np.outer(relative[:, 2], [0.0, 0.0, 1.0])
    assert cylinder['radius_nm'] == pytest.approx(float(np.linalg.norm(radial, axis=1).max()), abs=1e-5)
    assert cylinder['surface_radius_nm'] == pytest.approx(1.0), 'the floor only pushes the surface outwards'
    assert cylinder['height_nm'] == pytest.approx(max(2.0 * 0.65, 2.0), abs=1e-6)
    assert cylinder['frame_axis'] == [0.0, 0.0, 1.0]


def test_the_stamped_head_stands_outside_the_surface_and_its_tail_is_closer_to_the_axis(tmp_path):
    """Acceptance (b)'s body: every stamped head is outside the measured radius and every tail nearer the axis."""
    points = _asymmetric_protein()
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(), radius_nm=1.0)
    atoms = pdc_build.stamp(DRAFT, placed['centers'], placed['directions'], first_residue=10)

    cylinder = placed['band']['cylinder']
    axis = np.asarray(cylinder['axis'])
    origin = np.asarray(cylinder['origin_nm'])
    molecules = {}
    for atom in atoms:
        molecules.setdefault(atom['residue_id'], []).append(atom)

    assert len(molecules) == 12
    for residue_id, beads in molecules.items():
        head = np.asarray([atom['position'] for atom in beads if atom['name'] == 'HEAD'])
        tail = np.asarray([atom['position'] for atom in beads if atom['name'] == 'TAIL1'])
        head_distance = float(distance_to_axis(head, axis, origin).max())
        tail_distance = float(distance_to_axis(tail, axis, origin).max())
        assert head_distance >= cylinder['radius_nm'], f'detergent {residue_id} has its head inside the surface'
        assert head_distance == pytest.approx(cylinder['surface_radius_nm'] + MOLECULE_LENGTH_NM,
                                              abs=SURFACE_TOLERANCE_NM)
        assert tail_distance < head_distance, f'detergent {residue_id} has its tail outside its head'


def test_every_direction_is_the_outward_normal_tilted_by_the_documented_angle(tmp_path):
    """Acceptance (b)'s direction: mostly the outward normal, tilted about the tangent by the named constant."""
    points = _asymmetric_protein()
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 24, seed=4, frame=_frame(), radius_nm=1.0)
    band = placed['band']
    axis = np.asarray(band['cylinder']['axis'])
    origin = np.asarray(band['cylinder']['origin_nm'])
    centres = np.asarray(placed['centers'])
    directions = np.asarray(placed['directions'])
    relative = centres - origin
    heights = relative @ axis
    radial = relative - np.outer(heights, axis)
    outward = radial / np.linalg.norm(radial, axis=1)[:, None]

    assert np.allclose(np.linalg.norm(directions, axis=1), 1.0)
    tilt = np.degrees(np.arccos(np.clip((directions * outward).sum(axis=1), -1.0, 1.0)))
    assert np.allclose(tilt, pdc_placement.TILT_DEGREES, atol=1e-9), 'the tilt is the documented constant'
    axial_component = directions @ axis
    assert np.allclose(axial_component, np.sign(heights) * np.sin(np.deg2rad(pdc_placement.TILT_DEGREES)),
                       atol=1e-9), 'the head leans away from the mid-plane, so the tail dips towards it'
    assert not np.allclose(directions, outward), 'the body is not the old pure-radial heading'


def test_the_cylinder_is_seeded_and_keeps_no_two_sites_closer_than_the_overlap_gate(tmp_path):
    points = _ring(2.0, 0.3)
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 40, seed=11, frame=_frame(), radius_nm=2.0)
    again = pdc_placement.place_detergents(points, _template(tmp_path), 40, seed=11, frame=_frame(), radius_nm=2.0)
    other = pdc_placement.place_detergents(points, _template(tmp_path), 40, seed=12, frame=_frame(), radius_nm=2.0)

    centres = np.asarray(placed['centers'])
    separations = np.linalg.norm(centres[:, None, :] - centres[None, :, :], axis=2)
    np.fill_diagonal(separations, np.inf)

    assert placed['valid'], placed['issues']
    assert len(centres) == 40, 'the requested count is the count that is placed'
    assert placed['centers'] == again['centers'], 'the seed decides the cylinder too'
    assert other['centers'] != placed['centers'], 'a different seed must place differently'
    assert separations.min() >= pdc_placement.MIN_DISTANCE_NM


def test_the_cylinders_sites_keep_the_ladders_own_slots_and_only_nudge_locally(tmp_path):
    """The shape changes; the arrangement does not. Each site is one ladder slot, nudged at most locally.

    The ladder is drawn once for the seed. A slot whose first trial fails its gates tries the module's bounded local
    offsets and is otherwise left empty -- the next ladder phase is never used, so the belt keeps the golden-angle
    arrangement's even spacing instead of clustering wherever a later pass found room. Every placed site is therefore
    within the documented trial bounds of a *distinct* ladder slot, and every slot is claimed at most once.
    """
    seed = 20261013
    points = _ring(1.5, 0.3)
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 24, seed=seed, frame=_frame(),
                                            radius_nm=1.5)
    band = placed['band']
    axis = np.asarray(band['cylinder']['axis'])
    origin = np.asarray(band['cylinder']['origin_nm'])
    relative = np.asarray(placed['centers']) - origin
    heights = relative @ axis
    radial = relative - np.outer(heights, axis)
    outward = radial / np.linalg.norm(radial, axis=1)[:, None]
    across, up = pdc_placement._plane_basis(axis)
    azimuths = np.arctan2(outward @ up, outward @ across)

    slots = [(float(np.arctan2(row[1], row[0])),
              float(np.sin(0.5 * np.pi * row[2]) * band['vertical_half_band_nm']))
             for row in golden_angle_directions(24, seed)]
    max_heading = np.deg2rad(max(abs(value) for value in pdc_placement.BELT_TRIAL_HEADING_DEG))
    max_height = max(abs(value) for value in pdc_placement.BELT_TRIAL_HEIGHT_NM)

    assert placed['valid'], placed['issues']
    assert len(placed['centers']) == 24 and band['passes'] == 1
    claimed = set()
    for azimuth, height in zip(azimuths, heights):
        matches = [index for index, (heading, value) in enumerate(slots)
                   if abs((heading - azimuth + np.pi) % (2 * np.pi) - np.pi) <= max_heading + 1e-9
                   and abs(value - height) <= max_height + 1e-9]
        assert matches, 'a site is not within the documented local offsets of any ladder slot'
        assert not claimed.intersection(matches), 'two sites claim one ladder slot'
        claimed.update(matches)
    assert len(claimed) == 24, "every slot is the ladder's own, and none is a later phase's"


def test_the_belt_covers_the_spread_vertical_band_and_wraps_the_cylinder(tmp_path):
    """Acceptance (c): the vertical spread is 1.5x the torus's own band, symmetric about the mid-plane.

    The old belt's head heights spanned `2 * length * sin(pi/2 * z)` for the ladder's maximum |z|; scaling each
    height by `VERTICAL_SPREAD` instead of `1` makes the new spread exactly 1.5x the old one. The azimuths still wrap
    the whole circumference, so the same count covers the taller band all the way round.
    """
    points = _ring(1.5, 0.3)
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 40, seed=7, frame=_frame(), radius_nm=1.5)
    band = placed['band']
    axis = np.asarray(band['cylinder']['axis'])
    origin = np.asarray(band['cylinder']['origin_nm'])
    relative = np.asarray(placed['centers']) - origin
    heights = relative @ axis
    radial = relative - np.outer(heights, axis)
    outward = radial / np.linalg.norm(radial, axis=1)[:, None]
    across, up = pdc_placement._plane_basis(axis)
    azimuths = np.arctan2(outward @ up, outward @ across)

    assert len(placed['centers']) == 40, 'the requested count is the count that covers the taller band'
    zmax = float(np.max(golden_angle_directions(40, 7)[:, 2]))
    old_spread = 2.0 * MOLECULE_LENGTH_NM * float(np.sin(0.5 * np.pi * zmax))
    new_spread = float(heights.max() - heights.min())
    assert new_spread == pytest.approx(pdc_placement.VERTICAL_SPREAD * old_spread, rel=1e-9)
    assert band['vertical_half_band_nm'] == pytest.approx(pdc_placement.VERTICAL_SPREAD * MOLECULE_LENGTH_NM)
    assert heights.max() > 0.9 * band['vertical_half_band_nm']
    assert heights.min() < -0.9 * band['vertical_half_band_nm']

    ordered = np.sort((azimuths + 2.0 * np.pi) % (2.0 * np.pi))
    gaps = np.diff(np.append(ordered, ordered[0] + 2.0 * np.pi))
    assert gaps.max() < 4.0 * (2.0 * np.pi / 40), 'the azimuths wrap the belt rather than one arc of it'


def test_a_request_the_cylinder_cannot_hold_fails_the_count_gate_rather_than_being_nudged(tmp_path):
    """The refusal path: what the shape cannot hold is reported, and the slots that fail stay empty.

    A solid transmembrane cloud of radius 2.4 nm, and a count of 600 over the vertical band a 0.4 nm molecule's
    spread covers. The bounded local trials move every slot that can be moved, but they cannot manufacture room for a
    count the ladder's own slots do not fit, so the draw ends with fewer sites than asked and the count gate says so.
    Every empty slot is recorded with its own base geometry and the gate it failed; no fabricated list is returned.
    """
    points = [point for z in np.linspace(-0.9, 0.9, 5) for point in _ring(2.4, float(z), count=180)]
    placed = pdc_placement.place_detergents(points, _template(tmp_path, length_nm=0.4), 600, seed=4,
                                            frame=_frame(), radius_nm=2.4, measure_capacity=False)
    band = placed['band']

    assert not placed['valid']
    assert any(issue.startswith('aggregation count') for issue in placed['issues']), placed['issues']
    assert len(placed['centers']) < 600, 'the slots the gates refused are left empty'
    assert band['rejected'] == len(band['rejected_slots']) > 0
    assert band['detergents_drawn'] == band['rejected'] + len(placed['centers'])
    assert band['passes'] == 1, 'the ladder is drawn once'
    for slot in band['rejected_slots']:
        assert set(slot) == {'position_nm', 'normal_nm', 'heading_rad', 'height_nm', 'reason', 'gate_nm'}
        assert slot['reason'] in ('head-clearance', 'body-clearance', 'site-spacing', 'body-gap')
        assert np.isfinite(slot['position_nm'] + slot['normal_nm'] + [slot['gate_nm']]).all()
    # The count sentence is the empty-slot marks' detail, verbatim; the rings come first.
    count_issue = next(issue for issue in placed['issues'] if issue.startswith('aggregation count'))
    empty = [mark for mark in placed['problems'] if mark['kind'] == 'empty-slot']
    assert empty and placed['problems'][:len(empty)] == empty
    assert all(mark['detail'] == count_issue and mark['molecule'] is None for mark in empty)


@pytest.mark.parametrize(('points', 'length_nm', 'reason'), [
    pytest.param(_asymmetric_protein(), None, 'length', id='molecule-with-no-measurable-length'),
    pytest.param(_ring(1.0, 3.0) + _ring(5.0, 3.0), MOLECULE_LENGTH_NM, 'slab holds no atom',
                 id='protein-outside-the-stated-slab'),
])
def test_a_stated_membrane_the_placement_cannot_measure_keeps_the_sphere(tmp_path, points, length_nm, reason):
    """No length, no cylinder; no atom in the slab, no measurement: the sphere is kept and `belt_reason` says which.

    A molecule nobody measured is not a stand-off to build a belt from, and a guessed cylinder is not one either.
    """
    placed = pdc_placement.place_detergents(points, _template(tmp_path, length_nm=length_nm), 8, seed=3,
                                            frame=_frame())

    assert placed['placement_shape'] == 'sphere' and placed['band'] is None
    assert reason in placed['belt_reason']


def test_a_protein_that_states_no_membrane_gets_a_shell_measured_from_it(tmp_path):
    """`frame=None` is every packaged protein and every import that states nothing: the sphere, now measured.

    The radius used to *be* the setting -- the same 3.0 nm about every protein, whatever the selection reached. It is
    now the greater of the setting and `extent about the centroid + the clearance + the molecule's own length`, the
    relationship the belt's measured cylinder already had: the protein decides and the setting is only a floor. This protein
    reaches 5.0 nm from its own centroid, so the measured shell is 5.0 + 0.5 + 2.0 = 7.5 nm and the old 3.0 nm shell
    would have put every site inside it.
    """
    points = _asymmetric_protein()
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4)

    centres = np.asarray(placed['centers'])
    centroid = np.asarray(points).mean(axis=0)
    extent = pdc_placement.extent_about_centroid(points)
    shell = placed['shell']

    assert placed['placement_shape'] == 'sphere' and placed['band'] is None and placed['frame'] is None
    assert shell['radius_source'] == 'measured', 'the protein reached further than the setting'
    assert shell['measured_extent_nm'] == pytest.approx(extent)
    assert shell['radius_nm'] == pytest.approx(extent + pdc_placement.MIN_CLEARANCE_NM + MOLECULE_LENGTH_NM)
    assert np.allclose(np.linalg.norm(centres - centroid, axis=1), shell['radius_nm']), \
        'every site is on the shell the record states'
    assert placed['radius_nm'] == shell['radius_nm'] and placed['radius_floor_nm'] == pdc_placement.DEFAULT_RADIUS_NM
    assert np.all(np.linalg.norm(centres - centroid, axis=1) > pdc_placement.DEFAULT_RADIUS_NM), \
        'the old fixed shell is what this replaces'


def test_a_sphere_whose_protein_is_smaller_than_the_setting_keeps_the_setting_as_its_radius(tmp_path):
    """The other half of the rule: a shell the setting already clears is the setting's, and says so."""
    points = [[0.0, 0.0, 0.0], [0.2, 0.0, 0.0]]
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, radius_nm=4.0)

    assert placed['shell']['radius_nm'] == pytest.approx(4.0)
    assert placed['shell']['radius_source'] == 'floor'
    assert placed['shell']['measured_shell_nm'] < 4.0
    assert np.allclose(np.linalg.norm(np.asarray(placed['centers']) - np.asarray(points).mean(axis=0), axis=1), 4.0)


def test_an_empty_micelle_is_the_same_sphere_with_a_frame_as_without_one(tmp_path):
    """The user's decision: no protein, a simple sphere -- and a frame handed over with it changes nothing."""
    template = _template(tmp_path)
    without = pdc_placement.place_detergents(None, template, 8, seed=3)
    stated = pdc_placement.place_detergents(None, template, 8, seed=3, frame=_frame())

    assert stated['centers'] == without['centers'] and stated['directions'] == without['directions']
    assert stated['placement_shape'] == 'sphere' and stated['protein_free']
    assert np.allclose(np.linalg.norm(np.asarray(stated['centers']), axis=1), pdc_placement.DEFAULT_RADIUS_NM)


def test_a_cylinder_faces_the_way_the_frame_states_rather_than_the_way_z_does(tmp_path):
    """A y-facing bilayer is the case a reader that indexed z would place every detergent outside of."""
    axis = np.array([0.0, 1.0, 0.0])
    points = [[2.0 * np.cos(a), 0.2, 2.0 * np.sin(a)] for a in np.linspace(0.0, 2.0 * np.pi, 12, endpoint=False)]
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(axis=tuple(axis)),
                                            radius_nm=2.0)

    cylinder = placed['band']['cylinder']
    centres = np.asarray(placed['centers'])
    distances = distance_to_axis(centres, np.asarray(cylinder['axis']), np.asarray(cylinder['origin_nm']))

    assert placed['placement_shape'] == 'belt-cylinder' and placed['valid'], placed['issues']
    assert np.allclose(np.asarray(cylinder['axis']), axis), 'the cylinder faces the frame, not z'
    assert np.allclose(distances, cylinder['surface_radius_nm'] + MOLECULE_LENGTH_NM, atol=1e-9), \
        "the lateral surface is measured perpendicular to the frame's own axis, not z"


# --- `radius_nm` as a floor on a protein build ---------------------------------------------------------------

def test_a_radius_larger_than_the_measured_cylinder_lifts_the_surface_to_it(tmp_path):
    """The setting may push a belt out; it can never shrink it below what the protein was measured to need."""
    points = _asymmetric_protein()          # a 1.0 nm in-slab radius, so the cylinder measures 1.0 nm
    measured = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(),
                                              belt_floor_nm=0.75)
    lifted = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(),
                                            belt_floor_nm=2.5)

    assert measured['band']['radius_nm'] == 1.0, 'a setting below the measurement leaves the surface alone'
    assert lifted['band']['radius_nm'] == 2.5, 'a setting above it sets the surface'
    assert lifted['band']['cylinder']['radius_nm'] == 1.0, 'the measured cylinder is still recorded'
    assert lifted['band']['slab_radius_nm'] == 1.0, 'and the old frame-axis measurement beside it'
    assert lifted['band']['radius_source'] == 'floor' and measured['band']['radius_source'] == 'measured'
    assert lifted['band']['detergent_length_nm'] == MOLECULE_LENGTH_NM, 'the setting is not the stand-off'


def test_a_radius_smaller_than_the_measured_cylinder_changes_nothing(tmp_path):
    points = _asymmetric_protein()
    smaller = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(), radius_nm=0.75)
    measured = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(), radius_nm=1.0)

    assert smaller['centers'] == measured['centers'], 'the floor is the measured cylinder, not the setting'
    assert smaller['band']['radius_nm'] == measured['band']['radius_nm'] == 1.0


def test_the_belt_gap_moves_the_surface_out_by_exactly_the_gap(tmp_path):
    """The belt-protein gap is extra stand-off on the measured surface: 0 is today's geometry, and a positive gap
    moves every head site out by the gap and records it. The sphere keeps the radius it always had, so a protein that
    states no membrane is untouched by the setting."""
    points = _asymmetric_protein()          # a 1.0 nm in-slab radius, so the cylinder measures 1.0 nm
    template = _template(tmp_path)
    unstated = pdc_placement.place_detergents(points, template, 12, seed=4, frame=_frame(), radius_nm=1.0,
                                              belt_gap_nm=0.0)
    gapped = pdc_placement.place_detergents(points, template, 12, seed=4, frame=_frame(), radius_nm=1.0,
                                            belt_gap_nm=1.5)
    sphere = pdc_placement.place_detergents(points, template, 12, seed=4, radius_nm=3.0)
    sphere_gapped = pdc_placement.place_detergents(points, template, 12, seed=4, radius_nm=3.0, belt_gap_nm=1.5)

    assert unstated['valid'] and gapped['valid'], gapped['issues']
    assert unstated['band']['radius_nm'] == 1.0 and unstated['band']['gap_nm'] == 0.0
    assert unstated['band']['cylinder']['radius_nm'] == 1.0, 'the measured cylinder itself never moves'
    assert gapped['band']['gap_nm'] == 1.5
    assert gapped['band']['radius_nm'] == pytest.approx(2.5), 'the surface is measured radius plus the gap'
    assert gapped['band']['cylinder']['surface_radius_nm'] == pytest.approx(2.5)
    assert gapped['band']['radius_nm'] - unstated['band']['radius_nm'] == pytest.approx(1.5), \
        'the difference is exactly the gap'
    assert np.allclose(distance_to_axis(gapped['centers'], gapped['band']['cylinder']['axis'],
                                        gapped['band']['cylinder']['origin_nm']),
                       gapped['band']['radius_nm'] + MOLECULE_LENGTH_NM, atol=1e-9)
    assert sphere['centers'] == sphere_gapped['centers'], 'the sphere never reads the gap'
    assert sphere_gapped['band'] is None
    with pytest.raises(ValueError, match='gap cannot be negative'):
        pdc_placement.place_detergents(points, template, 12, seed=4, frame=_frame(), belt_gap_nm=-0.5)
    with pytest.raises(ValueError, match='gap cannot be negative'):
        pdc_placement.capacity(points, template, 12, frame=_frame(), belt_gap_nm=-0.5)


def test_an_empty_micelle_still_uses_the_radius_as_the_sphere_it_builds(tmp_path):
    """No protein, no measured cylinder: `radius_nm` is the sphere's own radius, exactly as it was before any floor."""
    placed = pdc_placement.place_detergents(None, None, 8, seed=3, radius_nm=2.0, frame=_frame())

    assert placed['placement_shape'] == 'sphere' and placed['band'] is None
    assert np.allclose(np.linalg.norm(np.asarray(placed['centers']), axis=1), 2.0)


def test_an_empty_micelles_sphere_is_the_placement_it_always_was(tmp_path):
    """The correction's own boundary: a build with no protein keeps the sphere, to the digit.

    Pinned as coordinates rather than as a radius, because "unchanged" is a claim about the placement this module
    hands over: the same seed places the same shell about the origin, whatever shape a protein build now takes.
    """
    placed = pdc_placement.place_detergents(None, None, 8, seed=3, radius_nm=3.0)

    assert placed['placement_shape'] == 'sphere' and placed['band'] is None and placed['belt_reason'] is None
    assert placed['centers'] == [
        [-0.24189934527559237, 1.432082297479876, 2.625], [-1.2722059611942003, -1.9661808137355883, 1.875],
        [2.6912331733009767, 0.7011697418773536, 1.125], [-2.630766376365014, 1.3922798831367538, 0.375],
        [0.9993737034719876, -2.80368100910369, -0.375], [1.0810020126549018, 2.5623835873334913, -1.125],
        [-2.1287349151170436, -0.9761468440565864, -1.875], [1.3823922929595351, -0.4453835968758607, -2.625]]


def test_the_spheres_sites_are_its_shell_and_the_stamped_heads_stand_on_it(tmp_path):
    """The anchor `stamp` uses is one convention for both shapes: the site names the detergent's head end.

    On the sphere the sites are the shell itself, so the heads end up on the shell and the tails inside it -- the
    same relationship the tube's sites have to its outer surface. The *placement* is untouched (the pinned shell
    above); what this pins is where the molecule's own beads land relative to it.
    """
    placed = pdc_placement.place_detergents(None, None, 4, seed=3, radius_nm=3.0)
    atoms = pdc_build.stamp(DRAFT, placed['centers'], placed['directions'], first_residue=10)

    molecules = {}
    for atom in atoms:
        molecules.setdefault(atom['residue_id'], []).append(atom)

    assert len(molecules) == 4
    for site, (residue_id, beads) in zip(placed['centers'], molecules.items()):
        head = np.asarray([atom['position'] for atom in beads if atom['name'] == 'HEAD'][0])
        tail = np.asarray([atom['position'] for atom in beads if atom['name'] == 'TAIL1'][0])
        assert np.allclose(head, site, atol=SURFACE_TOLERANCE_NM), 'the head end stands at the site it was given'
        assert np.linalg.norm(tail) < np.linalg.norm(head), 'and the tail beads sit inside the shell'


# --- the clearance is the detergent's own body, not its head site -------------------------------------------

#: A molecule that reaches 3 nm from its head end along its own axis: three atoms, at the head and 1 and 3 nm back.
#: The clearance the placement has always measured knows only where the head is, so a 3 nm tail is invisible to it.
TAIL_3NM_POINTS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
#: The molecule's own beads, expanded through the module's own function -- the same body `pdc_build.stamp` writes.
def molecule_beads(site, direction, template):
    return pdc_placement.body_beads(site, direction, pdc_placement.detergent_profile(template))


def atom_records(points, residue='DDM'):
    """A molecule's own coordinate file: one `HETATM` per bead, in a PDB's Angstrom columns."""
    return ''.join(f'HETATM{index:5d}  C{index}  {residue} A   1   '
                   f'{x * 10:8.3f}{y * 10:8.3f}{z * 10:8.3f}  1.00  0.00\n'
                   for index, (x, y, z) in enumerate(points, 1))


def shaped_template(directory, points, *, residue='DDM'):
    """A template whose molecule is the beads `points`, loaded the way the builders load one."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'molecule.pdb').write_text(atom_records(points, residue))
    (directory / 'molecule.itp').write_text('')
    path = directory / 'micelle_template.json'
    path.write_text(json.dumps({'name': residue, 'residue': residue, 'beads': [{'name': 'B1'}],
                                'coordinates': 'molecule.pdb', 'topology': 'molecule.itp',
                                'tail_direction': [0, 0, -1]}))
    return load_template(path)


def protein_bead_clearance(placed, template, protein):
    """The closest any placed detergent's own bead comes to any protein point, over the whole placement."""
    protein = np.asarray(protein, dtype=float)
    return min(float(np.linalg.norm(bead - protein, axis=1).min())
               for site, direction in zip(placed['centers'], placed['directions'])
               for bead in molecule_beads(site, direction, template))


def test_no_detergent_bead_lands_inside_the_protein(tmp_path):
    """Task 1's acceptance: the protein is two points 0.5 nm apart and the molecule reaches 3 nm past its head.

    A head site 0.5 nm from either point passes the clearance this module has always measured -- and the tail then
    runs straight through the pair, which is the clash the preview showed. Every bead is measured now.
    """
    template = shaped_template(tmp_path, TAIL_3NM_POINTS)
    protein = [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]]

    placed = pdc_placement.place_detergents(protein, template, 6, seed=7, mode='self-assembly')

    assert placed['valid'], placed['issues']
    assert len(placed['centers']) == 6
    for site, direction in zip(placed['centers'], placed['directions']):
        beads = molecule_beads(site, direction, template)
        assert len(beads) == 3
        assert min(np.linalg.norm(bead - np.asarray(protein), axis=1).min() for bead in beads) >= \
            pdc_placement.BEAD_CLEARANCE_NM
    assert placed['bead_clearance_nm'] >= pdc_placement.BEAD_CLEARANCE_NM
    assert placed['body_profile']['bead_count'] == 3, 'the gate measured the molecule, and the record says so'


def test_the_body_gate_refuses_more_draws_than_the_head_gate_alone_would(tmp_path):
    """The gate is doing the work, not the size of the box: a 3 nm molecule is refused where its head would pass.

    The same protein, placed with a molecule that states no coordinates at all, keeps the head-only gate and reports
    it (`body_profile: None` with a reason) -- so a placement never claims a check it did not run.
    """
    template = shaped_template(tmp_path, TAIL_3NM_POINTS)
    protein = [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]]

    placed = pdc_placement.place_detergents(protein, template, 6, seed=7, mode='self-assembly')

    assert placed['body_profile_reason'] is None
    assert protein_bead_clearance(placed, template, protein) >= pdc_placement.BEAD_CLEARANCE_NM
    # The measured bead gap is smaller than the head clearance on at least one detergent: the body is inside the
    # head gate's own 0.5 nm sphere of influence, and only the bead-level measurement could have refused it there.
    assert placed['bead_clearance_nm'] < placed['protein_clearance_nm']


def test_a_molecule_that_states_no_coordinates_keeps_the_head_only_gate_and_says_so(tmp_path):
    """No coordinates, no profile: the template is not silently given a length and the record carries the reason."""
    template = _template(tmp_path, length_nm=None)
    placed = pdc_placement.place_detergents(PROTEIN, template, 8, seed=3, mode='self-assembly')

    assert placed['valid'], placed['issues']
    assert placed['body_profile'] is None
    assert 'no coordinates' in placed['body_profile_reason']
    assert placed['bead_clearance_nm'] is None, 'nothing was measured, so no number is reported'


def test_no_detergent_bead_lands_inside_a_protein_the_cylinder_wraps(tmp_path):
    """The same gate on the belt: a ring inside the cylinder's own volume, where only a body can reach it.

    The in-slab rings set the measured cylinder (3.0 nm) and the molecule's own length is 2.0 nm, so the heads stand
    at 5.0 nm and every tail reaches back to about 3.07 nm. The 3.0 nm ring sits on that path: a head site is two
    nanometres clear of it, and the tail is what comes within the bead gate.
    """
    template = _template(tmp_path)                       # two atoms, 2.0 nm apart
    points = _ring(2.0, 0.0) + _ring(3.0, 0.0, count=12)

    placed = pdc_placement.place_detergents(points, template, 12, seed=4, frame=_frame(), radius_nm=2.0)

    assert placed['valid'], placed['issues']
    assert placed['placement_shape'] == 'belt-cylinder'
    assert placed['protein_clearance_nm'] >= pdc_placement.MIN_CLEARANCE_NM
    assert protein_bead_clearance(placed, template, points) >= pdc_placement.BEAD_CLEARANCE_NM
    assert placed['bead_clearance_nm'] < placed['protein_clearance_nm'], \
        'the bodies reach past the heads, and it is the bodies the protein is near'


def test_a_sphere_keeps_every_bead_clear_by_construction(tmp_path):
    """The shell's own guarantee: radius = extent + clearance + reach, so no bead can reach the protein."""
    template = shaped_template(tmp_path, TAIL_3NM_POINTS)
    points = np.asarray(_asymmetric_protein())

    placed = pdc_placement.place_detergents(points, template, 16, seed=5, mode='lattice')

    assert placed['valid'], placed['issues']
    assert protein_bead_clearance(placed, template, points) >= pdc_placement.MIN_CLEARANCE_NM, \
        'the measured shell clears the protein by the head clearance, so the body does too'


# --- orientations are drawn ----------------------------------------------------------------------------------


def test_self_assembled_orientations_are_not_all_one_direction(tmp_path):
    """Task 2's acceptance: a cloud's directions span the sphere instead of sharing one radial."""
    template = _template(tmp_path)
    placed = pdc_placement.place_detergents(_asymmetric_protein(), template, 8, seed=11, mode='self-assembly')

    unit = np.asarray(placed['directions']) / np.linalg.norm(placed['directions'], axis=1)[:, None]
    angles = [np.degrees(np.arccos(np.clip(unit[i] @ unit[j], -1.0, 1.0)))
              for i in range(len(unit)) for j in range(i)]
    assert len(unit) == 8
    assert max(angles) > 20, 'orientations are all radial'


def test_a_self_assembled_head_faces_away_from_the_nearest_protein_bead(tmp_path):
    """Drawn, then *flipped* -- the one transformation allowed after the draw, and it only swaps the axis's ends."""
    template = _template(tmp_path)
    protein = np.asarray(_asymmetric_protein())
    placed = pdc_placement.place_detergents(protein, template, 10, seed=12, mode='self-assembly')

    for site, direction in zip(np.asarray(placed['centers']), np.asarray(placed['directions'])):
        nearest = protein[int(np.argmin(np.linalg.norm(protein - site, axis=1)))]
        assert float(np.dot(direction, site - nearest)) >= 0, 'the head is aimed at the protein'


def test_the_drawn_orientations_are_the_seeds_own(tmp_path):
    """One generator, one draw order: the same seed rebuilds the same directions, a different one does not."""
    template = _template(tmp_path)
    first = pdc_placement.place_detergents(_asymmetric_protein(), template, 10, seed=21, mode='self-assembly')
    again = pdc_placement.place_detergents(_asymmetric_protein(), template, 10, seed=21, mode='self-assembly')
    other = pdc_placement.place_detergents(_asymmetric_protein(), template, 10, seed=22, mode='self-assembly')

    assert first['directions'] == again['directions']
    assert first['directions'] != other['directions']


def test_the_record_says_which_orientation_policy_built_the_cloud(tmp_path):
    """A report has to tell a drawn cloud from a lattice without inspecting vectors."""
    template = _template(tmp_path)
    drawn = pdc_placement.place_detergents(PROTEIN, template, 8, seed=3, mode='self-assembly')
    lattice = pdc_placement.place_detergents(PROTEIN, template, 8, seed=3, mode='lattice')

    assert drawn['orientation_policy'] == 'random-outward'
    assert lattice['orientation_policy'] == 'radial'


# --- the shell is sized by the subunits the run includes -----------------------------------------------------


def _rod(half=False, radius=1.0):
    """A protein shaped like a rod along x: a tube of points 12 nm long, or the 6 nm of its first half."""
    ends = (-6.0, 0.0) if half else (-6.0, 6.0)
    points = []
    for x in np.linspace(*ends, 7):
        for angle in np.linspace(0.0, 2.0 * np.pi, 12, endpoint=False):
            points.append([float(x), radius * float(np.cos(angle)), radius * float(np.sin(angle))])
    return points


def test_the_shell_follows_the_selected_subunits(tmp_path):
    """Task 3's acceptance: half the protein gets a smaller shell, a smaller box, and says the measurement decided."""
    template = shaped_template(tmp_path, [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])
    whole_rod, half_rod = _rod(), _rod(half=True)

    whole = pdc_placement.place_detergents(whole_rod, template, 40, seed=3, mode='lattice')
    half = pdc_placement.place_detergents(half_rod, template, 40, seed=3, mode='lattice')

    assert whole['valid'] and half['valid'], (whole['issues'], half['issues'])
    assert half['shell']['radius_nm'] < whole['shell']['radius_nm'] * 0.75
    assert half['shell']['radius_source'] == 'measured' and whole['shell']['radius_source'] == 'measured'
    # The box the build derives from the same points follows the selection too -- `pdc_box.initial_box` is measured
    # from the coordinates handed in, so a smaller selection is a smaller box.
    assert initial_box(half_rod)[0] < initial_box(whole_rod)[0]


def test_the_radius_setting_is_the_floor_the_shell_is_measured_over(tmp_path):
    """Both numbers are in the record, and `radius_source` says which of them decided."""
    template = shaped_template(tmp_path, [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])

    lifted = pdc_placement.place_detergents(_rod(half=True), template, 24, seed=3, radius_nm=12.0)

    assert lifted['shell']['radius_nm'] == pytest.approx(12.0)
    assert lifted['shell']['radius_source'] == 'floor'
    assert lifted['shell']['radius_floor_nm'] == 12.0
    assert lifted['shell']['measured_shell_nm'] < 12.0, 'the measurement is kept, even when it lost'
    assert lifted['radius_nm'] == 12.0


def test_the_shell_reports_its_density_rather_than_scaling_the_count(tmp_path):
    """The count stays the user's; the crowding is reported so a tight shell can be read as tight."""
    template = shaped_template(tmp_path, [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])
    placed = pdc_placement.place_detergents(_rod(half=True), template, 24, seed=3, mode='lattice')

    shell = placed['shell']
    volume = 4.0 / 3.0 * np.pi * shell['radius_nm'] ** 3
    assert placed['aggregation_number'] == 24 and len(placed['centers']) == 24
    assert shell['volume_nm3'] == pytest.approx(volume, rel=1e-6)
    assert shell['estimated_density_per_nm3'] == pytest.approx(24 / volume, rel=1e-5)
    assert shell['capacity_nm3_per_detergent'] == pytest.approx(volume / 24, rel=1e-5)


def test_the_belt_reports_its_own_density_the_same_way(tmp_path):
    """A cylindrical shell's volume is its own, so the panel's density sentence reads the same field for either shape."""
    placed = pdc_placement.place_detergents(_asymmetric_protein(), _template(tmp_path), 12, seed=4, frame=_frame(),
                                            radius_nm=1.0)

    band = placed['band']
    inner = band['radius_nm']
    outer = inner + band['detergent_length_nm']
    volume = np.pi * (outer ** 2 - inner ** 2) * 2.0 * band['vertical_half_band_nm']
    assert band['volume_nm3'] == pytest.approx(volume, rel=1e-6)
    assert band['estimated_density_per_nm3'] == pytest.approx(12 / volume, rel=1e-5)
    assert placed['shell'] is None, 'a belt is not a sphere, so the sphere record is not written'


# --- capacity: the number the user asked for never changes ------------------------------------------------


def _short_molecule(tmp_path):
    """A molecule 0.2 nm long, so a small protein cannot enlarge the shell by much."""
    return shaped_template(tmp_path, [(0.0, 0.0, 0.0), (0.2, 0.0, 0.0)])


def test_a_shell_too_small_reports_the_count_it_could_hold(tmp_path):
    """Task 5's acceptance: a refusal measures what the shape holds, on every seed it reports."""
    template = _short_molecule(tmp_path)
    small_region = [[0.0, 0.0, 0.0]]

    placed = pdc_placement.place_detergents(small_region, template, 150, seed=5, mode='lattice', radius_nm=0.5)

    assert not placed['valid']
    measurement = placed['capacity_aggregation']
    assert 0 < measurement['count'] < 150
    assert measurement['requested'] == 150 and measurement['seeds'] == [1, 2, 3]
    for seed in measurement['seeds']:
        assert pdc_placement.place_detergents(small_region, template, measurement['count'], seed=seed,
                                              mode='lattice', radius_nm=0.5)['valid']
    assert any('the shell holds about' in issue for issue in placed['issues']), placed['issues']
    assert f'{measurement["count"]}' in [issue for issue in placed['issues'] if 'shell holds' in issue][0]


def test_one_more_than_the_capacity_is_refused(tmp_path):
    """The measurement is a boundary and not a slogan: the count above it fails the gate it was measured over."""
    template = _short_molecule(tmp_path)
    small_region = [[0.0, 0.0, 0.0]]
    measurement = pdc_placement.place_detergents(small_region, template, 150, seed=5, mode='lattice',
                                                radius_nm=0.5)['capacity_aggregation']

    over = pdc_placement.place_detergents(small_region, template, measurement['count'] + 1, seed=1, mode='lattice',
                                          radius_nm=0.5)

    assert not over['valid'], 'a shell that holds N must refuse N + 1 on the seed that was measured'


def test_a_shell_that_holds_the_full_count_reports_no_capacity(tmp_path):
    """A succeeded placement has nothing to report, so the field is `None` and no clause is added."""
    template = _short_molecule(tmp_path)
    placed = pdc_placement.place_detergents([[0.0, 0.0, 0.0]], template, 8, seed=5, mode='lattice', radius_nm=1.0)

    assert placed['valid'], placed['issues']
    assert placed['capacity_aggregation'] is None
    assert not any('shell holds' in issue for issue in placed['issues'])


def test_the_capacity_measurement_does_not_measure_itself(tmp_path):
    """`measure_capacity=False` is the inner call: the bisection's own placements report nothing."""
    template = _short_molecule(tmp_path)
    placed = pdc_placement.place_detergents([[0.0, 0.0, 0.0]], template, 150, seed=5, mode='lattice',
                                            radius_nm=0.5, measure_capacity=False)

    assert not placed['valid'] and placed['capacity_aggregation'] is None


def test_the_capacity_is_the_placers_own_measurement_not_a_formula(tmp_path):
    """It is `place_detergents` at the top of it: no second geometry, and the same number for a direct call."""
    template = _short_molecule(tmp_path)
    small_region = [[0.0, 0.0, 0.0]]

    measured = pdc_placement.capacity(small_region, template, 150, mode='lattice', radius_nm=0.5)
    placed = pdc_placement.place_detergents(small_region, template, 150, seed=5, mode='lattice', radius_nm=0.5)

    assert measured == placed['capacity_aggregation']



# --- a conformation library: the drawn body, its own stream, and the gate that measures it --------------------


#: The sha256 of the placement record `place_detergents(None, _template(tmp_path), 2, seed=7)` produced before a
#: conformation library existed, with the one new `conformations: None` key removed. This is every existing run's
#: geometry: if it changes, a placement's own numbers moved. It also pins the preview's additive
#: `problems`/`problems_truncated` keys (empty and zero here). Re-record it only when that is the intended change.
UNTROUBLED_PLACEMENT_SHA256 = '3ddc78958e373fed001029a20911c0c0747f63f7a4e292af57f17a15b63a56aa'


def drawn_profile(offsets):
    """One library entry's profile, in the shape the library's pinned API states: head at the origin, axis +z."""
    points = np.asarray(offsets, dtype=float)
    return {'offsets': points, 'axis': np.array([0.0, 0.0, 1.0]),
            'length_nm': float(-points[:, 2].min()), 'reach_nm': float(np.linalg.norm(points, axis=1).max()),
            'radial_nm': float(np.linalg.norm(points[:, :2], axis=1).max()), 'bead_count': int(len(points)),
            'source': 'conformations', 'head_source': 'library'}


class DrawnLibrary:
    """The library's pinned surface, duck-typed -- a key, a size and one profile per entry -- so placement is tested
    without the library package, which the placement must never import."""

    def __init__(self, entries, key='librarykey0123456', size=None):
        self.profiles = tuple(drawn_profile(entry) for entry in entries)
        self.key = key
        self.size = len(self.profiles) if size is None else size


def test_a_placement_with_no_library_is_the_placement_it_always_was(tmp_path):
    """`conformations=None` is every existing run: the same positions, directions and numbers, draw for draw.

    The record gains exactly one key -- `conformations: None` -- and the pinned digest is taken with that key removed,
    so this fails on any other change to a placement's own arithmetic.
    """
    template = _template(tmp_path)
    implicit = pdc_placement.place_detergents(None, template, 2, seed=7)
    explicit = pdc_placement.place_detergents(None, template, 2, seed=7, conformations=None)

    assert implicit == explicit
    assert implicit.pop('conformations') is None
    digest = hashlib.sha256(json.dumps(implicit, sort_keys=True).encode()).hexdigest()
    assert digest == UNTROUBLED_PLACEMENT_SHA256


def test_the_library_draw_is_its_own_stream_one_entry_and_one_azimuth_per_site(tmp_path):
    """A separate generator, in site order: the sites are the ones they would have been without a library."""
    template = _template(tmp_path)
    library = DrawnLibrary([[[0.0, 0.0, 0.0], [0.2, 0.0, -0.5]], [[0.0, 0.0, 0.0], [0.1, 0.0, -0.2]],
                            [[0.0, 0.0, 0.0], [0.0, 0.0, -0.4]]])
    placed = pdc_placement.place_detergents(None, template, 8, seed=11, conformations=library)
    plain = pdc_placement.place_detergents(None, template, 8, seed=11)

    rng = np.random.default_rng([11, pdc_placement.CONFORMATION_SEED])
    entries, twists = [], []
    for _ in range(8):
        entries.append(int(rng.integers(0, library.size)))
        twists.append(round(float(rng.uniform(0.0, 2.0 * np.pi)), 6))
    assert placed['conformations'] == {'key': library.key, 'size': library.size, 'entries': entries,
                                       'twists': twists}
    assert plain['conformations'] is None
    assert placed['centers'] == plain['centers'], 'the site generator draws did not move'
    assert placed['directions'] == plain['directions']
    again = pdc_placement.place_detergents(None, template, 8, seed=11, conformations=library)
    assert again['conformations'] == placed['conformations'], 'the same seed draws the same entries'
    other = pdc_placement.place_detergents(None, template, 8, seed=12, conformations=library)
    assert other['conformations'] != placed['conformations'], 'a different seed draws different entries'


def test_the_drawn_body_is_the_body_the_stamp_writes():
    """The gate and `stamp` are one arithmetic: `R @ Rz(twist) @ bead`, head anchor on the site."""
    offsets = np.array([[0.0, 0.0, 0.0], [0.4, 0.0, -0.6]])
    profile = drawn_profile(offsets)
    site, direction, twist = np.array([3.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]), 1.234

    measured = pdc_placement.body_beads(site, direction, profile, twist)
    atoms = pdc_build.stamp(DRAFT, [site], [direction], first_residue=0, entries=[offsets], twists=[twist])

    assert np.allclose(measured, [atom['position'] for atom in atoms], atol=1e-5)
    assert np.allclose(measured[0], site), 'the head anchor is the site'
    assert not np.allclose(pdc_placement.body_beads(site, direction, profile), measured), 'the azimuth turns the body'


def test_a_long_drawn_entry_fails_the_body_gate_where_a_short_one_passes(tmp_path):
    """The gate measures the drawn body: the same sites are clear with one library and refused with another.

    The template's own 2 nm body sizes the sphere and is what the gate measured before a library existed; the drawn
    3 nm entry reaches back to the protein at the shell's centre, which the template's body never did. The azimuth is
    a rotation about +z, so a bead's own z offset is what decides how far back it reaches.
    """
    template = _template(tmp_path)
    protein = [[0.0, 0.0, 0.0]]
    long_entry = [[[0.0, 0.0, 0.0], [0.0, 0.0, -3.0]]]
    short_entry = [[[0.0, 0.0, 0.0], [0.0, 0.0, -0.3]]]

    long_placed = pdc_placement.place_detergents(protein, template, 4, seed=7,
                                                 conformations=DrawnLibrary(long_entry))
    short_placed = pdc_placement.place_detergents(protein, template, 4, seed=7,
                                                  conformations=DrawnLibrary(short_entry))
    plain = pdc_placement.place_detergents(protein, template, 4, seed=7)

    assert not long_placed['valid'], 'a body that reaches the protein is refused'
    assert any('drawn detergent body' in issue for issue in long_placed['issues']), long_placed['issues']
    assert short_placed['valid'], short_placed['issues']
    assert short_placed['bead_clearance_nm'] == pytest.approx(3.0 - 0.3, abs=1e-6), \
        "the reported clearance is the drawn body's"
    assert plain['bead_clearance_nm'] != short_placed['bead_clearance_nm'], \
        'the template body and the library body are different measurements'
    assert short_placed['body_profile'] == plain['body_profile'], "body_profile stays the template's"


def test_a_local_helix_steps_only_its_own_arc_out_and_the_rest_hugs_the_bundle(tmp_path):
    """The belt follows the local protein surface, not the one furthest atom anywhere on the cylinder.

    The transmembrane ring measures 1.0 nm everywhere except a small arc, where three atoms reach 3.0 nm -- the
    protruding-helix case. A global maximum would put the whole belt on a 3.0 nm surface. The local surface must put
    the sites over the helix outside it and keep every other sector near the 1.0 nm bundle.
    """
    points = _ring(1.0, 0.0) + [[3.0, 0.0, 0.0], [2.9, 0.3, 0.0], [2.8, -0.3, 0.0]]
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame())

    assert placed['valid'], placed['issues']
    band = placed['band']
    assert band['radius_max_nm'] == pytest.approx(band['cylinder']['radius_nm'], abs=1e-6), \
        'the protrusion still sets its own arc'
    assert band['radius_min_nm'] < 1.0, 'an arc away from the protrusion hugs the bundle'
    assert band['radius_nm'] < band['cylinder']['radius_nm'] - 0.5, \
        'the mean local surface is not the global maximum'
    assert placed['protein_clearance_nm'] >= pdc_placement.MIN_CLEARANCE_NM


# --- the belt's own packing: a height-aware local surface and a body-body gap --------------------------------

#: A protrusion that is localized in **both** angle and height: two atoms at 3.0 nm at one axial side. An
#: angular-only local surface stands every site in its sector off at 3.0; a height-aware one lets the sites above and
#: below it see the 1.0 nm ring.
PROTRUSION_ANGLES_DEG = (-10.0, 10.0)
PROTRUSION_RADIUS_NM = 3.0
PROTRUSION_HEIGHT_NM = 1.2


def _axially_local_helix_protein():
    """A 1.0 nm ring at the mid-plane plus the two-atom protrusion at +1.2 nm."""
    points = _ring(1.0, 0.0, count=24)
    points += [[PROTRUSION_RADIUS_NM * float(np.cos(np.deg2rad(angle))),
                PROTRUSION_RADIUS_NM * float(np.sin(np.deg2rad(angle))),
                PROTRUSION_HEIGHT_NM] for angle in PROTRUSION_ANGLES_DEG]
    return points


def _belt_geometry(placed):
    """Each placed site's azimuth, height and radial distance from the cylinder the band records."""
    band = placed['band']
    axis = np.asarray(band['cylinder']['axis'], dtype=float)
    origin = np.asarray(band['cylinder']['origin_nm'], dtype=float)
    relative = np.asarray(placed['centers'], dtype=float) - origin
    heights = relative @ axis
    radial = relative - np.outer(heights, axis)
    outward = radial / np.linalg.norm(radial, axis=1)[:, None]
    across, up = pdc_placement._plane_basis(axis)
    return np.arctan2(outward @ up, outward @ across), heights, np.linalg.norm(radial, axis=1)


def _body_pair_gap(placed, profile):
    """The closest two beads of two different placed detergents' own bodies come, in nm."""
    beads = np.asarray([bead for site, direction in zip(placed['centers'], placed['directions'])
                        for bead in pdc_placement.body_beads(np.asarray(site), np.asarray(direction), profile)])
    distances = np.linalg.norm(beads[:, None, :] - beads[None, :, :], axis=2)
    np.fill_diagonal(distances, np.inf)
    return float(distances.min())


def _belt_model(length_nm=MOLECULE_LENGTH_NM):
    """A three-bead body model, the shape `detergent_cg.derive` states: a head and two `C`-type tail beads."""
    return {'beads': [{'name': 'HEAD', 'type': 'SN6', 'position': [0.0, 0.0, 0.0]},
                      {'name': 'TAIL1', 'type': 'C1', 'position': [0.5, 0.0, 0.0]},
                      {'name': 'TAIL2', 'type': 'C1', 'position': [length_nm, 0.0, 0.0]}]}


def _belt_with_protrusion(tmp_path, *, window=pdc_placement.DEFAULT_BELT_AXIAL_WINDOW_NM,
                          body_gap=pdc_placement.DEFAULT_MIN_BODY_GAP_NM, count=40, seed=4):
    """The protrusion fixture placed with a **model** body, which is what a mapping build actually stamps."""
    template = _template(tmp_path)
    profile = pdc_placement.detergent_profile_from_model(_belt_model(), template)
    placed = pdc_placement.place_detergents(_axially_local_helix_protein(), template, count, seed=seed,
                                            frame=_frame(half_thickness_nm=1.48),
                                            belt_axial_window_nm=window, min_body_gap_nm=body_gap,
                                            body_profile=profile)
    return placed, profile


def test_a_belt_body_keeps_the_minimum_body_gap_and_its_surface_is_height_aware(tmp_path):
    """The measured 2ydo defect, pinned as one fixture: the body gate bites, and height sees the bundle.

    The protein is a 1.0 nm ring with a two-atom protrusion at 3.0 nm on one axial side. On a real belt the
    body-body distance was unenforced (638 pairs under 0.25 nm), and the angular-only local surface let one helix
    push its whole sector's arc out. This belt's bodies must keep `min_body_gap_nm`; the sites *near the protrusion's
    heading but above/below its axial window* must stand on the 1.0 nm bundle, not on the 3.0 nm protrusion; and a
    feasible count must place completely with even angular and height coverage.
    """
    placed, profile = _belt_with_protrusion(tmp_path)
    band = placed['band']
    azimuths, heights, radial = _belt_geometry(placed)

    # (c) a feasible count is placed, and the record carries the two settings it was drawn under.
    assert placed['valid'], placed['issues']
    assert len(placed['centers']) == 40
    assert band['min_body_gap_nm'] == pdc_placement.DEFAULT_MIN_BODY_GAP_NM
    assert band['axial_window_nm'] == pdc_placement.DEFAULT_BELT_AXIAL_WINDOW_NM

    # (a) no two placed bodies come closer than the minimum body-bead distance, and it is the model's body.
    assert _body_pair_gap(placed, profile) >= pdc_placement.DEFAULT_MIN_BODY_GAP_NM
    assert placed['body_profile']['source'] == 'model' and placed['body_profile']['bead_count'] == 3

    # (b) at the protrusion's own heading, the sites outside its axial window see the bundle (their head sites stand
    # `length` outside ~1.0 nm, not outside the 3.0 nm protrusion).
    near = np.abs((azimuths + np.pi) % (2.0 * np.pi) - np.pi) <= np.deg2rad(12.0)
    protrusion_window = np.abs(heights - PROTRUSION_HEIGHT_NM) > pdc_placement.DEFAULT_BELT_AXIAL_WINDOW_NM
    bundle_sites = radial[near & protrusion_window]
    assert bundle_sites.size, 'the fixture must put sites above/below the protrusion at its own heading'
    assert bundle_sites.min() < PROTRUSION_RADIUS_NM + MOLECULE_LENGTH_NM - 1.0, \
        'a site above/below the protrusion still stands off the protrusion it is not level with'
    assert radial[near].max() > PROTRUSION_RADIUS_NM + MOLECULE_LENGTH_NM - 0.5, \
        'and a site level with the protrusion does stand off it'

    # (d) coverage is the ladder's own: no angular sector and no quarter of the band is empty.
    sectors = np.floor(((azimuths + 2.0 * np.pi) % (2.0 * np.pi)) / (2.0 * np.pi / 8.0)).astype(int).clip(0, 7)
    assert np.bincount(sectors, minlength=8).min() >= 3, 'an empty sector is a cluster left by relocating sites'
    quarters = np.floor((heights + band['vertical_half_band_nm'])
                        / (2.0 * band['vertical_half_band_nm'] / 4.0)).astype(int).clip(0, 3)
    assert np.bincount(quarters, minlength=4).min() >= 3, 'the heights still cover the whole band'


def test_the_axial_window_sets_how_far_a_site_sees_a_neighbouring_slice(tmp_path):
    """The window is the height-aware half-window: a wide one lets the protrusion inflate its whole sector again.

    With the default window, the sites at the protrusion's heading but above or below it stand on the 1.0 nm bundle.
    Widen the window to 5 nm and every one of those sites sees the protrusion, so the sector's surface is the
    protrusion's and the belt's mean surface moves out. Nothing else in the request changes.
    """
    narrow, _ = _belt_with_protrusion(tmp_path)
    wide, _ = _belt_with_protrusion(tmp_path, window=5.0)

    narrow_azimuths, narrow_heights, narrow_radial = _belt_geometry(narrow)
    wide_azimuths, wide_heights, wide_radial = _belt_geometry(wide)
    near_narrow = np.abs((narrow_azimuths + np.pi) % (2.0 * np.pi) - np.pi) <= np.deg2rad(12.0)
    near_wide = np.abs((wide_azimuths + np.pi) % (2.0 * np.pi) - np.pi) <= np.deg2rad(12.0)

    assert narrow['band']['axial_window_nm'] == pdc_placement.DEFAULT_BELT_AXIAL_WINDOW_NM
    assert wide['band']['axial_window_nm'] == 5.0
    assert narrow['valid'] and wide['valid'], (narrow['issues'], wide['issues'])
    assert narrow_radial[near_narrow].min() < PROTRUSION_RADIUS_NM + MOLECULE_LENGTH_NM - 1.0, \
        'the narrow window keeps some sites at the bundle'
    assert wide_radial[near_wide].min() > PROTRUSION_RADIUS_NM + MOLECULE_LENGTH_NM - 1.0, \
        'the wide window lets the protrusion stand every site in its sector off'
    assert wide['band']['radius_nm'] > narrow['band']['radius_nm'], 'the mean surface follows the window'
    assert wide_heights.size == narrow_heights.size == 40, 'the window moves the surface, not the ladder'


def test_a_zero_body_gap_disables_the_belt_body_gate(tmp_path):
    """`min_body_gap_nm: 0` is the old head-site-only packing, and the bodies then may overlap.

    A tight 0.5 nm ring with a 2 nm molecule puts neighbouring bodies within the default gap. With the gate the
    trials push every slot out until nothing is closer than 0.3 nm; with `0` the gate does not run at all, the same
    slots are accepted where they were, and two bodies are measurably closer than the gate.
    """
    points = _ring(0.5, 0.0, count=24)
    template = _template(tmp_path)
    profile = pdc_placement.detergent_profile_from_model(_belt_model(), template)
    gated = pdc_placement.place_detergents(points, template, 40, seed=4, frame=_frame(), body_profile=profile)
    ungated = pdc_placement.place_detergents(points, template, 40, seed=4, frame=_frame(),
                                             min_body_gap_nm=0.0, body_profile=profile)

    assert gated['valid'] and ungated['valid'], (gated['issues'], ungated['issues'])
    assert len(gated['centers']) == len(ungated['centers']) == 40
    assert _body_pair_gap(gated, profile) >= pdc_placement.DEFAULT_MIN_BODY_GAP_NM
    assert _body_pair_gap(ungated, profile) < pdc_placement.DEFAULT_MIN_BODY_GAP_NM, \
        'the gate is what kept these bodies apart'
    assert ungated['band']['min_body_gap_nm'] == 0.0
    assert gated['centers'] != ungated['centers'], 'the gate changes where the sites could stand'


def test_the_body_gate_measures_the_model_body_and_an_explicit_none_is_a_centres_only_head_gate(tmp_path):
    """A mapping build's body is the model's beads, not the template's all-atom file; `None` is a bare centre.

    `_UNSET` keeps the template fallback (today's direct callers); `detergent_profile_from_model` reads the beads
    `detergent_cg.derive` writes, and its own length is the belt's stand-off -- so an 11-bead DDM is not stood off at
    the 81-atom file's reach. An explicit `None` says the build stamps one centre per molecule: the record then carries
    no body profile, says why, and reports no bead clearance because only the head site was gated.
    """
    template = _template(tmp_path)                      # two atoms, 2.0 nm apart
    model = _belt_model(length_nm=3.0)                  # three beads, 3.0 nm of reach
    profile = pdc_placement.detergent_profile_from_model(model, template)
    points = _ring(1.0, 0.0, count=24)

    modelled = pdc_placement.place_detergents(points, template, 40, seed=4, frame=_frame(), body_profile=profile)
    centres = pdc_placement.place_detergents(points, template, 40, seed=4, frame=_frame(), body_profile=None)
    fallback = pdc_placement.place_detergents(points, template, 40, seed=4, frame=_frame())

    # The model's own profile, not the template's: three beads, its own length, and a head read from its types.
    assert profile['bead_count'] == 3 and profile['source'] == 'model'
    assert profile['length_nm'] == pytest.approx(3.0) and profile['head_source'] == 'types'
    assert pdc_placement.detergent_profile_from_model(None, template)['source'] == 'coordinates'
    assert pdc_placement.detergent_profile_from_model({'beads': []}, template)['source'] == 'coordinates'

    # The model body is what the gate and the belt measured: its stand-off is 3.0, and its tail is what comes close.
    assert modelled['valid'] and len(modelled['centers']) == 40, modelled['issues']
    assert modelled['body_profile']['source'] == 'model' and modelled['body_profile']['bead_count'] == 3
    assert modelled['body_profile_reason'] is None
    assert modelled['band']['detergent_length_nm'] == 3.0
    assert modelled['bead_clearance_nm'] < modelled['protein_clearance_nm'], \
        'the model body reaches past its head site, and it is the body the protein is near'

    # A centres-only build passes the explicit `None`: the head site is the gate, and the record says so.
    assert centres['valid'] and len(centres['centers']) == 40, centres['issues']
    assert centres['body_profile'] is None and centres['bead_clearance_nm'] is None
    assert 'centre per molecule' in centres['body_profile_reason']
    assert centres['band']['detergent_length_nm'] == MOLECULE_LENGTH_NM, 'the template still sizes a centre build'
    assert centres['centers'] != modelled['centers'], 'the model body is what the sites stood off'

    # `_UNSET` is the template fallback, byte-identical to a caller that never heard of a model.
    assert fallback['body_profile'] == pdc_placement._profile_record(pdc_placement.detergent_profile(template))
    assert fallback['body_profile']['source'] == 'coordinates'


def test_a_slot_whose_base_fails_a_gate_is_moved_by_a_bounded_trial(tmp_path):
    """Task 1: a base the old gate refused is nudged, and the accepted head and body clear every gate.

    The base head is the ladder's own heading/height placed at the supplied local surface, with a protein point
    sitting exactly on it. The old code rejected this slot before any trial (a head distance of 0 nm is below the
    clearance); the ladder's first legal trial moves the head radially outward and the slot is filled. The trial is
    inside the documented local bounds, so no neighbour's ladder position is used.
    """
    from micelle.packing import golden_angle_directions

    cylinder = {'axis': [0.0, 0.0, 1.0], 'origin': [0.0, 0.0, 0.0]}
    length, half_band = 0.5, 1.0
    ladder = golden_angle_directions(1, 3)
    heading = float(np.arctan2(ladder[0, 1], ladder[0, 0]))
    height = float(np.sin(0.5 * np.pi * ladder[0, 2]) * half_band)
    axis = np.asarray(cylinder['axis'], dtype=float)
    across, up = pdc_placement._plane_basis(axis)
    outward = np.cos(heading) * across + np.sin(heading) * up
    base_candidate = (1.0 + length) * outward + height * axis
    base_direction = (np.cos(pdc_placement.TILT_RADIANS) * outward
                      + np.sign(height) * np.sin(pdc_placement.TILT_RADIANS) * axis)
    protein = np.asarray([base_candidate])
    profile = pdc_placement.detergent_profile(_template(tmp_path))

    # The old first gate: the base head is inside the clearance, so the slot never reached a trial.
    assert float(np.linalg.norm(base_candidate - protein, axis=1).min()) < pdc_placement.MIN_CLEARANCE_NM
    assert pdc_placement.body_clearance(base_candidate, base_direction, profile, protein) < \
        pdc_placement.BEAD_CLEARANCE_NM

    centers, directions, drawn, rejected, passes, rejected_slots = pdc_placement._cylinder_sites(
        1, 3, cylinder, lambda heading, height: 1.0, length, half_band, protein,
        pdc_placement.MIN_CLEARANCE_NM, profile)

    assert len(centers) == 1 and drawn == 1 and rejected == 0 and passes == 1
    assert rejected_slots == []
    moved = centers[0]
    assert not np.allclose(moved, base_candidate), 'the refused slot is moved by a trial, not kept or dropped'
    relative = moved - np.asarray(cylinder['origin'])
    assert abs(float(relative @ axis) - height) <= max(abs(value) for value in pdc_placement.BELT_TRIAL_HEIGHT_NM)
    radial = relative - float(relative @ axis) * axis
    base_radial = 1.0 + length
    assert float(np.linalg.norm(radial)) - base_radial <= \
        max(pdc_placement.BELT_TRIAL_RADIAL_NM) + 1e-9, 'the move is a local nudge, not another ladder slot'
    assert float(np.linalg.norm(moved - protein, axis=1).min()) >= pdc_placement.MIN_CLEARANCE_NM
    beads = pdc_placement.body_beads(moved, directions[0], profile)
    assert float(np.linalg.norm(beads[:, None, :] - protein[None, :, :], axis=2).min()) >= \
        pdc_placement.BEAD_CLEARANCE_NM


def _blocked_in_band_protein(count, seed, half_band, length_nm, slab_half_nm):
    """A transmembrane ring plus a lid of protein atoms standing on every in-band trial site above the slab.

    The lid atoms are deliberately **outside** the frame's slab: `_belt_cylinder` measures its local surface only
    from in-slab atoms, so they gate a candidate's clearance without ever becoming a surface to stand off. Every
    positive-height slot whose in-band trials would all land above the slab gets one lid atom on each of them, so
    only the documented out-of-band fallback can place those slots. The ring is the only in-slab atom, which makes
    the measured cylinder the flat 1.0 nm ring.
    """
    ring = _ring(1.0, 0.0, count=24)
    ladder = golden_angle_directions(count, seed)
    headings = np.arctan2(ladder[:, 1], ladder[:, 0])
    heights = np.sin(0.5 * np.pi * ladder[:, 2]) * half_band
    axis = np.array([0.0, 0.0, 1.0])
    across, up = pdc_placement._plane_basis(axis)
    lowest = max(abs(value) for value in pdc_placement.BELT_TRIAL_HEIGHT_NM)
    lid = []
    for heading, height in zip(headings, heights):
        if height - lowest <= slab_half_nm:
            # This slot has an ordinary in-band trial inside the slab; it is not the case this fixture blocks.
            continue
        for heading_offset in (0.0, *np.deg2rad(pdc_placement.BELT_TRIAL_HEADING_DEG)):
            for height_offset in (0.0, *pdc_placement.BELT_TRIAL_HEIGHT_NM):
                trial_height = float(np.clip(height + height_offset, -half_band, half_band))
                if trial_height <= slab_half_nm:
                    continue
                # The topmost lid atom stays 0.02 nm inside the band, so the first out-of-band height is still more
                # than `min_clearance_nm` above it.
                trial_height = min(trial_height, half_band - 0.02)
                for radial_offset in (0.0, *pdc_placement.BELT_TRIAL_RADIAL_NM):
                    radius = 1.0 + length_nm + radial_offset
                    outward = np.cos(heading + heading_offset) * across + np.sin(heading + heading_offset) * up
                    lid.append(list(radius * outward + trial_height * axis))
    return np.asarray(ring + lid, dtype=float)


def test_a_slot_the_protein_blocks_in_band_clears_at_the_next_height_above_the_band(tmp_path):
    """A slot whose every in-band trial fails tries the absolute heights above/below the band before it is empty.

    The protein's lid sits exactly on every in-band trial a positive-height slot can reach, so none of the base,
    height, heading or radial trials clear the head gate. The documented first out-of-band height (+(half_band +
    0.5)) is then tried at the slot's own heading, with no radial offset, and it clears -- and the record states the
    taller band it actually occupies while `vertical_half_band_nm` stays the requested one.
    """
    count, seed = 12, 4
    half_band = pdc_placement.VERTICAL_SPREAD * MOLECULE_LENGTH_NM
    points = _blocked_in_band_protein(count, seed, half_band, MOLECULE_LENGTH_NM, slab_half_nm=0.85)
    placed = pdc_placement.place_detergents(points, _template(tmp_path), count, seed=seed,
                                            frame=_frame(half_thickness_nm=0.85), measure_capacity=False)
    band = placed['band']
    axis = np.asarray(band['cylinder']['axis'], dtype=float)
    origin = np.asarray(band['cylinder']['origin_nm'], dtype=float)
    heights = (np.asarray(placed['centers'], dtype=float) - origin) @ axis

    assert placed['valid'], placed['issues']
    assert len(placed['centers']) == count, 'the fallback placed the slots the in-band trials could not'
    assert band['vertical_half_band_nm'] == pytest.approx(half_band)
    assert band['placed_axial_max_nm'] > half_band, 'a placed centre stands outside the band the request stated'
    assert band['placed_axial_max_nm'] == pytest.approx(float(np.abs(heights).max()), abs=1e-6)

    outside = heights[np.abs(heights) > half_band + 1e-9]
    assert outside.size >= 1
    assert np.allclose(outside, half_band + pdc_placement.BELT_TRIAL_BEYOND_NM[0]), \
        'the first out-of-band height is the one that cleared, at the slot\'s own heading'
    assert np.allclose((np.asarray(placed['directions']) @ axis)[np.abs(heights) > half_band + 1e-9],
                       np.sin(np.deg2rad(pdc_placement.TILT_DEGREES))), \
        'an out-of-band height takes its tilt sign from that height, as every trial does'

    limit = half_band + max(pdc_placement.BELT_TRIAL_BEYOND_NM)
    assert float(np.abs(heights).max()) <= limit + 1e-6, 'the fallback is bounded by its last documented height'
    assert float(heights.min()) >= -limit - 1e-6, 'and it never leaves the band further on the other side'
    mean, length = band['radius_nm'], band['detergent_length_nm']
    assert band['volume_nm3'] == pytest.approx(
        np.pi * ((mean + length) ** 2 - mean ** 2) * 2.0 * band['placed_axial_max_nm']), \
        'the volume is the band actually occupied, not the requested half-band'


def test_a_slot_with_nothing_blocking_it_still_places_inside_the_band(tmp_path):
    """The fallback must not move ordinary placements: every centre and the recorded maximum stay in the band."""
    placed = pdc_placement.place_detergents(_asymmetric_protein(), _template(tmp_path), 12, seed=4, frame=_frame())
    band = placed['band']
    axis = np.asarray(band['cylinder']['axis'], dtype=float)
    origin = np.asarray(band['cylinder']['origin_nm'], dtype=float)
    heights = (np.asarray(placed['centers'], dtype=float) - origin) @ axis

    assert placed['valid'], placed['issues']
    assert len(placed['centers']) == 12
    assert np.all(np.abs(heights) <= band['vertical_half_band_nm'] + 1e-9), \
        'an ordinary slot is still placed in band; the out-of-band fallback never runs for it'
    assert band['placed_axial_max_nm'] <= band['vertical_half_band_nm'] + 1e-9
    assert band['placed_axial_max_nm'] == pytest.approx(float(np.abs(heights).max()), abs=1e-6)
    mean, length, half_band = band['radius_nm'], band['detergent_length_nm'], band['vertical_half_band_nm']
    assert band['volume_nm3'] == pytest.approx(np.pi * ((mean + length) ** 2 - mean ** 2) * 2.0 * half_band)


def _assert_finite_marks(marks):
    """Every mark is JSON-safe: three finite coordinates, a finite radius, finite beads."""
    assert all(np.isfinite(mark['position_nm']).all() for mark in marks)
    assert all(mark['normal_nm'] is None or np.isfinite(mark['normal_nm']).all() for mark in marks)
    assert all(np.isfinite(mark['radius_nm']) for mark in marks)
    assert all(np.isfinite(bead).all() for mark in marks for bead in mark['protein_beads'])
    assert all(len(mark['position_nm']) == 3 for mark in marks)


def test_the_rejection_records_and_problems_are_deterministic_in_the_seed(tmp_path):
    """Same seed -> byte-identical rejected slots and marks; a different seed -> different geometry."""
    points = [point for z in np.linspace(-0.9, 0.9, 5) for point in _ring(2.4, float(z), count=180)]
    template = _template(tmp_path, length_nm=0.4)
    first = pdc_placement.place_detergents(points, template, 600, seed=4, frame=_frame(), radius_nm=2.4,
                                           measure_capacity=False)
    again = pdc_placement.place_detergents(points, template, 600, seed=4, frame=_frame(), radius_nm=2.4,
                                           measure_capacity=False)
    other = pdc_placement.place_detergents(points, template, 600, seed=5, frame=_frame(), radius_nm=2.4,
                                           measure_capacity=False)

    assert json.dumps(first['problems'], sort_keys=True) == json.dumps(again['problems'], sort_keys=True)
    assert first['band']['rejected_slots'] == again['band']['rejected_slots']
    assert first['band']['rejected_slots'] != other['band']['rejected_slots']
    assert first['problems'] != other['problems']
    _assert_finite_marks(first['problems'])


def test_an_empty_slot_ring_sits_at_the_rejected_slots_own_base_point(tmp_path):
    """The preview's ring is the slot's own geometry: base point, outward normal, and the failed gate's distance."""
    points = [point for z in np.linspace(-0.9, 0.9, 5) for point in _ring(2.4, float(z), count=180)]
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 600, seed=4,
                                            frame=_frame(), radius_nm=2.4, measure_capacity=False)
    slots = placed['band']['rejected_slots']
    empty = [mark for mark in placed['problems'] if mark['kind'] == 'empty-slot']

    assert len(empty) == len(slots)
    for slot, mark in zip(slots, empty):
        assert mark['position_nm'] == slot['position_nm']
        assert mark['normal_nm'] == slot['normal_nm']
        assert mark['radius_nm'] == slot['gate_nm']
        assert mark['molecule'] is None and mark['detail'].startswith('aggregation count')


def test_a_rejected_slot_is_lifted_with_the_belt_so_its_ring_stays_on_the_drawn_belt(tmp_path):
    """A raised belt raises its empty slots too: the ring sits where that slot would have stood after the offset.

    The count is chosen so some slots stay empty even after the out-of-band fallback (280 holds 255), and few enough
    that `MAX_PROBLEMS` does not truncate their rings.
    """
    points = [point for z in np.linspace(-0.9, 0.9, 5) for point in _ring(2.4, float(z), count=180)]
    template = _template(tmp_path, length_nm=0.4)
    level = pdc_placement.place_detergents(points, template, 280, seed=4, frame=_frame(), radius_nm=2.4,
                                           measure_capacity=False)
    lifted = pdc_placement.place_detergents(points, template, 280, seed=4, frame=_frame(), radius_nm=2.4,
                                            belt_offset_nm=0.3, measure_capacity=False)
    axis = np.asarray(level['band']['cylinder']['axis'], dtype=float)
    before = level['band']['rejected_slots']
    after = lifted['band']['rejected_slots']

    assert len(before) == len(after) > 0
    for low, high in zip(before, after):
        assert np.allclose(np.asarray(high['position_nm']) - np.asarray(low['position_nm']), 0.3 * axis, atol=5e-6)
        assert high['height_nm'] == pytest.approx(low['height_nm'] + 0.3, abs=5e-6)
        assert high['normal_nm'] == low['normal_nm']
        assert high['reason'] == low['reason']
    rings = [mark for mark in lifted['problems'] if mark['kind'] == 'empty-slot']
    assert [mark['position_nm'] for mark in rings] == [slot['position_nm'] for slot in after]


def test_a_head_inside_the_clearance_is_marked_at_its_site_and_nearest_protein_bead(tmp_path):
    """The belt raises into a protrusion the unshifted site gate never measured: each offending head is marked."""
    points = _ring(1.0, 0.0, count=12) + _ring(3.0, 2.0, count=24)
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(),
                                            radius_nm=1.0, belt_offset_nm=2.0, measure_capacity=False)
    head = [mark for mark in placed['problems'] if mark['kind'] == 'head-clearance']

    assert not placed['valid'] and head
    issue = next(issue for issue in placed['issues'] if issue.startswith('detergent too close'))
    centers = np.asarray(placed['centers'])
    cloud = np.asarray(points)
    for mark in head:
        index = mark['molecule'] - 1
        assert mark['detail'] == issue
        assert mark['position_nm'] == [round(float(value), 6) for value in centers[index]]
        assert mark['normal_nm'] is None
        assert len(mark['protein_beads']) == 1
        assert np.linalg.norm(centers[index] - np.asarray(mark['protein_beads'][0])) < \
            pdc_placement.MIN_CLEARANCE_NM
        assert np.linalg.norm(centers[index] - np.asarray(mark['protein_beads'][0])) == pytest.approx(
            float(np.linalg.norm(centers[index] - cloud, axis=1).min()), abs=6e-6)
    _assert_finite_marks(placed['problems'])


def test_a_drawn_body_inside_the_bead_gate_is_marked_with_its_offending_pair(tmp_path):
    """A body-clearance mark is the offending detergent bead, and the protein point it comes too close to."""
    template = _template(tmp_path)
    protein = [[0.0, 0.0, 0.0]]
    library = DrawnLibrary([[[0.0, 0.0, 0.0], [0.0, 0.0, -3.0]]])
    placed = pdc_placement.place_detergents(protein, template, 4, seed=7, conformations=library)
    body = [mark for mark in placed['problems'] if mark['kind'] == 'body-clearance']
    drawn = placed['conformations']

    assert not placed['valid'] and body
    issue = next(issue for issue in placed['issues'] if 'drawn detergent body' in issue)
    for mark in body:
        assert mark['detail'] == issue
        index = mark['molecule'] - 1
        assert 0 <= index < len(placed['centers'])
        profile = library.profiles[drawn['entries'][index]]
        beads = pdc_placement.body_beads(np.asarray(placed['centers'][index]),
                                         np.asarray(placed['directions'][index]),
                                         profile, drawn['twists'][index])
        assert any(np.allclose(mark['position_nm'], np.round(bead, 6)) for bead in beads)
        assert mark['normal_nm'] is None
        assert np.linalg.norm(np.asarray(mark['position_nm']) - np.asarray(mark['protein_beads'][0])) < \
            pdc_placement.BEAD_CLEARANCE_NM
    _assert_finite_marks(placed['problems'])


def test_an_overlapping_pair_records_both_molecule_indices(tmp_path, monkeypatch):
    """One mark per member, each naming its own index and the partner's centre, so both indices are recorded."""
    from micelle.validation import validate_positions

    monkeypatch.setattr(pdc_placement, 'MIN_DISTANCE_NM', 0.0)
    placed = pdc_placement.place_detergents(None, _template(tmp_path), 60, seed=7, mode='self-assembly',
                                            radius_nm=1.0)
    overlap = [mark for mark in placed['problems'] if mark['kind'] == 'overlap']
    report = validate_positions(placed['centers'], len(placed['centers']))
    first, second = report['overlap_pairs'][0]

    assert not placed['valid'] and overlap
    assert len(report['minimum_pair']) == 2, 'the report names the closest pair'
    issue = next(issue for issue in placed['issues'] if issue.startswith('detergent overlap'))
    centers = np.asarray(placed['centers'])
    partner_of = {first + 1: second, second + 1: first}
    pair_marks = [mark for mark in overlap
                  if mark['molecule'] in partner_of
                  and mark['protein_beads'] == [[round(float(value), 6)
                                                 for value in centers[partner_of[mark['molecule']]]]]]
    assert {mark['molecule'] for mark in pair_marks} == {first + 1, second + 1}
    for mark in pair_marks:
        assert mark['detail'] == issue
        assert mark['position_nm'] == [round(float(value), 6) for value in centers[mark['molecule'] - 1]]
    _assert_finite_marks(placed['problems'])


def test_problem_marks_are_capped_and_the_leftovers_counted(tmp_path, monkeypatch):
    """MAX_PROBLEMS marks in the documented order; `problems_truncated` is the number left out."""
    template = _template(tmp_path)
    long_entry = [[[0.0, 0.0, 0.0], [0.0, 0.0, -3.0]]]
    library = DrawnLibrary(long_entry)

    monkeypatch.setattr(pdc_placement, 'MAX_PROBLEMS', 10_000)
    uncapped = pdc_placement.place_detergents([[0.0, 0.0, 0.0]], template, 250, seed=7, conformations=library)
    total = len(uncapped['problems'])
    assert total > 200 and uncapped['problems_truncated'] == 0

    monkeypatch.setattr(pdc_placement, 'MAX_PROBLEMS', 50)
    capped = pdc_placement.place_detergents([[0.0, 0.0, 0.0]], template, 250, seed=7, conformations=library)
    assert pdc_placement.MAX_PROBLEMS == 50
    assert len(capped['problems']) == 50
    assert capped['problems_truncated'] == total - 50
    assert capped['problems'] == uncapped['problems'][:50]
    assert pdc_placement.MAX_PROBLEMS == 50


def test_the_whole_belt_can_be_lifted_along_the_membrane_normal(tmp_path):
    """A belt offset moves every site together, higher along the frame's axis; 0 is the unchanged placement."""
    points = _asymmetric_protein()
    level = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame())
    lifted = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(),
                                            belt_offset_nm=0.2)

    assert level['valid'] and lifted['valid'], (level['issues'], lifted['issues'])
    assert lifted['band']['belt_offset_nm'] == 0.2
    axis = np.asarray(level['band']['cylinder']['axis'])
    assert len(lifted['centers']) == len(level['centers'])
    assert np.allclose(np.asarray(lifted['centers']) - 0.2 * axis, level['centers'])
