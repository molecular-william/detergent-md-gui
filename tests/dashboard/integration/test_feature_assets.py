"""A feature's panels are its own files; the shell names no feature and ships no feature markup.

The registry is the contract: `Feature.panel_modules` says which DOM id a feature mounts from which module, the panes
come from its template package, and the shell loop includes what is installed and skips what is not. These tests read
the registry rather than a list of file names, so a new feature is covered the moment it registers.
"""
from pathlib import Path

from dashboard import features, paths
from dashboard.app import create_app

TEMPLATE = Path(__file__).resolve().parents[3] / 'packages/core/src/dashboard/web/templates/dashboard.html'


def test_every_registered_panel_has_a_module_and_a_pane():
    for panel, (owner, module, factory) in features.browser_panels().items():
        feature = {each.name: each for each in features.ensure()}[owner]
        assert (feature.static / module).is_file(), f'{panel}: {feature.static / module} is missing'
        assert (feature.templates / 'panels' / f'{panel}.html').is_file(), f'{panel}: its pane is missing'
        assert factory.isidentifier(), f'{panel}: {factory!r} is not a JS export name'


def test_the_shell_template_names_no_feature_panel():
    source = TEMPLATE.read_text()
    assert '{% for panel_id in panel_modules %}' in source, 'the shell lost the registry loop'
    for panel in features.browser_panels():
        assert f'<section id="{panel}"' not in source, f'the shell still hard-codes the {panel} panel'


def test_a_feature_asset_is_served_from_that_feature_only(tmp_path):
    app = create_app(paths=paths.Paths(project_root=paths.default_paths().project_root, workspace=tmp_path),
                     config={'DISABLE_COORDINATOR': True})
    client = app.test_client()
    for panel, (owner, module, _) in features.browser_panels().items():
        response = client.get(f'/feature-assets/{owner}/{module}')
        assert response.status_code == 200, f'{panel}: {owner}/{module} is not served'
        assert 'javascript' in response.headers['Content-Type'], panel
    assert client.get('/feature-assets/not-a-feature/anything.js').status_code == 404


def test_every_registered_extension_module_is_served(tmp_path):
    """A shared panel's feature half is a module under that feature's static tree, served like its panels.

    `Feature.extension_modules` is what `boot` imports before any panel mounts, so a path with no file behind it is
    a workspace whose panel silently falls back to the engine's -- and only at a browser's load.
    """
    app = create_app(paths=paths.Paths(project_root=paths.default_paths().project_root, workspace=tmp_path),
                     config={'DISABLE_COORDINATOR': True})
    client = app.test_client()
    modules = features.browser_extensions()
    assert modules, 'no feature registers an extension module'
    by_name = {feature.name: feature for feature in features.ensure()}
    for owner, module in modules:
        assert (by_name[owner].static / module).is_file(), f'{owner}/{module} is not in that feature tree'
        response = client.get(f'/feature-assets/{owner}/{module}')
        assert response.status_code == 200, f'{owner}/{module} is not served'
        assert 'javascript' in response.headers['Content-Type'], module


def test_every_section_fragment_is_in_its_features_template_package():
    """A workspace may name its form, its blurb and its gallery note as fragments; each must exist to render."""
    for feature in features.ensure():
        if not feature.section:
            continue
        record = feature.section[1]
        for key in ('form_fragment', 'form_blurb', 'gallery_note'):
            named = record.get(key)
            if named:
                assert (feature.templates / named).is_file(), f'{feature.name}: {key} names a missing fragment {named}'
