"""Which area a test module belongs to, in one table, so a subset can be run without the suite.

`-m pdc` runs the protein-detergent tests, `-m 'mapping and not browser'` the mapping ones without a browser, and
`-m 'not slow and not browser'` stays the fast tier. The areas are matched against a module's path inside
`tests/dashboard` in this order, first match wins; `tests/dashboard/unit/test_test_areas.py` fails when a module matches
none or more than one, so a new file is categorised on the pass that adds it instead of drifting into whichever pattern
happens to catch it.

Order matters where a name is ambiguous: `test_cg_mapping_script.py` is a mapping test, not a CG-adapter one, so the
narrower patterns come first.
"""
import fnmatch
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent

AREAS = {
    'pdc': (
        'unit/test_pdc_*', 'integration/test_pdc_*', 'browser/test_pdc_*',
        # Back-mapping's fragment generator is pdc's own conversion science, named for the tool it feeds.
        'unit/test_cg2at_fragment.py',
        # The micelle builder is pdc's placement science; a change there is a change to a protein build.
        'unit/test_micelle_*', 'integration/test_micelle_api.py',
    ),
    'mapping': (
        'unit/test_mapping_*', 'unit/test_draft_*', 'unit/test_screen_candidates.py', 'unit/test_ring_scale.py',
        'unit/test_ngl_beads.py', 'unit/test_cg_mapping_script.py', 'unit/test_cg_molecule_names.py',
        'unit/test_export_bundle_imports.py',
        'integration/test_mapping_*', 'browser/test_mapping_*', 'browser/test_bead_editor_controls_browser.py',
    ),
    'bonded': (
        'unit/test_bonded*', 'unit/test_bartender_fit.py', 'unit/test_dihedral_fit.py',
        'unit/test_prepare_ring_constraints.py', 'unit/test_parameterization_*', 'unit/test_fitted_reference.py',
        'unit/test_cg_parameterization_consumption.py', 'unit/test_cg_reference_distributions.py',
        'unit/test_migrate_parameterization_owners.py', 'unit/test_cg_models.py',
        'integration/test_bonded_api.py', 'integration/test_parameterization_*',
        'browser/test_bonded_*',
    ),
    'carbohydrate': (
        'unit/test_sugar_*', 'unit/test_carbohydrate*', 'unit/test_sucrose_*', 'unit/test_fragment_grouping.py',
        'integration/test_sucrose_reference_mapping.py',
    ),
    'aa': (
        'unit/test_aa_*', 'unit/test_forcefields.py', 'unit/test_prepared_manifest.py',
        'integration/test_aa_*', 'browser/test_aa_*',
    ),
    'analysis': (
        'unit/test_analysis_*', 'unit/test_assessment_rescore.py',
        'unit/test_consistency_*', 'unit/test_current_figures.py', 'unit/test_distance_diagnostics_plot.py',
        'unit/test_overlap_*', 'unit/test_cross_check_reader.py', 'unit/test_kinds_published.py',
        'unit/test_default_analyses.py', 'unit/test_transferability_reader.py', 'unit/test_transfer_free_energy.py',
        'unit/test_model_topology.py', 'unit/test_reference_caching.py',
        'integration/test_analysis_*', 'integration/test_assessment_rescore.py', 'integration/test_default_analyses.py',
        'integration/test_distance_diagnostics_api.py',
        'integration/test_transferability_api.py',
        'browser/test_analyses_draft_browser.py', 'browser/test_assessment_rescore_browser.py',
        'browser/test_figure_viewer.py',
    ),
    'osmotic': (
        'unit/test_osmotic_*', 'integration/test_osmotic_*', 'browser/test_osmotic_*',
    ),
    'molecules': (
        'unit/test_detergent_*', 'unit/test_composition_*', 'unit/test_properties_*', 'unit/test_identity.py',
        'unit/test_reference_identity.py',
        'integration/test_detergent_list.py', 'integration/test_compositions_api.py',
        'integration/test_molecule_discovery.py', 'browser/test_composition_*',
    ),
    'web': (
        'unit/test_dashboard_factory.py', 'unit/test_sections.py', 'unit/test_paths.py', 'unit/test_json_repository.py',
        'unit/test_deferred_imports.py', 'unit/test_temporary_validation_cleanup.py',
        'integration/test_dashboard.py', 'integration/test_app_factory.py', 'integration/test_dom_ids.py',
        'integration/test_rendered_hosts.py', 'integration/test_request_bodies.py',
        'integration/test_api_error_contract.py', 'integration/test_workspace_panels.py',
        'integration/test_collection_shapes.py',
        'browser/test_dashboard_browser.py', 'browser/test_lazy_loading.py', 'browser/test_plotly_lazy_browser.py',
        'browser/test_workspace_navigation_browser.py',
    ),
    'runs': (
        'unit/test_run_*', 'unit/test_stage_*', 'unit/test_progress_reading.py', 'unit/test_attempt.py',
        'unit/test_candidate_verdict.py', 'unit/test_workflow_plan_pairs.py', 'unit/test_coordinator_surface.py',
        'unit/test_run_type_matrix.py', 'unit/test_prepare_time_skips.py',
        'integration/test_in_place_resume.py', 'integration/test_job*.py', 'integration/test_jobs_run_type_filter.py',
        'integration/test_readiness_*.py', 'integration/test_run_*.py', 'integration/test_stage_*.py',
        'unit/test_cg_adapter_molecule_scoped.py', 'unit/test_cg_run_type_staging.py', 'unit/test_cg_inputs.py',
        'integration/test_cg_prepare_contract.py',
        'browser/test_runs_table_browser.py', 'browser/test_run_view_*', 'browser/test_new_run_*',
    ),
    'infra': (
        'unit/test_agents_contract.py', 'unit/test_tool_probe.py', 'unit/test_tools.py', 'unit/test_devices.py',
        'unit/test_gpu_launchers.py', 'unit/test_mdrun_gpu*.py', 'unit/test_protocol.py', 'unit/test_profiles.py',
        'unit/test_domain_errors.py', 'unit/test_named_defaults.py', 'unit/test_migrate_digests.py',
        'unit/test_migrate_run_layout.py', 'unit/test_mdp_writer.py', 'unit/test_martini3.py',
        'unit/test_module_layout.py', 'unit/test_test_areas.py',
        'integration/test_operations.py', 'integration/test_reset_workspace.py',
        'integration/test_performance_api.py',
    ),
}


def area_of(path):
    """The area a module's path names, or `None`; the first match in `AREAS` order wins."""
    try:
        relative = Path(path).resolve().relative_to(TESTS_ROOT).as_posix()
    except (ValueError, OSError):
        return None
    for name, patterns in AREAS.items():
        if any(fnmatch.fnmatch(relative, pattern) for pattern in patterns):
            return name
    return None
