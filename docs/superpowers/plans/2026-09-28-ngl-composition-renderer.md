# NGL replaces plotly in the Molecule Combination panel

Status: scoped, not written. Opened after the decision that the endpoint comboboxes own the linkage choice, so
the bead picker has no job and plotly's only advantage in this panel is gone with it.

## What is already in place

- `dashboard/web/static/vendor/ngl.js` — NGL 2.3.1, tracked, 1,283,924 bytes, sha256 `0e8fea984b0e306d…dc5d`,
  with `ngl.js.source.json` beside it (commit `48408cf`). Loads as a UMD bundle with a plain script tag.
- The preview response carries `pdb` — one HETATM per bead at the joined geometry, Angstrom, CONECT bonds, and
  a `REMARK 950 BEAD <name> <type> <size> <fragment>` line per bead (commits `6bb482f`, `b3b9932`, `57eca8a`).
- The panel draws each fragment by id, so the cards can move without touching javascript.

## The unit

One coherent change; the picker removal and the renderer swap land together, because either alone leaves dead
interaction or a dead renderer on screen.

1. `dashboard/web/templates/dashboard.html:11` — add
   `<script src="{{ url_for('static', filename='vendor/ngl.js') }}"></script>` beside the plotly tag. Static
   files already go through Flask's own static route, so **no new route is needed**; the plotly route exists
   only because plotly lives inside its installed package. Add the tag here rather than earlier: on its own it
   loads 1.25 MB per page for nothing.
2. `dashboard/web/static/js/compositions.js` — delete `chooseEndpoint` (lines 22–31) and the
   `onBeadSelection: names => chooseEndpoint(key, names)` wiring inside `plotFor` (lines 14–19); delete the
   now-unused `mountBondedPlot` import (line 2). The endpoint dropdowns and `syncEndpoints` (line 56) are
   independent of both and stay.
3. Same file — replace `plotFor` with `stageFor(key)`, creating one NGL stage per panel element on first use
   (`new NGL.Stage($('#composition-plot-' + key), {backgroundColor: 'white'})`, kept in the existing `plots`
   map), and rewrite the render loop in `paint()` (line 36) to load `result.pdb` into each stage:
   `stage.loadFile(new Blob([pdb], {type: 'text/plain'}), {ext: 'pdb'})` then `addRepresentation('ball+stick', …)`.
   Keep `#composition-geometry-basis` and the diagnostics path untouched.
4. `dashboard/web/static/compositions.css` — `.composition-plot` keeps its box and border but the fixed
   `.composition-plots .composition-plot{height:380px}` / `.composition-plot-joined{height:440px}` become
   viewer canvases (NGL needs a sized container; it does not size to content).
5. `tests/dashboard/browser/test_composition_geometry_browser.py` — rewrite the accessors, not the claims. It
   currently reads plotly traces (`el.data`, `.filter(trace => trace.meta === 'bead')`, `EDGE_POINTS`) and
   asserts `.plotly` is visible. The claims to preserve: the endpoint bead is the linkage colour in each
   fragment, no virtual site is drawn, the edge counts per panel, and the endpoint values the comboboxes hold.

## Design decisions this unit has to settle

- **A test-visible handle.** NGL stages are module-scoped, so a browser test cannot reach them. Expose them on
  the panel element (`host.compositionStages = {...}`) and assert against that: component count, atom count,
  and the bead names from the loaded structure. Document it as the panel's test seam, not as a public API.
- **Sphere radii.** NGL's `ball+stick` uses per-element van der Waals radii; the Martini classes are 0.264 /
  0.230 / 0.191 nm for R / S / T, whose ratios (1 : 0.87 : 0.72) do **not** match vdW C/N/O (1 : 0.91 : 0.89).
  The element mapping in `render_pdb` (R→C, S→N, T→O) gets the ordering right but not the proportion, so either
  a per-class radius override or a documented, measured `radiusScale` is needed. Measure the drawn ratio; do not
  assume.
- **Colour by type.** The `REMARK 950 BEAD` lines exist so the viewer can colour by bead type rather than by
  element. Decide whether the panel does that now or after the swap lands.

## Verification

- `dashboard/.venv/bin/python -m pytest tests/dashboard/browser/test_composition_geometry_browser.py -q -n 0`
- the fast tier (`-m 'not browser and not slow'`) and `ruff check dashboard tests --select F,E9,I`
- a live look: the three panels must render beads, not empty canvases. Screenshots of the running app have
  timed out before, so measure (`canvas` size, component count) if the capture fails.
- **Stage explicitly** (`git add <paths>`), never `git add -A`: `vendor/ngl.js` is a 1.25 MB blob and being
  swept into an unrelated commit has already happened once.
