# Martini 3 carbohydrate validation

This note records the validation methods used in the primary Martini 3
carbohydrate paper and the implications for the Maltose virtual-site variants
in this repository.

## Primary sources

- Grunewald et al., *A Consistent Martini 3 Coarse-Grained Force Field for
  Carbohydrates*, J. Chem. Theory Comput. 2022, 18, 7555-7569,
  DOI [10.1021/acs.jctc.2c00757](https://doi.org/10.1021/acs.jctc.2c00757).
  The pinned local copy is
  [`references/Martini 3 Coarse-Grained Force Field for Carbohydrates.pdf`](../../references/Martini%203%20Coarse-Grained%20Force%20Field%20for%20Carbohydrates.pdf).
- The corresponding official Martini 3 topology is pinned by commit and hash in
  [`references/martini_v3.0.0_sugars_v2.source.json`](../../references/martini_v3.0.0_sugars_v2.source.json).

Page numbers below are the printed journal pages in the PDF.

## Model construction relevant to virtual sites

The paper assigns the ring TC4 virtual site during every carbohydrate mapping;
it is not an optional post-processing marker (p. 7558). The site is massless,
placed at the ring center of geometry, and supplies a hydrophobic interaction
center for ring-stacking interactions. It also compensates for the atom-count
mismatch introduced when four non-hydrogen ring atoms are represented by an
S-bead. The paper evaluates the virtual-site effect with an indole-glucose
potential of mean force in the Supporting Information.

The paper first maps ring COG distances and then increases ring distances by a
uniform 15% to match molecular volume. The scaled model improves SASA and
Connolly-surface agreement (pp. 7557-7558). The official topology therefore
contains TC4 sites, ring constraints, and exclusions; for example, the LAC
entry has six massive beads, two TC4 sites, six scaled ring constraints, and
two virtual-site definitions
([`martini_v3.0.0_sugars_v2.itp`](../../references/martini_v3.0.0_sugars_v2.itp), pp. 7567-7568).

## Validation methods

### Mapping geometry and molecular volume

- Eleven monosaccharides and three disaccharides were simulated with multiple
  atomistic force fields and compared with Martini 3 mappings.
- SASA and Connolly surfaces were compared for unscaled and 15%-scaled ring
  geometries. Martini SASA used bead-specific radii and a 0.191 nm probe.
- The paper averaged SASA over at least 200 ns for both AA and CG systems
  (pp. 7557-7558 and Methods section 5.3, p. 7565).

### Transfer thermodynamics

- Bead types were selected against water-to-octanol transfer free energies for
  eleven monosaccharides. Most partition coefficients were measured
  experimentally because suitable literature values were unavailable.
- The reported mean absolute error for monosaccharides was about 1.5 kJ/mol.
- Trehalose and sucrose transfer free energies were used as a disaccharide
  transferability check, with errors of about 0.5 and 3.0 kJ/mol respectively
  (pp. 7558-7559).

### Osmotic pressure

- Osmotic pressure was measured for eight monosaccharides and two
  disaccharides over 0-2.5 molal and compared with experiment and Martini 2
  (Section 3.1, pp. 7559-7560).
- The method confines solute molecules near the center of a large box with a
  flat-bottomed potential, couples pressure only in the z direction, and
  obtains osmotic pressure from the mean restraining force divided by the
  xy area. The production protocol used 500 ns per condition (Methods 5.3,
  p. 7565).
- Lower-than-experimental pressure indicates excessive carbohydrate
  self-aggregation. Agreement was good below roughly 1.5 molal, with residual
  deviations at higher concentration.

### Solution and polymer behavior

- Dextran oligomers of degree of polymerization 9, 15, and 24 were compared
  against atomistic radius-of-gyration and end-to-end-distance distributions.
- Dextran water solubility, chloroform aggregation, and a dextran/PEO aqueous
  two-phase system were tested. These used multi-microsecond simulations and
  RDF/density-profile analyses (Section 3.2, pp. 7560-7561).
- Cellulose chains and a cellulose I-beta fibril were tested for aggregation and
  stability in water, and cellulose solvation was tested in an ionic liquid
  (Section 3.3, pp. 7561-7562).

### Glycolipid and membrane behavior

- GM3 clustering in a 10% glycolipid POPC membrane was compared with AA and
  Martini 2 cluster distributions.
- Shiga toxin/Gb3 and cholera toxin/GM3 systems were simulated for 10 us.
  The analysis included binding persistence, lipid density maps, site-specific
  RDFs, and membrane curvature, with controls lacking glycolipid receptors
  (Section 3.4, pp. 7562-7564).

## Consequences for Maltose-0-noVS

The noVS candidate cannot inherit the paper's validation evidence. Removing
the TC4 sites changes both the interaction surface and the nominal bead-count
balance; the current candidate also removes the ring definitions and 15%
scaled ring constraints. It is therefore a different model, not merely the
same mapping with two display atoms omitted.

The most defensible comparison is paired and controlled:

1. Keep the six physical bead assignments, types, AA source, seeds, and fitted
   nonbonded terms identical.
2. Compare a TC4 model with a physical-only model that retains explicit ring
   geometry constraints. This isolates the virtual-site effect.
3. Compare both models against AA mapped geometry and SASA first, then perform
   transfer/hydration checks and concentration-dependent osmotic-pressure
   tests. Treat a generic noVS model with no ring constraints as a separate,
   more speculative candidate.

The repository currently has execution evidence for short DDM carbohydrate
screening, but not the paper's osmotic-pressure, transfer-free-energy, or
long-timescale solution validation. The current calibration handoff also
states that the available 10 ns AA reference is not demonstrated to be
converged. A successful short CG run must therefore remain an execution
check, not a validation claim.
