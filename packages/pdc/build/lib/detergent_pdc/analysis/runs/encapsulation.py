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
from dashboard.analysis.runs.radii import AA_RADII, PROBE
from dashboard.models.sugars import recognition

# The probe and the element radii are the house surface conventions, imported rather than restated: a second copy
# would be a second convention, and the two would drift. `PROBE_NM` and `ATOM_RADII_NM` are the names a caller here
# uses; `surfaces.py` owns the values.
PROBE_NM = PROBE
ATOM_RADII_NM = AA_RADII
# The Martini 3 size classes this repository carries a radius for, from `models/sugars/recognition.py`: a mapping
# records one of exactly these, and anything else has no radius here to resolve to.
SIZE_RADII_NM = recognition.RADII_NM

# The plan's apolar set, as one-letter codes. A structure states a residue as its standard three-letter code, so the
# map below is what turns a name into the code the set is written in.
APOLAR_CODES = frozenset('AVLIMFWP')
ONE_LETTER = {
    'ALA': 'A', 'ARG': 'R', 'ASN': 'N', 'ASP': 'D', 'CYS': 'C', 'GLN': 'Q', 'GLU': 'E', 'GLY': 'G',
    'HIS': 'H', 'ILE': 'I', 'LEU': 'L', 'LYS': 'K', 'MET': 'M', 'PHE': 'F', 'PRO': 'P', 'SER': 'S',
    'THR': 'T', 'TRP': 'W', 'TYR': 'Y', 'VAL': 'V',
}
# Modified residues that present the same nonpolar surface as the residue they modify, each named with its parent's
# one-letter code so a reader can check the chemistry against the parent's entry above. A code is here ONLY if its
# parent is one of APOLAR_CODES: a modification of a polar residue would put polar atoms into a sum about nonpolar
# surface, the opposite error to the one this table fixes. The entries, with parents:
#
#   MSE selenomethionine  -- methionine with its sulfur replaced by selenium (M); the most common modified residue
#                            in deposited structures, and the one whose absence undercounts every SeMet-phased one.
#   FME N-formylmethionine-- the initiator, methionine carrying a formyl on the backbone nitrogen (M); a backbone
#                            modification that adds no side-chain polarity.
#   MED D-methionine      -- the D-form of methionine (M).
#   NLE norleucine        -- leucine with the branched side chain straightened into n-butyl (L).
#   NVA norvaline         -- valine missing the gamma methyl, a straight propyl chain (V).
#   ABA 2-aminobutyric acid -- alanine with one more methylene in the side chain (A).
#   AIB 2-aminoisobutyric acid -- alanine with two methyls on the alpha carbon (A).
#   DAL, DVA, DLE, DIL, DPN, DPR, DTR -- the D-forms of alanine, valine, leucine, isoleucine, phenylalanine, proline
#                            and tryptophan (A, V, L, I, F, P, W). A D-alanine is as nonpolar as an L-alanine, and
#                            these appear in membrane-active peptides. The repository's own residue dictionary
#                            (dashboard/web/static/vendor/ngl.js) spells D-phenylalanine and D-methionine DPN and MED;
#                            there is no DPH spelling for D-phenylalanine, and DPH is phenytoin in the PDB chemical
#                            component dictionary, so folding it in would count a drug as protein surface.
#
# Deliberately NOT here, though a reader may expect them:
#   HYP hydroxyproline    -- parent proline (P) IS apolar, but HYP adds a hydroxyl, so it presents polar surface and
#                            folding it in would overcount. It is the one apolar-parent case the rule excludes.
#   SEP phosphoserine, TPO phosphothreonine, CSO S-hydroxycysteine, KCX N-carbamoyl-lysine, MLY N-dimethyl-lysine --
#                            each adds polarity (a phosphate, a hydroxyl, or a carbamoyl group) and each modifies a
#                            residue that is already polar (S, T, C, K), so none can be nonpolar surface.
MODIFIED_APOLAR = {
    'MSE': 'M', 'FME': 'M', 'MED': 'M', 'NLE': 'L', 'NVA': 'V', 'ABA': 'A', 'AIB': 'A',
    'DAL': 'A', 'DVA': 'V', 'DLE': 'L', 'DIL': 'I', 'DPN': 'F', 'DPR': 'P', 'DTR': 'W',
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
    'slab; the rest of the structure still occludes them. A modified residue with an apolar parent (one of those '
    'eight) is folded into the apolar set as if it were the parent -- MSE, FME and MED (methionine), NLE (leucine), '
    'NVA (valine), ABA and AIB (alanine), and the D-forms DAL, DVA, DLE, DIL, DPN, DPR, DTR -- while a modified '
    'residue whose parent is polar, or that adds a polar group such as a hydroxyl or a phosphate, is not apolar. '
    'head_area = pi * r_head^2, where r_head is the radius of '
    'the largest head bead of the detergent mapping\u2019s head group -- the convention taken for a multi-bead head '
    'group -- from its Martini 3 size class (R 0.264, S 0.230, T 0.191 nm). '
    'needed = apolar_area / head_area; fraction = requested * head_area / apolar_area. '
    'When the caller narrows to a strict subset of the chains the '
    'structure declares, the structure is filtered to those chains before the surface is computed, so the number '
    'describes the subunit that will be simulated and not the whole deposited file; naming every chain is the whole '
    'file, exactly as naming none is.'
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
    """Which atoms sit in an apolar residue: A, V, L, I, M, F, W, P by standard three-letter code, plus the nonpolar
    modified residues whose parent is one of those eight.

    A modified residue that adds no polarity sits in the same class as the residue it modifies -- an MSE is a
    methionine with selenium for sulfur, so the surface it presents is methionine's. A modified residue whose parent
    is polar, or that adds a polar group, is not apolar and must not be folded in: this sum is about nonpolar surface,
    and folding polar atoms into it is the opposite error to the undercount it fixes.
    """
    mask = []
    for name in residue_names:
        code = str(name).strip().upper()
        parent = ONE_LETTER.get(code)
        if parent is None:
            parent = MODIFIED_APOLAR.get(code)
        mask.append(parent in APOLAR_CODES)
    return mask


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


def read_structure(path, chains=None):
    """A deposited structure's heavy atoms: positions in nanometres, radii, and the names a mask is built from.

    `chains` is the selection. A selection that is a *strict subset* of the chains the structure declares narrows the
    atoms to those chains, so a caller that asks for one subunit of an assembly sizes that subunit and not the file --
    the SASA then sees only the atoms that go into the run. A selection that names every chain the structure declares
    is not a narrowing: the object is the whole file, which is what a caller that never chose keeps and what a picker
    that chooses all of them means -- so a chain-less record (a placeholder HETATM in a file like 1AT9) is kept with
    it, exactly as the whole-file estimate keeps it. `narrowed` says which of the two happened.
    `chains_available` always reports every chain the file names, whatever was selected, so a caller can refuse a
    chain the structure does not have rather than being handed an empty structure. A structure that names no chain
    returns an empty `chains_available`; nothing is guessed.

    One reader, so no caller carries its own copy of the element rule. MDAnalysis reads the file -- the library the
    other surface computation here already uses -- and `atom_radii_nm` turns each atom's name into the radius
    `surfaces.AA_RADII` states. Imported inside the function because the route layer imports this module at
    start-up, and a trajectory library is not worth paying for until a structure is actually sized.
    """
    import MDAnalysis

    universe = MDAnalysis.Universe(str(path))
    identifiers = [str(atom.chainID) for atom in universe.atoms]
    available = sorted({chain for chain in identifiers if chain})
    indices = range(len(identifiers))
    narrowed = False
    if chains is not None and not {str(chain) for chain in chains} >= set(available):
        wanted = {str(chain) for chain in chains}
        indices = [index for index, chain in enumerate(identifiers) if chain in wanted]
        narrowed = True
    names = [str(universe.atoms[index].name) for index in indices]
    return {'atom_names': names,
            'residues': [str(universe.atoms[index].resname) for index in indices],
            'chains': [identifiers[index] for index in indices],
            'chains_available': available,
            'narrowed': narrowed,
            'positions_nm': [[float(value) / _ANGSTROM for value in universe.atoms[index].position]
                             for index in indices],
            'radii_nm': atom_radii_nm(names)}


def unknown_chains(available, requested):
    """The requested chains the structure does not name, sorted; empty when every one is present.

    A refusal rather than a filter: a chain that is not there would silently size or build a different object than
    the one that was asked for, and in the number or the structure that comes back the two are indistinguishable.
    """
    present = {str(chain) for chain in (available or [])}
    return sorted({str(chain) for chain in (requested or [])} - present)


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
