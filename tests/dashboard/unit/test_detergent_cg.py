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

    assert centres['A'] == [0.05, 0.0, 0.0]
    assert centres['B'] == [0.0, 0.3, 0.0] and centres['C'] == [0.0, 0.0, 0.3]


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
