"""A workspace's URLs render that workspace's panels, and a panel it does not have is a 404.

The first test is the one that mattered. `sections.py` is the registry of which panels a workspace owns, and
`dashboard.html` is where those panels live; nothing tied them together, so a panel could be registered -- and so
rendered as a live tab -- while its section did not exist. That is not a cosmetic mismatch: `tabs.js` looks a panel up
by id, finds `null`, and then hides every panel on the page, so clicking the tab leaves a blank workspace with no
error anywhere. The osmotic series and the micelle builder were both registered that way, and both were removed from
the tab lists rather than given empty sections, because a panel nobody has built should not look built.
"""
import re
from pathlib import Path

import pytest

from dashboard.web.sections import SECTIONS, TAB_IDS


def panel_sections_in_template():
    """The `id` of every panel section the template renders.

    Matched on `panel` being one of the section's classes rather than on the attribute equalling `class="panel"`:
    a workspace-specific class beside it (`class="panel bonded-workspace"`) is still a panel, and the stricter
    pattern reported a panel missing that the page renders -- a false red on a change that only added a class.
    """
    html = (Path(__file__).resolve().parents[3] / 'dashboard/web/templates/dashboard.html').read_text()
    found = set()
    for match in re.finditer(r'<section id="([a-z-]+)"([^>]*)>', html):
        classes = re.search(r'class="([^"]*)"', match.group(2))
        if classes and 'panel' in classes.group(1).split():
            found.add(match.group(1))
    return found


@pytest.mark.parametrize('name', sorted(SECTIONS))
def test_every_registered_panel_has_a_section_in_the_template(name):
    """A tab whose panel is missing blanks the workspace, and no tier would report it."""
    rendered = panel_sections_in_template()
    for slug in SECTIONS[name]['tabs']:
        assert TAB_IDS[slug] in rendered, (
            f'{name} registers {slug!r}, whose panel id {TAB_IDS[slug]!r} has no section in dashboard.html -- '
            f'the tab would render and hide every panel when clicked')


def test_a_panel_this_workspace_does_not_have_is_a_404(dashboard):
    """`selectTab` used to answer a name it did not know with the first tab. A URL says what happened instead."""
    with dashboard.client as c:
        assert c.get('/detergent-validation/complexes').status_code == 404
        assert c.get('/protein-detergent/bead-assignment').status_code == 404
        assert c.get('/detergent-validation/nonsense').status_code == 404
        assert c.get('/nonsense/runs').status_code == 404


def test_each_workspace_offers_only_its_own_panels(dashboard):
    """Asserted on the link row, not the panels.

    The template still renders every panel and hides the ones a workspace does not own, so a panel's id being present
    in the page says nothing about ownership -- my first version of this test asserted on that and was wrong. What a
    workspace *offers* is its row of sub-tab links, and each link is scoped to its own workspace's slug.
    """
    with dashboard.client as c:
        validation = c.get('/detergent-validation/runs').get_data(as_text=True)
        simulations = c.get('/protein-detergent/complexes').get_data(as_text=True)
    assert '/detergent-validation/bead-assignment' in validation
    assert '/protein-detergent/bead-assignment' not in simulations
    assert '/protein-detergent/complexes' in simulations
    assert '/detergent-validation/complexes' not in validation


def test_the_front_door_renders_its_sub_tabs(dashboard):
    """The section tabs come from the registry and the sub-tab row from the *resolved* workspace.

    Those are two different lookups, and when they disagree the page renders its two workspace tabs above an empty
    row -- which is how this broke: the front door passed the registry's key where a slug was expected, so the
    template iterated an undefined value and Jinja said nothing. Counting the rows is the assertion that would have
    caught it, and asserting only that the two workspace tabs are present (the first version of this test) is not.
    """
    with dashboard.client as c:
        body = c.get('/').get_data(as_text=True)
    assert body.count('class="subtab"') == len(SECTIONS['validation']['tabs']), (
        'the front door must render every sub-tab of the workspace it opens on')
    for slug in SECTIONS['validation']['tabs']:
        assert f'/detergent-validation/{slug}' in body


def test_the_front_door_answers_with_a_workspace_and_names_its_panel(dashboard):
    """`/` renders rather than redirects, so the client can send a returning browser to its own workspace."""
    with dashboard.client as c:
        page = c.get('/')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'section-tab' in body, 'the two workspace tabs are rendered'
    assert 'id="legacy-tabs"' in body, 'and the map from an old /#tab fragment to its new address'
