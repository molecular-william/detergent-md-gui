"""The series as the coordinator creates it: one run, and the run type's own admission.

Two things are pinned here, and both are about *this* shape rather than the route's payload:

* **one run.** `POST /api/osmotic/series` calls `create_job` once. That is the fix for the defect the previous
  shape could not express -- with `max_concurrent_runs: 1` the per-condition batch was refused `CapacityFull` from
  the second condition on, so a five-condition series queued one run.
* **the admission is the run type's own.** `create_job` used to answer every non-pdc run type with the *CG*
  adapter's readiness, which refuses every `standard` profile outright ("A reviewed CG model is required"), and
  the `standard` profile is what this panel asks for. The CG gate is about a replicated CG topology, which an
  osmotic series does not build: what it needs of its mapping is the bead radii the box is sized from. So the
  answers are the run type's -- the solute is a sugar, the files are here, the concentrations can be placed.

Nothing here runs GROMACS: `run_job` is replaced with a no-op so the job is created and left `queued`, which is
what the assertions are about. What the run then does with those concentrations is the runner's own suite.
"""
from dashboard.execution.coordination.errors import RunConflict
from dashboard.models.mappings import context as mapping_context

SOLUTE_FILES = ('solute.gro', 'solute.itp', 'water.gro', 'martini_v3.0.0_solvents_v1.itp')
SERIES = '/api/osmotic/series'


def _solute_files(dashboard, molecule='maltose'):
    """The directory `prepare` copies out of, in the fixture's own workspace rather than the developer's."""
    root = dashboard.coordinator.RUNS.parent / 'osmotic' / molecule
    root.mkdir(parents=True, exist_ok=True)
    for name in SOLUTE_FILES:
        (root / name).write_text('fixture\n')
    return root


def _save_mapping(dashboard, molecule_id='Maltose'):
    """Save a candidate through the route the assignment editor posts to, so `create_job` can resolve it."""
    context = mapping_context.build_context(dashboard.coordinator.ROOT / 'molecules', molecule_id)
    with dashboard.client as c:
        preview = c.post('/api/mappings/automatic/preview',
                         json={'molecule_id': molecule_id, 'molecule_snapshot': context['snapshot']}).get_json()
        assert preview['available'] is True, preview.get('reasons')
        candidate = dict(preview['candidate'], molecule_id=molecule_id, molecule_snapshot=context['snapshot'])
        saved = c.post('/api/mappings/drafts', json=candidate)
    assert saved.status_code == 201, saved.get_data(as_text=True)
    return saved.get_json()


def _no_worker(monkeypatch):
    """Keep the run from being executed: this suite is about the record the coordinator creates."""
    from dashboard.execution.coordination.coordinator import Coordinator

    monkeypatch.setattr(Coordinator, 'run_job', lambda self, jid, worker=None: None)


def test_the_route_creates_one_run_for_the_whole_series(dashboard, monkeypatch):
    """Five conditions, one job, and its own settings carry them: that is what makes a series one worker slot."""
    _no_worker(monkeypatch)
    _solute_files(dashboard)
    mapping = _save_mapping(dashboard)

    with dashboard.client as c:
        response = c.post(SERIES, json={'molecule_id': 'Maltose', 'mapping_candidate': mapping['file'],
                                        'molalities': [0.5, 1.0, 1.5, 2.0, 2.5],
                                        'osmotic_production_ps': 500000, 'temperature_k': 308.15,
                                        'solute_root': str(_solute_files(dashboard))})

    assert response.status_code == 201, response.get_data(as_text=True)
    body = response.json
    assert body['count'] == 5 and body['molalities'] == [0.5, 1.0, 1.5, 2.0, 2.5]

    jobs = [job for job in dashboard.coordinator.database().all() if job.get('run_type') == 'osmotic']
    assert len(jobs) == 1, 'the series is one run, so five conditions cost one worker slot'
    run = jobs[0]
    assert run['id'] == body['run_id']
    assert run['settings']['molalities'] == [0.5, 1.0, 1.5, 2.0, 2.5]
    assert run['settings']['series_id'] == body['series_id']
    assert run['settings']['solute_root'] == str(_solute_files(dashboard))
    assert run['stage_plan'] == ['Osmotic series'], 'the run type\'s own plan, not a CG one'
    assert run['workflow_version'] == 'osmotic-v1'
    assert run['status'] == 'queued'
    assert '5 conditions' in run['label']


def test_the_standard_profile_is_admitted_because_the_run_type_answers_for_itself(dashboard, monkeypatch):
    """The CG adapter refuses `standard` for every molecule; this run type does not build a CG topology.

    Without the run type's own admission this route could not create a series at all, whatever the user asked
    for -- a defect no route-level test would have caught, because they stub `create_job`.
    """
    _no_worker(monkeypatch)
    _solute_files(dashboard)
    mapping = _save_mapping(dashboard)

    with dashboard.client as c:
        response = c.post(SERIES, json={'molecule_id': 'Maltose', 'mapping_candidate': mapping['file'],
                                        'solute_root': str(_solute_files(dashboard))})

    assert response.status_code == 201, response.get_data(as_text=True)
    assert 'A reviewed CG model is required' not in response.get_data(as_text=True)


def test_the_coordinators_own_admission_refuses_a_non_sugar_with_the_reason(dashboard):
    """A payload that reaches `create_job` without the route is refused by the run type, not by GROMACS."""
    try:
        dashboard.coordinator.create_job('DDM', 'fast_forward', 'DDM osmotic series',
                                         settings={'solute_root': str(_solute_files(dashboard, 'ddm')),
                                                   'molalities': [1.0]},
                                         molecule_id='DDM', run_type='osmotic')
    except RunConflict as exc:
        reason = str(exc)
    else:                                     # pragma: no cover - the failure this asserts is the point
        raise AssertionError('a non-sugar is not a valid osmotic solute and this one was admitted')

    assert 'not a carbohydrate' in reason, reason


def test_the_coordinators_own_admission_names_a_missing_solute_file(dashboard, monkeypatch):
    """The refusal the run type gives when its files are not there, rather than a CG answer about something else."""
    _no_worker(monkeypatch)
    root = _solute_files(dashboard)
    (root / 'water.gro').unlink()

    try:
        dashboard.coordinator.create_job('Maltose', 'fast_forward', 'Maltose osmotic series',
                                         settings={'solute_root': str(root), 'molalities': [1.0]},
                                         molecule_id='Maltose', run_type='osmotic')
    except RunConflict as exc:
        reason = str(exc)
    else:                                     # pragma: no cover
        raise AssertionError('a solute root missing water.gro was admitted')

    assert 'water.gro' in reason and 'solute_root is missing' in reason, reason
