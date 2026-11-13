"""Derive GROMACS virtual-site parameters from a molecule topology.

This module is an adapted implementation of the MkVsites algorithm, not a copy of the upstream
tree. The upstream program is MIT-licensed; this port keeps only the derivation rules and the
force-field snippet formats needed by the dashboard.

    Per Larsson, Rosita Carolina Kneisz, Erik G Marklund, "MkVsites: A tool for creating GROMACS
    virtual sites parameters to increase performance in all-atom molecular dynamics simulations",
    J. Comput. Chem. 41(2):1564-1569 (2020), doi:10.1002/jcc.26198.

MkVsites, Copyright (c) 2020 Erik Marklund, is distributed under the MIT licence:
https://github.com/ErikMarklund/mkvsites (commit 3878974). This implementation is independent
code; it does not vendor that repository.

What is derived
---------------
Every atom is a node with its immediate bonded neighbours. A node with three or four neighbours,
exactly one non-hydrogen neighbour and hydrogens for the rest is represented by one virtual-site
type with a derived dummy mass and two distances. A hydroxyl oxygen with one hydrogen and one
heavy neighbour gets an angle constraint. The exact inline bond and angle rows of that node are
preferred; when a row carries no parameter the force field's ``[ bondtypes ]`` or
``[ angletypes ]`` entry for the same atom types is used. Missing parameters are reported as
warnings, never invented.

The ``forcefield`` block maps to GROMACS files as follows:

``constraints``
    ``[ constraints ]`` in ``ffbonded.itp``: two rows per virtual-site type, dummy--dummy and
    dummy--anchoring heavy atom. The values are in nanometres.
``angle_constraints``
    Also ``[ constraints ]`` in ``ffbonded.itp``: the heavy--hydrogen distance that freezes an
    O--H angle.
``dummy_masses``
    ``[ atomtypes ]`` in ``ffnonbonded.itp``: a massless dummy particle type.
``atomtypes``
    ``atomtypes.atp``: the name and zero mass of the dummy type.
``vsd``
    The force field's ``.vsd`` file, one ``center heavy dummy`` pattern per virtual-site type.

Atom indices in the JSON are 1-based. A virtual-site construct's ``atoms`` entry is
``[center, heavy, hydrogen...]``; an angle constraint's is ``[heavy, hydrogen]``.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

__all__ = ['VsiteError', 'derive_text', 'derive_file', 'derive_from_itp', 'derive_from_rtp']

_ELEMENTS = {1: 'H', 6: 'C', 7: 'N', 8: 'O', 15: 'P', 16: 'S'}
_RTP_SECTIONS = frozenset({
    'atoms', 'bonds', 'angles', 'dihedrals', 'impropers', 'pairs', 'cmap', 'exclusions',
    'bondedtypes', 'virtual_sites2', 'virtual_sites3', 'virtual_sites4', 'virtual_sitesn',
})
_WARNING = 'warning'


class VsiteError(ValueError):
    """A topology, force field or parameter set that cannot be used for derivation."""


@dataclass(frozen=True)
class _AtomType:
    name: str
    atnum: int
    mass: float


@dataclass(frozen=True)
class _Atom:
    index: int
    type: str
    name: str


@dataclass(frozen=True)
class _Bond:
    i: int
    j: int
    funct: int
    b0: float | None
    kb: float | None


@dataclass(frozen=True)
class _Angle:
    i: int
    j: int
    k: int
    funct: int
    theta0: float | None
    ktheta: float | None


@dataclass(frozen=True)
class _TypeBond:
    types: tuple[str, str]
    funct: int
    b0: float | None


@dataclass(frozen=True)
class _TypeAngle:
    types: tuple[str, str, str]
    funct: int
    theta0: float | None


@dataclass(frozen=True)
class _Molecule:
    kind: str
    moleculetype: str
    sha256: str
    atomtypes: dict[str, _AtomType]
    atoms: dict[int, _Atom]
    bonds: list[_Bond]
    angles: list[_Angle]


@dataclass(frozen=True)
class _ForceField:
    path: Path
    atomtypes: dict[str, _AtomType]
    bondtypes: list[_TypeBond]
    angletypes: list[_TypeAngle]


@dataclass(frozen=True)
class _Construct:
    center: int
    heavy: int
    hydrogens: tuple[int, ...]
    center_type: str
    heavy_type: str
    dummy_mass: float
    dummy_distance: float
    anchor_distance: float


@dataclass(frozen=True)
class _AngleConstraint:
    heavy: int
    hydrogen: int
    heavy_type: str
    hydrogen_type: str
    distance: float


def _clean(line: str) -> str:
    return line.split(';', 1)[0].strip()


def _warning(diagnostics: list[dict], message: str) -> None:
    diagnostics.append({'level': _WARNING, 'message': message})


def _integer(token: str, what: str) -> int:
    try:
        return int(token)
    except (TypeError, ValueError) as exc:
        raise VsiteError(f'{what}: {token!r} is not an integer') from exc


def _number(token: str, what: str) -> float:
    try:
        value = float(token)
    except (TypeError, ValueError) as exc:
        raise VsiteError(f'{what}: {token!r} is not a number') from exc
    if not math.isfinite(value):
        raise VsiteError(f'{what}: {token!r} is not finite')
    return value


def _distance(value: float, what: str) -> float:
    if not math.isfinite(value):
        raise VsiteError(f'{what} is not finite')
    if value < 0:
        raise VsiteError(f'{what} is negative ({value})')
    if value == 0:
        raise VsiteError(f'{what} must be positive')
    return value


def _angle_value(value: float, what: str) -> float:
    if not math.isfinite(value):
        raise VsiteError(f'{what} is not finite')
    if value < 0 or value > 180:
        raise VsiteError(f'{what} is outside 0..180 degrees ({value})')
    return value


def _read(path: Path) -> tuple[str, str]:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise VsiteError(f'cannot read topology {path}: {exc}') from exc
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        text = data.decode('latin-1')
    return text, hashlib.sha256(data).hexdigest()


def _reject_directives(path: Path, text: str) -> None:
    """Refuse includes and macros; tolerate the position-restraint guard an ITP writes around itself.

    A guarded ``[ position_restraints ]`` block is not a virtual-site input, so its ``#ifdef``/``#endif``
    pair is skipped rather than resolved. An ``#include`` still means the atom/term rows are elsewhere, and
    deriving from the unexpanded file would miss them.
    """
    guard = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        clean = _clean(raw)
        if not clean.startswith('#'):
            continue
        directive = clean.split()[0]
        if directive in ('#ifdef', '#ifndef'):
            guard += 1
            continue
        if directive == '#endif':
            guard = max(0, guard - 1)
            continue
        if guard:
            continue
        raise VsiteError(
            f'{path}:{lineno}: preprocessor directive {directive!r} is not supported; '
            'inline included files before deriving virtual sites')


def _atomtype(path: Path, lineno: int, fields: list[str]) -> _AtomType:
    if len(fields) < 7:
        raise VsiteError(
            f'{path}:{lineno}: [ atomtypes ] line needs at least 7 fields '
            '(type at.num mass charge ptype sigma epsilon)')
    name = fields[0]
    atnum = _integer(fields[1], f'{path}:{lineno}: at.num')
    if atnum < 0:
        raise VsiteError(f'{path}:{lineno}: at.num must not be negative ({atnum})')
    mass = _number(fields[2], f'{path}:{lineno}: mass')
    if mass < 0:
        raise VsiteError(f'{path}:{lineno}: mass must not be negative ({mass})')
    return _AtomType(name, atnum, mass)


def _parse_itp(path: Path, text: str, sha256: str) -> tuple[_Molecule, list[dict]]:
    _reject_directives(path, text)
    diagnostics: list[dict] = []
    atomtypes: dict[str, _AtomType] = {}
    atoms: dict[int, _Atom] = {}
    bonds: list[_Bond] = []
    angles: list[_Angle] = []
    moleculetype: str | None = None
    moleculetype_headers = 0
    section = ''

    for lineno, raw in enumerate(text.splitlines(), 1):
        clean = _clean(raw)
        if not clean:
            continue
        if clean.startswith('['):
            end = clean.find(']')
            if end < 0:
                raise VsiteError(f'{path}:{lineno}: unterminated section header {clean!r}')
            section = clean[1:end].strip().lower()
            if section == 'moleculetype':
                moleculetype_headers += 1
                if moleculetype_headers > 1:
                    raise VsiteError(f'{path}:{lineno}: exactly one [ moleculetype ] is supported')
            continue

        fields = clean.split()
        if section == 'moleculetype':
            if moleculetype is not None:
                raise VsiteError(f'{path}:{lineno}: [ moleculetype ] must contain one line')
            if len(fields) < 2:
                raise VsiteError(f'{path}:{lineno}: [ moleculetype ] needs a name and nrexcl')
            moleculetype = fields[0]
        elif section == 'atomtypes':
            atomtype = _atomtype(path, lineno, fields)
            if atomtype.name in atomtypes:
                raise VsiteError(f'{path}:{lineno}: duplicate [ atomtypes ] entry {atomtype.name!r}')
            atomtypes[atomtype.name] = atomtype
        elif section == 'atoms':
            if len(fields) < 7:
                raise VsiteError(
                    f'{path}:{lineno}: [ atoms ] line needs at least 7 fields '
                    '(nr type resnr resid atom cgnr charge [mass])')
            index = _integer(fields[0], f'{path}:{lineno}: atom number')
            if index < 1:
                raise VsiteError(f'{path}:{lineno}: atom numbers are 1-based ({index})')
            if index in atoms:
                raise VsiteError(f'{path}:{lineno}: duplicate atom number {index}')
            atoms[index] = _Atom(index, fields[1], fields[4])
        elif section == 'bonds':
            _append_bond(path, lineno, fields, bonds, diagnostics)
        elif section == 'angles':
            _append_angle(path, lineno, fields, angles, diagnostics)

    if moleculetype_headers == 0:
        raise VsiteError(f'{path}: no [ moleculetype ] section')
    if moleculetype is None:
        raise VsiteError(f'{path}: [ moleculetype ] has no name')
    if not atoms:
        raise VsiteError(f'{path}: no [ atoms ] section')
    _validate_numbering(path, atoms)
    _validate_terms(path, atoms, bonds, angles)
    return _Molecule('itp', moleculetype, sha256, atomtypes, atoms, bonds, angles), diagnostics


def _validate_numbering(path: Path, atoms: dict[int, _Atom]) -> None:
    numbers = sorted(atoms)
    for expected, found in enumerate(numbers, 1):
        if expected != found:
            raise VsiteError(
                f'{path}: atom numbering must be 1-based and contiguous; '
                f'expected {expected}, found {found}')


def _validate_terms(path: Path, atoms: dict[int, _Atom], bonds: list[_Bond], angles: list[_Angle]) -> None:
    for bond in bonds:
        for index in (bond.i, bond.j):
            if index not in atoms:
                raise VsiteError(f'{path}: bond {bond.i}-{bond.j} refers to missing atom {index}')
    for angle in angles:
        for index in (angle.i, angle.j, angle.k):
            if index not in atoms:
                raise VsiteError(
                    f'{path}: angle {angle.i}-{angle.j}-{angle.k} refers to missing atom {index}')


def _append_bond(path: Path, lineno: int, fields: list[str], bonds: list[_Bond], diagnostics: list[dict]) -> None:
    if len(fields) < 3:
        raise VsiteError(f'{path}:{lineno}: [ bonds ] line needs i j funct')
    i = _integer(fields[0], f'{path}:{lineno}: bond atom i')
    j = _integer(fields[1], f'{path}:{lineno}: bond atom j')
    funct = _integer(fields[2], f'{path}:{lineno}: bond funct')
    if funct != 1:
        _warning(diagnostics, f'{path}:{lineno}: bond {i}-{j} has funct {funct}; only funct 1 is used')
        return
    b0 = _distance(_number(fields[3], f'{path}:{lineno}: bond b0'), f'{path}:{lineno}: bond {i}-{j} b0') if len(fields) > 3 else None
    kb = _number(fields[4], f'{path}:{lineno}: bond kb') if len(fields) > 4 else None
    bonds.append(_Bond(i, j, funct, b0, kb))


def _append_angle(path: Path, lineno: int, fields: list[str], angles: list[_Angle], diagnostics: list[dict]) -> None:
    if len(fields) < 4:
        raise VsiteError(f'{path}:{lineno}: [ angles ] line needs i j k funct')
    i = _integer(fields[0], f'{path}:{lineno}: angle atom i')
    j = _integer(fields[1], f'{path}:{lineno}: angle atom j')
    k = _integer(fields[2], f'{path}:{lineno}: angle atom k')
    funct = _integer(fields[3], f'{path}:{lineno}: angle funct')
    if funct != 1:
        _warning(diagnostics, f'{path}:{lineno}: angle {i}-{j}-{k} has funct {funct}; only funct 1 is used')
        return
    theta0 = _angle_value(_number(fields[4], f'{path}:{lineno}: angle theta0'), f'{path}:{lineno}: angle {i}-{j}-{k} theta0') if len(fields) > 4 else None
    ktheta = _number(fields[5], f'{path}:{lineno}: angle ktheta') if len(fields) > 5 else None
    angles.append(_Angle(i, j, k, funct, theta0, ktheta))


def _parse_rtp(path: Path, text: str, sha256: str, residue: str) -> tuple[_Molecule, list[dict]]:
    _reject_directives(path, text)
    diagnostics: list[dict] = []
    records: list[tuple[str, str, int, list[str]]] = []
    residues: list[str] = []
    current: str | None = None
    section = ''

    for lineno, raw in enumerate(text.splitlines(), 1):
        clean = _clean(raw)
        if not clean:
            continue
        if clean.startswith('['):
            end = clean.find(']')
            if end < 0:
                raise VsiteError(f'{path}:{lineno}: unterminated section header {clean!r}')
            name = clean[1:end].strip()
            if name.lower() in _RTP_SECTIONS:
                section = name.lower()
            else:
                current = name
                section = ''
                if name not in residues:
                    residues.append(name)
            continue
        if current is not None and section:
            records.append((current, section, lineno, clean.split()))

    if residue not in residues:
        available = ', '.join(residues) if residues else 'none'
        raise VsiteError(f'{path}: residue {residue!r} not found (available: {available})')

    atom_names: dict[str, int] = {}
    atoms: dict[int, _Atom] = {}
    for residue_name, section_name, lineno, fields in records:
        if residue_name != residue or section_name != 'atoms':
            continue
        if len(fields) < 4:
            raise VsiteError(f'{path}:{lineno}: RTP [ atoms ] line needs atom type charge cgnr')
        name, atom_type = fields[0], fields[1]
        if name in atom_names:
            raise VsiteError(f'{path}:{lineno}: duplicate RTP atom name {name!r}')
        index = len(atom_names) + 1
        atom_names[name] = index
        atoms[index] = _Atom(index, atom_type, name)
    if not atoms:
        raise VsiteError(f'{path}: residue {residue!r} has no [ atoms ] section')

    bonds: list[_Bond] = []
    angles: list[_Angle] = []
    for residue_name, section_name, lineno, fields in records:
        if residue_name != residue:
            continue
        if section_name == 'bonds':
            _append_rtp_bond(path, lineno, fields, atom_names, bonds, diagnostics)
        elif section_name == 'angles':
            _append_rtp_angle(path, lineno, fields, atom_names, angles, diagnostics)

    return _Molecule('rtp', residue, sha256, {}, atoms, bonds, angles), diagnostics


def _rtp_atom(path: Path, lineno: int, token: str, names: dict[str, int]) -> int:
    try:
        return names[token]
    except KeyError:
        # RTP writes links to a neighbouring residue as `+N`/`-C`; for one residue the
        # local atom is still what the bond/angle row names.
        local = token.lstrip('+-')
        if local in names:
            return names[local]
        raise VsiteError(f'{path}:{lineno}: atom {token!r} is not in this residue') from None


def _append_rtp_bond(path: Path, lineno: int, fields: list[str], names: dict[str, int],
                     bonds: list[_Bond], diagnostics: list[dict]) -> None:
    if len(fields) < 3:
        raise VsiteError(f'{path}:{lineno}: RTP [ bonds ] line needs atom atom funct')
    i = _rtp_atom(path, lineno, fields[0], names)
    j = _rtp_atom(path, lineno, fields[1], names)
    funct = _integer(fields[2], f'{path}:{lineno}: bond funct')
    if funct != 1:
        _warning(diagnostics, f'{path}:{lineno}: bond {fields[0]}-{fields[1]} has funct {funct}; only funct 1 is used')
        return
    b0 = _distance(_number(fields[3], f'{path}:{lineno}: bond b0'), f'{path}:{lineno}: bond {fields[0]}-{fields[1]} b0') if len(fields) > 3 else None
    kb = _number(fields[4], f'{path}:{lineno}: bond kb') if len(fields) > 4 else None
    bonds.append(_Bond(i, j, funct, b0, kb))


def _append_rtp_angle(path: Path, lineno: int, fields: list[str], names: dict[str, int],
                      angles: list[_Angle], diagnostics: list[dict]) -> None:
    if len(fields) < 4:
        raise VsiteError(f'{path}:{lineno}: RTP [ angles ] line needs atom atom atom funct')
    i = _rtp_atom(path, lineno, fields[0], names)
    j = _rtp_atom(path, lineno, fields[1], names)
    k = _rtp_atom(path, lineno, fields[2], names)
    funct = _integer(fields[3], f'{path}:{lineno}: angle funct')
    if funct != 1:
        _warning(diagnostics, f'{path}:{lineno}: angle {fields[0]}-{fields[1]}-{fields[2]} has funct {funct}; only funct 1 is used')
        return
    theta0 = _angle_value(_number(fields[4], f'{path}:{lineno}: angle theta0'), f'{path}:{lineno}: angle theta0') if len(fields) > 4 else None
    ktheta = _number(fields[5], f'{path}:{lineno}: angle ktheta') if len(fields) > 5 else None
    angles.append(_Angle(i, j, k, funct, theta0, ktheta))


def _load_force_field(path: Path) -> _ForceField:
    path = Path(path)
    if not path.is_dir():
        raise VsiteError(f'force field directory {path} does not exist')
    nonbonded = path / 'ffnonbonded.itp'
    bonded = path / 'ffbonded.itp'
    if not nonbonded.is_file() and not bonded.is_file():
        raise VsiteError(f'force field directory {path} has neither ffnonbonded.itp nor ffbonded.itp')

    atomtypes: dict[str, _AtomType] = {}
    if nonbonded.is_file():
        text, _ = _read(nonbonded)
        section = ''
        for lineno, raw in enumerate(text.splitlines(), 1):
            clean = _clean(raw)
            if not clean or clean.startswith('#'):
                continue
            if clean.startswith('['):
                end = clean.find(']')
                if end < 0:
                    raise VsiteError(f'{nonbonded}:{lineno}: unterminated section header {clean!r}')
                section = clean[1:end].strip().lower()
                continue
            if section == 'atomtypes':
                atomtype = _atomtype(nonbonded, lineno, clean.split())
                atomtypes.setdefault(atomtype.name, atomtype)

    bondtypes: list[_TypeBond] = []
    angletypes: list[_TypeAngle] = []
    if bonded.is_file():
        text, _ = _read(bonded)
        section = ''
        for lineno, raw in enumerate(text.splitlines(), 1):
            clean = _clean(raw)
            if not clean or clean.startswith('#'):
                continue
            if clean.startswith('['):
                end = clean.find(']')
                if end < 0:
                    raise VsiteError(f'{bonded}:{lineno}: unterminated section header {clean!r}')
                section = clean[1:end].strip().lower()
                continue
            fields = clean.split()
            if section == 'bondtypes':
                if len(fields) < 5:
                    raise VsiteError(f'{bonded}:{lineno}: [ bondtypes ] line needs i j funct b0 kb')
                funct = _integer(fields[2], f'{bonded}:{lineno}: bond funct')
                b0 = _number(fields[3], f'{bonded}:{lineno}: bond b0')
                if funct == 1:
                    _distance(b0, f'{bonded}:{lineno}: bond b0')
                bondtypes.append(_TypeBond((fields[0], fields[1]), funct, b0))
            elif section == 'angletypes':
                if len(fields) < 6:
                    raise VsiteError(f'{bonded}:{lineno}: [ angletypes ] line needs i j k funct theta0 ktheta')
                funct = _integer(fields[3], f'{bonded}:{lineno}: angle funct')
                theta0 = _number(fields[4], f'{bonded}:{lineno}: angle theta0')
                if funct == 1:
                    _angle_value(theta0, f'{bonded}:{lineno}: angle theta0')
                angletypes.append(_TypeAngle((fields[0], fields[1], fields[2]), funct, theta0))
    return _ForceField(path, atomtypes, bondtypes, angletypes)


def _inline_bond(molecule: _Molecule, i: int, j: int) -> _Bond | None:
    for bond in molecule.bonds:
        if {bond.i, bond.j} == {i, j} and bond.b0 is not None:
            return bond
    return None


def _inline_angle(molecule: _Molecule, i: int, j: int, k: int) -> _Angle | None:
    for angle in molecule.angles:
        if angle.j == j and {angle.i, angle.k} == {i, k} and angle.theta0 is not None:
            return angle
    return None


def _force_field_bond(forcefield: _ForceField | None, type_i: str, type_j: str,
                      diagnostics: list[dict], context: str) -> tuple[bool, float | None]:
    if forcefield is None:
        return False, None
    pair = frozenset((type_i, type_j))
    for bond in forcefield.bondtypes:
        if frozenset(bond.types) == pair:
            if bond.funct != 1:
                _warning(diagnostics,
                         f'{context} is underivable: force-field bond type {type_i}-{type_j} has funct {bond.funct}; only funct 1 is used')
                return True, None
            return True, bond.b0
    return False, None


def _force_field_angle(forcefield: _ForceField | None, type_i: str, type_j: str, type_k: str,
                       diagnostics: list[dict], context: str) -> tuple[bool, float | None]:
    if forcefield is None:
        return False, None
    ends = frozenset((type_i, type_k))
    for angle in forcefield.angletypes:
        if angle.types[1] == type_j and frozenset((angle.types[0], angle.types[2])) == ends:
            if angle.funct != 1:
                _warning(diagnostics,
                         f'{context} is underivable: force-field angle type {type_i}-{type_j}-{type_k} has funct {angle.funct}; only funct 1 is used')
                return True, None
            return True, angle.theta0
    return False, None


def _bond_length(molecule: _Molecule, forcefield: _ForceField | None, i: int, j: int,
                 atomtypes: dict[str, _AtomType], diagnostics: list[dict], context: str) -> float | None:
    inline = _inline_bond(molecule, i, j)
    if inline is not None:
        return inline.b0
    type_i = molecule.atoms[i].type
    type_j = molecule.atoms[j].type
    found, value = _force_field_bond(forcefield, type_i, type_j, diagnostics, context)
    if value is not None:
        return value
    if found:
        return None
    if forcefield is None:
        reason = 'no inline bond length and no force field was given'
    else:
        reason = f'no inline bond length and no [ bondtypes ] entry for {type_i}-{type_j}'
    _warning(diagnostics, f'{context} is underivable: {reason}')
    return None


def _angle_parameter(molecule: _Molecule, forcefield: _ForceField | None, i: int, j: int, k: int,
                     diagnostics: list[dict], context: str) -> float | None:
    inline = _inline_angle(molecule, i, j, k)
    if inline is not None:
        return inline.theta0
    type_i = molecule.atoms[i].type
    type_j = molecule.atoms[j].type
    type_k = molecule.atoms[k].type
    found, value = _force_field_angle(forcefield, type_i, type_j, type_k, diagnostics, context)
    if value is not None:
        return value
    if found:
        return None
    if forcefield is None:
        reason = 'no inline angle and no force field was given'
    else:
        reason = f'no inline angle and no [ angletypes ] entry for {type_i}-{type_j}-{type_k}'
    _warning(diagnostics, f'{context} is underivable: {reason}')
    return None


def _element(atomtype: _AtomType) -> str:
    symbol = _ELEMENTS.get(atomtype.atnum)
    if symbol is None:
        raise VsiteError(f'atom type {atomtype.name!r} has unsupported atomic number {atomtype.atnum}')
    return symbol


def _mass(atomtype: _AtomType) -> float:
    if not math.isfinite(atomtype.mass) or atomtype.mass < 0:
        raise VsiteError(f'atom type {atomtype.name!r} has invalid mass {atomtype.mass}')
    return atomtype.mass


def _adjacency(molecule: _Molecule) -> dict[int, list[int]]:
    neighbours: dict[int, list[int]] = {index: [] for index in molecule.atoms}
    for bond in molecule.bonds:
        neighbours[bond.i].append(bond.j)
        neighbours[bond.j].append(bond.i)
    return {index: sorted(set(values)) for index, values in neighbours.items()}


def _one_vsite(molecule: _Molecule, forcefield: _ForceField | None, atomtypes: dict[str, _AtomType],
               centre: int, hydrogens: tuple[int, ...], heavy: int,
               diagnostics: list[dict]) -> _Construct | None:
    context = f'virtual-site construct at atom {centre} ({molecule.atoms[centre].name})'
    d_ch = _bond_length(molecule, forcefield, hydrogens[0], centre, atomtypes, diagnostics, context)
    d_ca = _bond_length(molecule, forcefield, centre, heavy, atomtypes, diagnostics, context)
    angle = _angle_parameter(molecule, forcefield, hydrogens[0], centre, heavy, diagnostics, context)
    if d_ch is None or d_ca is None or angle is None:
        return None

    centre_type = atomtypes[molecule.atoms[centre].type]
    heavy_type = atomtypes[molecule.atoms[heavy].type]
    hydrogen_types = [atomtypes[molecule.atoms[index].type] for index in hydrogens]
    m_centre = _mass(centre_type)
    m_hydrogens = [_mass(hydrogen_type) for hydrogen_type in hydrogen_types]
    m_total = m_centre + sum(m_hydrogens)
    if m_total <= 0:
        _warning(diagnostics, f'{context}: the centre and its hydrogens have no positive mass')
        return None

    radians = math.radians(angle)
    d_hy = d_ch * math.sin(radians)
    inertia = sum(mass * d_hy * d_hy for mass in m_hydrogens)
    dummy_mass = m_total / 2.0
    dummy_distance = 2.0 * math.sqrt(inertia / m_total)
    d_hx = d_ch * -math.cos(radians)
    d_x = (m_centre * d_ca + m_hydrogens[0] * len(hydrogens) * (d_ca + d_hx)) / m_total
    anchor_distance = math.hypot(d_x, dummy_distance / 2.0)
    if dummy_distance <= 0 or anchor_distance <= 0 or not math.isfinite(anchor_distance):
        _warning(diagnostics, f'{context}: the geometry is degenerate for a virtual site')
        return None
    _element(centre_type)
    return _Construct(centre, heavy, hydrogens, centre_type.name, heavy_type.name,
                      dummy_mass, dummy_distance, anchor_distance)


def _one_angle_constraint(molecule: _Molecule, forcefield: _ForceField | None,
                          atomtypes: dict[str, _AtomType], oxygen: int, hydrogen: int, heavy: int,
                          diagnostics: list[dict]) -> _AngleConstraint | None:
    context = f'OH angle constraint at atom {oxygen} ({molecule.atoms[oxygen].name})'
    d_ao = _bond_length(molecule, forcefield, heavy, oxygen, atomtypes, diagnostics, context)
    d_oh = _bond_length(molecule, forcefield, oxygen, hydrogen, atomtypes, diagnostics, context)
    angle = _angle_parameter(molecule, forcefield, heavy, oxygen, hydrogen, diagnostics, context)
    if d_ao is None or d_oh is None or angle is None:
        return None
    radians = math.radians(angle)
    x = d_ao + d_oh * -math.cos(radians)
    y = d_oh * math.sin(radians)
    distance = math.hypot(x, y)
    if distance <= 0 or not math.isfinite(distance):
        _warning(diagnostics, f'{context}: the geometry is degenerate for an angle constraint')
        return None
    return _AngleConstraint(heavy, hydrogen, molecule.atoms[heavy].type,
                            molecule.atoms[hydrogen].type, distance)


def _same_distance(first: float, second: float, fraction: float) -> bool:
    if first == second:
        return True
    return abs(first - second) <= abs(second) * fraction


def _group_vsites(constructs: list[_Construct], atomtypes: dict[str, _AtomType]) -> list[dict]:
    groups: list[dict] = []
    for construct in constructs:
        match = next((group for group in groups
                      if group['center'] == construct.center_type
                      and group['heavy'] == construct.heavy_type
                      and _same_distance(construct.dummy_distance, group['dummy_distance_nm'], 0.01)
                      and _same_distance(construct.anchor_distance, group['anchor_distance_nm'], 0.01)), None)
        if match is not None:
            match['atoms'].append([construct.center, construct.heavy, *construct.hydrogens])
            match['count'] += 1
            continue
        base = f"M{_element(atomtypes[construct.center_type])}H{len(construct.hydrogens)}_"
        used = {group['name'] for group in groups}
        suffix = 1
        while f'{base}{suffix}' in used:
            suffix += 1
        groups.append({
            'name': f'{base}{suffix}',
            'center': construct.center_type,
            'heavy': construct.heavy_type,
            'nH': len(construct.hydrogens),
            'dummy_mass': construct.dummy_mass,
            'dummy_distance_nm': construct.dummy_distance,
            'anchor_distance_nm': construct.anchor_distance,
            'count': 1,
            'atoms': [[construct.center, construct.heavy, *construct.hydrogens]],
        })
    return groups


def _group_angle_constraints(constraints: list[_AngleConstraint]) -> list[dict]:
    groups: list[dict] = []
    for constraint in constraints:
        match = next((group for group in groups
                      if group['heavy'] == constraint.heavy_type
                      and group['hydrogen'] == constraint.hydrogen_type
                      and abs(group['distance_nm'] - constraint.distance) <= 1e-4), None)
        if match is not None:
            match['atoms'].append([constraint.heavy, constraint.hydrogen])
            match['count'] += 1
            continue
        groups.append({
            'heavy': constraint.heavy_type,
            'hydrogen': constraint.hydrogen_type,
            'distance_nm': constraint.distance,
            'count': 1,
            'atoms': [[constraint.heavy, constraint.hydrogen]],
        })
    return groups


def _forcefield(vsites: list[dict], angle_constraints: list[dict]) -> dict:
    constraints: list[str] = []
    for vsite in vsites:
        constraints.append(f"{vsite['name']} {vsite['name']} 2 {vsite['dummy_distance_nm']:.6f}")
        constraints.append(f"{vsite['name']} {vsite['heavy']} 2 {vsite['anchor_distance_nm']:.6f}")
    angle_lines = [f"{group['heavy']} {group['hydrogen']} 2 {group['distance_nm']:.6f}"
                   for group in angle_constraints]
    return {
        'constraints': constraints,
        'angle_constraints': angle_lines,
        'dummy_masses': [f"{vsite['name']} 0 0.000000 0.00 A 0.0 0.0" for vsite in vsites],
        'atomtypes': [f"{vsite['name']} 0.00000" for vsite in vsites],
        'vsd': [f"{vsite['center']} {vsite['heavy']} {vsite['name']}" for vsite in vsites],
    }


def _derive(molecule: _Molecule, forcefield: _ForceField | None, diagnostics: list[dict]) -> dict:
    atomtypes = dict(forcefield.atomtypes) if forcefield is not None else {}
    atomtypes.update(molecule.atomtypes)

    for index in sorted(molecule.atoms):
        atom = molecule.atoms[index]
        if atom.type not in atomtypes:
            source = f' in force field {forcefield.path}' if forcefield is not None else ''
            raise VsiteError(
                f'atom {index} ({atom.name}) has atom type {atom.type!r}, which has no [ atomtypes ] entry{source}')
        _mass(atomtypes[atom.type])

    neighbours = _adjacency(molecule)
    constructs: list[_Construct] = []
    constraints: list[_AngleConstraint] = []
    for index in sorted(molecule.atoms):
        adjacent = neighbours[index]
        hydrogen = [neighbour for neighbour in adjacent if atomtypes[molecule.atoms[neighbour].type].atnum == 1]
        heavy = [neighbour for neighbour in adjacent if neighbour not in hydrogen]

        if len(adjacent) in (3, 4) and len(heavy) == 1 and len(hydrogen) == len(adjacent) - 1:
            construct = _one_vsite(molecule, forcefield, atomtypes, index, tuple(hydrogen), heavy[0], diagnostics)
            if construct is not None:
                constructs.append(construct)

        oxygen = atomtypes[molecule.atoms[index].type].atnum == 8
        if oxygen and len(hydrogen) == 1 and len(heavy) == 1:
            constraint = _one_angle_constraint(molecule, forcefield, atomtypes, index,
                                               hydrogen[0], heavy[0], diagnostics)
            if constraint is not None:
                constraints.append(constraint)

    vsites = _group_vsites(constructs, atomtypes)
    angle_constraints = _group_angle_constraints(constraints)
    return {
        'source': {'kind': molecule.kind, 'moleculetype': molecule.moleculetype, 'sha256': molecule.sha256},
        'vsites': vsites,
        'angle_constraints': angle_constraints,
        'forcefield': _forcefield(vsites, angle_constraints),
        'diagnostics': diagnostics,
    }


def derive_text(text: str, *, force_field: str | Path | None = None, kind: str = 'itp',
                residue: str | None = None) -> dict:
    """Derive virtual sites from topology text already in memory.

    ``kind`` is ``'itp'`` (one moleculetype) or ``'rtp'`` (one residue); the SHA-256 is taken
    over the UTF-8 text. A route that has parsed an inspected snapshot can use this without
    staging the file on disk.
    """
    kind = kind.lower()
    if kind not in ('itp', 'rtp'):
        raise VsiteError(f'unsupported topology kind {kind!r}; use "itp" or "rtp"')
    if kind == 'itp' and residue:
        raise VsiteError('a residue name is only valid for kind="rtp"')
    if kind == 'rtp' and not residue:
        raise VsiteError('kind="rtp" requires a residue name')
    source = Path('<text>')
    sha256 = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if kind == 'rtp':
        molecule, diagnostics = _parse_rtp(source, text, sha256, residue)
    else:
        molecule, diagnostics = _parse_itp(source, text, sha256)
    forcefield = _load_force_field(Path(force_field)) if force_field is not None else None
    return _derive(molecule, forcefield, diagnostics)


def derive_file(path: str | Path, *, force_field: str | Path | None = None, kind: str | None = None,
                residue: str | None = None) -> dict:
    """Derive virtual sites from a file, inferring ITP/TOP versus RTP from its suffix."""
    path = Path(path)
    if kind is None:
        kind = 'rtp' if path.suffix.lower() == '.rtp' else 'itp'
    kind = kind.lower()
    if kind == 'rtp':
        return derive_from_rtp(path, residue or '', force_field)
    if kind == 'itp':
        if residue:
            raise VsiteError('a residue name is only valid for kind="rtp"')
        return derive_from_itp(path, force_field)
    raise VsiteError(f'unsupported topology kind {kind!r}; use "itp" or "rtp"')


def derive_from_itp(path: str | Path, force_field: str | Path | None = None) -> dict:
    """Derive virtual sites from one ITP/TOP moleculetype.

    ``force_field`` is an optional directory with ``ffnonbonded.itp`` and ``ffbonded.itp`` used
    only where the molecule itself has no parameter. A malformed or unsupported topology raises
    :class:`VsiteError`; a missing bonded parameter is returned as a warning.
    """
    path = Path(path)
    text, sha256 = _read(path)
    molecule, diagnostics = _parse_itp(path, text, sha256)
    forcefield = _load_force_field(Path(force_field)) if force_field is not None else None
    return _derive(molecule, forcefield, diagnostics)


def derive_from_rtp(path: str | Path, residue: str, force_field: str | Path | None = None) -> dict:
    """Derive virtual sites from one residue in an RTP file.

    RTP rows normally carry no bond or angle parameters, so ``force_field`` is required for a
    useful answer. Missing atom types raise :class:`VsiteError`; a missing bonded parameter is
    returned as a warning rather than guessed.
    """
    if not residue:
        raise VsiteError('an RTP residue name is required')
    path = Path(path)
    text, sha256 = _read(path)
    molecule, diagnostics = _parse_rtp(path, text, sha256, residue)
    forcefield = _load_force_field(Path(force_field)) if force_field is not None else None
    return _derive(molecule, forcefield, diagnostics)
