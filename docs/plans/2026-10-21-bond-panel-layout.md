# CG Bond Interactions: a two-column model card, and Job beside Result

> **For Hermes:** implement with `subagent-driven-development` or task by task; the browser tier is the acceptance.

**Goal:** the panel's inputs read in three rows instead of four, the torsion fieldset sits to their right rather than
under them, and the Job and Result cards share one row at half width each.

**Why:** seven fields in a two-column grid take four rows of vertical space before the first button, and the torsion
fieldset — a *property of the mapping*, read and written beside those fields — is stacked below them, so the card is
about 700 px tall before a fit is queued. Job and Result are each a badge, a line of detail and a few rows: at full
width they are mostly empty, and stacking them pushes the interactions table off-screen while a fit is running.

**Where the markup is:** `dashboard/web/templates/dashboard.html`
* `section.card.bonded-model` — the model card, lines 626-666. Fields: `.form-grid.bonded-model-fields`, lines 634-645
  (Mapping, AA reference, Fit with, Constraint threshold, Fit temperature, Torsion model, Torsion stiffness scale).
  The torsion fieldset: `fieldset.bonded-torsion`, lines 648-653. Then the toolbar (Fit / Delete), `#bonded-fit-status`,
  and `.notice.bonded-help`.
* `section.card.bonded-job#bonded-job` — lines 667-681, and `section.card.bonded-result#bonded-result` — lines 683-693.
  They are adjacent siblings, both `hidden` until the panel has something to show, and both precede `.bonded-columns`
  (interactions + connectivity).

**Current CSS:** `dashboard/web/static/dashboard.css` line 1 has `.form-grid{display:grid;grid-template-columns:1fr 1fr;
gap:18px}`, collapsing to one column at `max-width:520px`. There is no rule for the job/result pair; both are ordinary
`.card` blocks.

---

### Task 1: the model card becomes two columns, its fields three

**Files:** modify `dashboard/web/templates/dashboard.html:634-653`, `dashboard/web/static/dashboard.css` (append a
`bonded-model` block; the file is one minified line — append rather than edit inside it).

**Step 1 — markup.** Wrap the fields and the fieldset in one grid so they are siblings:

```html
<div class="bonded-model-body">
  <div class="form-grid bonded-model-fields">
    <label>Mapping<select id="bonded-mapping-select" …></select></label>
    <label>AA reference<select id="bonded-aa-reference" …></select></label>
    <label>Fit with<select id="bonded-engine" …></select></label>
    <label>Constraint threshold …</label>
    <label>Fit temperature …</label>
    <label>Torsion model<select id="bonded-torsion-model" …>…</select></label>
    <label class="bonded-scale-field">Torsion stiffness scale<input id="bonded-torsion-scale" …></label>
  </div>
  <fieldset class="bonded-torsion">…</fieldset>
</div>
```

Two facts to keep: the ids do not move (every one is read by `bonded-parameterization.js`), and `#bonded-aa-facts` /
`#bonded-engine-note` stay *outside* the grid — they are per-field notes that would otherwise land in a cell and push
the rows around when empty.

**Step 2 — CSS.**

```css
.bonded-model-body{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(300px,1fr);gap:20px;align-items:start}
.bonded-model-fields{grid-template-columns:repeat(3,minmax(0,1fr))}
.bonded-model-fields .bonded-scale-field{grid-column:1}
.bonded-torsion{margin:0;height:100%}
@media (max-width:1100px){.bonded-model-body{grid-template-columns:1fr}}
@media (max-width:760px){.bonded-model-fields{grid-template-columns:1fr 1fr}}
```

`minmax(0,…)` on every track matters: a `<select>` whose option text is long otherwise sets the track's min-content
width and the card overflows the page — the same class of bug as `.hint` without `overflow-wrap`.

**Step 3 — the browser assertion.** Add to `tests/dashboard/browser/test_bonded_parameterization_browser.py`, on the
page that already selects a mapping:

```python
fields = page.locator('.bonded-model-fields')
torsion = page.locator('fieldset.bonded-torsion')
assert torsion.bounding_box()['x'] > fields.bounding_box()['x'] + fields.bounding_box()['width'] - 1
# three per row: the fourth field starts a new row
boxes = [page.locator('.bonded-model-fields > label').nth(i).bounding_box() for i in range(4)]
assert boxes[3]['y'] > boxes[0]['y'] + 10
assert abs(boxes[0]['y'] - boxes[2]['y']) < 2
assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
```

The last line is not decoration: it is the assertion that caught the `.hint` overflow on 2026-10-21.

**Step 4 — run it.** `dashboard/.venv/bin/python -m pytest -m browser -q -n 0 -k bonded_parameterization` → the new
assertions pass, the existing panel tests still pass (they address ids and text, not positions).

**Step 5 — commit** `feat(bonded): the model card is two columns and its fields three`.

---

### Task 2: Job and Result share a row

**Files:** `dashboard/web/templates/dashboard.html:667-693`; `dashboard.css`.

**Step 1 — wrap them** (no other change; both keep `hidden` until the panel fills them):

```html
<div class="bonded-run-cards">
  <section class="card bonded-job" id="bonded-job" …>…</section>
  <section class="card bonded-result" id="bonded-result" …>…</section>
</div>
```

**Step 2 — CSS.**

```css
.bonded-run-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;align-items:start}
.bonded-run-cards > .card{margin:0}
@media (max-width:1000px){.bonded-run-cards{grid-template-columns:1fr}}
```

`align-items:start` is the point: the job card grows when its log opens, and the result card must not stretch to match
an empty box. `[hidden]` already wins over `display:grid` (`dashboard.css` has `[hidden]{display:none!important}`), so a
hidden card does not leave a hole.

**Step 3 — assertion.** In the same browser file, on the test that queues a fit (it stubs the job response):

```python
job, result = page.locator('#bonded-job'), page.locator('#bonded-result')
jb, rb = job.bounding_box(), result.bounding_box()
assert abs(jb['y'] - rb['y']) < 2, 'the two cards sit in one row'
assert jb['width'] < page.evaluate('innerWidth') * 0.5 and rb['width'] < page.evaluate('innerWidth') * 0.5
```

**Step 4 — run** the same `-k bonded_parameterization` selection, then the full browser tier (`-n 16 --dist worksteal`,
236 today) because the card grid sits above two other panels' scroll positions.

**Step 5 — commit** `feat(bonded): Job and Result sit side by side`.

---

### Task 3: docs

`docs/PROJECT_GUIDE.md` §"CG Bond Interactions" gains one sentence on the layout (model card two columns: fields then
torsion; Job and Result in one row); `AGENTS.md` needs nothing — this is presentation, not contract. Record the new
browser assertions in the commit message, not in AGENTS.

**Acceptance:** the panel's model card is under ~430 px tall before a fit is queued; Job and Result are each half-width
in one row above the interactions table; no horizontal overflow at 1280 px; browser tier green.

**Draft to look at:** `docs/design/drafts/bond-interactions-layout.html`.
