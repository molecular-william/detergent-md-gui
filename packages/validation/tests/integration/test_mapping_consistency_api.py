"""The AA-vs-CG comparison, read from the record the analysis published.

The panel renders numbers a reader may quote, so the route reads the published attempt — its `result.json` and
the artifact that names — instead of recomputing anything. These tests build the attempt by hand because that
is what the worker leaves behind: a content-addressed output directory under the attempt, named by the record.
"""
import json

from detergent_validation.analysis.runs import ff_interactions

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
              'run_type': 'cg', 'profile': 'draft-smoke-reference',
              'parameterization': {'kind': 'revision'}, 'reference_run_id': '03875cf39790',
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
    'scientifically_validated': False,
    'aa_cg_comparison': 'analysis/surfaces/surface-comparison-aa-cg.json',
    'statistics': {'AA': {'frames': 20001, 'start_ps': 0.0, 'end_ps': 200000.0,
                          'mean_nm2': 5.8157, 'std_nm2': 0.077, 'xvg': 'analysis/surfaces/aa/sasa.xvg'},
                   'Simulated CG': {'frames': 20001, 'start_ps': 0.0, 'end_ps': 200000.0,
                                    'mean_nm2': 5.599, 'std_nm2': 0.174,
                                    'xvg': 'analysis/surfaces/simulated-cg/sasa.xvg'}},
}


def publish_surfaces(dashboard, jid, attempt='attempt1', output='output/abc123', surfaces=None):
    """Leave behind what `analysis.worker` leaves behind for a completed surfaces analysis."""
    directory = dashboard.coordinator.RUNS / jid / 'analyses/surfaces/hash' / attempt
    published = surfaces if surfaces is not None else SURFACES
    surfaces_dir = directory / output / 'analysis/surfaces'
    surfaces_dir.mkdir(parents=True)
    (surfaces_dir / 'metadata.json').write_text(json.dumps(published))
    (surfaces_dir / 'surface-comparison-aa-cg.json').write_text(json.dumps({'panels': []}))
    (surfaces_dir / 'aa').mkdir(exist_ok=True); (surfaces_dir / 'simulated-cg').mkdir(exist_ok=True)
    (surfaces_dir / 'aa/sasa.xvg').write_text('0 5.80\n100 5.82\n')
    (surfaces_dir / 'simulated-cg/sasa.xvg').write_text('0 5.60\n100 5.59\n')
    (directory / 'result.json').write_text(json.dumps(
        {'result': published, 'output_directory': output, 'wall_seconds': 121.0}))
    return directory


def test_a_published_surfaces_analysis_comes_with_its_numbers(dashboard):
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
    # The removed interactive figure is not a payload field; the pair JSON is the Shape pane's data.
    assert 'figure' not in surfaces
    assert surfaces['aa_cg_comparison'] == ('analyses/surfaces/hash/attempt1/output/abc123/'
                                            'analysis/surfaces/surface-comparison-aa-cg.json')
    assert surfaces['statistics']['AA']['xvg'] == ('analyses/surfaces/hash/attempt1/output/abc123/'
                                                    'analysis/surfaces/aa/sasa.xvg')
    assert surfaces['statistics']['Simulated CG']['xvg'].endswith(
        'output/abc123/analysis/surfaces/simulated-cg/sasa.xvg')
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


def test_the_queue_request_is_derived_from_the_run_it_belongs_to(dashboard, monkeypatch):
    """The button sends no path and no snapshot: the route fills both from the run's own record.

    The comparison is the run's mapping against the run's own trajectory, so a request that could name a different
    snapshot would let the panel show numbers for a mapping the run did not consume.
    """
    job(dashboard, 'ab12cd34ef56', molecule_id='LMNG', detergent='LMNG')
    run = dashboard.coordinator.RUNS / 'ab12cd34ef56'
    run.mkdir(parents=True)
    (run / 'manifest.json').write_text(json.dumps({
        'mapping_candidate': {'name': 'LMNG mapping', 'beads': [
            {'atoms': [1, 2], 'residue': 1, 'letter': 'A', 'name': 'S1A', 'type': 'SP1r'}]},
        'cg_names': {'final_itp': 'LMNG.itp'},
    }))
    captured = {}

    def queue(jid, kind, payload, **_):
        captured.update(jid=jid, kind=kind, payload=payload)
        return {'id': 'queued1', 'kind': kind, 'status': 'queued'}, 202

    monkeypatch.setattr(dashboard.coordinator.analysis_coordinator, 'queue', queue)
    response = dashboard.client.post('/api/jobs/ab12cd34ef56/mapping-consistency', json={})

    assert response.status_code == 202
    assert captured['jid'] == 'ab12cd34ef56' and captured['kind'] == 'mapping-consistency'
    assert captured['payload']['mapping_snapshot']['beads'][0]['name'] == 'S1A'
    assert captured['payload']['molecule'] == 'LMNG'
    assert captured['payload']['cg_topology'] == 'LMNG.itp'


def test_a_run_that_records_no_mapping_snapshot_is_refused(dashboard):
    """A run cannot be compared through someone else's mapping, so the refusal names what is missing."""
    job(dashboard, 'cd34ef56ab12')
    run = dashboard.coordinator.RUNS / 'cd34ef56ab12'
    run.mkdir(parents=True)
    (run / 'manifest.json').write_text(json.dumps({'cg_names': {'final_itp': 'X.itp'}}))

    response = dashboard.client.post('/api/jobs/cd34ef56ab12/mapping-consistency', json={})

    assert response.status_code == 400
    assert 'no mapping snapshot' in response.json['error']


def test_an_atomistic_only_run_is_refused(dashboard):
    job(dashboard, 'ef56ab12cd34', run_type='aa_only')
    run = dashboard.coordinator.RUNS / 'ef56ab12cd34'
    run.mkdir(parents=True)
    (run / 'manifest.json').write_text(json.dumps({'cg_names': {'final_itp': 'X.itp'}}))

    response = dashboard.client.post('/api/jobs/ef56ab12cd34/mapping-consistency', json={})

    assert response.status_code == 400
    assert 'CG run' in response.json['error']


def test_a_reference_or_composition_kind_cg_run_is_refused(dashboard):
    """Only a revision-kind CG run has the mapped trajectory and the terms this comparison reads."""
    job(dashboard, 'ab12cd34ef57', parameterization={'kind': 'reference', 'sugar_entry': 'SUCR'})
    (dashboard.coordinator.RUNS / 'ab12cd34ef57').mkdir(parents=True)
    (dashboard.coordinator.RUNS / 'ab12cd34ef57' / 'manifest.json').write_text(json.dumps(
        {'parameterization': {'kind': 'reference', 'sugar_entry': 'SUCR'}}))

    response = dashboard.client.post('/api/jobs/ab12cd34ef57/mapping-consistency', json={})

    assert response.status_code == 400
    assert 'parameterization revision' in response.json['error']


# ------------------------------------------------------------------------------------ Fast-Forward interactions

FF_MODEL = {'beads': [
    {'export_name': 'B01', 'residue': 1, 'letter': 'A'},
    {'export_name': 'B02', 'residue': 1, 'letter': 'B'},
    {'export_name': 'B03', 'residue': 2, 'letter': 'A'},
    {'export_name': 'B04', 'residue': 2, 'letter': 'B'},
]}
FF_REPORT = """ [ Interaction Distribution Report ]
   Overall Score : 0.238 +/- 0.0208

 bonds
\tB01_B02             : 0.18 (0.17)

 angles
\tB01_B02_B03         : 0.44 (0.41)

 dihedrals
\tB01_B02_B03_B04     : 0.21 (0.19)
"""


def distr(path, base):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'0.20 {base}\n0.30 {base * 2}\n0.40 {base / 2}\n')


def ff_work(tmp_path, *, consumed=False):
    """A staged work directory shaped the way the analysis worker leaves it."""
    work = tmp_path / 'work'
    (work / '2_mapping').mkdir(parents=True)
    (work / '2_mapping/model.json').write_text(json.dumps(FF_MODEL))
    (work / '5_assessment').mkdir(parents=True)
    (work / '5_assessment/report_interactions.out').write_text(FF_REPORT)
    for name in ('B01_B02_bonds', 'B01_B02_B03_angles', 'B01_B02_B03_B04_dihedrals'):
        distr(work / '5_assessment' / f'{name}_distr.dat', 0.5)
    if consumed:
        (work / '3_initial_CG').mkdir(parents=True)
        store = tmp_path / 'store'
        entries = []
        for name in ('B01_B02_bonds', 'B01_B02_B03_angles', 'B01_B02_B03_B04_dihedrals'):
            path = store / f'{name}_distr.dat'; distr(path, 0.7)
            entries.append({'name': str(path), 'sha256': 'x'})
        (work / '3_initial_CG/parameterization_used.json').write_text(json.dumps(
            {'fitted': False, 'engine': 'fast-forward', 'revision': 1,
             'reference_distributions': entries}))
        (work / 'store').mkdir()
        for entry in entries:
            source = tmp_path / 'store' / entry['name'].rsplit('/', 1)[-1]
            (work / 'store' / source.name).write_text(source.read_text())
    else:
        (work / '3_initial_CG').mkdir(parents=True)
        for name in ('B01_B02_bonds', 'B01_B02_B03_angles', 'B01_B02_B03_B04_dihedrals'):
            distr(work / '3_initial_CG' / f'{name}_distr.dat', 0.7)
        (work / '3_initial_CG/bonded_fit.json').write_text(json.dumps({'temperature_k': 303.0}))
    return work


def test_the_ff_record_reads_the_fitted_shape_and_its_metrics(tmp_path):
    work = ff_work(tmp_path)
    record = ff_interactions.publish(work)

    assert record['source'] == 'fitted' and record['scope'] == 'bonded-terms'
    assert record['reference']['from'] == 'stage 3 ff_inter'
    assert record['reference']['fit_temperature_k'] == 303.0
    terms = {term['name']: term for term in record['terms']}
    assert set(terms) == {'B01_B02', 'B01_B02_B03', 'B01_B02_B03_B04'}
    bond = terms['B01_B02']
    assert bond['section'] == 'bonds' and bond['label'] == '(1,A) - (1,B)' and bond['unit'] == 'nm'
    assert bond['hellinger'] == 0.18 and bond['ff_score'] == 0.17
    assert bond['reference']['density'] == [0.7, 1.4, 0.35]
    assert bond['simulated']['density'] == [0.5, 1.0, 0.25]
    assert (work / 'ff-interactions.json').is_file()
    assert json.loads((work / 'ff-interactions.json').read_text())['terms'] == record['terms']


def test_the_ff_record_reads_the_consumed_shape_from_the_store(tmp_path):
    work = ff_work(tmp_path, consumed=True)
    record = ff_interactions.publish(work)

    assert record['source'] == 'consumed'
    assert record['reference']['from'] == 'parameterization store'
    assert record['reference']['revision'] == 1 and record['reference']['engine'] == 'fast-forward'
    bond = next(term for term in record['terms'] if term['name'] == 'B01_B02')
    assert bond['reference']['density'] == [0.7, 1.4, 0.35]
    assert bond['simulated']['density'] == [0.5, 1.0, 0.25]


def test_a_missing_side_is_named_rather_than_drawn_as_a_comparison(tmp_path):
    work = ff_work(tmp_path)
    (work / '3_initial_CG/B01_B02_bonds_distr.dat').unlink()
    record = ff_interactions.publish(work)

    bond = next(term for term in record['terms'] if term['name'] == 'B01_B02')
    assert 'reference' not in bond
    assert 'fitted no reference histogram' in bond['reference_missing']
    assert bond['simulated']


def test_the_source_hook_stages_the_store_for_a_consuming_run(tmp_path):
    run = tmp_path / 'run'
    stages = run / 'stages'
    stages.mkdir(parents=True)
    (stages / '2_mapping').mkdir()
    (stages / '2_mapping/model.json').write_text(json.dumps(FF_MODEL))
    (stages / '5_assessment').mkdir()
    (stages / '5_assessment/report_interactions.out').write_text(FF_REPORT)
    distr(stages / '5_assessment/B01_B02_bonds_distr.dat', 0.5)
    store = tmp_path / 'store'
    reference = store / 'B01_B02_bonds_distr.dat'; distr(reference, 0.7)
    (stages / '3_initial_CG').mkdir()
    (stages / '3_initial_CG/parameterization_used.json').write_text(json.dumps(
        {'reference_distributions': [{'name': str(reference), 'sha256': 'x'}]}))

    entries = ff_interactions.sources(run)

    assert entries['store/B01_B02_bonds_distr.dat'] == reference
    assert '3_initial_CG/parameterization_used.json' in entries
    assert '5_assessment/report_interactions.out' in entries


def publish_ff(dashboard, jid, record):
    directory = dashboard.coordinator.RUNS / jid / 'analyses/ff-interactions/hash/attempt1'
    output = directory / 'output/abc123'
    output.mkdir(parents=True)
    (output / 'ff-interactions.json').write_text(json.dumps(record))
    (directory / 'result.json').write_text(json.dumps(
        {'result': record, 'output_directory': 'output/abc123', 'wall_seconds': 1.0}))


def test_the_ff_route_serves_the_published_record(dashboard):
    job(dashboard, 'aa11bb22cc33')
    publish_ff(dashboard, 'aa11bb22cc33', {'schema_version': 1, 'scope': 'bonded-terms', 'available': True,
                                           'source': 'consumed', 'terms': [{'name': 'B01_B02', 'section': 'bonds',
                                                                           'label': '(1,A) - (1,B)'}]})

    body = dashboard.client.get('/api/jobs/aa11bb22cc33/ff-interactions').json

    assert body['available'] is True and body['source'] == 'consumed'
    assert body['attempt'] == 'attempt1' and body['terms'][0]['name'] == 'B01_B02'
    assert body['published_at']


def test_the_ff_route_says_why_there_is_no_record(dashboard):
    job(dashboard, 'bb22cc33dd44')

    body = dashboard.client.get('/api/jobs/bb22cc33dd44/ff-interactions').json

    assert body['available'] is False
    assert 'no fast-forward interaction record' in body['reason'].lower()


def test_the_source_hook_stages_a_fitted_runs_own_histograms(tmp_path):
    run = tmp_path / 'run'
    stages = run / 'stages'
    (stages / '2_mapping').mkdir(parents=True)
    (stages / '2_mapping/model.json').write_text(json.dumps(FF_MODEL))
    (stages / '5_assessment').mkdir()
    (stages / '5_assessment/report_interactions.out').write_text(FF_REPORT)
    distr(stages / '5_assessment/B01_B02_bonds_distr.dat', 0.5)
    (stages / '3_initial_CG').mkdir()
    distr(stages / '3_initial_CG/B01_B02_bonds_distr.dat', 0.7)
    (stages / '3_initial_CG/bonded_fit.json').write_text(json.dumps({'temperature_k': 303.0}))

    entries = ff_interactions.sources(run)

    assert entries['3_initial_CG/B01_B02_bonds_distr.dat'].is_file()
    assert entries['3_initial_CG/bonded_fit.json'].is_file()
    assert not [name for name in entries if name.startswith('store/')]
