"""The dashboard's two workspaces, and which panels belong to each.

These tests read the registry rather than a rendered page, which is the point of the registry existing: the split is
asserted once here, and a template that renders the wrong panels is a rendering bug rather than a disagreement about
what the split is.

The registry is also the answer to "where does a new panel go" -- a panel is added by naming it in a section's `tabs`
and giving it a label, and the tests below fail if either half is missing.
"""
import pytest

from dashboard.web.sections import PANEL_BLURBS, PANELS, PLANNED, SECTIONS, panel_glyph, panel_label, section_by_slug, section_for, tabs_for


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
    assert tabs_for('validation') >= ('runs', 'new-run', 'bead-assignment', 'bond-interactions',
                                      'combinations', 'mapping-validation')
    assert tabs_for('simulations') >= ('runs', 'new-run', 'complexes')
    for panel in ('bead-assignment', 'bond-interactions', 'combinations', 'mapping-validation',
                  'osmotic-pressure'):
        assert panel not in tabs_for('simulations')
    for panel in ('complexes', 'initial-state'):
        assert panel not in tabs_for('validation')


def test_a_planned_panel_is_not_offered_by_any_workspace():
    """A panel registered in `tabs` renders a live tab, so an unbuilt one must not be there.

    This is the invariant that was violated: `osmotic-pressure` and `initial-state` were listed as tabs while no
    section existed for either, and a tab whose panel is missing hides every panel on the page when clicked. They
    belong in `PLANNED` -- named, greyed where the overview lists them, and not clickable -- until their sections
    are written.
    """
    registered = {panel for section in SECTIONS.values() for panel in section['tabs']}
    for panel in PLANNED:
        assert panel not in registered, f'{panel} is planned but offered as a tab'


def test_both_workspaces_have_their_own_run_list_and_queue_form():
    """`runs` and `new-run` appear in both deliberately: they are different lists and different forms.

    The user's decision was that the two are not shared. A detergent run has no detergent *count*; a complex run
    cannot be queued without one. Asserting the names are present in both is what stops a later "deduplication" from
    quietly merging them.
    """
    for name in SECTIONS:
        assert 'runs' in tabs_for(name)
        assert 'new-run' in tabs_for(name)


def test_every_slug_is_a_url_segment_and_every_panel_is_labelled():
    """A slug goes in an address bar, so it is checked as one rather than as a display name."""
    for name, section in SECTIONS.items():
        slug = section['slug']
        assert slug == slug.lower()
        assert ' ' not in slug and '_' not in slug and '/' not in slug
        for panel in section['tabs']:
            assert panel in PANELS, f'{panel} has no label or glyph'
            assert panel_label(panel), f'{panel} has an empty label'


def test_the_slugs_are_distinct_from_the_section_names_they_are_not_derived_from():
    """The label is not the slug, and neither is computed from the other.

    `protein-detergent` is shorter than "Protein-detergent simulations" because that is the path the user asked for.
    A future tidy-up that derives slugs from labels would silently rename a URL.
    """
    for name, section in SECTIONS.items():
        assert section['slug'] != name
    assert SECTIONS['validation']['slug'] == 'detergent-validation'
    assert SECTIONS['simulations']['slug'] == 'protein-detergent'


def test_every_blurb_describes_a_panel_that_exists_and_every_panel_has_one():
    """The overview lists these, so a panel without a blurb and a blurb without a panel are both rendering bugs."""
    registered = {panel for section in SECTIONS.values() for panel in section['tabs']}
    for panel in registered:
        assert panel in PANEL_BLURBS, f'{panel} is rendered but undescribed'
    for panel in PANEL_BLURBS:
        assert panel in registered or panel in PLANNED, f'{panel} is described but never rendered'


def test_a_panel_with_no_label_raises_rather_than_returning_its_slug():
    """A missing label is a registry error. Returning the slug ships a page reading `new-run` to a person."""
    with pytest.raises(KeyError):
        panel_label('not-a-panel')
    assert panel_label('new-run') == 'New run'
    assert panel_glyph('new-run') == '▶'
    assert panel_glyph('not-a-panel') == '', 'an unregistered glyph is empty, not an exception: the rail can do without it'


def test_an_unknown_section_is_refused_rather_than_defaulted():
    """A URL naming a workspace that does not exist is a 404, not a silent redirect into one that does."""
    assert section_for('nonsense') is None
    assert section_for('validation') is SECTIONS['validation']
    assert section_by_slug('nonsense') is None
    assert section_by_slug('detergent-validation') is SECTIONS['validation']
    assert section_by_slug('protein-detergent') is SECTIONS['simulations']
