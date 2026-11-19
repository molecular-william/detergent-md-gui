"""The user's report of 2026-10-14: with one or two subunits selected the plane should shrink, and the
detergent tails should face the transmembrane centre rather than sitting parallel.

Both halves are measured here rather than described, and the measurement says two different things:

* **the plane.** The slab radius is measured from the SELECTED chains' own atoms inside the membrane frame's slab, so
  a selection whose atoms reach a smaller radius measures a smaller radius -- and, above the default radius the
  placement treats as a floor, the belt is placed on that smaller cylinder surface. A *deposited trimer* is the case that
  hides it: its chains are three-fold about the membrane axis, so one chain, two chains and three chains all reach
  the same radius. 1AT9 is exactly that protein (measured in the report beside this file), so the report's first half
  is not reproducible on it and its expectation is right in general.
* **the tails.** Every site's direction is its own meridian, so the belt has one distinct direction per detergent and
  every tail points at the tube's centre-line at its own azimuth. The committed placement is therefore not parallel
  and not in the membrane plane; `test_no_two_detergents_share_an_orientation` measures that.

Nothing here reads the developer's workspace: every structure is built by the fixture below.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from detergent_pdc.execution import pdc_preview
from detergent_pdc.execution.adapters import pdc_import, pdc_placement
from detergent_pdc.execution.scripts import pdc_build
from micelle.frame import frame_from_pdb, unit_axis
from micelle.registry import load_template

#: The molecule's own length, written into the template's coordinate file in Angstroms: it is what the tube's radius
#: is measured from, so it has to be readable for the belt to exist at all.
MOLECULE_LENGTH_NM = 2.0
#: The membrane the fixture structures state for themselves, so the placement takes the tube's branch.
HALF_THICKNESS_NM = 1.48
#: A four-bead detergent of the shape `stamp` orients: a two-bead tail and a two-bead head, 1.0 nm end to end.
DRAFT = {'residue': 'DDM', 'beads': [{'name': 'C1A', 'type': 'C1', 'position': [0.0, 0.0, 0.0]},
                                    {'name': 'C1B', 'type': 'C1', 'position': [0.33, 0.0, 0.0]},
                                    {'name': 'H1A', 'type': 'SN6', 'position': [0.66, 0.0, 0.0]},
                                    {'name': 'H1B', 'type': 'SN6', 'position': [1.0, 0.0, 0.0]}]}


def molecule_file(directory: Path, length_nm: float = MOLECULE_LENGTH_NM) -> Path:
    """The molecule the template names, as a PDB: two atoms `length_nm` apart, which is its measured reach."""
    path = directory / 'beads.pdb'
    path.write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000  1.00  0.00\n'
                    f'HETATM    2  C2  DDM A   1   {length_nm * 10.0:8.3f}   0.000   0.000  1.00  0.00\n')
    return path


def template(directory: Path, length_nm: float = MOLECULE_LENGTH_NM):
    """A template with a measurable molecule, loaded the way the builders load one."""
    directory.mkdir(parents=True, exist_ok=True)
    molecule_file(directory, length_nm)
    (directory / 'beads.itp').write_text('[ moleculetype ]\nDDM 1\n')
    path = directory / 'micelle_template.json'
    path.write_text(json.dumps({'name': 'DDM', 'residue': 'DDM', 'coordinates': 'beads.pdb',
                                'topology': 'beads.itp', 'beads': [{'name': 'DDM', 'type': 'registered'}],
                                'headgroup': [0, 0, 0], 'tail_direction': [0, 0, -1]}))
    return load_template(path)


def ring(radius_nm: float, *, z_nm: float = 0.2, count: int = 24, phase: float = 0.0):
    """`count` atoms on a ring of `radius_nm` inside the slab, in nanometres."""
    angles = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False) + phase
    return [[radius_nm * float(np.cos(angle)), radius_nm * float(np.sin(angle)), z_nm] for angle in angles]


def structure(directory: Path, chains, *, name: str = 'stated.pdb', stated: bool = True) -> Path:
    """A structure whose named chains reach the radii given: `chains` is `[(chain_id, [points...]), ...]`.

    `stated` writes the `REMARK` a structure states its own membrane with, which is the whole of what decides the
    placement's shape. The records are written in a PDB's Angstroms, as every reader here expects.
    """
    directory.mkdir(parents=True, exist_ok=True)
    lines = [f'REMARK      1/2 of bilayer thickness:   {HALF_THICKNESS_NM * 10:>5.1f}' if stated else 'REMARK  none']
    serial = 0
    for chain, points in chains:
        for index, point in enumerate(points, start=1):
            serial += 1
            lines.append(f'ATOM  {serial:5d}  CA  ALA {chain}{index:4d}    '
                         f'{point[0] * 10.0:8.3f}{point[1] * 10.0:8.3f}{point[2] * 10.0:8.3f}'
                         f'  1.00  0.00           C')
    path = directory / name
    path.write_text('\n'.join(lines) + '\nEND\n')
    return path


def placement_for(stage: Path, source: Path, chains, count: int, *, radius_nm=pdc_placement.DEFAULT_RADIUS_NM,
                  belt_floor_nm=0.0):
    """What the build would place for this selection: the stage's own chain filter, frame and placement step."""
    stage.mkdir(parents=True, exist_ok=True)
    selected, _, _ = pdc_build.select_protein(stage, source, chains)
    points = [list(atom['position']) for atom in pdc_import.structure_atoms(selected)]
    frame = frame_from_pdb(selected)
    placed = pdc_placement.place_detergents(points, template(stage / 'molecule'), count, seed=20261014,
                                            frame=frame, radius_nm=radius_nm, belt_floor_nm=belt_floor_nm)
    return placed, frame


def distance_to_axis(sites, axis, origin):
    """Each site's radial distance from the cylinder's axis, as `test_pdc_placement` measures it."""
    sites = np.asarray(sites, dtype=float)
    axis = np.asarray(axis, dtype=float)
    relative = sites - np.asarray(origin, dtype=float)
    axial = relative @ axis
    return np.linalg.norm(relative - np.outer(axial, axis), axis=1)


# --- half one: the plane, and the selection ---------------------------------------------------------------

def test_the_measured_slab_radius_shrinks_with_the_selection(tmp_path):
    """"The plane should shrink correspondingly": measured from the selected chains' own atoms, it does.

    One chain reaches 3.0 nm inside the slab and the other 1.0 nm, so the measurement is the selection's. Both stay
    inside the stated slab, so the second chain is not quietly measured as absent.
    """
    source = structure(tmp_path, [('A', ring(3.0)), ('B', ring(1.0))])
    assert frame_from_pdb(source) is not None, 'the fixture must state its own membrane for this to be the tube'

    one, _ = placement_for(tmp_path / 'a', source, ['A'], 12)
    other, _ = placement_for(tmp_path / 'b', source, ['B'], 12)
    both, _ = placement_for(tmp_path / 'ab', source, ['A', 'B'], 12)

    assert one['band']['slab_radius_nm'] == pytest.approx(3.0, abs=1e-4)
    assert other['band']['slab_radius_nm'] == pytest.approx(1.0, abs=1e-4)
    assert both['band']['slab_radius_nm'] == pytest.approx(3.0, abs=1e-4), \
        'the union reaches what its widest chain reaches, and no further'


def test_the_selection_moves_the_belt_whenever_the_measurement_is_over_the_floor(tmp_path):
    """A radius stated below both measurements is only a floor, so the belt follows each selection's own cylinder.

    Chain B is six atoms here and not twenty-four. The slab radius is the *furthest* in-slab atom, and a ring of
    twenty-four atoms all at exactly that radius (0.26 nm apart) leaves no azimuth clear: every detergent's tail bead
    reaches the centre-line, and the bead-level gate (0.25 nm) refuses all of them, so the belt is empty and there is
    no surface to measure. A real cross-section has one atom at its furthest point and the rest inside it; six atoms
    keep the measurement exact (1.0 nm) and leave the belt placeable, which is what this test is about.
    """
    source = structure(tmp_path, [('A', ring(3.0)), ('B', ring(1.0, count=6))])

    one, _ = placement_for(tmp_path / 'a', source, ['A'], 12, belt_floor_nm=1.0)
    other, _ = placement_for(tmp_path / 'b', source, ['B'], 12, belt_floor_nm=1.0)

    assert one['band']['radius_nm'] == pytest.approx(3.0, abs=1e-4)
    assert other['band']['radius_nm'] == pytest.approx(1.0, abs=1e-4)
    assert other['band']['detergent_length_nm'] == pytest.approx(MOLECULE_LENGTH_NM)
    # And the placed sites stand off the smaller cylinder's surface, not the larger one's: the belt really moved.
    assert len(other['centers']) == 12
    cylinder = other['band']['cylinder']
    distances = distance_to_axis(other['centers'], cylinder['axis'], cylinder['origin_nm'])
    assert np.allclose(distances, cylinder['surface_radius_nm'] + MOLECULE_LENGTH_NM, atol=1e-5)


def test_a_selection_under_the_default_radius_follows_its_measured_cylinder(tmp_path):
    """The belt follows the selection's own measurement, not the sphere's 3.0 nm default.

    `radius_nm` is the sphere's radius, not a belt floor any more: the belt surface is measured from the selected
    transmembrane atoms, and the old 3.0 nm floor that used to hold a small selection out on the default belt is
    gone. A selection that measures 1.0 nm is therefore placed on a 1.0 nm belt, and its `radius_source` says the
    measurement decided.
    """
    source = structure(tmp_path, [('A', ring(3.0)), ('B', ring(1.0))])

    placed, _ = placement_for(tmp_path / 'b', source, ['B'], 12)

    assert placed['band']['slab_radius_nm'] == pytest.approx(1.0, abs=1e-4), 'the measurement shrank'
    assert placed['band']['cylinder']['radius_nm'] == pytest.approx(1.0, abs=1e-4)
    assert placed['band']['radius_floor_nm'] == 0.0
    assert placed['band']['radius_nm'] == pytest.approx(1.0, abs=1e-4), \
        'the belt surface is the measured cylinder, not the sphere default'
    assert placed['band']['radius_source'] == 'measured'


def test_a_three_fold_selection_leaves_the_measured_radius_unchanged(tmp_path):
    """Why the report does not reproduce on 1AT9: its chains are three-fold about the membrane axis.

    Each chain here is the same motif turned by 120 degrees, so every selection reaches the same radius -- one
    subunit, two, or all three. That is the deposited trimer's own situation, measured on 1AT9's file at 3.2202 nm
    from its atoms (3.1408 nm from the coarse-grained beads a placement actually measures) for chain A, for A+B and
    for A+B+C alike.
    """
    turn = 2.0 * np.pi / 3.0
    source = structure(tmp_path, [('A', ring(3.0, phase=0.0)), ('B', ring(3.0, phase=turn)),
                                  ('C', ring(3.0, phase=2.0 * turn))])

    radii = []
    for index, chains in enumerate((['A'], ['A', 'B'], ['A', 'B', 'C'])):
        placed, _ = placement_for(tmp_path / f'sel{index}', source, chains, 12)
        radii.append(placed['band']['slab_radius_nm'])

    assert radii == pytest.approx([3.0, 3.0, 3.0], abs=1e-4), \
        'a three-fold assembly measures the same cylinder whichever of its subunits is selected'


def test_a_subset_keeps_the_proteins_own_membrane_statement(tmp_path):
    """The frame survives the chain filter, which is what lets a subset be placed as a belt at all."""
    source = structure(tmp_path, [('A', ring(3.0)), ('B', ring(1.0))])

    placed, frame = placement_for(tmp_path / 'a', source, ['A'], 12)

    assert frame is not None and frame.half_thickness_nm == HALF_THICKNESS_NM
    assert placed['placement_shape'] == 'belt-cylinder'


# --- half two: the tails, and the centre-line ------------------------------------------------------------

def test_no_two_detergents_share_an_orientation_so_the_belt_is_not_parallel(tmp_path):
    """"The tails are still in a parallel orientation": measured over a placed belt, they are not.

    Each site's direction is its own outward normal, tilted about its own tangent -- so the belt has one distinct
    direction per detergent and no shared heading. A parallel belt would repeat one direction, have a zero spread of
    azimuths, and a mean direction of unit length; the three are measured here.
    """
    source = structure(tmp_path, [('A', ring(1.5))])
    placed, frame = placement_for(tmp_path / 'a', source, ['A'], 60, radius_nm=1.5)

    directions = np.asarray(placed['directions'])
    axis = np.asarray(unit_axis(frame.axis), dtype=float)
    origin = np.asarray(placed['band']['cylinder']['origin_nm'])
    centres = np.asarray(placed['centers'])
    relative = centres - origin
    heights = relative @ axis
    radial = relative - np.outer(heights, axis)
    outward = radial / np.linalg.norm(radial, axis=1)[:, None]
    assert len(directions) == 60 and np.allclose(np.linalg.norm(directions, axis=1), 1.0)

    distinct = {tuple(np.round(row, 9)) for row in directions}
    separations = np.degrees(np.arccos(np.clip(directions @ directions.T, -1.0, 1.0)))
    np.fill_diagonal(separations, np.nan)
    assert len(distinct) == len(directions), 'no two detergents may share a direction'
    assert float(np.nanmin(separations)) > 0.1, 'and no two may be effectively the same orientation'
    assert float(np.linalg.norm(directions.mean(axis=0))) < 0.25, \
        'parallel bodies would have a mean of unit length'

    # The constant tilt is the one the placement documents, and the azimuths still wrap the whole belt.
    tilt = np.degrees(np.arccos(np.clip((directions * outward).sum(axis=1), -1.0, 1.0)))
    assert np.allclose(tilt, pdc_placement.TILT_DEGREES), 'every body is the same documented tilt'
    across, up = pdc_placement._plane_basis(axis)
    azimuths = np.arctan2(outward @ up, outward @ across)
    assert float(azimuths.max() - azimuths.min()) > 0.9 * 2.0 * np.pi, 'the belt wraps the whole circumference'
    # The ladder's entries never reach |z| = 1 exactly, so the band is covered just short of its edges.
    assert 0.95 * placed['band']['vertical_half_band_nm'] < float(np.abs(heights).max()) \
        <= placed['band']['vertical_half_band_nm'] + 1e-6


def test_every_tail_dips_inwards_from_its_own_outward_normal(tmp_path):
    """The tail's heading is the outward normal tilted towards the axis, not a single belt-wide heading.

    `stamp` hangs the body back along `-direction`, so the head-ward direction's radial component is `cos` of the
    documented tilt and the tail end therefore sits `length * cos(tilt)` closer to the axis than the head end. Each
    site's own azimuth gives it its own normal, so the belt is not one heading.
    """
    source = structure(tmp_path, [('A', ring(1.5))])
    placed, frame = placement_for(tmp_path / 'a', source, ['A'], 60, radius_nm=1.5)

    axis = np.asarray(unit_axis(frame.axis), dtype=float)
    origin = np.asarray(placed['band']['cylinder']['origin_nm'])
    centres = np.asarray(placed['centers'])
    directions = np.asarray(placed['directions'])
    relative = centres - origin
    heights = relative @ axis
    radial = relative - np.outer(heights, axis)
    outward = radial / np.linalg.norm(radial, axis=1)[:, None]

    tilt = np.degrees(np.arccos(np.clip((directions * outward).sum(axis=1), -1.0, 1.0)))
    assert np.allclose(tilt, pdc_placement.TILT_DEGREES), 'every tail dips by the documented tilt'

    # And the tail end is closer to the axis than the head end by exactly that tilt's own radial loss.
    head_radial = np.linalg.norm(radial, axis=1)
    tail_radial = np.linalg.norm(radial - MOLECULE_LENGTH_NM * np.cos(np.deg2rad(pdc_placement.TILT_DEGREES))
                                 * outward, axis=1)
    assert np.all(tail_radial < head_radial)
    assert np.allclose(head_radial - tail_radial,
                       MOLECULE_LENGTH_NM * np.cos(np.deg2rad(pdc_placement.TILT_DEGREES)))


def test_the_stamped_molecule_follows_its_own_sites_direction(tmp_path):
    """No second orientation is applied afterwards: the stamped body's own axis is the placement's direction.

    `stamp` rotates the molecule rigidly from its head-ward axis onto the direction it is handed, so the mean head
    bead minus the mean tail bead of every copy is that copy's own direction -- not a belt-wide heading.
    """
    source = structure(tmp_path, [('A', ring(1.5))])
    placed, frame = placement_for(tmp_path / 'a', source, ['A'], 24, radius_nm=1.5)
    atoms = pdc_build.stamp(DRAFT, placed['centers'], placed['directions'], first_residue=10)

    molecules: dict[int, list[dict]] = {}
    for atom in atoms:
        molecules.setdefault(atom['residue_id'], []).append(atom)
    assert len(molecules) == 24

    for (centre, direction), beads in zip(zip(placed['centers'], placed['directions']), molecules.values()):
        head = np.mean([atom['position'] for atom in beads if atom['name'].startswith('H1')], axis=0)
        tail = np.mean([atom['position'] for atom in beads if atom['name'].startswith('C1')], axis=0)
        own = head - tail
        own = own / np.linalg.norm(own)
        # A tolerance a hundred times the 1e-5 the beads are rounded to in the written file.
        assert np.allclose(own, direction, atol=1e-4), 'the body is oriented by its own site, per site'
        # The molecule's head end stands outside the cylinder surface by the molecule's own length.
        head_end = max((np.asarray(atom['position']) for atom in beads if atom['name'].startswith('H1')),
                       key=lambda point: float(np.dot(point - np.asarray(centre), direction)))
        cylinder = placed['band']['cylinder']
        assert distance_to_axis([head_end], cylinder['axis'], cylinder['origin_nm'])[0] == \
            pytest.approx(cylinder['surface_radius_nm'] + placed['band']['detergent_length_nm'], abs=1e-4)


# --- the preview's own report of the belt's radius --------------------------------------------------------

def cg_beads(radius_nm: float, *, z_nm: float = 0.2, count: int = 12):
    """Coarse-grained beads on a ring of `radius_nm` inside the slab, in the shape `preview` reads them in."""
    return [{'residue_id': 1, 'residue': 'PRO', 'name': f'B{index:03d}', 'position': point}
            for index, point in enumerate(ring(radius_nm, z_nm=z_nm, count=count), start=1)]


def stub_coarse_grained(monkeypatch, tmp_path, beads):
    """The CG step, stubbed: what is under test is the placement and what the service reports about it."""
    monkeypatch.setattr(pdc_preview, 'coarse_grained',
                        lambda *args, **kwargs: (beads, {'cached': True, 'seconds': 0.0, 'key': 'stub',
                                                         'path': str(tmp_path / 'entry'), 'beads_bytes': 0,
                                                         'dropped_residues': [], 'protein_input': 'protein.pdb',
                                                         'command': None}))


def preview_basis(tmp_path, monkeypatch, radius_nm: float):
    """The basis the panel renders for a protein that states its own membrane and coarse-grains to `radius_nm`."""
    source = structure(tmp_path, [('A', ring(radius_nm))], name='protein.pdb')
    stub_coarse_grained(monkeypatch, tmp_path, cg_beads(radius_nm))
    template_path = tmp_path / 'template' / 'micelle_template.json'
    template(tmp_path / 'template')
    answer = pdc_preview.preview(project_root=tmp_path, cache_root=tmp_path / 'cache', template=str(template_path),
                                 protein=str(source), chains=['A'], aggregation_number=24, seed=20261014)
    assert answer['valid'], answer['reasons']
    return answer['basis']


def test_the_panel_number_is_the_belts_own_radius_and_not_the_detergents_length(tmp_path, monkeypatch):
    """"The hydrophobic plane should shrink correspondingly": the number the panel states must be that plane.

    The belt is a cylinder whose surface radius is measured from the selected transmembrane atoms; the card renders
    `basis.band_radius_nm` as "the belt is a band of radius X nm in the membrane plane". That field used to carry the
    torus's *tube* radius -- the detergent's own length, the same 2.0 nm for every selection -- so a reader checking
    whether the plane shrank with the subunits saw one constant number. It is the cylinder's own surface radius where
    the sentence says it is, and it moves when the selection moves the cylinder.
    """
    one = preview_basis(tmp_path / 'one', monkeypatch, 3.5)
    other = preview_basis(tmp_path / 'other', monkeypatch, 4.5)

    assert one['band_radius_nm'] == pytest.approx(3.5, abs=1e-4), "the belt's own cylinder surface radius"
    assert one['band_radius_nm'] != MOLECULE_LENGTH_NM, "not the detergent's length"
    assert one['detergent_length_nm'] == pytest.approx(MOLECULE_LENGTH_NM), 'which is stated under its own name'
    assert one['slab_radius_nm'] == pytest.approx(3.5, abs=1e-4)
    assert other['band_radius_nm'] == pytest.approx(4.5, abs=1e-4), \
        'the plane follows the selection, which is the whole of the report'
