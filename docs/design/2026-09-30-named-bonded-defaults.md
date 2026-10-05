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

### Arm C: the constraint threshold, and six causes eliminated by measurement

Arm C (`6404c3951674`) is arm A's mapping, reference and settings with one line changed: `fit_topology.sh` passes
`-constraints 10000` (FF's own default) where it passed `1000000000`. Verified in the run's own files -- the
prepared script reads `-temperature 303 -constraints 10000`, and FF's output writes the `S1B-S2A` link as
`2 5 1 0.273` inside `[ constraints ]` with the harmonic form under an undefined `#ifdef FLEXIBLE`. The stiff link
is therefore rigid in the simulated topology.

**It failed too, and sooner**: `Constraint error in algorithm Lincs at step 5640` (112.8 ps), where arms A and B
reached 125-200 ps. The first violation is now on the new constraint itself (atoms 2-5, rms 2.90).

What has been measured and eliminated, in order of how much it cost:

| candidate | the measurement that eliminates it |
| --- | --- |
| the ring scale (1.15) | arm B held every ring at its measured distance and failed identically |
| the stiff harmonic link (k 12964.8) | arm C made it a constraint and the run failed sooner |
| an integration instability from that constant | same as above: removing it from the integrator changed nothing |
| energy pumping by a wrong bonded term | arm C's `md.edr` is flat: potential -14850 +/- 120 kJ/mol across all 113 ps, temperature 301.4 K |
| the box or a periodic image | dodecahedron 5.013/5.013/3.545 nm; the solute spans 1.008 nm along the smallest axis, leaving 2.54 nm of clearance against a 1.35 nm cutoff |
| the missing barostat and its -583 bar | the maltose run (`22075892b606`) sits at **-526 bar** and completes 200 ns in the same construction with the same scripts |
| bonded pairs sharing the nonbonded interaction | the published `SUCR` entry's `[ exclusions ]` is `4 1 2 3` and nothing else -- the same convention this topology follows |

What is left standing: the failure is **DDM-specific**, it begins on a bead adjacent to the ring-1/ring-2 link
(atoms 2-3, 2-5, 5-6 across the three arms), and the two-molecule sugars run the identical pipeline to 200 ns.
The cheapest discriminating experiment is therefore a control rather than another variant: **the same mapping with
the three `C1` tail beads removed**, which turns DDM into a two-ring sugar comparable to the ones that work. It
survives and the tail is implicated; it fails and the linkage is.

### Arms D and E: the published protocol, and the one number that separates DDM from the reference

The user read the Martini 3 paper's Methods, which turned up the one part of the published CG setup this project
had never executed. "General setup for CG molecular dynamics simulations and analysis" (and the carbohydrate
paper's own protocol, which restates it for exactly this system) prescribe a **Parrinello-Rahman barostat at 1 bar,
tau_p 12 ps** for production. Our CG templates carry `Pcoupl = parrinello-rahman`, `tau_p = 12.0`, `ref_p = 1.0`
-- the papers' numbers -- and `cg.py`'s `mdp_integration` stamped `pcoupl = no` over them (`a20d844`), so every CG
run this project has done was NVT with `ref_p` and `compressibility` dead keys.

| arm | run | the variable | outcome |
| --- | --- | --- | --- |
| D | `207ff34ce8bc` | the barostat restored, beta 4.5e-5 | failed at 72.5 ps |
| E | `5bb303eb9ff5` | D + the equilibration at 10 fs | failed at **446.0 ps** |

The barostat engaged: arm D's mean pressure is **1.36 bar** with the volume settling at 81.1 nm3, against the
NVT arms' **-583 bar** -- a ~9% contraction to the correct density. It failed anyway, and sooner.

Arm E is the best result of the five: **446 ps**, 2-6x the others, from the one change that made the starting state
better rather than the system stiffer. Its failure is the same one, at the same pair, after 445 ps of clean
dynamics: a 2% deviation on a ring constraint, then eleven steps later the `S1B-S2A` link explodes.

**What the reference says about that pair.** Every two-ring sugar in `references/martini_v3.0.0_sugars_v2.itp`
joins its rings with a bond of **0.357 nm (LAC), 0.369 (SUCR) and 0.417 (TREH)**, at k 11250, 6200 and 9000.
DDM's link is fitted at **0.273 nm, k 12964.8** -- 24% shorter than the shortest published one and the stiffest.
Measured on arm E's own starting geometry, that pair sits at 0.282 nm while the closest *non-bonded* pair in the
molecule is 0.407 nm: the link is held closer than every other contact the molecule has, including the ones that
are supposed to be soft. Nothing else in the molecule is like that -- the ring constraints are 0.275-0.368 nm and
the published links are of the same order as their ring constraints, not below them.

That is the next hypothesis with its number, and it is checkable: lengthen the link to the reference's own range,
or find out why this mapping puts the two rings closer together than the reference's disaccharides do.

### Arm F, and the correction it forces: the onset is stochastic, not tuned

| arm | run | the variable | failed at |
| --- | --- | --- | --- |
| A | `860eb013a82c` | 1.15, `-constraints 1000000000`, 20 fs eq | **858.4 ps** |
| B | `e08dc53410f9` | ring scale 1.0 | 199.6 ps |
| C | `6404c3951674` | the link as a constraint | 113.2 ps |
| D | `207ff34ce8bc` | + Parrinello-Rahman at 1 bar | 72.5 ps |
| E | `5bb303eb9ff5` | + 10 fs equilibration | 445.9 ps |
| F | `c48c50265874` | + 5 fs equilibration (the user's call) | **53.5 ps** |

Arm E looked like a trend when it was read: 446 ps against the 125-200 ps of the arms before it. **It was not one.**
Arm F, the same idea taken further, failed at 53 ps -- earlier than everything -- and re-reading arm A's own log
(rather than the first warning I had quoted for it) shows it reached **858 ps**, the longest of the six.

So the honest reading is that the onset is **stochastic across an order of magnitude** (53-858 ps) for
configurations whose physics barely differs, and none of the six variables -- ring scale, link stiffness, link
type, pressure coupling, equilibration step at two values -- moved it out of that band. Two runs of the same idea
are as far apart as either is from the control.

What that leaves is the structural observation above, which is not a tuning knob: the link is held 24% shorter
than the shortest published disaccharide link and closer than any other contact the molecule has. A contact in that
part of its own potential is exactly the kind that fails stochastically -- it is held in a steep region, and a rare
fluctuation tips it. Every arm failed at that pair; none of them failed anywhere else.

The 10 fs and 5 fs equilibration steps are both defensible on the Methods' authority (equilibration is excluded
from the 20 fs rule), and neither is evidenced to help. That is a decision for the user, not a result.
