"""Write the CG2AT2 fragment a mapping implies, so back-mapping can convert a detergent.

CG2AT2 converts a coarse-grained residue by reading a fragment from its own database: a `<NAME>.pdb` split into `[ BEAD ]`
sections whose ATOM lines are the atoms behind each bead, and a `<NAME>.itp` holding those atoms with their types, charges,
masses and bonds. The vendored database covers the molecules the Warwick group simulates -- `non_protein/` holds 48 lipid and
sterol fragments (POPC, POPE, POPG, PIPI variants, CDL2, CHOL, ...) and no detergent at all, which is why a DDM complex stops
at "DDM is not in the fragment database!".

That is not a gap we have to leave: a mapping states, bead by bead, which atoms it covers, and the molecule's own GROMACS
topology states every atom's type, charge, mass and bonds. This module turns the two into the three files CG2AT2 reads.

Three decisions worth stating, because each is a place a fragment can be wrong:

* **Hydrogens belong to the bead that holds their heavy neighbour.** A mapping covers heavy atoms only (35 of DDM's 81), and
  the fragment has to describe all 81 or the fragment is not the molecule. Each hydrogen is therefore assigned to the bead of
  the heavy atom it is bonded to, from the topology's own `[ bonds ]`.
* **A virtual-site bead borrows one atom from the ring it sits in.** DDM's `S1VS`/`S2VS` beads are placed from the beads
  around them, so nothing in the atomistic structure belongs to them -- but the converter requires every CG bead to own at
  least one atom and attributes each atom to exactly one bead (an empty section raised `KeyError: 1` inside its centre-of-mass
  routine, and duplicated atoms would be written into the converted molecule twice). Each virtual site therefore takes the
  lowest-numbered atom of the first bead sharing its stem (`S1VS` -> `S1A`), the smallest departure that keeps one atom in one
  bead. It is an approximation and the run's record says so: the site's own position is derived, and the borrowed atom is a
  stand-in for it, never a claim that the atom belongs there.
* **The topology is carried as it stands, renamed.** The molecule here is SwissParam-parametrised (atom types `CR`, `OR`,
  `HCMM`, `HOR`) and `molecules/DDM/metadata.json` already says so, with the CGenFF compatibility it assumes but does not
  demonstrate. Rewriting its atom types to CHARMM36 names would invent parameters; the fragment therefore carries the
  molecule's own `[ atomtypes ]` block with the molecule, and the run's record says the converted complex mixes that tree with
  the protein's CHARMM36 rather than pretending to one force field.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MOLECULETYPE = re.compile(r'^(\s*\[\s*moleculetype\s*\])', re.IGNORECASE)
SECTION = re.compile(r'^\s*\[\s*([A-Za-z_]+)\s*\]')
ATOM_RECORD = ('ATOM', 'HETATM')


def _sections(text: str) -> dict[str, list[str]]:
    """Split an itp into its sections, keyed lower-case, comments and blanks kept."""
    out: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        found = SECTION.match(line)
        if found:
            current = found.group(1).lower()
            out.setdefault(current, [])
            continue
        if current is not None:
            out[current].append(line)
    return out


def topology_atoms(text: str) -> list[dict]:
    """`[ atoms ]` as records: number, type, name, charge, mass."""
    atoms = []
    for line in _sections(text).get('atoms', []):
        if not line.strip() or line.lstrip().startswith(';'):
            continue
        columns = line.split()
        atoms.append({'number': int(columns[0]), 'type': columns[1], 'residue': columns[3],
                      'name': columns[4], 'charge': float(columns[6]), 'mass': float(columns[7])})
    return atoms


def topology_bonds(text: str) -> list[tuple[int, int]]:
    bonds = []
    for line in _sections(text).get('bonds', []):
        if not line.strip() or line.lstrip().startswith(';'):
            continue
        columns = line.split()
        bonds.append((int(columns[0]), int(columns[1])))
    return bonds


def bead_atoms(mapping: dict, topology: str) -> dict[str, list[int]]:
    """Each atom-bearing bead's atoms, with every hydrogen on the bead of its heavy neighbour.

    The mapping's indices are the topology's atom numbers (1-based). A bead with no atoms states no atoms: DDM's two virtual
    sites are placed from their neighbours and have nothing in the atomistic structure to own.
    """
    atoms = topology_atoms(topology)
    known = {atom['number'] for atom in atoms}
    owner: dict[int, str] = {}
    beads: dict[str, list[int]] = {}
    for bead in mapping['beads']:
        numbers = [int(index) for index in bead['atoms']]
        unknown = [number for number in numbers if number not in known]
        if unknown:
            raise ValueError(f'bead {bead["name"]} names atoms the topology does not have: {unknown[:5]}')
        beads[bead['name']] = numbers
        for number in numbers:
            owner[number] = bead['name']

    for first, second in topology_bonds(topology):
        for heavy, other in ((first, second), (second, first)):
            if heavy in owner and other not in owner:
                bead = owner[heavy]
                beads[bead].append(other)
                owner[other] = bead
    for bead in beads:
        beads[bead].sort()
    for bead in [bead for bead, numbers in beads.items() if not numbers]:
        stem = bead[:-2] if bead.endswith('VS') else bead[:-1]
        donors = [name for name, numbers in beads.items() if name != bead and name.startswith(stem) and numbers]
        if not donors:
            raise ValueError(f'the virtual site {bead} has no ring to borrow an atom from')
        source = donors[0]
        borrowed = beads[source].pop(0)
        beads[bead] = [borrowed]
    unmapped = sorted(known - set(owner))
    if unmapped:
        raise ValueError(f'the topology has atoms no bead covers: {unmapped[:8]}')
    return beads


def fragment_pdb(name: str, beads: dict[str, list[int]], coordinates: list[dict]) -> str:
    """`[ BEAD ]` sections of ATOM lines, in mapping order, one residue called `name`."""
    by_number = {record['number']: record for record in coordinates}
    # No header line before the first section: CG2AT2's reader sets `bead` from a `[ BEAD ]` line and stops with
    # "error reading: <fragment>.pdb" on any line that arrives before one -- a comment or a blank counts.
    lines = []
    for bead, numbers in beads.items():
        lines.append(f'[ {bead} ]')
        for number in numbers:
            record = by_number[number]
            lines.append(
                f'ATOM  {number:5d} {record["name"]:<4.4} {name:>4.4} {1:4d}    '
                f'{record["x"]:8.3f}{record["y"]:8.3f}{record["z"]:8.3f}  1.00  0.00          {record["element"]:>2}'
            )
        lines.append('')
    return '\n'.join(lines) + 'END\n'


def fragment_itp(text: str, name: str) -> str:
    """The molecule's topology with its moleculetype and residue column renamed to `name`.

    Everything else -- `[ atomtypes ]` included -- is carried unchanged, because the parameters are the molecule's and this
    module has no business inventing different ones.
    """
    out, in_atoms, in_type = [], False, False
    for line in text.splitlines():
        if MOLECULETYPE.match(line):
            out.append(line)
            in_atoms, in_type = False, True
            continue
        found = SECTION.match(line)
        if found:
            out.append(line)
            section = found.group(1).lower()
            in_atoms = section == 'atoms'
            in_type = section == 'moleculetype'
            continue
        if in_type and line.strip() and not line.lstrip().startswith((';', '[')):
            # The first data line under `[ moleculetype ]` is the name and the exclusion count; the comment between them
            # (`; Name nrexcl`) is why this is a state and not a blank-line test.
            out.append(f'{name}      3')
            in_type = False
            continue
        if in_atoms and line.strip() and not line.lstrip().startswith(';'):
            columns = line.split()
            columns[3] = name
            out.append('  '.join(f'{value:>8}' if index else value for index, value in enumerate(columns)))
            continue
        out.append(line)
    return '\n'.join(out) + '\n'


def safe_names(names: list[str]) -> dict[str, str]:
    """Bead names shortened to the four characters a PDB atom-name field holds, kept unique.

    CG2AT2 round-trips the coarse-grained input through PDB, whose atom-name field is columns 13-16: a five-character bead
    name is read back as four, so `TAIL1`, `TAIL2` and `TAIL3` all arrive as `TAIL` and the converter then cannot find the
    bead it was asked for ("The bead TAIL is missing from the fragment library"). The shortening is deterministic -- the
    first three characters plus the position among the names sharing them -- and a collision is refused rather than
    resolved by luck, because a fragment that attributes one bead's atoms to another is worse than a stopped conversion.
    """
    shortened = {name: name for name in names if len(name) <= 4}
    for name in names:
        if len(name) <= 4:
            continue
        stem = name[:3]
        index = 1 + sum(1 for other in names if other.startswith(stem) and other != name and names.index(other) < names.index(name))
        candidate = f'{stem}{index}'
        while candidate in shortened.values() or len(candidate) > 4:
            index += 1
            candidate = f'{stem}{index}'
        shortened[name] = candidate
    unique = set(shortened.values())
    if len(unique) != len(names):
        raise ValueError(f'the bead names cannot be made unique in four characters: {sorted(shortened.items())}')
    return shortened


def renamed_gro(text: str, residue: str, names: dict[str, str]) -> str:
    """A `.gro` copy whose named beads carry their shortened names, so the converter reads them back intact.

    Only the atom-name column changes, and only for the residue that asked for it: everything else in the file -- the box
    line included -- is what the simulation wrote.
    """
    lines = text.splitlines(keepends=True)
    if len(lines) < 3:
        raise ValueError('the gro file is too short to hold a system')
    out = [lines[0], lines[1]]
    for line in lines[2:-1]:
        if len(line) < 20:
            out.append(line)
            continue
        atom = line[10:15].strip()
        if line[5:10].strip() == residue and atom in names:
            out.append(f'{line[:10]}{names[atom]:>5}{line[15:]}')
        else:
            out.append(line)
    out.append(lines[-1])
    return ''.join(out)


def read_pdb_atoms(path: Path) -> list[dict]:
    atoms = []
    for line in path.read_text().splitlines():
        if not line.startswith(ATOM_RECORD):
            continue
        atoms.append({'number': int(line[6:11]), 'name': line[12:16].strip(), 'x': float(line[30:38]),
                      'y': float(line[38:46]), 'z': float(line[46:54]),
                      'element': (line[76:78].strip() or line[12:16].strip()[:1])})
    return atoms


def write(directory: Path, mapping_path: Path, topology_path: Path, coordinates_path: Path,
          name: str | None = None) -> dict:
    mapping = json.loads(mapping_path.read_text())
    residue = name or mapping.get('name', '').split('_')[0] or 'LIG'
    topology = topology_path.read_text()
    names = safe_names([bead['name'] for bead in mapping['beads']])
    beads = {names[bead]: numbers for bead, numbers in bead_atoms(mapping, topology).items()}
    coordinates = read_pdb_atoms(coordinates_path)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f'{residue}.pdb').write_text(fragment_pdb(residue, beads, coordinates))
    (directory / f'{residue}.itp').write_text(fragment_itp(topology, residue))
    return {'residue': residue, 'renamed': {old: new for old, new in names.items() if old != new},
            'beads': {bead: len(numbers) for bead, numbers in beads.items()},
            'atoms': sum(len(numbers) for numbers in beads.values()),
            'files': [str(directory / f'{residue}.pdb'), str(directory / f'{residue}.itp')]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Write the CG2AT2 fragment a mapping implies')
    parser.add_argument('--mapping', required=True)
    parser.add_argument('--topology', required=True)
    parser.add_argument('--coordinates', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--name')
    arguments = parser.parse_args(argv)
    written = write(Path(arguments.out), Path(arguments.mapping), Path(arguments.topology),
                    Path(arguments.coordinates), arguments.name)
    print(json.dumps(written, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
