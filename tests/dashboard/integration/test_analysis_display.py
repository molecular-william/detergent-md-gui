"""Analysis artifact metadata stays attached to indexed figures."""
import json

from dashboard.analysis import observability


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
