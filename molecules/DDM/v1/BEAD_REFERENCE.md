# DDM identity and bead references

`identity.json` records the user-supplied DDM SMILES, canonical stereochemistry, and source checksum. It matches the SwissParam `results/tautomers.smi` input exactly after canonicalization: C24H46O11, neutral. The historical dashboard command containing `OCC` was a test string (ethanol), not DDM; it must not be reused as molecular identity. That job's AA input was the local SwissParam structure.

All 95 entries in `detergents.json` parse with RDKit. This verifies syntax, not that every name, stereoisomer, or commercial mixture is chemically represented correctly.

## Local Martini references

Source: `M3-Bible/src/MartiniCGSmilesDB_v6.xlsx`, sheet `All` (413 data rows), and `M3-Bible/building_block_table.pdf`. Literature references are listed in `M3-Bible/README.md`.

- Dodecane, MOLTAG `DOD`: three C1 beads, encoded as `{[#C1]|3}.{#C1=[$]CCCC[$]}`. This supports a starting hypothesis for the C12 hydrophobic tail; the glycosidic linkage still needs explicit treatment.
- D-glucose, MOLTAG `GLC`: the CG graph contains two SP4r nodes, one SP1r node, and one TC4 node. This is a sugar reference, not a complete DDM topology. Inspect the corresponding carbohydrate model for placement, virtual-site definitions, constraints, and bonded parameters before implementation.
- Multiple entries exist for the same chemistry (for example ethanol and 2-butoxyethanol) with different bead assignments. Selection requires chemical context and provenance; the workbook is not a unique automatic lookup table.

DDM contains linked sugar rings and an alkyl glycoside. Substitution changes hydroxyl/ether environments, so copying two isolated-glucose models unchanged is not justified. No fitted or validated DDM parameter set is claimed here.

## Integration findings

`make_table.py` defaults to worksheet `prod`, but the supplied workbook contains only `All`; use `All` when reading it. Keep the upstream source unchanged.

The latest AA retry passed structure boxing and stopped at `grompp`: the copied template includes `MMFF/lig.itp`, whereas SwissParam supplies `MMFF/lig1.itp`. No AA reference trajectory was produced by that attempt. Dashboard stage percentage is a command-count estimate, not simulated-time progress.
