"""The trajectory-overview route and its source hook, against a run whose stages hold a trajectory.

The producer itself is pinned by `unit/test_run_trajectory_overview.py`; this file pins the seam a person uses --
the route queues the kind with no payload, and the hook stages the run's latest playable segment rather than every
trajectory the run wrote.
"""
import json

from dashboard.analysis.runs import trajectory_overview

JID = '123456abcdef'


def write(root, relative, text='', size=0):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text else 'x' * size)
    return path


def gro(count):
    row = f'{1:5d}{"DDM":<5s}{"B01":>5s}{1:5d}{0.1:8.3f}{0.2:8.3f}{0.3:8.3f}'
    return 'coarse-grained system\n' + f'{count:5d}\n' + (row + '\n') * count + '   8.00000   8.00000   8.00000\n'


def seed(dashboard):
    coordinator = dashboard.coordinator
    job = {'id': JID, 'label': 'Overview', 'detergent': 'DDM', 'method': 'pdc', 'profile': 'default',
           'status': 'completed', 'stage': 'complete', 'run_type': 'pdc', 'created': coordinator.now(),
           'analyses': [], 'settings': {'contact_nm': 0.6}}
    coordinator.database().replace([job])
    run = coordinator.RUNS / JID
    write(run, 'stages/3_nvt/system.xtc', size=120)
    write(run, 'stages/3_nvt/system.gro', gro(40))
    write(run, 'stages/4_npt/system.xtc', size=240)
    write(run, 'stages/4_npt/system.gro', gro(40))
    write(run, 'manifest.json', json.dumps({'run_type': 'pdc', 'status': 'completed', 'stages': [],
                                            'settings': {'contact_nm': 0.6}}))
    return coordinator, run


def test_the_route_queues_the_overview_with_no_payload(dashboard, monkeypatch):
    coordinator, _ = seed(dashboard)
    monkeypatch.setattr(coordinator.analysis_coordinator, 'run', lambda *args: None)

    response = dashboard.client.post(f'/api/jobs/{JID}/trajectory-overview', json={})

    assert response.status_code == 202, response.get_data(as_text=True)
    task = coordinator.lookup(JID)['analyses'][0]
    assert task['kind'] == 'trajectory-overview'
    assert task['payload'] == {}
    with coordinator.JOBS_LOCK:
        coordinator.ANALYSIS_WORKERS.pop((JID, task['id']), None)


def test_the_hook_stages_only_the_latest_playable_segment(dashboard):
    _, run = seed(dashboard)

    entries = trajectory_overview.sources(run)

    staged = set(entries)
    assert 'stages/4_npt/system.xtc' in staged, staged
    assert 'stages/4_npt/system.gro' in staged, staged
    assert 'stages/3_nvt/system.xtc' not in staged, 'an older playable segment was staged beside the latest one'


def test_the_hook_stages_each_equilibration_legs_energy_file(dashboard):
    """The third figure row reads one term per leg, so the hook stages each leg's own EDR explicitly."""
    _, run = seed(dashboard)
    write(run, '03_minimization/run.edr', size=10)
    write(run, '04_nvt/system.edr', size=10)
    write(run, '05_npt/run.edr', size=10)

    entries = trajectory_overview.sources(run)

    assert entries['03_minimization/run.edr'] == run / '03_minimization/run.edr'
    assert entries['04_nvt/system.edr'] == run / '04_nvt/system.edr'
    assert entries['05_npt/run.edr'] == run / '05_npt/run.edr'
