"""Build a pdb2gmx-readable RTP entry from a molecule ITP/TOP.

The AA workflow's molecules are SwissParam/CGenFF ITPs: one moleculetype with its own atom types and
explicit bond/angle/dihedral parameters. pdb2gmx cannot use such an ITP directly, but it can use an RTP
residue plus the same parameters in a force field. This module writes that residue entry.

Only the parameters the topology already states are copied. The RTP `[ bondedtypes ]` line names the
function type each section uses, so the rows omit the function field (pdb2gmx fills it in); a topology
whose terms do not all use 1/1/9/2 is refused rather than silently reinterpreted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class RtpError(ValueError):
    """The topology cannot be represented as one pdb2gmx RTP residue."""


@dataclass(frozen=True)
class _Atom:
    name: str
    type: str
    charge: float
    cgnr: int


@dataclass(frozen=True)
class _Term:
    atoms: tuple[str, ...]
    funct: int
    params: tuple[str, ...]


def _lines(text: str):
    section = ''
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        if line.startswith('#'):
            # Position-restraint guards do not change the topology; includes mean the rows are elsewhere.
            if line.split()[0] in ('#ifdef', '#ifndef', '#else', '#endif'):
                continue
            raise RtpError(f'line {lineno}: preprocessor directive {line.split()[0]!r} is not supported')
        directive = re.fullmatch(r'\[\s*(\S+)\s*\]', line)
        if directive:
            section = directive.group(1).lower()
            continue
        yield lineno, section, line.split()


def _params(fields: list[str], lineno: int) -> tuple[int, tuple[str, ...]]:
    try:
        funct = int(fields[0])
    except (IndexError, ValueError) as exc:
        raise RtpError(f'line {lineno}: a term needs a numeric function type') from exc
    params = tuple(fields[1:])
    # SwissParam repeats the two parameters of a funct 1/2 term; the MDP/RTP wants one pair.
    return funct, params if funct == 9 else params[:2]


def from_itp(text: str, *, residue: str, source: str = '') -> str:
    """One ITP/TOP moleculetype as an RTP residue named `residue`."""
    if not re.fullmatch(r'[A-Za-z0-9_+-]{1,80}', residue):
        raise RtpError(f'residue name {residue!r} is not a pdb2gmx residue name')
    atoms: list[_Atom] = []
    bonds: list[_Term] = []
    angles: list[_Term] = []
    dihedrals: list[_Term] = []
    impropers: list[_Term] = []
    exclusions: list[tuple[str, ...]] = []
    for lineno, section, fields in _lines(text):
        if section == 'atoms':
            if len(fields) < 7:
                raise RtpError(f'line {lineno}: atom needs nr type resnr resid atom cgnr charge')
            name, atom_type = fields[4], fields[1]
            if not re.fullmatch(r'[A-Za-z0-9_+-]{1,20}', name):
                raise RtpError(f'line {lineno}: atom name {name!r} is not an RTP atom name')
            atoms.append(_Atom(name, atom_type, float(fields[6]), int(fields[5])))
        elif section == 'bonds':
            funct, params = _params(fields[2:], lineno)
            bonds.append(_Term((fields[0], fields[1]), funct, params))
        elif section == 'angles':
            funct, params = _params(fields[3:], lineno)
            angles.append(_Term(tuple(fields[:3]), funct, params))
        elif section == 'dihedrals':
            funct, params = _params(fields[4:], lineno)
            term = _Term(tuple(fields[:4]), funct, params)
            (impropers if funct in (2, 4) else dihedrals).append(term)
        elif section == 'exclusions':
            exclusions.append(tuple(fields))
        elif section.startswith('virtual_sites'):
            raise RtpError(f'line {lineno}: the source topology already has {section}; '
                           'combine the existing sites with MkVsites before converting it to RTP')
    if not atoms:
        raise RtpError('the topology has no atoms')
    names = {atom.name for atom in atoms}
    if len(names) != len(atoms):
        raise RtpError('two atoms share a name; an RTP residue addresses atoms by name')
    def resolve(term: _Term) -> _Term:
        try:
            resolved = tuple(atoms[int(index) - 1].name for index in term.atoms)
        except (ValueError, IndexError) as exc:
            raise RtpError(f'term {term.atoms} refers to an atom number outside [ atoms ]') from exc
        return _Term(resolved, term.funct, term.params)
    bonds = [resolve(term) for term in bonds]
    angles = [resolve(term) for term in angles]
    dihedrals = [resolve(term) for term in dihedrals]
    impropers = [resolve(term) for term in impropers]
    exclusions = [tuple(atoms[int(index) - 1].name for index in row) for row in exclusions]
    # pdb2gmx fills the function type from [ bondedtypes ]; a mix cannot be represented there.
    expected = {'bonds': 1, 'angles': 1, 'dihedrals': 9, 'impropers': 2}
    for label, terms in (('bonds', bonds), ('angles', angles), ('dihedrals', dihedrals), ('impropers', impropers)):
        for term in terms:
            if term.funct != expected[label]:
                raise RtpError(f'{label} use function type {term.funct}; this converter writes one '
                               f'[ bondedtypes ] and needs {expected[label]}')
    lines = ['; Generated from the molecule topology by the dashboard RTP converter.']
    if source:
        lines.append(f'; source: {source}')
    lines += ['', '[ bondedtypes ]', '; bonds  angles  dihedrals  impropers',
              '       1       1          9          2', '', f'[ {residue} ]', ' [ atoms ]']
    lines += [f'{atom.name} {atom.type} {atom.charge:g} {atom.cgnr}' for atom in atoms]
    if bonds:
        lines += ['', ' [ bonds ]']
        lines += [' '.join(term.atoms + term.params) for term in bonds]
    if angles:
        lines += ['', ' [ angles ]']
        lines += [' '.join(term.atoms + term.params) for term in angles]
    if dihedrals:
        lines += ['', ' [ dihedrals ]']
        lines += [' '.join(term.atoms + term.params) for term in dihedrals]
    if impropers:
        lines += ['', ' [ impropers ]']
        lines += [' '.join(term.atoms + term.params) for term in impropers]
    if exclusions:
        lines += ['', ' [ exclusions ]']
        lines += [' '.join(names) for names in exclusions]
    return '\n'.join(lines) + '\n'


def from_itp_file(path: str | Path, *, residue: str) -> str:
    path = Path(path)
    return from_itp(path.read_text(encoding='utf-8'), residue=residue, source=str(path))
