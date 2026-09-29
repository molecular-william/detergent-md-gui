# Tab organisation and one content width — design note

Measured on the live dashboard, 2026-09-29, viewport 1280 px, seven tabs.

## The two things that are actually wrong

1. **The tab bar already overflows.** The seven buttons need 1674 px inside a 1217 px `nav`, so the row scrolls
   horizontally and the last tab is cut off. Nothing about that is a future risk; it is a scrollbar under the
   tabs today, and every surface added makes it worse. The widths are ragged because the labels are not the same
   kind of thing — "Runs" 92 px against "Single Molecule Simulations" 288 px.

2. **Every panel is the same width; their content is not distributed the same way.** All seven panels' outer
   containers measure 1217 px. What differs is inside:

   | panel | box | content |
   | --- | --- | --- |
   | Runs | 1217 | table 1320 px — wider than the box, scrolls sideways, columns stretched across |
   | Single Molecule Simulations | 1217 | form in two columns 627 + 570, settings grid 540 |
   | CG Bead Assignment | 1217 | editor 1167 = 1.4fr + a 448 px minimum column |
   | CG Bond Interactions | 1217 | two columns 1fr + 1fr |
   | Mapping Validation | 1217 | cards 1217, tables 1167 |
   | Molecule Combination | 1217 | workspace 1217 with a 340 px sidebar |
   | Protein–Detergent Complex | 1217 | 339 px setup + 859 px view |

   So "Runs uses more horizontal space" is true to the eye and false to the ruler: Runs' content fills its box
   edge to edge, and the others sit in sub-columns of 340–860 px with empty space around them. The fix is not to
   widen the panels. It is to give every panel one content measure and let each workspace place its pieces on it.

## Recommendation

**Take both, but take them separately** — one is a CSS consolidation, the other is a navigation change, and
each has its own reversal cost.

### 1. One content grid, every panel

One row of rules at the top of the content area, and every card or workspace spans a whole number of columns of
it: the table spans all 12, a form spans 8 with its review panel on 4, a two-pane workspace is 8 + 4, a sidebar
is 3 + 9. The `Runs` filtering card is already this shape, which is why it reads as the widest panel — it
becomes the template rather than the exception.

What this replaces: the per-workspace minima (`minmax(448px, 1fr)`, `minmax(240px, 0.85fr)`, `minmax(420px,
2.15fr)`, the 340 px sidebar) that were each chosen in isolation.

Reversal cost: a stylesheet block and one class per panel container. No markup structure changes.

### 2. Vertical rail, collapsible, with the horizontal bar as the small-screen fallback

A left rail fixes the overflow by construction and scales to the tabs that are still coming (E4/E5 add surfaces,
the PDC panel has two more phases behind it). Two things have to be true for it to be an improvement rather than
a loss:

- **It collapses.** At < 1100 px the rail becomes icon + short label (or icon only), because 200 px taken from
  the run table is 200 px taken from the one panel that wants them. The toggle state belongs in the same
  `storage` the tab selection already uses.
- **The labels are regrouped and shortened.** Two groups, with a separator: the model-building tabs (CG Bead
  Assignment, CG Bond Interactions, Molecule Combination) and the run-and-read tabs (Runs, Single Molecule
  Simulations, Mapping Validation, Protein–Detergent Complex). "Single Molecule Simulations" is a sentence; the
  rail has room for it, but "Simulate" is what the group header makes unambiguous.

Keyboard: `tabs.js` handles Left/Right/Home/End today. A vertical tablist needs `aria-orientation="vertical"`
and Up/Down, and `tabs.js` derives the tab list from the DOM so nothing else changes.

Costs, stated: the rail takes 200 px of content width on a 1280 px viewport unless it collapses; the run table
already scrolls sideways inside its card at 1320 px of content, and the rail makes that a little worse until the
table itself is denser (method folded into molecule, duration into created) — a separate, optional item.

Reversal cost: the markup is one `nav` moved inside a wrapper element, plus a breakpoint. The tab logic does not
change, because the tab list is read from the DOM.

## As built (2026-09-29)

`static/layout.css`, loaded last so the measure wins over each workspace's own minima, plus the rail markup in
`dashboard.html` and `aria-orientation` with both arrow-key pairs in `tabs.js`.

Three decisions made while building, against the draft:

- **The form's columns are 6 + 6, not 8 + 4.** At a 1280 px window the rail leaves a 997 px measure, so a
  four-column settings panel is 319 px and its three-across fields wrap — "AA NVT equilibration (ps)" over three
  lines, with the inputs squeezed beside the Default buttons. Six and six gives 489 px each, which is what the
  fields had at their old 540 px. The Mapping editor's columns went 7 + 5 for the same reason.
- **The rail compacts through the stylesheet, not a toggle**: 220 px, 64 px below 1100 px, and the horizontal row
  below 900 px. A toggle would be a second piece of state to keep in step with the CSS, and `tabs.js` already has
  to follow the breakpoint to set `aria-orientation` for assistive technology.
- **RUN AND READ comes first**, so the landing tab is the top entry and the groups run from "look at runs" to
  "design a model"; the draft showed BUILD A MODEL first.

The tab order is therefore runs, simulate, validation, complexes, bead assignment, bond interactions,
combinations. One existing test used `ArrowRight` from the second tab to reach the mappings panel; it now clicks
the tab and says why, and the arrow keys are covered in the layout test, where the order is the rail's own.

## What I would not do

- **Wrap the tabs onto two rows.** It costs no width and looks like an accident at the eighth tab; the rail does
  the same job and holds a group structure.
- **A "More" overflow menu.** Seven primary views behind a menu is a discoverability regression, and the
  selector rows inside the panels already depend on knowing where things live.
- **Shrinking the type to fit.** The labels are 15 px on a 1217 px bar; making them 13 px buys one more tab and
  costs legibility on every screen for the sake of a layout that is already out of room.

## Draft

`docs/design/prototypes/dashboard-tabs-20260929.html` — a static draft with the measured widths recreated: the
current bar with its overflow, the rail collapsed and expanded, and three panel stubs (the run table, a
form-plus-review panel, a two-pane workspace) laid out on the one grid so the widths can be compared directly.
