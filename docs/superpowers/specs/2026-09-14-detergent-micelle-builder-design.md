# Detergent micelle builder design

## Status

Architecture approved by the user on 2026-09-14. Implementation has not started.

## Goal

Provide a reproducible CLI that builds a spherical, single-detergent Martini 3 micelle around an inserted membrane protein and emits GROMACS-ready files plus structural validation reports. The first research benchmark is DDM with bacteriorhodopsin.

## Scope and non-goals

The initial release supports one registered detergent species per build, spherical initial packing, cubic boxes by default, optional orthorhombic boxes, optional ions, and optional restrained energy minimization. It does not initially support mixed detergents, arbitrary aggregate shapes, or automatic beta-barrel orientation. Existing Martini protein/topology inputs remain supported; automatic martinize2 preparation is a fallback.

## Relationship to Insane

Insane supplies reusable ideas for deterministic sphere sampling, coordinate transforms, PBC handling, and solvent placement. Its bilayer packing is slab-specific and its topology output is too rudimentary for this workflow. The implementation is native to this repository and preserves source/tool provenance.

## Inputs

A build requires a registered detergent template, an integer seed, and an aggregation number. Protein input may be an atomistic structure, a prepared Martini structure/topology, or both. Optional inputs specify OPM metadata, an explicit membrane axis/span, box dimensions, water/ion composition, and whether restrained minimization should run.

Detergent registry metadata is JSON/YAML and references ordinary coordinate/topology assets. It records molecule/residue names, bead names and types, charge, headgroup anchors, tail direction, bonds, dimensions, and orientation annotations. Missing or ambiguous topology dependencies are errors.

## Pipeline

1. Validate all paths, structures, templates, settings, and resource limits.
2. Use supplied CG protein files when available; otherwise run martinize2 on the atomistic structure. Record source, version, command, and hashes.
3. Determine the protein axis with precedence OPM metadata, explicit user axis/span, then a combined alpha-helix clustering plus hydrophobicity/neighbor-density heuristic. Report axis, membrane span, confidence, evidence, and fallback reason.
4. Estimate an initial micelle radius from detergent dimensions and aggregation number.
5. Generate a deterministic spherical candidate lattice from the required seed.
6. Score candidates for hydrophobic-belt coverage, soluble-domain exposure, pore/entrance clearance, hard overlaps, headgroup-outward/tail-inward orientation, and radial uniformity.
7. Select the best directions and run hybrid local repacking: tangential/radial shifts first, then unused high-scoring directions, with bounded deterministic retries. The requested aggregation count is exact.
8. If exact count or hard geometry gates cannot be met, write diagnostics only and no production topology.
9. Add Martini water and optional neutralizing or concentration-based ions. Record exact composition.
10. Build a cubic box by default or explicit orthorhombic dimensions.
11. Assemble and validate the GROMACS topology dependency closure and molecule counts.
12. Run structural checks and `gmx grompp`; optionally run restrained energy minimization.
13. Write immutable coordinates, topology, reports, diagnostics, and manifest.

## Validation gates

Hard gates block production output: finite coordinates, valid box/PBC, exact aggregation count, no severe overlap, valid detergent orientation, hydrophobic-belt coverage, soluble-domain/pore clearance, consistent molecule counts/order, resolved topology includes, and successful `gmx grompp`. Optional minimization has an independent status and does not claim equilibration or scientific validation.

Reports contain JSON and HTML/Markdown summaries with counts, distances, overlap distributions, orientation distributions, belt coverage, exposure/clearance, confidence, solvent/ions, box, topology closure, grompp/minimization results, seed, tool versions, commands, and source hashes.

## CLI and dashboard boundary

The primary command is `micelle-build`. `micelle validate <directory>` reruns checks, and `micelle inspect <directory>` summarizes a build. The dashboard will submit the CLI as a thin job wrapper and display manifests/reports; scientific generation and validation remain owned by the CLI.

## Benchmark and acceptance

The initial benchmark includes empty DDM micelles at selected aggregation numbers and bacteriorhodopsin with an OPM-aligned atomistic structure. The heuristic orientation path is tested separately. Identical seeds/settings are used for comparable builds. Acceptance requires deterministic reruns, exact counts, passing hard gates, topology preprocessing, and useful diagnostics for deliberately impossible packing requests.

## Error and reproducibility policy

Every build requires or explicitly receives an integer seed. No global RNG is used. Failed builds preserve a diagnostic package. Production outputs are immutable and never silently overwritten. All state transitions, commands, environments, dependencies, hashes, and failure reasons are recorded in a manifest.
