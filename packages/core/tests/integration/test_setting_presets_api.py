"""The preset routes, and the queue payload fields the New run form adds beside them.

The store is per workspace, so these tests read it the way the panel does -- through the JSON API -- and then
build a second application object against the same workspace to prove the file, not the process, is the store.
"""
import re

import pytest
from dashboard import paths

from tests.harness import factory


def saved(client, **overrides):
    payload = {'name': 'Short AA', 'run_type': 'aa_only', 'settings': {'aa_production_ps': 500}}
    payload.update(overrides)
    return client.post('/api/setting-presets', json=payload)


def test_a_preset_is_saved_listed_marked_and_deleted(dashboard):
    client = dashboard.client
    assert client.get('/api/setting-presets?run_type=aa_only').json == {'presets': [], 'default': None}

    response = saved(client)
    assert response.status_code == 201, response.data
    preset = response.get_json()['preset']
    assert preset['run_type'] == 'aa_only' and preset['settings']['aa_production_ps'] == 500

    listed = client.get('/api/setting-presets?run_type=aa_only').json
    assert [item['id'] for item in listed['presets']] == [preset['id']]
    assert listed['presets'][0]['is_default'] is False and listed['default'] is None
    # The options one run type owns are not offered to another.
    assert client.get('/api/setting-presets?run_type=cg').json == {'presets': [], 'default': None}

    patched = client.patch(f"/api/setting-presets/{preset['id']}", json={'is_default': True})
    assert patched.status_code == 200 and patched.get_json()['defaults'] == {'aa_only': preset['id']}
    listed = client.get('/api/setting-presets?run_type=aa_only').json
    assert listed['default'] == preset['id'] and listed['presets'][0]['is_default'] is True

    deleted = client.delete(f"/api/setting-presets/{preset['id']}")
    assert deleted.status_code == 200 and deleted.get_json() == {'deleted': preset['id']}
    assert client.get('/api/setting-presets?run_type=aa_only').json == {'presets': [], 'default': None}


def test_a_duplicate_name_in_one_run_type_is_a_409_and_an_unadvertised_setting_a_400(dashboard):
    client = dashboard.client
    assert saved(client).status_code == 201
    duplicate = saved(client, name='short aa')
    assert duplicate.status_code == 409 and 'Short AA' in duplicate.get_json()['error']

    refused = saved(client, name='Bad', settings={'cg_production_ps': 10})
    assert refused.status_code == 400 and 'cg_production_ps' in refused.get_json()['error']
    assert len(client.get('/api/setting-presets?run_type=aa_only').json['presets']) == 1


def test_an_unknown_run_type_preset_or_id_is_refused(dashboard):
    client = dashboard.client
    assert client.get('/api/setting-presets?run_type=no-such-type').status_code == 400
    assert client.patch('/api/setting-presets/nosuchpreset', json={'is_default': True}).status_code == 404
    assert client.delete('/api/setting-presets/nosuchpreset').status_code == 404


def test_the_store_is_the_workspace_file_not_the_process(tmp_path):
    """A second application object over the same workspace offers the preset the first one saved."""
    first = factory.build(tmp_path)
    with paths.use(first.paths):
        assert saved(first.client).status_code == 201
        preset = first.client.get('/api/setting-presets?run_type=aa_only').json['presets'][0]
        first.client.patch(f"/api/setting-presets/{preset['id']}", json={'is_default': True})

    second = factory.build(tmp_path)
    with paths.use(second.paths):
        listed = second.client.get('/api/setting-presets?run_type=aa_only').json
    assert listed['presets'][0]['name'] == 'Short AA'
    assert listed['default'] == preset['id']
    assert (first.paths.workspace / 'setting-presets.json').is_file()


def test_an_unnamed_run_gets_the_panel_format_and_records_its_preset(dashboard, monkeypatch):
    """The two server-side halves of the form: the generated label, and the preset named as provenance.

    The form posts a suggestion, so an empty label here is the API caller's case -- and the preset object is
    metadata, never an MDP setting. The worker is stubbed: this test is about the record, not a simulation.
    """
    dashboard.coordinator.database().replace([])
    monkeypatch.setattr(dashboard.coordinator, 'run_job', lambda *args: None)
    preset = saved(dashboard.client).get_json()['preset']

    response = dashboard.client.post('/', json={
        'run_type': 'aa_only', 'molecule_id': 'DDM', 'label': '',
        'settings': {'aa_production_ps': 500},
        'settings_preset': {'id': preset['id'], 'name': preset['name']}})

    assert response.status_code == 201, response.data
    job = dashboard.coordinator.database().all()[0]
    # [molecule]-[AA|CG]-[length]ns-[YYYYMMDD]; AA length is NVT + NPT + production at the run's own values.
    assert re.fullmatch(r'DDM-AA-11\.1ns-\d{8}', job['label']), job['label']
    assert job['settings_preset'] == {'id': preset['id'], 'name': preset['name']}
    assert 'settings_preset' not in job['settings']
    dashboard.coordinator.WORKERS.clear()


@pytest.mark.parametrize('run_type, settings, expected', [
    ('aa_only', {'aa_nvt_ps': 100, 'aa_npt_ps': 1000, 'aa_production_ps': 10000}, 'DDM-AA-11.1ns'),
    ('cg', {'cg_equil_ps': 5000, 'cg_production_ps': 10000}, 'DDM-CG-15ns'),
    ('cg', {'cg_equil_ps': 10, 'cg_production_ps': 10000}, 'DDM-CG-10ns'),
    ('cg', {}, 'DDM-CG'),
])
def test_the_generated_label_names_the_type_and_the_total_length(run_type, settings, expected):
    """Equilibration is part of the length, and the CG tag is every type but an AA-only run. A composition run
    configures no duration, so it gets no length segment rather than a false `0ns`."""
    from dashboard.execution.coordination.coordinator import generated_label

    label = generated_label('DDM', run_type, settings, 'standard')

    assert label.startswith(expected + '-')
    assert re.fullmatch(r'\d{8}', label.rsplit('-', 1)[1])
    assert len(label) <= 160


def test_a_very_long_molecule_name_trims_the_name_not_the_date():
    """The cap is on the label, and the tail is what names the run: a cut date would stop it being a label."""
    from dashboard.execution.coordination.coordinator import generated_label

    label = generated_label('X' * 300, 'aa_only', {'aa_production_ps': 10000}, 'standard')

    assert len(label) == 160
    assert re.fullmatch(r'X+-AA-11\.1ns-\d{8}', label)
