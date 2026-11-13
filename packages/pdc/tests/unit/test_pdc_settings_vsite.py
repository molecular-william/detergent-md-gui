"""The protein virtual-site choice is a run setting: advertised, validated, and recorded.

`gmx pdb2gmx -vsite` is the one GROMACS choice the back-map makes about the protein, and it reaches every pdb2gmx
CG2AT2 runs through the stage's wrapper. The setting has to survive the route's advertised-key filter
(`runs.py:queue`), the settings normalizer, `validate_payload` and `prepare`'s record, or the panel would show a
control that the run silently ignores.
"""
import json

import pytest
from detergent_pdc.execution.adapters import pdc

from tests.harness.pdc_fixtures import inputs_dir, prepared_run

VALUES = ('none', 'hydrogens', 'aromatics')


def test_the_choice_is_advertised_with_its_three_values():
    assert pdc.DEFAULTS['protein_vsite'] == 'none', 'an existing run or clone must back-map as it always did'
    label, options = pdc.CHOICE_SPECS['protein_vsite']
    assert label == 'Protein virtual sites'
    assert options == VALUES
    assert 'protein_vsite' in dict(pdc.PROTOCOL.choice_specs()), \
        'runs.py:queue drops an unadvertised setting without a word'


@pytest.mark.parametrize('value', VALUES)
def test_the_settings_round_trip_accepts_each_value(value):
    numbers = pdc.normalize_settings({'protein_vsite': value})
    assert numbers['protein_vsite'] == value
    assert pdc.validate_payload({**numbers, 'seed': 20260930})['protein_vsite'] == value


def test_the_default_is_none_for_a_payload_that_says_nothing():
    assert pdc.validate_payload({'seed': 1})['protein_vsite'] == 'none'
    assert pdc.settings_from({'seed': 1})['protein_vsite'] == 'none'


@pytest.mark.parametrize('value', ('all', 'aromatic', 'Hydrogens', '', None))
def test_a_value_the_wrapper_cannot_pass_is_refused(value):
    with pytest.raises(ValueError, match='protein virtual-site choice'):
        pdc.validate_payload({'seed': 1, 'protein_vsite': value})
    with pytest.raises(ValueError, match='protein_vsite must be one of'):
        pdc.normalize_settings({'protein_vsite': value})


def test_the_queue_route_keeps_the_choice_for_the_run(tmp_path):
    """`runs.py:queue` keeps only advertised keys, so the advertised spec is what makes this test possible."""
    from dashboard.app import create_app
    from dashboard.paths import Paths

    app = create_app(Paths(workspace=tmp_path / 'pdc'), {'TESTING': True, 'DISABLE_COORDINATOR': True})
    client = app.test_client()

    response = client.post('/', json={'molecule_id': 'DDM', 'run_type': 'pdc', 'method': 'bartender',
                                      'template': 'molecules/DDM/micelle_template.json',
                                      'protein_vsite': 'hydrogens'})

    assert response.status_code == 201, response.get_data(as_text=True)
    assert response.json['settings']['protein_vsite'] == 'hydrogens'


def test_prepare_records_the_choice_in_the_settings_and_the_manifest(tmp_path):
    run = prepared_run(tmp_path, settings={'protein_vsite': 'aromatics'})
    settings = json.loads((inputs_dir(run) / pdc.SETTINGS_NAME).read_text())
    manifest = json.loads((run / 'manifest.json').read_text())

    assert settings['protein_vsite'] == 'aromatics'
    assert manifest['settings']['protein_vsite'] == 'aromatics'


def test_a_prepared_run_that_names_nothing_records_the_default(tmp_path):
    run = prepared_run(tmp_path)
    settings = json.loads((inputs_dir(run) / pdc.SETTINGS_NAME).read_text())

    assert settings['protein_vsite'] == 'none'
