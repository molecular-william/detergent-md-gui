# Detergent MD automation

Local Martini/GROMACS research dashboard for AA-only molecule simulation and
AA→CG parameterization of any molecule with a compatible topology. The
packaged DDM example (`molecules/DDM`) is a worked reference; other molecules
run through the same generic adapter. The broader membrane-protein and
micelle-builder workflows remain paused project goals.

## Start

From the repository root:

```bash
dashboard/.venv/bin/python -m dashboard
Open http://127.0.0.1:5000. Run one coordinator per configured workspace.
```

## Documentation
* Agent guidance — engineering rules, workflow contract, and the
"do not" list for coding agents and contributors.
* Project guide — dashboard operation, paths,
persistence, migration, and testing.
* DDM calibration — scientific status, bonded-state
  limitations, and the current DDM handoff.
* Carbohydrate validation operations — the Sucrose diagnostic workflow,
  target registry, artifact access, and scientific validation boundary.
* Molecule directory contract — required AA inputs.
* Dashboard developer guide — source ownership and
testing.

## Repository layout
* dashboard/ — application source, grouped by execution, models, analyses, and web UI.
* tests/dashboard/ — unit, integration, and browser tests with isolated stores.
* reports/dashboard/, reports/validation/ — scientific reports and acceptance evidence.
* molecules/, references/, resources/ — canonical scientific inputs.
* config/ — workspace and tool/resource settings.
* archive/ — preserved historical development material.

## Roadmap
The following work is documented but not yet implemented.

### Open engineering items after the 2026-09-24 consolidation
The consolidation plan (docs/superpowers/plans/2026-09-24-architecture-consolidation.md) is complete
except for one task, and its acceptance checklist is answered with measurements. What is still open,
and where the evidence for each one lives:

- **Attempt lifecycle not yet adopted.** `dashboard/execution/coordination/attempt.py` is implemented
  and tested, but `workflow.run`, `Coordinator.run_job` and `AnalysisCoordinator.run` still keep their
  own write policies (a manifest entry, a database row, and deferred locals written in a `finally`).
  The obstacle at each site is recorded at Task 6.3 of the plan. Adopt `AnalysisCoordinator.run`
  first, or delete the module and record that the three loops differ in substance.
- **Mapping identity includes the candidate name**, and run admission compares that identity, so
  renaming a candidate orphans its fitted bonded states. The name-free `content_identity` exists and
  is used only for duplicate detection. See item 2 of the reconciled gaps in DDM_CALIBRATION.md; the
  state side is fixed (a state records both hashes and compatibility asks the chemistry), the
  selector's filter still matches on the candidate hash and needs the candidate list to publish a
  content identity for the browser to send.
- **Legacy diagnostics rendering.** A diagnostics JSON written before `kind` existed would show a
  constrained pair as a physical bead, and matrix colour limits remain per-run. See item 5 of the
  same section.
- **Two run paths are declared, not implemented:** `cg_composition` runs are a screening stub
  (they declare `execution_kind`), and the Sucrose mapping path is provisional with a one-ring
  recognizer. Both are documented as such rather than presented as finished.
- **Browser tier timing.** The one reproducible flake is fixed -- a 5 s expectation used as a load
  wait -- and the reason is recorded in tests/dashboard/browser/conftest.py. The fix is verified, but
  the failure needed a busy machine to appear, so treat a future failure in
  `test_dashboard_browser.py` as the same class until proven otherwise.

### Iterative mapping refinement panel
A fourth dashboard panel that manages candidate generation and evidence without changing immutable runs or silently selecting a model. It is a review queue linking a mapping candidate, its source structure/reference model, execution settings, analysis artifacts, and reviewer decision.

Planned increments:

1. Reference import and candidate records. Import reference CG PDB/ITP pairs; parse and preserve source files, checksums, force-field/version metadata, bead names/types, bonded terms, and any available atom-map file. Extend mapping JSON with parent_candidate, reference_sources, review_state, labels, and a revision number; revisions always create new files.
2. Controlled candidate generation. Bounded variants from a selected draft: bead size changes obeying coverage/connectivity; local ±1 polarity variants; optional Martini d/a/e/v labels when supported; alternate boundaries from the user or inferred from the bond graph. Every generated candidate records parent, transformation, random seed (if applicable), and validation report; no draft is overwritten.
3. Evidence execution. A short reproducible run using the existing workflow. Panel displays stage progress and links to structural validation, AA-to-CG COG error, fitted distributions, SASA and Connolly surface comparisons, topology-independent observables, numerical stability, and experimental-target residuals.
4. Transparent ranking. Diagnostic score computed only from available, quality-checked metrics. Metric values, normalization, weights, missing-data mask, and score version persist in analysis/refinement_score.json. Rankings are labeled diagnostic; they
cannot approve a model automatically.
5. Human review gate. States draft, needs-review, approved-for-test, and rejected, with reviewer, timestamp, notes, and required justification for size/polarity exceptions. Approval is blocked for structural errors, unstable trajectories, missing required force-field terms, or unresolved atom correspondence.

Scientific validation remains a separate decision. The panel accelerates
review; it does not convert a high diagnostic score into a valid model.

## Micelle builder
A native spherical single-detergent Martini micelle builder around membrane
proteins, exposed through the dashboard. Paused at the user's request.

* Approved design: docs/superpowers/specs/2026-09-14-detergent-micelle-builder-design.md.
* Implementation plan: docs/superpowers/plans/2026-09-14-detergent-micelle-builder.md.
* Partial micelle/ package exists at the repository root. It is experimental and must not be used to claim a validated scientific model.
* The initial core (python -m micelle build) validates a registered detergent template, creates a deterministic spherical center lattice, and writes geometry diagnostics. Protein-aware packing, topology closure, solvent/ions, GROMACS preprocessing, and dashboard submission are unfinished.

## Protein-detergent workflow
The broader memembed -> martinize -> insane -> cg2at chain remains a project goal. Historical assets are preserved under archive/MemProtMD/. The maintained path is execution/adapters/aa.py -> execution/adapters/cg.py -> Fast_Forward -> GROMACS, described in the project guide.

## Verification
```bash
dashboard/.venv/bin/python -m pytest -q
```
See the project guide for focused test commands, browser acceptance criteria, and the fresh-workspace reset boundary.
