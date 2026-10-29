"""How far the constraints a draft asks for sit from the geometry the molecule is built at.

The draft writes a `[ constraints ]` section for every pair of beads inside a ring: the length is the distance between
those beads' centres in the molecule's own atomistic structure, multiplied by the ring's scale (1.15 by default), and
the bond between the pair is dropped because the constraint replaces it. That is a rigid, self-consistent statement
about *one* conformer -- the isolated molecule's MMFF structure -- and it is then handed to a simulation whose molecule
comes from somewhere else: the mapped atoms of an atomistic run in solvent, at whatever conformer that run sampled.

This measures the distance between those two statements, per constrained pair. It answers the question a LINCS failure
raises -- `Constraint error in algorithm Lincs at step 6174` -- without guessing: a constraint whose length is far from
the distance the beads actually sit at is a constraint the solver has to fight, and a ring made of three of them has
no way to relax except by tearing apart the pair that carries the most error.

Nothing here decides what to do about it. The three numbers per pair are the draft's own centre distance, the length
the constraint asks for, and the distance in the mapped structure; a later task chooses between constraining only the
pairs whose geometry is close and writing the rest as bonds, and that choice needs this number first.
"""
from __future__ import annotations

from pathlib import Path

from ... import itp

#: How the constrained pair was matched to the mapped structure's rows.
BY_NAME = 'name'
BY_ORDER = 'order'


def constraints(topology_text):
    """A draft topology's `[ constraints ]` as `[{'indices': (i, j), 'beads': (a, b), 'length_nm': value}]`.

    The pair is named through the same topology's `[ atoms ]` rows, because a bead named `B07` in a run's structure is
    the seventh bead of the mapping that built it: indices travel between the two files, names do not.
    """
    names, rows = {}, []
    for section, lines in itp.sections(topology_text):
        if section not in ('atoms', 'constraints'):
            continue
        for _number, body in lines:
            fields = body.split()
            if section == 'atoms':
                if len(fields) >= 5:
                    names[int(fields[0])] = fields[4]
                continue
            if len(fields) < 3:
                continue
            try:
                first, second, function = (int(fields[0]), int(fields[1]), int(fields[2]))
                length = float(fields[3])
            except (IndexError, ValueError):
                raise ValueError(f'Invalid constraint row: {body}') from None
            if function != 1:
                raise ValueError(f'Only constraint function 1 is a length; {body} asks for function {function}')
            rows.append({'indices': (first, second), 'beads': (names.get(first), names.get(second)),
                         'length_nm': length})
    return rows


def read_gro(path):
    """A `.gro` in file order as `[(name, [x, y, z])]`, in nanometres.

    Order rather than names, because a run renames the beads `B01..` while the mapping that made it calls them
    `S1A`, `TAIL2` and so on. The caller is told which pairing it got, so neither spelling is an assumption.
    """
    lines = Path(path).read_text().splitlines()
    if len(lines) < 3:
        raise ValueError(f'{path} is not a .gro file')
    try:
        count = int(lines[1].strip())
    except ValueError:
        raise ValueError(f'{path}: the second line is not an atom count') from None
    rows = []
    for line in lines[2:2 + count]:
        rows.append((line[10:15].strip(), [float(line[20:28]), float(line[28:36]), float(line[36:44])]))
    if len(rows) != count:
        raise ValueError(f'{path}: {count} atoms claimed, {len(rows)} present')
    return rows


def align(draft, rows):
    """Match a structure's rows to the draft's beads: by name when it has them, by order when it does not."""
    names = [bead['name'] for bead in draft['beads']]
    present = {name for name, _ in rows}
    if all(name in present for name in names):
        positions = {name: position for name, position in rows}
        return [positions[name] for name in names], BY_NAME
    if len(rows) != len(names):
        raise ValueError(f'the structure has {len(rows)} beads and the draft has {len(names)}, and neither '
                         f'spelling matches: the two do not describe the same molecule')
    return [position for _, position in rows], BY_ORDER


def _distance(first, second):
    return sum((first[axis] - second[axis]) ** 2 for axis in range(3)) ** 0.5


def measure(draft, rows):
    """Per constrained pair: the draft's own distance, the constraint, and the mapped distance.

    `rows` is a structure's bead positions, in the draft's bead order -- `align` produces that from a `.gro`.
    """
    positions, pairing = align(draft, rows)
    centres = {bead['name']: bead['position'] for bead in draft['beads']}
    pairs = []
    for row in constraints(draft['topology']):
        first, second = row['beads']
        if first not in centres or second not in centres:
            raise ValueError(f'the constraint names {first}-{second}, which the draft has no centres for')
        index_first, index_second = row['indices']
        draft_distance = _distance(centres[first], centres[second])
        mapped_distance = _distance(positions[index_first - 1], positions[index_second - 1])
        difference = row['length_nm'] - mapped_distance
        pairs.append({'beads': [first, second], 'indices': list(row['indices']),
                      'constraint_nm': round(row['length_nm'], 6),
                      'draft_nm': round(draft_distance, 6),
                      'mapped_nm': round(mapped_distance, 6),
                      'constraint_over_mapped_nm': round(difference, 6),
                      'constraint_over_mapped_pct': round(100.0 * difference / mapped_distance, 3) if mapped_distance else None})
    pairs.sort(key=lambda row: abs(row['constraint_over_mapped_nm']), reverse=True)
    overs = [row['constraint_over_mapped_nm'] for row in pairs]
    percents = [row['constraint_over_mapped_pct'] for row in pairs if row['constraint_over_mapped_pct'] is not None]
    return {
        'molecule_id': draft.get('molecule_id'),
        'beads': len(draft['beads']),
        'paired_by': pairing,
        'pairs': pairs,
        'largest_over_nm': overs[0] if overs else None,
        'largest_over_pct': percents[0] if percents else None,
        'median_over_pct': sorted(percents)[len(percents) // 2] if percents else None,
        'interpretation': (
            'The constraint is the ring pair\'s distance in the molecule\'s own atomistic structure times the ring '
            'scale; the mapped distance is where those two beads sit in a mapped structure from a run. A constraint '
            'far longer than the mapped distance starts every step by pulling the pair together, and a ring of three '
            'such constraints has no way to give.'
        ),
    }


def format_report(measured):
    """The measurement as lines, largest mismatch first."""
    lines = [f"{measured['molecule_id']}: {len(measured['pairs'])} constrained pairs, paired by "
             f"{measured['paired_by']}", '']
    lines.append(f"{'pair':22} {'constraint':>10} {'draft':>9} {'mapped':>9} {'over':>9} {'over %':>8}")
    for row in measured['pairs']:
        lines.append(f"{'-'.join(row['beads']):22} {row['constraint_nm']:10.4f} {row['draft_nm']:9.4f} "
                     f"{row['mapped_nm']:9.4f} {row['constraint_over_mapped_nm']:+9.4f} "
                     f"{row['constraint_over_mapped_pct']:+8.2f}")
    lines.append('')
    lines.append(f"largest over: {measured['largest_over_nm']:+.4f} nm "
                 f"({measured['largest_over_pct']:+.2f}%), median {measured['median_over_pct']:+.2f}%")
    return '\n'.join(lines)
