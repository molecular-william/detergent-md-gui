"""The AA-CG run type's readiness asks about the profile it actually runs under.

`readiness()` gates its mapping check on the profile string (`if profile in ('draft-smoke','draft-smoke-reference')`)
and defaults to `'standard'` when a caller names none. The panel no longer offers an AA-CG run a profile choice and
sends none (D2 of `docs/design/2026-10-16-new-run-panel-refactor.md`), so that fallback both skipped the mapping
check and put a *standard*-parameterization blocker in front of a run type that has never run under that profile:

    standard              blockers ['A reviewed CG model is required for standard parameterization. Choose candidate …']
                          mapping checks []
    draft-smoke-reference blockers ['CG mapping: Select a saved CG mapping before launching candidate screening']
                          mapping checks [('CG mapping', False, 'Select a saved CG mapping before launching …')]

`cg._protocol_readiness` now falls back to `AA_CG_PROFILE`, which is also `prepare()`'s own default -- the same rule
in both places, which is what the second test here pins, because a fallback that drifts from the builder's default
would put the panel's answer and the run's behaviour apart again.
"""
import inspect

from dashboard.execution.adapters import cg


def test_readiness_under_the_run_types_own_profile_checks_the_mapping():
    answer = cg.readiness('Maltose', 'fast_forward', cg.AA_CG_PROFILE, None, 'molecules')
    mapping = [check for check in answer['checks'] if check['label'] == 'CG mapping']
    assert mapping, 'the AA-CG profile must be the one whose mapping check runs'
    assert mapping[0]['ready'] is False
    assert 'Select a saved CG mapping' in mapping[0]['detail']
    assert any('Select a saved CG mapping' in blocker for blocker in answer['blockers'])


def test_the_readiness_fallback_is_the_builders_own_default():
    """One string, two places: a caller naming no profile gets the same one from both."""
    assert inspect.signature(cg.prepare).parameters['profile'].default == cg.AA_CG_PROFILE
    source = inspect.getsource(cg._protocol_readiness)
    assert "metadata.get('profile') or AA_CG_PROFILE" in source


def test_the_readiness_route_asks_about_the_profile_the_run_type_runs_under(dashboard):
    """The adapter's fallback only reaches an answer the route does not overwrite.

    `/api/readiness` used to build its metadata with `request.args.get('profile', 'standard')`, so an AA-CG request
    that named no profile -- which is every request the panel makes, since D2 removed the choice -- was judged
    under `standard`. That put `A reviewed CG model is required for standard parameterization` in front of a run
    type that has never run under that profile, and skipped the mapping check the same string gates.
    """
    with dashboard.client as client:
        answer = client.get('/api/readiness?run_type=aa_cg').get_json()

    assert answer['profile'] == cg.AA_CG_PROFILE
    assert not [blocker for blocker in answer['blockers'] if 'standard parameterization' in blocker]
    assert any(check['label'] == 'CG mapping' for check in answer['checks'])


def test_a_typo_in_the_profile_is_still_reported_rather_than_silently_standard(dashboard):
    """The route's own default went away; its refusal of a name no run type has did not."""
    with dashboard.client as client:
        assert client.get('/api/readiness?run_type=aa_cg&profile=standrd').status_code == 400
        named = client.get('/api/readiness?run_type=aa_cg&profile=standard').get_json()

    assert named['profile'] == 'standard'
    assert any('standard parameterization' in blocker for blocker in named['blockers']), \
        'a caller that names standard still gets the standard answer'
