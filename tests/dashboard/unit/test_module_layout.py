"""Guard the package layout: retired module paths must not be imported.

This is the acceptance criterion for the layout move. Both tests carry an
``xfail`` marker while the move is in flight; the phase is complete when the
markers are removed and both pass.
"""
import importlib
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]

# Every path here is a module that a later layout phase relocates. Keeping the
# list explicit means an unfinished move fails loudly instead of leaving an old
# path in place beside a new one.
RETIRED = (
    # models: mapping cluster -> models/candidates/
    'dashboard.models.mapping_schema', 'dashboard.models.mapping_store',
    'dashboard.models.mapping_graph', 'dashboard.models.mapping_context',
    'dashboard.models.mapping_exports', 'dashboard.models.mapping_suggestions',
    'dashboard.models.mapping_references', 'dashboard.models.depiction',
    # models: sugar cluster -> models/sugars/
    'dashboard.models.sugar_recognition', 'dashboard.models.sugar_mapping',
    'dashboard.models.sugar_topology', 'dashboard.models.carbohydrate',
    # models: bonded, molecule and shared clusters
    'dashboard.models.bonded_states', 'dashboard.models.bonded_generation',
    'dashboard.models.aa_molecules', 'dashboard.models.model_registry',
    'dashboard.models.draft_model', 'dashboard.models.packaged_ddm_source',
    'dashboard.models.composition_topology', 'dashboard.models.cg_models',
    'dashboard.models.json_repository', 'dashboard.models.evidence',
    # execution: adapters and coordination
    'dashboard.execution.aa_workflow', 'dashboard.execution.cg_adapter',
    'dashboard.execution.cg_workflow', 'dashboard.execution.composition_workflow',
    'dashboard.execution.stage_io', 'dashboard.execution.micelle_job',
    'dashboard.execution.coordinator', 'dashboard.execution.worker',
    'dashboard.execution.analysis_coordinator', 'dashboard.execution.admission',
    'dashboard.execution.resources', 'dashboard.execution.temporary',
    'dashboard.execution.manifest',
    # analysis: validation and run analyses
    'dashboard.analysis.carbohydrate_geometry', 'dashboard.analysis.carbohydrate_targets',
    'dashboard.analysis.carbohydrate_validation', 'dashboard.analysis.transfer_free_energy',
    'dashboard.analysis.osmotic_pressure', 'dashboard.analysis.aa_references',
    'dashboard.analysis.observability', 'dashboard.analysis.refinement',
    'dashboard.analysis.surfaces',
    # web: one route module per concept
    'dashboard.web.routes.models',
)

NEW_MODULES = (
    'dashboard.models.candidates.schema', 'dashboard.models.candidates.store',
    'dashboard.models.candidates.context', 'dashboard.models.compositions.model',
    'dashboard.models.bonded.states', 'dashboard.models.sugars.coords',
    'dashboard.models.molecules.aa', 'dashboard.execution.adapters.aa',
    'dashboard.execution.adapters.cg', 'dashboard.execution.coordination.coordinator',
    'dashboard.analysis.validation.report', 'dashboard.analysis.runs.references',
)


@pytest.mark.xfail(reason='layout move in progress', strict=False)
def test_no_module_imports_a_retired_path():
    offenders = []
    for path in sorted(list((ROOT / 'dashboard').rglob('*.py')) + list((ROOT / 'tests').rglob('*.py'))):
        if '.venv' in path.parts:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.match(r'\s*(from|import)\s', line) and any(name in line for name in RETIRED):
                offenders.append(f'{path.relative_to(ROOT)}:{number}')
    assert not offenders, 'Retired import paths remain: ' + ', '.join(offenders)


@pytest.mark.parametrize('name', NEW_MODULES)
@pytest.mark.xfail(reason='layout move in progress', strict=False)
def test_new_paths_are_importable(name):
    assert importlib.import_module(name)
