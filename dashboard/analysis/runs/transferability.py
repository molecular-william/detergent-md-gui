"""Do our bead types carry one set of numbers across molecules?

Every other analysis in this repository compares our model against its own atomistic reference, within one run. That
answers "is the mapping, the mapped trajectory and the simulated trajectory one assignment", which the ring
constraints make agree by construction. It cannot answer the question a force field's bead types actually make a
claim about: does a bead type mean the same thing in every molecule it appears in?

This reads the published reports of several runs and puts the *same bead-type pair* side by side. The pairing is by
bead type, never by atom index or residue number, because those differ between molecules by definition. Whether a
pair sits inside one ring or joins two is part of the key, since those are different interactions even when the types
are the same -- an `SP1r`-`SP1r` bond inside a ring is not the glycosidic linkage.

The published row names beads as `[residue, name]`, so the types come from each run's own mapping candidate, which is
what the caller passes alongside the report. A signature that appears in one molecule only is reported with the
molecules that have it; nothing is padded to make a table look square.
"""


def bead_types(candidate):
    """A mapping's beads to their types, keyed the way a published report names them.

    A report names a bead `[residue, letter]` -- `[1, "A"]` -- and the letter alone is ambiguous: in a two-ring
    sugar, `S1A` and `S2A` are different beads with different types. So the primary key is the pair, with the bead's
    own name as a fallback for a report that spells it that way. Virtual sites are included: they are beads too.
    """
    types = {}
    for bead in (candidate or {}).get('beads', []):
        if not bead.get('type'):
            continue
        if bead.get('name'):
            types[bead['name']] = bead['type']
        if bead.get('letter'):
            types[(bead.get('residue'), bead['letter'])] = bead['type']
    return types


def _role(pair):
    """`intra` when both beads belong to one residue, `inter` when the pair joins two."""
    (left_residue, _), (right_residue, _) = pair
    return 'intra' if left_residue == right_residue else 'inter'


def _signature(types, pair):
    """The key a comparison is made under: the two bead types, order-insensitive, with the role."""
    names = [types.get((residue, bead), types.get(bead, bead)) for residue, bead in pair]
    return tuple(sorted(names)), _role(pair)


def compare(entries):
    """`{molecule: {'report': ..., 'candidate': ...}}` in, per bead-type signature out.

    Each signature carries every molecule that states it, with that molecule's means and the number of rows it
    contributed, plus the spread of the atomistic means across molecules -- which is the number that answers the
    transferability question: a spread near zero means the same bead-type pair holds the same geometry wherever it
    appears.
    """
    signatures = {}
    for molecule, entry in sorted(entries.items()):
        types = bead_types(entry.get('candidate'))
        rows = ((entry.get('report') or {}).get('pairs') or {}).get('rows') or []
        for row in rows:
            key = _signature(types, row['pair'])
            entry_for_molecule = signatures.setdefault(key, {'molecules': {}, 'rows': 0})
            aa = (row.get('aa') or {}).get('mean')
            cg = (row.get('cg') or {}).get('mean')
            record = entry_for_molecule['molecules'].setdefault(
                molecule, {'atomistic': [], 'cg': [], 'pairs': []})
            if aa is not None:
                record['atomistic'].append(aa)
            if cg is not None:
                record['cg'].append(cg)
            # The pair as the report labels it. A type pair can cover more than one of these -- and when it does,
            # a spread across molecules may be the labelling rather than the model, which a reader has to be able
            # to tell apart.
            record['pairs'].append([f'{residue}{bead}' for residue, bead in row['pair']])
            entry_for_molecule['rows'] += 1

    result = []
    for (types, role), entry in sorted(signatures.items()):
        molecules = {}
        atomistic_means = []
        for molecule, record in sorted(entry['molecules'].items()):
            mean = sum(record['atomistic']) / len(record['atomistic']) if record['atomistic'] else None
            cg_mean = sum(record['cg']) / len(record['cg']) if record['cg'] else None
            molecules[molecule] = {'atomistic_mean_nm': mean, 'cg_mean_nm': cg_mean,
                                   'rows': len(record['atomistic']), 'pairs': record['pairs']}
            if mean is not None:
                atomistic_means.append(mean)
        spread = None
        if len(atomistic_means) > 1:
            average = sum(atomistic_means) / len(atomistic_means)
            spread = 100.0 * (max(atomistic_means) - min(atomistic_means)) / average
        result.append({'types': list(types), 'role': role, 'molecules': molecules,
                       'spread_pct': spread, 'rows': entry['rows']})

    return {
        'signatures': result,
        'molecules': sorted(entries),
        'interpretation': (
            'This compares our model across molecules, not against experiment. A spread of nearly zero says the '
            'same bead-type pair holds the same atomistic geometry wherever it appears, which is what makes the '
            'bead types a shared library rather than per-molecule fits. A linkage is where a difference is expected: '
            'the published entries give each disaccharide its own linkage stiffness, so the linkage is not the same '
            'interaction in two different molecules even when the types on either side are.'
        ),
    }
