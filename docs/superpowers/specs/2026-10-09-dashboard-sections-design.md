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

The dashboard opens on an **overview showing both sections as large panels**, each listing that section's own
sub-panels. Clicking into one leads to that section's workspace. The **last section opened is remembered**, so the
dashboard opens where the person was working, and the shell carries a **button to switch to the other section** —
a person should never have to go back to the overview to get across.

Two buttons were the original proposal and the user replaced them: two panels, each with its sub-panels visible,
tells someone what is behind the door before they open it.

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

**The overview** at `/`. Both sections as large panels, each showing its own sub-panels as labelled entries, so the
page states what is behind each door before anyone opens it. The overview is where a first-time reader learns there
are two halves.

**Two section workspaces**, `/validation` and `/simulations`. Each renders the existing shell with a section-scoped
tab list and the panels that section owns. Each carries a **switch** to the other section, and `/` is always one
click away — but the last section opened is **remembered**, so opening the dashboard returns you there rather than
to the overview every time.

**Section membership**, as decided:

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

## The risks, each with what it costs

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

8. **Still open: what happens to today's single page.** See the elaboration below; the question is what `/` should
   have to say once the overview exists.

9. **The osmotic series lives in validation**, by the user's reasoning that it is sugar work and sugars are
   detergent work.

### Open decision 8, elaborated

Today `/` renders the whole dashboard: seven tabs, all panels, one page. After this change `/` is the overview, and
that page needs a destination. The question is not cosmetic, because something currently depends on the old page
existing:

- **The old page is the only page the browser tier knows.** 54 tests open `/` and click tabs in it. Whatever happens
  to `/`, they must point somewhere real.
- **Bookmarks and the remembered tab point at it.** `selectTab` writes `#tab` into the URL, so a link someone saved
  is `/` plus a tab name.
- **The tabs cross section boundaries freely today.** A run card in the job list switches to the validation tab in
  place. That is only possible because one page holds every panel, and it is precisely what the split removes.

Three destinations are possible, and they are not equivalent:

- **A redirect from `/` to the remembered section**, so an old bookmark lands in a workspace. Simple, but a
  bookmarked `#bonded` in someone who last used the simulations section lands where that tab does not exist —
  `selectTab` would fall back to the section's first tab, silently.
- **Keeping the old page as a third "everything" view**, reachable but not linked. Nothing breaks, but the
  two-section structure stops being true: anyone can still see all seven tabs at once and the split becomes a
  preference rather than the shape of the tool.
- **Removing it**, so the only way in is the overview — the strictest reading of the two-section design, and the one
  that makes the structure real at the cost of surprising anyone with an old bookmark.

My own view: the second is a false economy (it preserves a page whose premise the refactor rejects), and the first
and third differ mainly in how loudly an old link fails. I would take the first with the fallback made *visible* —
landing in a section and being told the tab you asked for is in the other one, rather than silently getting a
different tab. But this is the user's call, and it is genuinely their call: it is about how the tool should behave
for someone who has used it for a year.
