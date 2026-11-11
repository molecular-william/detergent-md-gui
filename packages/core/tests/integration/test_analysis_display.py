"""Analysis artifact metadata stays attached to indexed figures."""
import json

from dashboard.analysis.runs import observability


def test_artifact_index_attaches_nearest_analysis_metadata(tmp_path):
    output = tmp_path / 'analysis' / 'plots' / 'output'
    output.mkdir(parents=True)
    (output / 'score.svg').write_text('<svg/>')
    (output.parent / 'analysis-metadata.json').write_text(json.dumps({
        'title': 'Wasserstein distance',
        'units_or_direction': 'nm; lower is better',
        'legacy': False,
    }))
    entries = observability.artifacts(tmp_path)
    score = next(item for item in entries if item['path'].endswith('score.svg'))
    assert score['metadata']['title'] == 'Wasserstein distance'
    assert score['metadata']['units_or_direction'] == 'nm; lower is better'


def test_the_surfaces_figure_is_not_listed_as_a_figure(dashboard):
    """The surfaces analysis's old interactive HTML is an artifact, not a figure the viewer lists.

    The producer no longer writes it, but an attempt published before this round still has one on disk. It must not
    enter the figure list or the media-filtered artifact list; the artifact route still serves the file itself.
    """
    job = {'id': '123456abcdef', 'status': 'completed'}
    dashboard.coordinator.database().insert(job)
    run = dashboard.coordinator.run_path(job)
    surfaces = run / 'analyses/surfaces/sig/attempt/output/key/analysis/surfaces'
    surfaces.mkdir(parents=True)
    (surfaces / 'surface-comparison.html').write_text('<html>envelopes</html>')
    (surfaces / 'surface-comparison-aa-cg.json').write_text('{"panels": []}')
    (run / 'figure.svg').write_text('<svg/>')

    listed = dashboard.client.get('/api/jobs/123456abcdef/figures?refresh=1').json
    media = dashboard.client.get('/api/jobs/123456abcdef/artifacts?media=1&refresh=1').json

    assert [entry['path'] for entry in listed['artifacts']] == ['figure.svg']
    assert [entry['path'] for entry in media['artifacts']] == ['figure.svg']
