# PDC placement: simplify the belt algorithm

Status: built (2026-11-25). The behaviour-preserving refactors and both structural simplifications the user chose
are in.

## What the algorithm is now

`pdc_placement.place_detergents` has four moving parts:

1. **Shape**: `_belt_cylinder` measures the transmembrane cylinder and draws its sites; `_self_assemble` and
   `pack_micelle` handle the sphere/random shapes.
2. **Slot draw**: `_cylinder_sites` lays the golden-angle ladder and tries bounded local offsets per slot through
   `_belt_trial_verdict` (head clearance, site spacing, body clearance, body gap). A failed slot also tries two
   absolute heights just outside the band (`BELT_TRIAL_BEYOND_NM`) before being left empty.
3. **Final geometry**: `place_detergents` translates the belt along the normal (`_translate_belt`), draws the
   conformation library, and parks problem heads above/below the band (`_park_belt_problems` ->
   `_park_problem_sites`), balanced between the two sides.
4. **Bookkeeping**: the band's radius/reach/volume are recomputed by `_refresh_band_geometry`; `capacity()` measures
   how many detergents the shape holds by rerunning placements.

## Built in this slice (no behaviour change)

- **One geometry-number implementation.** `_belt_cylinder` used to compute the surface mean/min/max, the belt reach and
  the volume itself, and `_refresh_band_geometry` computed the same numbers again after parking. The cylinder now
  builds its record and calls `_refresh_band_geometry`; the parking calls it again on the final geometry. One
  implementation, one place to change.
- **One candidate builder.** The slot draw and the parking both built "a head at (heading, height, radius) plus its
  tilted direction"; `_belt_site` now does that once.
- **One fewer gate parameter.** `_belt_trial_verdict` no longer takes the molecule's reach: it derives it from the
  profile it already has. Both call sites got shorter.
- **The parking reuses `body_clearance`.** `body_clearance` gained the drawn `twist`, and the parking uses it for the
  template and drawn bodies instead of keeping its own protein-by-body distance matrix and a parallel list of drawn
  beads. The checks are identical; the code and the per-site cost are smaller.
- **Named steps out of `place_detergents`.** `_translate_belt` and `_park_belt_problems` are separate functions, so
  the orchestrator reads as shape -> draw -> translate -> park -> validate -> report. The module is 1,772 lines
  (was 1,794) and `place_detergents` about 268 (was about 300).

Verified identical on the exact 2ydo + NG case: 19 moved, 8 inside, 5 above / 6 below, 0 far, 0 too-close, same
radius and reach. Checks: fast tier 3,218 passed / 1 xfailed; browser 430 passed; pdc fast area 879 / 1 xfailed; ruff
clean.

## Built: the capacity search is deleted

`capacity()` bisected between 1 and the requested count, assuming "if N fits, N-1 fits". The golden-angle ladder
breaks that: on the exact case 155 detergents place 144, but the bisection answered **18** -- a count that fits, but
far below what the shape keeps -- at the cost of many recursive placements. `capacity()`, `_capacity_sentence`,
`measure_capacity`, the `capacity_aggregation` report/basis field and the panel's "Use the measured count" button are
gone. The count gate's sentence now names the number the placement kept: "this placement keeps 144 of the 155
detergents asked for". The preview's refusal carries that sentence; nothing claims a largest count.

## Built: one outside-band pass

The slot draw's `BELT_TRIAL_BEYOND_NM` fallback and the parking's outside search were two implementations of "find a
place outside the band". Now:

- `_cylinder_sites` leaves a slot whose in-band trials fail **empty**, with its base geometry in `rejected_slots`.
- `_park_problem_sites` runs one outside-band pass. `_outside_site` is the search: the side with fewer placements so
  far, the `BELT_PARK_OUTSIDE_NM` heights beyond each face, and the small heading turns; `_gated_site` is the one
  acceptance check (all gates, the drawn body, the far threshold).
- Empty slots are filled first (a complete count is what avoids a refusal), then the far/too-close placed heads are
  parked. The band record's `rejected`/`rejected_slots` lose the slots that were filled, and `radial_repair.filled`
  states how many.
- Conformations are drawn for every slot the ladder may offer and trimmed to the placed count, so a filled slot has
  its own entry and the existing sites keep their stream prefix.

Measured: the exact 2ydo+NG case has no empty slots, so it is unchanged (0 filled, 19 moved, 8 inside, 5 above/6
below). On a 280-slot ring (solid 2.4 nm protein, 0.4 nm molecule) the pass fills **all 280** (the draw alone kept
255); at 600 it fills 288 and still refuses with 517 placed. Checks: fast tier 3,213 passed / 1 xfailed; browser 430
passed; pdc fast area 874 / 1 xfailed; ruff clean.
