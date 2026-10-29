"""Features register with the engine; the engine does not import them.

The two feature distributions do not exist in this checkout yet, so these tests drive the seam with a fabricated
feature. They pin the contract the real features will rely on: discovery is by importability, and registration
**mutates** the registries the engine already reads (run types, kinds, sections) instead of rebinding a name that a
route may have captured.
"""

import pytest
from dashboard import features
from dashboard.analysis import kinds
from dashboard.execution import protocol
from dashboard.web import sections
from flask import Blueprint, Flask


@pytest.fixture
def fake_feature(monkeypatch):
    """One feature record, registered through the same path an installed distribution takes, then withdrawn."""
    blueprint = Blueprint('fake_feature', __name__)

    @blueprint.get('/fake')
    def fake_route():
        return 'ok'

    feature = features.Feature(
        name='fake',
        blueprints=(blueprint,),
        protocols={'fake-run': lambda: None},
        kinds=(kinds.Kind('fake-kind', (), lambda work, payload=None: None, 'Fake', 'n/a', 'n/a'),),
        section=('fake-section', {'slug': 'fake', 'label': 'Fake section', 'blurb': 'a fake',
                                  'tabs': ('fake-panel',), 'run_types': ()}),
        panels=(('fake-panel', ('Fake panel', '*')),),
        blurbs=(('fake-panel', 'nothing runs here'),),
        tab_ids=(('fake-panel', 'fake-panel-id'),),
    )
    monkeypatch.setattr(features, 'installed', lambda: [feature])
    monkeypatch.setattr(features, '_features', None)
    yield feature
    for name in feature.protocols:
        protocol._BUILDERS.pop(name, None)
    protocol.register({})
    for row in feature.kinds:
        kinds.TABLE.pop(row.name, None)
    sections.SECTIONS.pop(feature.section[0], None)
    for slug, _ in feature.panels:
        sections.PANELS.pop(slug, None)
    for slug, _ in feature.blurbs:
        sections.PANEL_BLURBS.pop(slug, None)
    for slug, _ in feature.tab_ids:
        sections.TAB_IDS.pop(slug, None)


def test_discovery_is_importability(monkeypatch, tmp_path):
    """`find_spec` is the install check: a package on the path is a feature, and one absent is not named."""
    package = tmp_path / 'fake_dist'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'feature.py').write_text(
        "from dashboard import features\n\nFEATURE = features.Feature(name='fake-dist')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(features, 'KNOWN', ('fake_dist', 'not_installed_anywhere'))
    monkeypatch.setattr(features, '_features', None)
    assert [feature.name for feature in features.installed()] == ['fake-dist']
    assert [feature.name for feature in features.ensure()] == ['fake-dist'], 'loaded once, then cached'


def test_register_adds_every_part_the_feature_contributes(fake_feature):
    app = Flask(__name__)
    features.register(app)
    assert 'fake-run' in protocol.RUN_TYPES, 'a feature run type is published with the engine ones'
    assert kinds.known('fake-kind'), 'a feature kind is reachable through the table the worker reads'
    assert sections.section_for('fake-section')['slug'] == 'fake'
    assert sections.tabs_for('fake-section') == ('fake-panel',)
    assert sections.tab_id('fake-panel') == 'fake-panel-id'
    assert any(rule.rule == '/fake' for rule in app.url_map.iter_rules()), 'its blueprint is served'


def test_registration_is_once_even_across_applications(fake_feature):
    """Two app objects in one process (the tests build many) must not register the share-a-registry parts twice."""
    features.register(Flask(__name__))
    features.register(Flask(__name__))
    assert protocol.RUN_TYPES.count('fake-run') == 1
    assert list(kinds.TABLE).count('fake-kind') == 1
    assert protocol._BUILDERS['fake-run'] is not None


def test_a_workspace_cannot_be_claimed_twice():
    with pytest.raises(ValueError, match='already registered'):
        sections.register(('simulations', sections.SECTIONS['simulations']))
