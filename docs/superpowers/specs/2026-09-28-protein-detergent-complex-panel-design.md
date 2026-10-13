# Protein–detergent complex panel — design

## Status

Decisions taken by the user on 2026-09-28 (recorded at the end); nothing is implemented yet. Builds on the paused
micelle builder whose architecture was approved on 2026-09-14
(`2026-09-14-detergent-micelle-builder-design.md`); that design's pipeline is the reference for how detergents
are placed, and its implementation under `micelle/` is a working skeleton, not a validated model.

§1 and §4 (the box), §3's belt clearance and §7's belt contact criterion are amended by
`2026-10-05-membrane-frame-pdc-design.md`, which puts the protein's orientation, the detergent belt and the box in
the membrane frame OPM states rather than in a principal-axis guess.

## Goal

A second simulation workflow beside the single-molecule one: place a membrane protein in a box, build a
detergent belt around it the way the micelle builder does, solvate and ionise it, run Martini CG MD until a
micelle has formed, extend that to 1 µs, and back-map the final snapshot with CG2AT-align. The whole setup is
visible in an NGL viewer before anything is run. Empty (protein-free) micelles are in scope.

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
| Back-mapping | CG2AT2 (`github.com/owenvickery/cg2at`), vendored like `tools/bartender/` | Runs from source; its `-o align` is the requested method |

`nglview` is not used: it is the Jupyter widget. The library underneath, NGL.js, is already vendored here.

## Inputs

Protein structure (PDB), detergent template id, aggregation number, integer seed, salt concentration (default
0.15 M), CG durations (default 100 ns assessment + 900 ns extension), the placement mode (lattice, the default, or
self-assembly — §3), stage settings for the mdrun budget, and an
optional display name. Every build is immutable and seeded; no global RNG. A protein-free build supplies no
protein and skips the protein stages.

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

Two modes, both seeded and both recorded on the run (`placement_mode`); a build states which one it used.

- **Self-assembly — the requested route.** The detergents are placed **at random** inside the box the protein is
  inserted into (§1): uniform positions, rejection-sampled so that none is within the placement clearance of the
  protein and no two are within the builder's overlap gate, and CG MD then lets the belt find its own arrangement.
  This is MemProtMD's Self Assembly route (`PDB -> Memembed -> martinize2 -> self-assemble -> CGMD -> CG2AT`) applied
  at the build. The seed is the whole of the randomness, so the same seed rebuilds the same placement and a different
  seed rebuilds a different one; the placement region is §1's box, so what the detergents fill is what the box states.
- **Lattice — kept as the other mode.** The micelle builder's deterministic lattice, scoring and bounded repacking,
  with the protein in place: exact aggregation count, headgroup-outward orientation, and the builder's hard overlap
  gates. The seed chooses the lattice's phase, and this is the placement every existing run had.

In both modes, protein-relative clearance is the builder's minimum-distance gate; no hydrophobic-belt check exists in
this code, and the belt is defined by `2026-10-05-membrane-frame-pdc-design.md`. A placement that cannot satisfy the
gates writes diagnostics and produces no run, as in the original design. For a protein-free build the same placement
runs with the protein-relative terms switched off, so an empty micelle — placed by either mode — is one code path
rather than a second builder.

Lattice stays the default, so no existing build's placement moves; self-assembly is selected explicitly until a real
run says the self-assembled belt is better.

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

### 7. Micelle-formation assessment — decided

A detergent counts as *in the micelle* when its tail beads are within **0.6 nm** of another detergent's tail
beads, and the resulting contact graph's largest connected cluster holds at least the requested aggregation
number. A protein-containing build also requires that cluster to touch the protein's hydrophobic belt; for a
protein-free build that requirement does not apply. Detergents in smaller clusters are *not in the micelle*. The
report records the cluster sizes, the contact distance used, the fraction of the requested count in the largest
cluster, and the protein contact count, so a disagreement with the criterion can be re-judged from the artifact
without re-running anything. The contact distance and the cluster-size requirement are settings, not constants,
so changing the criterion costs a re-run rather than a code change.

### 8. Removal and restart — decided

Detergents not in the micelle are removed and the run **continues** from the assessment-phase checkpoint, since
the request says restart only on the threshold. If more than **10% of the requested aggregation number** were
removed — with a floor of one detergent, so a small build still has a meaningful rule — the assessment phase is
re-run from scratch with new initial velocities, because a system that lost that fraction has not formed the
intended aggregate and continuing would sample the wrong state. A retry changes **only the velocities**: the
placed system is kept, so attempts differ in one documented way and stay comparable. The loop is bounded at
**3 attempts**, and every attempt records its seed and its removal count.

### 9. Extension phase

A further 900 ns, continued from the retained checkpoint (`gmx convert-tpr -extend`), so the total CG sampling is
1 µs. Assessment is re-run at the end and compared with the assessment-phase report.

### 10. Back-mapping — decided

The final snapshot is converted to atomistic detail with **CG2AT2** (`github.com/owenvickery/cg2at`) using its
**align** method (`-o align`, output `FINAL/final_cg2at_aligned.pdb`), which fits supplied atomistic fragments to
the CG structure and morphs them towards the atomistic reference.

- It runs from source and needs no installation; its requirements (Python 3, GROMACS > v5, numpy, scipy) are
  already satisfied here. It is vendored under `tools/` (gitignored, like `tools/bartender/`), with the release or
  commit recorded in the run manifest, in the same spirit as the vendored NGL asset.
- Its fragment database covers CG Martini 2 and 3, so the invocation uses `-fg martini_3-0_charmm36` with the
  matching `-ff`, because these runs are Martini 3.
- `-silent` is passed so a stage cannot block on an interactive question.
- It needs the coarse-grained system **and** the original atomistic structure (both of which the build has) and
  it invokes GROMACS internally for a short minimisation and a steered-MD morph, so it is a real stage with a
  log rather than a post-processing afterthought.

## Panel

- **Setup sub-panel**: protein upload/selection (or none, for an empty micelle), detergent template, aggregation
  number, seed, salt concentration, the two durations, and the stage settings (shared with the other workflow).
- **System view sub-panel**: NGL, showing the built system after setup and the final snapshot after each
  assessment. Water and ions are hidden by default (they dominate the atom count and hide the science); the
  protein, detergents and box edges are shown. The viewer is fed by a server-side PDB written from the actual
  coordinates, in the same way the Molecule Combination panel is fed, so the picture cannot disagree with the
  system.
- **Status sub-panel**: the stages with their state, the assessment verdict with the numbers behind it, the
  removal and retry history, and the provenance (template, seed, tool versions, the recorded mdrun flags).
- The panel is a thin client: science stays in `micelle/` and the adapter.

## Validation gates and claims

Hard gates before a run is admitted: protein parsed and finite (when one is supplied), template resolved, seed an
integer, aggregation number ≥ 1, box extents positive after extension, no severe detergent overlap, orientation
valid, molecule counts consistent, and `gmx grompp` succeeding for every stage. The assessment criteria are
**proxies for aggregate formation, not evidence of equilibration**; 1 µs of Martini CG sampling is a stated
target, not a convergence claim, and the panel must label the product `candidate-unvalidated` exactly as the
composition panel does for its own candidates. Back-mapped output is the same product at higher resolution and
carries the same label.

## Decisions taken by the user (2026-09-28)

1. **Micelle criterion**: the contact-graph criterion in §7, as proposed, with its distance and cluster-size
   requirement exposed as settings.
2. **Back-mapping**: CG2AT2 from `github.com/owenvickery/cg2at`. Its `-o align` is the requested CG2AT-align
   method, and its fragment database covers Martini 3, so there is no version conflict with these runs.
3. **Retry policy**: 3 attempts, velocities only.
4. **Removal threshold**: a fraction of the requested aggregation number — **10%**, with a floor of one
   detergent.
5. **Scope**: protein-free (empty) micelles are included.
