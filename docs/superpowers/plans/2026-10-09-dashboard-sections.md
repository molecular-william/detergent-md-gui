# The dashboard's two sections: implementation plan

> **For Hermes:** use the `subagent-driven-development` skill to execute this task by task. Read
> `docs/superpowers/specs/2026-10-09-dashboard-sections-design.md` first — it carries the reasoning, the rejected
> alternatives, and the decisions this plan assumes.

**Goal:** the dashboard opens on a landing view with two buttons, one leading to a **detergent validation** section
and one to a **protein-detergent simulations** section, each rendering only its own tabs and panels.

**Architecture:** one Flask application, one coordinator, one job store, and the 79 existing endpoints untouched. A
section is a server-side value that decides which `[role=tab]` buttons and which `[role=tabpanel]` sections the
template renders; `tabs.js` already scopes itself to whatever tabs are in the document, so no panel JavaScript
changes. The landing is a route of its own with no tabs at all.

**Tech stack:** Flask + Jinja templates, plain ES modules, pytest, and the browser tier (Playwright-driven) that
already exists.

**Shape of this document:** Phase 1 in full, because it is the part that can go wrong quietly — the shell, the
landing, and the browser tier. Phases 2 to 4 are named with their paths and their acceptance criteria, and are
detailed when Phase 1 has landed and the decisions at the end of the spec are settled. Detailing them now would mean
writing code against decisions that have not been made.

**Two rules this plan holds itself to, both learned in this repository.** No commit leaves the suite red: where a
change breaks existing tests, the test update lands *in the same commit*, not in a later one. And **every
`Expected:` count below was measured before it was written** — where a number is not known yet, the step says to
record it rather than predicting it.

---

## Phase 1: the shell, the landing, and the browser tier

### Task 1.1: The section registry

**Objective:** one place that says which tabs each section owns, so the template does not become the only record of
the split.

**Files:**
- Create: `dashboard/web/sections.py`
- Test: `tests/dashboard/unit/test_sections.py`

**Step 1: Write the failing test**

```python
from dashboard.web.sections import SECTIONS, section_for, tabs_for


def test_the_two_sections_are_the_ones_the_design_names():
    assert set(SECTIONS) == {'validation', 'simulations'}
    assert SECTIONS['validation']['label'] == 'Detergent validation'
    assert SECTIONS['simulations']['label'] == 'Protein-detergent simulations'


def test_every_section_starts_on_a_tab_it_owns():
    """The first tab is the one `selectTab` falls back to when a stale name is restored from storage."""
    for name, section in SECTIONS.items():
        assert section['tabs'], f'{name} has no tabs'
        assert section['tabs'][0] in section['tabs']


def test_a_panel_belongs_to_at_least_one_section_and_never_to_both_runs_lists():
    """`runs` and `new` appear in both by design; the panels that are about one molecule do not."""
    assert tabs_for('validation') >= {'runs', 'new', 'mappings', 'bonded', 'compositions', 'validation'}
    assert tabs_for('simulations') == ('runs', 'new', 'pdc')


def test_an_unknown_section_is_refused_rather_than_defaulted():
    """A URL that names a section which does not exist is a 404, not a silent redirect into one of them."""
    assert section_for('nonsense') is None
    assert section_for('validation') is not None
```

**Step 2: Run it to verify it fails**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_sections.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.web.sections'`

**Step 3: Write the registry**

```python
"""Which tabs each section of the dashboard owns.

The split is a view: one coordinator, one job store, one set of endpoints. This module is the single record of what
goes where, so the template renders a section rather than deciding for itself, and so a test can assert the split
without reading HTML.
"""

#: The glyph each tab shows in the rail, kept beside the tabs rather than in the template so a section cannot render
#: a tab whose glyph nobody defined.
GLYPHS = {'runs': '☰', 'new': '▶', 'validation': '✓', 'pdc': '⬡',
          'mappings': '◎', 'bonded': '⇄', 'compositions': '⧉', 'osmotic': '△'}


def section_for(name):
    """The section `name`, or `None`. A route turns `None` into a 404 rather than choosing a section for the caller."""
    return SECTIONS.get(name)


def tabs_for(name):
    """The tabs a section renders, in the order it renders them."""
    section = SECTIONS.get(name)
    return tuple(section['tabs']) if section else ()
```

with `SECTIONS` itself above them. Note the apostrophe in the blurb: this is Python source, and the string is
double-quoted precisely so the prose does not need escaping.

```python
SECTIONS = {
    'validation': {
        'label': 'Detergent validation',
        'blurb': "Build and check a detergent's coarse-grained model: assign beads, fit its bonded terms, combine "
                 "molecules, and compare each against its reference and against measured data.",
        # `osmotic` is the concentration series built on 2026-10-08; its reader is committed as 2f6162b.
        'tabs': ('runs', 'new', 'mappings', 'bonded', 'compositions', 'validation', 'osmotic'),
    },
    'simulations': {
        'label': 'Protein-detergent simulations',
        'blurb': 'Set up and run a protein with its detergent, and read the results.',
        'tabs': ('runs', 'new', 'pdc'),
    },
}
```

**Step 4: Run it to verify it passes**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_sections.py -q`
Expected: PASS. Record the count it prints; do not copy a count from this document.

**Step 5: Commit**

```bash
git add dashboard/web/sections.py tests/dashboard/unit/test_sections.py
git commit -m "feat: the dashboard's two sections, in one registry rather than in the template"
```

---

### Task 1.2: The landing

**Objective:** `/` shows two buttons and nothing else.

**Files:**
- Create: `dashboard/web/templates/landing.html`
- Modify: `dashboard/web/routes/runs.py` (or a new `dashboard/web/routes/home.py`, registered in `dashboard/app.py`'s
  `for module in (...)` tuple)
- Test: `tests/dashboard/integration/test_landing.py`

**Step 1: Write the failing test**

```python
def test_the_landing_offers_both_sections_and_no_tabs(dashboard):
    with dashboard.client as c:
        page = c.get('/')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'Detergent validation' in body
    assert 'Protein-detergent simulations' in body
    assert '/validation' in body and '/simulations' in body
    assert 'role="tab"' not in body, 'the landing is a fork in the road, not a workspace'


def test_each_section_is_reachable_from_the_landing(dashboard):
    with dashboard.client as c:
        for path in ('/validation', '/simulations'):
            assert c.get(path).status_code == 200
```

**Step 2: Run it to verify it fails**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_landing.py -q`
Expected: FAIL — 404 for `/`, because the dashboard single page is at `/` today and moving it is Task 1.3.

**Step 3: Write the landing template and route**

`landing.html` extends the existing shell's head (read `dashboard.html` for the block names rather than assuming
them) and renders, for each section in `SECTIONS`, an `<a>` carrying the section's label and blurb. The buttons are
**links, not JavaScript**: a landing that needs a script to work is a landing that is broken when the script is.

**Step 4: Run it to verify it passes**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_landing.py -q`
Expected: PASS. Record the count.

**Step 5: Commit**

```bash
git add dashboard/web/routes/home.py dashboard/web/templates/landing.html dashboard/app.py tests/dashboard/integration/test_landing.py
git commit -m "feat: the dashboard opens on a fork -- two sections, and no workspace behind it"
```

---

### Task 1.3: The sections render the workspace

**Objective:** `/validation` and `/simulations` render the existing dashboard, scoped to their own tabs.

**Files:**
- Modify: `dashboard/web/routes/runs.py` (the route that renders `dashboard.html` today — find it, do not guess)
- Modify: `dashboard/web/templates/dashboard.html` (the `<nav role="tablist">` block, lines 21-31 today)
- Test: `tests/dashboard/integration/test_sections_api.py`

**Step 1: Write the failing test**

```python
def test_a_section_renders_its_own_tabs_and_not_the_others(dashboard):
    """The assertion is on the *panels*, not the buttons: a panel present but unreachable is still a panel."""
    for section, expected, absent in (('validation', ('mappings', 'bonded', 'validation'),
                                       ('pdc',)),
                                      ('simulations', ('pdc',), ('mappings', 'bonded', 'compositions'))):
        with dashboard.client as c:
            body = c.get(f'/{section}').get_data(as_text=True)
        for tab in expected:
            assert f'data-tab="{tab}"' in body, f'{section} should offer {tab}'
            assert f'id="{tab}"' in body, f'{section} should render the {tab} panel'
        for tab in absent:
            assert f'id="{tab}"' not in body, f'{section} should not render the {tab} panel at all'


def test_the_run_list_is_present_in_both_sections(dashboard):
    with dashboard.client as c:
        for section in ('validation', 'simulations'):
            assert 'id="runs"' in c.get(f'/{section}').get_data(as_text=True)


def test_an_unknown_section_is_a_404_and_not_a_workspace(dashboard):
    with dashboard.client as c:
        assert c.get('/nonsense').status_code == 404
```

**Step 2: Run it to verify it fails**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_sections_api.py -q`
Expected: FAIL — `/validation` is a 404, and the single page at `/` renders all seven tabs.

**Step 3: Make the template render a section**

Replace the seven handwritten `<button role="tab">` elements with a loop over the section's tabs, and wrap each
`<section class="panel" role="tabpanel">` in a membership test on the same list. Read the existing block before
editing it: the buttons carry `id`, `aria-controls`, `data-tab`, a glyph span and a text span, and every one of those
is load-bearing — `tabs.js` reads `data-tab` and toggles `hidden` on the element named by it, and the accessibility
tier asserts the `aria-controls` pairing.

The route passes the section; the template reads it. Nothing else about the page changes.

**Step 4: Run the *whole* fast tier, not just the new tests**

Run: `dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q`
Expected: this is where a change to `dashboard.html` shows its blast radius. Record the pass/fail counts it prints.
The fast tier measured **1208 passed** at `2f6162b`; anything less means a test read the page and found it changed.

**Step 5: Commit**

```bash
git add dashboard/web/routes/runs.py dashboard/web/templates/dashboard.html tests/dashboard/integration/test_sections_api.py
git commit -m "feat: a section renders its own tabs, and a tab that is not in the section is not in the page"
```

---

### Task 1.4: The browser tier knows which page it is on

**Objective:** every browser test opens the section it belongs to, and the suite is green again.

**Files:**
- Modify: `tests/dashboard/browser/test_dashboard_browser.py` (and any conftest helper that opens `/`)
- Test: the browser tier itself

**This task is not optional and must not be deferred to "later".** A refactor that lands with a red browser tier has
not landed; the browser tier is the only tier that proves the tabs, the hash, and the rail actually work.

**Step 1: Read the tier's own entry point**

Run: `grep -rn "goto\|page.goto\|base_url\|live_server" tests/dashboard/browser/conftest.py | head -20`
Do not assume the fixture's name. Every test that navigates goes through it, and that is the single place the
section is added — a per-test edit of 54 tests is the wrong change.

**Step 2: Make the section a parameter of the fixture, defaulting to `validation`**

The tier's existing tests are almost all about the validation-side panels (bead assignment, bonded terms, the
mapping comparison), so `validation` is the default that leaves most of them unchanged. Tests about `pdc` ask for
`simulations` explicitly.

**Step 3: Run the browser tier**

Run: `dashboard/.venv/bin/python -m pytest -m browser -q -n 2`
Expected: record the counts. The last full run before this work was **53 passed, 1 skipped**; that one skip is a
quarantined behaviour with no issue tracking it, and it should either be fixed or deleted while this tier is being
touched anyway.

**Step 4: Commit**

```bash
git add tests/dashboard/browser/
git commit -m "test: the browser tier opens the section its subject belongs to"
```

---

### Task 1.5: The section switcher, and the tab remembered per section

**Objective:** nobody is stranded in a section, and switching does not forget where you were.

**Files:**
- Modify: `dashboard/web/templates/dashboard.html` (the shell's header)
- Modify: `dashboard/web/static/js/tabs.js`
- Test: `tests/dashboard/browser/`

**Step 1:** Add a link back to `/` in the shell, labelled with the *other* section as well as home — a person in the
wrong section should be able to see where the other one is without going home first.

**Step 2:** Key the remembered tab by section: `storage.set('tab:' + section, id)`. `selectTab` already falls back
to the first tab it finds, so the old key degrades safely and needs no migration.

**Step 3:** Run the browser tier, and hard-reload (the skill's rule: a running dashboard freezes Python and models at
process start but re-reads templates and static files per request — so a template or JS edit reaches the next
request, but restart after any Python change).

Run: `dashboard/.venv/bin/python -m pytest -m browser -q -n 2`
Expected: record the counts.

**Step 4: Commit**

```bash
git add dashboard/web/templates/dashboard.html dashboard/web/static/js/tabs.js tests/dashboard/browser/
git commit -m "feat: a way back to the fork, and the tab you were on remembered per section"
```

---

## Phase 2: the panels regroup, and the run lists diverge

Named now, detailed when Phase 1 has landed and the decisions are settled.

- **2.1 — the run list filtered per section.** Both sections show `id="runs"`; the validation one should not list a
  protein-detergent complex run and the other should not list a bead-assignment probe. This needs the job store's
  own run-type vocabulary, which the coordinator already has.
- **2.2 — the cross-section links.** `main.js`'s `onValidate` and `openBondedModel` switch tabs in place today. From
  the simulations section they must navigate. Acceptance: a run opened in either section can reach its validation
  without a dead end, and the tests that pin those links assert the navigation rather than the tab.
- **2.3 — "Single Molecule Simulations" split from the complex launch.** Both sections have a `new` tab today
  rendering one form. Either the form is scoped by section or the two become separate panels.
- **2.4 — the shared panels.** Molecules, catalog and maintenance are reachable from both. A menu in the shell is
  the proposal; the alternative is duplicating them into both sections.

## Phase 3: retire the single page

- **3.1 — decide** (see the decisions) whether `/` was the old page, a redirect, or is removed. Acceptance: no route
  renders all seven tabs, and every old bookmark is either redirected or deliberately refused.
- **3.2 — update the docs** that describe the single page, including this repository's `AGENTS.md` handoff and the
  dashboard skill's own reference.

## Phase 4: the osmotic panel, built inside the validation section

Its reader exists and is tested (`2f6162b`: `GET /api/osmotic/conditions`, one row per molality, the paper's targets
and citation attached, the 0 molal control present and unmeasured). What is missing is the card and the series view.
Build it as a tab of the validation section rather than retrofitting it to a page that is about to change shape.
