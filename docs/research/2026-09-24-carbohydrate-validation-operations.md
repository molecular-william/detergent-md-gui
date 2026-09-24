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
