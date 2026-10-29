"""The AA-vs-CG comparison, read from the record the analysis published.

The panel renders numbers a reader may quote, so the route reads the published attempt — its `result.json` and
the artifact that names — instead of recomputing anything. These tests build the attempt by hand because that
is what the worker leaves behind: a content-addressed output directory under the attempt, named by the record.
"""
import json

COMPARISON = {
    'schema_version': 1, 'comparison': 'AA vs CG', 'molecule': 'Sucrose', 'entry': 'SUCR',
    'pairs': {'counts': {'pairs': 6, 'compared': 6, 'cg_outside_aa_range': 1}, 'rows': []},
    'terms': [], 'displacement': {'rmsd_nm': 0.0149, 'max_nm': 0.0223},
    'diagnostic_only': True, 'scientifically_validated': False,
    'interpretation': 'This compares our model with our own atomistic reference.',
}


def job(dashboard, jid, **overrides):
    runs = dashboard.coordinator.RUNS; runs.mkdir(parents=True, exist_ok=True)
    record = {'id': jid, 'label': 'Sucrose CG consumer', 'detergent': 'Sucrose', 'method': 'fast_forward',
              'run_type': 'aa_cg', 'profile': 'draft-smoke-reference', 'reference_run_id': '03875cf39790',
              'molecule_id': 'Sucrose', 'status': 'completed', 'stage': 'complete',
              'created': dashboard.coordinator.now(), **overrides}
    dashboard.coordinator.database().replace([record])
    return record


def publish(dashboard, jid, attempt='attempt1', comparison=None, output='output/abc123', record=True):
    """Leave behind what `analysis.worker` leaves behind for a completed comparison."""
    directory = dashboard.coordinator.RUNS / jid / 'analyses/mapping-consistency/hash' / attempt
    (directory / output / 'analysis').mkdir(parents=True)
    (directory / output / 'analysis/mapping_consistency.json').write_text(
        json.dumps(comparison if comparison is not None else COMPARISON))
    if record:
        (directory / 'result.json').write_text(json.dumps(
            {'result': {'artifact': 'analysis/mapping_consistency.json', 'comparison': 'AA vs CG',
                        'pairs': {'pairs': 6, 'compared': 6, 'cg_outside_aa_range': 1},
                        'displacement_rmsd_nm': 0.0149, 'diagnostic_only': True},
             'output_directory': output, 'wall_seconds': 13.3}))
    return directory


SURFACES = {
    'probe_nm': 0.191, 'rendering': 'SAS mesh, GROMACS Connolly dots retained separately',
    'scientifically_validated': False, 'comparison_html': 'analysis/surfaces/surface-comparison.html',
    'statistics': {'AA': {'frames': 20001, 'start_ps': 0.0, 'end_ps': 200000.0,
                          'mean_nm2': 5.8157, 'std_nm2': 0.077},
                   'Simulated CG': {'frames': 20001, 'start_ps': 0.0, 'end_ps': 200000.0,
                                    'mean_nm2': 5.599, 'std_nm2': 0.174}},
}


def publish_surfaces(dashboard, jid, attempt='attempt1', output='output/abc123', surfaces=None):
    """Leave behind what `analysis.worker` leaves behind for a completed surfaces analysis."""
    directory = dashboard.coordinator.RUNS / jid / 'analyses/surfaces/hash' / attempt
    published = surfaces if surfaces is not None else SURFACES
    (directory / output / 'analysis/surfaces').mkdir(parents=True)
    (directory / output / 'analysis/surfaces/metadata.json').write_text(json.dumps(published))
    (directory / output / 'analysis/surfaces/surface-comparison.html').write_text('<html>envelopes</html>')
    (directory / 'result.json').write_text(json.dumps(
        {'result': published, 'output_directory': output, 'wall_seconds': 121.0}))
    return directory


def test_a_published_surfaces_analysis_comes_with_its_numbers_and_its_figure(dashboard):
    """The envelope analysis is its own kind and its own attempt; the panel reads what it published."""
    job(dashboard, 'aa11bb22cc33')
    publish(dashboard, 'aa11bb22cc33')
    publish_surfaces(dashboard, 'aa11bb22cc33')

    surfaces = dashboard.client.get('/api/jobs/aa11bb22cc33/mapping-consistency').json['surfaces']

    assert surfaces['available'] is True
    assert surfaces['statistics']['AA']['mean_nm2'] == 5.8157
    assert surfaces['statistics']['Simulated CG']['mean_nm2'] == 5.599
    assert surfaces['validated'] is False
    assert 'SAS mesh' in surfaces['rendering']
    # Relative to the run directory, so the panel builds the artifact URL from it and never from a filesystem path.
    assert surfaces['figure'] == ('analyses/surfaces/hash/attempt1/output/abc123/'
                                  'analysis/surfaces/surface-comparison.html')
    assert surfaces['source'].endswith('analysis/surfaces/metadata.json')


def test_a_run_with_no_surfaces_analysis_says_so_rather_than_showing_nothing(dashboard):
    """Never queued is a state, and a card that shows an empty frame reads as broken."""
    job(dashboard, 'aa11bb22cc33')
    publish(dashboard, 'aa11bb22cc33')

    surfaces = dashboard.client.get('/api/jobs/aa11bb22cc33/mapping-consistency').json['surfaces']

    assert surfaces['available'] is False
    assert 'surfaces' in surfaces['reason'].lower()
    assert 'figure' not in surfaces


def test_a_surfaces_record_whose_artifact_is_gone_falls_back_to_the_reason(dashboard):
    """An attempt that names a file no longer there is not a published analysis."""
    job(dashboard, 'aa11bb22cc33')
    publish(dashboard, 'aa11bb22cc33')
    directory = publish_surfaces(dashboard, 'aa11bb22cc33')
    (directory / 'output/abc123/analysis/surfaces/metadata.json').unlink()

    surfaces = dashboard.client.get('/api/jobs/aa11bb22cc33/mapping-consistency').json['surfaces']

    assert surfaces['available'] is False


def test_the_published_comparison_is_what_answers(dashboard):
    job(dashboard, 'aa11bb22cc33')
    publish(dashboard, 'aa11bb22cc33')

    response = dashboard.client.get('/api/jobs/aa11bb22cc33/mapping-consistency')

    assert response.status_code == 200
    body = response.json
    assert body['comparison']['comparison'] == 'AA vs CG'
    assert body['attempt'] == 'attempt1'
    assert body['source'].endswith('analysis/mapping_consistency.json')
    assert body['molecule'] == 'Sucrose' and body['reference_run_id'] == '03875cf39790'
    assert body['summary']['displacement_rmsd_nm'] == 0.0149
    assert body['published_at'], 'the record is dated, so a reader can tell staleness'
    assert body['comparison']['scientifically_validated'] is False


def test_a_run_with_no_published_comparison_says_so(dashboard):
    job(dashboard, 'dd44ee55ff66')

    response = dashboard.client.get('/api/jobs/dd44ee55ff66/mapping-consistency')

    assert response.status_code == 404
    assert 'No AA vs CG comparison' in response.get_data(as_text=True)


def test_an_attempt_that_names_a_missing_artifact_is_a_404_not_a_crash(dashboard):
    job(dashboard, 'a0b1c2d3e4f5')
    attempt = publish(dashboard, 'a0b1c2d3e4f5')
    record = json.loads((attempt / 'result.json').read_text())
    record['output_directory'] = 'output/gone'
    (attempt / 'result.json').write_text(json.dumps(record))

    response = dashboard.client.get('/api/jobs/a0b1c2d3e4f5/mapping-consistency')

    assert response.status_code == 404
    assert 'names no published comparison file' in response.get_data(as_text=True)


def test_the_newest_attempt_answers_when_several_exist(dashboard):
    """A re-run leaves both attempts; the reader gets the later one, and it says which.

    The mtimes are set rather than left to the filesystem: two writes inside the same clock tick would make
    "newest" a coin toss, and a reader choosing which of two published comparisons to quote is not a coin toss.
    """
    import os

    job(dashboard, '0f1e2d3c4b5a')
    first = publish(dashboard, '0f1e2d3c4b5a', attempt='attempt1')
    second = publish(dashboard, '0f1e2d3c4b5a', attempt='attempt2',
                     comparison={**COMPARISON, 'displacement': {'rmsd_nm': 0.0198}})
    os.utime(first / 'result.json', (1_700_000_000, 1_700_000_000))
    os.utime(second / 'result.json', (1_700_000_100, 1_700_000_100))

    response = dashboard.client.get('/api/jobs/0f1e2d3c4b5a/mapping-consistency')

    assert response.json['attempt'] == 'attempt2'
    assert response.json['comparison']['displacement']['rmsd_nm'] == 0.0198
