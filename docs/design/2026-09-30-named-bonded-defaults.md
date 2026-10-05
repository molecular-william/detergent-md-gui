# The named Martini 3 bonded defaults, and what they change

The user pointed at `references/M3-Lipid-Parameters/ITPs/martini_v3.0.0_ffbonded_v2.itp` (added 2026-09-30, part of the
set vendored at commit `2121527`, DOI 10.1021/acscentsci.5c00755). This records what is in it, what it would change,
and what it would not, measured rather than assumed.

## What the file is

Not a plain `[ bondtypes ]` table. It is a **library of named generalised parameters**, one `#define` per bead
signature and context, which the set's lipid topologies then use:

    [ bondtypes ]
    #define b_C1_C1_mid   1  0.490  2800.0   ; middle of an alkane chain
    #define b_C1_C1_end   1  0.500  2800.0   ; at the end of the chain: internal AA conformations average longer

    71 bondtypes rows, 64 angletypes rows, no dihedraltypes.

The naming convention is the content: `<b|a|d>_<bead types>_<context>`. Contexts seen: `_mid`, `_end`, `_mid_5long`,
and ether/plasmalogen variants (`_ether`, `_plasm`). A pair therefore has more than one published value, chosen by
where it sits in a chain.

## What it changes for our DDM tail

The tail is three `C1` beads. The set's named defaults give it:

    middle bond   b_C1_C1_mid   0.490 nm, k 2800
    end bonds     b_C1_C1_end   0.500 nm, k 2800

Our current draft takes its `C1|C1` bond from whichever lipid molecule's own `[ bonds ]` line matched first, which the
generated topology shows as length 0.47 with k 3800. So this file corrects both numbers **and** supplies something the
draft has no notion of: a chain-end bond is not a chain-middle bond.

**Corrected 2026-10-02 (`30bb52e`).** This paragraph first read "for a three-bead tail that is one middle and two
end bonds", which describes a four-bead chain. The tail is three beads and its head bead is bonded to the sugar,
so only `TAIL1` is a terminus: the tail has **one end bond and one middle bond**, and the rule that produces
that is "a bond with a bead of degree 1 on either side is an end bond".

## What it does not change

The thirteen terms that still fall back are the sugar ring and the head-tail junction: `SP1r|SP1r`, `SP1r|SP4r`,
`SN6|SP4r`, `C1|SP1r` and their angles. **None of the sugar bead types appear in this file at all** — checked by name:
no `SP*`, `SN*` or `TC*` signature anywhere in it. Those gaps belong to the sugar parameter set or to a fit against an
atomistic reference; this file cannot close them.

## The change to make

1. Read the `#define` rows of `[ bondtypes ]` / `[ angletypes ]` / `[ dihedraltypes ]` into the bonded index, taking
   the bead signature from the name and the context from its trailing tokens.
2. Choose the context from the term's position: a bond whose bead has exactly one bonded neighbour in the mapping is an
   `_end` bond, otherwise `_mid`. The generator knows the graph; the index only knows the pair.
3. Rank these defaults **above** the lipidome's per-molecule `[ bonds ]` lines and **below** a detergent-specific
   reference (`references/martini-ddm.itp`, MAD). Rank 3 in `_KNOWN_...`-style terms: generalised beats incidental,
   specific beats general.
4. Record the macro name (`b_C1_C1_end`) in the term's provenance, so a reader sees which published name was applied
   rather than only its numbers.

Re-measure afterwards: the expectation is that the tail's terms move from an incidental lipid's values to the named
defaults, and the matched count stays 13 of 26 because the sugar gaps are untouched. If the count moves, that is a
surprise worth reporting rather than a success.

**Measured 2026-10-02.** Both landed: reference terms 12 -> 20, geometric fallbacks 13 -> 5, and the tail's two
`C1|C1` bonds read 0.500 nm at the terminus (`b_C1_C1_end`) and 0.490 nm on the bond that runs on into the head
(`b_C1_C1_mid`), both k 2800, with the macro names in the provenance. The count did move, and for the reason the
expectation gave: the molecule's own fit (`references/bartender/DDM.itp`) reaches two of the sugar pairs the
lipid file cannot.

## Measured: the ring scale, and what actually breaks the DDM run

Task 2.4's run, and the ring question with it, went as a controlled head-to-head: one mapping, one AA reference
(`2321ee23a536`), one set of settings, and the ring constraints the only difference between the arms.

| arm | run | ring constraints | outcome |
| --- | --- | --- | --- |
| A (control) | `860eb013a82c` | measured x 1.15 | failed in CG simulation, exit 139 |
| B (measured) | `e08dc53410f9` | measured x 1.0 | failed in CG simulation, exit 139 |

Both arms are verified in their own files. `stages/2_mapping/ring_targets.json` carries `raw_mean_nm` and
`target_nm`; arm B's ratio is exactly 1.0 (0.310205 -> 0.310205) against arm A's 1.15 (0.310205 -> 0.356736), and
the simulated `4_CG_sim/DDM.itp` carries the same six lengths. Arm B's 0.310/0.359/0.295 are the distances
BARTENDER's fit converged to.

**The ring scale is exonerated.** Arm B held every ring at the distance its own mapped trajectory measures -- the
1.15 removed entirely -- and failed at the same place, the same way, as the control. Whatever breaks this run, it
is not the 15%.

What the failure is: equilibration runs its 10 ps clean. Production is clean for ~125 ps, then the first LINCS
warning appears at step 6283 on a ring constraint (atoms 2-3, deviation 0.3%), and **within ten steps the
deviation is 7.0** on atoms 5-6 with the coordinates destroyed; the run limps on until GROMACS segfaults in its own
neighbour-grid code (`gmx::Grid::setCellIndices`) at ~200 ps. The simulated topology carries no ring-internal
angles, so this is not an over-constrained triangle.

**Next hypothesis, with its number.** The topology stage runs `ff_inter ... -constraints 1000000000`
(`execution/scripts/fit_topology.sh:16`), and Fast_Forward's own default for that flag is **10000**. The run
therefore keeps as *harmonic bonds* the terms FF would have turned into constraints -- including `S1B-S2A` at
**k = 12964.8 kJ/mol/nm²**, about ten times Martini's canonical bond constant (1250) and 4.6 times the named
defaults (2800). Its harmonic period at a 27 g/mol reduced mass is ~0.29 ps: ~14 steps per period at the 20 fs CG
timestep, against ~46 for a canonical Martini bond.

Two cheap independent tests, either one a single line: `-constraints 10000` (FF's own default, so the stiff links
become constraints and the timestep stops mattering for them), or keep the flag and run at 10 fs.

Not started as a refit, per Task 2.4: this says what to try next, not what the answer is.
