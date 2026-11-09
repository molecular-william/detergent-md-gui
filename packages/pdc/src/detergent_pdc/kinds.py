"""The pdc analyses: the kinds this feature owns, registered through `Feature(kinds=...)`.

A kind is one row of `dashboard.analysis.kinds.Kind`; registration is the table, so the worker, the descriptions and
the analysis control read them through the engine's one vocabulary. `pdc-structure` is the first: it resolves the
run's own production leg through its `source_hook`, so the chosen trajectory is part of the analysis signature.
"""
from dashboard.analysis.kinds import Kind

from .analysis.runs import structure

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
)
