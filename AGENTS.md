# Project guidance for coding agents

Rules and facts for working here. State, measurements and open items are in `docs/HANDOFF.md`; repo layout,
persistence, migration and testing in `docs/PROJECT_GUIDE.md`; procedures and gotchas in the `detergent-md-dashboard`
skill. Read `HANDOFF.md` before touching the DDM CG chain or the coordinator.

## Goal
One local Python service orchestrating resumable GROMACS/Martini jobs -- AA to CG, protein-detergent, osmotic series
-- with a Flask dashboard over persisted manifests and logs. Reproducible; outputs immutable; analyses derived from
them.

## Where things are
- AA to CG: `execution/adapters/aa.py` then `cg.py` (the only CG stage pipeline), then Fast_Forward, then GROMACS.
  Any molecule with a compatible AA topology runs it; packaged `molecules/DDM` is the reference example, not a shim.
- Protein-detergent: `execution/adapters/pdc.py` owns the stages and runs its own `pdc_*.sh` scripts; the placement
  science stays in `micelle/` (paused, not a validated model). Back-mapping is vendored CG2AT2 (`tools/cg2at/`),
  driven by `pdc_backmap.sh` with the `martini_3-0_charmm36` fragment DB.
- Osmotic series: `execution/adapters/osmotic.py` (+ `osmotic_box.py`, `osmotic_mdp.py`), route
  `web/routes/osmotic.py`, panel `osmotic-pressure`.
- Force fields are local (`resources/forcefields/martini_v3.itp`; charmm36 in the AA template). Tools come from
  `config/tools.json` through `execution/tools.py`: a declared path is verified or resolves to nothing, never to a
  substitute; every manifest records the resolved version and path.
- Maintained assets are `resources/` and `dashboard/` only. `memembed`, `martinize`, `insane` and `cg2at` are not
  maintained, and no `archive/` tree exists.

## Workflow contract
- AA-only: solvation, neutralization, minimization, NVT, NPT equilibration, NPT production, reference publication.
- CG: AA reference, trajectory mapping, CG parameterization (`ff_inter` when it fits, `use_parameterization.sh`
  when it consumes), CG simulation, CG assessment (`ff_assess`), SASA.
- pdc: Protein preparation (PDB2PQR rebuild, `prepare_protein`, off by default), System preparation, Energy
  minimisation, NVT, NPT, CG assessment MD (production only; it reads `../4_npt/`), Micelle assessment, CG extension
  MD, Final assessment, Back-mapping (a toggle). `pdc.LEGS` names each leg's mdp and `pdc.stage_by_name` names a
  stage, so no caller counts them.
- Every stage records start/end, command, environment, inputs, outputs, exit code and log path. A stage with nothing
  to do records `skipped` (exit 4) with its reason in `skip.json` and the run carries on. Runs end `complete`,
  `failed`, `cancelled` or `blocked`.
- Only `1_system/prepare_system.sh` and the three equilibration legs are filled at prepare time
  (`pdc.GENERATED_STAGES`); every other stage file is `pdc_...` and copied.

## Facts that change what you build
- **Every AA-CG run fits its own bonded parameters** (`cg.AA_CG_PROFILE`; stage 3 is `CG parameterization`) unless
  its mapping carries a current revision, which it then consumes and says so in its own artefact. A parameterization
  belongs to the mapping, revisions are keyed by content hash and one is current (`make current`). Producing one is
  `POST /api/bonded-parameterizations` -- engines `fast-forward` and `bartender`, the latter restricted to
  `-refit -owntraj`; every engine fits to an AA ensemble, so `aa_reference` is required -- and makes no MD. Deleting a
  saved mapping deletes its parameterizations (and the fit jobs and staged frames built for it) unless another saved
  mapping carries the same content hash; both panels that can delete a mapping do it through that one route, and say
  what went with it.
- **A candidate's identity must not depend on how its numbers were spelled.** `identity.candidate_identity` hashes
  `1` and `1.0` alike (`numbers_as_values`): a mapping is read as JSON, posted back by a browser, and JS has no int,
  so a file's `1.0` returns as `1`. Hashing the spellings differently gave one mapping two content identities -- the
  file's and the posted snapshot's -- and a fit was filed under a digest no saved mapping addressed: the panel showed
  "no parameterization" and its job box sat on `queued`. Reads fall back to `legacy_content_identity` for records
  written before that; only `candidate_identity` normalises, never `canonical_sha256` (file/snapshot/reference digests
  are byte digests on purpose).
- **`ff_inter` writes `funct 9`, not `funct 1`**: one `phi C mult` triplet per line, eight lines for one quadruple, so
  eight lines are one dihedral with eight harmonics. A reader that assumes `funct 1` refuses the topology; one that
  treats each line as a dihedral measures the same torsion eight times. `dihedral_fit.read_declared_dihedrals` merges
  them and compares the whole curve; `bonded_terms` keeps the lines.
- `snapshots` runs for every run with a trajectory, and `queue_defaults` asks one resolver
  (`coordinator.automatic_analyses`), so `aa_cg` also owes `dihedral-fit` and `bonded-cross-check`. Frames resolve
  through the run's own layout (`07_reference/` for AA-only, `4_CG_sim/` for a CG consumer).
- `GET /api/jobs/<id>/structure?path=<run-relative .gro>` writes the run's own bonds and constraints as CONECT and
  refuses a `.pdb`. A file carrying `CONECT` is never distance-guessed; a coarse-grained file is `inferBonds: 'none'`.
  Bead size and family colouring come from one table in `ngl-beads.js`, legend included.
- A pdc belt is a **torus** when the protein states a membrane (`pdc_placement._belt_torus`; `radius_nm` is then a
  floor under the measured centre-line) and a fixed-radius **sphere** when it does not. Secondary structure is
  martinize2's `-dssp` answered by mdtraj (`pdc_build.SS_SOURCE`), with MDAnalysis DSSP as the recorded fallback.
- The osmotic run type is one run owning N concentrations (`settings.molalities`, sugars only, own checkpoint per
  concentration, `series_on_failure` `carry_on` or `stop`); `osmotic_molality` is not a setting any more.
- Panels: `Run view` (both workspaces; two side-by-side monitors paired in time), `CG Bond Interactions`,
  protein-detergent `New run` (live placement preview, `prepare_protein`), `Osmotic Series`, Mapping Validation, and
  CG Bead Assignment (one 3D diagram; the server's RDKit depiction stays for the export bundle). The bonded panel
  draws the selected candidate's own molecule, never the packaged reference; it deletes the selected mapping, and its
  fit box names the four job steps with an elapsed time. A fit job is polled by `?job_id=`, never by the mapping's
  hash: the hash is a mapping's history, the id is the job the panel queued. A revision's terms name beads by their
  **export** name (`B01` is the mapping's first bead, virtual sites included, `mappings/exports.py`), so anything
  needing a position translates them first: the 3D scene did not, and drew no bonded term at all until it did. The scene
  has one style per term kind (`bonded-plot.TERM_STYLES`): bonds the mapping's green, constraints a darker shade of it
  and left on the bond they fix, angles amber, dihedrals green dashed at alpha 0.5, impropers slate dash-dot, virtual
  sites violet dotted -- and the kinds whose geometry is collinear with a bond (angles and both torsion kinds) are
  stepped off it by 1.8% of the molecule's diagonal, seeded per (kind, bead set) so a re-render moves nothing and
  `ff_inter`'s eight harmonics of one torsion coincide. A virtual site is drawn twice: an open diamond as a bead (a
  solid circle reads as an atom the model lacks) and a violet star from the site to each parent, because the term names
  the site alone and the parents live on the mapping's bead record.
- Carbohydrate validation is an immutable analysis on a completed source run. Checked-in targets are citation
  metadata until molecule-specific measurements arrive, and a `setup` analysis proves execution, never validity.

## Engineering rules
- Test against fixtures, never the developer's workspace; build the record through the route the UI uses.
- Trace inputs, state transitions, outputs and failure handling before editing.
- Keep force-field and tool versions and exact commands in run metadata; never silently overwrite a run.
- Validate uploaded structures, detergent definitions, resource limits and paths at trust boundaries.
- Stages are resumable, idempotent, cancellable and safe to run concurrently.
- Simulation outputs are immutable; analyses reference their source trajectory.
- GROMACS + Martini by default; anything else only with measured need.
- Test command construction, stage transitions, failure recovery and analysis parsing without long simulations.

## Do not
- Exercise a destructive control against the live workspace. Point it at a fixture, or inspect what the client sends.
- Delete simulation data, or rebuild a file to stand in for a lost record.
- Signal a PID from a previous coordinator session; only the current worker owns its subprocess groups.
- Treat a notebook as production orchestration, or a completed diagnostic as scientific validation.
- Assume a detergent has Martini parameters because it is available.

## Standing decisions
- CG production 20 fs, CG equilibration 5 fs, AA half 2 fs. `cg.mdp_integration` stamps the AA half's `dt`; the CG
  timestep is the templates' own (`4_CG_sim/inputs/md.mdp` 0.02, `eq.mdp` 0.005), read back per file.
- This GROMACS is an MPI-only build: `-ntomp` is the knob, `-ntmpi` is invalid. In use:
  `/usr/local/gromacs/2026.3/bin/gmx`.
- Internal consistency is the primary evidence; the reference's own numbers are context, not a pass mark.
- A mapping states its own ring scale and the guard is a range, not a constant. Ring scale is closed against as the
  cause of the DDM failure, and fitted linkage values are not a diagnosis -- spend no further arm on either.
- The published M3-Lipid set is the standard source, recorded per run, and stays untracked. GLYCAM06 is dropped.
- The scheduled cron drivers and the mapping-refinement panel are cancelled; do not rebuild either.
- `-improperIncrement 10` goes to every BARTENDER fit, so impropers fitted since are not comparable with earlier ones.
- Phase 4 (sucrose and maltose experimental sources) is deferred, not abandoned.

## Verify
```
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q      # fast: 1,792, ~18 s with a private MPLCONFIGDIR
dashboard/.venv/bin/python -m pytest -m browser -q -n 24 --dist worksteal   # browser: 223, ~37 s
dashboard/.venv/bin/python -m pytest -m slow -q -n 0                       # slow: 66, ~64 s serial
dashboard/.venv/bin/ruff check dashboard tests                             # F, E9, I must exit 0
scripts/gate_commit.sh <message-file> <paths...>                           # fast tier + ruff over named paths; commits only when clean
dashboard/.venv/bin/python scripts/mutation_check.py                       # 11 mutants: 10 caught, 1 survived (the control)
```
The suite is 2,081 tests (1,792 + 223 + 66). A shared matplotlib config directory makes four distance-diagnostic
tests race, so export a private `MPLCONFIGDIR` before running the tier, gate included. Repo-wide `ruff check .` exits
1 on 19 pre-existing `micelle/` findings; scope lint to the paths you touched.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **detergent_md** (1775 symbols, 4945 relationships, 139 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/detergent_md/context` | Codebase overview, check index freshness |
| `gitnexus://repo/detergent_md/clusters` | All functional areas |
| `gitnexus://repo/detergent_md/processes` | All execution flows |
| `gitnexus://repo/detergent_md/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
