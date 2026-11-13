"""The molecule profiles this feature's report requires.

A profile names the evidence section ids a molecule class must carry; the engine merges this table with the other
installed features' profiles through `dashboard.features`. The feature that owns a report owns the vocabulary its
report must contain.
"""

#: The section ids a molecule of this class must evidence. This distribution owns the report that requires them.
MOLECULE_PROFILES = {
    'carbohydrate': ('mapped_geometry', 'transfer_free_energy', 'osmotic_pressure'),
}
