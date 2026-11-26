"""The pdc analyses: the kinds this feature owns, registered through `Feature(kinds=...)`.

A kind is one row of `dashboard.analysis.kinds.Kind`; registration is the table, so the worker, the descriptions and
the analysis control read them through the engine's one vocabulary. `pdc-structure` is the first: it resolves the
run's own production leg through its `source_hook`, so the chosen trajectory is part of the analysis identity.
"""
from dashboard.analysis.kinds import Kind

from .analysis.runs import interaction_energy, structure

KINDS = (
    Kind(
        'pdc-structure',
        (),
        structure.run,
        "Structure \u00b7 shape, size, radial distribution and contacts",
        "Radius of gyration, the run's own micelle size, radial distributions and bead contacts from one bounded "
        "sample of the production leg. It measures the sampled frames and establishes no convergence.",
        "nm, molecules, and bead counts",
        records_gmx_version=True,
        source_hook=structure.sources),
    Kind(
        'pdc-interaction-energy',
        (),
        interaction_energy.run,
        "Interaction energy \u00b7 receptor—detergent, receptor—receptor, receptor—water",
        "Short-range Lennard-Jones and reaction-field Coulomb energies between the receptor and the detergent, the "
        "receptor itself, and water, from a bounded rerun of the sampled production frames. It is not a decomposition "
        "of the total potential and not a binding free energy.",
        "kJ/mol",
        records_gmx_version=True,
        source_hook=interaction_energy.sources),
)
