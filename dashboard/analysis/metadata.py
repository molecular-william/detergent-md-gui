"""Stable explanations for dashboard analysis artifacts."""

DESCRIPTIONS = {
    'mapped_geometry': ('Carbohydrate geometry and volume', 'SASA, ring geometry, and molecular volume should agree with the cited reference protocol.', 'nm², nm³, and geometric distributions'),
    'transfer_free_energy': ('Water-to-octanol transfer free energy', 'BAR estimates require both solvent legs, uncertainty, and a cited target.', 'kJ/mol; residual to target'),
    'osmotic_pressure': ('Concentration-dependent osmotic pressure', 'Every configured concentration must have a force/area estimate and uncertainty.', 'pressure units; residual to target'),
    'carbohydrate-validation': ('Carbohydrate validation report', 'Three independent evidence classes are required; setup checks remain diagnostic-only.', 'status and native evidence units'),
    'mapping-consistency': ('Mapping consistency', 'A model should reproduce the atomistic structure it was built from; agreement here is not experimental evidence.', 'nm, degrees, and distribution metrics'),
    'bartender-fit': ('BARTENDER bonded fit', 'A fitted term inside the reference ensemble\'s own spread reproduces the geometry the molecule has; agreement is a check against our own reference, not experimental evidence.', 'nm, degrees, and force constants'),
    'overlap': ('AA/CG bead overlap', 'The coarse-grained model should reproduce the intra-bead distance distributions of the atomistic reference it was built from; agreement is internal consistency, not experimental evidence.', 'overlap coefficient 0-1; higher is closer'),
    'osmotic-pressure': ('Osmotic pressure · one condition', "The wall force the confined solute exerts, recomputed from the run's own trajectory at the paper's 1000 kJ/mol/nm2 and divided by the dividing area. Both walls are reported: their mean is the pressure, and their ratio says whether the average has converged -- a one-sided load halves the mean, which is the failure the ratio exists to catch.", 'bar, and each wall\'s force in kJ/mol/nm'),
    'bonded-cross-check': ('Bonded terms · our fit against the estimate', 'The fitted force constants beside the ones an independent equipartition estimate reads from the same frames. The two are not expected to be equal -- one is a coupled distribution-matching fit, the other is per term -- but a term we write as a rigid constraint and the estimate reads as a spring is a different molecule.', 'nm, kJ/mol/nm^2, and which side calls each term a constraint'),
    'dihedral-fit': ('Dihedral terms · a criterion against the tool default', 'For every proper dihedral the topology declares, the multiplicity and force constant an AIC/BIC-chosen cosine fit reads from the same frames, beside the ones the tool wrote. Where they disagree, the tool default is what is being questioned -- agreement is not evidence the tool chose well.', 'degrees, kJ/mol, and a multiplicity'),
    'plots': ('SASA over time', 'AA and CG SASA should agree in mean and temporal variability; larger is not inherently better.', 'nm²; agreement of mean/SD is desired'),
    'surfaces': ('AA/CG solvent-accessible surface overlay', 'Aligned envelopes should occupy similar regions; a snapshot is not ensemble validation.', 'nm; visual agreement'),
    'observables': ('Interaction distributions', 'Bond, angle, and dihedral distributions should reproduce AA shapes and populations.', 'native observable units; mismatch is lower-is-better'),
    'refinement-score': ('Refinement score', 'Mismatch metrics are lower-is-better; 0 means identical distributions where the scorer defines that range.', 'native metric units'),
    'stability': ('Numerical stability', 'No LINCS warnings and finite coordinates are required, but passing does not establish physical validity.', 'counts and diagnostic signals'),
    'snapshots': ('Trajectory snapshots', 'Snapshots provide visual inspection and are not a distributional validation.', 'coordinates'),
    'targets': ('Analysis targets', 'Targets describe the comparison protocol; they are not a quality score.', 'protocol metadata'),
}


def describe(kind, result=None, legacy=False):
    title, ideal, units = DESCRIPTIONS.get(kind, (kind.replace('-', ' ').title(), 'Interpret with the run protocol and source metadata.', 'native units'))
    return {'schema_version':1,'kind':kind,'title':title,'ideal_result':ideal,'units_or_direction':units,
            'legacy':bool(legacy),'stats':result or {}}
