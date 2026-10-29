"""The 3D overlay's arithmetic: units, serials, centres and radii.

The panel's 2D view drew bead circles at the mean of their atoms for a long time before anyone checked the
coordinates' units, and this project has already had one coordinate bug from that ambiguity. Everything the 3D view
claims about where a bead is and how much it covers is decided here, so it is decided in a test.
"""
from dashboard.models.mappings import overlay3d


def context_of(atoms, bonds=(), name="Maltose"):
    return {"name": name, "molecule_id": "Maltose", "atoms": atoms,
            "bonds": [{"a": a, "b": b} for a, b in bonds]}


def atom(atom_id, xyz, element="C", heavy=True, name=None):
    return {"id": atom_id, "name": name or element, "residue": "MOL", "element": element,
            "heavy": heavy, "charge": 0.0, "xyz": xyz}


def test_the_pdb_is_written_in_angstroms_from_a_context_that_holds_nanometres():
    """The unit conversion, on a number where guessing the wrong unit is obvious."""
    context = context_of([atom(1, [0.1, 0.2, 0.3])])
    line = [row for row in overlay3d.pdb_text(context).splitlines() if row.startswith("HETATM")][0]
    assert f"{1.0:8.3f}" in line and f"{2.0:8.3f}" in line and f"{3.0:8.3f}" in line, line


def test_a_written_atom_serial_is_its_mapping_atom_id():
    """bead.atoms holds context atom ids, so the serials have to be those ids and not a fresh numbering."""
    context = context_of([atom(7, [0.0, 0.0, 0.0]), atom(9, [0.1, 0.0, 0.0])])
    serials = [int(row[6:11]) for row in overlay3d.pdb_text(context).splitlines() if row.startswith("HETATM")]
    assert serials == [7, 9], serials


def test_hydrogens_are_not_written_and_bonds_to_them_are_not_either():
    """A mapping assigns heavy atoms and the 2D view draws heavy atoms; a hydrogen bond would be invisible."""
    context = context_of([atom(1, [0.0, 0.0, 0.0]), atom(2, [0.1, 0.0, 0.0], element="H", heavy=False),
                          atom(3, [0.2, 0.0, 0.0])], bonds=[(1, 2), (1, 3)])
    text = overlay3d.pdb_text(context)
    assert text.count("HETATM") == 2, text
    conect = [row for row in text.splitlines() if row.startswith("CONECT")]
    assert conect == ["CONECT    1    3"], conect


def test_a_bead_centre_is_the_mean_of_the_atoms_it_maps():
    """Two atoms 1 A apart on x, in a context that holds nanometres: the middle is 0.5 A, not 0.05."""
    context = context_of([atom(1, [0.0, 0.0, 0.0]), atom(2, [0.1, 0.0, 0.0])])
    spheres = overlay3d.bead_spheres(context, [{"name": "B01", "size": "S", "type": "C1", "atoms": [1, 2]}])
    assert len(spheres) == 1
    assert spheres[0]["centre"] == [0.5, 0.0, 0.0], spheres[0]


def test_a_bead_sphere_reaches_its_outermost_atom_and_is_floored_by_its_size_class():
    """The radius is what says how much of the molecule a bead covers, so it is asserted both ways."""
    context = context_of([atom(1, [0.0, 0.0, 0.0]), atom(2, [1.0, 0.0, 0.0])])   # 10 A apart in angstroms
    wide = overlay3d.bead_spheres(context, [{"name": "B01", "size": "T", "atoms": [1, 2]}])[0]
    assert wide["radius"] == round(5.0 + overlay3d.PADDING_ANGSTROM, 4), wide
    tight = overlay3d.bead_spheres(context, [{"name": "B02", "size": "R", "atoms": [1]}])[0]
    assert tight["radius"] == overlay3d.SIZE_RADII["R"], tight


def test_a_bead_with_no_mapped_atoms_is_skipped_rather_than_drawn_at_the_origin():
    """A virtual site has no coordinates: drawing it would put a sphere somewhere it is not."""
    context = context_of([atom(1, [0.0, 0.0, 0.0])])
    spheres = overlay3d.bead_spheres(context, [{"name": "VS1", "size": "T", "atoms": []},
                                               {"name": "B01", "size": "T", "atoms": [1]},
                                               {"name": "B02", "size": "T", "atoms": [99]}])
    assert [sphere["name"] for sphere in spheres] == ["B01"], spheres


def test_the_bead_file_puts_one_atom_per_bead_at_its_centre_and_names_its_size_class():
    """The overlay's own file: a viewer draws each atom as a sphere whose radius comes from the class.

    A representation has one radius scale, so beads of different sizes need different representations; putting each
    bead's class in the residue column is what lets the client group them. The serial is the bead's position, which
    is how a clicked sphere is turned back into the bead.
    """
    context = context_of([atom(1, [0.0, 0.0, 0.0]), atom(2, [0.2, 0.0, 0.0])])
    beads = [{"name": "B01", "size": "S", "atoms": [1, 2]}, {"name": "B02", "size": "R", "atoms": [1]}]
    text = overlay3d.bead_pdb_text(context, beads)
    rows = [row for row in text.splitlines() if row.startswith("HETATM")]
    # The class lives in the residue column: a bare word in the viewer's selection language is a residue name.
    assert [row[17:20].strip() for row in rows] == ["S", "R"], rows
    assert [int(row[6:11]) for row in rows] == [1, 2], rows
    assert f"{1.0:8.3f}" in rows[0], rows[0]        # the centre of (0, 0, 0) and (0.2, 0, 0) nm is 1 A on x
    # One row per bead that has atoms, taken from the same call the file is written from.
    assert text.count("HETATM") == len(overlay3d.bead_spheres(context, beads)), text


def test_a_virtual_site_has_no_row_in_the_bead_file_either():
    """Otherwise a viewer would draw a sphere at the origin for a bead that has no atoms."""
    context = context_of([atom(1, [0.0, 0.0, 0.0])])
    text = overlay3d.bead_pdb_text(context, [{"name": "VS1", "size": "T", "atoms": []}])
    assert "HETATM" not in text, text
