# Plan: CG stage settings, pdb2gmx virtual sites, Generate seeds and stage traces (2026-11-13)

Status: **built** (approved 2026-11-13). Draft: `docs/design/drafts/2026-11-13-cg-stage-settings.html`. Execution record: four lanes (CG settings, form JS, overview, pdc vsite) with the Lead owning markup/integration; fast 2769 / 1 xfailed, browser 381, slow 24, ruff clean; live `d1dc16dfe369` and overview `04171a0091c5` (details in `HANDOFF.md`).

## Decisions

1. **CG runs get three stage editors**, mirroring the AA ones: CG minimisation, CG equilibration and CG production.
   - Minimisation: step cap, neighbour-list rebuild, Verlet buffer tolerance.
   - Equilibration: duration, timestep, nstlist, Verlet tolerance, thermostat coupling, barostat coupling, compressibility.
   - Production: duration, timestep, nstlist, Verlet tolerance, thermostat coupling, barostat coupling, compressibility. Its existing output-cadence and cutoff overrides stay under *Other run options*.
   - Applies to every CG kind: revision, composition and published reference (the sugar adapter gains the same keys).
   - Defaults are the reviewed profile values, so an untouched run renders byte-identical MDPs.
2. **Virtual sites.** `pdb2gmx` cannot build a topology for this project's ligand molecules: the stored SwissParam
   PDB has residue `LIG`, and `gmx pdb2gmx -vsite {none,hydrogens,aromatics}` fails with
   `Residue 'LIG' not found in residue topology database`. The only stage that invokes pdb2gmx is the pdc back-map
   (inside CG2AT2, on the protein). The choice therefore lands in **pdc's Other run options** as
   *Protein virtual sites* (`none` / `hydrogens` / `aromatics`) and is passed as `-vsite` to every `pdb2gmx` call
   CG2AT2 makes, through a repo-owned `gmx` wrapper selected with CG2AT2's `-gmx` flag. `none` adds no flag.
   Recorded in the pdc settings and manifest. CG2AT2's own `-vs` is not used, because it only supports hydrogens.
3. **Both random seeds** replace *Default* with *Generate*, drawing a random integer in `1..YYYYMMDD` (today in
   local time, e.g. 20261113), matching pdc's existing seed convention.
4. **Trajectory overview gains a third row of three panels**: Potential vs step (minimisation), Temperature vs time
   (NVT), Pressure vs time (NPT). The production energy row is unchanged. The record gains `energy.stages` with a
   bounded series and summary per leg. Stage EDRs are staged explicitly: AA `03_minimization/run.edr`,
   `04_nvt/run.edr`, `05_npt/run.edr`; CG `4_CG_sim/{min,eq,md}.edr`; pdc `03_minimisation/system.edr`,
   `04_nvt/system.edr`, `05_npt/system.edr`.

## Settings and consumers

| key | default | range | written to |
|---|---|---|---|
| `cg_minimization_steps` | profile 20000 | 1–1 000 000 | `cg-minimization-v1` `nsteps` |
| `cg_minimization_nstlist` | profile 20 | 1–10 000 | `cg-minimization-v1` `nstlist` |
| `cg_minimization_verlet_buffer_tolerance` | profile 0.005 | 0.001–0.1 | `cg-minimization-v1` `verlet-buffer-tolerance` |
| `cg_equil_dt_fs` | profile 5 | 0.5–20 | `cg-equilibration-v1` `dt` (fs/1000) |
| `cg_equil_nstlist` | profile 40 | 1–10 000 | `cg-equilibration-v1` `nstlist` |
| `cg_equil_verlet_buffer_tolerance` | profile 0.005 | 0.001–0.1 | `cg-equilibration-v1` `verlet-buffer-tolerance` |
| `cg_equil_tau_t` | profile 1.0 | 0.01–100 | `cg-equilibration-v1` `tau-t` |
| `cg_equil_tau_p` | profile 4.0 | 0.1–100 | `cg-equilibration-v1` `tau-p` |
| `cg_equil_compressibility` | profile 4.5e-5 | 0–1 | `cg-equilibration-v1` `compressibility` |
| `cg_production_dt_fs` | profile 20 | 0.5–20 | `cg-production-v1` `dt` (fs/1000) |
| `protein_vsite` (pdc) | `none` | none/hydrogens/aromatics | pdb2gmx `-vsite` via CG2AT2 |

The durations `cg_equil_ps`/`cg_production_ps` move from Sampling into the stage editors; `lengthSentence`,
`labelLength`, presets and clones keep reading the same field names.

## Lanes

| Lane | Owns | Work |
|---|---|---|
| **Lead** | `dashboard.html`, `new-run.css`, pdc `new-run-pdc.html`, plan/draft, integration, tiers, gate, docs, commit | markup for the three CG editors and the two Generate buttons; pdc vsite combo; final diff |
| **A — CG execution** | `execution/adapters/cg.py`, `composition.py`, `execution/mdp/profiles.py`, `execution/settings_help.py`, validation `sugar_cg.py`; unit tests `test_mdp_writer`, `test_cg_adapter_molecule_scoped`, `test_cg_inputs`, `test_composition_workflow`, sugar tests | keys/specs/defaults, profile `variable`, `mdp_values`, prepare calls, help; parity and override tests |
| **B — form JS** | `web/static/js/new-run.js`; browser tests `test_aa_new_run_browser`, `test_new_run_browser`, `test_new_run_cg_model_browser`, `test_new_run_state` | CG field lists, facts sync, visibility/listeners, Generate handler; browser tests |
| **C — overview graphs** | `analysis/runs/trajectory_overview.py`, `analysis/kinds.py` description; unit/integration tests | stage EDR sources, `energy.stages`, third row, tests |
| **D — pdc vsite** | pdc `execution/adapters/pdc.py`, `execution/scripts/pdc_backmap.sh`, pdc JS form fields if needed; pdc tests | choice spec, settings record, wrapper + `-gmx`, tests |

Markup contract for lane B: `#stage-cg-minimization`, `#stage-cg-equilibration`, `#stage-cg-production`, each
`<details class="stage-editor cg-setting">` with a `.stage-facts` host `#stage-cg-<stage>-facts`; Generate buttons
`#generate-aa-seed`, `#generate-cg-seed`; pdc select `name="protein_vsite"`.

## Checks

- Fast: `pytest -m 'not browser and not slow' -q`; MDP parity at defaults for cg revision/composition/reference;
  new override cases; spec publication for all three CG adapters; pdc settings round-trip and script assertions.
- Browser: `pytest -m browser -q -n 16 --dist worksteal`; three CG editors render and hide for AA; facts update;
  Generate fills an integer in range; pdc combo posts.
- Slow: `pytest -m slow -q -n 0`.
- Ruff over touched paths; gate commit.
- Live: one timed CG `draft-smoke` run with a non-default equilibration timestep and production nstlist, then its
  overview; report wall time and the record's stage series.
