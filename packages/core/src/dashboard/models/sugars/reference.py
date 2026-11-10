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

#: The molecules the published set names, and the entry that is *their own* model. Connectivity identification is not
#: enough to decide this: it is stereochemistry-blind, so an epimer with the same ring sizes and linkage letters
#: identifies the same entry while being a different molecule -- maltose and `LAC` are both 6+6 with an AB link, and
#: `LAC` is lactose. The panel may show an entry only for the molecule the entry is published for. `accepts_identity`
#: is the one exception: an entry whose mapping is identical to the one the identifier named may stand for the
#: molecule when the molecule's own identity says so -- which is how glucose uses `GLC` although its layout says `GAL`.
PUBLISHED_FOR = {'Sucrose': 'SUCR', 'Trehalose': 'TREH', 'Lactose': 'LAC', 'Glucose': 'GLC'}

# The data root, asked of `dashboard.paths` when the package is importable -- it honours `DASHBOARD_ROOT`, and an
# installed distribution does not sit inside a checkout. The sugar package is also shipped whole into the mapping
# export bundle, where no dashboard package exists above it: that import can fail there, and the fallback only has
# to resolve to something in a copy that never reads the reference file.
try:
    from ... import paths as _paths
    ROOT = _paths.PROJECT_ROOT
except ImportError:
    ROOT = Path(__file__).resolve().parents[3]


def reference_path(root=None):
    return Path(root or ROOT) / 'references' / REFERENCE_NAME


def provenance_path(root=None):
    return Path(root or ROOT) / 'references' / PROVENANCE_NAME


def sha256(root=None):
    return hashlib.sha256(reference_path(root).read_bytes()).hexdigest()


def _sections(text):
    """Named sections of a GROMACS topology as field lists."""
    current, table = None, {}
    for line in text.splitlines():
        clean = line.split(';', 1)[0].strip()
        if clean.startswith('['):
            current = clean.strip('[] ').lower()
            table.setdefault(current, [])
        elif clean and current:
            table[current].append(clean.split())
    return table


def conform(data, entry_name):
    """Where a generated candidate departs from the reference entry's mapping.

    Only mapping facts are checked -- residues, bead letters and types, each ring's site parents, and the
    inter-residue links. Equilibrium numbers are not part of conformance; see `parameter_delta` and the
    plan's decision D1. An empty list means the mapping reproduces the reference.
    """
    expected_signature = signature(entry(entry_name))
    beads = data.get('beads') or []
    by_residue = {}
    for bead in beads:
        by_residue.setdefault(bead.get('residue', 1), []).append(bead)
    issues = []
    if set(by_residue) != set(expected_signature['residues']):
        issues.append(f'residues {sorted(by_residue)} do not match the reference '
                      f'{sorted(expected_signature["residues"])}')
    for number in sorted(set(by_residue) | set(expected_signature['residues'])):
        expected_beads = expected_signature['residues'].get(number, [])
        actual_beads = by_residue.get(number, [])
        actual_letters = [bead.get('letter') or bead['name'] for bead in actual_beads]
        if actual_letters != [bead['name'] for bead in expected_beads]:
            issues.append(f'residue {number}: beads {actual_letters} do not match the reference '
                          f'{[bead["name"] for bead in expected_beads]}')
            continue
        for bead, expected_bead in zip(actual_beads, expected_beads):
            if bead['type'] != expected_bead['type']:
                issues.append(f'residue {number} bead {bead["name"]}: type {bead["type"]} where the '
                              f'reference has {expected_bead["type"]}')
        sites = [bead for bead in actual_beads if bead.get('virtual_site')]
        physical = [bead['name'] for bead in actual_beads if not bead.get('virtual_site')]
        if len(sites) != len(expected_signature['virtual_sites'].get(number, [])):
            issues.append(f'residue {number}: {len(sites)} ring sites where the reference has '
                          f'{len(expected_signature["virtual_sites"].get(number, []))}')
        elif sites and sorted(sites[0]['virtual_site']['parents']) != sorted(physical):
            issues.append(f'residue {number}: the ring site is not built from its own '
                          f'{len(physical)} physical beads')

    currency = {bead['name']: (bead.get('residue', 1), bead.get('letter') or bead['name'])
                for bead in beads}
    actual_links = set()
    for edge in data.get('connections') or []:
        if edge[0] in currency and edge[1] in currency and currency[edge[0]][0] != currency[edge[1]][0]:
            actual_links.add(frozenset((currency[edge[0]], currency[edge[1]])))
    expected_links = {frozenset((tuple(link['a']), tuple(link['b'])))
                      for link in expected_signature['links']}
    if actual_links != expected_links:
        issues.append('inter-residue links '
                      f'{sorted(sorted(pair) for pair in actual_links)} do not match the reference '
                      f'{sorted(sorted(pair) for pair in expected_links)}')
    return issues


def mapping_signature(entry_name):
    """An entry's mapping facts alone: residues, bead names and types, virtual sites and inter-residue link ends.

    The equilibrium numbers are deliberately left out. The published `GLC` and `GAL` are one mapping with different
    constraint lengths -- which is why a glucose structure's connectivity identifies `GAL` -- so a comparison that
    kept the lengths would report a difference the mapping cannot see.
    """
    record = signature(entry(entry_name))
    return {
        'residues': {number: [(bead['name'], bead['type'], bead['virtual_site']) for bead in beads]
                     for number, beads in sorted(record['residues'].items())},
        'links': sorted(sorted((tuple(link['a']), tuple(link['b']))) for link in record['links']),
    }


def same_layout(first, second):
    """Whether two published entries describe one bead layout (residues, bead names/types, sites, link ends)."""
    return mapping_signature(first) == mapping_signature(second)


def accepts_identity(candidate, molecule_id, entry):
    """Whether this molecule may use `entry` although its layout identified another published entry.

    Identification is stereochemistry-blind: every aldohexose has the same four-bead pattern, so a glucose structure's
    candidate list holds every aldohexose and its first candidate is `GAL`. The molecule's own identity decides only
    when it has a published entry, that entry is the one selected, the candidate conforms to it, and the identified
    entry shares its mapping layout. Then choosing the entry changes the published numbers, never the bead mapping. A
    molecule with no published entry stays refused -- maltose's layout matches `LAC`, but `LAC` is lactose's model --
    and so does an entry this candidate does not reproduce.
    """
    if PUBLISHED_FOR.get(molecule_id) != entry:
        return False
    identified = (candidate.get('reference') or {}).get('entry')
    if not identified:
        return False
    if identified == entry:
        return True
    return not conform(candidate, entry) and same_layout(identified, entry)


def layout_note(candidate, entry):
    """The sentence for a layout that cannot tell two entries apart, or None when identification named `entry`."""
    identified = (candidate.get('reference') or {}).get('entry')
    if not identified or identified == entry or not same_layout(identified, entry):
        return None
    return (f'The bead layout alone cannot distinguish {entry} from {identified}: the entries share one mapping '
            f'layout (residues, bead names and types, links and virtual sites) and differ in their published bond '
            f'lengths, so the molecule\'s identity selects {entry}.')


def run_topology(entry_name, *, residue_name=None, provenance=None):
    """The published entry's own terms, written in the layout a run consumes.

    This is a transcription, not a fit and not a geometry seed: every constraint length, bond, angle, dihedral,
    virtual site and exclusion is the reference file's value. A run's start coordinates come from the mapped AA
    geometry, so its initial distances will differ from these; that difference is what
    ``parameter_delta(..., layout='run')`` reports, and minimisation/equilibration absorb it.

    Run layout means one residue per molecule and ``B01..`` atom names, the convention ``mapped.gro``, the ``.map``
    and every analysis already use. The published entry's residue/letter column is a mapping fact (``conform``
    checks it) and is not reproduced here; for ``TREH`` that column also carries the published inconsistency
    ``signature`` reads around (atom 8's parents are residue 2 but its residue column is 1).
    """
    record = entry(entry_name)
    name = residue_name or entry_name
    source = provenance or {}
    header = [
        f'; Published Martini 3 sugar topology: {entry_name} from {REFERENCE_NAME}.',
        '; Constraints, bonds, angles, dihedrals and virtual sites are the published values, not a fit.',
        '; The starting coordinates are the mapped AA geometry; this topology pulls them onto published geometry.',
    ]
    if source:
        header.append('; provenance: ' + ' '.join(
            f'{key}={value}' for key, value in source.items() if value not in (None, '')))
    lines = [*header, '', '[ moleculetype ]', f'{name} {record.get("nrexcl", 1)}', '', '[ atoms ]',
             ';   nr  type  resnr  residu  atom  cgnr  charge  mass']
    for atom in record['atoms']:
        lines.append(f'{atom["index"]:6d} {atom["type"]:>6} 1 {name:>5} B{atom["index"]:02d} '
                     f'{atom["index"]:6d} {atom["charge"]:g} {atom["mass"]:g}')
    for section in ('bonds', 'constraints', 'angles', 'dihedrals', 'virtual_sitesn', 'exclusions'):
        rows = record.get(section) or []
        if not rows:
            continue
        lines += ['', f'[ {section} ]']
        for row in rows:
            if section in ('bonds', 'constraints'):
                fields = [str(row['i']), str(row['j']), str(row['function']), f'{row["length"]:g}']
                if 'force' in row:
                    fields.append(f'{row["force"]:g}')
            elif section == 'angles':
                fields = [str(row['i']), str(row['j']), str(row['k']), str(row['function']),
                          f'{row["angle"]:g}', f'{row["force"]:g}']
            elif section == 'dihedrals':
                fields = [str(row['i']), str(row['j']), str(row['k']), str(row['l']),
                          str(row['function']), f'{row["angle"]:g}', f'{row["force"]:g}']
                if row.get('multiplicity') is not None:
                    fields.append(f'{row["multiplicity"]:g}')
            elif section == 'virtual_sitesn':
                fields = [str(row['site']), str(row['function']),
                          *[str(parent) for parent in row['parents']]]
            else:
                fields = [str(row['site']), *[str(atom) for atom in row['atoms']]]
            lines.append(' '.join(fields))
    return '\n'.join(lines) + '\n'


def parameter_delta(topology_text, entry_name, *, layout='reference'):
    """Generated constraint lengths beside the reference's published values, per residue and bead letter.

    The generated topology is what a run would consume, so this compares the numbers as they are written
    rather than recomputing them. Both are reported: reproducing the mapping is not the same claim as
    reproducing the published equilibrium distances.

    ``layout='run'`` reads a topology written the way a run consumes it: one residue per molecule, atoms named
    ``B01..``. A conforming candidate keeps the reference's bead order, so ``B01`` is the reference's atom 1 and
    the published residue/letter is the currency the comparison uses. Without this every generated value reads
    ``None`` beside the published one for a run-layout topology.
    """
    sections = _sections(topology_text)
    reference_entry_record = entry(entry_name)
    reference_atoms = {atom['index']: (atom['residue'], atom['name'])
                       for atom in reference_entry_record['atoms']}
    if layout == 'run':
        currency = {int(row[0]): reference_atoms.get(int(row[0]), (int(row[2]), row[4]))
                    for row in sections.get('atoms', [])}
    else:
        currency = {int(row[0]): (int(row[2]), row[4]) for row in sections.get('atoms', [])}
    generated = {}
    for row in sections.get('constraints', []):
        first, second = int(row[0]), int(row[1])
        if first in currency and second in currency:
            generated[frozenset((currency[first], currency[second]))] = float(row[3])
    bonds = {}
    for row in sections.get('bonds', []):
        first, second = int(row[0]), int(row[1])
        if first in currency and second in currency:
            bonds[frozenset((currency[first], currency[second]))] = (float(row[3]), float(row[4]))
    delta = []
    for item in reference_entry_record['constraints']:
        pair = frozenset((reference_atoms[item['i']], reference_atoms[item['j']]))
        names = sorted(pair, key=lambda name: (name[0], name[1]))
        value = generated.get(pair)
        delta.append({'residue': names[0][0], 'pair': [name[1] for name in names],
                      'reference': item['length'], 'generated': value,
                      'difference': None if value is None else round(value - item['length'], 4),
                      'relative': None if value is None else round((value - item['length']) / item['length'], 4)})
    # The inter-residue bond is reported on the same footing: its length is derived here while the
    # reference fixes one per disaccharide, and its stiffness is the part adopted from the reference.
    for link in signature(reference_entry_record)['links']:
        pair = frozenset((tuple(link['a']), tuple(link['b'])))
        names = sorted(pair, key=lambda name: (name[0], name[1]))
        generated_bond = bonds.get(pair)
        value = None if generated_bond is None else generated_bond[0]
        delta.append({'residue': 'link', 'pair': [name[1] for name in names],
                      'reference': link['length'], 'generated': value,
                      'difference': None if value is None else round(value - link['length'], 4),
                      'relative': None if value is None else round((value - link['length']) / link['length'], 4),
                      'reference_force': link.get('force'),
                      'generated_force': None if generated_bond is None else generated_bond[1]})
    return delta


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

    A virtual site's residue is the residue of the parents that build it, not the file's residue column: the
    published `TREH` atom 8 (the second `TC4`, parents 5-7) carries residue 1 while its parents are residue 2, and
    its `[ virtual_sitesn ]` and `[ exclusions ]` rows agree with the parents. The site belongs to the ring it is
    built from, so the parents' residue is the mapping fact; the column is the anomaly. Reading it the other way
    put two sites in residue 1 and none in residue 2, which made the chemically correct Trehalose candidate fail
    `conform` and kept a correct reference model out of the panel. A site with no parent row (an entry using
    `virtual_sites3`, which this file does not) keeps the column it was read from.
    """
    by_index = {atom['index']: atom for atom in entry_record['atoms']}
    sites = {site['site']: site['parents'] for site in entry_record.get('virtual_sitesn') or []}

    def residue_of(atom):
        parents = sites.get(atom['index']) if not atom['mass'] else None
        numbers = {by_index[parent]['residue'] for parent in parents or [] if parent in by_index}
        return next(iter(numbers)) if len(numbers) == 1 else atom['residue']

    residues = {}
    for atom in entry_record['atoms']:
        residues.setdefault(residue_of(atom), []).append(
            {'name': atom['name'], 'type': atom['type'], 'mass': atom['mass'],
             'virtual_site': not atom['mass']})
    links = []
    for bond in entry_record['bonds']:
        first, second = by_index[bond['i']], by_index[bond['j']]
        if residue_of(first) != residue_of(second):
            links.append({'a': [residue_of(first), first['name']], 'b': [residue_of(second), second['name']],
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
