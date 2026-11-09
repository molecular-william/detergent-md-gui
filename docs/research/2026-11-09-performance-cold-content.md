# Cold first content of the dashboard panels: measurements, loading-state audit, and a minimal proposal

Lane A (slice A) of `docs/plans/2026-11-09-performance-follow-up.md`. Evidence gathered 2026-11-09 against the live
dashboard at `http://127.0.0.1:5000` (GET only; nothing restarted, stopped, or written) and read from the working tree
at that moment. No tracked file was edited; this file is the lane's one artifact. Measurement scripts lived under
`/tmp` and are not committed.

Two other lanes were editing `shared.js`, `runs.js` and `run-view-analysis.js` while this was measured, so the
line numbers below describe the working tree as it stood at 13:09-13:20 local time, not `HEAD`.

## 1. How it was measured

- `.venv/bin/python` + Playwright (`chromium-1217`), headless, viewport 1440x1000, against the live dashboard.
- **Cold**: a fresh browser context per panel, `Network.setCacheDisabled(true)`, one navigation straight to the panel's
  URL (`/detergent-validation/<panel>`), so the shell's own boot is inside the window.
- **First useful content** is an in-page predicate polled every 25 ms; the reported number is `performance.now()` when
  it first held, i.e. milliseconds from navigation commit. No wall-clock threshold is asserted anywhere.
- **Warm**: the same URL loaded a second time in the same cache-enabled context (the first load warms HTTP cache and
  the module registry).
- Requests and bytes are response events for that navigation; bytes are `content-length` (the body the server states,
  not wire bytes after compression). API paths are grouped in §3.
- Every number is one sample on a Werkzeug dev server in headless Chromium. Small differences are noise; only the
  order-of-magnitude and request-identity facts below are relied on.

### Panel content predicates (the DOM checks used)

| Panel | Predicate |
|---|---|
| Runs | `#jobs tbody` has rows and no longer reads "Loading runs…" |
| Run view | `#run-view-viewer-A canvas` exists **and** `#run-view-readout-A` contains "atoms drawn" |
| New run | `#molecule-directory` has more than one option and `#molecule-details` no longer reads "Checking input…" |
| Mappings (Bead Assignment) | `#mapping-molecule` has options and `#mapping-bead-rows` has rows |
| Bonded (Bond Interactions) | any `.js-plotly-plot` exists |
| Run view / Shape and volume | the visible `.analysis-pane` has text (a notice counts as the section's answer) |
| Run view / Bonded terms | same, requiring the FF/terms wording |

## 2. Measured results

Cold, cache disabled, direct URL. "scripts" counts engine modules, feature modules and injected bundles together.

| Panel | First content (ms) | script req | script KB | API req | API KB | Plotly responseEnd | Warm first content (ms) |
|---|---|---|---|---|---|---|---|
| Runs | 1659 | 34 | 1897 | 2 | 38 | — | 1269 |
| Run view | 2043 | 34 | 1897 | 20 | 1961 | — | 2237 |
| New run | 1348 | 34 | 1897 | 2 | 14 | — | 1207 |
| Mappings | 1722 | 34 | 1897 | 7 | 281 | — | 2113 |
| Bonded | **4275** | 35 | **6600** | 8 | 251 | 1659 | 2882 |
| Run view / Shape and volume (default pair: no comparison published) | 1609 | 34 | 1897 | 7 | 21 | 1052 | — |
| Run view / Bonded terms (same pair) | 1566 | 34 | 1897 | 9 | 23 | 1035 | — |
| Run view / Shape and volume, `?run=67bc79a995d6` (surfaces + comparison published) | 1858 | 34 | 1897 | 11 | 701 | 1016 | — |
| Run view / Bonded terms, `?run=67bc79a995d6` | 2136 | 34 | 1897 | 10 | 1000 | 1189 | — |

Shared facts behind every row:

- **NGL: 1 request, 1,284,224 B**, `responseEnd` 258-392 ms after commit. That single blocking `<script>` is 68% of the
  shell's 1897 KB and is downloaded for every panel. NGL is used by Run view (`run-view-monitor.js`,
  `run-view-trajectory.js`), the bead editor overlay (`mapping-ngl.js`), Combinations (`compositions.js`) and two pdc
  modules — so Runs, New run and Bonded pay for it without ever constructing a scene.
- **Plotly: 4,816,114 B**, only where a plot is asked for (Bonded, and the Run view Analysis sections through
  `run-view-mapping-map.js`), `responseEnd` 1016-1659 ms. It is loaded even when the Shape section ends up rendering a
  "not published" notice, because the comparison map mounts on section activation (`run-view-analysis.js:309`) and the
  map is what asks for Plotly.
- **Warm is not faster in any useful sense** (1269-2882 ms). `Cache-Control: no-cache` on `/static/js/*` and
  `/feature-assets/*` means every visit revalidates the same 34 module requests; the server is local so the round trips
  are cheap, and the remaining cost is module execution and panel construction. The plan's earlier "revisit 767 ms"
  figure is a *panel switch in one page*, not a second page load.
- The first panel cannot mount until boot's feature imports resolve: `main.js:37-40` starts the imports, `main.js:77`
  awaits them all, and only then `main.js:97 initializeTabs()` dispatches the open panel. Runs' data answer is 38 KB and
  37.5 KB of that is `/api/jobs`; the other ~1.6 s is the module graph plus boot ordering.
- **A 10.3 MB figure is fetched during a cold Run view**: `/api/jobs/67bc79a995d6/artifacts/analyses/surfaces/.../surface-comparison.html?inline=1`
  = 10,300.8 KB. `RunFigureViewer` renders the first figure of the run as soon as the list arrives
  (`figures.js:66 select(...)`, `figures.js:82-83` creates the `iframe`), and the Figures tab is not the open
  section, so this is eager figure loading on a hidden pane. It dominates the Run view API bytes (1961 KB measured in
  that load and 701-1000 KB in the section loads, where the same run was shown).

## 3. What happens before the panel has useful content

### The shell, on every page

1. `dashboard.html:6-19` — nine stylesheets plus one per installed feature.
2. `dashboard.html:20` — `<meta name="plotly-src">` (a URL only; the bundle is not loaded here).
3. `dashboard.html:21` — **`<script src="/static/vendor/ngl.js">` blocking, 1.28 MB**. Runs, New run and Bonded need
   none of it; it is what makes a panel that never opens a scene pay for a 3D library.
4. `dashboard.html:26-35` boots `main.js`. `main.js:37-40` dynamically imports every installed feature's panels and
   extension modules (`features.py:244`, `feature.py:157`). `run-view-mapping.js` imports `bonded-plot.js`
   (`run-view-mapping-map.js:17`), which imports `plotly-loader.js`, so the Plotly *loader* ships on every page while
   the 4.8 MB *bundle* stays lazy.
5. `main.js:47-80` constructs all engine panels synchronously, then `main.js:77` awaits the imports, `main.js:97-104`
   announces the open panel and schedules the catalogue warm-up (`main.js:101-104`).

### Runs — `runs.js` mount

`#jobs tbody` holds one row reading "Loading runs…" (`dashboard.html:104`) until `/api/jobs` and `/api/storage` answer.
The reader sees a table frame with a loading row, then a filter/search toolbar that does nothing until the first
answer. No heavy construction; the cost is the shell (the panel's own data is 38 KB).

### Run view — `run-view.js:232-249`, `run-view-monitor.js`, `run-view-analysis.js`

- `mount()` does `readScope(); build(); await loadRuns(); await pickInitial()` (`run-view.js:233-239`).
- `build()` (`run-view.js:118-146`) creates **two** monitors; each `createMonitor` writes its markup
  (`run-view-monitor.js:87-109`) and constructs the Trajectory block and the Analysis card. `monitorMarkup` has an
  empty `<div id="run-view-viewer-A">` and no interim text in the stage card.
- `loadRuns()` (`run-view.js:91-116`) issues one `/api/jobs?…&run_type=…&status=completed` per run type in scope
  (five requests here, `run-view-scope` at `dashboard.html:129`) — 20-37 KB.
- `pickInitial()` opens a run on each monitor. `loadRun` (`run-view-monitor.js:232-275`) writes
  `'Reading what this run holds…'` and a `'Reading the run directory…'` row (`:243-244`), fires `/trajectory`
  (`:249`), walks the artifact index per extension in pages of 100 (`:277-291`), reads `stages/2_mapping/model.json`
  (`:378-395`), then `draw()` (`:447-515`) fetches `/structure` and only then calls `stageFor()`
  (`:418-423`), which is where **`new NGL.Stage`** happens — i.e. the WebGL canvas is created after the fetches, with
  the card blank until then.
- The Analysis card mounts `/analyses`, `/figures` and the distance diagnostics and, through `figures.js`, the first
  figure's 10.3 MB iframe.
- The reader meanwhile sees: a populated run chooser, a blank canvas card with an empty caption, the analysis sentence
  "Choose a run to see its analysis graphs." (`run-view-analysis.js:54-55`) — and, only after `loadRun` starts, the two
  interim strings above.

### New run — `new-run.js` mount

The template already owns the interim text: `#molecule-directory`'s placeholder option "Loading molecule directories…"
and `#molecule-details` "Checking input files…" (`dashboard.html:156,158`). No heavy construction; 14 KB of data.

### Mappings / Bead Assignment — `mappings.js:452-474`

`mount()` sets `aria-busy` on the section (`:454`), reads three catalogues in parallel, then loads the molecule editor
and the 3D overlay (`mapping-ngl.js:106-112`, which also toggles `aria-busy`). No visible loading text: the editor
table is simply empty until the answer, and the `aria-busy` flag has no CSS (see §4).

### Bonded / Bond Interactions — `bonded.js:351-359`, `bonded-plot.js`

`mount()` fills the mapping select, awaits `parameterization.mount()` then `refreshMapping()`. `refreshMapping`
(`bonded.js:322-347`) sets `aria-busy` on the model card, reads `/api/mappings/<file>`, resolves the structure, reads
the parameterization record. The scene itself is drawn by `mountBondedPlot` (`bonded-plot.js:196`) whose `render`
calls `ensurePlotly()` (`bonded-plot.js:404`; loader `plotly-loader.js:10-43`) and then `Plotly.react` (`:423`).
Meanwhile the `.bonded-plot` div (`dashboard.html:487`) is an empty box, and the panel's one `role=status` line
(`.bonded-panel-message`, `dashboard.html:501`) is empty until an error or a save writes it.
Measured: 4275 ms to first plot, 4.8 MB of bundle, 1659 ms to the bundle's `responseEnd`.

### Validation sections inside Run view — `run-view-mapping.js`, `run-view-mapping-map.js`

- Module load: `run-view-mapping.js` is an extension module imported at boot, so it is on every page; it registers
  three sections (`:760-791`) and a notice (`:793-797`).
- Opening a section: `run-view-analysis.js:292-318 activate()` unhides the pane, mounts the **map**
  (`:306-309`, `mountMap` → `run-view-mapping-map.js` → `mountBondedPlot` → Plotly), and calls `drawSection`
  (`:275-290`) which calls `section.mount(...)` with the pane as `host`. Between unhiding the pane and the section
  writing into it, the pane is empty.
- `paintShape` (`run-view-mapping.js:665`) awaits `loadBody` (`:71-93`, `/mapping-consistency`), then writes the whole
  section with `host.innerHTML` (`:684`), then awaits the surface-pair JSON (`:728-737`) and the two SASA series
  (`:747-749`), drawing with Plotly (`:305`, `:394`, `:452`). `paintGeometry` and `paintBonded` follow the same shape.
- Measured: the notice case is 1566-1609 ms and still pulls Plotly (1035-1052 ms); with a published comparison the
  pane is 1858-2136 ms and reads 701-1000 KB of API.

## 4. Where an honest loading state belongs

### What already exists and is invisible

| State | Where it is set | Shown? |
|---|---|---|
| `aria-busy` on the Mappings section (`mount`) | `mappings.js:454`, cleared `:473` | **No** — no CSS rule reads `[aria-busy]` anywhere in `dashboard.css`, `runs.css`, `new-run.css`, `mappings.css`, `run-view.css`, `layout.css`, `workspaces.css`, `compositions.css` (grep: zero hits) |
| `aria-busy` on the Bonded model card | `bonded.js:327`, cleared `:344` | No |
| `aria-busy` on the molecule editor workspace | `mappings.js:240`, cleared `:288` | No |
| `aria-busy` on the bead editor overlay | `mapping-ngl.js:106,112,160` | No |
| `aria-busy` on the New run panel | `new-run.js:895`, cleared `:912` | No |
| "Loading runs…" placeholder row | `dashboard.html:104` | Yes |
| "Loading molecule directories…" / "Checking input files…" | `dashboard.html:156,158` | Yes |
| "Reading what this run holds…" / "Reading the run directory…" | `run-view-monitor.js:243-244` | Yes, in the caption and the holds table |
| "Loading `<path>`…" | `run-view-monitor.js:448` | Yes, after the canvas exists |
| "Choose a run to see its analysis graphs." | `run-view-analysis.js:54-55` | Yes, until a run is chosen |

So the busy flag is already plumbed in five places — the missing piece is one CSS rule and a text line, not new state
machinery.

### Blank regions with nothing at all

1. `#runs`, `#new-run`, `#mappings`, `#bonded` between the tab click and the first data answer — only New run has a
   placeholder; the panel that is *initially open on a cold load* has none (boot's imports run first, §3).
2. The Run view monitor's stage card (`run-view-monitor.js:100-106`) until `draw()` creates the canvas.
3. Every Run view analysis pane (`run-view-analysis.js:68-73`) until the section writes — this is the Shape and Bonded
   terms case above, ~1.6 s of blank pane.
4. `.bonded-plot` (`dashboard.html:487`) until Plotly arrives — ~1.6-4.3 s of empty box.

### Smallest hook that covers each

- **One shared helper**, next to the existing DOM helpers in `shared.js` (added after the `setText` line, ~`shared.js:8`):
  `setPanelBusy(element, text)` — sets `aria-busy`, inserts (or updates) a `<p class="panel-loading" role="status">` as
  the element's first child, and removes it when `text` is empty. ~10 lines, no state.
- **The panel mount entry point**: `main.js:82-96`, the one `dashboard:tab` listener. Wrap the existing dispatch:
  `setPanelBusy(document.getElementById(id), 'Loading this panel…')` before the mount call, clear it in the
  `.finally` that the existing `.catch` implies. This is the only place every panel passes through, and it makes the
  five existing `aria-busy` flags visible at the same time via CSS.
- **The monitor canvas card**: add one `<p class="hint run-view-loading" id="run-view-loading-<side>">Loading this run's
  structure…</p>` inside `.run-view-stage` in `monitorMarkup` (`run-view-monitor.js:100-106`), and set its `hidden`
  (or remove it) in `draw()` when the component exists (`run-view-monitor.js:487-499`), in the no-structure branch
  (`:269-273`) and in the stage-failure branch (`:474-481`).
- **The analysis pane**: `run-view-analysis.js:275-290 drawSection` — before `section.mount(context(...))`, call
  `setPanelBusy(pane, 'Reading this section…')`; clear it in the `.finally` of the same promise, so a section that
  writes its own markup (all three do) ends up with only its own content and a section that returns early leaves no
  spinner. **Note the overlap**: this file is Lane B's (§8).
- **The Bonded plot host**: the panel already owns `message` (`bonded.js:84`); set it to "Loading the model and its
  terms…" at the top of `mount()`/`refreshMapping()` and clear it in the `finally` that already clears `aria-busy`
  (`bonded.js:344`). No change to `bonded-plot.js` is needed.
- **CSS**: one rule in `dashboard.css` (the shared sheet), e.g.
  `.panel-loading{color:var(--muted);font-size:12px;margin:6px 0}` and
  `[aria-busy="true"]{opacity:.72;transition:opacity .15s}`. No new file, no framework.

## 5. What is already warm, and what may be warmed

Already loaded by the shell on every page (so not warm-up candidates):

- all engine modules (static import graph of `main.js`), including `bonded-plot.js` and `plotly-loader.js` via the
  validation extension's imports;
- every installed feature's panel and extension modules (`main.js:37-40`);
- **the NGL bundle, unconditionally** (`dashboard.html:21`);
- all panel markup: every panel's section lives in the one document (`dashboard.html:93-502`), hidden by attribute;
- the catalogue lists, once, after idle (`main.js:14-28`, `main.js:101-104`).

Warm-up proposal (shown panel only, after idle, once):

- **Plotly**, when the shown panel is Bonded **or** Run view — because Geometry / Bonded terms / Shape are Run view
  sections that draw through `bonded-plot.js` and `ensurePlotly`. Call `ensurePlotly()` from a
  `setTimeout(idle(...), 1500)`-style hook mirroring `main.js:101-104`, gated on the shown panel: read the open
  subtab's `aria-selected` (`dashboard.html:79-81`) or the panel section's `hidden` attribute — the same test Lane B is
  adding as `shown()` in `run-view-analysis.js`. Never call it from a hidden panel's mount.
- `ensurePlotly` already gives the properties a warm-up needs: one promise per module instance and **one script element
  per document** (`plotly-loader.js:20-41`), so a warm call and a later panel call share the same request and the same
  `window.Plotly`; a failed warm removes the element (`:33-39`) so the panel's own ask is a fresh one; and the promise
  resolves with `window.Plotly` so nothing has to poll. Add a module-level `warmed` flag (or reuse the fact that
  `window.Plotly` short-circuits at `:11`) so a revisit does not ask again.
- **NGL is not a warm-up candidate** — it is already downloaded on every page. What the Run view pays is
  `new NGL.Stage` plus one `loadFile` parse per monitor, after two fetches. If the shell wants NGL off non-3D pages,
  that is the opposite change: make it lazy like Plotly (a `vendor/ngl-loader.js` that appends the same
  `<script data-ngl>`, one promise per page) and then warm it for Run view / Complexes / Bead editor only. That is a
  measurement-backed proposal, not a warm-up, and it changes `dashboard.html:21` and every `window.NGL` reader.

Must **not** be warmed, under any name:

- `/api/jobs`, the queue, running progress, the console log — live run state;
- `/api/jobs/<id>/analyses`, `/figures`, artifact indexes, `mapping-consistency`, `ff-interactions`,
  `distance-diagnostics` — run-scoped records, and `mapping-consistency` decides what the section says;
- the generated figures themselves (including the 10.3 MB interactive surface figure) — the plan's standing rule, and
  §2 shows this is already the largest single item on a Run view cold load;
- Plotly when Runs, New run, Mappings or Combinations is the shown panel; and never for a hidden panel;
- the second Run view monitor's scene beyond what `mount` already draws (plan open decision 3; not measured here).

## 6. What the proposal does not change

No prefetch of a hidden panel, no caching of live state, no change to which run each monitor picks, no change to the
Plotly/NGL libraries, no new dependency, no build step. Every measured number above is reachable again by the same
protocol; nothing in it is a wall-clock assertion.

## 7. Test plan (no wall-clock thresholds)

Existing patterns to reuse:

- request identity: `packages/core/tests/browser/test_lazy_loading.py:23-30,94-112` records `page.on('request')` paths
  and asserts a path is asked once (or never);
- bundle identity and exactly-once: `packages/core/tests/browser/test_plotly_lazy_browser.py:58-101` (bundle fetched
  once, `.bonded-plot .plotly` visible) and `:162-201` (**holds** the bundle with `page.route`, asserts the section's
  text is readable while the bundle is still held, then releases it);
- panel content waits: `packages/core/tests/browser/test_run_view_browser.py`, `test_runs_table_browser.py`,
  `packages/validation/tests/browser/test_run_view_mapping_analysis_browser.py`;
- visibility flag already asserted: `expect(...).to_have_attribute('aria-busy', 'false')`
  (`test_bead_editor_controls_browser.py:48`, `test_bonded_parameterization_browser.py:213`).

Proposed regression (one new module, e.g. `packages/core/tests/browser/test_panel_loading_browser.py`, plus one case in
the validation browser tier):

1. **Loading state is visible while the answer is held.** `page.route('**/api/jobs?**', hold)`; `page.goto('/runs')`;
   assert `#runs` has `aria-busy="true"` and `#runs .panel-loading` is visible; release the route; assert
   `aria-busy="false"` and `.panel-loading` count 0, and the existing run row appears. No timeout assertion.
2. **Loading state for a section whose data is held.** Reuse the `publish(dashboard, ...)` fixture from
   `test_plotly_lazy_browser.py:169`; hold `**/mapping-consistency`; open Run view, click the Shape tab; assert the
   pane has `aria-busy="true"` and its `.panel-loading` text; also assert no Plotly bundle request has been made yet;
   release; assert the surface section's own wording appears.
3. **Request identity for the warmed bundle.** On `/runs` assert no request matches `meta[name="plotly-src"]`;
   then click `#tab-bonded`, expect `.bonded-plot .plotly` and exactly one bundle request (this is
   `test_plotly_lazy_browser.py:58-101` reused, and it stays the guard if warm-up is added: the warm request and the
   panel's request must still be one).
4. **NGL stays out of a non-3D cold load** — only after (and if) the lazy-loader change is accepted: assert no
   `/static/vendor/ngl.js` request on `/runs`, one after opening Run view and waiting for the canvas.

## 8. Risks and coordination

- **File overlap.** Lane B is editing `shared.js` and `run-view-analysis.js` right now (the analysis card's poller). The
  helper in `shared.js` and the pane hook in `run-view-analysis.js:275-290` must be sequenced by the integrator after
  Lane B, or Lane B adds the one line in `drawSection` itself. `main.js`, `run-view-monitor.js`, `bonded.js` and
  `dashboard.css` are untouched by Lane B at the time of writing.
- **`aria-busy` semantics.** A busy container suppresses live-region announcements to assistive technology, so it must
  be cleared on every path — including the mount's rejection path that `main.js:92-95` already handles, and the
  superseded-generation returns in `bonded.js` and `mappings.js`. A loading line that never clears is worse than none.
- **Layout risk.** Inserting a paragraph as a section's first child shifts content; `dashboard.css` has no
  `:first-child` rules on sections today, but browser tests assert counts and text of panel children
  (`test_bonded_workspace_browser.py`, `test_bead_editor_controls_browser.py`), so the line must be removable and
  must not be inside a `<table>` or `.analysis-views`.
- **Warm-up cost.** 4.8 MB on a metered or slow link for a panel the reader may never open is plan open decision 2; the
  proposal gates it on the shown panel, on idle, and once per page, and does not make first paint wait for it.
- **The measurement is single-sample** on a dev server in headless Chromium; treat 10-20% differences as noise. The
  load-bearing facts are request identity (34 modules, 1 NGL script, Plotly only where plotted), the bundle sizes, and
  the 10.3 MB eager figure.
- **Not measured here:** the second monitor's deferral (plan item 4), the server cost of the requests, and the cost of
  `new NGL.Stage` separated from the structure fetch. All three would need their own pass.

### Inferred, not measured

- That warm page loads receive 304s for the 34 modules (the warm request counts are 34 and the API `content-length` for
  repeated `/api/jobs` is 0, which is consistent with conditional answers, but `transferSize` was not captured).
- That making NGL lazy would save roughly the 258-392 ms `responseEnd` plus 1.28 MB on non-3D cold loads; the saving
  on a cold remote cache would be larger than this local number.
- That the surface pair/SASA fetches are what the extra ~250 KB in the published-comparison Shape case consists of; the
  per-request breakdown for that case was not printed.
