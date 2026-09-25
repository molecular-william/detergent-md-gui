"""The factory fixture builds an application the test owns.

The autouse fixture patched the import-time singleton and had to remember six attributes; the
factory builds an application instead, so what a test touches is that application's own
coordinator and its own workspace. This pins the fixture itself, since the migration depends on
it being a real second application and not a second name for the singleton.
"""
from dashboard.app import default_coordinator


def test_the_fixture_builds_an_application_of_its_own(dashboard):
    assert dashboard.coordinator is not default_coordinator
    assert dashboard.coordinator.app is dashboard.app
    assert dashboard.client.get('/api/jobs').status_code == 200


def test_the_factory_workspace_is_the_tests_own(dashboard):
    """The database and run directories hang off the workspace the factory chose."""
    assert dashboard.coordinator.DATA == dashboard.paths.database
    assert dashboard.paths.database.parent == dashboard.paths.workspace
    assert dashboard.paths.runs.parent == dashboard.paths.workspace


def test_the_factory_accepts_config_for_the_application(tmp_path):
    from tests.dashboard import factory
    built = factory.build(tmp_path, MAX_CONTENT_LENGTH=2048)
    assert built.app.config['MAX_CONTENT_LENGTH'] == 2048
    assert built.app.config['DISABLE_COORDINATOR'] is True, 'config defaults still apply'
