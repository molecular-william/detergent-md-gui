"""The hydrophobic-surface encapsulation estimate: a pre-run sizing aid, from a structure alone.

Before a protein-detergent run, this says whether the number of detergents the reader asked for is the right order
of magnitude for the protein's apolar surface in the membrane. Five steps: per-atom solvent-accessible area of the
protein; restrict to the transmembrane slab; sum the slab's apolar surface; divide by the area one detergent's head
bead covers; report the count the surface implies, the count that was asked for, and what fraction of the surface
that count would cover.

What it is not is as important as what it is. It treats the protein as a flat surface -- no curvature, no packing,
no shape -- so it says "N detergents is roughly the right order" and never "the micelle forms". The run's own
assessment decides that. `ESTIMATE_CAVEAT` carries the sentence so a reader sees it beside the number instead of
having to know it.

The arithmetic and the numerics are separable on purpose. `slab_area`, `counts` and the size-class readers are pure
functions of values handed in, so a test pins them with numbers chosen by hand; `estimate` is the one place that
reaches for a surface library, and it is pinned against structures whose area is analytic. Nothing here runs
GROMACS, and a SASA implementation is never the thing being tested.
"""
from __future__ import annotations

import math
import re

import numpy as np

from ...models.sugars import recognition
from .surfaces import AA_RADII, PROBE

# The probe and the element radii are the house surface conventions, imported rather than restated: a second copy
# would be a second convention, and the two would drift. `PROBE_NM` and `ATOM_RADII_NM` are the names a caller here
# uses; `surfaces.py` owns the values.
PROBE_NM = PROBE
ATOM_RADII_NM = AA_RADII
# The Martini 3 size classes this repository carries a radius for, from `models/sugars/recognition.py`: a mapping
# records one of exactly these, and anything else has no radius here to resolve to.
SIZE_RADII_NM = recognition.RADII_NM

# The plan's apolar set, as one-letter codes. A structure states a residue as its standard three-letter code, so the
# map below is what turns a name into the code the set is written in. A residue that is not one of the twenty
# standard codes -- a modified residue such as MSE -- is not in the set and is counted as not apolar.
APOLAR_CODES = frozenset('AVLIMFWP')
ONE_LETTER = {
    'ALA': 'A', 'ARG': 'R', 'ASN': 'N', 'ASP': 'D', 'CYS': 'C', 'GLN': 'Q', 'GLU': 'E', 'GLY': 'G',
    'HIS': 'H', 'ILE': 'I', 'LEU': 'L', 'LYS': 'K', 'MET': 'M', 'PHE': 'F', 'PRO': 'P', 'SER': 'S',
    'THR': 'T', 'TRP': 'W', 'TYR': 'Y', 'VAL': 'V',
}
# A deterministic Fibonacci point mesh. The area is a ratio of reachable points, so this is a resolution knob and
# not a random draw: the same structure always gives the same number.
POINT_NUMBER = 1000
# nm -> Angstrom: the surface library works in the units a PDB is written in, and this module works in nanometres.
_ANGSTROM = 10.0

ESTIMATE_METHOD = (
    'Flat-area estimate from the deposited structure, no simulation. '
    'Per-atom solvent-accessible area by Shrake-Rupley (biotite.structure.sasa, probe 0.191 nm, element radii '
    'passed in explicitly from surfaces.AA_RADII), summed over the transmembrane slab |z - centre| <= half_thickness '
    'with the centre at the origin, which is where OPM centres the bilayer. The slab area is the sum of the atoms '
    'whose residue is apolar (A, V, L, I, M, F, W, P, by standard three-letter code) and whose own z lies inside the '
    'slab; the rest of the structure still occludes them. head_area = pi * r_head^2, where r_head is the radius of '
    'the largest head bead of the detergent mapping\u2019s head group -- the convention taken for a multi-bead head '
    'group -- from its Martini 3 size class (R 0.264, S 0.230, T 0.191 nm). '
    'needed = apolar_area / head_area; fraction = requested * head_area / apolar_area.'
)

ESTIMATE_CAVEAT = (
    'This is a sizing aid and not a verdict: it treats the protein as a flat surface, with no curvature, packing or '
    'shape, so it says the requested count is roughly the right order and never that the micelle forms. The run\u2019s '
    'own assessment decides that; the estimate does not validate encapsulation.'
)


def element_of(atom_name):
    """The element a PDB atom name names, the way `surfaces.py` reads one.

    One rule for both surfaces: digits and punctuation are not part of an element, a two-letter element is title
    case, and everything else is its first letter upper case. `CA` is the alpha carbon here, not calcium, which is
    what a protein's own names mean.
    """
    letters = re.sub('[^A-Za-z]', '', str(atom_name))
    if not letters:
        raise ValueError(f'no element can be read from the atom name {atom_name!r}')
    return letters[:2].title() if letters[:2].title() in ('Cl', 'Br') else letters[:1].upper()


def atom_radii_nm(atom_names):
    """The radius of each atom, in nanometres, from the element its name names.

    An element with no verified radius is refused *with its name* rather than given a default: a made-up radius is
    indistinguishable from a measured one once it is in an area.
    """
    radii = []
    for name in atom_names:
        element = element_of(name)
        if element not in ATOM_RADII_NM:
            raise ValueError(f'No verified Rowland\u2013Taylor radius for {name} (element {element})')
        radii.append(ATOM_RADII_NM[element])
    return radii


def apolar_mask(residue_names):
    """Which atoms sit in an apolar residue: A, V, L, I, M, F, W, P, by the residue's standard three-letter code."""
    return [ONE_LETTER.get(str(name).strip().upper()) in APOLAR_CODES for name in residue_names]


def slab_area(areas_nm2, positions_nm, apolar, *, centre_nm, half_thickness_nm):
    """The area of the atoms inside the transmembrane slab whose residue is apolar, in square nanometres.

    Pure arithmetic on areas that are handed in, which is what makes the slab test and the apolar sum testable
    without a surface library: the caller decides what an atom's area is and this decides which areas are added.
    """
    areas = np.asarray(areas_nm2, dtype=float)
    axial = np.asarray(positions_nm, dtype=float)[:, 2]
    apolar = np.asarray(apolar, dtype=bool)
    inside = np.abs(axial - float(centre_nm)) <= float(half_thickness_nm)
    return float(np.nansum(areas[inside & apolar]))


def counts(apolar_area_nm2, head_radius_nm, requested):
    """Steps 4 and 5: the count the area implies, and the fraction of the area the requested count covers.

    `needed` and `fraction` are reciprocals through `requested`, so a reader can check one against the other.
    """
    area = float(apolar_area_nm2)
    radius = float(head_radius_nm)
    if not radius > 0:
        raise ValueError('the estimate needs a positive head radius to divide by')
    if not area > 0:
        raise ValueError('the estimate needs a positive apolar area to divide')
    head_area = math.pi * radius ** 2
    count = int(requested)
    return {'head_area_nm2': head_area, 'needed': area / head_area, 'requested': count,
            'fraction': count * head_area / area}


def estimate(positions_nm, radii_nm, apolar, *, centre_nm, half_thickness_nm, head_radii_nm, requested,
             probe_nm=PROBE_NM, points=POINT_NUMBER, residues=None):
    """The whole estimate: the numbers the panel shows, from a structure and the detergent's head radii.

    `positions_nm` and `radii_nm` are the protein's atoms and their radii, `apolar` the per-atom mask, and the slab
    is `|z - centre| <= half_thickness`. The surface is computed over the *whole* structure -- an atom outside the
    slab still shadows one inside it -- and the slab decides only which areas are summed. `head_radii_nm` are the
    radii of the detergent mapping's head beads; the largest of them sets the footprint, which is the convention
    `ESTIMATE_METHOD` names.
    """
    heads = [float(radius) for radius in (head_radii_nm or [])]
    if not heads:
        raise ValueError('the estimate needs the detergent mapping\u2019s head bead: none was resolved, so there is '
                         'no head radius to size the belt with')
    positions = np.asarray(positions_nm, dtype=float)
    radii = np.asarray(radii_nm, dtype=float)
    areas = _atom_sasa_nm2(positions, radii, probe_nm, points, residues)
    area = slab_area(areas, positions, apolar, centre_nm=centre_nm, half_thickness_nm=half_thickness_nm)
    if not area > 0:
        raise ValueError('the transmembrane slab holds no apolar surface, so there is nothing to size a belt '
                         'against')
    numbers = counts(area, max(heads), requested)
    return {'apolar_area_nm2': area, 'head_radius_nm': max(heads), 'atoms': int(len(positions)), **numbers}


def _atom_sasa_nm2(positions_nm, radii_nm, probe_nm, points, residues=None):
    """Atom-wise SASA in square nanometres, by the tested Shrake-Rupley implementation in biotite.

    biotite works in Angstrom, so the conversion happens here and nowhere else. `residues` are the structure's own
    residue names when the caller has them, so the library's own solvent and ion filters apply the way they do to a
    protein it reads itself; a structure with no names is treated as all solute. Imported inside the function
    because the route layer imports this module at start-up and this library is not worth paying for until a
    structure is actually sized.
    """
    import biotite.structure as structure

    if len(positions_nm) != len(radii_nm):
        raise ValueError(f'{len(positions_nm)} atoms but {len(radii_nm)} radii')
    atoms = structure.AtomArray(len(positions_nm))
    atoms.coord = np.asarray(positions_nm, dtype=float) * _ANGSTROM
    atoms.atom_name = np.array([f'A{index}' for index in range(len(positions_nm))])
    atoms.element = np.array(['C'] * len(positions_nm))
    atoms.res_name = np.array([str(name)[:5] for name in residues] if residues is not None
                              else ['UNK'] * len(positions_nm))
    areas = structure.sasa(atoms, probe_radius=float(probe_nm) * _ANGSTROM, ignore_ions=True,
                           point_number=int(points),
                           vdw_radii=np.asarray(radii_nm, dtype=float) * _ANGSTROM)
    return np.nan_to_num(areas, nan=0.0) / (_ANGSTROM ** 2)


# --- where the head bead's size class comes from: the detergent's own mapping ----------------------------------

def head_beads(mapping):
    """A detergent mapping's head-group beads: its physical beads that are not the aliphatic carbon series.

    The same rule the placement uses to orient a molecule (`pdc_build.py`): a C-type bead is the tail, everything
    else is the head. A ring virtual site is not a bead with a size of its own, so it is not a head either.
    """
    return [bead for bead in (mapping.get('beads') or [])
            if not bead.get('virtual_site') and not str(bead.get('type') or '').startswith('C')]


def size_class(bead):
    """A bead's Martini 3 size class: the size the mapping records, or the prefix its bead type carries.

    A schema-valid mapping records `size` as R, S or T. Martini 3 also spells the class as a prefix on the bead
    type -- `SP1r` is small, `TC4` is tiny, `C1` and `P1` are regular -- which is the fallback for a mapping that
    records a type but no size.
    """
    recorded = str(bead.get('size') or '').strip().upper()
    if recorded:
        return recorded
    prefix = str(bead.get('type') or '')[:1].upper()
    return prefix if prefix in ('S', 'T') else 'R'


def size_radius_nm(size):
    """The radius a Martini 3 size class maps to, or a refusal naming the class this repository does not carry.

    Refusing rather than substituting is the point: a radius picked for an unrecognised class would be a number
    nobody measured sitting where a measured one belongs.
    """
    try:
        return SIZE_RADII_NM[str(size).upper()]
    except KeyError:
        raise ValueError(f'the mapping states bead size {size!r}, and this repository carries no radius for it '
                         f'(it carries {sorted(SIZE_RADII_NM)})') from None


def read_structure(path):
    """A deposited structure's heavy atoms: positions in nanometres, radii, and the names a mask is built from.

    One reader, so no caller carries its own copy of the element rule. MDAnalysis reads the file -- the library the
    other surface computation here already uses -- and `atom_radii_nm` turns each atom's name into the radius
    `surfaces.AA_RADII` states. Imported inside the function because the route layer imports this module at
    start-up, and a trajectory library is not worth paying for until a structure is actually sized.
    """
    import MDAnalysis

    universe = MDAnalysis.Universe(str(path))
    names = [str(atom.name) for atom in universe.atoms]
    return {'atom_names': names, 'residues': [str(atom.resname) for atom in universe.atoms],
            'positions_nm': [[float(value) / _ANGSTROM for value in atom.position] for atom in universe.atoms],
            'radii_nm': atom_radii_nm(names)}


def mapping_head_radii(mapping):
    """Every head bead's radius, in nanometres, from the detergent mapping's own size classes.

    A mapping that names no head bead cannot answer, and says so rather than returning an empty list a caller might
    read as "no head surface".
    """
    beads = head_beads(mapping)
    if not beads:
        raise ValueError('the detergent mapping names no head bead: every physical bead is of the aliphatic carbon '
                         'series, so there is no head size class to resolve')
    return [size_radius_nm(size_class(bead)) for bead in beads]
