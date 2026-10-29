"""The named Martini 3 bonded defaults: a chain-end bond is not a chain-middle bond.

`martini_v3.0.0_ffbonded_v2.itp` is a library of named generalised parameters rather than a `[ bondtypes ]` table, and
the name carries the content: `b_C1_C1_mid` 0.490 against `b_C1_C1_end` 0.500. Our draft used to take its tail bond
from whichever lipid's own `[ bonds ]` line matched first, which is an incidental value for a different molecule.

Two things are pinned here: that the `#define` rows are read with their context, and that the real DDM draft ends up
with the published end/inside pair rather than one value applied to both bonds.
"""
from __future__ import annotations

from pathlib import Path

from dashboard.models.bonded import generation
from detergent_pdc.models.molecules import detergent_cg

from tests.harness.support import PROJECT_ROOT

MOLECULE_ROOT = PROJECT_ROOT / 'molecules'

DEFAULTS = """[ bondtypes ]
#define b_C1_C1_mid         1      0.490    2800.0    ; in the middle of an alkane chain
#define b_C1_C1_end         1      0.500    2800.0    ; at the end of the chain
#define b_C1_C1_mid_5long   1      0.520    2800.0    ; over-mapping a bead
#define b_C1_C4_mid         1      0.475    2800.0    ; another signature entirely

[ angletypes ]
#define a_C1_C1_C1_def      1      180.0    13.5
#define a_SP1_SP1_SP1_glyc  1      100.0    20.0      ; a lipid context this project does not build
"""


def project(tmp_path) -> Path:
    root = tmp_path / 'project'
    (root / 'references').mkdir(parents=True)
    (root / 'references' / 'named.itp').write_text(DEFAULTS)
    return root


def test_the_defines_are_read_with_their_context(tmp_path):
    index = generation.reference_bond_index(project(tmp_path))

    records = index['named_defaults']['bonds']['C1|C1']

    contexts = {record['context']: record for record in records}
    assert contexts['end']['parameters'] == [0.5, 2800.0]
    assert contexts['end']['macro'] == 'b_C1_C1_end'
    assert contexts['mid']['parameters'] == [0.49, 2800.0]
    assert contexts['mid_5long']['parameters'] == [0.52, 2800.0]
    assert 'C1|C4' in index['named_defaults']['bonds'], 'another signature is indexed under its own key'


def test_the_context_decides_which_one_is_chosen(tmp_path):
    index = generation.reference_bond_index(project(tmp_path))

    end = generation._select_reference(index, 'bonds', ['C1', 'C1'], '', 3, context='end')
    middle = generation._select_reference(index, 'bonds', ['C1', 'C1'], '', 3, context='mid')

    assert end[1]['parameters'] == [0.5, 2800.0] and end[1]['macro'] == 'b_C1_C1_end'
    assert middle[1]['parameters'] == [0.49, 2800.0] and middle[1]['macro'] == 'b_C1_C1_mid'


def test_a_lipid_only_context_is_never_chosen(tmp_path):
    """`_glyc` describes a lipid nobody here builds, so a term with no context gets nothing from it."""
    index = generation.reference_bond_index(project(tmp_path))

    key, selected, _ = generation._select_reference(index, 'angles', ['SP1', 'SP1', 'SP1'], '', 3, context='def')

    assert selected is None or selected['parameters'] != [100.0, 20.0], selected


def test_a_three_bead_tail_takes_the_end_bond_and_then_the_middle_one(tmp_path):
    """The repository's own DDM tail, in the shape a mapping gives it: a head bead, then three C1 beads.

    The free end's bond is an `_end` bond because TAIL1 has nothing beyond it; the next one runs on into the head, so
    neither of its beads is a terminus and it takes the `_mid` value. Both are published; neither is incidental.
    """
    import json

    candidate = tmp_path / 'tail.json'
    candidate.write_text(json.dumps({
        'schema_version': 3, 'molecule_id': 'DDM', 'name': 'a tail for the test', 'martini_version': 3,
        'beads': [{'name': 'HEAD', 'type': 'SP1r', 'size': 'S', 'atoms': [13, 14, 34, 35]},
                  {'name': 'TAIL1', 'type': 'C1', 'size': 'R', 'atoms': [1, 2, 3, 4]},
                  {'name': 'TAIL2', 'type': 'C1', 'size': 'R', 'atoms': [5, 6, 7, 8]},
                  {'name': 'TAIL3', 'type': 'C1', 'size': 'R', 'atoms': [9, 10, 11, 12]}],
        'connections': [['HEAD', 'TAIL3'], ['TAIL3', 'TAIL2'], ['TAIL2', 'TAIL1']], 'rings': []}))

    draft = detergent_cg.derive(candidate, MOLECULE_ROOT, MOLECULE_ROOT.parent)
    bonds = {}
    section = None
    for line in draft['topology'].splitlines():
        stripped = line.strip()
        if stripped.startswith('['):
            section = stripped
            continue
        if section == '[ bonds ]' and stripped:
            # `i j funct length force`, so the parameters are the last two fields.
            bonds[tuple(stripped.split()[:2])] = tuple(stripped.split()[-2:])

    # These two pairs *are* the macros: no other source in the tree carries 0.490/2800 or 0.500/2800 for C1-C1, so a
    # value match is the evidence that the published named defaults were the source.
    values = sorted(bonds.values())
    assert ('0.49', '2800') in values, values
    assert ('0.5', '2800') in values, values
    assert len(bonds) == 3, f'a three-bead tail behind a head bead has three bonds: {bonds}'
