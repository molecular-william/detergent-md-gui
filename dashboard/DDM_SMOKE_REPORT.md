# DDM draft execution validation — 2026-09-11

Run: [e8e9775b061f](http://127.0.0.1:5000/?run=e8e9775b061f#runs)

**All six workflow stages completed; the scientific model remains unvalidated.**
Execution took approximately 51 seconds (04:20:41–04:21:32 UTC). This is an
observed duration, not an estimated completion time.

| Stage | Observed result |
| --- | --- |
| AA reference | SwissParam DDM/CHARMM36; minimization, 10 ps equilibration and 50 ps production; ligand contains 81 atoms |
| ff_map | 11 CG beads; 251 frames over 50 ps; full heavy-atom coverage |
| ff_inter | Fitted DDM.itp, 12 bonds and 16 angles, distributions, pairwise references and plots |
| CG simulation | Martini 3 water, fitted draft DDM; 10 ps equilibration and 50 ps production; 251 frames |
| ff_assess | Interaction score 0.485; pairwise-distance score 0.555, maximum 1.00; all reported scores finite |
| SASA | AA and CG curves, 251 frames each, tutorial radii/probe |

Independent COG verification: maximum component difference **0.000501 nm**,
within XTC rounding. Frame times and bead order match the source mapping.
First/middle/last AA snapshots at 0, 25 and 50 ps are available in the run.

## Interpretation

These results prove that the execution chain and artifact handoffs work. They do
not establish physical accuracy, convergence, acceptable hydration or micelle
behaviour. The draft nonbonded assignments are uncalibrated, sugar stereochemistry
and bonded representation need review, sampling is only 50 ps, and the pairwise
score indicates poor structural agreement. Do not use this model for production.

The smoke protocol uses pure-water NVT at 300 K and a conservative 2 fs CG step.
It deliberately differs from the tutorial's longer salted NPT protocol. All
choices, input hashes, tool paths/versions, stage commands and exit codes are
recorded in the manifest. No GROMACS preprocessing warnings were bypassed.

## Fixes established by actual execution

- Replaced ENAP scripts/topologies with dashboard-owned DDM stages and the shared
  MAP exporter; removed unsupported ff_inter flags and connected ff_assess.
- Specified one MPI rank/four OpenMP threads for local GPU GROMACS.
- Used supported GRO topology input for Fast_Forward/MDAnalysis, retaining
  GROMACS 2026 TPRs for simulation. MDAnalysis 2.10 does not support TPR 138.
- Preserved raw ff_map outputs and restored AA frame timestamps/boxes in a
  checked derived trajectory; the bundled tool had reset the interval to 1 ps.
- Removed an unused FLEXIBLE macro instead of using maxwarn.
- Corrected snapshot API serialization and made snapshots use portable ligand
  files. The dashboard now displays the actual stage plan and draft status.

Earlier failed attempts and all simulation data remain intact; retries created
new run IDs. The successful manifest links back through the retry chain.

## Artifacts

- [Manifest](runs/e8e9775b061f/manifest.json)
- [Mechanical validation and comparison reports](runs/e8e9775b061f/5_assessment/validation.json)
- [Mapping verification](runs/e8e9775b061f/2_mapping/mapping_validation.json)
- [Interaction report](runs/e8e9775b061f/5_assessment/report_interactions.out)
- [Distance report](runs/e8e9775b061f/5_assessment/report_distances.out)
- [Fitted draft topology](runs/e8e9775b061f/3_initial_CG/DDM.itp)
- [Console log](e8e9775b061f.log)

Next: review the mapping/types and interaction scaffold, address the poor
structural agreement, establish equilibrated conditions, then use longer AA/CG
sampling and independent validation before approving any production model.
