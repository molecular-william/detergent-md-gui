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
draft has no notion of: a chain-end bond is not a chain-middle bond. For a three-bead tail that is one middle and two
end bonds, and the difference (0.49 vs 0.50 nm) is small but it is the published distinction, not ours to collapse.

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
