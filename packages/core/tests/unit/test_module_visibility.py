"""The installed-module switch: a saved view decision, not an unload.

Hiding a module filters the workspace registry on the next page load. Its blueprints, run types, analysis kinds and
recorded-code resolvers stay registered, which is what keeps a run made under it readable after it is switched off.
"""


from dashboard import features
from dashboard import paths as path_config
from dashboard.app import create_app
from dashboard.web import sections

from tests.harness.support import PROJECT_ROOT


def workspace(tmp_path):
    return path_config.Paths(project_root=PROJECT_ROOT, workspace=tmp_path / 'workspace')


def test_the_registry_records_the_module_that_owns_each_workspace():
    owners = {feature.section[0]: feature.name for feature in features.ensure() if feature.section}
    assert owners
    for name, owner in owners.items():
        assert sections.SECTIONS[name]['owner'] == owner


def test_a_workspace_without_a_setting_shows_every_module(tmp_path):
    chosen = sections.enabled(workspace(tmp_path))
    assert chosen is None
    assert all(row['enabled'] for row in sections.module_rows(workspace(tmp_path)))


def test_the_setting_filters_the_shown_workspaces(tmp_path):
    selected = workspace(tmp_path)
    sections.set_enabled(selected, ['validation'])
    try:
        shown = sections.shown(sections.enabled(selected))
        assert 'validation' in shown and 'simulations' not in shown
        assert sections.section_by_slug('protein-detergent', sections.enabled(selected)) is None
    finally:
        sections.set_enabled(selected, ['validation', 'pdc'])


def test_hiding_every_module_leaves_the_engine_workspace(tmp_path):
    shown = sections.shown([])
    assert list(shown) == ['core']
    assert shown['core']['slug'] == 'dashboard'
    assert shown['core']['run_types'] == ('aa_only', 'aa_cg')


def test_the_engine_workspace_is_never_hidden():
    name, record = sections.DEFAULT_SECTION
    assert record.get('owner') is None
    assert sections.shown([])[name] is record


def test_an_unreadable_setting_falls_back_to_every_module(tmp_path, caplog):
    selected = workspace(tmp_path)
    selected.workspace.mkdir(parents=True)
    (selected.workspace / sections.MODULES_FILE).write_text('{not json')
    assert sections.enabled(selected) is None
    assert 'ignoring unreadable' in caplog.text


def test_the_switch_round_trips_through_the_api_and_survives_a_new_application(tmp_path):
    from tests.harness import factory

    built = factory.build(tmp_path / 'first')
    client = built.client
    state = client.get('/api/modules').get_json()
    assert {row['name'] for row in state['modules']} == {feature.name for feature in features.ensure()}

    response = client.put('/api/modules', json={'enabled': ['validation']})
    assert response.status_code == 200
    assert [row['enabled'] for row in response.get_json()['modules'] if row['name'] == 'pdc'] == [False]

    page = client.get('/').get_data(as_text=True)
    assert 'data-section="detergent-validation"' in page
    assert 'data-section="protein-detergent"' not in page
    # A workspace whose module is hidden is a link that was valid a moment ago: it lands on the Runs front door.
    for path in ('/protein-detergent', '/protein-detergent/runs', '/protein-detergent/new-run'):
        response = client.get(path)
        assert response.status_code == 302, path
        assert response.headers['Location'] == '/' or response.headers['Location'].endswith('/'), path
    # A workspace this dashboard does not have, and a panel a shown workspace does not have, are still 404s.
    assert client.get('/not-a-workspace/runs').status_code == 404
    assert client.get('/detergent-validation/not-a-panel').status_code == 404

    # A new application over the same workspace reads the saved set: the switch survives a restart.
    restarted = create_app(built.paths, {'DISABLE_COORDINATOR': True})
    assert 'data-section="protein-detergent"' not in restarted.test_client().get('/').get_data(as_text=True)


def test_an_unknown_module_name_is_refused(tmp_path):
    from tests.harness import factory

    client = factory.build(tmp_path / 'app').client
    response = client.put('/api/modules', json={'enabled': ['validation', 'typo']})
    assert response.status_code == 400
    assert 'unknown module' in response.get_json()['error']
    assert client.put('/api/modules', json={'enabled': 'validation'}).status_code == 400
