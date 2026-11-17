"""A `pdc` stage-setting preset round-trips through the real routes and its own adapter vocabulary.

The store is shared with the other run types and the settings are normalized by the adapter that owns them, so the
one thing this adds is the run type: a preset saved here is listed here, is a different run type's absence, can be
made the default and is deleted by id. Everything runs against the `dashboard` fixture's temporary workspace, never
the developer's store; `setting_presets` writes its file under `paths.workspace`.
"""
from __future__ import annotations

SETTINGS = {'pdc_nvt_ps': 250, 'pdc_npt_ps': 900, 'salt_molar': 0.15,
            'pdc_posres_nvt': 'no', 'pdc_npt_pcoupl': 'c-rescale'}


def test_a_pdc_preset_is_saved_listed_marked_and_deleted(dashboard):
    client = dashboard.client
    assert client.get('/api/setting-presets?run_type=pdc').get_json() == {'presets': [], 'default': None}

    response = client.post('/api/setting-presets', json={
        'name': 'PDC standard', 'run_type': 'pdc', 'settings': SETTINGS})
    assert response.status_code == 201, response.get_json()
    preset = response.get_json()['preset']
    assert preset['run_type'] == 'pdc' and preset['name'] == 'PDC standard'
    # The stored settings are the adapter's normalized numbers, in its builder spelling: the durations live under
    # `nvt_ps`/`npt_ps`. The panel translates those back on load, and this pins the shape it receives.
    assert float(preset['settings']['nvt_ps']) == 250
    assert float(preset['settings']['npt_ps']) == 900
    assert 'pdc_nvt_ps' not in preset['settings']
    assert float(preset['settings']['salt_molar']) == 0.15
    assert preset['settings']['pdc_posres_nvt'] == 'no'
    assert preset['settings']['pdc_npt_pcoupl'] == 'c-rescale'

    listed = client.get('/api/setting-presets?run_type=pdc').get_json()
    assert [item['id'] for item in listed['presets']] == [preset['id']]
    assert listed['presets'][0]['is_default'] is False and listed['default'] is None
    # Another run type does not see it: the store is keyed by run type.
    assert client.get('/api/setting-presets?run_type=aa_only').get_json() == {'presets': [], 'default': None}

    patched = client.patch(f"/api/setting-presets/{preset['id']}", json={'is_default': True})
    assert patched.status_code == 200, patched.get_json()
    assert patched.get_json()['defaults'] == {'pdc': preset['id']}
    listed = client.get('/api/setting-presets?run_type=pdc').get_json()
    assert listed['default'] == preset['id'] and listed['presets'][0]['is_default'] is True

    deleted = client.delete(f"/api/setting-presets/{preset['id']}")
    assert deleted.status_code == 200 and deleted.get_json() == {'deleted': preset['id']}
    assert client.get('/api/setting-presets?run_type=pdc').get_json() == {'presets': [], 'default': None}


def test_a_pdc_preset_refuses_a_setting_the_adapter_does_not_advertise(dashboard):
    """The adapter's vocabulary is the authority: a key it does not advertise is refused, never stored and dropped."""
    client = dashboard.client
    refused = client.post('/api/setting-presets', json={
        'name': 'Wrong', 'run_type': 'pdc', 'settings': {'cg_production_ps': 10}})
    assert refused.status_code == 400, refused.get_json()
    assert 'cg_production_ps' in refused.get_json()['error']
    assert client.get('/api/setting-presets?run_type=pdc').get_json() == {'presets': [], 'default': None}
