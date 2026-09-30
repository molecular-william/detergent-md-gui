"""A mapping's Martini generation decides which references may parameterise it.

Found while measuring the DDM draft: its tail bonds were parameterised from `martini-ddm.itp` and the MAD Database,
which are Martini 2 files, while its head came from the Martini 3 sugar references — a hybrid the pipeline assembled
without saying so. Bead-type letters cannot tell the generations apart (Martini 2 and 3 both use `C1`), so the
version is read from a sidecar or a known family, and a mapping that states its version is parameterised only from
that version.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard.models.bonded import generation

C1_BOND_M2 = '; m2\n[ moleculetype ]\nDET 1\n\n[ atoms ]\n1 C1 1 DET A 1 0 72\n2 C1 1 DET B 2 0 72\n\n' \
             '[ bonds ]\n1 2 1 0.50 1000\n'
C1_BOND_M3 = C1_BOND_M2.replace('; m2', '; m3').replace('0.50 1000', '0.47 1250')


def reference_tree(tmp_path: Path) -> Path:
    """Two references for one bead-type pair: one says it is Martini 2, the other Martini 3."""
    for folder, text, version in (('m2', C1_BOND_M2, 2), ('m3', C1_BOND_M3, 3)):
        directory = tmp_path / 'references' / folder
        directory.mkdir(parents=True)
        (directory / f'{folder}.itp').write_text(text)
        (directory / f'{folder}.itp.source.json').write_text(json.dumps({'martini_version': version}))
    return tmp_path


def mapping(beads=None, **extra) -> dict:
    return {'name': 'test', 'beads': beads or [{'name': 'A', 'type': 'C1', 'atoms': [1]},
                                               {'name': 'B', 'type': 'C1', 'atoms': [2]}],
            'connections': [['A', 'B']], **extra}


def structure() -> dict:
    return {'atoms': [{'id': 1, 'xyz': [0.0, 0.0, 0.0]}, {'id': 2, 'xyz': [5.0, 0.0, 0.0]}],
            'bonds': [[1, 2]]}


def test_the_known_families_are_tagged_with_their_generation():
    assert generation._reference_version('references/martini-ddm.itp') == 2
    assert generation._reference_version('references/MAD Database/SDS/SDS.itp') == 2
    assert generation._reference_version('references/martini_v3.0.0_sugars_v2.itp') == 3


def test_a_sidecar_states_the_generation_where_the_file_does_not(tmp_path):
    directory = tmp_path / 'references'
    directory.mkdir()
    (directory / 'x.itp').write_text(C1_BOND_M2)
    (directory / 'x.itp.source.json').write_text(json.dumps({'martini_version': 3}))

    assert generation._reference_version('references/x.itp', directory / 'x.itp') == 3


def test_an_unstated_generation_is_usable_rather_than_excluded():
    """An unknown is not evidence of a mismatch; excluding it would silently drop parameters."""
    assert generation._reference_version('references/some-other-model.itp') is None


def test_a_martini_3_mapping_is_parameterised_only_from_martini_3_references(tmp_path):
    root = reference_tree(tmp_path)

    three = generation.generate(mapping(martini_version=3), structure(), root)
    two = generation.generate(mapping(martini_version=2), structure(), root)

    assert three['interactions'][0]['parameters'][1] == '1250'
    assert two['interactions'][0]['parameters'][1] == '1000'
    sources = {reference['path'] for reference in three['interactions'][0]['provenance']['references']}
    assert sources == {'references/m3/m3.itp'}, 'the Martini 3 build must not be parameterised from the M2 file'


def test_a_mapping_that_states_no_generation_keeps_the_old_behaviour(tmp_path):
    root = reference_tree(tmp_path)

    answer = generation.generate(mapping(), structure(), root)

    assert answer['interactions'][0]['parameters'][1] in {'1000', '1250'}, 'a version-less mapping still gets terms'


def test_a_term_whose_only_references_are_the_wrong_generation_falls_back_rather_than_mixing(tmp_path):
    """The measured DDM case: the C1|C1 bond exists only in Martini 2 files, so a Martini 3 mapping gets no bond
    parameter from them -- it gets the geometry fallback, and the provenance says fallback."""
    directory = tmp_path / 'references' / 'm2'
    directory.mkdir(parents=True)
    (directory / 'm2.itp').write_text(C1_BOND_M2)
    (directory / 'm2.itp.source.json').write_text(json.dumps({'martini_version': 2}))

    answer = generation.generate(mapping(martini_version=3), structure(), tmp_path)
    provenance = answer['interactions'][0]['provenance']

    assert provenance['fallback'] is True and provenance['matched_key'] == 'C1|C1'
    assert answer['interactions'][0]['parameters'][1] == '5000', 'the placeholder, not a Martini 2 constant'
    assert any('No exact reference bond' in line for line in answer['diagnostics'])


def test_the_repositorys_own_ddm_tail_carries_a_martini_3_reference(tmp_path):
    """The tail's bond comes from a reference, and demonstrably not from the Martini 2 detergent file.

    This test used to pin the opposite: with only the sugar and MAD references in the tree, `C1|C1` matched nothing
    and the tail fell back to placeholder constants. Adding the published Martini 3 lipid set gives that pair a
    source, so what is pinned now is that the source is used -- and that the Martini 2 detergent's own values
    (length 0.222-0.246 nm, force constant 30000) are still not what a Martini 3 mapping gets.
    """
    candidate = tmp_path / 'candidate.json'
    candidate.write_text(json.dumps({
        'schema_version': 3, 'molecule_id': 'DDM', 'name': 'two tail beads', 'martini_version': 3,
        'beads': [{'name': 'A', 'type': 'C1', 'atoms': [1, 2, 3, 4]},
                  {'name': 'B', 'type': 'C1', 'atoms': [5, 6, 7, 8]}],
        'connections': [['A', 'B']]}))
    molecule_root = Path(__file__).resolve().parents[3] / 'molecules'
    from dashboard.models.molecules import detergent_cg

    draft = detergent_cg.derive(candidate, molecule_root, molecule_root.parent)
    bond = draft['topology'].split('[ bonds ]', 1)[1].strip().splitlines()[0].split()

    assert draft['reference_terms'] >= 1, 'the published Martini 3 lipid set gives this pair a source'
    assert draft['fallback_terms'] < draft['terms'], 'so the tail is no longer all fallback'
    assert float(bond[-1]) != 5000.0, 'not the placeholder force constant'
    assert 0.221 < float(bond[-2]) < 0.60, f'the length is a Martini 3 one, not {bond[-2]}'
    assert float(bond[-1]) != 30000.0, 'and not the Martini 2 detergent force constant'


def test_the_published_lipid_set_states_its_generation():
    """A Martini 2 mapping must not pick up Martini 3 lipid parameters, so the family states which it is."""
    from dashboard.models.bonded import generation

    root = Path(__file__).resolve().parents[3]
    relative = 'references/M3-Lipid-Parameters/ITPs/martini_v3.0.0.itp'

    assert generation._reference_version(relative, root / relative) == 3
    assert generation._reference_version('references/martini-ddm.itp', root / 'references/martini-ddm.itp') == 2
