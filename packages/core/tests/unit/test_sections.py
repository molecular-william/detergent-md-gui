"""The dashboard's two workspaces, and which panels belong to each.

These tests read the registry rather than a rendered page, which is the point of the registry existing: the split is
asserted once here, and a template that renders the wrong panels is a rendering bug rather than a disagreement about
what the split is.

The registry is also the answer to "where does a new panel go" -- a panel is added by naming it in a section's `tabs`
and giving it a label, and the tests below fail if either half is missing.
"""
import pytest
from dashboard import features
from dashboard.web import sections
from dashboard.web.sections import PANELS, SECTIONS, section_by_slug

from tests.harness import factory


def test_the_two_sections_are_the_ones_the_design_names():
    assert set(SECTIONS) == {'validation', 'simulations'}
    assert SECTIONS['validation']['label'] == 'Detergent validation'
    assert SECTIONS['simulations']['label'] == 'Protein-detergent simulations'


def test_every_section_starts_on_a_panel_it_owns():
    """The first panel is the one a bare section URL opens, so it must be a real member of that section."""
    for name, section in SECTIONS.items():
        assert section['tabs'], f'{name} has no panels'
        assert section['tabs'][0] in section['tabs']
        assert section['tabs'][0] == 'runs', 'both workspaces should open on their own run list'


def test_the_panels_that_are_about_one_molecule_stay_out_of_the_simulations_section():
    """The heart of the split: a detergent's own model work is not a protein-detergent system's business."""
    assert set(SECTIONS['validation']['tabs']) >= {'runs', 'new-run', 'bead-assignment', 'bond-interactions',
                                                   'combinations', 'osmotic-pressure'}
    assert set(SECTIONS['simulations']['tabs']) >= {'runs', 'new-run', 'complexes'}
    for panel in ('bead-assignment', 'bond-interactions', 'combinations', 'osmotic-pressure'):
        assert panel not in SECTIONS['simulations']['tabs']
    # The Mapping Validation tab is retired: its per-run analysis lives in Run view, so no workspace offers it.
    assert 'mapping-validation' not in SECTIONS['validation']['tabs']
    for panel in ('complexes', 'initial-state'):
        assert panel not in SECTIONS['validation']['tabs']


def test_both_workspaces_have_their_own_run_list_and_queue_form():
    """`runs` and `new-run` appear in both deliberately: they are different lists and different forms.

    The user's decision was that the two are not shared. A detergent run has no detergent *count*; a complex run
    cannot be queued without one. Asserting the names are present in both is what stops a later "deduplication" from
    quietly merging them.
    """
    for name in SECTIONS:
        assert 'runs' in SECTIONS[name]['tabs']
        assert 'new-run' in SECTIONS[name]['tabs']


def test_every_slug_is_a_url_segment_and_every_panel_is_labelled():
    """A slug goes in an address bar, so it is checked as one rather than as a display name."""
    for name, section in SECTIONS.items():
        slug = section['slug']
        assert slug == slug.lower()
        assert ' ' not in slug and '_' not in slug and '/' not in slug
        for panel in section['tabs']:
            assert panel in PANELS, f'{panel} has no label or glyph'
            assert PANELS[panel][0], f'{panel} has an empty label'


def test_the_slugs_are_distinct_from_the_section_names_they_are_not_derived_from():
    """The label is not the slug, and neither is computed from the other.

    `protein-detergent` is shorter than "Protein-detergent simulations" because that is the path the user asked for.
    A future tidy-up that derives slugs from labels would silently rename a URL.
    """
    for name, section in SECTIONS.items():
        assert section['slug'] != name
    assert SECTIONS['validation']['slug'] == 'detergent-validation'
    assert SECTIONS['simulations']['slug'] == 'protein-detergent'


def test_an_unknown_section_is_refused_rather_than_defaulted():
    """A URL naming a workspace that does not exist is a 404, not a silent redirect into one that does."""
    assert section_by_slug('nonsense') is None
    assert section_by_slug('detergent-validation') is SECTIONS['validation']
    assert section_by_slug('protein-detergent') is SECTIONS['simulations']


def test_the_two_workspaces_label_their_new_run_panel_differently():
    """The rail's word for a panel is shared; the heading above it is where a workspace says what it runs.

    `New run` fits a 200 px rail and is right in both workspaces, so it stays the panel's label. The heading is not
    the same thing: the two workspaces queue different pipelines, and "Single Molecule Simulations" against
    "Protein-Detergent Simulations" is where a reader learns which one they are in.
    """
    assert PANELS['new-run'][0] == 'New run'
    assert SECTIONS['validation']['panel_labels']['new-run'] == 'Single Molecule Simulations'
    assert SECTIONS['simulations']['panel_labels']['new-run'] == 'Protein-Detergent Simulations'


def test_no_other_panel_label_moves_when_one_workspace_names_a_panel():
    """A per-workspace label is a list of exceptions: a panel left out of it keeps its rail label, by name."""
    for section in SECTIONS.values():
        renamed = section.get('panel_labels', {})
        for panel in section['tabs']:
            if panel in renamed:
                continue
            assert PANELS[panel][0], f'{panel} in {section["slug"]} has no rail label'
    assert set(SECTIONS['validation']['panel_labels']) == {'new-run'}
    assert set(SECTIONS['simulations']['panel_labels']) == {'new-run'}
    assert PANELS['runs'][0] == 'Runs'
    assert PANELS['complexes'][0] == 'Complexes'


def test_a_per_workspace_label_names_a_panel_that_workspace_owns():
    """The overview of a workspace lists its panels; a label for a panel it does not have is a dead entry."""
    for name, section in SECTIONS.items():
        for panel in section.get('panel_labels', {}):
            assert panel in section['tabs'], f'{name} labels {panel}, which is not one of its panels'
            assert panel in PANELS, f'{panel} is labelled per workspace but has no rail label or glyph'


def test_visible_honours_dashboard_tabs(monkeypatch):
    """An instance may show fewer panels than its distribution owns; the registry still names them all."""
    section = sections.SECTIONS['validation']
    monkeypatch.setenv('DASHBOARD_TABS', 'runs,new-run')
    assert sections.visible(section)['tabs'] == ('runs', 'new-run')
    monkeypatch.delenv('DASHBOARD_TABS')
    assert sections.visible(section)['tabs'] == section['tabs']


def test_visible_refuses_a_panel_the_workspace_lacks(monkeypatch):
    monkeypatch.setenv('DASHBOARD_TABS', 'runs,not-a-panel')
    with pytest.raises(ValueError, match='not-a-panel'):
        sections.visible(sections.SECTIONS['validation'])


def test_create_app_validates_dashboard_tabs_at_construction(tmp_path, monkeypatch):
    """A bad panel name is a start-up failure, not a 400 on whichever page is opened first.

    `create_app` builds its own application through the factory, so the setting can be changed and read again
    without touching the module-level `app` built at import.
    """
    from tests.harness import factory

    monkeypatch.setenv('DASHBOARD_TABS', 'runs,not-a-panel')
    with pytest.raises(ValueError, match='not-a-panel'):
        factory.build(tmp_path / 'unknown')

    monkeypatch.setenv('DASHBOARD_TABS', 'runs,new-run')
    assert factory.build(tmp_path / 'valid').app is not None

    monkeypatch.delenv('DASHBOARD_TABS')
    assert factory.build(tmp_path / 'unset').app is not None, 'unset still means every panel'


def test_the_engine_registers_its_own_workspace_when_none_is_installed():
    """A core-only install has no feature workspace; the engine's own is the page its front door renders."""
    saved = dict(SECTIONS)
    SECTIONS.clear()
    try:
        sections.ensure_default()
        assert set(SECTIONS) == {'core'}
        assert SECTIONS['core']['tabs'] == ('runs', 'run-view', 'new-run')
        assert SECTIONS['core']['run_types'] == ('aa_only', 'cg')
    finally:
        SECTIONS.clear()
        SECTIONS.update(saved)


def test_a_full_install_keeps_its_workspaces():
    """`ensure_default` only answers an empty registry: a full install must not grow a third, empty tab."""
    before = dict(SECTIONS)
    sections.ensure_default()
    assert SECTIONS == before


def test_a_core_only_install_starts_on_its_own_workspace(tmp_path, monkeypatch):
    """The failure this replaces: with no workspace registered, `/` raised StopIteration and answered 500."""
    saved = dict(SECTIONS)
    SECTIONS.clear()
    monkeypatch.setattr(features, 'ensure', lambda: [])
    try:
        built = factory.build(tmp_path / 'core-only')
        response = built.client.get('/')
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert 'data-tab="runs"' in page and 'data-tab="new"' in page
        assert set(SECTIONS) == {'core'}
    finally:
        SECTIONS.clear()
        SECTIONS.update(saved)
