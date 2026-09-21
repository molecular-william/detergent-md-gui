# Detergent Micelle Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic CLI that creates and validates spherical single-detergent Martini micelles around membrane proteins and exposes it to the dashboard.

**Architecture:** A native Python core owns registry loading, orientation, spherical candidate scoring, local/global repacking, solvent/ions, topology closure, validation, diagnostics, and manifests. A thin CLI calls the core; the dashboard submits the CLI and renders immutable reports. Existing Insane code is a reference for algorithms, not a copied implementation.

**Tech Stack:** Python, NumPy, MDAnalysis, GROMACS (`gmx grompp`, optional `gmx mdrun`), martinize2, pytest, Flask dashboard.

**Spec:** `docs/superpowers/specs/2026-09-14-detergent-micelle-builder-design.md`

## Global Constraints

- Single registered detergent per build; spherical initial envelope.
- Every build requires an integer seed and exact aggregation number.
- OPM metadata precedes explicit axis/span, which precedes combined heuristic orientation.
- Use supplied CG protein files; otherwise invoke martinize2 and record the command.
- Reposition locally, then use unused scored directions for replacements; emit diagnostics only when exact count or hard gates fail.
- Cubic box by default; optional orthorhombic box; water plus optional ions.
- `gmx grompp` is a hard gate; restrained minimization is optional and reported independently.
- Production outputs are immutable; source hashes, commands, environments, and failures are recorded.

---

### Task 1: Registry and immutable build model

**Files:**
- Create: `micelle/registry.py`, `micelle/model.py`, `micelle/errors.py`
- Create: `micelle/tests/test_registry.py`
- Modify: `pyproject.toml` only if the existing packaging does not discover `micelle`

**Interfaces:**
- `load_template(path: Path) -> DetergentTemplate`
- `validate_template(template: DetergentTemplate) -> list[str]`
- `BuildConfig` fields: `protein_aa`, `protein_cg`, `protein_topology`, `detergent`, `aggregation_number`, `seed`, `box`, `water`, `ions`, `run_minimization`, `output`
- `BuildManifest.write(path: Path) -> None`

- [ ] Add a declarative DDM template referencing coordinate and `.itp` assets, with residue/bead names, charges, head/tail annotations, dimensions, bonds, and hashes.
- [ ] Reject missing assets, duplicate bead names, non-integer seeds, non-positive aggregation numbers, and unresolved includes.
- [ ] Test valid DDM loading, malformed metadata, immutable output refusal, and exact manifest serialization.
- [ ] Run `pytest micelle/tests/test_registry.py -q`.

### Task 2: Protein preparation and orientation

**Files:**
- Create: `micelle/protein.py`, `micelle/orientation.py`
- Create: `micelle/tests/test_orientation.py`, `micelle/tests/fixtures/bacteriorhodopsin.pdb`

**Interfaces:**
- `prepare_cg_protein(config, workdir, runner) -> PreparedProtein`
- `infer_orientation(aa_structure, opm=None, explicit_axis=None, explicit_span=None) -> OrientationReport`

- [ ] Prefer supplied CG files; otherwise invoke martinize2 through an argument-list subprocess and record version/command.
- [ ] Parse OPM orientation only from explicit metadata and report provenance.
- [ ] Implement combined alpha-helix clustering, hydrophobicity, and neighbor-density fallback with confidence and membrane span.
- [ ] Test precedence, low-confidence rejection, martinize2 command construction, and deterministic reports using a bacteriorhodopsin fixture.
- [ ] Run `pytest micelle/tests/test_orientation.py -q`.

### Task 3: Candidate lattice, scoring, and repacking

**Files:**
- Create: `micelle/packing.py`, `micelle/geometry.py`
- Create: `micelle/tests/test_packing.py`

**Interfaces:**
- `golden_angle_directions(count: int, seed: int) -> np.ndarray`
- `score_candidate(candidate, protein, template, config) -> CandidateScore`
- `pack_micelle(protein, template, config) -> PackedMicelle`
- `repack_and_replace(packed, candidates, config) -> PackedMicelle | PackingDiagnostics`

- [ ] Generate deterministic spherical candidate directions and derive an initial radius from dimensions and aggregation number.
- [ ] Score belt coverage, soluble-domain exposure, pore clearance, hard overlaps, orientation, and radial uniformity.
- [ ] Select highest-scoring directions, then shift local neighbors and try unused scored directions for replacement.
- [ ] Preserve exact count or return diagnostic-only failure with rejected candidates and reasons.
- [ ] Test same-seed byte-equivalent placement, protein-free micelles, impossible counts, and soluble-domain masking.
- [ ] Run `pytest micelle/tests/test_packing.py -q`.

### Task 4: Solvent, ions, box, and topology assembly

**Files:**
- Create: `micelle/solvation.py`, `micelle/topology.py`, `micelle/output.py`
- Create: `micelle/tests/test_topology.py`, `micelle/tests/test_solvation.py`

**Interfaces:**
- `build_box(positions, margin, shape, dimensions=None) -> Box`
- `solvate(system, water, ions) -> SolvatedSystem`
- `assemble_topology(system, forcefield, fragments) -> TopologyResult`
- `write_gromacs_system(system, output_dir) -> OutputManifest`

- [ ] Exclude solvent using bead-level radial/protein occupancy masks, not Insane’s membrane-centered slab mask.
- [ ] Add requested water, neutralizing ions, or concentration-based ions and record counts.
- [ ] Implement explicit cubic and orthorhombic boxes with validated dimensions.
- [ ] Resolve every topology include, verify molecule order/counts against coordinates, and write `.gro`, `.top`, `.itp`, index, and manifest without overwriting.
- [ ] Test solvent exclusion, charge neutrality, box dimensions, include closure, and count mismatch failures.
- [ ] Run `pytest micelle/tests/test_topology.py micelle/tests/test_solvation.py -q`.

### Task 5: Validation, diagnostics, and CLI

**Files:**
- Create: `micelle/validation.py`, `micelle/report.py`, `micelle/cli.py`
- Create: `micelle/tests/test_validation.py`, `micelle/tests/test_cli.py`

**Interfaces:**
- `validate_build(build_dir, run_grompp=True) -> ValidationReport`
- `write_report(report, output_dir) -> None`
- CLI commands: `micelle-build`, `micelle validate PATH`, `micelle inspect PATH`

- [ ] Implement hard gates for finite coordinates, PBC, exact aggregation count, severe overlaps, orientation/composition, belt coverage, exposure/clearance, topology closure, and `gmx grompp`.
- [ ] Keep optional restrained minimization separate from geometry validity.
- [ ] Emit JSON plus HTML/Markdown summaries containing metrics, commands, versions, seed, hashes, and errors.
- [ ] Emit a diagnostic-only package for failed exact-count/hard-gate builds.
- [ ] Test CLI parsing, report consistency, grompp command construction, impossible-build diagnostics, and inspect output.
- [ ] Run `pytest micelle/tests -q`.

### Task 6: Bacteriorhodopsin benchmark and dashboard wrapper

**Files:**
- Create: `micelle/tests/fixtures/ddm_empty_config.json`, `micelle/tests/fixtures/bacteriorhodopsin_config.json`
- Create: `dashboard/execution/micelle_job.py`, `dashboard/test_micelle_job.py`
- Modify: `dashboard/app.py`, `dashboard/web/templates/dashboard.html`, `dashboard/web/static/js/main.js`
- Create: `docs/MICELLE_BUILDER.md`

**Interfaces:**
- `run_micelle_job(payload, run_dir) -> dict`
- `POST /api/micelle/build` returns job metadata; existing run manifests/artifact APIs remain authoritative.

- [ ] Run deterministic empty-DDM and bacteriorhodopsin OPM benchmark smoke builds with identical seeds where comparisons are intended.
- [ ] Add dashboard submission/status/artifact rendering without moving scientific logic into Flask.
- [ ] Ensure failed builds expose diagnostics and cannot be submitted as runnable systems.
- [ ] Document setup, template registration, martinize2 prerequisites, CLI examples, reports, and optional minimization.
- [ ] Run dashboard unit/browser tests plus `pytest micelle/tests -q`.

## Final verification

- [ ] Run `pytest micelle/tests dashboard/test_micelle_job.py -q`.
- [ ] Run a deterministic empty-DDM build twice and compare coordinate/report hashes.
- [ ] Run bacteriorhodopsin with OPM and heuristic orientation paths; inspect confidence and hard-gate reports.
- [ ] Run `gmx grompp` on the generated system and record its result.
- [ ] Run optional restrained minimization once; verify it is clearly separated from scientific validation.
- [ ] Confirm no production files are overwritten and impossible requests produce diagnostics only.
