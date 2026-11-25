# PDC belt: total-height vertical spread and a far-head repair

Status: built (2026-11-25, the user's decisions in the questions this plan answers)

Supersedes the band part of `docs/plans/2026-11-25-pdc-belt-form-coverage-and-placement.md`: the 4 nm spread is the
**total** height of the band, not the half-height.

## What the user asked for

The user saw detergents placed far from the belt on 2ydo with NG and proposed: find the detergents that are too far
out, using a distance threshold to the other detergents' centre of mass, and try to place them slightly higher or
lower than the belt. The questions this plan answers:

1. **4 nm means the total band height** (so it spans ±2 nm about the membrane mid-plane), not a half-height of 4 nm.
2. The outlier ruler is the **sideways distance from the belt's axis** (equivalently, how much a head's local surface
   exceeds the belt's median), not the distance to the centre of mass.
3. The retry may move a head **up to 1.5 nm** higher or lower, and nowhere else.
4. If no legal nearby spot exists, the head **keeps its original position** (the count never drops).

Why the centre-of-mass ruler was not used: on the tall band it mixed height into the number. On 2ydo + NG it flagged
55 of 154 heads at mean + 0.5 nm while still missing 2 of the 11 that were genuinely far out; at mean + 1.0 it caught
only 6 of 11. The sideways measure flags exactly the 11 NG / 8 DDM heads that look detached.

## Tasks

1. **Setting**: `belt_vertical_spread_nm` is the band's total height, default 4.0 nm, advertised by the adapter and
   stated by the form (1–20 nm, Default button). The build halves it for the placement; the preview and admission do
   the same. Two retired spellings stay readable for an old payload, clone or preset: `belt_vertical_half_nm` (the
   half-height) and `belt_vertical_spread` (the oldest multiple of the detergent length). A payload that states the
   total wins over either.
2. **Repair**: after the belt draw, measure every placed head's sideways distance from the cylinder axis, take the
   median as the belt's own radius, and flag a head more than `BELT_FAR_RADIAL_NM` (0.75 nm) beyond it. In ladder
   order, each flagged head tries the heights in `BELT_RECLAIM_HEIGHT_NM` (0.5, −0.5, 1.0, −1.0, 1.5, −1.5 nm) at its
   own heading, clipped to the band, re-measuring the local surface at each. A candidate replaces the head only when
   every existing gate passes (head clearance, site spacing, body clearance, body gap) **and** the head lands back
   inside the belt. Otherwise the original position stands. The band record gains `radial_repair` with the median,
   the threshold, the trial heights and how many heads moved or stayed far.
3. **Tests and docs**: adapter default/retired precedence, the build's total→half conversion, two unit tests for the
   repair (moved / kept), the browser fields and defaults, GUIDE/HANDOFF.

## Acceptance criteria

- A fresh form shows `Vertical spread = 4`, and a build with no band setting writes a band spanning ±2 nm.
- An old payload stating only the retired half-height or the multiple keeps the band it was placed with.
- A head further than 0.75 nm beyond the belt's median is re-tried at most 1.5 nm higher or lower; it moves only if
  every gate passes and it lands inside the belt, and otherwise stays exactly where the draw put it.
- The band record states what the repair did.

## Execution record (2026-11-25)

Implemented as above. **Measured consequence, which the user should know:** on 2ydo chain A, NG, 155 detergents, seed
20261125, the 4 nm total band places **144 of 155** (11 slots rejected, so the preview refuses the count; the
capacity bisection reports 18, a valid count that all three of its seeds accept, but very conservative because the
ladder's fit is not monotonic in the count) where the old ±4 nm band placed 154. At a count of 18 the preview is valid,
places all 18, and the repair moves one head. The conservative ±1.5 nm retry found **no** legal spot for any of the
16 NG / 7 DDM heads
still outside the belt: the neighbours' bodies and the minimum body gap block every candidate, and some candidates
land outside the belt even when legal. At the old ±4 nm band the same retry moved 1 NG and 3 DDM heads. Next levers,
if wanted: allow up to ±2.5 nm plus a small sideways turn (a dry run moved 8 of 11 NG and 7 of 8 DDM at the tall
band), allow an inward radial nudge down to the median, or keep 155 by using the taller band.
