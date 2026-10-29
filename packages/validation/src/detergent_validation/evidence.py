"""The evidence vocabulary this feature's report requires.

A section is report vocabulary, not an analysis kind: it says what a validation report must show and how to read it.
The profile names the sections a molecule class must carry, and the engine merges this table with the other installed
features' tables through `dashboard.features`. The feature that owns a report also owns the words it must contain.
"""

EVIDENCE_SECTIONS = {
    'mapped_geometry': ('Carbohydrate geometry and volume', 'SASA, ring geometry, and molecular volume should agree with the cited reference protocol.', 'nm², nm³, and geometric distributions'),
    'transfer_free_energy': ('Water-to-octanol transfer free energy', 'BAR estimates require both solvent legs, uncertainty, and a cited target.', 'kJ/mol; residual to target'),
    'osmotic_pressure': ('Concentration-dependent osmotic pressure', 'Every configured concentration must have a force/area estimate and uncertainty.', 'pressure units; residual to target'),
}

#: The section ids a molecule of this class must evidence. This distribution owns the report that requires them.
MOLECULE_PROFILES = {
    'carbohydrate': ('mapped_geometry', 'transfer_free_energy', 'osmotic_pressure'),
}
