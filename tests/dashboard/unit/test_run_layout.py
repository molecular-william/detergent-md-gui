"""Two stage layouts, resolved by role rather than guessed at."""
from pathlib import Path

import pytest

from dashboard.analysis.runs import layout


def write(root, *paths):
    for path in paths:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('x')


def test_an_aa_only_run_publishes_its_reference_under_07(tmp_path):
    write(tmp_path, 'stages/07_reference/lig.xtc', 'stages/07_reference/lig.gro')
    assert layout.resolve(tmp_path, 'aa_trajectory') == tmp_path / 'stages/07_reference/lig.xtc'
    assert layout.resolve(tmp_path, 'aa_structure') == tmp_path / 'stages/07_reference/lig.gro'


def test_a_cg_consumer_reads_the_atomistic_reference_it_prepared(tmp_path):
    write(tmp_path, 'stages/1_AA-reference/prod/lig.xtc', 'stages/1_AA-reference/prod/lig.gro')
    assert layout.resolve(tmp_path, 'aa_trajectory') == tmp_path / 'stages/1_AA-reference/prod/lig.xtc'
    assert layout.resolve(tmp_path, 'aa_structure') == tmp_path / 'stages/1_AA-reference/prod/lig.gro'


def test_a_cg_consumer_resolves_its_mapped_and_coarse_grained_trajectories(tmp_path):
    write(tmp_path, 'stages/2_mapping/mapped.xtc', 'stages/2_mapping/mapped.gro',
          'stages/4_CG_sim/prod/lig_CG.xtc', 'stages/4_CG_sim/prod/lig_CG.gro')
    assert layout.resolve(tmp_path, 'mapped_trajectory').name == 'mapped.xtc'
    assert layout.resolve(tmp_path, 'mapped_structure').name == 'mapped.gro'
    assert layout.resolve(tmp_path, 'cg_trajectory').name == 'lig_CG.xtc'
    assert layout.resolve(tmp_path, 'cg_structure').name == 'lig_CG.gro'


def test_a_missing_role_names_every_path_it_looked_for(tmp_path):
    with pytest.raises(ValueError) as error:
        layout.resolve(tmp_path, 'cg_trajectory')
    message = str(error.value)
    assert '4_CG_sim/prod/lig_CG.xtc' in message and 'no cg_trajectory' in message


def test_a_run_holding_both_layouts_is_refused_rather_than_chosen(tmp_path):
    write(tmp_path, 'stages/07_reference/lig.xtc', 'stages/1_AA-reference/prod/lig.xtc')
    with pytest.raises(ValueError, match='more than one aa_trajectory'):
        layout.resolve(tmp_path, 'aa_trajectory')


def test_an_unknown_role_is_refused_with_the_known_ones(tmp_path):
    with pytest.raises(ValueError, match='Unknown run role'):
        layout.resolve(tmp_path, 'cg_trajectoryy')


def test_the_cg_topology_is_found_by_its_residue_name(tmp_path):
    write(tmp_path, 'stages/3_initial_CG/SUCR_initial.itp')
    assert layout.cg_topology(tmp_path).name == 'SUCR_initial.itp'


def test_a_system_topology_beside_it_is_not_taken_for_the_molecule(tmp_path):
    write(tmp_path, 'stages/3_initial_CG/SUCR_initial.itp', 'stages/3_initial_CG/system_EMPTY.top')
    assert layout.cg_topology(tmp_path).name == 'SUCR_initial.itp'


def test_two_candidate_topologies_are_refused_rather_than_ranked(tmp_path):
    write(tmp_path, 'stages/3_initial_CG/SUCR_initial.itp', 'stages/3_initial_CG/LIG.itp')
    with pytest.raises(ValueError, match='more than one CG molecule topology'):
        layout.cg_topology(tmp_path)


def test_a_topology_that_is_absent_says_so_with_the_glob(tmp_path):
    with pytest.raises(ValueError, match='3_initial_CG'):
        layout.cg_topology(tmp_path)


def test_the_summary_reports_absences_as_data_rather_than_raising(tmp_path):
    write(tmp_path, 'stages/07_reference/lig.xtc', 'stages/common/molecule/molecule.itp')
    report = layout.summary(tmp_path)
    assert report['aa_trajectory'] == 'stages/07_reference/lig.xtc'
    assert report['solute_topology'] == 'stages/common/molecule/molecule.itp'
    assert report['cg_trajectory'] is None and report['cg_topology'] is None
    assert set(report) == set(layout.CANDIDATES) | {'cg_topology'}


def test_the_work_directory_an_analysis_is_handed_has_the_same_files_without_stages(tmp_path):
    """`analysis.worker` copies the sources into a work directory rooted at the execution root.

    An analysis is handed that directory, not the run directory, so the same roles have to resolve when the
    stage directories are not under `stages/`. Until this was true, every published analysis that read
    through `layout` refused a completed run with "has no aa_structure" and "has no CG molecule topology".
    """
    write(tmp_path, '1_AA-reference/prod/lig.xtc', '1_AA-reference/prod/lig.gro',
          '2_mapping/mapped.xtc', '2_mapping/mapped.gro',
          '4_CG_sim/prod/lig_CG.xtc', '4_CG_sim/prod/lig_CG.gro')
    assert layout.resolve(tmp_path, 'aa_trajectory') == tmp_path / '1_AA-reference/prod/lig.xtc'
    assert layout.resolve(tmp_path, 'mapped_structure') == tmp_path / '2_mapping/mapped.gro'
    assert layout.resolve(tmp_path, 'cg_trajectory') == tmp_path / '4_CG_sim/prod/lig_CG.xtc'


def test_the_same_role_at_both_roots_is_still_an_ambiguity(tmp_path):
    write(tmp_path, '07_reference/lig.xtc', 'stages/07_reference/lig.xtc')
    with pytest.raises(ValueError, match='more than one aa_trajectory'):
        layout.resolve(tmp_path, 'aa_trajectory')


def test_the_recorded_topology_name_selects_among_the_files_a_fitted_run_leaves(tmp_path):
    """A completed run leaves six `.itp` files here; only the recorded one is the simulated molecule."""
    write(tmp_path, '3_initial_CG/SUCR.itp', '3_initial_CG/SUCR_initial.itp',
          '3_initial_CG/SUCR_coordinate_seed.itp', '3_initial_CG/SUCR_ff_inter.itp',
          '3_initial_CG/martini_v3.0.0.itp', '3_initial_CG/reference_sugars_v2.itp')
    with pytest.raises(ValueError, match='more than one CG molecule topology'):
        layout.cg_topology(tmp_path)
    assert layout.cg_topology(tmp_path, 'SUCR.itp').name == 'SUCR.itp'
    assert layout.summary(tmp_path, 'SUCR.itp')['cg_topology'] == '3_initial_CG/SUCR.itp'


def test_a_recorded_name_that_is_not_there_says_what_is(tmp_path):
    write(tmp_path, '3_initial_CG/SUCR_initial.itp', '3_initial_CG/martini_v3.0.0.itp')
    with pytest.raises(ValueError) as error:
        layout.cg_topology(tmp_path, 'SUCR.itp')
    assert 'has no SUCR.itp' in str(error.value) and 'SUCR_initial.itp' in str(error.value)


def test_the_detergent_topology_is_the_builds_own_name_among_the_libraries(tmp_path):
    """The measured `1_system` of `00b9ae6db23f` holds five `.itp` files, so a count cannot select the detergent.

    `detergent.itp` is the template's atomistic moleculetype, handed to the build as an input, and the three
    `martini_v3.0.0*.itp` are the force field; only `detergent_CG.itp` is the model the run simulated -- the file
    its `system.top` includes.
    """
    write(tmp_path, 'stages/1_system/detergent_CG.itp', 'stages/1_system/detergent.itp',
          'stages/1_system/martini_v3.0.0.itp', 'stages/1_system/martini_v3.0.0_solvents_v1.itp',
          'stages/1_system/martini_v3.0.0_ions_v1.itp')

    assert layout.pdc_topology(tmp_path).name == 'detergent_CG.itp'
    assert layout.coarse_topology(tmp_path, 'pdc').name == 'detergent_CG.itp'


def test_a_detergent_topology_is_found_in_a_staged_directory_holding_only_it(tmp_path):
    """A producer is handed the work directory its kind's sources made, which may hold one `.itp` and nothing else."""
    write(tmp_path, '1_system/DDM.itp')

    assert layout.pdc_topology(tmp_path).name == 'DDM.itp'
    assert layout.coarse_topology(tmp_path, None).name == 'DDM.itp', \
        'without a run type, the layout the run wrote answers'


def test_two_detergent_candidate_topologies_are_refused_rather_than_ranked(tmp_path):
    """No build-name file and more than one other: refused, naming what it found, for `cg_topology`'s reason."""
    write(tmp_path, 'stages/1_system/DDM.itp', 'stages/1_system/DDM_v2.itp')

    with pytest.raises(ValueError, match='more than one candidate detergent topology'):
        layout.pdc_topology(tmp_path)


def test_a_run_type_names_the_directory_its_topology_lives_in(tmp_path):
    """`coarse_topology` is the one entry point: `pdc` answers from `1_system/`, everything else from `3_initial_CG/`."""
    write(tmp_path, 'stages/1_system/detergent_CG.itp', 'stages/3_initial_CG/SUCR_initial.itp')

    assert layout.coarse_topology(tmp_path, 'pdc').name == 'detergent_CG.itp'
    assert layout.coarse_topology(tmp_path, 'aa_cg').name == 'SUCR_initial.itp'
    assert layout.coarse_topology(tmp_path, 'aa_only').name == 'SUCR_initial.itp'


def test_the_detergent_topology_name_is_the_adapters_own():
    """`layout` cannot import an execution adapter, so it spells the name again; this is what keeps them one name."""
    from dashboard.execution.adapters import pdc

    assert layout.PDC_TOPOLOGY_NAME == pdc.DETERGENT_TOPOLOGY == 'detergent_CG.itp'
    system = Path(pdc.stage_by_name('System preparation').relative).parent.as_posix()
    assert system in layout.PDC_TOPOLOGY_DIRS, 'the build stage\'s directory must be a spelling the reader knows'


def test_the_pdc_stage_table_names_the_adapters_own_directories():
    """The layout table is the only copy of the stage->directory rule; the adapter must not drift from it."""
    from dashboard.execution.adapters import pdc

    adapter = {Path(stage.relative).parent.name for stage in pdc.STAGES}
    assert adapter <= set(layout.PDC_STAGE_KEYS), 'the adapter writes a stage directory the readers do not know'
    assert len(adapter) == len(layout.PDC_STAGE_DIRECTORIES), 'one numbered directory per pdc stage'


def test_the_frame_source_prefers_the_extracted_solute_over_the_stage_output(tmp_path):
    """A current CG run holds both: the stage's raw `md.xtc` and the solute `trjconv` extracted from it.

    They are two generations of one artifact, not two spellings of one, so `resolve`'s exactly-one rule would
    refuse such a run -- the preference is stated instead of being an ambiguity.
    """
    write(tmp_path, 'stages/4_CG_sim/md.xtc', 'stages/4_CG_sim/md.gro',
          'stages/4_CG_sim/prod/lig_CG.xtc', 'stages/4_CG_sim/prod/lig_CG.gro')

    trajectory, structure, role = layout.frame_source(tmp_path)

    assert trajectory == tmp_path / 'stages/4_CG_sim/prod/lig_CG.xtc'
    assert structure == tmp_path / 'stages/4_CG_sim/prod/lig_CG.gro'
    assert role == 'cg_trajectory'


def test_the_frame_source_reads_the_stages_own_output_when_the_solute_was_never_extracted(tmp_path):
    """The measured older layout: `4_CG_sim/{eq,md}.xtc` with no `prod/` beside them."""
    write(tmp_path, 'stages/4_CG_sim/eq.xtc', 'stages/4_CG_sim/eq.gro',
          'stages/4_CG_sim/md.xtc', 'stages/4_CG_sim/md.gro')

    trajectory, structure, role = layout.frame_source(tmp_path)

    assert trajectory == tmp_path / 'stages/4_CG_sim/md.xtc'
    assert structure == tmp_path / 'stages/4_CG_sim/md.gro'
    assert role == 'cg_stage_trajectory'


def test_the_frame_source_reads_an_aa_only_runs_published_reference(tmp_path):
    write(tmp_path, 'stages/07_reference/lig.xtc', 'stages/07_reference/lig.gro')

    trajectory, structure, role = layout.frame_source(tmp_path)

    assert trajectory == tmp_path / 'stages/07_reference/lig.xtc'
    assert structure == tmp_path / 'stages/07_reference/lig.gro'
    assert role == 'aa_trajectory'


def test_the_frame_source_resolves_the_work_directory_spelling(tmp_path):
    """The worker hands an analysis a work directory whose files sit at the root, not under `stages/`."""
    write(tmp_path, '1_AA-reference/prod/lig.xtc', '1_AA-reference/prod/lig.gro')

    assert layout.frame_source(tmp_path)[0] == tmp_path / '1_AA-reference/prod/lig.xtc'


def test_a_run_with_no_trajectory_to_review_names_what_it_looked_for(tmp_path):
    with pytest.raises(ValueError) as error:
        layout.frame_source(tmp_path)

    message = str(error.value)
    assert 'no trajectory to review' in message
    assert '07_reference/lig.xtc' in message and '4_CG_sim/md.xtc' in message


def test_an_ambiguous_role_is_refused_rather_than_stepped_over(tmp_path):
    """A run spelling one role two ways is a defect, not a reason to review a different trajectory."""
    write(tmp_path, 'stages/07_reference/lig.xtc', 'stages/07_reference/lig.gro',
          'stages/1_AA-reference/prod/lig.xtc', 'stages/1_AA-reference/prod/lig.gro')

    with pytest.raises(ValueError, match='more than one aa_trajectory'):
        layout.frame_source(tmp_path)


def test_an_osmotic_stage_resolves_under_stages_and_at_the_legacy_run_root(tmp_path):
    """The osmotic stage moved to `stages/01_simulate`; two runs in this workspace keep it at the run root."""
    write(tmp_path, 'stages/01_simulate/conditions/00_1molal/osmotic_condition.json')
    assert layout.stage_root(tmp_path) == tmp_path / 'stages'

    legacy = tmp_path / 'legacy'
    write(legacy, '01_simulate/osmotic_condition.json')
    assert layout.stage_root(legacy) == legacy


def test_the_osmotic_kind_stages_a_condition_now_that_the_stage_is_under_stages(tmp_path):
    """The kind's patterns are relative to the stage root, so `stages/01_simulate/...` is the same declaration."""
    from dashboard.analysis import worker

    write(tmp_path, 'stages/01_simulate/osmotic_condition.json', 'stages/01_simulate/plumed.dat',
          'stages/01_simulate/solvated.gro', 'stages/01_simulate/prod/md_whole.xtc')

    entries = worker.source_entries(layout.stage_root(tmp_path), 'osmotic-pressure')

    assert set(entries) == {'01_simulate/osmotic_condition.json', '01_simulate/plumed.dat',
                            '01_simulate/solvated.gro', '01_simulate/prod/md_whole.xtc'}
