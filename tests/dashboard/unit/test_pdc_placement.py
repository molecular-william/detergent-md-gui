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
from dashboard.execution.adapters.pdc_box import initial_box
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


def test_a_protein_that_states_no_membrane_gets_a_shell_measured_from_it(tmp_path):
    """`frame=None` is every packaged protein and every import that states nothing: the sphere, now measured.

    The radius used to *be* the setting -- the same 3.0 nm about every protein, whatever the selection reached. It is
    now the greater of the setting and `extent about the centroid + the clearance + the molecule's own length`, the
    relationship the belt's centre-line already had: the protein decides and the setting is only a floor. This protein
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


def test_no_detergent_bead_lands_inside_a_protein_the_tube_wraps(tmp_path):
    """The same gate on the belt: a second ring inside the tube's own volume, where only a body can reach it.

    The in-slab ring sets the measured cylinder (2.0 nm) and the tube's radius is the molecule's own 2.0 nm, so the
    sites stand at 4.0 nm in the membrane plane while every body reaches back to the centre-line. A ring at 3.0 nm
    sits on that path: a head site is a nanometre clear of it, and the tail is what comes within the gate.
    """
    template = _template(tmp_path)                       # two atoms, 2.0 nm apart
    points = _ring(2.0, 0.0) + _ring(3.0, 0.0, count=12)

    placed = pdc_placement.place_detergents(points, template, 12, seed=4, frame=_frame(), radius_nm=2.0)

    assert placed['valid'], placed['issues']
    assert placed['placement_shape'] == 'belt-torus'
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
    """A torus's volume is its own (Pappus), so the panel's density sentence reads the same field for either shape."""
    placed = pdc_placement.place_detergents(_asymmetric_protein(), _template(tmp_path), 12, seed=4, frame=_frame(),
                                            radius_nm=1.0)

    band = placed['band']
    volume = 2.0 * np.pi ** 2 * band['centre_line_radius_nm'] * band['tube_radius_nm'] ** 2
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

