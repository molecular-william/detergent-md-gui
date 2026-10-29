"""The Run view panel's registry contract: one panel, in both workspaces, scoped to each one's own run types.

`dashboard/web/sections.py` is the single place a panel is declared, and this file holds the two things the panel
would be wrong without:

- **It is registered in both workspaces and resolves.** A registered panel whose label, glyph or DOM id is missing
  renders a tab that resolves to no element -- `tabs.js` finds `null` and hides every panel, leaving a blank
  workspace with no error anywhere. The DOM-id half of that is asserted against the rendered page in
  `tests/dashboard/integration/test_dom_ids.py`; this file asserts the registry's own halves.
- **Its scope is the workspace's own run types, and every one of them is a run type the route accepts.** The panel
  asks `/api/jobs?run_type=<type>` for each of these, and the route refuses a name that is not in
  `protocol.RUN_TYPES` with a 400 rather than an empty page. A scope naming a type the pipeline does not have would
  therefore turn the panel's list into an error, which is what the second assertion below exists to catch.

The scope is registered here rather than written in the panel's JavaScript, because a second copy of the list is a
second place for a run type to go missing -- and because which runs a workspace may reach is a registry question.
"""

import pytest
from dashboard.execution import protocol
from dashboard.web.sections import PANEL_BLURBS, PANELS, TAB_IDS, panel_glyph, panel_label, run_types_for, tabs_for

from tests.dashboard.support import PACKAGE

TEMPLATE = PACKAGE / 'web/templates/dashboard.html'
MODULE = PACKAGE / 'web/static/js/run-view.js'


def test_both_workspaces_offer_the_run_view_panel():
    """One component, two registrations: the panel is how a run is read in either workspace."""
    for name in ('validation', 'simulations'):
        assert 'run-view' in tabs_for(name), f'{name} does not offer the Run view panel'


def test_the_run_view_panel_resolves_to_a_label_glyph_and_dom_id():
    assert panel_label('run-view') == 'Run view'
    assert panel_glyph('run-view') == '⬓'
    assert TAB_IDS['run-view'] == 'runview'
    assert PANELS['run-view'][0] == 'Run view'
    assert PANEL_BLURBS['run-view'], 'a registered panel must carry its one-line description'


def test_each_workspace_scopes_the_run_view_to_its_own_run_types():
    """The heart of D2: a reader picks their workspace's kind out of their workspace's runs.

    Detergent validation reads single-molecule work -- AA-only, AA-CG, CG composition and the osmotic series.
    Protein-detergent simulations reads the complexes it queues, and nothing else: an AA-only run is not that
    workspace's to show.
    """
    assert run_types_for('validation') == ('aa_only', 'aa_cg', 'cg_composition', 'osmotic')
    assert run_types_for('protein-detergent') == ('pdc',)
    assert 'pdc' not in run_types_for('validation')
    assert not set(run_types_for('simulations')) & set(run_types_for('validation'))


def test_every_scoped_run_type_is_one_the_run_list_accepts():
    """The route 400s on a name it does not know, so a scope naming a type that does not exist is a broken panel."""
    for section in ('validation', 'simulations'):
        for run_type in run_types_for(section):
            assert run_type in protocol.RUN_TYPES, \
                f'{section} scopes the panel to {run_type!r}, which /api/jobs refuses'


def test_every_run_type_the_workspace_owns_is_offered():
    """The other direction: a run type in a workspace's tabs nobody can reach is a run nobody can look at.

    `aa_cg` is what a record without a `run_type` resolves to (`protocol.run_type_of`), so it must be reachable
    from the workspace the single-molecule runs live in even if no job record names it by name.
    """
    assert set(run_types_for('validation')) == {'aa_only', 'aa_cg', 'cg_composition', 'osmotic'}
    assert 'aa_cg' in run_types_for('validation')


def test_an_unknown_workspace_is_refused_rather_than_defaulted():
    """A scope resolved from an unknown workspace would be a guess, the same reason a route 404s on an unknown slug."""
    with pytest.raises(KeyError):
        run_types_for('nonsense')
    assert run_types_for('detergent-validation') == run_types_for('validation')


def test_the_panel_reads_its_scope_from_the_page_rather_than_keeping_its_own():
    """A run-type list in the module would be a second source of truth, and the one that drifts."""
    text = MODULE.read_text()
    assert '#run-view-scope' in text, 'the module must read the registry-written scope block'
    assert 'run_types:' not in text and 'RUN_TYPES' not in text, \
        'the module must not carry a run-type list of its own'


def test_the_panels_own_sheet_is_linked_after_the_other_panels_and_before_the_measure():
    """The order is load-bearing, and reversing it stacks the two columns.

    `run-view.css` states the panel's own grid and `layout.css` states the twelve-column measure the two columns
    are hung on. At equal specificity the later sheet wins, so the measure must come last -- the same arrangement
    `new-run.css` sits in.
    """
    html = TEMPLATE.read_text()
    order = [name for name in ('pdc.css', 'run-view.css', 'layout.css') if f"filename='{name}'" in html]
    assert order == ['pdc.css', 'run-view.css', 'layout.css'], html[:2000]
