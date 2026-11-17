"""The stage settings a run recorded, grouped by stage, and the bar's stage segments.

Two properties matter and are tested here rather than in the route tests: a group lists exactly the keys the run
recorded (no invented value, no dropped one), and the segments are arithmetic over the run's own plan -- the four AA
dynamics stages weighted by their step counts, the other run types' work stages in plan order with equal widths --
only the stages the run's plan contains, and sum to one.
"""
import pytest
from dashboard.web import stage_settings

AA_SETTINGS = {
    'aa_minimization_steps': 20000, 'aa_minimization_emtol': 1000, 'aa_minimization_emstep': 0.01,
    'aa_nvt_ps': 100, 'aa_nvt_dt_fs': 2, 'aa_nvt_tcpl': 'V-rescale',
    'aa_npt_ps': 1000, 'aa_npt_dt_fs': 2, 'aa_npt_tau_p': 5,
    'aa_production_ps': 10000, 'aa_production_dt_fs': 2,
    'temperature_k': 303.15, 'pressure_bar': 1, 'aa_seed': 20260917, 'output_interval_ps': 10,
    'force_field': 'charmm36-feb2026_cgenff-4.6', 'constraints': 'all-bonds', 'box_nm': 2.5,
    'box_shape': 'cubic', 'mdrun_gpu': 0, 'mdrun_ntomp': 8,
}
AA_JOB = {'run_type': 'aa_only', 'settings': AA_SETTINGS}


def keys(group):
    return [field['key'] for field in group['fields']]


def test_aa_groups_lists_the_recorded_keys_under_their_stage():
    groups = stage_settings.groups(AA_JOB, {})

    assert [group['label'] for group in groups] == \
           ['Energy minimization', 'NVT equilibration', 'NPT equilibration', 'NPT production', 'Run settings']
    assert keys(groups[0]) == ['aa_minimization_steps', 'aa_minimization_emtol', 'aa_minimization_emstep']
    assert keys(groups[1]) == ['aa_nvt_ps', 'aa_nvt_dt_fs', 'aa_nvt_tcpl']
    assert keys(groups[2]) == ['aa_npt_ps', 'aa_npt_dt_fs', 'aa_npt_tau_p']
    assert keys(groups[3]) == ['aa_production_ps', 'aa_production_dt_fs']
    assert keys(groups[4]) == ['temperature_k', 'pressure_bar', 'aa_seed', 'output_interval_ps', 'force_field',
                               'constraints', 'box_nm', 'box_shape', 'mdrun_gpu', 'mdrun_ntomp']


def test_aa_groups_show_no_key_the_run_did_not_record():
    recorded = {'aa_nvt_ps': 100, 'aa_nvt_dt_fs': 2, 'temperature_k': 303.15}
    groups = stage_settings.groups({'run_type': 'aa_only', 'settings': recorded}, {})

    assert [group['label'] for group in groups] == ['NVT equilibration', 'Run settings']
    flattened = [key for group in groups for key in keys(group)]
    assert sorted(flattened) == sorted(recorded), 'every recorded key appears once, and nothing else'


def test_a_label_comes_from_the_adapters_table_else_the_key_is_spaced():
    groups = stage_settings.groups(
        {'run_type': 'aa_only', 'settings': {'aa_nvt_dt_fs': 2, 'my_own_number': 3}}, {})

    assert groups[0]['fields'][0]['label'] == 'NVT timestep (fs)'
    assert groups[1]['fields'][0]['label'] == 'my own number'


def test_values_keep_their_recorded_type_and_arrays_stay_arrays():
    settings = {'aa_npt_ps': 1000, 'mdrun_flags': ['-nb', 'gpu'], 'mdrun_cpt': 10}
    groups = stage_settings.groups({'run_type': 'aa_only', 'settings': settings}, {})

    values = {field['key']: field['value'] for group in groups for field in group['fields']}
    assert values == {'aa_npt_ps': 1000, 'mdrun_flags': ['-nb', 'gpu'], 'mdrun_cpt': 10}


def test_cg_groups_split_the_two_legs_and_productions_own_options():
    settings = {'cg_minimization_steps': 500, 'cg_equil_ps': 10, 'cg_production_ps': 200,
                'nstlist': 40, 'verlet_buffer_tolerance': 0.005, 'nstxtcout': 100,
                'aa_production_ps': 100, 'mdrun_gpu': 0}
    groups = stage_settings.groups({'run_type': 'cg', 'settings': settings}, {})

    assert [group['label'] for group in groups] == \
           ['CG minimization', 'CG equilibration', 'CG production', 'Run settings']
    assert keys(groups[2]) == ['cg_production_ps', 'nstlist', 'verlet_buffer_tolerance', 'nstxtcout']
    assert keys(groups[3]) == ['aa_production_ps', 'mdrun_gpu']


def test_another_run_type_has_one_group_from_its_adapters_vocabulary(monkeypatch):
    class Stub:
        @staticmethod
        def settings_specs():
            return {'protein': ('Protein structure', None, None), 'ions': ('Ions', 0, 100)}

        @staticmethod
        def choice_specs():
            return {}

    monkeypatch.setattr(stage_settings.protocol, 'adapter_for', lambda run_type: Stub())
    groups = stage_settings.groups({'run_type': 'pdc', 'settings': {'protein': '/p.pdb', 'ions': 150}}, {})

    assert len(groups) == 1 and groups[0]['label'] == 'Run settings'
    assert [(field['key'], field['label']) for field in groups[0]['fields']] == \
           [('protein', 'Protein structure'), ('ions', 'Ions')]


def test_a_run_type_with_no_adapter_still_answers(monkeypatch):
    def missing(run_type):
        raise ValueError('unknown run type')

    monkeypatch.setattr(stage_settings.protocol, 'adapter_for', missing)
    groups = stage_settings.groups({'run_type': 'gone', 'settings': {'some_key': 1}}, {})

    assert keys(groups[0]) == ['some_key']


def test_the_manifests_settings_win_over_the_job_rows():
    manifest = {'run_type': 'aa_only', 'settings': {'aa_nvt_ps': 50, 'aa_nvt_dt_fs': 2}}
    job = {'run_type': 'aa_only', 'settings': {'aa_nvt_ps': 999, 'aa_nvt_dt_fs': 2}}

    values = {field['key']: field['value']
              for group in stage_settings.groups(job, manifest) for field in group['fields']}
    assert values['aa_nvt_ps'] == 50


def test_segments_are_the_four_aa_stages_in_plan_order():
    rows, total = stage_settings.segments(AA_JOB, {})

    assert [row['stage'] for row in rows] == ['AA minimization', 'AA NVT equilibration',
                                              'AA NPT equilibration', 'AA NPT production']
    assert [row['kind'] for row in rows] == ['min', 'nvt', 'npt', 'production']
    assert [row['steps'] for row in rows] == [20000, 50000, 500000, 5000000]
    assert total == sum(row['steps'] for row in rows) == 5570000
    assert sum(row['fraction'] for row in rows) == pytest.approx(1)
    assert rows[0]['fraction'] == pytest.approx(20000 / 5570000)


def test_segments_honour_the_runs_own_plan():
    manifest = {'run_type': 'aa_only', 'settings': AA_SETTINGS,
                'stage_plan': [['AA NVT equilibration', '04_nvt/run.sh'],
                               ['AA NPT production', '06_production/run.sh']]}

    rows, total = stage_settings.segments(AA_JOB, manifest)

    assert [row['stage'] for row in rows] == ['AA NVT equilibration', 'AA NPT production']
    assert total == 5050000
    assert sum(row['fraction'] for row in rows) == pytest.approx(1)


def test_a_names_only_legacy_plan_is_understood():
    rows, _ = stage_settings.segments({'run_type': 'aa_only', 'settings': AA_SETTINGS,
                                       'stage_plan': ['AA NVT equilibration']}, {})

    assert [row['stage'] for row in rows] == ['AA NVT equilibration']


def test_minimization_falls_back_to_the_reviewed_cap_for_an_older_run():
    settings = {key: value for key, value in AA_SETTINGS.items() if key != 'aa_minimization_steps'}

    rows, _ = stage_settings.segments({'run_type': 'aa_only', 'settings': settings}, {})

    assert rows[0]['steps'] == stage_settings.MINIMIZATION_STEPS_FALLBACK == 20000


CG_PLAN = ['AA reference', 'trajectory mapping', 'CG parameterization', 'CG simulation',
           'CG assessment (ff_assess)', 'SASA analysis']
PDC_PLAN = ['Protein preparation', 'System preparation', 'Energy minimisation', 'NVT equilibration',
            'NPT equilibration', 'CG assessment MD', 'Micelle assessment', 'CG extension MD',
            'Final assessment', 'Back-mapping (CG2AT2)']


def test_cg_segments_are_its_work_stages_with_equal_widths():
    rows, total = stage_settings.segments({'run_type': 'cg', 'settings': {}}, {'stage_plan': CG_PLAN})

    assert [row['stage'] for row in rows] == ['trajectory mapping', 'CG parameterization', 'CG simulation',
                                              'CG assessment (ff_assess)', 'SASA analysis']
    assert [row['kind'] for row in rows] == ['mapping', 'fit', 'production', 'assessment', 'analysis']
    assert [row['label'] for row in rows][:2] == ['Mapping', 'Parameterization']
    assert all(row['steps'] is None for row in rows), 'no comparable step count across these stages'
    assert total is None
    assert [row['fraction'] for row in rows] == pytest.approx([0.2] * 5)


def test_pdc_segments_are_its_work_stages_and_flag_a_planned_skip(monkeypatch):
    monkeypatch.setattr(stage_settings.features, 'planned_skips',
                        lambda job, manifest=None: {'Micelle assessment': 'no membrane'})
    rows, total = stage_settings.segments({'run_type': 'pdc', 'settings': {}}, {'stage_plan': PDC_PLAN})

    assert [row['stage'] for row in rows] == ['Energy minimisation', 'NVT equilibration', 'NPT equilibration',
                                              'CG assessment MD', 'Micelle assessment', 'CG extension MD',
                                              'Final assessment', 'Back-mapping (CG2AT2)']
    assert [row.get('skipped', False) for row in rows] == [False] * 4 + [True] + [False] * 3
    assert [row['fraction'] for row in rows] == pytest.approx([0.125] * 8)
    assert total is None


def test_osmotic_segments_are_its_one_stage():
    rows, total = stage_settings.segments({'run_type': 'osmotic', 'settings': {}},
                                          {'stage_plan': ['Osmotic series']})

    assert [row['stage'] for row in rows] == ['Osmotic series']
    assert rows[0]['fraction'] == pytest.approx(1)
    assert total is None


def test_a_run_type_with_no_segment_table_keeps_the_single_fill():
    assert stage_settings.segments({'run_type': 'aa_cg', 'settings': {}},
                                   {'stage_plan': PDC_PLAN}) == (None, None)


def test_a_plan_with_none_of_its_work_stages_keeps_the_single_fill():
    assert stage_settings.segments({'run_type': 'cg', 'settings': {}},
                                   {'stage_plan': [['AA minimization', '03_minimization/run.sh']]}) == (None, None)


def test_segments_are_none_when_the_numbers_cannot_be_computed():
    settings = {key: value for key, value in AA_SETTINGS.items() if key != 'aa_npt_dt_fs'}

    assert stage_settings.segments({'run_type': 'aa_only', 'settings': settings}, {}) == (None, None)

    zero = {**AA_SETTINGS, 'aa_production_dt_fs': 0}
    assert stage_settings.segments({'run_type': 'aa_only', 'settings': zero}, {}) == (None, None)


def test_payload_carries_the_groups_and_the_segments_the_bar_is_drawn_from():
    body = stage_settings.payload(AA_JOB, {})

    assert set(body) == {'groups', 'segments', 'total_steps'}
    assert body['total_steps'] == 5570000
    assert body['segments'] == stage_settings.segments(AA_JOB, {})[0]
    assert [field['key'] for field in body['groups'][0]['fields']][0] == 'aa_minimization_steps'
