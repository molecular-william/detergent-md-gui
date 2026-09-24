# Carbohydrate Validation Operations

The CG Bead Assignment tab launches validation for a completed source run. The
server snapshots the selected mapping and molecule context, derives the chosen
representation, and queues an immutable `carbohydrate-validation` analysis
attempt under the source run's `analyses/` directory.

Choose `TC4 reference` to retain the massless TC4 ring sites. Choose
`Physical-only, ring-constrained` to remove those sites while retaining the
physical bead assignments and 1.15-scaled ring constraints. This transform is
deterministic and records the source mapping hash and transformation version.

Use `Setup check` to verify files, topology sections, target selection, and
report wiring. Setup results are always diagnostic-only. Use `Evidence run` only
when the source trajectories and targets support the published protocol:

- geometry and volume use at least 200 ns of sampled AA and CG data;
- transfer free energy uses 19 nonuniform lambda windows, soft-core LJ, NpT
  sampling in water and octanol, and BAR uncertainty;
- osmotic pressure uses the 0–2.5 molal concentration series, a flat-bottomed
  solute restraint, z-only pressure coupling, force/area estimates, and about
  500 ns per concentration.

The local registry is `resources/validation/carbohydrates/targets-v1.json`.
Entries currently marked `metadata_only` expose their citation but deliberately
block evidence completion until measured values and uncertainties are entered.
Maltose is an extrapolative repository candidate because it is not a direct
disaccharide entry in the pinned Martini 3 carbohydrate topology.

Validation status is independent of mapping approval and production
authorization. A completed analysis proves that the requested calculations ran;
it does not establish a scientifically validated model without complete,
target-backed evidence.

## Sucrose diagnostic setup

The dashboard discovers sucrose from `molecules/Sucrose` when its SwissParam
topology and coordinates are present. Restart the dashboard after adding a new
molecule so the process loads the current validation routes and molecule
catalogue:

```bash
dashboard/.venv/bin/python -m dashboard
```

After the process is ready, verify that the live instance has loaded the
validation catalogue:

```bash
curl -fsS http://127.0.0.1:5000/api/mappings/representations
curl -fsS 'http://127.0.0.1:5000/api/mappings/validation-targets?molecule_id=Sucrose'
```

Stop or account for active workers before restarting a shared workspace. A
stale process can serve the dashboard while returning empty validation
controls even though the source files and routes are present.

In **CG Bead Assignment**, select **Sucrose** and use **Generate automatic
candidate**. The current sugar recognizer covers one hexopyranose ring and
keeps the remaining sucrose graph as a provisional connected draft. Its
limitations are stored in the candidate provenance; it is suitable for a
diagnostic execution check, not an official Martini sucrose parameterization.

For a reproducible short AA-to-CG diagnostic, select the saved sucrose mapping
in **New Run**, choose `draft-smoke`, and start an AA-CG run. The coordinator
creates the AA source and waiting CG child together. The run records the
molecule snapshot, mapping snapshot, seeds, GPU-enabled GROMACS commands, and
all stage logs. Once the child completes, select the completed source run in
the carbohydrate validation controls and run a `Setup check` with the
`sucrose-martini3-paper-v1` target.

The validation attempt can publish the existing immutable
`analysis/surfaces/surface-comparison.html` Plotly artifact and SASA statistics
for AA, raw mapped, ring-scaled mapped, and simulated CG coordinates. These
plots are diagnostic for short trajectories. The paper's 200 ns geometry
sampling, 19-window transfer calculations, and 500 ns osmotic-pressure series
remain required before an evidence run can be complete.

## Completed Sucrose hand-off

The first reproducible diagnostic run used the following preserved records:

| Record | ID or location |
| --- | --- |
| AA source run | `66e1b55f6a3d` |
| Corrected CG consumer | `5e70070d287f` |
| Validation analysis | `3ef7c9eb4e5b` |
| Surface comparison | `analyses/carbohydrate-validation/f6944146aa15e3049e78db46404d4d09bc847340d097613ff12be5ddcd646d1f/3ef7c9eb4e5b/output/db16df1bc5db600bae56ad2045c37d5e0dc54d6b2dc3161831ed2b603b404706/analysis/surfaces/surface-comparison.html` |

The report was generated from the completed CG consumer and is served through
the normal run artifact endpoint:

```text
/api/jobs/5e70070d287f/artifacts/<path-from-artifact-index>?inline=1
```

The first CG attempt (`7d4161f125b2`) is intentionally retained as a failed
diagnostic record. Its provisional mapping contained a redundant cycle in the
tail graph; the corrected placement logic skips already-placed linked
components while preserving the source topology. Do not delete the failed
attempt when diagnosing future regressions.

Observed SASA means for this short diagnostic were approximately 5.847 nm²
(AA), 5.343 nm² (raw mapped), 5.535 nm² (ring-scaled mapped), and 5.817 nm²
(simulated CG). The simulated CG segment covered only 50 ps, so these values
are execution evidence and visualization inputs, not convergence evidence.

## Handoff checklist

When continuing this work:

1. Confirm the dashboard process is fresh and the representation and target
   endpoints return data for the selected molecule.
2. Confirm the mapping provenance says `provisional` before using an automatic
   Sucrose candidate.
3. Inspect the source run manifest and stage logs for the resolved GROMACS
   executable, GPU flags, input hashes, and exact commands.
4. Treat `metadata_only`, `insufficient_data`, and `diagnostic_only` statuses
   as blocking evidence gaps. They cannot be converted to `validated` by a
   successful queue or plotting operation.
5. Use the artifact index to resolve relative paths; absolute workspace paths
   are not HTTP routes.
