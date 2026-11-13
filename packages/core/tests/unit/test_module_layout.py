"""The shared CG stage scripts and the helpers they run as modules live in the repository.

The retired-path and package-move guards this file used to carry scanned a nonexistent root
directory, so they could not fail for the reason they named. They were deleted with the move they
guarded; what remains is the check that a run's scripts are actually present.
"""
from dashboard import paths as dashboard_paths
from dashboard.execution.adapters import cg


def test_run_preparation_scripts_are_present():
    """The shared CG stage scripts and the helpers they run as modules live in the repository.

    `finalize_mapping.py` is not among them any more: it existed to check and re-time bundled `ff_map` output, and
    the one mapper that has ever run here writes its own times and records its own check.
    """
    assert cg.SCRIPTS.is_dir(), f'{cg.SCRIPTS} is not a directory'
    # The scripts are the package's, not the data root's: the package lives under packages/core/src when the
    # dashboard runs from a checkout, and in site-packages when it is installed.
    assert cg.SCRIPTS == dashboard_paths.PACKAGE_ROOT / 'execution/scripts'
    modules = ('refine_bonded.py', 'sugar_mapping.py', 'prepare_ring_constraints.py', 'use_parameterization.py',
               'validate_run.py', 'distance_diagnostics.py')
    assert [name for name in modules if not (cg.SCRIPTS / name).is_file()] == []
    scripts = ('aa_reference.sh', 'map_trajectory.sh', 'fit_topology.sh', 'use_parameterization.sh',
               'cg_simulation.sh', 'assess.sh', 'sasa.sh')
    assert [name for name in scripts if not (cg.SCRIPTS / name).is_file()] == []
