"""Detergent placement: the builder's geometry plus the gates that decide whether a run may proceed.

The properties worth pinning are the ones a reader would otherwise have to trust: the count is exact, the same seed
gives the same positions while a different seed does not, every detergent is outside the protein, and an impossible
packing is reported as an issue rather than handed back as coordinates for a run to fail on later.
"""
import json

import numpy as np
import pytest

from dashboard.execution.adapters import pdc_placement
from micelle.frame import frame_from_structure
from micelle.registry import load_template

PROTEIN = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


def _template(tmp_path):
    (tmp_path / 'x.pdb').write_text('')
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


# --- the band: the shape a protein that states its own membrane is placed in --------------------------------

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


def test_a_stated_membrane_puts_the_lattice_on_a_band_rather_than_a_sphere():
    """The lattice's shape is the membrane's when the structure states one: a cylinder band in the bilayer plane."""
    points = _asymmetric_protein()
    placed = pdc_placement.place_detergents(points, None, 12, seed=4, frame=_frame())

    centres = np.asarray(placed['centers'])
    axis = np.array([0.0, 0.0, 1.0])
    axial = centres @ axis
    transverse = np.linalg.norm(centres - np.outer(axial, axis), axis=1)

    assert placed['valid'], placed['issues']
    assert placed['placement_shape'] == 'belt-band'
    # The band's own radius: the furthest atom *inside the slab* (1.0 nm), plus the clearance the gate asks for --
    # not the 5.0 nm the soluble domain reaches, and not the shell's fixed 3.0 nm about the centroid.
    assert placed['band']['radius_nm'] == 1.5
    assert placed['band']['slab_radius_nm'] == 1.0, 'the radius it was derived from, so a reader can re-add the gate'
    assert (placed['band']['plane_low_nm'], placed['band']['plane_high_nm']) == (-1.0, 1.0)
    assert np.all(np.abs(axial) < 1.0), 'every centre is inside the bilayer slab the structure stated'
    assert axial.max() - axial.min() > 1.5, 'the band spans the slab rather than a single ring at one z'
    assert np.allclose(transverse, 1.5), 'the band is one radius, measured from the membrane axis'
    assert placed['protein_clearance_nm'] >= pdc_placement.MIN_CLEARANCE_NM

    centroid = np.asarray(points).mean(axis=0)
    assert not np.allclose(np.linalg.norm(centres - centroid, axis=1), pdc_placement.DEFAULT_RADIUS_NM), \
        'a sphere about the centroid is the shape this replaces'


def test_a_protein_that_states_no_membrane_keeps_the_sphere_it_had():
    """`frame=None` is every packaged protein and every import that states nothing: the shell, byte for byte."""
    points = _asymmetric_protein()
    placed = pdc_placement.place_detergents(points, None, 12, seed=4)

    centres = np.asarray(placed['centers'])
    centroid = np.asarray(points).mean(axis=0)

    assert placed['placement_shape'] == 'sphere' and placed['band'] is None and placed['frame'] is None
    assert np.allclose(np.linalg.norm(centres - centroid, axis=1), pdc_placement.DEFAULT_RADIUS_NM)


def test_a_stated_membrane_the_protein_sits_entirely_outside_keeps_the_sphere():
    """No atom in the slab means no measured band radius, and a guessed one is not one: the caller keeps the shell."""
    placed = pdc_placement.place_detergents(_ring(1.0, 3.0) + _ring(5.0, 3.0), None, 8, seed=3, frame=_frame())

    assert placed['placement_shape'] == 'sphere' and placed['band'] is None


def test_an_empty_micelle_is_the_same_sphere_with_a_frame_as_without_one(tmp_path):
    """The user's decision: no protein, a simple sphere -- and a frame handed over with it changes nothing."""
    without = pdc_placement.place_detergents(None, None, 8, seed=3)
    stated = pdc_placement.place_detergents(None, None, 8, seed=3, frame=_frame())

    assert stated['centers'] == without['centers'] and stated['directions'] == without['directions']
    assert stated['placement_shape'] == 'sphere' and stated['protein_free']
    assert np.allclose(np.linalg.norm(np.asarray(stated['centers']), axis=1), pdc_placement.DEFAULT_RADIUS_NM)


def test_a_band_faces_the_way_the_frame_states_rather_than_the_way_z_does():
    """A y-facing bilayer is the case a reader that indexed z would place every detergent outside of."""
    axis = np.array([0.0, 1.0, 0.0])
    points = [[2.0 * np.cos(a), 0.2, 2.0 * np.sin(a)] for a in np.linspace(0.0, 2.0 * np.pi, 12, endpoint=False)]
    placed = pdc_placement.place_detergents(points, None, 12, seed=4, frame=_frame(axis=tuple(axis)))

    centres = np.asarray(placed['centers'])
    directions = np.asarray(placed['directions'])

    assert placed['placement_shape'] == 'belt-band' and placed['valid'], placed['issues']
    assert np.all(np.abs(centres @ axis) < 1.0), 'the band lies in the plane the frame states'
    assert np.allclose(directions @ axis, 0.0), 'a belt detergent faces across its membrane, not along it'


def test_the_band_direction_is_the_way_out_of_the_belt_not_the_way_out_of_the_centroid():
    """The one convention `stamp` aims the detergent's head-ward axis with, on the band's own geometry."""
    points = _asymmetric_protein()
    placed = pdc_placement.place_detergents(points, None, 12, seed=4, frame=_frame())

    centres = np.asarray(placed['centers'])
    directions = np.asarray(placed['directions'])
    axis = np.array([0.0, 0.0, 1.0])
    headings = centres - np.outer(centres @ axis, axis)

    assert np.allclose(np.linalg.norm(directions, axis=1), 1.0)
    assert np.allclose(directions, headings / np.linalg.norm(headings, axis=1)[:, None]), \
        'the direction is the band site\'s own heading, away from the membrane axis'

    centroid = np.asarray(points).mean(axis=0)
    from_centroid = centres - centroid
    from_centroid = from_centroid / np.linalg.norm(from_centroid, axis=1)[:, None]
    assert not np.allclose(directions, from_centroid), \
        'the centroid is off the membrane, so it is not the point the belt faces away from'


def test_the_band_is_seeded_and_holds_no_two_sites_closer_than_the_overlap_gate(tmp_path):
    placed = pdc_placement.place_detergents(_ring(2.0, 0.3), None, 40, seed=11, frame=_frame())
    again = pdc_placement.place_detergents(_ring(2.0, 0.3), None, 40, seed=11, frame=_frame())
    other = pdc_placement.place_detergents(_ring(2.0, 0.3), None, 40, seed=12, frame=_frame())

    centres = np.asarray(placed['centers'])
    separations = np.linalg.norm(centres[:, None, :] - centres[None, :, :], axis=2)
    np.fill_diagonal(separations, np.inf)

    assert placed['valid'], placed['issues']
    assert len(centres) == 40, 'the requested count is the count that is placed'
    assert placed['centers'] == again['centers'], 'the seed decides the band too'
    assert other['centers'] != placed['centers'], 'a different seed must place differently'
    assert separations.min() >= pdc_placement.MIN_DISTANCE_NM


def test_a_band_that_cannot_clear_the_protein_is_refused_with_the_reason_it_has_always_given():
    """A band is not a licence to place anyway: the same gate judges it, and failing it stops the build."""
    points = _ring(2.0, 0.3)
    placed = pdc_placement.place_detergents(points, None, 12, seed=4, frame=_frame())
    axis = np.array([0.0, 0.0, 1.0])
    centres = np.asarray(placed['centers'])
    top = centres[int(np.argmax(centres @ axis))]
    assert placed['valid'], placed['issues']

    # An atom just outside the slab, directly under the topmost site: the slab cannot see it, so the band's radius
    # does not grow for it -- and what stops the build is the clearance gate, not a band quietly moved out of its way.
    refused = pdc_placement.place_detergents(points + [[float(top[0]), float(top[1]), 1.02]], None, 12, seed=4,
                                             frame=_frame())

    assert not refused['valid']
    assert any(issue.startswith('detergent too close to the protein') for issue in refused['issues'])
    assert refused['protein_clearance_nm'] < pdc_placement.MIN_CLEARANCE_NM

