"""The coordinator's public surface: no method that only forwards.

A one-line pass-through hides which collaborator owns the state and gives a second name
to the same operation, so a reader has to check two places to learn that a route's
listing is the store's listing. Eight of them went. The four that stay each enforce
something -- this pins that they keep saying what.
"""
import pytest

from dashboard.execution.coordination.coordinator import Coordinator

FORWARDS = ('load', 'save', 'update_job', 'update_analysis', 'analysis_dependencies',
            'run_analysis', 'cancel_analysis', 'queue_analysis')
KEPT = ('database', 'lookup', 'manifest_data', 'now')


@pytest.mark.parametrize('name', FORWARDS)
def test_a_pass_through_method_is_gone(name):
    assert not hasattr(Coordinator, name), \
        f'{name} only forwards; callers reach the collaborator it owns'


@pytest.mark.parametrize('name', KEPT)
def test_a_kept_method_states_the_invariant_it_enforces(name):
    assert (getattr(Coordinator, name).__doc__ or '').strip(), \
        f'{name} stays only because it enforces something; say what'
