"""Detergent placement: the builder's geometry plus the gates that decide whether a run may proceed.

The properties worth pinning are the ones a reader would otherwise have to trust: the count is exact, the same seed
gives the same positions while a different seed does not, every detergent is outside the protein, and an impossible
packing is reported as an issue rather than handed back as coordinates for a run to fail on later.

The belt's own shape is the *torus* the user's correction asks for (2026-10-14): the protein's hydrophobic cylinder
-- the circle of the measured slab radius lying in the membrane plane -- is the tube's centre-line, the tube's radius
is the detergent's own length, the head ends sit on the tube's outer surface and every detergent's body points back
at that centre-line. These tests measure that shape rather than describe it.
"""
import json

import numpy as np
import pytest

from dashboard.execution.adapters import pdc_placement
from dashboard.execution.scripts import pdc_build
from micelle.frame import frame_from_structure
from micelle.packing import golden_angle_directions
from micelle.registry import load_template

PROTEIN = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
#: The fixture molecule's own length: its structure is two atoms this far apart, which is what the tube's radius is
#: measured from. A molecule nobody can measure -- `length_nm=None` -- is the case that keeps the sphere.
MOLECULE_LENGTH_NM = 2.0
#: The stated tolerance on "the head end lies on the tube's outer surface". The placement's own sites are exact; the
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


def test_the_self_assembly_direction_is_outward_too(tmp_path):
    """The empty micelle's region is centred on the origin, so the outward direction is the centre's own heading."""
    template = _template(tmp_path)
    placed = pdc_placement.place_detergents(None, template, 24, seed=20260502, mode='self-assembly',
                                            radius_nm=3.0)

    centres = np.asarray(placed['centers'])
    directions = np.asarray(placed['directions'])
    assert len(centres) == 24
    for centre, direction in zip(centres, directions):
        assert np.linalg.norm(direction) == pytest.approx(1.0)
        assert np.allclose(direction, centre / np.linalg.norm(centre)), \
            'the self-assembly direction is the way out of the cloud too'


# --- the tube: the shape a protein that states its own membrane is placed in --------------------------------

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


def distance_to_centre_line(sites, centre_radius, axis=(0.0, 0.0, 1.0), centre_nm=0.0):
    """Each site's distance to the tube's centre-line: the circle of `centre_radius` in the frame's own plane.

    The nearest point of that circle to a site is the one at the site's own azimuth, so the distance is the
    meridional pair `(radial - centre_radius, axial - centre_nm)` -- which is the quantity the tube's radius is
    measured in, and the one the acceptance asks about ("no site outside the detergent length from the centre-line").
    """
    sites = np.asarray(sites, dtype=float)
    axis = np.asarray(axis, dtype=float)
    radial = np.linalg.norm(sites - np.outer(sites @ axis, axis), axis=1) - centre_radius
    axial = sites @ axis - centre_nm
    return np.hypot(radial, axial)


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


def test_a_stated_membrane_puts_the_placement_on_the_tubes_own_surface(tmp_path):
    """The correction's shape: the sites stand at the detergent's own length from the protein's cylinder.

    The tube's centre-line is the circle of the measured slab radius in the membrane plane and the tube's radius is
    the detergent's own length -- measured from the molecule, not a constant. Every site is therefore the same
    distance from the centre-line wherever around the half-circle it sits, while its distance from the *membrane
    axis* varies with the meridian angle: that is the difference between a torus and the cylinder wall this replaces.
    """
    points = _asymmetric_protein()
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(), radius_nm=1.0)

    centres = np.asarray(placed['centers'])
    axis = np.array([0.0, 0.0, 1.0])
    axial = centres @ axis
    transverse = np.linalg.norm(centres - np.outer(axial, axis), axis=1)

    assert placed['valid'], placed['issues']
    assert placed['placement_shape'] == 'belt-torus'
    # The centre-line is the slab's own 1.0 nm: the `radius_nm` setting is a floor under it and 1.0 is not above it.
    assert placed['band']['centre_line_radius_nm'] == 1.0
    assert placed['band']['slab_radius_nm'] == 1.0, 'the radius it was derived from, so a reader can re-add the floor'
    assert placed['band']['tube_radius_nm'] == MOLECULE_LENGTH_NM, "the tube is the detergent's own length"
    assert (placed['band']['plane_low_nm'], placed['band']['plane_high_nm']) == (-1.0, 1.0)

    distances = distance_to_centre_line(centres, 1.0)
    assert np.allclose(distances, MOLECULE_LENGTH_NM, atol=SURFACE_TOLERANCE_NM), \
        "every site is the detergent's own length from the centre-line"
    assert np.all(np.abs(axial) < MOLECULE_LENGTH_NM + SURFACE_TOLERANCE_NM), \
        'and inside the tube, which reaches the detergent length either side of the membrane centre'
    assert np.allclose(transverse, 1.0 + MOLECULE_LENGTH_NM * np.cos(np.arcsin(axial / MOLECULE_LENGTH_NM)),
                       atol=1e-6), 'the belt wraps the half-circle: its radius from the axis is not one number'
    assert transverse.max() - transverse.min() > 1.0, 'the sites are not all at one stand-off distance from the axis'
    assert placed['protein_clearance_nm'] >= pdc_placement.MIN_CLEARANCE_NM


def test_no_site_lies_outside_the_detergent_length_from_the_centre_line(tmp_path):
    """The acceptance's own test, on a protein whose own atoms reach into the tube's surface."""
    # An in-slab ring sets the measured cylinder (1.0 nm); a second ring, outside the slab so it cannot enlarge that
    # measurement, sits right where the tube's surface passes -- so the draw has to refuse those entries and keep the
    # count from the entries the protein leaves room for.
    points = _ring(1.0, 0.2) + _ring(2.0, 1.6, count=180)
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 40, seed=11, frame=_frame(), radius_nm=1.0)

    assert placed['valid'], placed['issues']
    distances = distance_to_centre_line(placed['centers'], placed['band']['centre_line_radius_nm'])
    assert len(distances) == 40, 'the requested count is the count that is placed'
    assert np.all(distances <= placed['band']['tube_radius_nm'] + SURFACE_TOLERANCE_NM), \
        'no site is outside the detergent length from the centre-line'
    assert placed['band']['rejected'] > 0, 'this protein reaches into the tube, so entries were refused'
    assert placed['band']['tube_radius_nm'] == MOLECULE_LENGTH_NM


def test_the_head_end_is_further_from_the_centre_line_than_its_tail_end_and_lands_on_the_surface(tmp_path):
    """What the user's correction asks for, measured on the stamped molecule rather than asserted about it.

    `stamp` puts the molecule's *head end* at the site and points its head-ward axis along the placement's own
    direction, so every detergent's head end sits on the tube's outer surface -- the detergent's own length from the
    centre-line -- and its tail beads sit nearer that centre-line.
    """
    points = _asymmetric_protein()
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(), radius_nm=1.0)
    atoms = pdc_build.stamp(DRAFT, placed['centers'], placed['directions'], first_residue=10)

    centre_radius = placed['band']['centre_line_radius_nm']
    molecules = {}
    for atom in atoms:
        molecules.setdefault(atom['residue_id'], []).append(atom)

    assert len(molecules) == 12
    for residue_id, beads in molecules.items():
        head = [np.asarray(atom['position']) for atom in beads if atom['name'] == 'HEAD']
        tail = [np.asarray(atom['position']) for atom in beads if atom['name'] == 'TAIL1']
        head_distance = float(distance_to_centre_line(head, centre_radius).max())
        tail_distance = float(distance_to_centre_line(tail, centre_radius).max())
        assert head_distance > tail_distance, f'detergent {residue_id} has its tail outside its head'
        assert head_distance == pytest.approx(MOLECULE_LENGTH_NM, abs=SURFACE_TOLERANCE_NM), \
            "the head end lies on the tube's outer surface"


def test_the_direction_is_the_tubes_radial_direction_and_not_the_cylinders_heading(tmp_path):
    """The geometry today's code cannot express: the head-to-tail axis depends on where around the half-circle."""
    points = _asymmetric_protein()
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 24, seed=4, frame=_frame(), radius_nm=1.0)

    centres = np.asarray(placed['centers'])
    directions = np.asarray(placed['directions'])
    axis = np.array([0.0, 0.0, 1.0])
    radial = centres - np.outer(centres @ axis, axis)
    radial = radial / np.linalg.norm(radial, axis=1)[:, None]

    assert np.allclose(np.linalg.norm(directions, axis=1), 1.0)
    axial_component = np.abs(directions @ axis)
    assert axial_component.max() > 0.9, 'the belt reaches the top and bottom of the half-circle'
    assert axial_component.min() < 0.2, 'and it reaches the membrane plane, where the tube and the cylinder agree'
    assert not np.allclose(directions, radial), "the cylinder's own heading is the shape this replaces"
    # Every direction is its own meridian's outward radial direction: the plane's heading turned by the site's
    # meridian angle. A direction built from the plane heading alone would have no axial part at all.
    meridian = np.arcsin(np.clip((centres @ axis) / placed['band']['tube_radius_nm'], -1.0, 1.0))
    expected = np.cos(meridian)[:, None] * radial + np.sin(meridian)[:, None] * axis
    assert np.allclose(directions, expected, atol=1e-9)


def test_the_tube_is_seeded_and_keeps_no_two_sites_closer_than_the_overlap_gate(tmp_path):
    points = _ring(2.0, 0.3)
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 40, seed=11, frame=_frame(), radius_nm=2.0)
    again = pdc_placement.place_detergents(points, _template(tmp_path), 40, seed=11, frame=_frame(), radius_nm=2.0)
    other = pdc_placement.place_detergents(points, _template(tmp_path), 40, seed=12, frame=_frame(), radius_nm=2.0)

    centres = np.asarray(placed['centers'])
    separations = np.linalg.norm(centres[:, None, :] - centres[None, :, :], axis=2)
    np.fill_diagonal(separations, np.inf)

    assert placed['valid'], placed['issues']
    assert len(centres) == 40, 'the requested count is the count that is placed'
    assert placed['centers'] == again['centers'], 'the seed decides the tube too'
    assert other['centers'] != placed['centers'], 'a different seed must place differently'
    assert separations.min() >= pdc_placement.MIN_DISTANCE_NM


def test_the_tubes_first_pass_is_the_ladders_own_golden_angle_sites(tmp_path):
    """The shape changes; the arrangement does not. Where the protein leaves room, the sites are the ladder's own.

    A site the protein leaves no room for is refused and its replacement comes from the next pass -- the same ladder
    with its phase advanced -- so the first pass's sites are the entries of `golden_angle_directions` for the seed
    itself, in order, and the sites that had to come later are still entries of that same arrangement.
    """
    points = _ring(1.5, 0.3)
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 24, seed=20261013, frame=_frame(),
                                            radius_nm=1.5)
    axis = np.array([0.0, 0.0, 1.0])
    length = placed['band']['tube_radius_nm']

    places = [(np.arctan2(centre[1], centre[0]),
               np.arcsin(np.clip((np.asarray(centre) @ axis) / length, -1.0, 1.0)))
              for centre in placed['centers']]
    assert len(places) == 24

    known = []
    for phase in range(placed['band']['passes']):
        ladder = golden_angle_directions(24, 20261013 + phase)
        known += [(float(np.arctan2(row[1], row[0])), float(0.5 * np.pi * row[2])) for row in ladder]

    for azimuth, meridian in places:
        assert any(abs((heading - azimuth + np.pi) % (2 * np.pi) - np.pi) < 1e-9
                   and abs(m - meridian) < 1e-9 for heading, m in known), \
            "every site is one of the ladder's own golden-angle entries"


def test_the_tube_wraps_the_whole_half_circle_rather_than_one_band_of_it(tmp_path):
    """What the correction replaces: a cylinder wall's sites are all at one height; a tube's are not.

    The sites' meridian angle must cover the half-circle -- from the membrane plane (where the detergent points
    across the bilayer) to the membrane normal (where it points out of it) -- because the ladder's second coordinate
    is that angle and the ladder covers its range.
    """
    placed = pdc_placement.place_detergents(_asymmetric_protein(), _template(tmp_path), 40, seed=7, frame=_frame(),
                                            radius_nm=1.0)
    axis = np.array([0.0, 0.0, 1.0])
    centres = np.asarray(placed['centers'])
    length = placed['band']['tube_radius_nm']
    axial = np.abs(centres @ axis) / length

    assert len(centres) == 40
    assert axial.max() > 0.9, 'the belt reaches the top and bottom of the half-circle'
    assert axial.min() < 0.1, 'and it reaches the membrane plane, where the tube and the cylinder agree'
    assert np.all(axial <= 1.0 + SURFACE_TOLERANCE_NM), 'and it never leaves the half-circle'


def test_a_request_the_tube_cannot_hold_fails_the_count_gate_rather_than_being_nudged(tmp_path):
    """The refusal path is unchanged: what the shape cannot hold is reported, not quietly relocated."""
    # A protein that fills the tube's whole surface: 720 points on the centre-line itself, so every meridian angle of
    # every azimuth is inside the clearance gate. Nothing can be placed, and the count gate says so -- the same
    # sentence, and the same exit, the builder has always had.
    points = _ring(2.0, 0.0, count=720)
    placed = pdc_placement.place_detergents(points, _template(tmp_path, length_nm=0.4), 12, seed=4, frame=_frame(),
                                            radius_nm=2.0)

    assert not placed['valid']
    assert any(issue.startswith('aggregation count') for issue in placed['issues']), placed['issues']
    assert placed['band']['rejected'] >= len(points) - 1, 'every entry the draw offered was refused'


def test_a_detergent_whose_own_length_cannot_be_measured_keeps_the_sphere_it_had(tmp_path):
    """No length, no tube: a molecule nobody measured is not a radius to build one from."""
    placed = pdc_placement.place_detergents(_asymmetric_protein(), _template(tmp_path, length_nm=None), 8, seed=3,
                                            frame=_frame())

    assert placed['placement_shape'] == 'sphere' and placed['band'] is None
    assert 'length' in placed['belt_reason']


def test_a_protein_that_states_no_membrane_keeps_the_sphere_it_had(tmp_path):
    """`frame=None` is every packaged protein and every import that states nothing: the shell, byte for byte."""
    points = _asymmetric_protein()
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4)

    centres = np.asarray(placed['centers'])
    centroid = np.asarray(points).mean(axis=0)

    assert placed['placement_shape'] == 'sphere' and placed['band'] is None and placed['frame'] is None
    assert np.allclose(np.linalg.norm(centres - centroid, axis=1), pdc_placement.DEFAULT_RADIUS_NM)


def test_a_stated_membrane_the_protein_sits_entirely_outside_keeps_the_sphere(tmp_path):
    """No atom in the slab means no centre-line to measure, and a guessed one is not one: the caller keeps the shell."""
    placed = pdc_placement.place_detergents(_ring(1.0, 3.0) + _ring(5.0, 3.0), _template(tmp_path), 8, seed=3,
                                            frame=_frame())

    assert placed['placement_shape'] == 'sphere' and placed['band'] is None


def test_an_empty_micelle_is_the_same_sphere_with_a_frame_as_without_one(tmp_path):
    """The user's decision: no protein, a simple sphere -- and a frame handed over with it changes nothing."""
    template = _template(tmp_path)
    without = pdc_placement.place_detergents(None, template, 8, seed=3)
    stated = pdc_placement.place_detergents(None, template, 8, seed=3, frame=_frame())

    assert stated['centers'] == without['centers'] and stated['directions'] == without['directions']
    assert stated['placement_shape'] == 'sphere' and stated['protein_free']
    assert np.allclose(np.linalg.norm(np.asarray(stated['centers']), axis=1), pdc_placement.DEFAULT_RADIUS_NM)


def test_a_tube_faces_the_way_the_frame_states_rather_than_the_way_z_does(tmp_path):
    """A y-facing bilayer is the case a reader that indexed z would place every detergent outside of."""
    axis = np.array([0.0, 1.0, 0.0])
    points = [[2.0 * np.cos(a), 0.2, 2.0 * np.sin(a)] for a in np.linspace(0.0, 2.0 * np.pi, 12, endpoint=False)]
    placed = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(axis=tuple(axis)),
                                            radius_nm=2.0)

    centres = np.asarray(placed['centers'])
    distances = distance_to_centre_line(centres, 2.0, axis=axis)

    assert placed['placement_shape'] == 'belt-torus' and placed['valid'], placed['issues']
    assert np.allclose(distances, MOLECULE_LENGTH_NM, atol=SURFACE_TOLERANCE_NM), \
        "the tube is measured along the frame's own axis, not z"


# --- `radius_nm` as a floor on a protein build ---------------------------------------------------------------

def test_a_radius_larger_than_the_measured_cylinder_lifts_the_centre_line_to_it(tmp_path):
    """The setting may push a belt out; it can never shrink it below what the protein was measured to need."""
    points = _asymmetric_protein()          # a 1.0 nm in-slab radius, so the centre-line measures 1.0 nm
    measured = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(), radius_nm=1.0)
    lifted = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(), radius_nm=2.5)

    assert measured['band']['centre_line_radius_nm'] == 1.0, 'a setting below the measurement leaves the tube alone'
    assert lifted['band']['centre_line_radius_nm'] == 2.5, 'a setting above it sets the belt'
    assert lifted['band']['slab_radius_nm'] == 1.0, 'and the measured radius it was derived from is still recorded'
    assert lifted['band']['tube_radius_nm'] == MOLECULE_LENGTH_NM, "the setting is not the tube's radius"


def test_a_radius_smaller_than_the_measured_cylinder_changes_nothing(tmp_path):
    points = _asymmetric_protein()
    smaller = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(), radius_nm=0.75)
    measured = pdc_placement.place_detergents(points, _template(tmp_path), 12, seed=4, frame=_frame(), radius_nm=1.0)

    assert smaller['centers'] == measured['centers'], 'the floor is the measured cylinder, not the setting'
    assert smaller['band']['centre_line_radius_nm'] == measured['band']['centre_line_radius_nm'] == 1.0


def test_an_empty_micelle_still_uses_the_radius_as_the_sphere_it_builds(tmp_path):
    """No protein, no measured tube: `radius_nm` is the sphere's own radius, exactly as it was before any floor."""
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
