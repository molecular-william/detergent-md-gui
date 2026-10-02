"""The same bead-type pair side by side across molecules, read from each run's own published comparison.

Same pattern as the single-run comparison's tests: the attempt is built by hand, because that is what the worker
leaves behind, and the mapping the run used comes from its own manifest rather than from anything the test
restates. Nothing here recomputes a comparison.
"""
import json


def row(pair, aa, cg=None):
    return {'pair': pair, 'aa': {'mean': aa}, 'cg': {'mean': aa if cg is None else cg}}


def comparison(rows, molecule):
    return {'schema_version': 1, 'comparison': 'AA vs CG', 'molecule': molecule, 'entry': 'SUCR',
            'pairs': {'counts': {'pairs': len(rows)}, 'rows': rows}, 'terms': [],
            'displacement': {}, 'diagnostic_only': True, 'scientifically_validated': False}


def publish(dashboard, jid, molecule, beads, rows):
    """A completed run with a mapping in its manifest and a published comparison, as the worker leaves them."""
    run = dashboard.coordinator.RUNS / jid
    (run / 'analyses/mapping-consistency/hash/attempt1/output/abc123/analysis').mkdir(parents=True)
    (run / 'manifest.json').write_text(json.dumps(
        {'mapping_candidate': {'name': f'{molecule} mapping', 'molecule_id': molecule, 'beads': [
            {'letter': letter, 'residue': 1, 'name': f'S1{letter}', 'type': bead_type}
            for letter, bead_type in beads]}}))
    (run / 'analyses/mapping-consistency/hash/attempt1/output/abc123/analysis/mapping_consistency.json'
     ).write_text(json.dumps(comparison(rows, molecule)))
    (run / 'analyses/mapping-consistency/hash/attempt1/result.json').write_text(json.dumps(
        {'result': {'artifact': 'analysis/mapping_consistency.json', 'comparison': 'AA vs CG',
                    'diagnostic_only': True},
         'output_directory': 'output/abc123', 'wall_seconds': 13.3}))
    dashboard.coordinator.database().insert(
        {'id': jid, 'label': f'{molecule} CG consumer', 'molecule_id': molecule, 'detergent': molecule,
         'method': 'fast_forward', 'run_type': 'aa_cg', 'profile': 'draft-smoke-reference',
         'status': 'completed', 'stage': 'complete', 'created': dashboard.coordinator.now()})


def two_molecules(dashboard):
    """Two rings naming the same edge, at the same distance -- the transferable case."""
    publish(dashboard, 'aa11bb22cc33', 'Sucrose', [('A', 'SN6'), ('C', 'SP1r')],
            [row([[1, 'A'], [1, 'C']], 0.4230)])
    publish(dashboard, 'bb22cc33dd44', 'Trehalose', [('A', 'SN6'), ('C', 'SP1r')],
            [row([[1, 'A'], [1, 'C']], 0.4226)])


def test_the_same_bead_types_are_compared_across_the_two_runs(dashboard):
    two_molecules(dashboard)

    response = dashboard.client.get('/api/runs/transferability?ids=aa11bb22cc33,bb22cc33dd44')

    assert response.status_code == 200
    body = response.json
    assert body['molecules'] == ['Sucrose', 'Trehalose']
    signature = body['signatures'][0]
    assert signature['types'] == ['SN6', 'SP1r'] and signature['role'] == 'intra'
    assert signature['pairs_match'] is True
    assert signature['molecules']['Sucrose']['atomistic_mean_nm'] == 0.4230
    assert signature['molecules']['Trehalose']['atomistic_mean_nm'] == 0.4226
    assert signature['spread_pct'] < 1
    assert body['scientifically_validated'] is False
    assert body['sources']['Sucrose']['run'] == 'aa11bb22cc33'
    assert body['sources']['Sucrose']['source'].endswith('analysis/mapping_consistency.json')


def test_the_same_types_on_different_edges_are_reported_as_not_comparable(dashboard):
    """`SP1r`|`SP1r` is one molecule's B-C edge and another's A-C edge: a spread between two bonds."""
    publish(dashboard, 'aa11bb22cc33', 'Maltose', [('B', 'SP1r'), ('C', 'SP1r')],
            [row([[1, 'B'], [1, 'C']], 0.3130)])
    publish(dashboard, 'bb22cc33dd44', 'Sucrose', [('A', 'SP1r'), ('C', 'SP1r')],
            [row([[1, 'A'], [1, 'C']], 0.4019)])

    body = dashboard.client.get('/api/runs/transferability?ids=aa11bb22cc33,bb22cc33dd44').json

    signature = body['signatures'][0]
    assert signature['pairs_match'] is False
    assert signature['molecules']['Maltose']['pairs'] == [['1B', '1C']]
    assert signature['molecules']['Sucrose']['pairs'] == [['1A', '1C']]


def test_one_run_is_not_a_comparison(dashboard):
    two_molecules(dashboard)

    response = dashboard.client.get('/api/runs/transferability?ids=aa11bb22cc33')

    assert response.status_code == 400
    assert '2' in response.get_data(as_text=True)


def test_the_same_run_twice_is_refused(dashboard):
    two_molecules(dashboard)

    response = dashboard.client.get('/api/runs/transferability?ids=aa11bb22cc33,aa11bb22cc33')

    assert response.status_code == 400


def test_two_runs_of_one_molecule_are_refused_rather_than_silently_merged(dashboard):
    """The reader keys its rows by molecule, so a second run of one molecule would overwrite the first."""
    two_molecules(dashboard)
    publish(dashboard, 'cc33dd44ee55', 'Sucrose', [('A', 'SN6'), ('C', 'SP1r')],
            [row([[1, 'A'], [1, 'C']], 0.4100)])

    response = dashboard.client.get('/api/runs/transferability?ids=aa11bb22cc33,cc33dd44ee55')

    assert response.status_code == 400
    assert 'Sucrose' in response.get_data(as_text=True)


def test_a_run_with_no_published_comparison_names_itself(dashboard):
    two_molecules(dashboard)
    dashboard.coordinator.database().insert(
        {'id': 'deadbeef0000', 'label': 'nothing published', 'molecule_id': 'Maltose',
         'run_type': 'aa_cg', 'status': 'completed', 'stage': 'complete',
         'created': dashboard.coordinator.now()})

    response = dashboard.client.get('/api/runs/transferability?ids=aa11bb22cc33,deadbeef0000')

    assert response.status_code == 404
    assert 'deadbeef0000' in response.get_data(as_text=True)
