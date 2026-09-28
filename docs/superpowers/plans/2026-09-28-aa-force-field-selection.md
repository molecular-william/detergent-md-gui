# AA force-field selection, and the paper's atomistic reference protocol

## Why

The published Martini 3 carbohydrate constraints (Grünewald et al., JCTC 2022,
`10.1021/acs.jctc.2c00757`, pinned in `references/martini_v3.0.0_sugars_v2.source.json`) were built from
atomistic reference simulations run with **three** force fields. Our pipeline runs exactly one
(`charmm36-jul2022`), so comparing our derived geometry against those constraints confounds the mapping with
the force field. The open residual from the 200 ns ensemble work — ring 2's A-bead pairs about 15% below the
published lengths while ring 1's land within 5% — is either a mapping-definition difference or a force-field
difference, and a second force field is what tells those two apart.

## What the paper did (read from the full text, not from memory)

| force field | temperature | water | atomistic topology made with |
| --- | --- | --- | --- |
| GLYCAM06 | 310 K | TIP3P | itp from Glycam-Web, converted to GROMACS with `acpype` |
| CHARMM36m | 303.15 K | TIP3P | the CHARMM-GUI |
| GROMOS54a7 | 298.15 K | SPC | the Automated Topology Builder (ATB) |

Common protocol: a single carbohydrate solvated in a **2.4 × 2.4 × 2.4 nm** box of water; short equilibration
in the isobaric ensemble at 1 bar; at least **200 ns** with the default leapfrog integrator; all bonds
restrained with LINCS; "the GROMACS specific recommended run settings" per force field. The detailed table is
the paper's Table S3, which we do not have.

Two sentences that matter for us beyond the force fields:

- The paper's own **15% uniform scaling** of COG-mapped ring distances was introduced to match molecular
  volume (SASA), and is explicitly "applicable to all monosaccharides" (Section 2.2). Our `ring_pairs`' `1.15`
  is that scaling, not a local choice — worth a comment in the code, and it means the published lengths sit
  15% above the raw COG distances *by design*.
- The paper measures SASA for its reference structures with all three force fields because the bead sizes came
  from volume matching. So per-force-field sensitivity is a stated part of their method, not an afterthought.

## Current state (verified today)

- `dashboard/execution/environment.py:17` — `FORCE_FIELD = AA_TEMPLATE / "charmm36-jul2022.ff"`, one constant.
- `dashboard/execution/adapters/aa.py:294` — the topology's includes are a hard-coded string naming
  `charmm36-jul2022.ff` for force field, water and ions.
- `aa.py:304` — `genion -pname SOD -nname CLA` (CHARMM naming).
- `aa.py:238-252` — `mdp(settings, kind)` already carries the GROMACS manual's CHARMM36 block (Verlet,
  `vdwtype=Cut-off` with force-switch, `rlist`/`rvdw` 1.2, `rvdw-switch` 1.0, PME, `DispCorr=no`,
  `constraints=h-bonds`), as one dict.
- `aa.py:23` — `VERSION = 'charmm36-single-solute-v1'`; `environment.py:284-289` copies the tree into the
  run's `common/` and records `force_field_sha256`.
- `molecules/<Name>/metadata.json` already carries `force_field`, `water_model`, `parameterization`.
- GROMACS 2026.3 on this host ships `gromos54a7.ff` with `spc.itp` (moleculetype `SOL`) and an `ions.itp`
  offering **NA/CL** (no SOD/CLA). The vendored CHARMM tree's `tip3p.itp` is also `SOL`, and its `ions.itp`
  offers both NA/CL and SOD/CLA. Water names agree; ion names do not.
- `charmm36-jul2022.ff/forcefield.itp:21` carries `#ifdef USE_OLD_C36`, so C36m is what it uses by default.
- No `acpype`, no AmberTools (`antechamber`/`tleap`/`sqm`/`parmchk2`), and no GLYCAM06 anywhere on this host.
- `molecules/Sucrose/MATCH/` holds MATCH output whose `.par` header reads "built by MATCH and modified by
  SwissParam" — mixed provenance, usable only as a documented draft.

## Design

Force fields become **declarative data**, and a run records the resolved entry.

1. **A registry** (`dashboard/execution/forcefields.py`), one entry per usable force field, each carrying:
   display name, the tree's path (for the vendored ones) or a declared tool path, the water file and its
   moleculetype, the two ion names, the default temperature, the mdp block the manual prescribes, the source
   URL and version, and the parameterisation route a solute's topology must come from. Pure data plus one
   accessor; an unknown name is an error rather than a fallback.
2. **Per-molecule parameter sets per force field**: `molecules/<Name>/<force_field>/...`, with `metadata.json`
   naming both. A molecule whose declared force field is not the run's is refused before anything runs.
3. **The adapter reads the registry** instead of literals, and the generated scripts are asserted
   **byte-identical to today's** for the current force field, so this refactor cannot change a result.
4. **The box** gains a fixed-cube option (the paper's 2.4 nm) alongside today's padding rule, with a
   solute-fits check that refuses rather than truncating.
5. **Tool declaration**: the GROMOS tree lives in the GROMACS install, so its path and version are declared
   and recorded per `AGENTS.md`, and the manifest keeps the resolved version and path.

## Tasks

F1 the registry and its accessor (pure; tests: the CHARMM entry reproduces today's include string and
SOD/CLA; the GROMOS entry declares NA/CL and `spc`; an unknown name raises).
F2 the mdp blocks as data per force field (test: CHARMM's block is exactly today's nine settings; GROMOS's
entry exists and differs only where the manual says).
F3 the adapter reads the registry (behaviour-equivalence test: identical topology, `genion` command and mdp
for the current force field).
F4 the fixed-cube box option with the fits check.
F5 per-force-field water and ions end-to-end through the solvation and neutralization stages.
F6 the newer CHARMM36 (feb2026) as a second declared entry, named distinctly so an older parameterisation can
never silently pair with it.
F7 the UI: a force-field combobox in **Single Molecule Simulations**, populated from the registry, showing the
temperature and water each entry implies; the choice is recorded in the run's settings.
F8 GROMOS54a7 end-to-end for sucrose — **blocked on D3**.
F9 GLYCAM06 — **blocked on D1**.
F10 the per-force-field comparison: re-run the AA reference for each available entry and report the ring
constraint table per force field, reusing `dashboard/analysis/sugar_ensemble.py`. This is the scientific
payoff and the acceptance evidence for the whole phase.
F11 documentation, written last.

## Decisions needed

D1 **GLYCAM06 route**: (a) install AmberTools and `acpype` (~1-2 GB) to run the paper's exact chain;
(b) you fetch GROMACS-format GLYCAM06 files from Glycam-Web under your own account and we skip the conversion;
(c) defer GLYCAM06 and ship the other two first.
D2 **CHARMM36 version**: keep `jul2022` as the default (its CGenFF version is what our SwissParam solutes were
made against) and add feb2026 as a second entry, or switch the default to feb2026 and re-parameterise the
solutes. The MacKerell page warns the CGenFF file version must match the tool version that made the solute.
D3 **GROMOS54a7 solute topology**: the ATB route the paper used (web service, needs your account), the local
MATCH output (mixed provenance, draft only), or hand-porting GROMOS hexopyranose parameters.
D4 **Box**: adopt the paper's 2.4 nm cube for replication runs specifically, or make it the default for all
single-solute runs.
D5 **Order**: GROMOS54a7 first (the force field whose numbers the published sucrose entry came from), or
CHARMM36m first (closest to the parameters we already have).

## Verification

Per task, the fast tier and ruff. For F3, a byte-equivalence assertion, not a reading. For F5/F8, a real run
per force field: the acceptance evidence is the ensemble table for that force field beside the published
values and beside the CHARMM36 jul2022 run we already have (`13ba0a087fad`). The 2.4 nm box is far cheaper
than that run's box, so each reference run is well under the three hours the 200 ns run took at 1622 ns/day.
