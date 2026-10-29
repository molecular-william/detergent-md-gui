"""The carbohydrate target registry: the values it carries, and the ones it deliberately does not.

Entering numbers is the moment the registry stops being citation metadata, so the gate is that every entered target
goes through the analysis's own validator — and that the two datasets which have no source still say so rather than
carrying a plausible-looking number.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from detergent_validation.analysis.validation import targets as target_analysis

REGISTRY = Path(__file__).resolve().parents[3] / 'resources/validation/carbohydrates/targets-v1.json'
LOG_P_FACTOR = 5.708  # 2.303 RT at 25 C, in kJ/mol; the table's Exp column equals this times its logP column


def registry() -> dict:
    return json.loads(REGISTRY.read_text())


def datasets() -> dict:
    return {item['molecule_id']: item for item in registry()['datasets']}


def test_every_entered_target_passes_the_analysiss_own_validator(tmp_path):
    for dataset in registry()['datasets']:
        if not dataset['targets']:
            continue
        run = tmp_path / dataset['id']
        run.mkdir()
        report = target_analysis.build(run, {'targets': dataset['targets']})
        assert len(report['targets']) == len(dataset['targets'])
        assert report['scientifically_validated'] is False, 'a target is evidence, not a validation'


def test_the_entered_values_are_the_tables_own_and_agree_with_its_logP_column():
    glucose = datasets()['Glucose']['targets'][0]
    trehalose = datasets()['Trehalose']['targets'][0]

    assert (glucose['value'], glucose['uncertainty']) == (-17.81, 0.57)
    assert (trehalose['value'], trehalose['uncertainty']) == (-21.52, 0.29)
    for target, log_p in ((glucose, -3.12), (trehalose, -3.77)):
        assert target['value'] == pytest.approx(LOG_P_FACTOR * log_p, abs=0.01), \
            'the Exp column is the logP column at 5.708 kJ/mol per log unit; a mismatch means one was mis-typed'
    assert all(target['unit'] == 'kJ/mol' for target in (glucose, trehalose))
    assert 'Table S2' in glucose['citation'] and 'Table S2' in trehalose['citation']


def test_a_molecule_the_source_does_not_cover_says_what_is_missing_instead_of_carrying_a_number():
    # By dataset and not by molecule: a molecule can be covered for one quantity and missing another. Maltose now
    # carries measured *osmotic* pressures from a separate source, and is still missing the water-octanol partition
    # free energy that this source measures.
    for molecule, dataset_id in (('Sucrose', 'sucrose-martini3-paper-v1'),
                                 ('Maltose', 'maltose-pilot-v1')):
        dataset = next(item for item in registry()['datasets'] if item['id'] == dataset_id)

        assert dataset['molecule_id'] == molecule
        assert dataset['availability'] == 'metadata_only' and dataset['targets'] == []
        assert dataset['missing'].strip(), 'an unfilled dataset has to say what would fill it'


def test_the_uncertainty_of_every_target_comes_from_the_source():
    """The registry's own rule: a number without an uncertainty it can name is not evidence."""
    for dataset in registry()['datasets']:
        for target in dataset['targets']:
            assert target['uncertainty'] > 0
            assert 'SD' in target['conditions'], f"{target['id']}: name where the uncertainty came from"


def test_the_registry_states_the_convention_this_file_relies_on():
    note = registry()['source']['note']

    assert '5.708' in note and 'logP' in note
    assert 'metadata-only' in note or 'metadata_only' in note
