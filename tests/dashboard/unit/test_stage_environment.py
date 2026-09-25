"""One place decides the environment a stage runs in and the one a manifest records.

Five modules composed this by hand and they disagreed on the key order, and the analysis worker
built its subprocess environment from workflow.environment() while recording a hand-written
subset -- two sources for one thing, one of which a manifest cannot verify. The stage
environment and the recorded subset now come from one function, and these tests pin that the
recorded keys are the ones the stage actually runs with.
"""
from dashboard.execution import environment as environment_module


def test_the_recorded_subset_is_the_documented_keys():
    recorded = environment_module.recorded_environment()
    assert tuple(recorded) == environment_module.RECORDED_KEYS
    assert recorded == {k: environment_module.stage_environment()[k]
                        for k in environment_module.RECORDED_KEYS}


def test_the_recorded_environment_matches_what_the_stages_run_with():
    """The recorded values are the subprocess environment's, not fresh defaults."""
    whole = environment_module.environment()
    assert environment_module.recorded_environment() == {k: whole[k]
                                                         for k in environment_module.RECORDED_KEYS}
    assert whole['MPLBACKEND'] == 'Agg' and whole['OMP_NUM_THREADS'] == '8'


def test_extras_are_merged_once():
    recorded = environment_module.recorded_environment({'MPLBACKEND': 'pdf'})
    assert recorded['MPLBACKEND'] == 'pdf'
    assert recorded['PATH'] == environment_module.environment()['PATH']
