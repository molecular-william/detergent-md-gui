"""Deterministic bonded drafts from mappings and read-only CG references."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import itertools
import json
import math
from pathlib import Path

from . import FUNCTIONS
from ..mappings.identity import canonical_sha256


_MASSES = {'R': 72, 'S': 54, 'T': 36}
_FALLBACK_BOND_FORCE = 5000.0
_FALLBACK_ANGLE_FORCE = 25.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _format(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Bonded parameters must be finite numbers')
    return format(number, '.12g')


def _reference_term_key(kind, types):
    values = tuple(str(value) for value in types)
    if kind == 'bonds':
        values = tuple(sorted(values))
    else:
        values = min(values, tuple(reversed(values)))
    return '|'.join(values)


def _source_rank(path):
    """Rank known reference families without reading or mutating their files."""
    normalized = path.lower()
    if 'mad database' in normalized and '/ddm/' in normalized:
        return 4
    if 'martini-ddm' in normalized:
        return 4
    if 'mad database' in normalized:
        return 3
    if 'martini' in normalized:
        return 2
    return 1


def _parse_reference(path: Path, root: Path, diagnostics: list[str]):
    section = ''
    atom_types = {}
    rows = []
    try:
        lines = path.read_text(errors='replace').splitlines()
    except OSError as exc:
        diagnostics.append(f'{path}: {exc}')
        return rows
    for line_number, raw in enumerate(lines, 1):
        line = raw.split(';', 1)[0].strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().lower()
            continue
        if not line or line.startswith(('#', ';')):
            continue
        fields = line.split()
        if section == 'atoms':
            if len(fields) < 2:
                diagnostics.append(f'{path}:{line_number}: malformed atom row')
                continue
            try:
                atom_types[int(fields[0])] = fields[1]
            except ValueError:
                diagnostics.append(f'{path}:{line_number}: malformed atom index')
        elif section in ('bonds', 'angles', 'dihedrals'):
            width = {'bonds': 2, 'angles': 3, 'dihedrals': 4}[section]
            if len(fields) < width + 1:
                diagnostics.append(f'{path}:{line_number}: malformed {section} row')
                continue
            try:
                indices = [int(value) for value in fields[:width]]
                function = int(fields[width])
            except (TypeError, ValueError):
                diagnostics.append(f'{path}:{line_number}: malformed {section} indices/function')
                continue
            expected = FUNCTIONS.get(section, {}).get(function)
            if expected is None:
                diagnostics.append(f'{path}:{line_number}: unsupported {section} function {function}')
                continue
            if len(fields) < width + 1 + expected:
                diagnostics.append(f'{path}:{line_number}: malformed {section} parameters')
                continue
            try:
                parameters = [float(value) for value in fields[width + 1:width + 1 + expected]]
            except (TypeError, ValueError):
                diagnostics.append(f'{path}:{line_number}: malformed {section} parameters')
                continue
            if not all(math.isfinite(value) for value in parameters):
                diagnostics.append(f'{path}:{line_number}: nonfinite {section} parameters')
                continue
            types = [atom_types.get(index) for index in indices]
            if any(not value for value in types):
                diagnostics.append(f'{path}:{line_number}: {section} references unknown atom type')
                continue
            relative = path.relative_to(root).as_posix()
            rows.append({
                'kind': section,
                'key': _reference_term_key(section, types),
                'function': function,
                'parameters': parameters,
                'source_rank': _source_rank(relative),
                'path': relative,
                'line': line_number,
                'sha256': _sha256(path),
            })
    return rows


def reference_bond_index(project_root: Path) -> dict:
    """Index CG bonded terms from reference ITPs without mutating them."""
    root = Path(project_root)
    reference_root = root / 'references'
    diagnostics = []
    sources = []
    grouped = {kind: defaultdict(list) for kind in ('bonds', 'angles', 'dihedrals')}
    if reference_root.is_dir() and not reference_root.is_symlink():
        paths = sorted(path for path in reference_root.rglob('*.itp')
                       if path.is_file() and not path.is_symlink()
                       and '/aa/' not in path.relative_to(root).as_posix().lower())
    else:
        paths = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        source_hash = _sha256(path)
        sources.append({'path': relative, 'sha256': source_hash, 'rank': _source_rank(relative)})
        for record in _parse_reference(path, root, diagnostics):
            grouped[record['kind']][record['key']].append(record)

    def pack(records_by_key):
        packed = {}
        for key, records in sorted(records_by_key.items()):
            signatures = Counter((item['function'], tuple(item['parameters'])) for item in records)
            ordered = sorted(
                signatures,
                key=lambda signature: (
                    -max(item['source_rank'] for item in records
                         if (item['function'], tuple(item['parameters'])) == signature),
                    -signatures[signature],
                    min((item['path'], item['line']) for item in records
                        if (item['function'], tuple(item['parameters'])) == signature),
                ),
            )
            packed[key] = []
            for function, parameters in ordered:
                matching = [item for item in records
                            if (item['function'], tuple(item['parameters'])) == (function, parameters)]
                first = min(matching, key=lambda item: (-item['source_rank'], item['path'], item['line']))
                packed[key].append({
                    'function': function,
                    'parameters': list(parameters),
                    'count': signatures[(function, parameters)],
                    'references': [
                        {key: item[key] for key in ('path', 'sha256', 'line')}
                        for item in sorted(matching, key=lambda item: (item['path'], item['line']))
                    ],
                    'source_rank': first['source_rank'],
                })
        return packed

    bonds = pack(grouped['bonds'])
    angles = pack(grouped['angles'])
    dihedrals = pack(grouped['dihedrals'])
    payload = {
        'version': 2, 'sources': sources, 'bonds': bonds,
        'angles': angles, 'dihedrals': dihedrals, 'diagnostics': diagnostics,
    }
    payload['index_sha256'] = canonical_sha256(payload)
    return payload


def _structure_parts(structure):
    atoms = {int(atom['id']): atom for atom in structure.get('atoms', [])}
    raw_edges = structure.get('bonds', [])
    edges = []
    for edge in raw_edges:
        if isinstance(edge, dict):
            pair = (edge.get('a'), edge.get('b'))
        else:
            pair = tuple(edge[:2]) if isinstance(edge, (list, tuple)) and len(edge) >= 2 else ()
        if len(pair) == 2 and pair[0] in atoms and pair[1] in atoms and pair[0] != pair[1]:
            edges.append(tuple(sorted((int(pair[0]), int(pair[1])))))
    return atoms, sorted(set(edges))


def _coordinates_nm(structure):
    atoms, _ = _structure_parts(structure)
    legacy_angstrom = not structure.get('molecule_id') and not structure.get('snapshot')
    factor = 0.1 if legacy_angstrom else 1.0
    return {atom_id: tuple(float(value) * factor for value in atom.get('xyz', (0, 0, 0)))
            for atom_id, atom in atoms.items()}


def _centers(mapping, structure):
    coordinates = _coordinates_nm(structure)
    beads = {bead['name']: bead for bead in mapping.get('beads', [])}
    centers = {}
    for name, bead in beads.items():
        if bead.get('virtual_site'):
            continue
        points = [coordinates[atom_id] for atom_id in bead.get('atoms', []) if atom_id in coordinates]
        if points:
            centers[name] = tuple(sum(point[index] for point in points) / len(points) for index in range(3))
    for name, bead in beads.items():
        if not bead.get('virtual_site'):
            continue
        points = [centers[parent] for parent in bead['virtual_site'].get('parents', []) if parent in centers]
        if points:
            centers[name] = tuple(sum(point[index] for point in points) / len(points) for index in range(3))
    return centers


def _distance(first, second):
    return math.sqrt(sum((first[index] - second[index]) ** 2 for index in range(3)))


def _angle(first, middle, last):
    left = [first[index] - middle[index] for index in range(3)]
    right = [last[index] - middle[index] for index in range(3)]
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 180.0
    cosine = sum(left[index] * right[index] for index in range(3)) / (left_norm * right_norm)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _physical_edges(mapping, structure):
    names = {bead['name'] for bead in mapping.get('beads', []) if not bead.get('virtual_site')}
    if mapping.get('connections'):
        return sorted({tuple(sorted(pair)) for pair in mapping['connections']})
    owner = {atom_id: bead['name'] for bead in mapping.get('beads', [])
             if not bead.get('virtual_site') for atom_id in bead.get('atoms', [])}
    _, edges = _structure_parts(structure)
    return sorted({tuple(sorted((owner[first], owner[second]))) for first, second in edges
                   if first in owner and second in owner and owner[first] != owner[second]
                   and owner[first] in names and owner[second] in names})


def _validate_term(term, physical):
    if not isinstance(term, dict):
        raise ValueError('Each bonded term must be an object')
    kind = term.get('kind')
    if kind not in FUNCTIONS:
        raise ValueError(f'Unsupported bonded section: {kind}')
    beads = term.get('beads')
    arity = {'bonds': 2, 'angles': 3, 'dihedrals': 4}[kind]
    if not isinstance(beads, list) or len(beads) != arity or any(name not in physical for name in beads):
        raise ValueError(f'{kind} terms must name {arity} physical beads')
    function = int(term.get('function', 1))
    parameters = term.get('parameters')
    if function not in FUNCTIONS[kind] or not isinstance(parameters, list) or len(parameters) != FUNCTIONS[kind][function]:
        raise ValueError(f'Unsupported {kind} function or parameter count')
    values = []
    for value in parameters:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError('Bonded parameters must be finite numbers') from None
        if not math.isfinite(number):
            raise ValueError('Bonded parameters must be finite numbers')
        values.append(number)
    return kind, list(beads), function, values


def _canonical_term_key(kind, beads):
    forward = tuple(beads)
    reverse = tuple(reversed(beads))
    return kind, min(forward, reverse)


def topology_from_terms(mapping: dict, structure: dict, terms: list[dict], *, title='Bonded draft') -> str:
    """Build a complete, mapping-bound topology from editable ordinary terms."""
    beads = mapping.get('beads', [])
    physical = {bead['name'] for bead in beads if not bead.get('virtual_site')}
    checked = []
    seen = set()
    for term in terms:
        kind, names, function, parameters = _validate_term(term, physical)
        key = _canonical_term_key(kind, names)
        if key in seen:
            raise ValueError('Duplicate bonded term')
        seen.add(key)
        checked.append((kind, names, function, parameters))
    centers = _centers(mapping, structure)
    edges = _physical_edges(mapping, structure)
    existing_angles = {tuple(names) for kind, names, _, _ in checked if kind == 'angles'}
    adjacency = {name: set() for name in physical}
    for first, second in edges:
        adjacency[first].add(second)
        adjacency[second].add(first)
    for middle, neighbors in adjacency.items():
        for first, last in itertools.combinations(sorted(neighbors), 2):
            names = [first, middle, last]
            if tuple(names) in existing_angles or tuple(reversed(names)) in existing_angles:
                continue
            if first not in centers or middle not in centers or last not in centers:
                continue
            checked.append(('angles', names, 1, [_angle(centers[first], centers[middle], centers[last]), _FALLBACK_ANGLE_FORCE]))
    by_name = {bead['name']: index for index, bead in enumerate(beads, 1)}
    lines = [f'; {title}', '[ moleculetype ]', 'MOL 1', '', '[ atoms ]']
    for index, bead in enumerate(beads, 1):
        size = bead.get('size', 'R')
        mass = 0 if bead.get('virtual_site') else _MASSES.get(size, 72)
        lines.append(f'{index} {bead.get("type") or "C1"} 1 MOL {bead["name"]} {index} {bead.get("charge", 0)} {mass}')
    ring_pairs = set()
    if mapping.get('rings'):
        lines += ['', '[ constraints ]']
        for ring in mapping['rings']:
            ring_names = ring['beads']
            scale = float(ring.get('scale', 1.15))
            for first, second in itertools.combinations(ring_names, 2):
                if first not in centers or second not in centers:
                    continue
                pair = tuple(sorted((first, second)))
                ring_pairs.add(pair)
                lines.append(f'{by_name[first]} {by_name[second]} 1 {_format(_distance(centers[first], centers[second]) * scale)}')
    bonds = [(names, function, parameters) for kind, names, function, parameters in checked if kind == 'bonds']
    if bonds:
        lines += ['', '[ bonds ]']
        for names, function, parameters in bonds:
            if tuple(sorted(names)) in ring_pairs:
                continue
            indices = ' '.join(str(by_name[name]) for name in names)
            lines.append(f'{indices} {function} ' + ' '.join(_format(value) for value in parameters))
    angles = [(names, function, parameters) for kind, names, function, parameters in checked if kind == 'angles']
    if angles:
        lines += ['', '[ angles ]']
        for names, function, parameters in angles:
            indices = ' '.join(str(by_name[name]) for name in names)
            lines.append(f'{indices} {function} ' + ' '.join(_format(value) for value in parameters))
    dihedrals = [(names, function, parameters) for kind, names, function, parameters in checked if kind == 'dihedrals']
    if dihedrals:
        lines += ['', '[ dihedrals ]']
        for names, function, parameters in dihedrals:
            indices = ' '.join(str(by_name[name]) for name in names)
            lines.append(f'{indices} {function} ' + ' '.join(_format(value) for value in parameters))
    virtual_sites = [(index, bead) for index, bead in enumerate(beads, 1) if bead.get('virtual_site')]
    if virtual_sites:
        lines += ['', '[ virtual_sitesn ]']
        for index, bead in virtual_sites:
            parents = ' '.join(str(by_name[name]) for name in bead['virtual_site']['parents'])
            lines.append(f'{index} 1 {parents}')
        lines += ['', '[ exclusions ]']
        for index, bead in virtual_sites:
            parents = ' '.join(str(by_name[name]) for name in bead['virtual_site']['parents'])
            lines.append(f'{index} {parents}')
    return '\n'.join(lines) + '\n'


def _select_reference(index, kind, types, mapping_name=''):
    key = _reference_term_key(kind, types)
    candidates = list(index.get(kind, {}).get(key, []))
    if not candidates:
        return key, None, []
    molecule_name = str(mapping_name or '').lower().replace('_', '-')

    def rank(record):
        paths = [reference['path'].lower() for reference in record.get('references', [])]
        molecule_match = bool(molecule_name and any(molecule_name in path for path in paths))
        path = min(paths) if paths else ''
        return (int(molecule_match), int(record.get('source_rank', 0)),
                int(record.get('count', 0)), path)

    ordered = sorted(
        candidates,
        key=lambda record: (-rank(record)[0], -rank(record)[1], -rank(record)[2], rank(record)[3]),
    )
    selected = ordered[0]
    selected_rank = rank(selected)[:3]
    competing = [record for record in ordered
                 if rank(record)[:3] == selected_rank
                 and (record['function'], tuple(record['parameters'])) !=
                 (selected['function'], tuple(selected['parameters']))]
    return key, selected, competing


def _term_provenance(key, selected, competing, *, fallback=False, context=None):
    if selected is None:
        result = {
            'fallback': True,
            'references': [],
            'matched_key': key,
            'confidence': 0.0,
            'ambiguity': [],
        }
        if context is not None:
            result['context'] = context
        return result
    total = selected['count'] + sum(record['count'] for record in competing)
    ambiguity = [
        {'function': record['function'], 'parameters': list(record['parameters']),
         'count': record['count'], 'source_rank': record['source_rank']}
        for record in competing
    ]
    result = {
        'fallback': fallback,
        'references': deepcopy(selected['references']),
        'matched_key': key,
        'confidence': selected['count'] / total if total else 0.0,
        'ambiguity': ambiguity,
    }
    if context is not None:
        result['context'] = context
    return result


def _term_context(physical, names):
    return {
        'types': [physical[name].get('type') or '' for name in names],
        'sizes': [physical[name].get('size') or '' for name in names],
        'arity': len(names),
    }


def generate(mapping: dict, structure: dict, project_root: Path) -> dict:
    """Generate a nonpersistent bonded draft for one mapping."""
    if not isinstance(mapping, dict) or not isinstance(structure, dict):
        raise ValueError('A mapping and molecule structure are required')
    physical = {bead['name']: bead for bead in mapping.get('beads', []) if not bead.get('virtual_site')}
    centers = _centers(mapping, structure)
    index = reference_bond_index(project_root)
    diagnostics = list(index['diagnostics'])
    terms = []
    mapping_name = mapping.get('name', '')
    edges = _physical_edges(mapping, structure)
    term_keys = set()
    for first, second in edges:
        first_type = physical.get(first, {}).get('type') or ''
        second_type = physical.get(second, {}).get('type') or ''
        key, selected, competing = _select_reference(
            index, 'bonds', [first_type, second_type], mapping_name)
        if selected:
            parameters = [_format(value) for value in selected['parameters']]
            function = str(selected['function'])
            provenance = _term_provenance(
                key, selected, competing,
                context=_term_context(physical, [first, second]),
            )
            if competing:
                diagnostics.append(f'Ambiguous reference bond {key}; selected deterministic consensus for {first}-{second}.')
        else:
            if first not in centers or second not in centers:
                raise ValueError(f'Cannot place bond {first}-{second}: bead coordinates are unavailable')
            parameters = [_format(_distance(centers[first], centers[second])), _format(_FALLBACK_BOND_FORCE)]
            function = '1'
            provenance = _term_provenance(
                key, None, [], fallback=True,
                context=_term_context(physical, [first, second]),
            )
            diagnostics.append(f'No exact reference bond for {first_type}|{second_type}; used geometry fallback for {first}-{second}.')
        terms.append({'kind': 'bonds', 'beads': [first, second], 'function': function,
                      'parameters': parameters, 'provenance': provenance})
        term_keys.add(_canonical_term_key('bonds', [first, second]))
    adjacency = {name: set() for name in physical}
    for first, second in edges:
        adjacency[first].add(second)
        adjacency[second].add(first)
    for middle, neighbors in adjacency.items():
        for first, last in itertools.combinations(sorted(neighbors), 2):
            if first not in centers or middle not in centers or last not in centers:
                continue
            names = [first, middle, last]
            key, selected, competing = _select_reference(
                index, 'angles', [physical[name].get('type') or '' for name in names], mapping_name)
            if selected:
                function = str(selected['function'])
                parameters = [_format(value) for value in selected['parameters']]
                provenance = _term_provenance(
                    key, selected, competing,
                    context=_term_context(physical, names),
                )
                if competing:
                    diagnostics.append(f'Ambiguous reference angle {key}; selected deterministic consensus for {first}-{middle}-{last}.')
            else:
                function = '1'
                parameters = [_format(_angle(centers[first], centers[middle], centers[last])), _format(_FALLBACK_ANGLE_FORCE)]
                provenance = _term_provenance(
                    key, None, [], fallback=True,
                    context=_term_context(physical, names),
                )
                diagnostics.append(f'No exact reference angle for {key}; used geometry fallback for {first}-{middle}-{last}.')
            term_key = _canonical_term_key('angles', names)
            if term_key in term_keys:
                continue
            terms.append({'kind': 'angles', 'beads': names, 'function': function,
                          'parameters': parameters, 'provenance': provenance})
            term_keys.add(term_key)

    for second, third in sorted((first, second) for first, second in edges):
        left = sorted(adjacency.get(second, set()) - {third})
        right = sorted(adjacency.get(third, set()) - {second})
        for first in left:
            for fourth in right:
                names = [first, second, third, fourth]
                key, selected, competing = _select_reference(
                    index, 'dihedrals', [physical[name].get('type') or '' for name in names], mapping_name)
                if not selected:
                    continue
                term_key = _canonical_term_key('dihedrals', names)
                if term_key in term_keys:
                    continue
                if competing:
                    diagnostics.append(f'Ambiguous reference dihedral {key}; selected deterministic consensus for {first}-{second}-{third}-{fourth}.')
                terms.append({
                    'kind': 'dihedrals', 'beads': names, 'function': str(selected['function']),
                    'parameters': [_format(value) for value in selected['parameters']],
                    'provenance': _term_provenance(
                        key, selected, competing,
                        context=_term_context(physical, names),
                    ),
                })
                term_keys.add(term_key)
    topology = topology_from_terms(mapping, structure, terms, title='Automatic bonded draft')
    provenance = {
        'algorithm': {'name': 'reference-bond-angle-dihedral-consensus', 'version': '2'},
        'reference_index_sha256': index['index_sha256'],
        'references': sorted({reference['path'] for term in terms for reference in term['provenance']['references']}),
    }
    return {'topology': topology, 'interactions': terms, 'provenance': provenance, 'diagnostics': diagnostics}
