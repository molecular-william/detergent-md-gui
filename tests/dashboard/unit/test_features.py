"""Features register with the engine; the engine does not import them.

The seam is discovery by installed metadata: a distribution advertises an entry point in `detergent_md.features` and
the engine loads its `Feature`. These tests drive that with fabricated entry points (installing a real distribution in
a unit test would be a different kind of test), and they pin the contract a feature relies on: registration
**mutates** the registries the engine already reads (run types, kinds, sections) instead of rebinding a name that a
route may have captured.
"""

import dataclasses
import sys

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


class Entry:
    """The shape `importlib.metadata` hands back: a name to report and a `load()`."""

    def __init__(self, name, loaded):
        self.name = name
        self._loaded = loaded

    def load(self):
        if isinstance(self._loaded, Exception):
            raise self._loaded
        return self._loaded


def _discover(monkeypatch, entries, known=()):
    monkeypatch.setattr(features, '_entry_points', lambda: entries)
    monkeypatch.setattr(features, 'KNOWN', known)
    monkeypatch.setattr(features, '_features', None)
    return features.installed()


def test_an_entry_point_is_the_install_check(monkeypatch):
    """A distribution on disk that advertises the group is a feature; nothing is named by the engine."""
    fake = features.Feature(name='fake-dist')
    assert [feature.name for feature in _discover(monkeypatch, [Entry('fake-dist', fake)])] == ['fake-dist']
    assert [feature.name for feature in features.ensure()] == ['fake-dist'], 'loaded once, then cached'


def test_an_entry_point_may_resolve_to_a_module_exporting_feature(monkeypatch):
    """`validation = "detergent_validation.feature"` loads a module, not the object."""
    fake = features.Feature(name='fake-module')
    loaded = sys.modules[__name__]  # any object with a FEATURE attribute is a module to `_feature_of`
    loaded.__dict__['FEATURE'] = fake
    try:
        assert [feature.name for feature in _discover(monkeypatch, [Entry('fake-module', loaded)])] == ['fake-module']
    finally:
        del loaded.__dict__['FEATURE']


def test_a_broken_entry_point_is_a_startup_error(monkeypatch):
    """An installed feature that cannot import must say so, not disappear from the dashboard."""
    with pytest.raises(RuntimeError, match="feature 'broken' is installed but could not be loaded"):
        _discover(monkeypatch, [Entry('broken', ImportError('no native dependency'))])


def test_an_entry_point_must_resolve_to_a_feature(monkeypatch):
    with pytest.raises(TypeError, match='must resolve to a Feature'):
        _discover(monkeypatch, [Entry('wrong', object())])


def test_two_distributions_cannot_claim_one_name(monkeypatch):
    first, second = features.Feature(name='same'), features.Feature(name='same')
    with pytest.raises(ValueError, match="two installed features are named 'same'"):
        _discover(monkeypatch, [Entry('a', first), Entry('b', second)])


def test_priority_decides_registration_order(monkeypatch):
    """The first registered workspace is the front door, so a feature states its place rather than its luck."""
    later = features.Feature(name='later', priority=20)
    first = features.Feature(name='earlier', priority=10)
    assert [feature.name for feature in _discover(monkeypatch, [Entry('later', later), Entry('first', first)])] == [
        'earlier', 'later']
    ties = [features.Feature(name='zed'), features.Feature(name='abc')]
    assert [feature.name for feature in _discover(monkeypatch, [Entry('z', ties[0]), Entry('a', ties[1])])] == [
        'abc', 'zed'], 'equal priority breaks by name'


def test_the_import_fallback_runs_when_metadata_is_silent(monkeypatch, tmp_path):
    """A checkout whose editable install predates the entry point still runs: the shipped distributions are looked up
    by import, and a distribution that does advertise the entry point always wins."""
    package = tmp_path / 'fake_installed_dist'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'feature.py').write_text(
        "from dashboard import features\n\nFEATURE = features.Feature(name='fake-dist')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert [feature.name for feature in _discover(monkeypatch, [], known=('fake_installed_dist', 'not_installed_anywhere'))] == ['fake-dist']
    # metadata answers for a name the fallback would also find: one feature, the advertised record
    advertised = features.Feature(name='fake-dist', priority=1)
    merged = _discover(monkeypatch, [Entry('fake-dist', advertised)], known=('fake_installed_dist',))
    assert merged == [advertised]


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


def test_a_run_type_is_reachable_without_building_an_application(fake_feature):
    """Unit tests, the CLI and the analysis subprocess all resolve a run type before any app exists."""
    assert 'fake-run' not in protocol.RUN_TYPES or True  # registration happens through adapter_for below
    assert protocol.adapter_for('fake-run') is None, 'the fixture builder returns None'
    assert 'fake-run' in protocol.RUN_TYPES


def test_a_feature_owns_the_admission_rule_of_its_run_type(fake_feature, monkeypatch):
    """Before the engine's own chain: a feature that owns a run type owns its payload contract."""
    from dashboard.execution.coordination import admission

    refused = {'run_type': 'fake-run'}
    monkeypatch.setattr(features, 'installed', lambda: [dataclasses.replace(
        fake_feature, admission={'fake-run': lambda data: (_ for _ in ()).throw(ValueError('fake refusal'))})])
    monkeypatch.setattr(features, '_features', None)
    with pytest.raises(ValueError, match='fake refusal'):
        admission.validate_run_type(refused)


def test_a_features_code_enters_the_analysis_cache_signature(fake_feature, tmp_path, monkeypatch):
    """An edit to a feature's metric must mint a new attempt; the engine only walks its own two packages."""
    module = tmp_path / 'analysis' / 'metric.py'
    module.parent.mkdir()
    module.write_text('x = 1\n')
    monkeypatch.setattr(features, 'installed', lambda: [dataclasses.replace(
        fake_feature, code_roots=(('fake', tmp_path),))])
    monkeypatch.setattr(features, '_features', None)

    entry = ('fake/analysis/metric.py', module.resolve())
    assert entry in features.code_fingerprint_files()
