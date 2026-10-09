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

The dashboard opens on a **landing view with two large buttons**. One leads to the **detergent validation** section,
one to the **protein-detergent simulations** section. Each section has its own tabs, its own run list, and only the
panels that belong to it.

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

## The parts

**The landing** at `/`. Two buttons, each a link to a section. It carries no tab list and no panels; it is a fork in
the road. It should say, in a line each, what the two sections are for, because a two-button page with no explanation
is a guess.

**Two section pages**, `/validation` and `/simulations` (names to be decided — see the decisions). Each renders the
existing shell with a section-scoped tab list and the panels that section owns. A **section switcher** in the shell
returns to the landing, so nobody is stranded.

**Section membership**, as a first proposal:

| panel | validation | simulations |
| --- | --- | --- |
| `runs` — the job list | yes, filtered to its own run types | yes, filtered |
| `new` — queue a run | yes: Single Molecule Simulations | yes: the complex pipeline's own launch |
| `mappings` — Bead Assignment | yes | no |
| `bonded` — Bond Interactions | yes | no |
| `compositions` — Molecule Combination | yes | no |
| `validation` — Mapping Validation | yes | no |
| `pdc` — the complex panel | no | yes |
| **set up initial state** (new, future) | no | yes |
| **future complex analyses** | no | yes |
| **osmotic pressure** (new, built this week) | yes — it is a molecule against a paper | no |
| molecules, catalog, maintenance | shared — see the decisions | shared |

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

## The decisions this needs from you

Listed in full in the reply; recorded here so the spec stands alone:

- what the two sections are called, and whether "validation" is the right word for a section that contains a
  single-molecule *simulation*;
- whether the detergent-validation section should hold *only* comparisons against a reference and a paper, or the
  whole single-molecule workflow including the runs that produce them;
- what the landing does on a second visit — always shown, or remembering the last section;
- which panels are shared and how they are reached from both sections;
- how the run list is scoped: filtered per section, or one list that shows both with a section column;
- what "set up initial state" means for the complex section today, given the micelle builder is paused;
- whether a run that belongs to one section may be opened from the other;
- how the existing single page is retired — redirected, kept as a third "everything" view, or removed;
- and where the osmotic series lives, on the assumption above that it is validation.
