"""The timeline's stage list is names, because the timeline looks stages up by name.

A manifest's `stage_plan` is the workflow's `(name, script)` pairs and `stage_view` passed it through whole. The runs list
builds `new Map(stages.map(stage => [stage.name, stage]))` and then `stageMap.get(name)` for each entry of
`workflow_stages`: with pairs every lookup missed, `state` fell back to `'pending'`, and the dot's glyph table had nothing
for it. So a protein-detergent build -- the one run type whose plan is always recorded, because its scripts are generated
per run -- showed ten blank dots and no green tick for the seven stages it had actually completed.
"""
from dashboard.web import views
from detergent_pdc import view as pdc_view
from detergent_pdc.execution.adapters import pdc

PDC_PLAN = [[stage.name, stage.relative] for stage in pdc.STAGES]


def test_a_recorded_plan_reaches_the_timeline_as_names():
    job = {'run_type': 'pdc', 'id': '00b9ae6db23f', 'status': 'failed'}

    _, names = views.stage_view(job, {'stage_plan': PDC_PLAN, 'stages': []})

    assert names == [stage.name for stage in pdc.STAGES]
    assert all(isinstance(name, str) for name in names), 'a pair is not a stage name; the lookup needs the name'


def test_the_names_match_the_stage_records_the_timeline_joins_on():
    job = {'run_type': 'pdc', 'id': '00b9ae6db23f', 'status': 'failed'}
    stages = [{'name': 'Protein preparation', 'status': 'completed'},
              {'name': 'CG extension MD', 'status': 'failed'}]

    recorded, names = views.stage_view(job, {'stage_plan': PDC_PLAN, 'stages': stages})

    ticked = {stage['name'] for stage in recorded}
    assert ticked <= set(names), 'every stage a run recorded is a name the timeline can find'
    assert 'CG extension MD' in names and 'Protein preparation' in names


def test_a_job_with_no_recorded_plan_uses_its_own_run_type():
    """`cg.STAGES` is the last resort, not the answer for every run: a pdc job's plan is pdc's own."""
    job = {'run_type': 'pdc', 'id': 'abc', 'status': 'queued'}

    names = views.plan_names(job)

    assert names == [stage.name for stage in pdc.STAGES]
    assert 'CG simulation' not in names, 'an AA-CG stage name is not a protein-detergent stage name'


def test_a_plan_of_plain_names_is_left_alone():
    job = {'run_type': 'aa_cg', 'id': 'def'}
    manifest = {'stage_plan': ['AA reference', 'trajectory mapping']}

    assert views.stage_view(job, manifest)[1] == ['AA reference', 'trajectory mapping']


def test_the_run_card_predicts_the_settings_skips_before_the_stage_records_them():
    """The timeline is drawn from the static plan, so a queued no-removal or empty-micelle run used to show stages
    as pending that the settings already say will not run. These are previews only; the stage's own skip record wins."""

    empty = {'run_type': 'pdc', 'protein': None,
             'settings': {'prepare_protein': False, 'remove_out_of_micelle': False, 'backmap': True,
                          'minimisation_steps': 200000, 'nvt_ps': 500, 'npt_ps': 4500}}
    skips = pdc_view.planned_skips(empty)
    assert skips['Protein preparation'].startswith('empty micelle')
    assert set(skips) >= {'Micelle assessment', 'CG extension MD', 'Final assessment'}
    assert 'backmap' not in skips['Back-mapping (CG2AT2)']
    assert 'Back-mapping (CG2AT2)' in skips

    removal = {'run_type': 'pdc', 'protein': 'molecules/1qj8/1qj8.pdb',
               'settings': {'prepare_protein': True, 'remove_out_of_micelle': False, 'backmap': False,
                            'minimisation_steps': 0, 'nvt_ps': 0, 'npt_ps': 4500}}
    skips = pdc_view.planned_skips(removal)
    assert 'Protein preparation' not in skips and 'Micelle assessment' in skips
    assert 'Energy minimisation' in skips and 'NVT equilibration' in skips
    assert 'Back-mapping (CG2AT2)' in skips


def test_a_non_pdc_job_has_no_predicted_skips():
    assert pdc_view.planned_skips({'run_type': 'aa_cg', 'settings': {'remove_out_of_micelle': False}}) == {}
