"""Guard the package layout: retired module paths must not be imported.

Every import is resolved to an absolute dotted module name before the check, so
a bare list member is caught as well as a dotted path:

    from dashboard.web.routes import models          -> dashboard.web.routes.models
    from dashboard.models.mapping_store import get   -> dashboard.models.mapping_store

Relative imports resolve against the importing file's own package, which is
what makes `from . import models` inside web/routes/ visible here. A plain
substring search over import lines missed exactly that case: the retired route
module was imported by its bare name in a from-list and stayed invisible until
the AST walk replaced it.
"""
import ast
import importlib
import pathlib
import pkgutil
from pathlib import Path

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]

# One entry per module the layout move retired, grouped by the package it left.
RETIRED = (
    'dashboard.models.mapping_schema', 'dashboard.models.mapping_store',
    'dashboard.models.mapping_graph', 'dashboard.models.mapping_context',
    'dashboard.models.mapping_exports', 'dashboard.models.mapping_suggestions',
    'dashboard.models.mapping_references', 'dashboard.models.depiction',
    'dashboard.models.carbohydrates', 'dashboard.models.carbohydrate_validation',
    'dashboard.models.sugar_recognition', 'dashboard.models.sugar_mapping',
    'dashboard.models.sugar_topology',
    'dashboard.models.bonded_states', 'dashboard.models.bonded_generation',
    'dashboard.models.aa_molecules', 'dashboard.models.model_registry',
    'dashboard.models.draft_model', 'dashboard.models.packaged_ddm_source',
    'dashboard.models.composition_topology', 'dashboard.models.cg_models',
    'dashboard.models.json_repository', 'dashboard.models.evidence',
    'dashboard.execution.aa_workflow', 'dashboard.execution.cg_adapter',
    'dashboard.execution.cg_workflow', 'dashboard.execution.composition_workflow',
    'dashboard.execution.micelle_job', 'dashboard.execution.stage_io',
    'dashboard.execution.coordinator', 'dashboard.execution.worker',
    'dashboard.execution.analysis_coordinator', 'dashboard.execution.admission',
    'dashboard.execution.resources', 'dashboard.execution.temporary',
    'dashboard.execution.manifest',
    'dashboard.analysis.carbohydrate_validation', 'dashboard.analysis.carbohydrate_geometry',
    'dashboard.analysis.carbohydrate_targets', 'dashboard.analysis.transfer_free_energy',
    'dashboard.analysis.osmotic_pressure', 'dashboard.analysis.aa_references',
    'dashboard.analysis.observability', 'dashboard.analysis.refinement',
    'dashboard.analysis.surfaces', 'dashboard.analysis.targets',
    'dashboard.web.routes.models',
)

# The target layout: each name is a module the move created.
NEW_MODULES = (
    'dashboard.models.mappings', 'dashboard.models.mappings.schema',
    'dashboard.models.mappings.store', 'dashboard.models.mappings.context',
    'dashboard.models.mappings.references', 'dashboard.models.mappings.exports',
    'dashboard.models.bonded', 'dashboard.models.bonded.states',
    'dashboard.models.bonded.generation', 'dashboard.models.sugars',
    'dashboard.models.sugars.coords', 'dashboard.models.sugars.validation',
    'dashboard.models.compositions', 'dashboard.models.compositions.topology',
    'dashboard.models.molecules', 'dashboard.models.molecules.aa',
    'dashboard.models.molecules.registry', 'dashboard.models.repository',
    'dashboard.models.catalog',
    'dashboard.execution.adapters.aa', 'dashboard.execution.adapters.cg',
    'dashboard.execution.adapters.cg_names', 'dashboard.execution.adapters.composition',
    'dashboard.execution.adapters.micelle', 'dashboard.execution.environment',
    'dashboard.execution.coordination.coordinator', 'dashboard.execution.coordination.worker',
    'dashboard.execution.coordination.manifest', 'dashboard.execution.coordination.resources',
    'dashboard.analysis.validation.report', 'dashboard.analysis.validation.geometry',
    'dashboard.analysis.validation.targets', 'dashboard.analysis.runs.references',
    'dashboard.analysis.runs.surfaces',
    'dashboard.web.routes.common', 'dashboard.web.routes.mappings',
    'dashboard.web.routes.bonded', 'dashboard.web.routes.catalog',
    'dashboard.web.routes.refinement',
)


def _package(path):
    parts = list(path.relative_to(ROOT).with_suffix('').parts)
    return '.'.join(parts[:-1])


def imported_modules(path):
    """Absolute dotted names a file imports, including from-list members."""
    tree = ast.parse(path.read_text())
    package = _package(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split('.') if package else []
                climbed = node.level - 1
                if climbed:
                    parts = parts[:len(parts) - climbed]
                base = '.'.join(parts + ([node.module] if node.module else []))
            else:
                base = node.module or ''
            if base:
                yield base
            for alias in node.names:
                yield f'{base}.{alias.name}' if base else alias.name


def sources():
    for path in sorted(list((ROOT / 'dashboard').rglob('*.py')) + list((ROOT / 'tests').rglob('*.py'))):
        if '.venv' not in path.parts:
            yield path


def module_names():
    root = str(ROOT / 'dashboard')
    return sorted(name for _, name, _ in pkgutil.walk_packages([root], prefix='dashboard.')
                  if '.venv' not in name)


def test_module_level_path_constants_point_at_real_locations():
    """A moved module breaks its own `Path(__file__)` arithmetic silently.

    Nothing fails at import time and no unit test notices: the constant is only
    dereferenced by a real run. Both instances this guard was written from were
    exactly that -- after the adapters moved, `cg.SCRIPTS` computed
    execution/adapters/scripts (absent) and every script copy in run
    preparation would have raised FileNotFoundError; after the molecule modules
    moved, `aa.PACKAGED` computed dashboard/molecules/DDM/results/MMFF.

    Paths that a run creates later are listed as optional with the reason, so
    a genuinely missing constant cannot hide behind them.
    """
    optional = {
        # Written when the smoke mapping is saved; absent in a fresh checkout.
        'dashboard.models.molecules.draft.CANDIDATE',
    }
    missing = []
    for name in module_names():
        module = importlib.import_module(name)
        for attr, value in vars(module).items():
            key = f'{name}.{attr}'
            if attr.startswith('__') or not isinstance(value, pathlib.Path):
                continue
            if key in optional or value.exists():
                continue
            missing.append(f'{key} -> {value}')
    assert not missing, 'Module-level paths that do not exist: ' + '; '.join(missing)


def test_run_preparation_scripts_are_present():
    """cg.py copies these into each run directory; the adapter owns the list.

    `finalize_mapping.py` is not among them any more: it existed to check and re-time bundled `ff_map` output, and
    the one mapper that has ever run here writes its own times and records its own check.
    """
    from dashboard.execution import environment
    from dashboard.execution.adapters import cg

    assert cg.SCRIPTS.is_dir(), f'{cg.SCRIPTS} is not a directory'
    assert cg.SCRIPTS == Path(environment.ROOT / 'dashboard/execution/scripts')
    copied = ('refine_bonded.py', 'sugar_mapping.py',
              'prepare_ring_constraints.py', 'validate_run.py', 'distance_diagnostics.py')
    assert [name for name in copied if not (cg.SCRIPTS / name).is_file()] == []


def test_the_run_local_bonded_library_stays_standalone():
    """cg.py copies this one file into a run directory as bonded.py.

    The copy has no package beside it, so it must import nothing from the
    dashboard package: a relative import or a dashboard import would break
    every CG run at the point the copied file is first executed.
    """
    from dashboard.models import bonded

    source = pathlib.Path(bonded.__file__).read_text()
    offenders = [line for line in source.splitlines()
                 if line.startswith(('from .', 'import dashboard', 'from dashboard'))]
    assert not offenders, 'The copied bonded library imports the package: ' + '; '.join(offenders)


def test_no_module_imports_a_retired_path():
    offenders = sorted(f'{path.relative_to(ROOT)} -> {name}'
                       for path in sources()
                       for name in imported_modules(path)
                       if name in RETIRED)
    assert not offenders, 'Retired modules are still imported: ' + '; '.join(offenders)


@pytest.mark.parametrize('name', NEW_MODULES)
def test_new_paths_are_importable(name):
    assert importlib.import_module(name)
