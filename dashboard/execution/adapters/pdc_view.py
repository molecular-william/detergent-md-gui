"""The system view: what the panel renders, written from the coordinates so the picture cannot disagree with it.

Water and ions are excluded by default. They dominate the atom count, and the point of this view is the protein and
the detergent belt around it; a viewer handed every bead shows a box of water with no visible aggregate.

The element is a neutral stand-in ('C') rather than a chemistry claim, because a coarse-grained bead has no element:
the size class lives in a mapping or a topology, and until this workflow carries one the radii are uniform. The
docstring says so rather than implying a calibrated picture.
"""
from pathlib import Path

PROTEIN_RESIDUE = 'PRO'
DETERGENT_RESIDUE = 'DET'
WATER_RESIDUES = ('W', 'SW', 'PW', 'NA', 'CL')
BEAD_ELEMENT = 'C'


def read_gro(path):
    """The atoms of a GROMACS .gro: one `{'residue_id', 'residue', 'name', 'position'}` per bead, in nanometres.

    The residue *number* comes back as well as the name, because a system with eight detergents has eight residues
    all called `DDM` and the criterion has to tell them apart.

    A parser rather than a dependency: the viewer route should not import a trajectory library to draw a system, and
    the format is fixed-width and trivial to read.
    """
    lines = Path(path).read_text().splitlines()
    if len(lines) < 2:
        raise ValueError(f'{path} is not a .gro file')
    try:
        count = int(lines[1].strip())
    except ValueError as exc:
        raise ValueError(f'{path} does not state an atom count on its second line') from exc
    atoms = []
    body = lines[2:2 + count]
    if len(body) != count:
        raise ValueError(f'{path} declares {count} atoms and holds {len(body)}')
    for line in body:
        if len(line) < 44:
            raise ValueError(f'{path} has a truncated atom line: {line!r}')
        try:
            residue_id = int(line[0:5])
        except ValueError as exc:
            raise ValueError(f'{path} has an unreadable residue number: {line!r}') from exc
        atoms.append({'residue_id': residue_id, 'residue': line[5:10].strip(), 'name': line[10:15].strip(),
                      'position': [float(line[20:28]), float(line[28:36]), float(line[36:44])]})
    return atoms


def read_gro_box(path) -> list[float]:
    """A .gro's box vector, so a structure written from another one can keep its own box."""
    lines = Path(path).read_text().splitlines()
    if not lines:
        raise ValueError(f'{path} is not a .gro file')
    try:
        return [float(value) for value in lines[-1].split()]
    except ValueError as exc:
        raise ValueError(f'{path} has an unreadable box line: {lines[-1]!r}') from exc


def system_pdb(atoms, *, detergent_residue='DDM', include_water=False, title='PDC system'):
    """A PDB for the viewer: one HETATM per bead, protein as PRO, detergent as DET, water and ions dropped.

    The detergent is identified by the residue the template declares, so the caller names it rather than this module
    guessing; everything that is not the detergent and not solvent is protein, which is what the box holds.
    """
    kept = [atom for atom in atoms if include_water or atom['residue'].upper() not in WATER_RESIDUES]
    lines = [f'REMARK 950 {title.upper()}: COARSE-GRAINED SYSTEM AS SET UP, WATER AND IONS OMITTED',
             'REMARK 950 ELEMENTS ARE RADIUS STAND-INS, NOT CHEMISTRY']
    for serial, atom in enumerate(kept, start=1):
        name = atom['name'][:4]
        residue = (DETERGENT_RESIDUE if atom['residue'].upper() == detergent_residue.upper()
                   else PROTEIN_RESIDUE)
        x, y, z = (round(float(value) * 10.0, 3) for value in atom['position'])  # nm -> Angstrom, as PDB is
        lines.append(f'HETATM{serial:5d} {name:<4s} {residue:>3s} A{1:4d}    {x:8.3f}{y:8.3f}{z:8.3f}'
                     f'{1.0:6.2f}{0.0:6.2f}          {BEAD_ELEMENT:>2s}')
    lines.append('END')
    return '\n'.join(lines) + '\n'
