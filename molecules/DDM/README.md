# DDM inputs

`results/MMFF/` contains the canonical SwissParam atomistic topology and PDB.
`results/MATCH/` retains the alternate SwissParam output for reference. New run
discovers the MMFF ITP/PDB pair and converts coordinates inside each AA run.
`metadata.json` records identity, supported force-field setup and provenance.

Select DDM in the dashboard for an AA-only run or the DDM AA–CG adapter. CG
execution requires its mapping and bonded workflow; scientific validation remains
separate from completion. See [molecule inputs](../README.md) and
[DDM calibration](../../docs/DDM_CALIBRATION.md) for the maintained workflow.
