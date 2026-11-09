"""`/api/jobs/<jid>/analyses?view=summary` is a view of the same records, not a second answer.

The Run view's two 2 s pollers read only status, progress, directory and -- for a frame series -- payload and outputs.
The summary view drops the fields they never read (`result`, `environment`, `tools`, `command`), while the default
answer keeps the whole record for every other consumer.
"""
import json

SUMMARY_FIELDS = ('id', 'kind', 'status', 'created_at', 'started_at', 'ended_at', 'error', 'directory',
                  'progress', 'payload', 'outputs', 'stable')
DROPPED_FIELDS = ('result', 'environment', 'tools', 'command')


def test_the_summary_view_drops_only_the_heavy_fields_and_keeps_progress(dashboard):
    job_id = '123456abcdef'
    heavy = {'result': {'chart': 'x' * 5000}, 'environment': {'PATH': '/usr/bin'}, 'tools': {'gmx': '2026.3'},
             'command': ['gmx', 'mdrun']}
    completed = {'id': 'task-1', 'kind': 'ff-interactions', 'status': 'completed',
                 'created_at': '2026-11-08T10:00:00+00:00', 'started_at': '2026-11-08T10:00:01+00:00',
                 'ended_at': '2026-11-08T10:05:00+00:00', 'error': None,
                 'directory': 'analyses/ff-interactions/signature/1', 'payload': {'selection': ['A']},
                 'outputs': ['interactions.json'], 'stable': True, **heavy}
    running = {'id': 'task-2', 'kind': 'stability', 'status': 'running',
               'created_at': '2026-11-08T11:00:00+00:00', 'directory': 'analyses/stability/signature/2',
               'payload': {'window_ns': 1.0}, 'outputs': [], **heavy}
    dashboard.coordinator.database().insert({'id': job_id, 'status': 'completed',
                                             'analyses': [completed, running]})
    progress = dashboard.coordinator.run_path({'id': job_id}) / running['directory'] / 'progress.json'
    progress.parent.mkdir(parents=True)
    progress.write_text(json.dumps({'phase': 'building'}))

    client = dashboard.client
    full = client.get(f'/api/jobs/{job_id}/analyses').json
    assert len(full) == 2
    for task in full:
        for field in DROPPED_FIELDS:
            assert field in task, f'the default answer lost {field}, which the summary view is allowed to drop'
    assert full[1]['progress'] == 'building', 'the running attempt\'s phase is read before either view is answered'

    summary = client.get(f'/api/jobs/{job_id}/analyses?view=summary').json
    assert summary == [{field: task[field] for field in SUMMARY_FIELDS if field in task} for task in full]
    assert summary[1]['progress'] == 'building'
    for task in summary:
        assert not set(DROPPED_FIELDS) & set(task), task
