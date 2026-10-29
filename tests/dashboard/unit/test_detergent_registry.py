"""Which molecules are detergents: the registry at `detergents.json` decides, not a list held here.

`molecules/` holds DDM beside Maltose, Sucrose and Trehalose, and the protein-detergent pipeline builds its belt
out of a detergent's own beads -- so a panel that offered every molecule presented a sugar as a detergent and a run
that cannot be built. The registry names its entries' abbreviations inside the parentheses at the end of the name,
and a molecule directory is named after one; an entry whose parentheses hold the whole chemical name instead ("CHAPS
(3-[(3-Cholamidopropyl)dimethylammonio]-1-propanesulfonate)") or a size range ("Triton X-100 (~7-8 EO)") has no
abbreviation and cannot be picked.

Every fixture here is built in `tmp_path`: the registry file is data, and a test that read the repository's copy
would report on the file rather than on the rule.
"""
import json

import pytest
from dashboard.models.molecules import detergent_registry

DDM = 'n-Dodecyl-β-D-maltoside (DDM)'


def write_registry(root, entries):
    (root / 'detergents.json').write_text(json.dumps(entries, ensure_ascii=False), encoding='utf-8')
    return root


def test_an_entry_abbreviated_in_its_parentheses_is_pickable_by_that_abbreviation(tmp_path):
    root = write_registry(tmp_path, {DDM: 'C', '3-(Dodecyldimethylammonio)propanesulfonate (SB3-12)': 'C'})
    assert detergent_registry.codes(root) == {'DDM': DDM,
                                              'SB3-12': '3-(Dodecyldimethylammonio)propanesulfonate (SB3-12)'}
    assert detergent_registry.is_detergent('DDM', root) is True
    assert detergent_registry.require('DDM', root) == DDM


def test_a_molecule_the_registry_does_not_name_is_refused_by_name(tmp_path):
    """The refusal has to name the molecule: "not found" would not say which list was consulted."""
    root = write_registry(tmp_path, {DDM: 'C', 'Sucrose Monodecanoate / Monolaurate': 'C'})
    assert detergent_registry.is_detergent('Maltose', root) is False
    assert detergent_registry.is_detergent('Sucrose', root) is False, \
        'a name that only appears inside a longer entry is not an abbreviation'
    with pytest.raises(ValueError) as error:
        detergent_registry.require('Maltose', root)
    assert 'Maltose' in str(error.value)
    assert detergent_registry.REGISTRY_FILE in str(error.value)


def test_a_parenthesis_holding_something_other_than_an_abbreviation_is_not_a_code(tmp_path):
    """Two shapes in the registry put prose where every other entry puts its short name."""
    root = write_registry(tmp_path, {
        '4-Cyclohexyl-1-butyl-phosphocholine (Fos-Choline-Cyclohexyl-4)': 'C',
        'Triton X-100 (~7-8 EO)': 'C',
        'CHAPS (3-[(3-Cholamidopropyl)dimethylammonio]-1-propanesulfonate)': 'C',
        'n-Dodecyl-β-D-maltoside (DDM - H4 Variant)': 'C',
        'Anapoe-C12E8': 'C',
    })
    assert detergent_registry.codes(root) == {'Fos-Choline-Cyclohexyl-4':
                                              '4-Cyclohexyl-1-butyl-phosphocholine (Fos-Choline-Cyclohexyl-4)',
                                              'Anapoe-C12E8': 'Anapoe-C12E8'}


def test_one_entry_may_be_filed_under_several_abbreviations(tmp_path):
    root = write_registry(tmp_path, {'Lauryldimethylamine N-oxide (LDAO / C12AO)': 'C'})
    assert sorted(detergent_registry.codes(root)) == ['C12AO', 'LDAO']


def test_the_selection_keeps_the_records_it_was_given_and_adds_the_registry_name(tmp_path):
    """The panel's list is the molecule catalogue filtered, so the records it holds stay the catalogue's own."""
    root = write_registry(tmp_path, {DDM: 'C'})
    records = [{'id': 'DDM', 'name': 'DDM', 'path': 'molecules/DDM', 'valid': True},
               {'id': 'Maltose', 'name': 'Maltose', 'path': 'molecules/Maltose', 'valid': True}]
    assert detergent_registry.select(records, root) == [
        {'id': 'DDM', 'name': 'DDM', 'path': 'molecules/DDM', 'valid': True, 'registry_name': DDM}]


def test_a_registry_that_is_not_a_name_to_smiles_map_is_refused(tmp_path):
    (tmp_path / 'detergents.json').write_text('["DDM"]', encoding='utf-8')
    with pytest.raises(ValueError):
        detergent_registry.entries(tmp_path)
