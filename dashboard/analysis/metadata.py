"""Stable explanations for dashboard analysis artifacts."""

DESCRIPTIONS = {
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
