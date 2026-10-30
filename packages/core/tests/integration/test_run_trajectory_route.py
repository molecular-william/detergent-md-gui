"""The run trajectory endpoint: segments a panel can play, rather than one trajectory a pdc run does not have.

The HTTP half of `analysis/runs/segments.py`. What matters here is the contract the panel reads: an ordered list, each
entry naming its own structure and trajectory, the merge group it belongs to, and the boundary where the system is
rebuilt -- plus artefacts served by the artifact route, so the client never builds a URL from a filesystem path.

The paths are asserted by *fetching* the URLs the answer carries, not by matching their shape. This test used to
write its fixture at the run root and compare spellings, so it stayed green while every segment URL 404'd on a run
that keeps its stages under `stages/` (all of them since the run-lifecycle refactor). A current layout is the default
here; the legacy root layout keeps one case because migrated runs still read through it.
"""
from __future__ import annotations

JOB_ID = '00000000beef'


def gro(count):
    """A readable `.gro` with `count` atoms: the structure route parses it, so a placeholder line is not enough."""
    row = f'{1:5d}{"DDM":<5s}{"B01":>5s}{1:5d}{0.1:8.3f}{0.2:8.3f}{0.3:8.3f}'
    return ('coarse-grained system\n' + f'{count:5d}\n' + (row + '\n') * count
            + '   8.00000   8.00000   8.00000\n')


def write(root, relative, text='', size=0):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text else 'x' * size)
    return path


def pdc_run(dashboard, *, job_id=JOB_ID, run_type='pdc', stages='stages/'):
    """A finished pdc run in a current (`stages/`) or legacy (root) layout.

    The atom counts are what make the segments: 8 in the dry build, 40 through the removal boundary, 32 after it,
    and the final assessment re-declares the extension's trajectory.
    """
    root = dashboard.coordinator.RUNS / job_id
    write(root, f'{stages}1_system/system.gro', gro(8))
    write(root, f'{stages}3_nvt/system.gro', gro(40))
    write(root, f'{stages}3_nvt/system.xtc', size=120)
    write(root, f'{stages}4_npt/system.gro', gro(40))
    write(root, f'{stages}4_npt/system.xtc', size=140)
    write(root, f'{stages}2_assessment/prod/run.gro', gro(40))
    write(root, f'{stages}2_assessment/prod/whole.xtc', size=160)
    write(root, f'{stages}4_extension/prod/run.gro', gro(32))
    write(root, f'{stages}4_extension/prod/whole.xtc', size=180)
    write(root, f'{stages}4_extension/prod/run.xtc', size=90)
    write(root, f'{stages}5_assessment/prod/run.gro', gro(32))
    write(root, f'{stages}5_assessment/prod/run.xtc', size=90)
    # The back-mapped complex is a `.pdb`: the structure route refuses one, so its URL must be the artifact route's.
    write(root, f'{stages}10_backmap/FINAL/FINAL/final_cg2at_neutral.pdb',
          'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n')
    dashboard.coordinator.database().insert({'id': job_id, 'run_type': run_type, 'status': 'completed',
                                             'stage': 'complete', 'molecule_id': 'DDM',
                                             'created': '2026-10-14T00:00:00+00:00'})
    return root


def served(client, url):
    return client.get(url).status_code


def test_a_pdc_run_answers_with_its_segments_in_order(dashboard):
    pdc_run(dashboard)

    response = dashboard.client.get(f'/api/jobs/{JOB_ID}/trajectory')

    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body['run_type'] == 'pdc' and body['why'] is None
    names = [entry['name'] for entry in body['segments']]
    assert names[:3] == ['System preparation', 'NVT equilibration', 'NPT equilibration'], names
    assert body['segments'][0]['trajectory'] is None, 'the dry build has a structure and no frames'
    assert body['segments'][0]['structure'] == 'stages/1_system/system.gro', (
        'the spelling is the run root, which is what the routes resolve against')


def test_every_url_the_answer_carries_is_one_the_routes_serve(dashboard):
    """The one assertion this endpoint needed: fetch each URL, rather than compare the string a client would build."""
    pdc_run(dashboard)

    body = dashboard.client.get(f'/api/jobs/{JOB_ID}/trajectory').get_json()
    nvt = next(entry for entry in body['segments'] if entry['name'] == 'NVT equilibration')
    assert nvt['structure_url'] == f'/api/jobs/{JOB_ID}/structure?path=stages/3_nvt/system.gro'
    assert nvt['trajectory_url'] == f'/api/jobs/{JOB_ID}/artifacts/stages/3_nvt/system.xtc'
    assert nvt['atoms'] == 40 and nvt['group'] is not None

    backmap = next(entry for entry in body['segments'] if entry['name'] == 'Back-mapping (CG2AT2)')
    assert backmap['structure_url'] == (f'/api/jobs/{JOB_ID}/artifacts/'
                                        'stages/10_backmap/FINAL/FINAL/final_cg2at_neutral.pdb?inline=1'), (
        'a .pdb is served by the artifact route, because the structure route refuses one')

    fetched = 0
    for entry in body['segments']:
        for key in ('structure_url', 'trajectory_url'):
            if entry.get(key):
                assert served(dashboard.client, entry[key]) == 200, f'{entry["name"]}: {entry[key]}'
                fetched += 1
    assert fetched >= 8, 'the answer carries the structure and trajectory of every leg it found'


def test_a_legacy_run_keeps_its_root_spellings_and_serves_them(dashboard):
    """A migrated run's files sit at the root; the answer must not invent a `stages/` prefix for them."""
    pdc_run(dashboard, stages='')

    body = dashboard.client.get(f'/api/jobs/{JOB_ID}/trajectory').get_json()
    nvt = next(entry for entry in body['segments'] if entry['name'] == 'NVT equilibration')
    assert nvt['structure'] == '3_nvt/system.gro'
    assert nvt['trajectory'] == '3_nvt/system.xtc'
    assert served(dashboard.client, nvt['structure_url']) == 200
    assert served(dashboard.client, nvt['trajectory_url']) == 200


def test_the_boundary_and_the_duplicate_are_both_in_the_answer(dashboard):
    """One thing the panel must not infer: where the system is rebuilt, and which leg repeats another's frames."""
    pdc_run(dashboard)

    body = dashboard.client.get(f'/api/jobs/{JOB_ID}/trajectory').get_json()

    assert body['boundaries'][0]['at'] == 'CG extension MD'
    assert body['boundaries'][0]['atoms_from'] == 40 and body['boundaries'][0]['atoms_to'] == 32
    final = next(entry for entry in body['segments'] if entry['name'] == 'Final assessment')
    assert final['duplicate_of'] == 'CG extension MD'


def test_a_run_with_nothing_to_play_is_a_200_with_a_reason(dashboard):
    root = dashboard.coordinator.RUNS / JOB_ID
    write(root, 'stages/07_reference/lig.gro', gro(4))
    dashboard.coordinator.database().insert({'id': JOB_ID, 'run_type': 'aa_only', 'status': 'completed',
                                             'stage': 'complete', 'created': '2026-10-14T00:00:00+00:00'})

    response = dashboard.client.get(f'/api/jobs/{JOB_ID}/trajectory')

    assert response.status_code == 200
    body = response.get_json()
    assert body['segments'] == [] and 'no trajectory' in body['why']


def test_an_unknown_run_is_the_routes_own_404(dashboard):
    response = dashboard.client.get('/api/jobs/nosuchrun/trajectory')

    assert response.status_code == 404
