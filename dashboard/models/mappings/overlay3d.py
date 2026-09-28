"""3D overlay geometry for the mapping workspace: the molecule as a PDB, the beads as spheres.

The panel's 2D depiction already draws each bead as a circle at the mean of the atoms it maps. This is the same
idea in three dimensions, computed here rather than in the browser because the centre and the radius are the
scientific content of the view: a bead's sphere is the claim that these atoms belong together and where their
middle is. That is arithmetic, so it is testable, so it is tested -- the browser only draws what this returns.

Units: a mapping context carries coordinates in nanometres while a PDB file is in angstroms. The conversion is
explicit and covered by a test, because this project has already paid once for guessing which unit it held.

Serials: each written atom's serial is its context atom id. A mapping's bead.atoms is a list of those ids, so the
viewer can address a bead's atoms without a lookup table, and the file and the mapping cannot disagree about which
atom is which.
"""
from __future__ import annotations

NANOMETRE_TO_ANGSTROM = 10.0
# How far beyond the outermost mapped atom a bead's sphere reaches, so the sphere reads as covering its atoms
# rather than barely touching them.
PADDING_ANGSTROM = 0.8
# The molecular-volume classes the composition panel also draws by: R, S and T for a bead mapped to four, three or
# fewer heavy atoms. These are floors, so a single-atom bead still reads as a bead rather than as a dot.
SIZE_RADII = {"R": 2.64, "S": 2.30, "T": 1.91}


def angstrom(atom):
    """One atom's coordinates in angstroms, from a context that holds nanometres."""
    return [float(value) * NANOMETRE_TO_ANGSTROM for value in atom["xyz"]]


def pdb_text(context, *, residue_name="MOL"):
    """A PDB for the molecule's heavy atoms, with bonds as CONECT records.

    Only heavy atoms are written. A mapping assigns heavy atoms and the 2D depiction draws the same set, so a bond
    to a hydrogen would be a bond the user cannot see and cannot check. Bonds whose partner is not written are
    dropped rather than written against a serial that does not exist.
    """
    heavy = [atom for atom in context.get("atoms", []) if atom.get("heavy")]
    serials = {int(atom["id"]) for atom in heavy}
    lines = [f"REMARK 900 {context.get('name') or context.get('molecule_id') or 'Molecule'} mapping overlay",
             "REMARK 900 coordinates converted from nanometres; serials are mapping atom ids"]
    for atom in heavy:
        x, y, z = angstrom(atom)
        element = str(atom.get("element") or "C").strip().upper()
        name = str(atom.get("name") or element)[:4]
        lines.append(f"HETATM{int(atom['id']):5d} {name:<4s} {residue_name:>3s} A{1:4d}    "
                     f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {element[:2]:>2s}")
    for bond in context.get("bonds", []):
        if int(bond["a"]) in serials and int(bond["b"]) in serials:
            lines.append(f"CONECT{int(bond['a']):5d}{int(bond['b']):5d}")
    lines.append("END")
    return "\n".join(lines) + "\n"


def bead_spheres(context, beads):
    """One sphere per bead that maps at least one written atom: where its middle is and how much it covers.

    The centre is the unweighted mean of the mapped atoms, which is what the 2D overlay uses, so a bead reads the
    same in both views. The radius is the distance to its most distant atom plus a small padding, floored by the
    bead's size class: a bead whose atoms sit on top of each other still reads as a bead.

    A bead with no mapped atoms -- a virtual site, which has no coordinates -- is skipped rather than drawn at the
    origin, where it would look like a bead sitting somewhere in the molecule.
    """
    positions = {int(atom["id"]): angstrom(atom) for atom in context.get("atoms", []) if atom.get("heavy")}
    spheres = []
    for bead in beads or []:
        mapped = [int(atom_id) for atom_id in bead.get("atoms") or [] if int(atom_id) in positions]
        if not mapped:
            continue
        points = [positions[atom_id] for atom_id in mapped]
        centre = [sum(point[axis] for point in points) / len(points) for axis in range(3)]
        spread = max((sum((point[axis] - centre[axis]) ** 2 for axis in range(3)) ** 0.5 for point in points),
                     default=0.0)
        floor = SIZE_RADII.get(str(bead.get("size") or "").upper(), SIZE_RADII["T"])
        spheres.append({"name": bead["name"], "atoms": mapped, "size": bead.get("size"),
                        "type": bead.get("type"),
                        "centre": [round(value, 4) for value in centre],
                        "radius": round(max(floor, spread + PADDING_ANGSTROM), 4)})
    return spheres
