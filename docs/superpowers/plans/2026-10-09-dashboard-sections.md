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

### Task 1.2: The overview

**Objective:** `/` shows both sections as large panels, each with its own sub-panels listed, and nothing else.

**Files:**
- Create: `dashboard/web/templates/overview.html`
- Create: `dashboard/web/routes/home.py` (registered in `dashboard/app.py`'s `for module in (...)` tuple)
- Test: `tests/dashboard/integration/test_overview.py`

**Step 1: Write the failing test**

```python
def test_the_overview_offers_both_sections_and_no_tabs(dashboard):
    with dashboard.client as c:
        page = c.get('/')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'Detergent validation' in body
    assert 'Protein-detergent simulations' in body
    assert '/validation' in body and '/simulations' in body
    assert 'role="tab"' not in body, 'the overview is a map, not a workspace'


def test_each_section_panel_lists_that_section_own_sub_panels(dashboard):
    """The panel says what is behind the door -- that is the whole reason it replaced two buttons."""
    with dashboard.client as c:
        body = c.get('/').get_data(as_text=True)
    assert 'Bond Interactions' in body, 'a validation sub-panel'
    assert 'Complex' in body, 'a simulations sub-panel'
    # and nothing from the wrong side is listed under the wrong panel -- assert on the markup around each heading


def test_each_section_is_reachable_from_the_overview(dashboard):
    with dashboard.client as c:
        for path in ('/validation', '/simulations'):
            assert c.get(path).status_code == 200
```

**Step 2: Run it to verify it fails**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_overview.py -q`
Expected: FAIL — `/` renders the whole workspace today, so the `role="tab"` assertion fails first.

**Step 3: Write the overview template and route**

`overview.html` renders, for each section in `SECTIONS`, one large panel carrying the section's label and blurb and a
list of its sub-panels, each a link into the section. The panel's list is built from `SECTIONS[name]['tabs']`, so a
tab added to a section appears on the overview without a second list to keep in step — the same property that makes
the split cheap in the first place. Each panel's heading is itself a link to the section workspace.

**Step 4: Run it to verify it passes**

Run: `dashboard/.venv/bin/python -m pytest tests/dashboard/integration/test_overview.py -q`
Expected: PASS. Record the count.

**Step 5: Commit**

```bash
git add dashboard/web/routes/home.py dashboard/web/templates/overview.html dashboard/app.py tests/dashboard/integration/test_overview.py
git commit -m "feat: the dashboard opens on a map -- two sections, their sub-panels, and no workspace behind it"
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

### Task 1.5: The switch, and both kinds of remembering

**Objective:** nobody is stranded in a section, the section you were last in is where the dashboard opens, and
switching does not forget which tab you were on.

**Files:**
- Modify: `dashboard/web/templates/dashboard.html` (the shell's header)
- Modify: `dashboard/web/static/js/tabs.js`
- Test: `tests/dashboard/browser/`

The user's decision on 2026-10-09 replaced "always show the overview" with **remember the last section opened**, and
added that the shell must carry **a button to switch to the other section** so crossing never requires a trip
through the overview.

**Step 1: The switch.** In the shell's header, a link labelled with the *other* section's name, plus a link home to
the overview. A person in the wrong section should see where the other one is without going home first.

**Step 2: The section is remembered.** The overview route cannot know what the browser remembers — the section lives
in `localStorage` on the client — so this is a client-side decision made as early as possible: the shell reads the
remembered section and, if the page it was served is not that section, navigates. Read `tabs.js` before writing
this; it already writes `#tab` and one `localStorage` key, and the same `storage` helper is where this belongs.
Handle the no-preference case by serving the overview, which is what a first visit should get.

**Step 3: The tab is remembered per section.** Key the remembered tab by section, `storage.set('tab:' + section, id)`.
`selectTab` already falls back to the first tab it finds, so the old unkeyed value degrades safely and needs no
migration.

**Step 4: Run the browser tier, and hard-reload.**

The skill's rule applies twice over here: a running dashboard freezes Python and models at process start, so
**restart after the route change**, while templates and static files are re-read per request, so a **hard reload**
picks up the template and JS edits. A stale page will make this task look broken when it is not.

Run: `dashboard/.venv/bin/python -m pytest -m browser -q -n 2`
Expected: record the counts.

**Step 5: Commit**

```bash
git add dashboard/web/templates/dashboard.html dashboard/web/static/js/tabs.js tests/dashboard/browser/
git commit -m "feat: a way across, and both the section and the tab remembered"
```

---

## Phase 2: the panels regroup, and the run lists diverge

Named now, detailed when Phase 1 has landed and the decisions are settled. The user's answers on 2026-10-09 shaped
this list directly, and two of them changed it from what the design first proposed.

- **2.1 — the run list filtered per section.** The validation list must show no protein-related run and the
  simulations list no detergent-only run. Acceptance: a search of the two lists finds no run of the other kind, and
  the filter is done from the job store's own run-type vocabulary, not from a suffix guess on the label.

- **2.2 — the cross-references (new, from decision 4).** Each run shows **what it draws on and what uses it**: a
  complex run names the detergent runs whose mapping and fitted terms it consumed, and a detergent run names the
  complex runs that use it. This is provenance and the repository already treats it as first-class, so the first
  step is to *find out whether the link is already in the records* — the complex pipeline queues with a mapping and
  a solute root, so it may be, in which case this is a reader; if it is not, this task starts by recording it.
  Acceptance: both directions are visible from the run's own entry, and neither is a picker.

- **2.3 — a run's actions stay inside its own section (decision 5).** `main.js` wires a run card's actions to
  `selectTab('validation')` and `selectTab('bonded')` in place. Inside the validation section that is still correct;
  from the simulations list it would be a jump into a workspace that does not own the run. Audit every such wiring
  and make each one either stay in its section or link to the run's own entry. Acceptance: no control in either
  section opens a run belonging to the other, and the tests that pin those links assert that.

- **2.4 — two `new run` forms, not one (decision 6).** Molecules, catalog and maintenance are **duplicated** into
  both sections with their own settings, defaults and presets, because the workflows differ in substance: a
  single-detergent run has no detergent *count*, and a protein-detergent run cannot be queued without one. The
  duplication is deliberate and the two forms are expected to drift; what must not drift is the service behind them,
  which stays one implementation with two sets of default values.

- **2.5 — the initial-state preview (decision 7).** A snapshot of what a run is about to build, in the validation
  section's `new run` sub-panel: the water box with the detergent in it, before anything is integrated. Feasible
  without new machinery — the build already writes `solvated.gro` and `system.gro` at prepare time, which is
  *before* the run is queued, and the dashboard already renders structures with NGL. Acceptance: a prepared,
  unqueued run shows its box, and the viewer is the same one the mapping overlay uses rather than a second one.

- **2.6 — detergent design (decision 2).** A panel this section will grow, named by the user as part of what
  validation holds. Nothing is designed here yet; it is recorded so the section's shape accounts for it.

## Phase 3: retire the single page

- **3.1 — decide** (open decision 8 in the design) what `/` does with the old content. Acceptance: no route renders
  all seven tabs, and every old bookmark is either redirected or deliberately refused.
- **3.2 — update the docs** that describe the single page, including this repository's `AGENTS.md` handoff and the
  dashboard skill's own reference.

## Phase 4: the osmotic panel, built inside the validation section

Its reader exists and is tested (`2f6162b`: `GET /api/osmotic/conditions`, one row per molality, the paper's targets
and citation attached, the 0 molal control present and unmeasured). What is missing is the card and the series view.
Build it as a tab of the validation section rather than retrofitting it to a page that is about to change shape.
