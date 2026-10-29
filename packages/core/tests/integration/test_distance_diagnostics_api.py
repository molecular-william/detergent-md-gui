"""The diagnostics reader, once the duplicate write is gone.

`distance_diagnostics.py` wrote the identical result to `distance_diagnostics.json` and
`distance_diagnostics_stratified.json`. It writes only the stratified name now, and the route keeps
its fallback for runs written before that -- which is the case whose pairs may predate the per-pair
`kind`, so the response says which file answered instead of leaving a reader to assume.

The stage contract never declared the unstratified name, which is why dropping the write cannot
break a stage's output verification; the first test asserts that too, since it is the reason the
change is safe.
"""
import json

from dashboard import paths
from dashboard.execution import workflow


def seed(dashboard, jid, written):
    runs = dashboard.coordinator.RUNS; runs.mkdir(parents=True, exist_ok=True)
    job = {'id': jid, 'label': 'Diagnostics run', 'detergent': 'DDM', 'method': 'fast_forward',
           'status': 'completed', 'stage': 'complete', 'created': dashboard.coordinator.now()}
    dashboard.coordinator.database().replace([job])
    # Where the route looks, asked rather than assumed: a run's stage directories live under its `stages/`.
    (runs / jid / 'stages').mkdir(parents=True, exist_ok=True)
    assessment = workflow.stage_root(runs / jid) / '5_assessment'; assessment.mkdir(parents=True)
    for name, payload in written.items():
        (assessment / name).write_text(json.dumps(payload))
    return job


def test_the_stage_contract_requires_only_the_stratified_file():
    from dashboard.execution.adapters import cg
    declared = [pattern for patterns in cg.REQUIRED_OUTPUTS.values() for pattern in patterns]
    assert 'distance_diagnostics_stratified.json' in declared
    assert 'distance_diagnostics.json' not in declared


def test_the_writer_emits_only_the_stratified_file():
    """The script's __main__ block is its whole writer; the duplicate name is gone from it."""
    source = (paths.PACKAGE_ROOT / 'execution/scripts/distance_diagnostics.py').read_text()
    writes = [line for line in source.splitlines() if '.write_text(' in line and 'json.dumps' in line]
    assert len(writes) == 1, writes
    assert 'distance_diagnostics_stratified.json' in writes[0]


def test_the_stratified_file_is_what_answers(dashboard):
    seed(dashboard, 'aa11bb22cc33', {'distance_diagnostics_stratified.json': {'pairs': [{'kind': 'physical'}]}})

    response = dashboard.client.get('/api/jobs/aa11bb22cc33/distance-diagnostics')

    assert response.status_code == 200
    assert response.json['legacy'] is False
    assert response.json['source'].endswith('distance_diagnostics_stratified.json')


def test_a_run_written_before_the_change_still_renders_and_is_marked_legacy(dashboard):
    seed(dashboard, 'dd44ee55ff66', {'distance_diagnostics.json': {'pairs': [{'beads': ['B01', 'B02']}]}})

    response = dashboard.client.get('/api/jobs/dd44ee55ff66/distance-diagnostics')

    assert response.status_code == 200
    assert response.json['legacy'] is True
    assert response.json['source'].endswith('distance_diagnostics.json')


def test_a_run_with_neither_file_is_still_a_404(dashboard):
    seed(dashboard, 'a0b1c2d3e4f5', {})

    assert dashboard.client.get('/api/jobs/a0b1c2d3e4f5/distance-diagnostics').status_code == 404
