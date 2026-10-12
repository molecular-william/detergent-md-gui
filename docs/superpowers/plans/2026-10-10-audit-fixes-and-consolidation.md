# Audit fixes and consolidation: implementation plan

> **For Hermes:** this is the "plan every finding at once" mode of the codebase-architecture review — one phased plan,
> not a single-candidate grind. The review it follows is at
> `/home/wee/architecture-review-detergent-md-2026-10-09.html`; the findings named below are numbered as they are there
> (D1–D5 for defects, 1–6 for deepening candidates).

**Goal:** fix the five defects the audit found, then remove the four sources of friction that keep producing them —
without moving a directory, renaming a URL, or changing a manifest field.

**Architecture note, and it decides the ordering:** this plan contains **no layout move**. The audit's candidates are
interface and ownership problems, not packaging ones, so the consolidation reference's "layout first" rule has nothing
to act on and is deliberately not followed. The rule exists because a move breaks imports in ways no test shows; with
no move, the cheapest changes go first.

**The constraint that binds every phase:** HTTP URLs, browser storage keys, workspace and database layout, manifest
field names, stage names and documented entry points are frozen. Phase 0 exists to check the frozen ones mechanically.

---

## Sequencing

| Phase | Content | Depends on | Risk | Rough size |
|---|---|---|---|---|
| 0 | The gate sees the browser tier; the markers get one home | — | low | ~1 h |
| 1 | Defects D2, D3, D4, D5 | 0 | low | ~3 h |
| 2 | Candidate 1 — the protocol becomes the only way in | 1 | medium | ~4 h |
| 3 | Candidate 2 — one table for the analysis kinds | 1 | medium | ~4 h |
| 4 | Candidate 3 — the DOM ids get a single owner | 2, 3 | **high** | ~6 h |
| 5 | Candidate 4 — one writer per rendered host | 4 | medium | ~3 h |
| 6 | Candidate 6 — the four shallow modules | 2 | low | ~2 h |
| 7 | The stale config and the absent assets | — | low | ~1 h |

Each phase commits on its own and leaves the fast tier green. Phases 2–6 are **test-first**; 0, 6 and 7 are
**mechanical** and carry a verification command instead of a test cycle.

**Expected values below were measured while writing this plan**, at `6d5badd`:

```
fast tier         1223 passed, 36 warnings
browser tier      66 collected — 43 passing, 22 red (the two-level navigation refactor, still outstanding)
slow tier          7 collected, not run (builds simulations)
ruff (named)      clean
```

The browser tier's 22 red tests are **not** this plan's work and must not be absorbed into it: they belong to the
navigation refactor's Task 1.4. Phase 0 will make them *visible*, and Phase 0's acceptance is that the gate reports
them rather than that they are green.

---

## Phase 0 — the gate, and one home for the markers

**Mechanical.** Two edits, then the verification command.

**Why first:** the audit found five defects and the tier that exercises the dashboard could not have reported any of
them. Twenty of its sixty-six tests were red without anything noticing. This is the cheapest change here and the only
one that makes the rest of the plan hold.

**Files:** the gate script (`gate_commit.sh`), `pytest.ini`, `pyproject.toml`.

**Steps:**
1. Add a second invocation to the gate: the browser tier, for the paths the commit names, when a browser test or a
   template or a stylesheet is among them. Keep the fast tier as it is.
2. Delete the duplicated `markers` and `addopts` block from `pyproject.toml`, or from `pytest.ini` — one of the two,
   and say which in the commit. They are byte-identical today and `pytest.ini` wins by discovery order, so the copy in
   `pyproject.toml` is a trap: editing it changes nothing.
3. Do **not** make the browser tier block on a red baseline. It is red now; the gate must report the count and let a
   commit through while `# task-1.4` is outstanding, then be tightened to blocking when that lands. Say the same in
   the commit message so the loose setting has an owner.

**Verification:**
```bash
bash <skill>/scripts/gate_commit.sh <msg> dashboard/web/static/js/tabs.js
grep -c "markers" pytest.ini pyproject.toml     # exactly one file
```

**Acceptance:** a commit touching a JS file reports the browser tier's count; a commit touching only Python does not;
exactly one file declares the markers; the fast tier still gates.

---

## Phase 1 — the four open defects

**Test-first**, one task each, one commit each. D1 is already fixed in `6d5badd` and is listed only so the phase is
complete.

**D2 — one host, two writers.** `runs.js:161` fills `.analysis-tasks` with each task and its Cancel control;
`runs-diagnostics.js:11,79` replaces that host's children. *Test first:* open a run card, start a diagnostics view,
assert the Cancel control is still there. *Change:* give the diagnostics box its own host in the template, and let
`runs.js` own `.analysis-tasks` alone.

**D3 — a control with no refresh path.** The validation button is written only inside the card-creation block
(`runs.js:75-78`). *Test first:* render a card for a running `aa_cg` run, flip the job's status to completed, refresh,
assert the button became visible. *Change:* move the three lines into the per-refresh block at `runs.js:106-131`.

**D4 — the complex panel is armed only by a test hook.** `pdc.js:232`'s `setRun` has no production caller, so the
system viewer and snapshot strip never load. *Test first:* select a complex run through the panel's own controls and
assert the viewer requests its snapshot. *Change:* the panel's run selection calls `setRun` itself; `window.pdcSetRun`
stays for the tests but stops being the only door.

**D5 — the stage-plan converter mangles one shape.** `workflow._plan_pairs` indexes characters when handed an
`aa_cg` name list. *Test first:*
`_plan_pairs({'run_type':'aa_cg','stage_plan':['AA reference','trajectory mapping']})` must raise or return two pairs,
not `[['A','A'],['t','r']]`. *Change:* teach the converter the third shape, and make an unknown shape raise rather
than guess — the current fallback fails silently, which is why this existed unnoticed.

**Acceptance:** each defect has a test that fails before its change and passes after; the four tests name the defect
in their docstring; the fast tier is at 1223 + 4 passing.

---

## Phase 2 — candidate 1: the protocol becomes the only way in

**Test-first.** Ten call sites reach past `protocol.adapter_for`, measured:

```
execution/workflow.py:59    cg.REQUIRED_INPUTS as the default for every run type
execution/workflow.py:95    cg.prepare for anything that is not composition or pdc
execution/workflow.py:143   cg.tool_metadata for every non-aa_only resume
coordination/coordinator.py:379   cg.SETTING_SPECS to filter a job's settings
web/routes/runs.py:121      cg.SETTING_SPECS again, for the queue route
web/routes/molecules.py:89,98,113,124   four readiness calls reached directly
```

**Test first:** a test that the readiness route's answer for each run type equals the protocol's answer for that type
— it fails today for `aa_cg`, which the route composes by hand from two adapters.

**Change:** each of the ten sites asks the protocol. `workflow` keeps its own stage ledger and loses its `cg` import;
the readiness route stops composing and starts asking. D5 then becomes impossible rather than fixed, because a single
converter learns every shape from the adapter that owns it.

**Acceptance:** `grep -rn "cg\." dashboard/execution/workflow.py` returns nothing; the four readiness answers are
identical through both paths; the fast tier is green.

---

## Phase 3 — candidate 2: one table for the analysis kinds

**Test-first.** Four lists must agree about fourteen kinds, measured: `KINDS` (14 names), `PATTERNS` (the source file
per kind), **10 dispatch arms**, and `DESCRIPTIONS` (**17 entries** — three more than there are kinds). Nothing
compares them, and `metadata.describe` answers an unknown kind with an invented title rather than an error.

**Test first:** add a kind to `KINDS` only and assert the whole chain knows it — the test fails today, and the
invented title is what it should report.

**Change:** one table, one row per kind, holding its name, its sources, its dispatch and its description; the four
readers derive from it. The three descriptions with no kind are either matched to one or deleted, and the fallback in
`metadata.describe` becomes an error.

**Acceptance:** adding a kind is one row; the fallback is unreachable and tested as such; the fast tier is green.

---

## Phase 4 — candidate 3: the DOM ids get a single owner

**Test-first, and the highest-risk phase here.** Counted: **nine** modules resolve **215** id lookups against a
template that owns **163** ids, and **none** of those lookups points at a node the JavaScript creates. This is where
four of the five defects live, and D1 — a registered panel with no section — is exactly what it produces.

**The risk is not conceptual, it is churn:** 215 call sites across nine files, in code where a missed rename throws and
kills every later statement in that module. So this phase changes as few call sites as possible.

**Test first:** a test that every id a module looks up exists in a rendered page, and every id the template carries is
either looked up or declared deliberately unused. Both directions, because D1 was the second kind.

**Change, in three small steps:**
1. The registry (`sections.py`) already names panels and their ids. Extend it to the ids the templates carry, so the
   template writes them from one source rather than as literals.
2. Add the test above. It catches D1's class of failure without touching a single call site.
3. Only then, and only where a module restates the id vocabulary — `main.js:29`, `new-run.js:354`,
   `mappings.js:333-334` — read it from the registry instead. Leave the 215 `$('#id')` lookups alone: they are
   resolvable by the new test, and rewriting them buys naming tidiness at the cost of the exact churn this plan is
   trying to avoid.

**Acceptance:** the two-directional test is green; the three restatements are gone; a panel registered without a
section fails the test rather than blanking the page; **no panel module's lookup count changes.**

---

## Phase 5 — candidate 4: one writer per rendered host

**Test-first**, and it depends on Phase 4 because both concern who owns a rendered element. Phase 1 removes D2's
symptom; this removes the cause: a card is written by two modules that do not know about each other, and one host has
no declared owner. **Change:** each host in the run card gets a single writer, named in a comment; the window handle
that only tests use stops being load-bearing for the panel's own navigation. **Acceptance:** no element is written by
two modules; `window.*` exports are test hooks only, and each says so.

---

## Phase 6 — candidate 6: the four shallow modules

**Mechanical**, and each needs a decision rather than work:

```
adapters/micelle.py:6-16          one caller already does the surrounding work — inline it or give it depth
analysis/runs/observability.py:250-252   a three-line delegation holding a dispatch slot — call surfaces.generate
coordination/manifest.py:38-47    read_manifest has no caller anywhere — delete, verified by grep
adapters/cg_names.py              a guard that returns immediately because its condition is a constant
```

**Acceptance:** each is deleted or deepened, with the deletion test's answer in the commit; `grep -rn read_manifest`
finds nothing outside site-packages.

---

## Phase 7 — the stale config and the absent assets

**Mechanical**, and it closes two audit findings that are documentation wearing a config file's authority:
`config/benchmark.json` and `config/performance.json` are read by no code and both say `ntomp: 8`, contradicting the
`-ntomp 4` this project measured and set. `AGENTS.md:49` names `martini_v300.zip`, `insane3.py` and `mdp_files/` as
local assets; none exists anywhere in the tree. **Change:** either make each file authoritative and read it, or delete
it and say in the decision record that the numbers live in the adapters; correct `AGENTS.md` to what is present.
**Acceptance:** a config nothing reads is gone; `AGENTS.md`'s asset list matches the tree.

---

## Acceptance checklist

- [ ] Exactly one file declares the pytest markers; the gate reports the browser tier for front-end changes.
- [ ] D2–D5 each have a test that failed before its change; D1's two tests are green.
- [ ] `workflow.py` imports no adapter directly; all ten call sites ask the protocol.
- [ ] Adding an analysis kind is one row, and an unknown kind raises rather than inventing a title.
- [ ] No panel is registered without a section, and the test that proves it is green.
- [ ] No rendered element has two writers.
- [ ] No module in the shallow four remains a pass-through.
- [ ] HTTP URLs, storage keys, manifest fields and stage names are unchanged — checked mechanically, not by memory.
- [ ] The frozen-route-table diff is empty:
      `python -c "from dashboard.app import create_app; print(sorted(str(r) for r in create_app().url_map.iter_rules()))"`

## Deliberately not done

| Left alone | Why | What makes it safe |
|---|---|---|
| The 215 `$('#id')` lookups in panel modules | rewriting them is churn in the highest-risk area for naming's sake | Phase 4's two-directional test resolves every one of them against a rendered page |
| The 22 red browser tests | they belong to the navigation refactor's Task 1.4, not to this plan | Phase 0 makes them visible; the refactor's plan owns them |
| The directory layout | the candidates are interface and ownership problems, not packaging ones | no move means no import churn, which is why this plan has no layout phase |
| `analysis/metadata.py`'s 17 entries for 14 kinds | the extra three may be documentation for kinds that were planned | Phase 3 matches or deletes each, and the fallback becomes an error either way |
| The two-tier `pyproject.toml` / `pytest.ini` split | one file must go, but which is a preference not a finding | Phase 0 makes one authoritative and says so in the commit |
| The osmotic series' 2.24x divergence at 2.5 molal | it is a scientific result, not a defect — the model diverges from a 2016 paper as concentration rises | recorded in the osmotic plan's Task 2.1 with the whole series |

## A note on what this plan is not

It is not a refactor and it does not move anything. Every phase changes how one thing is reached or who owns it, which
is the smallest change that removes the friction the audit named. An implementer who decides to "also tidy the
directory while I am here" will produce the churn this plan was written to avoid, and the guard against that is the
frozen-route check in the acceptance list.
