"""Parsed, hash-pinned view of the Martini 3 reference carbohydrate topology.

The reference file is the oracle for mapping fidelity: bead counts, bead types, residue layout,
virtual sites and inter-residue connectivity are read from it rather than restated in code, so a
generated candidate can be checked against the published model instead of against our own assumptions.

The file's only preprocessor construct is an `#ifndef CONST` / `#ifdef CONST` pair on the NMC entry.
CONST is not defined for this project, so the `#ifndef` branch is live; the guarded branch is parsed
into `entry['guarded']` rather than dropped, so a future `-DCONST` build is a visible difference
instead of a silent one.
"""
import hashlib
from functools import lru_cache
from pathlib import Path

REFERENCE_NAME = 'martini_v3.0.0_sugars_v2.itp'
PROVENANCE_NAME = 'martini_v3.0.0_sugars_v2.source.json'

# Resolved from this file rather than from dashboard.paths: the sugar package is also shipped whole into
# the mapping export bundle, where no dashboard package exists above it. `.parents[3]` is the repository
# root when it runs from the dashboard.
ROOT = Path(__file__).resolve().parents[3]


def reference_path(root=None):
    return Path(root or ROOT) / 'references' / REFERENCE_NAME


def provenance_path(root=None):
    return Path(root or ROOT) / 'references' / PROVENANCE_NAME


def sha256(root=None):
    return hashlib.sha256(reference_path(root).read_bytes()).hexdigest()


def entries(root=None):
    """Every moleculetype in the reference, keyed by name."""
    return _entries(reference_path(root).read_text(), str(reference_path(root)))


def entry(name, root=None):
    table = entries(root)
    if name not in table:
        raise KeyError(f'No moleculetype {name} in {REFERENCE_NAME}')
    return table[name]


def residue_of(entry_record, index):
    """The residue number an atom index belongs to."""
    return next(atom['residue'] for atom in entry_record['atoms'] if atom['index'] == index)


def signature(entry_record):
    """The facts a generated candidate must reproduce: residues, beads, sites and inter-residue links.

    Equilibrium numbers are carried along for comparison but are not part of conformance; see the
    plan's decision D1.
    """
    residues = {}
    for atom in entry_record['atoms']:
        residues.setdefault(atom['residue'], []).append(
            {'name': atom['name'], 'type': atom['type'], 'mass': atom['mass'],
             'virtual_site': not atom['mass']})
    by_index = {atom['index']: atom for atom in entry_record['atoms']}
    links = []
    for bond in entry_record['bonds']:
        first, second = by_index[bond['i']], by_index[bond['j']]
        if first['residue'] != second['residue']:
            links.append({'a': [first['residue'], first['name']], 'b': [second['residue'], second['name']],
                          'length': bond['length'], 'force': bond.get('force')})
    return {'name': entry_record['name'], 'residues': residues, 'links': links,
            'virtual_sites': {number: [bead['name'] for bead in beads if bead['virtual_site']]
                              for number, beads in residues.items()}}


def _number(text):
    return float(text) if ('.' in text or 'e' in text.lower()) else int(text)


def _fields(line):
    return line.split()


def _record(section, fields):
    """Parse one data line into a record, or None when the line does not belong to the section."""
    try:
        if section == 'atoms':
            return {'index': int(fields[0]), 'type': fields[1], 'residue': int(fields[2]),
                    'residue_name': fields[3], 'name': fields[4],
                    'charge': _number(fields[6]), 'mass': _number(fields[7])}
        if section == 'constraints':
            return {'i': int(fields[0]), 'j': int(fields[1]), 'function': int(fields[2]),
                    'length': _number(fields[3])}
        if section == 'bonds':
            return {'i': int(fields[0]), 'j': int(fields[1]), 'function': int(fields[2]),
                    'length': _number(fields[3]), 'force': _number(fields[4])}
        if section == 'angles':
            return {'i': int(fields[0]), 'j': int(fields[1]), 'k': int(fields[2]),
                    'function': int(fields[3]), 'angle': _number(fields[4]), 'force': _number(fields[5])}
        if section == 'dihedrals':
            values = [_number(field) for field in fields[5:]]
            return {'i': int(fields[0]), 'j': int(fields[1]), 'k': int(fields[2]), 'l': int(fields[3]),
                    'function': int(fields[4]), 'angle': values[0], 'force': values[1],
                    'multiplicity': values[2] if len(values) > 2 else None}
        if section == 'exclusions':
            return {'site': int(fields[0]), 'atoms': [int(field) for field in fields[1:]]}
        if section == 'virtual_sitesn':
            return {'site': int(fields[0]), 'function': int(fields[1]),
                    'parents': [int(field) for field in fields[2:]]}
        if section == 'virtual_sites3':
            return {'site': int(fields[0]), 'function': int(fields[1]),
                    'atoms': [int(field) for field in fields[2:5]],
                    'parameters': [_number(field) for field in fields[5:]]}
    except (IndexError, ValueError):
        return None
    return None


@lru_cache(maxsize=4)
def _entries(text, source):
    table: dict = {}
    current: dict | None = None
    section: str | None = None
    guarded = False
    for raw in text.splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        if line.startswith('#'):
            directive = line.split()[0]
            if directive == '#ifdef':
                guarded = True          # CONST is not defined, so this branch is not taken
            elif directive in ('#ifndef', '#endif'):
                guarded = False
            continue
        if line.startswith('['):
            section = line.strip('[] ').strip().lower().replace(' ', '_')
            continue
        if section == 'moleculetype':
            name = _fields(line)[0]
            current = {'name': name, 'nrexcl': int(_fields(line)[1]), 'source': source, 'guarded': {}}
            table[name] = current
            continue
        if current is None:
            continue
        record = _record(section, _fields(line))
        if record is None:
            continue
        if guarded:
            current['guarded'].setdefault(section, []).append(record)
        else:
            current.setdefault(section, []).append(record)
    for record in table.values():
        for section_name in ('atoms', 'bonds', 'constraints', 'angles', 'dihedrals', 'exclusions',
                             'virtual_sitesn', 'virtual_sites3'):
            record.setdefault(section_name, [])
    return table
