"""The detergent draft: the machinery that turns a saved mapping into a topology and placeable beads.

The pieces are tested where they can be seen: the bead centres and the virtual sites are pure arithmetic on a
structure the test writes, and the derivation runs against the repository's own `molecules/DDM` (a tracked asset,
like a template) with a small mapping the test builds itself — so nothing here depends on the developer's saved
candidates or on the live workspace.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from dashboard.models.molecules import detergent_cg

MOLECULE_ROOT = Path(__file__).resolve().parents[3] / 'molecules'
STRUCTURE = {'atoms': [{'id': 1, 'xyz': [0.0, 0.0, 0.0]}, {'id': 2, 'xyz': [1.0, 0.0, 0.0]},
                       {'id': 3, 'xyz': [0.0, 3.0, 0.0]}, {'id': 4, 'xyz': [0.0, 0.0, 3.0]}],
             'bonds': [[1, 2], [2, 3], [3, 4]]}


def write_candidate(path: Path, **overrides) -> Path:
    data = {'schema_version': 3, 'molecule_id': 'DDM', 'name': 'test mapping',
            'beads': [{'name': 'A', 'type': 'C1', 'atoms': [1, 2]},
                      {'name': 'B', 'type': 'C1', 'atoms': [3, 4]},
                      {'name': 'VS', 'type': 'TC4', 'atoms': [],
                       'virtual_site': {'function': 1, 'parents': ['A', 'B']}}],
            'connections': [['A', 'B']]}
    data.update(overrides)
    path.write_text(json.dumps(data))
    return path


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps({**{'beads': [{'name': 'A', 'atoms': [1]}]}, **data}))
    return path


def test_a_mapping_without_beads_or_a_molecule_is_refused_with_the_reason(tmp_path):
    with pytest.raises(ValueError, match='carries no beads'):
        detergent_cg.candidate(_write(tmp_path / 'empty.json', {'beads': []}))
    with pytest.raises(ValueError, match='names no molecule'):
        detergent_cg.candidate(_write(tmp_path / 'anon.json', {'molecule_id': ''}))


def test_a_beads_position_is_the_mean_of_its_atoms_in_nanometres():
    centres = detergent_cg.bead_centres({'beads': [{'name': 'A', 'atoms': [1, 2]},
                                                   {'name': 'B', 'atoms': [3]},
                                                   {'name': 'C', 'atoms': [4]}]}, STRUCTURE)

    # Approximate because this is a unit conversion: the legacy rule is a tenth, and the value that arrives is a
    # float's worth of it. What is pinned is the nanometres, not the last bit of the arithmetic.
    assert centres['A'] == pytest.approx([0.05, 0.0, 0.0])
    assert centres['B'] == pytest.approx([0.0, 0.3, 0.0])
    assert centres['C'] == pytest.approx([0.0, 0.0, 0.3])


def test_a_structure_from_the_context_is_already_in_nanometres_and_is_not_divided_again():
    """The same structure, told apart by the two fields a context-built one carries.

    Measured: a placed detergent's beads sat 0.021-0.037 nm apart while the topology's ring constraints for those
    pairs asked 0.32-0.43 nm -- an ~11x stretch at t=0 -- because the centres were divided by ten when the context had
    already converted them. The sugar writer and the mapping export each had this defect before; this is the same one.
    """
    context = {**STRUCTURE, 'molecule_id': 'DDM', 'snapshot': {'snapshot_sha256': 'a' * 64}}

    centres = detergent_cg.bead_centres({'beads': [{'name': 'A', 'atoms': [1, 2]}]}, context)

    assert centres['A'] == [0.5, 0.0, 0.0], 'the context holds nanometres; a tenth of a nanometre apart is not a molecule'


def test_a_ring_virtual_site_is_the_centre_of_its_parents_and_nothing_else_is():
    centres = detergent_cg.bead_centres({'beads': [
        {'name': 'A', 'atoms': [1]}, {'name': 'B', 'atoms': [2]},
        {'name': 'VS', 'atoms': [], 'virtual_site': {'function': 1, 'parents': ['A', 'B']}}]}, STRUCTURE)

    assert centres['VS'] == [0.05, 0.0, 0.0]


@pytest.mark.parametrize('bead, message', [
    ({'name': 'A', 'atoms': [99]}, 'atoms the structure does not have'),
    ({'name': 'A', 'atoms': []}, 'function-1 virtual site'),
    ({'name': 'A', 'atoms': [], 'virtual_site': {'function': 2, 'parents': ['A', 'B']}}, 'function-1'),
    ({'name': 'A', 'atoms': [], 'virtual_site': {'function': 1, 'parents': ['A']}}, 'function-1'),
])
def test_a_bead_that_cannot_be_placed_says_why(bead, message):
    with pytest.raises(ValueError, match=message):
        detergent_cg.bead_centres({'beads': [bead]}, STRUCTURE)


def test_a_virtual_site_whose_parent_is_not_yet_placed_is_refused():
    with pytest.raises(ValueError, match='not beads placed before it'):
        detergent_cg.bead_centres({'beads': [{'name': 'VS', 'atoms': [],
                                              'virtual_site': {'function': 1, 'parents': ['A', 'B']}}]}, STRUCTURE)


def test_the_generated_topology_is_renamed_to_the_molecules_own_name():
    text = ('; Automatic bonded draft\n[ moleculetype ]\nMOL 1\n\n[ atoms ]\n1 C1 1 MOL A 1 0 72\n'
            '\n[ bonds ]\n1 2 1 0.3 5000\n')

    renamed = detergent_cg.named_topology(text, 'DDM')

    assert '[ moleculetype ]\nDDM 1' in renamed
    assert '1 C1 1 DDM A 1 0 72' in renamed, 'the atom rows carry the residue a reader sees beside the coordinates'
    assert 'MOL' not in renamed


def test_a_topology_without_a_moleculetype_is_refused():
    with pytest.raises(ValueError, match='no \\[ moleculetype \\]'):
        detergent_cg.named_topology('; nothing here\n', 'DDM')


def test_the_derivation_against_the_repositorys_own_ddm(tmp_path):
    """The real molecule, a mapping the test builds: two tail beads and the linkage between them."""
    candidate = tmp_path / 'candidate.json'
    candidate.write_text(json.dumps({
        'schema_version': 3, 'molecule_id': 'DDM', 'name': 'two beads over the real DDM',
        'beads': [{'name': 'A', 'type': 'C1', 'atoms': [1, 2, 3, 4]},
                  {'name': 'B', 'type': 'C1', 'atoms': [5, 6, 7, 8]}],
        'connections': [['A', 'B']]}))

    draft = detergent_cg.derive(candidate, MOLECULE_ROOT, MOLECULE_ROOT.parent)

    assert draft['residue'] == 'DDM' and draft['molecule_id'] == 'DDM'
    assert [bead['name'] for bead in draft['beads']] == ['A', 'B']
    assert all(bead['residue'] == 'DDM' for bead in draft['beads'])
    assert draft['terms'] == draft['reference_terms'] + draft['fallback_terms'] > 0
    assert '[ moleculetype ]\nDDM 1' in draft['topology']
    assert '[ atoms ]' in draft['topology'] and '[ bonds ]' in draft['topology']
    assert draft['topology'].count('\n') >= 8, 'the topology carries atoms and the terms that were generated'


# --- adopting a fitted parameterization -----------------------------------------------------------

#: A fit's own topology, with its own header and its own terms: the export names `B01`.. are what a fit writes, and
#: the mapping names these beads `S1A`.. The numbers are arbitrary on purpose -- a test that borrowed a fit's numbers
#: would pass while the wiring did nothing.
FITTED = """; This file was generated using the following command:
; ff_inter -f ../2_mapping/mapped.xtc -s ../2_mapping/mapped.gro -i DDM_initial.itp

[ moleculetype ]
DDM 1

[ atoms ]
 1 SP1r 1 DDM B01  1 0.0 54.0
 2 SP1r 1 DDM B02  2 0.0 54.0
 3 TC4  1 DDM B03  3 0.0  0.0
 4 SN6  1 DDM B04  4 0.0 54.0
 5 C1   1 DDM B05  5 0.0 72.0

[ bonds ]
 1  5 1 0.431 2690.007 ; B01_B05
 2  4 1 0.334 6309.064 ; B02_B04

[ constraints ]
 1  2 1 0.259821

[ angles ]
 2  1  5 1 137.802 107.554 ; B02_B01_B05

[ exclusions ]
 3  1  2  4

[ virtual_sitesn ]
 3 1  1  2  4
"""


def fitted_draft() -> dict:
    """The mapping's side of the same molecule: five beads, in this order, with the mapping's own names."""
    return {'residue': 'DDM', 'molecule_id': 'DDM',
            'beads': [{'name': 'S1A', 'type': 'SP1r'}, {'name': 'S1B', 'type': 'SP1r'},
                      {'name': 'S1VS', 'type': 'TC4'}, {'name': 'S2A', 'type': 'SN6'},
                      {'name': 'TAIL1', 'type': 'C1'}]}


def revision(topology: str = FITTED, **overrides) -> dict:
    return {'revision': 2, 'engine': 'fast-forward', 'mapping_content_hash': 'f' * 64,
            'terms': {'bonds': 2, 'constraints': 1, 'angles': 1, 'virtual_sitesn': 1},
            'topology': topology, **overrides}


def fields(line: str) -> list[str]:
    return line.split(';', 1)[0].split()


def atom_rows(text: str) -> list[list[str]]:
    """The `[ atoms ]` rows: the lines a reader of a topology means when it says "the atoms"."""
    section, rows = '', []
    for line in text.splitlines():
        content = line.split(';', 1)[0].strip()
        if content.startswith('[') and content.endswith(']'):
            section = content[1:-1].strip().lower()
        elif content and section == 'atoms':
            rows.append(content.split())
    return rows


def test_adopting_a_fit_renames_the_atoms_and_changes_nothing_else():
    """The one transformation the build needs: `grompp` matches topology to coordinates by atom name."""
    adopted = detergent_cg.adopt(fitted_draft(), revision())

    assert adopted['topology'].startswith('; This file was generated using the following command:'), \
        'the fit\'s header is not the run\'s to rewrite'
    assert adopted['molecule'] == 'DDM' and '[ moleculetype ]\nDDM 1' in adopted['topology']
    assert adopted['bead_names'] == ['S1A', 'S1B', 'S1VS', 'S2A', 'TAIL1']
    assert adopted['terms'] == {'bonds': 2, 'constraints': 1, 'angles': 1, 'virtual_sitesn': 1}
    rows = atom_rows(adopted['topology'])
    assert [row[1] for row in rows] == ['SP1r', 'SP1r', 'TC4', 'SN6', 'C1'], 'the types are the fit\'s'
    assert [row[4] for row in rows] == ['S1A', 'S1B', 'S1VS', 'S2A', 'TAIL1'], 'and the names are the mapping\'s'


def test_adopting_a_fit_touches_only_the_name_column_of_the_atom_rows():
    before, after = FITTED.splitlines(), detergent_cg.adopt(fitted_draft(), revision())['topology'].splitlines()

    assert len(before) == len(after), 'a line was added or lost'
    changed = [index for index, (old, new) in enumerate(zip(before, after)) if old != new]
    assert len(changed) == 5, f'only the five atom rows may differ, and these did: {changed}'
    for index in changed:
        old, new = fields(before[index]), fields(after[index])
        assert old[:4] == new[:4] and old[5:] == new[5:], f'line {index} changed more than its name column'
        assert old[4] != new[4]
        if ';' in before[index]:
            assert before[index].split(';', 1)[1] == after[index].split(';', 1)[1], 'a comment is not a name'


def test_adopting_a_fit_keeps_the_section_order():
    def sections(text: str) -> list[str]:
        return [line.strip() for line in text.splitlines() if line.strip().startswith('[')]

    assert sections(detergent_cg.adopt(fitted_draft(), revision())['topology']) == sections(FITTED)


def test_a_fit_of_a_different_atom_count_is_refused_with_both_counts():
    topology = FITTED.replace(' 5 C1   1 DDM B05  5 0.0 72.0\n', '')
    with pytest.raises(ValueError, match='declares 4 atoms and the mapping has 5'):
        detergent_cg.adopt(fitted_draft(), revision(topology))


def test_a_fit_of_a_different_bead_type_is_refused_naming_the_atom():
    draft = fitted_draft()
    draft['beads'][3]['type'] = 'SP4r'
    with pytest.raises(ValueError, match='atom 4 is SN6 in the parameters and SP4r in the mapping'):
        detergent_cg.adopt(draft, revision())


def test_a_fit_that_names_another_molecule_is_refused():
    """`grompp` reconciles the topology's molecule with the coordinates' residue, so this is a build that fails."""
    with pytest.raises(ValueError, match="names its molecule DDMX and the mapping's residue is DDM"):
        detergent_cg.adopt(fitted_draft(), revision(FITTED.replace('DDM 1', 'DDMX 1')))


def test_a_revision_with_no_topology_is_refused_rather_than_adopted():
    with pytest.raises(ValueError, match='no topology to adopt'):
        detergent_cg.adopt(fitted_draft(), revision(''))
