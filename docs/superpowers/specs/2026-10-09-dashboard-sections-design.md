# The dashboard's two sections: detergent validation and protein-detergent simulations

**Status:** design, awaiting the decisions listed at the end.
**Date:** 2026-10-09.
**Author:** Hermes Agent, from the user's direction of 2026-10-09.

## The problem

One page carries seven tabs, and they belong to two different kinds of work:

| tab | what it does |
| --- | --- |
| `runs` | every job in one list |
| `new` (Single Molecule Simulations) | an AA→CG run of one molecule, against a mapping |
| `validation` (Mapping Validation) | a mapping against its own reference, and the cross-molecule comparison |
| `pdc` (Protein-Detergent Complex Simulations) | the complex panel: build, queue, and read a multi-component system |
| `mappings` (Bead Assignment) | the CG bead assignment editor |
| `bonded` (CG Bond Interactions) | fitted bond/angle/dihedral terms, and the cross-check |
| `compositions` (Molecule Combination) | combining molecules into a system |

The first, third, fifth, sixth and seventh are about **getting a detergent's model right** — one molecule, or a few, and
whether the coarse-grained representation reproduces the reference. The second and fourth are about **simulating a
protein with detergents** — a different scientific question, a different system size, and a different reader. They are
interleaved in one list, and the run list shows both kinds of job together.

A person opening the dashboard cannot tell which half they are looking at, and someone arriving to look at a
protein-detergent system walks past a bead-assignment editor to find it.

## The goal

The dashboard carries **two large tabs across the top**, one for each workspace, and **the sub-panels of whichever
workspace is active sit in a second row directly beneath them**. Selecting a sub-panel shows that panel below. The
last workspace visited is remembered, so opening the dashboard returns you to where you were working.

There is **no overview page**. An earlier draft put both sections on a landing view as large panels listing their
sub-panels, and the user replaced it after seeing both rendered: the tabs *are* the switch, and nothing stands
between opening the dashboard and working. What the overview was for -- saying what each workspace contains before
you enter it -- the sub-titles on the two big tabs now do in one line each.

The user's words, having compared the two drafts: "Yeah I like this design more."

## The shape, and why it is cheap

The tab machinery is already data-driven. `dashboard/web/static/js/tabs.js` reads the tab list out of the document:

```javascript
// The document is the tab list: the buttons carry role=tab and data-tab, so a tab that is
// added to dashboard.html works without a second list to keep in step.
function tabIds() { return $$('[role=tab][data-tab]').map(tab => tab.dataset.tab); }
```

and `selectTab` already degrades safely when asked for a tab that is not present:

```javascript
const ids = tabIds();
if (!ids.includes(id)) id = ids[0] || 'runs';
```

So **a section is which `[role=tab]` buttons a page renders.** That is the whole mechanism:

- `dashboard.html` renders the section's own tab buttons and only those panels;
- the section is a server-side value, so the page is correct before any JavaScript runs;
- no endpoint changes, no coordinator changes, no second application, no second job store.

**What does not change, deliberately:** the coordinator, the job store, the analysis worker, the 79 existing
endpoints, and every panel's JavaScript. The split is a *view*, and the one job database stays one database —
two stores would make a run's identity ambiguous the moment someone wanted to refer to it from the other section.

**The two sections do not share their panels.** The one exception is a shared *library* — molecules, catalog,
maintenance — and the user decided against sharing even that: each section duplicates it, because the two need
different settings, different defaults and different presets. A single-detergent run has no detergent *count* to
specify; a protein-detergent run cannot be queued without one. That is not a difference in presentation, so the
`new run` form is not one form with a conditional — it is two forms, and they will drift apart on purpose.

## The parts

**The two big tabs**, across the top of every page, in equal halves. Each carries its workspace's name and a
one-line sub-title saying what is in it, because that sentence is what the abandoned overview was for. The active tab
is white against the inactive one's grey, by the same convention the panels already use.

**The sub-tab row**, directly beneath the big tabs inside the same white body, holding the active workspace's
sub-panels with their glyphs. It is rebuilt when the workspace changes, so it never shows a panel that the workspace
does not have. Measured in the draft: seven items under detergent validation, four under protein-detergent, one row
at 1500 px, wrapping rather than overflowing below that.

**The panel** below the row, one at a time, exactly as the dashboard shows a panel today.

**The last workspace visited is remembered**, and here that is load-bearing rather than convenient: with no overview
page there is no neutral landing state to fall back on, so the dashboard must open somewhere. It opens where the
person was.

**The URLs do not change.** The scheme agreed earlier -- `/detergent-validation/new-run` and its siblings -- maps
onto this layout exactly: the section segment is the big tab, the panel segment is the sub-tab. That the design
absorbed a change of chrome without touching its URLs is the sign the scheme was right.

## Which panels go where

| panel | validation | simulations |
| --- | --- | --- |
| `runs` — the job list | yes, its own runs only | yes, its own runs only |
| `new` — queue a run | yes: AA detergent, CG detergent | yes: protein-detergent systems |
| `mappings` — Bead Assignment | yes | no |
| `bonded` — Bond Interactions | yes | no |
| `compositions` — Molecule Combination | yes | no |
| `validation` — Mapping Validation | yes | no |
| **osmotic pressure** | yes — sugar work is detergent work | no |
| **detergent design** (new, future) | yes | no |
| `pdc` — the complex panel | no | yes |
| **set up initial state** (new) | no | yes |
| **future complex analyses** | no | yes |
| molecules, catalog, maintenance | **duplicated**, with its own defaults | **duplicated**, with its own defaults |

**The cross-references between sections.** A protein-detergent run consumes a detergent's mapping and its fitted
terms; the validation section holds the run that produced them. Neither section *opens* the other's runs — a run
belongs to one workspace — but both show **what is used by what**: a complex run states which detergent runs it
draws on, and a detergent run states which complex runs use it. This is provenance, which this repository already
treats as first-class, and it is the one piece of the other section that may appear in yours. It is explicitly not
a picker: a run from the other section must never enter the `new run` form's list of sources.

**The initial-state preview.** The validation section's `new run` sub-panel should show a snapshot of what it is
about to build — the water box with the detergent molecules in it, before anything is integrated. The build already
writes `solvated.gro` and `system.gro`, and the dashboard already renders structures with NGL, so this is a reader
and a viewer rather than new machinery. Feasibility is argued in the plan rather than assumed here.

## The URLs

The user's direction of 2026-10-09 settled this, and it is the decision that closes the "what happens to the old
page" question rather than deferring it:

    /                                        the overview: both sections as panels
    /detergent-validation                    its first sub-panel
    /detergent-validation/runs
    /detergent-validation/new-run
    /detergent-validation/bead-assignment
    /detergent-validation/bond-interactions
    /detergent-validation/combinations
    /detergent-validation/mapping-validation
    /detergent-validation/osmotic-pressure
    /protein-detergent                       its first sub-panel
    /protein-detergent/runs
    /protein-detergent/new-run
    /protein-detergent/complexes
    /protein-detergent/initial-state

**Every sub-panel is addressable.** That is the whole point: the current page hides six of seven panels behind
JavaScript, so a panel has no URL and a bookmark can only name the page. With one URL per panel, a link to the bond
interactions editor is a link to the bond interactions editor.

**The tab becomes a link, and the client keeps it instant.** Today a tab is a button that toggles `hidden`; with
these paths it is an `<a href>`. The page must be correct when that link is followed cold — which is the property
that makes the URL real — and `tabs.js` then intercepts the click and switches in place, so the feel does not change
for someone clicking around. Progressive enhancement, not a single-page app with URLs bolted on.

This also fixes the silent fallback. `selectTab` currently answers a name it does not know with `ids[0]`, which is
why the old bookmark discussion had no good answer: the user would have silently received a different tab. A path
that names a panel the section does not have is now a **404** from the server, which says what happened.

**The section slug is not the section label.** The label is "detergent validation"; the slug is
`detergent-validation`. The user wrote `protein-detergent`, not `protein-detergent-simulations`, so a slug may be
shorter than its label — the registry carries both and nothing derives one from the other.

**The old page.** `/` becomes the overview, and an old link of the form `/<panel>` or a saved `#tab` is answered by
the browser rather than the server, because a fragment is never sent to a server. A short redirect on the overview
maps a known old tab name to its new path; an unknown one lands on the overview, which is a page that at least
explains where things are. No third "everything" view, and nothing silently substituted.

## The risks, each with what it costs

**The navigation is new chrome, not a moved panel.** This is the one part of the refactor that is not relocating
existing markup. `layout.css` styles `nav[role=tablist]` as a vertical sidebar inside a two-column `.app-shell`
grid, at three breakpoints, and it was moved to the right of the content recently. A two-level top bar is a
different piece of chrome: the grid, the rail, its breakpoint rules and the tab-link styling all change, while the
panels themselves do not.

**And specificity is the trap in exactly that work.** The draft's first render had the two big tabs stacked in a
column rather than side by side, because `nav[role=tablist]` outranks a bare class and the draft's `display: flex`
never applied — `dashboard.css` and `layout.css` both set `max-width` on `main`, and the rail's rules win over a
later stylesheet unless the override carries an equal-or-higher anchor. Measured: y=211 against y=276 before the fix,
y=205 for both after. Anyone restyling that navigation should expect this and write the override with the anchor it
needs, or measure the boxes rather than trusting the appearance.

**The browser tier is the real hazard.** 54 browser tests, one skipped, drive the current single page; a test that
opens the dashboard and clicks a tab will find neither the tab nor the page it was on. Every one of them needs to know
which section it belongs to. This is the largest single piece of the work and it is not optional — a refactor that
lands with a red browser tier has not landed.

**Deep links cross the boundary.** `main.js` wires the run card's actions to tabs inside the current page:

```javascript
onValidate: id => { selectTab('validation'); return validation.open(id); },
openBondedModel: model => { selectTab('bonded'); return mappings.openBondedModel(model); },
```

With sections, a run shown in the *simulations* list whose mapping is worth validating must now *navigate* to the
validation section rather than switch a tab in place. Those links are the ones D1 built and they are pinned by
tests; the plan must keep them working across the split, and the tests must be updated deliberately rather than
deleted.

**The hash and the remembered tab are per-page.** `selectTab` writes `#tab` and `localStorage.tab`. Because it falls
back to `ids[0]` when the name is unknown, a stale value from the other section resolves to that section's first tab
rather than to a blank page — it works, but it means switching sections silently forgets which tab you were on. Making
the remembered tab per-section is a small change and worth doing.

**The narrow-window rail.** At 900 px and below the tablist is a horizontal row; the section switcher is a third
thing on that row. It needs to fit, and that is a CSS task with a browser test rather than a hope.

## Alternatives considered and rejected

**Two Flask applications on two ports.** Two coordinators, two job stores, and a run that exists in one and not the
other. Rejected: the job store is the identity of a run.

**Prefixing the API by section** (`/api/validation/jobs`). 79 endpoints churned for a view split, and a run would
have a different URL depending on which page asked about it. Rejected.

**A client-side-only split** (one page, JavaScript hides tabs). The page would be wrong until JavaScript ran, the
landing would be a lie about what the page contains, and every existing test would be testing the hidden version.
Rejected.

**A third top-level "tools" section** for the shared panels. It adds a section to hold three pages that both
sections need anyway. Rejected for now; the shared entries can be a menu in the shell.

## Migration order

1. **The landing and the shell**, with the tablists scoped by section and every panel still reachable — the split
   made structural before anything moves.
2. **The panels regrouped** to match the proposal above, and the run lists filtered by section.
3. **The remembered tab made per-section**, and the cross-section links converted from tab switches to navigation.
4. **The browser tier** re-pointed section by section, which is what proves 1–3.
5. **The osmotic panel**, built fresh inside the validation section rather than retrofitted — its reader exists and
   is tested (`2f6162b`); it needs a card and a series view, not a move.

Each step commits on its own and leaves the suite green, so the refactor can stop after any of them.

## The decisions, and where they stand

**Decided by the user on 2026-10-09:**

1. **The section names stay** — "detergent validation" and "protein-detergent simulations". The user's reason: a
   name is very easy to change later, so it is not worth spending the decision on now.

2. **Validation holds the whole detergent workflow**, not only its comparisons: full-atom detergent runs,
   coarse-grained detergent runs, CG bead mapping, CG interaction parameterisation, detergent design, and its own
   runs and new-run settings. "Detergent design" does not exist yet and is a panel this section will grow.

3. **The overview is two large panels, not two buttons** — each showing its sub-panels, so the page says what is
   behind each door. The last section opened is **remembered**, and the shell carries a **switch** to the other
   section so nobody has to go back to the overview to cross.

4. **The run lists are filtered by section** — the validation list shows no protein-related run and the simulations
   list shows no detergent-only run. **But both show the cross-references**: which detergent runs a complex run
   draws on, and which complex runs a detergent run is used by.

5. **A run may not be opened from the other section.** Both sections still *know* about the other's runs — that is
   what the cross-reference in (4) is — but a run from the other section must not appear in the `new run` form's
   list of sources.

6. **The shared panels are duplicated, not shared.** Molecules, catalog and maintenance appear in both sections,
   with their own settings, defaults and presets, because the two workflows differ in ways that are not
   presentational: a single-detergent run has no detergent *count* to give, and a protein-detergent run cannot be
   queued without one.

7. **"Set up initial state" is the micelle builder** — the work that is paused, with `micelle/` a partial skeleton
   and explicitly not a validated model. It belongs to the simulations section. Separately, and in the *validation*
   section's `new run` sub-panel, the user wants **a snapshot of the initial state** — the water box with the
   detergent in it — before the run starts. That is not the micelle builder and is not blocked by it.

8. **Settled: today's single page is dissolved, not preserved.** The user's answer was a URL scheme — one path per
   sub-panel, `dashboard/detergent-validation/new-run` and its siblings — and that answer is better than the three
   options the design had considered, because it removes the premise of the question. There is no "old page" to
   retire if every panel it contained has its own address; the page was only ever a container. See **The URLs**
   above for the scheme and the consequences.

   The reasoning is kept here because it applies to any future page without a URL. Today `/` holds seven tabs and
   three things depend on it: 54 browser tests that open it and click in it, bookmarks whose fragment `selectTab`
   wrote into the URL, and the run card's tab jumps, which work only because one page holds every panel. The options
   were a redirect into the remembered section, keeping the old page as an unlinked "everything" view, or removing
   it. The middle one was a false economy — it preserves a page whose premise the refactor rejects. Addressable
   panels make the first and third collapse into the same thing: nothing is lost, because nothing was ever stored
   on that page except the fact that all seven panels were reachable from it.

9. **The osmotic series lives in validation**, by the user's reasoning that it is sugar work and sugars are
   detergent work.
