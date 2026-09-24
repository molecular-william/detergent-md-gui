# Carbohydrate Validation Workspace

## Status

Design approved in conversation on 2026-09-24. This document defines the
dashboard-controlled validation workflow for monosaccharide and disaccharide
CG candidates. It does not approve any candidate scientifically.

## Problem

The dashboard can generate and execute carbohydrate CG candidates, but its
current analyses are execution and mapping diagnostics. It cannot compare the
published TC4 representation with a controlled physical-only representation,
or run the three physical evidence classes used by the Martini 3 carbohydrate
paper:

1. molecular geometry and volume;
2. water-to-octanol transfer free energy;
3. concentration-dependent osmotic pressure.

The existing `Maltose-0-noVS` candidate removes both TC4 sites and the ring
constraint definitions. That is a larger topology change than removing the
virtual interaction centers alone and cannot isolate their effect.

## Goals

- Add dashboard controls for reproducible carbohydrate validation attempts.
- Preserve the current TC4 mapping as the reference representation.
- Add an explicit `physical_only_ring_constrained` representation that removes
  TC4 sites while retaining the physical sugar mapping, ring parent groups, and
  1.15 ring-distance constraints.
- Run geometry/volume, transfer-free-energy, and osmotic-pressure evidence as
  separate immutable analyses with source hashes, settings, targets, and
  uncertainties.
- Compare TC4 and physical-only results under identical source, seed, target,
  and protocol settings.
- Keep evidence status separate from mapping approval and production
  authorization.
- Reuse the existing analysis coordinator, isolated analysis worker, immutable
  attempt directories, and dashboard artifact display.

## Non-goals

- Validating polysaccharides, dextran, cellulose, membranes, glycolipids, or
  protein binding in this increment.
- Claiming that a successful short CG run is scientific validation.
- Replacing Fast_Forward mapping or bonded fitting.
- Adding arbitrary automatic bead-type optimization.
- Making osmotic pressure or transfer free energy available without cited
  experimental targets and uncertainties.
- Automatically approving a mapping when an evidence run completes.
- Deleting or rewriting existing runs, mappings, reference files, or reports.

## Scientific basis

The primary source is Grunewald et al., *A Consistent Martini 3 Coarse-Grained
Force Field for Carbohydrates*, J. Chem. Theory Comput. 2022, 18, 7555-7569,
DOI 10.1021/acs.jctc.2c00757. The pinned paper and topology metadata are
recorded in `docs/research/2026-09-24-martini3-carbohydrate-validation.md`.

The paper assigns TC4 sites during carbohydrate mapping, expands ring COG
distances by 15% to improve molecular volume, matches transfer free energies,
computes osmotic pressure for eight monosaccharides and two disaccharides from
0-2.5 molal, and tests solution behavior on larger systems. This project only
adopts the first three evidence classes. Maltose is not a direct disaccharide
entry in the pinned Martini 3 topology, so Maltose results remain a
molecule-specific extrapolation unless independent experimental targets are
provided.

## Representation model

Every validation request chooses one representation mode:

- `tc4`: the existing mapping, including massless TC4 beads, ring definitions,
  virtual-site parent exclusions, and ring constraints.
- `physical_only_ring_constrained`: a deterministic derived mapping with the
  same physical beads, atom ownership, bead types, ring parent groups, and
  1.15 scale, but no TC4 beads and no virtual-site exclusions.

The physical-only transformation is owned by a focused mapping helper with a
versioned transformation identifier. It must reject mappings that do not have
recognized ring definitions or that already contain unsupported virtual-site
relationships. It must preserve the source mapping identity and record:

```json
{
  "representation_mode": "physical_only_ring_constrained",
  "source_mapping_hash": "...",
  "transformation": "remove_tc4_retain_ring_constraints@1"
}
```

Mapping schema changes permit a ring definition without a virtual-site bead
only when the representation mode is physical-only. Legacy mappings and
ordinary TC4 mappings retain their current validation rules.

Topology generation emits ring constraints for both modes. It emits
`[virtual_sitesn]` and parent exclusions only for `tc4`. Physical-only
topologies therefore retain ring geometry without introducing massless
interaction centers. Mapping trajectory generation retains raw and 15%-scaled
coordinates for both modes; only the TC4 mode adds derived site coordinates.

## Dashboard workflow

The CG Bead Assignment workspace adds a validation control for a selected,
molecule-bound mapping:

1. Select `TC4 reference` or `Physical-only, ring-constrained`.
2. Select `Setup check` or `Evidence run`.
3. Select a target dataset with cited values, uncertainties, units, and
   conditions.
4. Review mapping hash, molecule snapshot, representation transformation, AA
   reference, force-field/tool versions, estimated work, and validation scope.
5. Submit an immutable validation attempt.
6. View separate geometry, transfer, and osmotic evidence panels and their
   overall status.

The dashboard never computes scientific pass/fail locally. It submits a
validated request and renders the published report. The report status is one
of `not_run`, `running`, `insufficient_data`, `failed`, `diagnostic_only`, or
`evidence_complete`.

## Validation tiers

### Setup check

The setup check creates the derived mapping and topology, verifies source
identity and output names, checks solvent and target availability, runs
`grompp` where possible, and validates report wiring. Short simulations are
allowed only as executable setup probes. Results are `diagnostic_only`.

### Evidence run

The evidence run follows the paper-aligned protocol recorded in its manifest.
The final minimums are:

- Geometry: at least 200 ns of sampled AA and CG trajectory data for final
  SASA comparison, with frame/block statistics.
- Transfer free energy: 19 nonequally spaced lambda windows, soft-core LJ
  decoupling in water and octanol, NpT sampling, and BAR estimates with
  uncertainty.
- Osmotic pressure: a concentration series spanning approximately 0-2.5
  molal, a flat-bottomed solute restraint, z-only pressure coupling, force/area
  pressure estimates, and block uncertainty. Paper-aligned production is 500
  ns per concentration.

Shorter settings may be used for setup checks but cannot produce
`evidence_complete`.

## Evidence outputs

Each immutable attempt publishes one report containing:

- mapping and derived-topology hashes;
- molecule and AA-reference snapshots;
- force-field, GROMACS, Python, MDAnalysis, BAR, and analysis-code metadata;
- exact commands, seeds, boxes, concentrations, lambda values, durations, and
  logs;
- raw analysis products and content hashes;
- geometry metrics: SASA, surface products, ring side/angle distributions,
  means, standard deviations, and block uncertainty;
- transfer metrics: water free energy, octanol free energy, transfer free
  energy, uncertainty, target residual, and target citation;
- osmotic metrics: concentration, pressure, block uncertainty, target
  residual, and completion status;
- paired TC4/physical-only differences when both attempts share the same
  source and target set;
- per-evidence state and an overall state.

The three required evidence keys are exactly:

```text
mapped_geometry
transfer_free_energy
osmotic_pressure
```

Existing bonded-distribution, topology, stability, and execution results remain
diagnostics and do not replace a missing evidence key.

## Data flow and ownership

- `dashboard/models/mapping_schema.py` validates representation-aware mapping
  documents.
- A focused mapping module derives the physical-only representation and
  records its transformation provenance.
- `dashboard/models/sugar_topology.py` emits mode-specific topology while
  preserving ring constraints.
- `dashboard/analysis/` owns geometry, transfer, and osmotic calculations and
  their report schemas.
- `dashboard/analysis/worker.py` copies and hashes sources, runs an isolated
  attempt, and publishes immutable outputs.
- `dashboard/execution/analysis_coordinator.py` validates and queues the new
  analysis kind using existing ownership and concurrency rules.
- `dashboard/models/evidence.py` evaluates the three-key carbohydrate
  evidence profile.
- Dashboard routes and mapping JavaScript submit requests and render results;
  they do not infer scientific status.

## Failure handling

- Missing AA source, target dataset, octanol parameters, or required tools
  blocks the affected operation before launch and records `insufficient_data`.
- A representation transformation failure blocks the complete attempt.
- A failed osmotic concentration point preserves completed points but leaves
  `osmotic_pressure` incomplete.
- Cancellation preserves logs and partial outputs and cannot count as a pass.
- Existing source trajectories, mappings, and prior reports are never
  overwritten.
- Re-running the same request creates a new immutable attempt with its own
  seed and source hashes.

## Testing and acceptance

Unit tests must cover representation transformation determinism, source/hash
provenance, ring validation, TC4 versus physical-only topology sections,
physical-only ring constraints, and legacy mapping compatibility.

Analysis tests must cover SASA report parsing, lambda/BAR input construction,
osmotic force/area calculation, uncertainty/block summaries, target residuals,
missing-data states, partial concentration failure, and immutable publication.

Integration tests must cover request validation, analysis queueing, source
copying, report publication, rerun separation, and evidence-profile evaluation.

Browser tests must cover representation selection, setup/evidence tier
selection, target and workload review, launch progress, failed and
insufficient-data states, report rendering, and the fact that evidence status
does not change mapping approval.

Acceptance requires:

1. Both representations can be generated from the same valid mapping without
   changing physical atom ownership.
2. Physical-only topology contains the same ring constraints as TC4 but no
   TC4 atom, virtual-site section, or parent exclusions.
3. Setup checks are reproducible and labelled diagnostic-only.
4. Evidence attempts preserve complete provenance and immutable outputs.
5. A missing target or incomplete physical evidence cannot produce an
   evidence-complete result.
6. TC4 and physical-only comparisons report paired differences under shared
   inputs.
7. No mapping is automatically approved or authorized for production by this
   workflow.
