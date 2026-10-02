"""Deterministic bonded drafts from mappings and read-only CG references."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from ... import files
from ..mappings.identity import canonical_sha256
from ..sugars import angstrom_factor
from . import FUNCTIONS

#: One-entry memo for reference_bond_index, keyed on the source stamp. See files.memo.
_BOND_INDEX_CACHE = {}


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


# Which Martini generation a reference file belongs to, where the file itself does not say.
#
# `references/martini-ddm.itp` is Martini 2 (its bead types are `P1`/`P2`/`P4`/`C1` with bead masses 44-60), and the
# MAD Database's detergents are the same generation (its DDM entry says it was built by attaching an SDS tail to
# maltose, and its note about bonds over 25000 being treated as constraints is Martini 2's convention). A reference
# whose version is not stated is `None`, which means "usable": an unknown is not evidence of a mismatch, and
# excluding it would silently drop parameters. A sidecar (`<file>.source.json`) may state `martini_version`.
# `references/M3-Lipid-Parameters/` is the published Martini 3 lipid set (DOI 10.1021/acscentsci.5c00755): stating
# its generation is what keeps it out of a Martini 2 mapping's lookup, rather than relying on its version reading as
# unknown -- which is treated as usable, deliberately, for files that genuinely do not say.
_KNOWN_VERSIONS = {'martini-ddm': 2, 'references/mad database/': 2, 'm3-lipid-parameters': 3}


def _reference_version(relative: str, path=None) -> int | None:
    """The generation a reference file belongs to: from its sidecar, else from a known family, else unknown.

    `path` is the file itself when the caller has it, so a sidecar is found beside the file rather than beside a
    relative string that only resolves from one working directory.
    """
    file_path = Path(path) if path is not None else Path(relative)
    for sidecar in (file_path.with_name(file_path.name + '.source.json'),
                    file_path.with_suffix('.source.json')):
        if sidecar.is_file():
            try:
                stated = json.loads(sidecar.read_text()).get('martini_version')
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(stated, int):
                return stated
    normalized = relative.lower()
    for family, version in _KNOWN_VERSIONS.items():
        if family in normalized:
            return version
    return None


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


#: The contexts of the named defaults that mean something to a molecule this project builds: a bond in the middle of
#: a chain, one at its end, the over-mapping variant, and the general angle default. The file's other contexts
#: (`plasm`, `ether`, `glyc`, `bmp`, `fa`, ...) describe lipids nobody here builds, so they are parsed and never chosen.
NAMED_CONTEXTS = ('mid_5long', 'mid', 'end', 'def')

#: Generalised beats incidental: a named default is one published row for every molecule with that bead signature,
#: where a per-molecule `[ bonds ]` line is whatever that molecule happened to use. It ranks above those lines and
#: below a reference fitted to the molecule itself.
NAMED_DEFAULT_RANK = 9


def _parse_named_defaults(path: Path, root: Path, diagnostics: list[str]) -> dict:
    """The `#define` rows as `{kind: {key: [record]}}`, with the context kept and the macro named.

    This file is a library of named generalised parameters rather than a `[ bondtypes ]` table: `<b|a|d>_<bead
    types>_<context>`. The context is the content -- `b_C1_C1_mid` 0.490 against `b_C1_C1_end` 0.500 -- and a
    three-bead tail has two bonds and both of them end it.
    """
    kinds = {'b': 'bonds', 'a': 'angles', 'd': 'dihedrals'}
    widths = {'bonds': 2, 'angles': 3, 'dihedrals': 4}
    rows = {kind: defaultdict(list) for kind in widths}
    section = ''
    try:
        lines = path.read_text(errors='replace').splitlines()
    except OSError as exc:
        diagnostics.append(f'{path}: {exc}')
        return rows
    relative = path.relative_to(root).as_posix()
    for number, raw in enumerate(lines, 1):
        line = raw.split(';', 1)[0].strip()
        if line.startswith('['):
            section = line.strip('[] ').strip().lower()
            continue
        if not line.startswith('#define') or section not in ('bondtypes', 'angletypes', 'dihedraltypes'):
            continue
        fields = line.split()[1:]
        if len(fields) < 2 or len(fields[0]) < 3:
            continue
        kind = kinds.get(fields[0][0])
        if kind is None or fields[0][1] != '_':
            continue
        body = fields[0][2:]
        context = next((name for name in NAMED_CONTEXTS if body.endswith('_' + name)), None)
        if context is None:
            continue
        types = body[:-(len(context) + 1)].split('_')
        if len(types) != widths[kind]:
            continue
        try:
            function = int(fields[1])
            expected = FUNCTIONS[kind][function]
            parameters = [float(value) for value in fields[2:2 + expected]]
        except (IndexError, KeyError, ValueError):
            continue
        if len(parameters) != expected:
            continue
        key = _reference_term_key(kind, types)
        rows[kind][key].append({
            'macro': fields[0], 'context': context, 'function': function, 'parameters': parameters,
            'count': 1, 'source_rank': NAMED_DEFAULT_RANK,
            'references': [{'path': relative, 'sha256': _sha256(path), 'line': number}],
            'martini_versions': [],
        })
    return rows


def _reference_paths(root):
    """Every reference ITP the bonded index reads; AA directories are excluded."""
    reference_root = root / 'references'
    if not reference_root.is_dir() or reference_root.is_symlink():
        return []
    return sorted(path for path in reference_root.rglob('*.itp')
                  if path.is_file() and not path.is_symlink()
                  and '/aa/' not in path.relative_to(root).as_posix().lower())


def reference_bond_index(project_root: Path) -> dict:
    """Index CG bonded terms from reference ITPs without mutating them.

    Cached on the source stamp: otherwise every generate re-walks the reference tree and
    re-hashes each ITP. Treat the returned index as read-only: it is shared.
    """
    root = Path(project_root)
    return files.memo(_BOND_INDEX_CACHE, files.stamp(_reference_paths(root)), lambda: _build_bond_index(root))


def _build_bond_index(root: Path) -> dict:
    """Walk, hash and parse the reference ITPs. Called through the memo above."""
    diagnostics = []
    sources = []
    grouped = {kind: defaultdict(list) for kind in ('bonds', 'angles', 'dihedrals')}
    paths = _reference_paths(root)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        source_hash = _sha256(path)
        version = _reference_version(relative, path)
        sources.append({'path': relative, 'sha256': source_hash, 'rank': _source_rank(relative),
                        'martini_version': version})
        for record in _parse_reference(path, root, diagnostics):
            # The record carries its own file's generation, so selection never has to resolve a relative path again.
            record['martini_version'] = version
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
                    'martini_versions': sorted({item.get('martini_version') for item in matching}, key=str),
                })
        return packed

    bonds = pack(grouped['bonds'])
    angles = pack(grouped['angles'])
    dihedrals = pack(grouped['dihedrals'])
    named_defaults = {kind: defaultdict(list) for kind in ('bonds', 'angles', 'dihedrals')}
    for named_path in paths:
        parsed = _parse_named_defaults(named_path, root, diagnostics)
        for kind, keyed in parsed.items():
            for key, records in keyed.items():
                named_defaults[kind][key].extend(records)
    payload = {
        'version': 2, 'sources': sources, 'bonds': bonds,
        'angles': angles, 'dihedrals': dihedrals, 'diagnostics': diagnostics,
        'named_defaults': {kind: dict(keyed) for kind, keyed in named_defaults.items()},
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
    factor = angstrom_factor(structure)
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
    if len(set(beads)) != len(beads):
        # GROMACS refuses these outright -- "Duplicate atom index (6) in dihedrals" -- and it is right to: a
        # dihedral whose first and last atom are the same is not a dihedral, and the bond/angle equivalents are
        # equally meaningless. A repeated bead is a repeated atom once the term is rendered.
        raise ValueError(f'{kind} terms must name {arity} distinct beads; {beads} repeats one')
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


def _record_versions(record) -> set:
    """Which Martini generations a record's own sources belong to (None where a file does not say)."""
    if 'martini_versions' in record:
        return set(record['martini_versions'])
    stamped = record.get('martini_version')
    if stamped is not None or 'martini_version' in record:
        return {stamped}
    return {_reference_version(reference.get('path') or '') for reference in record.get('references') or []}


def _select_reference(index, kind, types, molecule='', martini_version=None, context=None):
    """The best reference for one term, and whatever else could have described it.

    Three sources, in order. A reference fitted to *this molecule* wins outright: `molecule` names it, and it is the
    only source fitted to the ensemble the project measures against. Then a *named default* in the right context --
    one published row for every molecule with that bead signature beats whatever incidental value a lipid's own
    `[ bonds ]` line happens to carry. Then the best parsed reference, which is where the sugar terms still come from.

    `molecule` used to be the mapping's *whole* name (`DDM draft from the automatic recogniser (Martini 3)`) tested as
    a substring of the path, which is never true, so `references/bartender/DDM.itp` could sit in the tree and never be
    chosen. A name's words are not used as tokens either: `martini`, `draft` and `automatic` would match half the
    reference tree.
    """
    key = _reference_term_key(kind, types)
    candidates = list(index.get(kind, {}).get(key, []))
    named = [record for record in (index.get('named_defaults') or {}).get(kind, {}).get(key, [])
             if context and record['context'] == context]
    if not candidates:
        if named:
            return key, named[0], []
        return key, None, []
    if martini_version is not None:
        # A term may be described by several files, and it is kept only if some source is of the requested
        # generation (or says nothing at all). Guessing a version from bead-type letters cannot work -- Martini 2 and
        # 3 both use `C1` -- and importing a Martini 2 parameter into a Martini 3 model is exactly the mixing this
        # route exists to avoid. When nothing matches, the term falls back to geometry and says so, which is a
        # weaker parameter than a mixed one and a stronger claim than a silent one.
        candidates = [record for record in candidates
                      if martini_version in _record_versions(record) or None in _record_versions(record)]
        if not candidates:
            return key, None, []
    molecule_name = str(molecule or '').lower().replace('_', '-')

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
    fitted = [record for record in ordered if rank(record)[0]]
    fitted_values = {(record['function'], tuple(record['parameters'])) for record in fitted}
    if named and (not fitted or len(fitted_values) > 1):
        # A fit is keyed by bead type, so it cannot say *which* of two bonds with the same signature it fitted -- for
        # a three-bead tail it holds both of them and either would be applied to both. Where the fit is ambiguous like
        # that, the published context-aware default is what knows the difference between a chain end and its middle;
        # where the fit is unambiguous (one value for the pair), it wins as the molecule's own measurement.
        chosen = named[0]
        competing = [record for record in ordered
                     if (record['function'], tuple(record['parameters'])) !=
                     (chosen['function'], tuple(chosen['parameters']))]
        return key, chosen, competing
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
    if selected.get('macro'):
        # The published name, so a reader sees which one was applied rather than only its numbers.
        result['macro'] = selected['macro']
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
    # A mapping that states its Martini generation gets only that generation's references: mixed generations are
    # what this filter exists to prevent, and a mapping that says nothing keeps the old behaviour.
    martini_version = mapping.get('martini_version')
    martini_version = int(martini_version) if isinstance(martini_version, (int, str)) and str(martini_version).isdigit() else None
    centers = _centers(mapping, structure)
    index = reference_bond_index(project_root)
    diagnostics = list(index['diagnostics'])
    terms = []
    molecule = mapping.get('molecule_id') or mapping.get('name', '')
    edges = _physical_edges(mapping, structure)
    # How many beads each one is bonded to, because the named defaults distinguish a chain end from a chain middle and
    # only the graph knows which a bond is. A bond with a terminal bead on either side is an end bond.
    degree = defaultdict(int)
    for first, second in edges:
        degree[first] += 1
        degree[second] += 1
    term_keys = set()
    for first, second in edges:
        first_type = physical.get(first, {}).get('type') or ''
        second_type = physical.get(second, {}).get('type') or ''
        key, selected, competing = _select_reference(
            index, 'bonds', [first_type, second_type], molecule, martini_version,
            context='end' if min(degree[first], degree[second]) <= 1 else 'mid')
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
                index, 'angles', [physical[name].get('type') or '' for name in names], molecule,
                martini_version, context='def')
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
                if fourth == first:
                    # A ring closure: on a three-membered ring the bead on the other side of the edge is the same
                    # bead, and `[first, second, third, first]` is not a dihedral. The proper term for this edge is
                    # emitted when the walk starts from a bead that is not the closure.
                    diagnostics.append(
                        f'Skipped a degenerate dihedral over {first}-{second}-{third}: its ends are the same bead.')
                    continue
                names = [first, second, third, fourth]
                key, selected, competing = _select_reference(
                    index, 'dihedrals', [physical[name].get('type') or '' for name in names], molecule,
                    martini_version)
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
