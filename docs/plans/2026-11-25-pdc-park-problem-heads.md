# PDC belt: park protruding and too-close heads above or below the band

Status: built (2026-11-25, the user's decision after looking at 2ydo + NG)

Supersedes the repair section of `docs/plans/2026-11-25-pdc-belt-outlier-repair.md`: the ±1.5 nm in-band nudge did
not reclaim the heads the user saw, so a problem head is now moved **outside** the band.

## What the user asked for

On 2ydo + NG the user still saw detergents "obviously protruding out of the detergent belt" and detergents "too
close to the protein". Both should be "put above or below the belt". The previous repair only tried heights within
1.5 nm of the site and inside the band; at the band and packing actually used it moved none of them.

## The exact case (from the dashboard log)

`155` NG detergents, 2ydo chain A, seed 12253886, `belt_vertical_spread_nm=5.5` (half 2.75), `belt_gap_nm=2.7`,
`belt_offset_nm=-0.5`, `min_body_gap_nm=0.35`, `belt_axial_window_nm=1.0`, `belt_outlier_distance_nm=0.5`, and the
stored 2000-conformation library `e1ca152b0b1650ed`. Before: refused ("detergent too close to the protein: 0.484 nm
< 0.5 nm"), 18 heads beyond the belt's median + 0.5 nm and 1 head too close (the translation put it there), only 6
reclaimed. The too-close head is the belt's vertical translation moving a gated site into the protein: the old code
gated the unshifted sites and only re-checked after translating.

## Decision and rule

- **Park problem heads above or below the band.** A head is a problem when (a) it is more than
  `belt_outlier_distance_nm` beyond the belt's median sideways distance (0 turns this criterion off), or (b) its head
  or its carried body is closer to the protein than its gate. Case (b) uses the template body and, when a
  conformation library is drawn, the drawn body too.
- **Trial positions**: at the head's own heading, the six small in-band heights first (`BELT_PARK_INSIDE_NM`,
  ±0.5/1.0/1.5 nm clipped to the band), then the heights just outside each face (`BELT_PARK_OUTSIDE_NM`, 0.5 to
  2.5 nm beyond). The first candidate that passes every gate, keeps the drawn body clear, and (for the far criterion)
  lands back inside the belt replaces the head.
- **No legal spot**: the head keeps the draw's position, so the count never drops. A too-close head is parked even
  when the outlier distance is 0, because leaving it would refuse the run.
- **Run on the final geometry**: the parking pass runs in `place_detergents` after the belt's vertical translation
  and after the conformation draw, so it sees the head/body that will actually be stamped. The band's radius,
  reach (including the drawn library bodies), volume and `placed_axial_max_nm` are recomputed from the moved sites.
- **Record**: `radial_repair` now states the distance, median, threshold, both height sets, `far_initial`,
  `moved`, `still_far`, `too_close_initial` and `still_too_close`.

## Result on the exact case

Valid, no reasons. 18 far + 1 too-close heads; **19 moved; 0 far and 0 too-close remain**. The closest head to the
protein is 0.652 nm (gate 0.5). The belt's recorded maximum radius drops from 6.403 to 4.550 nm. The preview takes
1.34 s and its cell grows: the stated z of 11.606 nm is written at 13.926 nm because the parked heads reach further
above/below the belt. The preview records that in `box_notes`; the queue's admission refuses a stated cell that
cannot hold the system, so the z field should be cleared or raised (the panel's Auto writes the preview's own box).

## Checks

Fast tier 3,216 passed / 1 xfailed; full browser tier 430 passed; pdc fast area 878 / 1 xfailed; ruff clean.
Unit tests pin the parked-outside-band case, the too-close case, the outlier distance's default/large/off behaviour
and the no-legal-spot case; the surface-rule and vertical-translation tests run with the far criterion off so they
measure the geometry they name. The mutation check keeps its documented 9 caught / 1 stale / 1 control.
