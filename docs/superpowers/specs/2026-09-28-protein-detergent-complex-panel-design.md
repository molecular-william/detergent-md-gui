# Protein–detergent complex panel — design

## Status

Drafted for review. Builds on the paused micelle builder whose architecture was approved on 2026-09-14
(`2026-09-14-detergent-micelle-builder-design.md`); that design's pipeline is the reference for how detergents
are placed, and its implementation under `micelle/` is a working skeleton, not a validated model.

## Goal

A second simulation workflow beside the single-molecule one: place a membrane protein in a box, build a
detergent belt around it the way the micelle builder does, solvate and ionise it, run Martini CG MD until a
micelle has formed, extend that to 1 µs, and back-map the final snapshot with CG2AT-align. The whole setup is
visible in an NGL viewer before anything is run.

## Naming

The existing **New run** tab becomes **Single Molecule Simulations**. Its contents, run types and routes do not
change; only the heading and the tab label. The new tab is **Protein-Detergent Complex Simulations**, which is a
separate run type (`pdc`), not a profile of the existing one — its stages, settings and assessment have nothing
in common with the single-molecule pipeline, and pretending otherwise would put two protocols behind one
`STAGES` list.

## What is reused rather than rebuilt

| Need | Existing asset | How |
| --- | --- | --- |
| Detergent placement, orientation, overlap gates | `micelle/geometry.py`, `packing.py`, `repack.py`, `orientation.py`, `registry.py` | Called in-process by the adapter, the way `aa.py`/`cg.py` are |
| Detergent registry format | `molecules/DDM/micelle_template.json` | One template per species; the panel lists what the registry holds |
| CG protein and elastic network | `martinize2` (console script in `dashboard/.venv/bin/`) | `-elastic -ef 1000 -el 10` is the requested network exactly |
| Box, solvent, ions | `gmx editconf`, `gmx solvate`, `gmx genion` | Commands recorded per stage |
| CG MD budget | `execution/adapters/aa.py:mdrun_command_flags` | The same stage settings, so the CPU/scheme choices reach this pipeline too |
| Stage records, manifests, cancellation | `execution/protocol.py`, `workflow.py`, `coordination/attempt.py` | Reused unchanged: this is a new pipeline, not a new execution layer |
| System viewer | `dashboard/web/static/vendor/ngl.js` (tracked, NGL 2.3.1) | Same stage-per-view pattern as the Molecule Combination panel |

`nglview` is not used: it is the Jupyter widget. The library underneath, NGL.js, is already vendored here.

## Inputs

Protein structure (PDB), detergent template id, aggregation number, integer seed, salt concentration (default
0.15 M), CG durations (default 100 ns assessment + 900 ns extension), stage settings for the mdrun budget, and an
optional display name. Every build is immutable and seeded; no global RNG.

## Protocol

### 1. Box and protein insertion

- x and y: the protein's own extent plus **2.0 nm** on each side (the requested 20 Å).
- z: an initial box of **6.0 nm** (the requested 60 Å) before detergent is added.
- Implemented as an explicit box (`gmx editconf -box`) rather than `-d`, because the z extent is a separate
  decision from the x/y margin and `-d` cannot express both.

### 2. Atomistic → CG protein

`martinize2` with the Martini 3 force field and an elastic network between all Cα pairs within **1.0 nm** at
**1000 kJ/mol** (`-elastic -ef 1000 -el 10`). Version, command and input hashes recorded. The network is written
from the atomistic structure so the restraint set is reproducible from the inputs alone.

### 3. Detergent placement around the protein

The micelle builder's deterministic lattice, scoring and bounded repacking, with the protein in place: exact
aggregation count, headgroup-outward orientation, and the builder's hard overlap gates. Protein-relative
clearance uses the builder's existing hydrophobic-belt / soluble-domain checks. A placement that cannot satisfy
the gates writes diagnostics and produces no run, as in the original design.

### 4. Box extension in z

z is extended so that the minimum distance between the protein and **all six faces** is at least 2.0 nm, i.e.
`z = 2 × 2.0 nm + (max_z − min_z)` of the placed system, with the protein centred. Recorded in the manifest
alongside the pre-extension dimensions.

### 5. Solvent and ions

Martini water fills the box (`gmx solvate`) and NaCl is added to **0.15 M** (`gmx genion -conc 0.15`),
neutralising the system first. Exact molecule counts and the ion count are recorded, as the builder's design
requires.

### 6. CG MD — assessment phase

100 ns under the stage settings' mdrun budget and scheme choices. Diagnostics per stage as usual.

### 7. Micelle-formation assessment

**This is the one part of the protocol the request leaves open, and it is a scientific decision, so the
specification proposes a default and asks.**

Proposal: a detergent counts as *in the micelle* when its tail beads are within **0.6 nm** of another
detergent's tail beads, and the resulting contact graph's largest connected cluster both holds at least the
aggregation number the build requested and touches the protein's hydrophobic belt. Detergents in smaller
clusters are *not in the micelle*. The report records the cluster sizes, the contact distance used, the
fraction of the requested count in the largest cluster, and the protein contact count, so a disagreement with
the criterion can be re-judged from the artifact without re-running anything.

Alternatives worth choosing between: a minimum contact count per detergent rather than graph connectivity; a
distance-to-centre-of-mass criterion; a radial density profile around the protein; or a combination with the
protein contact requirement dropped for empty (protein-free) micelles.

### 8. Removal and restart

Detergents not in the micelle are removed and the run **continues** from the assessment-phase checkpoint, since
the request says restart only on the threshold. If **more than 10** detergents were removed, the assessment
phase is re-run from scratch with new initial velocities (a fresh seed recorded in the manifest), because a
system that lost that many detergents has not formed the intended aggregate and continuing would sample the
wrong state. The retry count and every attempt are recorded; the loop is bounded by a documented maximum.

### 9. Extension phase

A further 900 ns, continued from the retained checkpoint (`gmx convert-tpr -extend`), so the total CG sampling is
1 µs. Assessment is re-run at the end and compared with the assessment-phase report.

### 10. Back-mapping

The final snapshot is converted to atomistic detail with **CG2AT-align**.

**Dependency gap, flagged rather than assumed:** no `cg2at`, `cg2at2` or `cg2at-align` executable exists on this
host, and no CG→AA path is maintained in the repository (the maintained direction is AA→CG). This stage
therefore needs a decision: install CG2AT2 and pin its version and provenance, use an alternative back-mapping
tool, or land the pipeline with this stage explicitly blocked and the rest usable. The repository must not
imply a back-mapped structure it cannot produce.

## Panel

- **Setup sub-panel**: protein upload/selection, detergent template, aggregation number, seed, salt
  concentration, the two durations, and the stage settings (shared with the other workflow).
- **System view sub-panel**: NGL, showing the built system after setup and the final snapshot after each
  assessment. Water and ions are hidden by default (they dominate the atom count and hide the science); the
  protein, detergents and box edges are shown. The viewer is fed by a server-side PDB written from the actual
  coordinates, in the same way the Molecule Combination panel is fed, so the picture cannot disagree with the
  system.
- **Status sub-panel**: the stages with their state, the assessment verdict with the numbers behind it, the
  removal and retry history, and the provenance (template, seed, tool versions, the recorded mdrun flags).
- The panel is a thin client: science stays in `micelle/` and the adapter.

## Validation gates and claims

Hard gates before a run is admitted: protein parsed and finite, template resolved, seed an integer, aggregation
number ≥ 1, box extents positive after extension, no severe detergent overlap, orientation valid, molecule
counts consistent, and `gmx grompp` succeeding for every stage. The assessment criteria are **proxies for
aggregate formation, not evidence of equilibration**; 1 µs of Martini CG sampling is a stated target, not a
convergence claim, and the panel must label the product `candidate-unvalidated` exactly as the composition panel
does for its own candidates.

## Open decisions for the user

1. The micelle-formation criterion (proposal above) — it decides what "suitably formed" means for every run.
2. CG2AT-align availability: install and pin it, choose another back-mapper, or ship the pipeline with that
   stage blocked.
3. Retry policy: maximum attempts, and whether each retry re-places detergents or only re-seeds velocities.
4. Whether the 10-detergent threshold should scale with the aggregation number (10 of 20 is half the belt; 10 of
   100 is a rounding error).
5. Whether an empty (protein-free) micelle is in scope, since the builder supports it and the panel would then
   cover both cases.
