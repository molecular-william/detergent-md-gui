# Plan: MkVsites derivation and vsite-ready AA runs (2026-11-13)

Status: **phases 1 and 2 built** (approved 2026-11-13). Draft:
`docs/design/drafts/2026-11-13-molecule-virtual-sites.html`.

## What MkVsites is

MIT-licensed Python 3 tool (Larsson, Kneisz & Marklund, *J. Comput. Chem.* 41:1564–1569, 2020,
doi:10.1002/jcc.26198). It derives **missing** GROMACS virtual-site parameters from an ITP or RTP plus a force
field: dummy atom types/masses, dummy–dummy and dummy–anchor constraints, OH angle constraints, and the `.vsd`
entries `pdb2gmx` uses to construct the sites. Its own scope is terminal groups (a centre with 3–4 neighbours,
one heavy and the rest hydrogen) and OH angle constraints; it does not convert CH2/CH/NH, and it does not rewrite
a topology.

Probe on this repo's DDM:

- With `charmm36-jul2022.ff` every atom is an alien (`CR`, `OR`, `HCMM`, `HOR` are not in CHARMM36), so nothing is
  derived.
- With a minimal force-field overlay built from the ITP's own `[ atomtypes ]` and inline bonds/angles it derives
  `MCH3_1` and seven OH constraints.
- Their `topinspect.py` ITP→RTP helper crashes on the DDM ITP, so the RTP bridge is ours.

## Phase 1 — derivation core, CLI and molecule-block report

1. `packages/core/src/dashboard/models/molecules/vsites.py`:
   - `derive_text(text, *, force_field=None, kind='itp', residue=None)` and `derive_file(path, ...)`.
   - Parse ITP/TOP (one moleculetype) or RTP (one residue); atoms, bonds, angles, atom types.
   - Per-atom derivation (exact bond/angle rows), ported from MkVsites with attribution.
   - Output vsite types, OH angle constraints, force-field snippets (`.vsd`, constraints, dummy masses, atomtypes)
     and diagnostics; no topology change.
2. `packages/core/src/dashboard/cli/derive_vsites.py`: `python -m dashboard.cli.derive_vsites --itp PATH
   [--force-field DIR] [--out PATH]`, and `--rtp PATH --residue NAME`. JSON on stdout by default.
3. Route `POST /api/molecules/<id>/virtual-sites`: reads the molecule's inspected snapshot, resolves its
   `metadata.force_field` entry, and returns the report. Read-only; refuses an invalid molecule with the same
   sentence the catalogue gives.
4. New run molecule block: a **Derive virtual sites** button inside the folded molecule input block, with a short
   status and a folded report (counts, force-field snippets, diagnostics, raw JSON). The button appears for a valid
   AA molecule and is disabled while the request runs. It does not queue a run or change any setting.
5. Checks: unit tests for the formulas/snippets/CLI, an integration test for the route, a browser test for the
   button/report, and a DDM case (read-only) asserting `MCH3_1` and OH constraints.

## Phase 2 — vsite-ready AA runs (pdb2gmx route)

1. Add an AA run setting `vsite` (`none`/`hydrogens`/`aromatics`), advertised in `SETTING_SPECS`/`CHOICE_SPECS`.
2. At prepare, when it is not `none`:
   - build an RTP for the ligand from its ITP (one residue, explicit bond/angle/dihedral parameters),
   - build a force-field overlay (copy the run's force field, add the ligand atom types and any missing bonded
     types; add dummy types/constraints from the derivation; add the `.vsd` entry),
   - run `gmx pdb2gmx -vsite <choice>` on the molecule PDB to produce `molecule.gro`/`molecule.itp`,
   - hash and record the generated topology, the RTP/overlay inputs, the pdb2gmx command and its version, and the
     derivation report; the stored ITP remains the provenance, not the simulated topology.
3. Refuse with a named message when the derivation cannot supply a complete set (e.g. a construct with a missing
   angle, or a topology pdb2gmx cannot build); never silently fall back to all-atom.
4. Validate the result: atom count/charge/mass bookkeeping, `grompp` acceptance, and an energy/force comparison
   against the all-atom topology for one run before calling it usable.
5. Wire the same choice into the CG run's AA reference half only if the reference is built rather than consumed;
   a CG run consumes a published reference, so the setting does not apply there.

## Out of scope

- Extending MkVsites to CH2/CH/NH/all hydrogens.
- Rewriting the stored ITP in place.
- Aromatic virtual sites for ligands (pdb2gmx's `aromatics` is protein-oriented; the AA choice will be limited to
  what the derivation and pdb2gmx can actually construct, and the form will say so).

## Checks

- Fast/browser/slow tiers and ruff as usual; the derivation test is marked `slow` if the DDM case is expensive.
- Live: phase 1 needs no run; phase 2 needs one timed AA `draft-smoke` run whose topology is vsite-ready, plus
  `grompp` and a short production leg.
