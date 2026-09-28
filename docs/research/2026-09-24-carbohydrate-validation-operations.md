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
candidate**. The recognizer covers hexopyranose and hydroxymethyl furanose rings
and numbers them in the reference residue order, so the sucrose candidate
reproduces the `SUCR` entry of `references/martini_v3.0.0_sugars_v2.itp`: two
residues of three physical beads plus a massless TC4 ring site, typed
SP1r/SP4r/SP1r then SN6/SP4r/SP1r, with the bridge oxygen on residue 1 and one
linkage bond between the two glycosidic beads.
`tests/dashboard/integration/test_sucrose_reference_mapping.py` drives the
candidate route end to end, and `reference.conform` states the verdict in the
candidate's provenance rather than leaving it to a reader.

The mapping conforms; the equilibrium numbers do not come from the reference.
Ring constraint lengths are the mean all-atom COG distances scaled by 1.15, as
the paper derives them, computed from this repository's atomistic source, and
`reference.parameter_delta` reports each one beside the published value. On
2026-09-25 they agreed to within about 15%: 0.318-0.427 nm against
0.305-0.468 nm. Reproducing a mapping is not the same claim as reproducing the
published force field, and stereochemistry is never perceived from a bond graph,
so the candidate records `stereochemistry: unresolved`.

Coordinate units are decided in one place (`dashboard/models/sugars/units.py`):
a structure built from the molecule context holds nanometres and the packaged
SwissParam reference holds angstroms. The sugar topology writer and the mapping
export previously divided by ten unconditionally, which made every generated
constraint length and exported coordinate a factor of ten too small. The same
mistake made the bead-crowding figure meaningless in the other direction: the
radii were converted to angstroms while the distances stayed nanometres, so
every pair of beads counted as overlapping.

A carbohydrate whose ring no template covers -- ribose, a deoxy sugar, a uronic
acid, an N-acetyl sugar, inositol -- still produces a candidate. The ring is
mapped with the general rules the paper states for its own residues: beads named
A, B, C from the anomeric carbon, the ether oxygen in the last ring bead, about
four heavy atoms per bead, and a massless TC4 site per ring. Its types come from
the same chemistry rules the templates use, and where a fragment matches none of
them the candidate says so: the mapping editor shows a warning that the types
may need manual correction, and the candidate's `warnings` list carries the same
text. Those classes are unvalidated by construction, which is why the candidate
is still produced rather than refused.

For a reproducible short AA-to-CG diagnostic, select the saved sucrose mapping
in **New Run**, choose `draft-smoke`, and start an AA-CG run. The coordinator
creates the AA source and waiting CG child together. The run records the
molecule snapshot, mapping snapshot, seeds, GPU-enabled GROMACS commands, and
all stage logs. Once the child completes, queue a validation attempt for the completed source run
through `POST /api/jobs/<id>/carbohydrate-validation` and run a `Setup check` with
the `sucrose-martini3-paper-v1` target.

The validation attempt can publish the existing immutable
`analysis/surfaces/surface-comparison.html` Plotly artifact and SASA statistics
for AA, raw mapped, ring-scaled mapped, and simulated CG coordinates. These
plots are diagnostic for short trajectories. The paper's 200 ns geometry
sampling, 19-window transfer calculations, and 500 ns osmotic-pressure series
remain required before an evidence run can be complete.

## Completed Sucrose hand-off

**Status 2026-09-28: none of these records is present in this checkout.** An inventory taken for this
note found `runs/` holding only `.gitkeep`, the `jobs` table in `workspace/dashboard/jobs.sqlite3` with no
rows, and none of the four IDs below anywhere on disk. The IDs are kept as a record of what was run; the
data they name is gone. If a copy exists elsewhere, do not treat it as evidence: a CG topology generated
for a ringed mapping before the coordinate-unit fix described above has bead distances a factor of ten too
small, so a run of that vintage is misleading rather than historical. Regenerate the mapping and the run
from current code instead.

The workspace also held a stale pre-fix sucrose mapping draft, `mapping_candidate_49a51b28f7504bef887a3880a114c201.json`
(sha256 `000c1572724b65c5529dc850c4062505a6863237dfdbfd2db238a834c86c6d51`, eight beads of which four were
named TAIL1 to TAIL4 -- the artifact that showed the fructose ring shredded). It was deleted at the user's
request. The two Maltose drafts and the DDM draft were kept: the validation note cites the Maltose variants
by name, and the DDM draft is the packaged reference example.

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

## Bead identity in a two-residue sugar

Sucrose, lactose and trehalose are each one moleculetype with two residues, and the reference names every residue's
beads A/B/C/VS -- sucrose's fructofuranose donates the glycosidic bond and its glucose receives it, and the residue
number is what tells the copies apart. GROMACS addresses atoms by index, so that is legal; but everything downstream
of the catalogue keys beads by name, including the endpoint selections the panel sends, the PDB writer's serial map
and the viewer's index lookup. A repeated name therefore resolved to the first residue every time, and sucrose
rendered as one ring with the second ring's bonds pointing into it, with no error anywhere.

`models/compositions/topology.py` now keeps each atom's residue number and, where a name occurs more than once,
suffixes every occurrence with it, so the catalogue offers `A1`, `A2`, `B1`, `B2`, … and the single-residue sugars
keep the reference's own names. Whether a bead is a virtual site is a property of the file -- the sites a
moleculetype declares -- and is no longer recognised by the name `VS`, which stopped matching as soon as a name was
suffixed: the endpoint lists had begun to offer `VS1` and `VS2` as linkage beads, and a site with no coordinates
would have been drawn as one.

## Handoff checklist

When continuing this work:

1. Confirm the dashboard process is fresh and the representation and target
   endpoints return data for the selected molecule.
2. Confirm the candidate's `reference` block names the entry it follows (`SUCR` for sucrose) and that
   `reference.conform` returns no issues before using an automatic Sucrose candidate. Its
   `stereochemistry` stays `unresolved`: connectivity does not determine it.
3. Inspect the source run manifest and stage logs for the resolved GROMACS
   executable, GPU flags, input hashes, and exact commands.
4. Treat `metadata_only`, `insufficient_data`, and `diagnostic_only` statuses
   as blocking evidence gaps. They cannot be converted to `validated` by a
   successful queue or plotting operation.
5. Use the artifact index to resolve relative paths; absolute workspace paths
   are not HTTP routes.
