"""Stopping an osmotic series on the first condition that ends failed.

The other half of the series' behaviour. `POST /api/osmotic/series` creates every condition up front and the
coordinator runs them one at a time; when a condition ends `failed` (after its retries) the series' remaining
conditions either carry on -- the historical contract and the default -- or are cancelled, with the gap recorded
on the failed run. The choice travels in the condition's own `settings` under `series_on_failure`, the setting the
run type advertises and the queue route already forwards; this module declares nothing new, it consumes the choice.

**The failure path is the subject.** Every test here drives the coordinator's real terminal-failure path
(`run_job`, which writes `failed` and then stops the series), not the helper it calls, so a hook that is defined
but never wired is a failing test rather than a passing one. The siblings are seeded straight into the store,
because a fixture cannot stand up a reviewed CG model and the batch route -- at `max_concurrent_runs: 1` -- can
create only its first condition.
"""
import dataclasses
import subprocess

import pytest

from dashboard import files
from dashboard.execution import protocol, workflow
from dashboard.execution.adapters import osmotic

# On the slow tier: a series stop spans runner subprocesses, which is what the marker renders.
pytestmark = pytest.mark.slow


SERIES = 'series0stop01'
FAILED = 'fa11ed000001'
FIRST = 'ca11ed000001'
SECOND = 'ba11ed000001'


def _condition(owner, run_id, molality, *, status='queued', series_id=SERIES,
               series_on_failure=None, **extra):
    """One condition in the store, with the settings the queue route stores for it."""
    settings = {'osmotic_molality': molality, 'series_id': series_id, 'solute_root': '/tmp/solute'}
    if series_on_failure is not None:
        settings['series_on_failure'] = series_on_failure
    job = {'id': run_id, 'label': f'Maltose osmotic {molality:g} molal', 'detergent': 'Maltose',
           'molecule_id': 'Maltose', 'method': 'fast_forward', 'run_type': 'osmotic',
           'status': status, 'stage': 'queued', 'created': owner.now(), 'profile': 'draft-smoke',
           'layout_version': 2, 'scientifically_validated': False, 'settings': settings, **extra}
    owner.database().insert(job)
    return job


def _run_to_failure(owner, monkeypatch, jid):
    """Drive a condition through the coordinator's own terminal-failure path, without GROMACS.

    Only the two seams a fixture cannot satisfy are replaced: the adapter's CG-model readiness (which needs a
    reviewed model) and the stage execution (which would shell out to a real `gmx`). Everything the failure
    actually travels through -- `run_job`, the attempt lifecycle, `finish_job` and whatever it calls -- is real.
    """
    def prepare(run_dir, metadata):
        files.atomic_json(run_dir / 'manifest.json', {'stages': [], 'stage_plan': ['Osmotic condition']})

    fake = dataclasses.replace(osmotic.PROTOCOL,
                               readiness=lambda metadata: {'ready': True, 'checks': [], 'blockers': []},
                               prepare=prepare)
    real = protocol.adapter_for
    monkeypatch.setattr(protocol, 'adapter_for', lambda name: fake if name == 'osmotic' else real(name))
    monkeypatch.setattr(workflow, 'run',
                        lambda *a, **k: (_ for _ in ()).throw(subprocess.CalledProcessError(1, ['gmx'])))
    owner.run_job(jid)


def _status(owner, run_id):
    return owner.lookup(run_id)['status']


def test_a_condition_that_ends_failed_cancels_the_rest_of_the_series_when_it_asked_to_stop(dashboard, monkeypatch):
    """Under `stop` the failed condition takes its siblings with it, and the gap is recorded on the failed run."""
    owner = dashboard.coordinator
    _condition(owner, FAILED, 1.0, status='running', series_on_failure='stop')
    _condition(owner, FIRST, 1.5, series_on_failure='stop')
    _condition(owner, SECOND, 2.0, series_on_failure='stop')

    _run_to_failure(owner, monkeypatch, FAILED)

    assert _status(owner, FAILED) == 'failed'
    assert _status(owner, FIRST) == 'cancelled'
    assert _status(owner, SECOND) == 'cancelled'
    for run_id, molality in ((FIRST, 1.5), (SECOND, 2.0)):
        error = owner.lookup(run_id)['error']
        assert 'Series stopped' in error and '1' in error, (run_id, error)
    gap = owner.lookup(FAILED)['series_stopped']
    assert {entry['id'] for entry in gap} == {FIRST, SECOND}
    assert {entry['molality'] for entry in gap} == {1.5, 2.0}


def test_a_condition_that_ends_failed_leaves_its_siblings_running_when_the_series_carries_on(dashboard, monkeypatch):
    """`carry_on` is the route's historical contract: a failed condition does not cancel what is left."""
    owner = dashboard.coordinator
    _condition(owner, FAILED, 1.0, status='running', series_on_failure='carry_on')
    _condition(owner, FIRST, 1.5, series_on_failure='carry_on')
    _condition(owner, SECOND, 2.0, series_on_failure='carry_on')

    _run_to_failure(owner, monkeypatch, FAILED)

    assert _status(owner, FAILED) == 'failed'
    assert _status(owner, FIRST) == 'queued'
    assert _status(owner, SECOND) == 'queued'
    assert 'series_stopped' not in owner.lookup(FAILED)


def test_the_default_when_no_choice_was_made_is_to_carry_on(dashboard, monkeypatch):
    """A condition stored before the choice existed carries no `series_on_failure`; the series must not stop."""
    owner = dashboard.coordinator
    _condition(owner, FAILED, 1.0, status='running')
    _condition(owner, FIRST, 1.5)

    _run_to_failure(owner, monkeypatch, FAILED)

    assert _status(owner, FIRST) == 'queued'
    assert 'series_stopped' not in owner.lookup(FAILED)


def test_a_series_sibling_still_running_is_stopped_through_its_own_cancel_event(dashboard, monkeypatch):
    """A sibling this coordinator is running is stopped the way `/control/<id>/cancel` stops one: the worker's own
    cancel event, never a signal aimed at a stored PID. The sibling worker is a second condition, so it is the
    sibling -- not the failing run -- whose flag must be set."""
    owner = dashboard.coordinator
    _condition(owner, FAILED, 1.0, status='running', series_on_failure='stop')
    _condition(owner, FIRST, 1.5, status='running', series_on_failure='stop')
    sibling_worker = owner.Worker()
    owner.WORKERS[FIRST] = sibling_worker

    try:
        _run_to_failure(owner, monkeypatch, FAILED)
        assert sibling_worker.cancel.is_set()
        assert _status(owner, FIRST) == 'cancelling'
    finally:
        owner.WORKERS.pop(FIRST, None)


def test_a_sibling_running_under_another_worker_is_not_falsely_marked_cancelled(dashboard, monkeypatch):
    """A `running` condition this coordinator owns no worker for cannot be stopped from here, so it is left as it
    is rather than recorded `cancelled` while a process is still on it -- the same refusal `/control/<id>/cancel`
    makes when it owns no worker."""
    owner = dashboard.coordinator
    _condition(owner, FAILED, 1.0, status='running', series_on_failure='stop')
    _condition(owner, FIRST, 1.5, status='running', series_on_failure='stop')

    _run_to_failure(owner, monkeypatch, FAILED)

    assert _status(owner, FIRST) == 'running'
    assert 'series_stopped' not in owner.lookup(FAILED)


def test_a_failure_in_a_different_series_does_not_touch_this_one(dashboard, monkeypatch):
    """The siblings are identified by the series id the run type already records, not by adjacency or timing."""
    owner = dashboard.coordinator
    _condition(owner, FAILED, 1.0, status='running', series_on_failure='stop', series_id='series0aaaaa1')
    _condition(owner, FIRST, 1.5, series_on_failure='stop', series_id='series0bbbbb1')

    _run_to_failure(owner, monkeypatch, FAILED)

    assert _status(owner, FIRST) == 'queued'


def test_a_failed_run_of_another_type_cannot_stop_an_osmotic_series(dashboard, monkeypatch):
    """Only a condition of this run type stops a series; a failure elsewhere that happens to carry a series id and
    the `stop` choice leaves the conditions alone."""
    owner = dashboard.coordinator
    _condition(owner, FIRST, 1.5, series_on_failure='stop')
    other = {'id': FAILED, 'label': 'DDM run', 'detergent': 'DDM', 'method': 'fast_forward',
             'run_type': 'aa_cg', 'status': 'running', 'stage': 'queued', 'created': owner.now(),
             'profile': 'draft-smoke', 'layout_version': 2,
             'settings': {'series_id': SERIES, 'series_on_failure': 'stop'}}
    owner.database().insert(other)

    _run_to_failure(owner, monkeypatch, FAILED)

    assert _status(owner, FAILED) == 'failed'
    assert _status(owner, FIRST) == 'queued'
