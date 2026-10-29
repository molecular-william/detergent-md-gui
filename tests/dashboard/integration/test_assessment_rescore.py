"""A finished run's stage 5 scored again, as a recorded second attempt, with no new MD.

The reason this exists: run `ce1318485197` printed an all-zero score matrix and drew no distance distributions, because
the parameterization revision it consumed recorded 13 bonded histograms and none of the 55 pairwise references
`ff_assess` scores. The panel's Recompute button did nothing about it, correctly -- Recompute re-queues *analyses*,
which are derived from the run's outputs, while that matrix is stage 5's own output and was written once when the run
ran. So a second attempt is staged beside the first, and the first is left exactly as it was.

Three things are pinned here, and the third is the one that keeps history honest:

* the attempt stages the revision's own references, writes `attempt.json`, and runs the repository script with the
  run's stage 3 for its ITP and the attempt's references for `-d`;
* exactly one `assessment_attempts` entry is appended, and the manifest's `stages` list is byte-for-byte what it was;
* the first assessment's directory is untouched, and a non-zero exit is recorded as a failed attempt rather than
  raised -- the run finished before anybody asked for this and stays `completed`.

The tool is a stand-in on the subprocess: a real `ff_assess` would need a fitted pair baseline and a trajectory, and
what is being tested is the staging, the environment and the record, not Fast-Forward.
"""
import json
import subprocess
import threading
import time
from pathlib import Path

from dashboard import files
from dashboard.execution import assessment_rescore
from dashboard.models.bonded import parameterization
from tests.dashboard import support

JID = 'a1b2c3d4e5f6'
BEADS = ('B01', 'B02', 'B03')
PAIRS = ('1_B01_1_B02_distances_distr.dat', '1_B01_1_B03_distances_distr.dat', '1_B02_1_B03_distances_distr.dat')
BONDED = ('B01_B02_bonds_distr.dat', 'B01_B02_B03_angles_distr.dat')
STAGES = ['AA reference', 'trajectory mapping', 'CG parameterization', 'CG simulation',
          assessment_rescore.STAGE, 'SASA analysis']
REVISION = {'engine': 'fast-forward',
            'topology': ('[ moleculetype ]\nMOL 1\n\n[ atoms ]\n'
                         '1 C1 1 MOL B01 1 0 72\n2 C1 1 MOL B02 2 0 72\n3 C1 1 MOL B03 3 0 72\n'),
            'options': {'constraints_threshold': 10000.0, 'temperature_k': 300.0,
                        'torsion_model': 'legacy', 'torsion_scale': 1.0},
            'ensemble': {'frames': 3},
            'aa_reference': {'run_id': 'a54ac8f64710', 'reference_sha256': 'ab' * 32,
                             'molecule_identity': 'cd' * 32, 'temperature_k': 300.0,
                             'production_ns': 10.0}}


def mapping(**overrides):
    candidate = {'name': 'DDM fixture', 'beads': [{'name': name} for name in BEADS], 'rings': [],
                 'connections': []}
    candidate.update(overrides)
    return candidate


def fitted(candidate, files=tuple(PAIRS) + tuple(BONDED)):
    """A revision saved the way a fit saves one: its AA reference histograms copied and hashed beside it."""
    work = parameterization.work_root() / f'{parameterization.content_identity(candidate)}-probe'
    stage = work / '3_initial_CG'
    stage.mkdir(parents=True, exist_ok=True)
    for name in files:
        (stage / name).write_text('0.005 0.0\n0.015 1.0\n')
    return parameterization.save(candidate, REVISION, work=work)


def seed(dashboard, *, status='completed', mapping_candidate=None):
    """A finished AA-to-CG run: its fixture trajectory, its first assessment, and a manifest that records both.

    `mapping_candidate` is the *already fitted* mapping when a test wants a particular revision (one with, or one
    without, the pairwise family); by default the run gets a scorable one.
    """
    coordinator = dashboard.coordinator
    candidate = mapping_candidate if mapping_candidate is not None else mapping()
    if parameterization.current(candidate) is None:
        fitted(candidate)
    job = {'id': JID, 'label': 'Rescore', 'detergent': 'DDM', 'method': 'fast_forward',
           'profile': 'draft-smoke', 'status': status, 'stage': 'complete', 'run_type': 'aa_cg',
           'created': coordinator.now(), 'analyses': []}
    coordinator.database().replace([job])
    run = coordinator.RUNS / JID
    support.cg_fixture_run(run, [[0., 0., 0.], [.4, 0., 0.], [0., .4, 0.]], names=BEADS, frames=3, residue='DDM')
    assessment = run / 'stages/5_assessment'
    assessment.mkdir(parents=True, exist_ok=True)
    # What the first attempt wrote: an all-zero matrix and the reports, named as stage 5 names them.
    (assessment / 'score_matrix_LIG1.png').write_bytes(b'\x89PNG first')
    (assessment / 'report_distances.out').write_text('Overall distance score : 0.0\n')
    files.atomic_json(run / 'manifest.json', {
        'id': JID, 'status': status, 'run_type': 'aa_cg',
        'cg_names': {'residue_name': 'DDM', 'initial_itp': 'DDM_initial.itp', 'final_itp': 'DDM.itp'},
        'mapping_candidate': candidate,
        'stage_plan': [[name, f'{name}/script.sh'] for name in STAGES],
        'stages': [{'name': name, 'status': 'completed', 'command': [name], 'outputs': []} for name in STAGES],
    })
    return coordinator, run


def manifest(run):
    return json.loads((run / 'manifest.json').read_text())


def snapshot(directory):
    """Every file under `directory` and its digest: the first assessment's own state, not its mtime."""
    return {path.name: files.sha256(path) for path in sorted(directory.iterdir()) if path.is_file()}


def stand_in(returncode=0, calls=None):
    """A subprocess that writes what stage 5 writes and says nothing: what is under test is staging and recording."""
    def run(command, cwd=None, env=None, stdout=None, stderr=None, **_kwargs):
        if calls is not None:
            calls.append({'command': command, 'cwd': cwd, 'env': dict(env or {})})
        directory = Path(cwd or '.')
        (directory / 'score_matrix_LIG1.png').write_bytes(b'\x89PNG second')
        (directory / 'distance_distributions_LIG1.png').write_bytes(b'\x89PNG second')
        (directory / 'report_distances.out').write_text('Overall distance score : 0.42\n')
        return subprocess.CompletedProcess(command, returncode)
    return run


def test_a_rescore_stages_the_revisions_references_and_appends_one_attempt(dashboard, monkeypatch):
    coordinator, run = seed(dashboard)
    stages_before = manifest(run)['stages']
    calls = []
    monkeypatch.setattr(assessment_rescore.subprocess, 'run', stand_in(calls=calls))

    attempt = assessment_rescore.prepare(coordinator, JID)
    assessment_rescore.run(coordinator, JID, attempt)

    directory = run / 'stages/5_assessment@1'
    staged = sorted(path.name for path in (directory / 'references').glob('*.dat'))
    assert staged == sorted(PAIRS + BONDED), 'the revision\'s own histograms, not the first attempt\'s'
    for name in ('assess.sh', 'validate_run.py', 'distance_diagnostics.py'):
        assert not (directory / name).exists(), f'{name} belongs to the repository, not to the attempt'
    written = json.loads((directory / 'attempt.json').read_text())
    assert written['attempt'] == 1 and written['revision']['revision'] == 1
    assert written['references']['files'] == 5 and written['references']['pairs'] == {'files': 3, 'expected': 3}
    assert [entry['name'] for entry in written['references']['inventory']] == sorted(PAIRS + BONDED)
    assert written['trajectory']['sha256'] == files.sha256(run / 'stages/4_CG_sim/prod/lig_CG.xtc')
    assert written['mapping']['mapping_hash'] == parameterization.identities(mapping())['mapping_hash']
    assert set(written['scripts']) == {'dashboard/execution/scripts/assess.sh',
                                       'dashboard/execution/scripts/validate_run.py',
                                       'dashboard/execution/scripts/distance_diagnostics.py'}

    # The repository script ran in the attempt's directory, with the run's stage 3 for the ITP and the attempt's
    # references for `-d`; its helpers are modules found through `PYTHONPATH`.
    assert calls[0]['cwd'] == str(directory)
    assert calls[0]['command'][-1] == str(assessment_rescore.environment.ROOT / 'dashboard/execution/scripts/assess.sh')
    assert calls[0]['env']['INITIAL_DIR'] == str(run / 'stages/3_initial_CG')
    assert calls[0]['env']['REFERENCES'] == str((directory / 'references').resolve())
    assert calls[0]['env']['INITIAL_ITP'] == 'DDM_initial.itp'
    assert calls[0]['env']['MOLECULE_TYPE'] == 'DDM'
    assert calls[0]['env']['PYTHON'] and calls[0]['env']['PYTHONPATH']
    assert (directory / 'console.log').read_text().startswith('$ bash -e -o pipefail')

    recorded = manifest(run)
    assert len(recorded['assessment_attempts']) == 1
    entry = recorded['assessment_attempts'][0]
    assert entry['attempt'] == 1 and entry['directory'] == 'stages/5_assessment@1'
    assert entry['exit_code'] == 0 and entry['status'] == 'completed'
    assert entry['references'] == 5 and entry['revision'] == 1
    assert entry['mapping_hash'] == written['mapping']['mapping_hash']
    assert entry['log'] == 'stages/5_assessment@1/console.log'
    assert entry['started_at'] and entry['ended_at']
    assert recorded['stages'] == stages_before, 'a second attempt is not a stage'
    assert recorded['status'] == 'completed'
    assert not assessment_rescore.in_flight(JID)


def test_the_first_assessment_is_untouched_by_a_rescore(dashboard, monkeypatch):
    """The run's own record of what it scored stays what it was: the attempt is written beside it, never over it."""
    coordinator, run = seed(dashboard)
    first = run / 'stages/5_assessment'
    before = snapshot(first)
    monkeypatch.setattr(assessment_rescore.subprocess, 'run', stand_in())

    attempt = assessment_rescore.prepare(coordinator, JID)
    assessment_rescore.run(coordinator, JID, attempt)

    assert snapshot(first) == before
    assert (first / 'report_distances.out').read_text() == 'Overall distance score : 0.0\n'
    assert not (first / 'attempt.json').exists()


def test_a_nonzero_exit_is_recorded_as_a_failed_attempt_and_is_not_raised(dashboard, monkeypatch):
    coordinator, run = seed(dashboard)
    monkeypatch.setattr(assessment_rescore.subprocess, 'run', stand_in(returncode=7))

    attempt = assessment_rescore.prepare(coordinator, JID)
    assessment_rescore.run(coordinator, JID, attempt)

    recorded = manifest(run)
    assert recorded['assessment_attempts'][0]['exit_code'] == 7
    assert recorded['assessment_attempts'][0]['status'] == 'failed'
    assert recorded['status'] == 'completed', 'the run finished before the re-score was asked for'
    assert not assessment_rescore.in_flight(JID)


def test_an_attempt_that_could_not_start_is_recorded_with_its_error(dashboard, monkeypatch):
    coordinator, run = seed(dashboard)

    def missing(*_args, **_kwargs):
        raise OSError('bash: No such file or directory')

    monkeypatch.setattr(assessment_rescore.subprocess, 'run', missing)

    attempt = assessment_rescore.prepare(coordinator, JID)
    assessment_rescore.run(coordinator, JID, attempt)

    entry = manifest(run)['assessment_attempts'][0]
    assert entry['exit_code'] is None and entry['status'] == 'failed'
    assert 'No such file or directory' in entry['error']
    assert not assessment_rescore.in_flight(JID)


def test_a_second_rescore_is_attempt_two_and_each_entry_stands_on_its_own(dashboard, monkeypatch):
    coordinator, run = seed(dashboard)
    monkeypatch.setattr(assessment_rescore.subprocess, 'run', stand_in())

    for _ in range(2):
        assessment_rescore.run(coordinator, JID, assessment_rescore.prepare(coordinator, JID))

    recorded = manifest(run)
    assert [entry['attempt'] for entry in recorded['assessment_attempts']] == [1, 2]
    assert [entry['directory'] for entry in recorded['assessment_attempts']] == ['stages/5_assessment@1',
                                                                                 'stages/5_assessment@2']


def test_the_route_answers_202_with_what_it_will_score_and_refuses_a_second_press(dashboard, monkeypatch):
    """The panel's control: prepare inline so the answer can say what the attempt will score with, run in a thread."""
    coordinator, _ = seed(dashboard)
    started, finished = threading.Event(), threading.Event()

    def stalled(_coordinator, jid, _attempt):
        started.set()
        try:
            finished.wait(5)
        finally:
            assessment_rescore.release(jid)

    monkeypatch.setattr(assessment_rescore, 'run', stalled)

    response = dashboard.client.post(f'/api/jobs/{JID}/assessment/rescore', json={})

    assert response.status_code == 202
    assert response.get_json() == {'attempt': 1, 'directory': 'stages/5_assessment@1',
                                   'references': 5, 'pairs': 3, 'revision': 1}
    assert started.wait(5), 'the attempt never reached its worker'
    second = dashboard.client.post(f'/api/jobs/{JID}/assessment/rescore', json={})
    assert second.status_code == 409
    assert 'already being re-scored' in second.get_json()['error']
    finished.set()


def test_the_route_starts_the_attempt_on_a_real_thread_and_records_it(dashboard, monkeypatch):
    """Nothing stands in for the worker here but the tool: the route's own thread pushes an application context,
    stages nothing twice, appends its entry, and gives the run's slot back."""
    coordinator, run = seed(dashboard)
    monkeypatch.setattr(assessment_rescore.subprocess, 'run', stand_in())

    response = dashboard.client.post(f'/api/jobs/{JID}/assessment/rescore', json={})

    assert response.status_code == 202
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and assessment_rescore.in_flight(JID):
        time.sleep(.02)
    assert not assessment_rescore.in_flight(JID), 'the attempt never finished'
    entry = manifest(run)['assessment_attempts'][0]
    assert entry['exit_code'] == 0 and entry['directory'] == 'stages/5_assessment@1'
    assert (run / 'stages/5_assessment@1/score_matrix_LIG1.png').is_file()


def test_the_route_refuses_a_revision_with_no_pairwise_family_and_says_how_many_it_has(dashboard):
    """The run this module exists for, through the route: the refusal is the reason, not a bare 409."""
    candidate = mapping()
    fitted(candidate, files=BONDED)
    coordinator, _ = seed(dashboard, mapping_candidate=candidate)

    response = dashboard.client.post(f'/api/jobs/{JID}/assessment/rescore', json={})

    assert response.status_code == 409
    assert '2 AA reference histogram(s)' in response.get_json()['error']
    assert not (coordinator.RUNS / JID / 'stages/5_assessment@1').exists(), 'a refused attempt staged nothing'


def test_the_newest_attempts_figures_are_the_ones_the_panel_is_offered(dashboard, monkeypatch):
    """`/figures` drops the first attempt's pictures once a re-score has written its own, and counts the replaced set."""
    coordinator, run = seed(dashboard)
    monkeypatch.setattr(assessment_rescore.subprocess, 'run', stand_in())
    assessment_rescore.run(coordinator, JID, assessment_rescore.prepare(coordinator, JID))

    response = dashboard.client.get(f'/api/jobs/{JID}/figures')

    assert response.status_code == 200
    paths = [entry['path'] for entry in response.get_json()['artifacts']]
    assert 'stages/5_assessment@1/score_matrix_LIG1.png' in paths
    assert 'stages/5_assessment/score_matrix_LIG1.png' not in paths
    assert response.get_json()['superseded'] == 1, 'the first attempt is counted, not silently dropped'


def test_the_diagnostics_route_reads_the_newest_attempt_that_published_one(dashboard, monkeypatch):
    coordinator, run = seed(dashboard)
    (run / 'stages/5_assessment/distance_diagnostics_stratified.json').write_text(
        json.dumps({'pairs': [{'beads': ['B01', 'B02'], 'kind': 'physical'}]}))

    def with_diagnostics(command, cwd=None, env=None, stdout=None, stderr=None, **_kwargs):
        Path(cwd or '.', 'distance_diagnostics_stratified.json').write_text(
            json.dumps({'pairs': [{'beads': ['B01', 'B02'], 'kind': 'physical', 'wasserstein_nm': {'raw_AA': .1}}]}))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(assessment_rescore.subprocess, 'run', with_diagnostics)
    assessment_rescore.run(coordinator, JID, assessment_rescore.prepare(coordinator, JID))

    body = dashboard.client.get(f'/api/jobs/{JID}/distance-diagnostics').get_json()

    assert body['attempt'] == 1
    assert body['source'] == 'stages/5_assessment@1/distance_diagnostics_stratified.json'
    assert body['data']['pairs'][0]['wasserstein_nm'] == {'raw_AA': .1}
