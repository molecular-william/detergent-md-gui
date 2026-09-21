# Molecule inputs

Put each molecule in a named subdirectory of `molecules/`, for example
`molecules/Maltose/`. Folder names use letters, numbers, underscores and hyphens.
The dashboard discovers a matching `.itp` and `.gro` or `.pdb` pair recursively,
including SwissParam's `results/MMFF/lig1.*` layout. Original parameter files
remain canonical; runs capture checksummed copies.

Use matching basenames where possible (`lig1.itp` + `lig1.pdb`). A directory with
one topology may also use differently named coordinates. GRO takes precedence
over PDB for the same topology. Multiple pairs are rejected; keep alternative
parameterizations outside the selected molecule folder. Local quoted ITP includes
are copied with their directory structure. Symlinks, path traversal, unsupported
preprocessor directives and inconsistent atom order/residue names are rejected.

If GRO is absent, preparation converts PDB to a run-local `molecule.gro`, retaining
atom order and converting Å to nm. The input is not minimized or reparameterized.
Resolve alternate locations and multiple PDB models first. The original PDB stays
unchanged. The conversion method, source hash and output hash are recorded; the
solvation stage creates the simulation box.

Missing `metadata.json` is generated automatically after input consistency checks.
Existing metadata is never overwritten. Identity and charge come from the ITP;
SwissParam headers select the supported CHARMM36 July 2022 / CHARMM TIP3P setup
with an explicit provenance note. Unknown sources receive `unknown` force-field
and water-model fields and remain blocked until those fields are set correctly.
Example metadata:

```json
{
  "name": "My molecule",
  "molecule_type": "LIG1",
  "net_charge": 0,
  "force_field": "charmm36-jul2022.ff",
  "water_model": "tip3p"
}
```

The AA-only adapter accepts one pre-parameterized compatible neutral or charged
solute in water. GROMACS preprocessing checks parameter resolution; successful
execution does not establish scientific validity. Arbitrary CG parameterization
is not implemented: AA–CG execution still requires the packaged DDM adapter.

The previous directory trees are backed up in
`archive/molecule-inputs-20260918/`; `migration.json` records verified source hashes.
Historical simulation snapshots were not changed. Existing flat
`molecule.itp`/`molecule.gro` directories remain supported. Equivalent relocated
inputs retain shared-reference identity. Retry rejects changed canonical snapshots;
clone creates a new selection, while resume uses the original immutable inputs.
