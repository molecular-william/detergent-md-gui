# Alignment with the Martini 3 Fast_Forward tutorial

Reference: https://cgmartini.nl/docs/tutorials/Martini3/Small_Molecule_Parametrization_FastForward/

The explicit **DDM draft smoke test** profile executes the tutorial sequence using
dashboard-owned scripts and run-local assets. Standard parameterization remains
blocked until a reviewed model is connected. Test results are never promoted to
scientific validation automatically.

| Tutorial step | Executed smoke-test implementation | Scientific work remaining |
| --- | --- | --- |
| AA reference | SwissParam LIG1, CHARMM36 July 2022, PME/force-switch; vacuum and solvated minimization; 10 ps NVT equilibration and 50 ps NVT production at 300 K | Equilibrated density, adequate sampling (tutorial recommends at least 50 ns), replicas and force-field assessment |
| CGbuilder mapping | Connected 11-bead draft covering 35 heavy atoms; shared NDX/MAP export; equal-weight heavy-atom COG | Review chemical groups, stereochemistry, shape and hydrogen/weight convention; last S bead has four atoms |
| ff_map | Molecule-whole ligand XTC + GRO, `-mols LIG1 -mode COG`; frame-by-frame COG validation | Assess mapping quality beyond atom coverage |
| Initial CG topology | Bond network from SwissParam connectivity; annotated bond/angle seed; separate ligand-only GROMACS preprocessing | Review draft nonbonded types and interaction network; ring geometry and torsions need further work |
| ff_inter | Fits bonds/angles to mapped AA at 300 K; writes DDM.itp, distributions, plots and pairwise-distance references | Convergence, fit quality and numerical stability at a useful Martini timestep |
| CG simulation | Fitted DDM topology, Martini 3 water; minimization, 10 ps NVT equilibration and 50 ps NVT production; 2 fs diagnostic timestep | Equilibrated density, solvent/ion conditions, longer sampling, aggregation validation |
| ff_assess | Actual CG-versus-AA distribution reports, plots, finite-score/trajectory checks | Interpret mismatches and iterate; a completed command is not an acceptable scientific score |
| SASA | AA and CG SASA curves with tutorial radii and 0.191 nm probe | Independent shape, hydration, thermodynamic and experimental validation |

## Compatibility decisions

- Installed local Fast_Forward source version `0.0.4.dev30` has no `-itp-only`
  option. Its supported `ff_inter` command writes the ITP directly. The run records
  tool versions and exact commands; no runtime network installation occurs.
- MDAnalysis 2.10 cannot parse GROMACS 2026 TPR version 138. Fast_Forward natively
  accepts GRO topology input, promoting each single ligand residue to a molecule.
  AA and CG trajectories are made whole with GROMACS before analysis. Explicit ITP
  annotations supply fitting/scoring connectivity. GROMACS still creates and uses
  TPR files for every simulation/preprocessing stage.
- The bundled `ff_map` resets the trajectory interval to 1 ps and writes its last
  frame as the GRO. `finalize_mapping.py` preserves these raw outputs, verifies all
  bead coordinates against independently computed AA COGs, restores exact AA frame
  times/boxes and writes the first mapped frame. Both source and derived artifacts
  remain available with a mapping validation record.
- Fitted bonds remain harmonic (`-constraints 1000000000`); the smoke test uses a
  2 fs timestep because short-reference fits can be very stiff. This is not a
  recommended production Martini model or timestep.
- Pure-water NVT is a bounded software test. It does not reproduce the tutorial's
  salted NPT production protocol. These differences are recorded in each manifest.
- No `-maxwarn`, ENAP topology, or guessed ETA is used. Draft nonbonded guesses
  are explicit in the run-local `mapping_candidate_smoke.json`; the existing
  original and tail-split candidates are unchanged.
