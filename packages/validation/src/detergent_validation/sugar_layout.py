"""The sugar CG run's layout data: where its one moleculetype lives.

The run's trajectory and structure use the engine's existing `4_CG_sim/prod/lig_CG.*` spellings, so no role is added.
The topology is not under `3_initial_CG/` like an AA-CG run's: `prepare` writes it into the run's shared `inputs/`
record, and this resolver is the one place that says so.
"""
from dashboard.analysis.runs import layout


def topology(root, name=None):
    """The sugar moleculetype a run simulated, recorded by `FINAL_ITP` and read from `inputs/`."""
    return layout.molecule_topology(root, ('inputs',), None, 'sugar topology', 'sugar topologies', name)


def register():
    layout.register(topology={'sugar_cg': topology})
