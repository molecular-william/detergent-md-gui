# PDC placement: simplify the belt algorithm

Status: partially built (2026-11-25). The behaviour-preserving refactors below are in; the two structural proposals
need the user's decision because they change what a refusal says or how an empty slot is reclaimed.

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

## Proposal 1 (needs a decision): delete the capacity bisection

`capacity()` bisects between 1 and the requested count, assuming "if N fits, N-1 fits". The golden-angle ladder
breaks that: on the exact case 155 detergents place 144 (so 155 does not fit), but the bisection reports **18** -- a
count that does fit on its three seeds, but far below what the shape keeps. It is also the most expensive path (many
recursive placements) and its "use the measured count" button sets a count that changes the ladder, so the new count
may not fit either.

Simplification: drop `capacity()` and report the count the requested placement actually kept (`len(centers)`), which
the refusal already knows. The sentence becomes "this placement keeps N of M" and the button sets N. That removes the
bisection, its recursive placements, and the false "largest count" claim. It changes the refusal wording and the
number the button offers, so it is the user's call.

## Proposal 2 (needs a decision): one outside-band search instead of two

The slot draw's `BELT_TRIAL_BEYOND_NM` (a failed slot tries two heights just outside the band) and the parking pass's
outside search (placed problem heads try two sides, heights and small heading turns) are two implementations of
"find a place outside the band". A single pass could handle both: the draw records a failed slot as empty, and one
"place outside the band" pass tries the empty slots and the placed problem heads with the same heights/turns and
gates. That removes a constant, a trial list and a second outside-placement path, and would likely reclaim more empty
slots because empty slots would get the same turns the parking has. It is a bigger change (a rejected slot becomes a
candidate for placement, which the count gate then sees), so it goes behind a plan/decision before code.
