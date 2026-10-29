"""What the server hands the Run view panel: the workspace's own scope, in the page, in both workspaces.

The panel is one module mounted in two places, and the only thing that tells it where it is is the scope block the
template renders from the registry (`routes/runs.py`'s `workspace_context`). So this file drives the real route and
reads the block back: a scope that disagreed with `sections.run_types_for` would have the panel offering one
workspace's runs from the other, and no test of the registry alone could see it.

The last test is the door from the Runs table (`D10`): a link on every run row, addressed by the run's id, so a
reader arrives on the panel with that run already drawn.
"""
import json
import re

from dashboard.web.sections import run_types_for

from tests.harness.support import PACKAGE

TEMPLATE = PACKAGE / 'web/templates/dashboard.html'


def scope_of(client, url):
    """The scope block as the page renders it, parsed rather than pattern-matched."""
    page = client.get(url)
    assert page.status_code == 200, url
    found = re.search(r'<script type="application/json" id="run-view-scope">(.*?)</script>',
                      page.get_data(as_text=True), re.S)
    assert found, 'the Run view scope block is not rendered'
    return json.loads(found.group(1))


def test_each_workspace_renders_its_own_run_view_scope(dashboard):
    with dashboard.client as client:
        validation = scope_of(client, '/detergent-validation/run-view')
        simulations = scope_of(client, '/protein-detergent/run-view')
    assert validation == {'slug': 'detergent-validation', 'types': list(run_types_for('validation'))}
    assert simulations == {'slug': 'protein-detergent', 'types': list(run_types_for('simulations'))}


def test_the_panel_is_the_open_one_when_the_url_names_it(dashboard):
    """A cold request returns the panel open, before any JavaScript runs -- and hidden where it is not the panel."""
    with dashboard.client as client:
        open_page = client.get('/detergent-validation/run-view').get_data(as_text=True)
        other_page = client.get('/protein-detergent/complexes').get_data(as_text=True)
        simulations = client.get('/protein-detergent/run-view').get_data(as_text=True)
    tag = re.compile(r'<section id="runview"[^>]*>')

    def opening(page):
        found = tag.search(page)
        assert found, 'the Run view section is not rendered'
        return found.group(0)

    assert opening(open_page) == \
        '<section id="runview" class="panel" role="tabpanel" aria-labelledby="tab-runview">'
    assert 'hidden' in opening(other_page), 'the panel is hidden on a page that is not its own'
    assert 'hidden' not in opening(simulations), 'and open in the other workspace too'


def test_the_sub_tab_rows_grew_by_the_new_panel_and_nothing_else_moved(dashboard):
    """Validation goes from seven tabs to eight; the rail was built for more, and no other label changes."""
    with dashboard.client as client:
        validation = client.get('/detergent-validation/run-view').get_data(as_text=True)
        simulations = client.get('/protein-detergent/run-view').get_data(as_text=True)
    assert validation.count('class="subtab"') == 8
    assert simulations.count('class="subtab"') == 4
    for label in ('Runs', 'New run', 'Bead Assignment', 'Bond Interactions', 'Combinations', 'Mapping Validation',
                  'Osmotic Series'):
        assert f'>{label}</span>' in validation, f'{label} is missing from the run-view page'
    assert '>Run view</span>' in validation and '>Run view</span>' in simulations


def test_a_run_row_carries_the_link_to_its_own_run_view(dashboard):
    """The second door to a run: the list is one, this link is the other, and it names the run in the query."""
    template = TEMPLATE.read_text()
    assert 'job-view-run' in template, 'the Runs table row has no View run link'
    runs_js = (PACKAGE / 'web/static/js/runs.js').read_text()
    assert '/run-view?run=' in runs_js, 'the link is not addressed to the Run view panel'
