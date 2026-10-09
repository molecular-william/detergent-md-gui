"""The series route: that it queues one condition per molality sharing a series id, and that it refuses before it
queues anything at all.

The refusal tests carry the weight. A route that queues what it can and reports the rest leaves a series whose
conditions do not correspond to each other, and the runs it did create are then evidence of nothing.

The two success tests stub `create_job`. The standard profile requires a *reviewed CG model*, which a fixture would
have to build a great deal of machinery to have -- and the subject of those two tests is the route: six conditions,
their labels, their shared series id, and the settings each is asked to store. What the coordinator does with them is
tested by the refusals here and by its own suite.

**No test names a run id or a candidate id from this machine.** The first version of this file named the maltose AA
reference and was refused by admission -- which turned out to be right, and to say something about the run type: an
osmotic condition takes its solute from a *mapping*, not from a shared AA reference. Named ids would have made these
tests pass only on a machine where those records happened to exist.
"""
from datetime import datetime, timezone
from unittest.mock import patch

from dashboard.web.routes import osmotic as route

SERIES = '/api/osmotic/series'


def _stores(dashboard, tmp_path):
    """Point the coordinator's database and run directory at a fixture, as the other API tests do."""
    return (patch.object(dashboard.coordinator, 'DATA', tmp_path / 'jobs.sqlite3'),
            patch.object(dashboard.coordinator, 'RUNS', tmp_path / 'runs'))


def _stub_create_job(dashboard, calls):
    """Record what the route asked for instead of asking the real coordinator to create it."""
    def fake(molecule, method, label, **kwargs):
        calls.append(dict(kwargs, molecule=molecule, method=method, label=label))
        return {'id': f'stub{len(calls):04d}', 'label': label}

    return patch.object(dashboard.coordinator, 'create_job', side_effect=fake)


def _completed_reference(dashboard):
    """A completed AA reference, in the fixture's own database.

    The osmotic run type does not consume one, but a payload that names one is refused by the coordinator's path, so
    having a real completed row here is what makes that refusal about the rule rather than about a missing record.
    """
    stamp = datetime.now(timezone.utc).isoformat()
    job = {'id': 'fixref000001', 'label': 'Fixture AA reference', 'detergent': 'Maltose',
           'molecule_id': 'Maltose', 'method': 'aa', 'run_type': 'aa_only', 'status': 'completed',
           'stage': 'complete', 'created': stamp, 'ended_at': stamp, 'profile': 'standard'}
    dashboard.coordinator.database().insert(job)
    return job['id']


def _payload():
    """A legitimate call: a molecule, the method its topology would be fitted with, and the dataset's temperature."""
    return {'molecule_id': 'Maltose', 'method': 'fast_forward', 'temperature_k': 308.15}


def test_the_default_series_is_the_papers_six_molalities_sharing_one_id(dashboard, tmp_path):
    calls = []
    database, runs = _stores(dashboard, tmp_path)
    with database, runs, _stub_create_job(dashboard, calls), dashboard.client as c:
        r = c.post(SERIES, json=dict(_payload(), solute_root=str(tmp_path)))

    assert r.status_code == 201, r.get_data(as_text=True)
    body = r.json
    assert body['molalities'] == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    assert body['count'] == 6 == len(calls)
    assert len({job['id'] for job in body['jobs']}) == 6

    for call, molality in zip(calls, body['molalities']):
        assert call['run_type'] == 'osmotic'
        assert call['molecule_id'] == 'Maltose'
        assert call['settings']['series_id'] == body['series_id']
        assert call['settings']['osmotic_molality'] == molality
        assert call['settings']['solute_root'] == str(tmp_path)
        assert f'{molality:g} molal' in call['label']


def test_a_shared_reference_is_refused_because_the_solute_comes_from_a_mapping(dashboard, tmp_path):
    """The refusal that taught this file what the run type is. A condition does not consume the AA trajectory: its
    solute is a mapped molecule, and the mapping candidate records which run it was made from."""
    database, runs = _stores(dashboard, tmp_path)
    with database, runs, dashboard.client as c:
        reference = _completed_reference(dashboard)
        before = c.get('/api/jobs?limit=100').json['jobs']
        r = c.post(SERIES, json=dict(_payload(), solute_root=str(tmp_path), reference_run_id=reference))
        after = c.get('/api/jobs?limit=100').json['jobs']

    assert r.status_code == 400, r.get_data(as_text=True)
    assert 'takes its solute from a mapping' in r.get_data(as_text=True)
    assert len(after) == len(before), 'a refused series creates nothing'


def test_a_molecule_id_of_the_wrong_form_is_refused_and_not_one_job_is_created(dashboard, tmp_path):
    """`validate_id` checks the *form* of an id; whether the molecule exists is the coordinator's to decide, and both
    refusals land before anything is queued, which is the property under test."""
    database, runs = _stores(dashboard, tmp_path)
    with database, runs, dashboard.client as c:
        before = c.get('/api/jobs?limit=100').json['jobs']
        r = c.post(SERIES, json=dict(_payload(), solute_root=str(tmp_path),
                                     molecule_id='not a molecule at all !'))
        after = c.get('/api/jobs?limit=100').json['jobs']

    assert r.status_code >= 400, r.get_data(as_text=True)
    assert len(after) == len(before), 'a refused series creates nothing'


def test_a_molality_the_build_cannot_place_is_refused_and_the_series_is_not_half_created(dashboard, tmp_path):
    """The refusal names the offending value, and it happens before the first job exists -- which is the whole point of
    checking every condition up front rather than queueing as it goes."""
    database, runs = _stores(dashboard, tmp_path)
    with database, runs, dashboard.client as c:
        before = c.get('/api/jobs?limit=100').json['jobs']
        r = c.post(SERIES, json=dict(_payload(), solute_root=str(tmp_path), molalities=[0.5, 1.0, 9.0]))
        after = c.get('/api/jobs?limit=100').json['jobs']

    assert r.status_code == 400, r.get_data(as_text=True)
    assert 'between 0.0 and 2.5' in r.get_data(as_text=True)
    assert len(after) == len(before)


def test_the_solute_root_is_required_because_prepare_cannot_find_the_files_without_it(dashboard, tmp_path):
    database, runs = _stores(dashboard, tmp_path)
    with database, runs, dashboard.client as c:
        r = c.post(SERIES, json=_payload())

    assert r.status_code == 400
    assert 'solute_root' in r.get_data(as_text=True)


def test_a_caller_may_name_its_own_molalities(dashboard, tmp_path):
    calls = []
    database, runs = _stores(dashboard, tmp_path)
    with database, runs, _stub_create_job(dashboard, calls), dashboard.client as c:
        r = c.post(SERIES, json=dict(_payload(), solute_root=str(tmp_path), molalities='0.5, 1.0'))

    assert r.status_code == 201, r.get_data(as_text=True)
    assert r.json['molalities'] == [0.5, 1.0]
    assert r.json['count'] == 2 == len(calls)


def test_a_series_with_no_molality_at_all_is_refused(dashboard, tmp_path):
    database, runs = _stores(dashboard, tmp_path)
    with database, runs, dashboard.client as c:
        r = c.post(SERIES, json=dict(_payload(), solute_root=str(tmp_path), molalities=[]))

    assert r.status_code == 400
    assert 'at least one molality' in r.get_data(as_text=True)


def test_the_defaults_are_the_papers_own_six():
    assert route.PAPER_MOLALITIES == (0.0, 0.5, 1.0, 1.5, 2.0, 2.5)


# --- the panel's reader: GET /api/osmotic/conditions -----------------------------------------------------------
#
# The subject here is *which attempt represents a molality*, which is what the first draft of this route got wrong:
# it returned every directory holding a condition record, which on this workspace is 27 rows for six conditions,
# thirteen of them abandoned attempts at 0.5 molal sitting beside the one that worked.

def _condition_on_disk(runs, run_id, molality, *, measured=None, written_at=None):
    """One condition's files, laid out as an osmotic run lays them out."""
    import json
    import os

    stage = runs / run_id / '01_simulate'
    stage.mkdir(parents=True)
    record = stage / 'osmotic_condition.json'
    record.write_text(json.dumps({'molality_requested': molality, 'molality_achieved': molality,
                                  'solute_molecules': 70, 'dividing_area_nm2': 25.4173, 'temperature': 308.15}))
    if measured is not None:
        (stage / 'osmotic-pressure.json').write_text(json.dumps(measured))
    if written_at is not None:
        os.utime(record, (written_at, written_at))
    return stage


def _measurement(pressure, symmetry=0.9930):
    return {'pressure_bar': pressure, 'symmetry': symmetry, 'frames': 5001, 'sample_stride': 10,
            'molecules': 70, 'force_kj_nm': 23.4421}


def test_one_row_per_molality_and_the_measured_attempt_represents_it(dashboard, tmp_path):
    """Three attempts at one molality collapse to the one that has a report, however the others sort."""
    database, runs = _stores(dashboard, tmp_path)
    with database, runs:
        _condition_on_disk(tmp_path / 'runs', 'abandoned001', 0.5, written_at=1_700_000_000)
        _condition_on_disk(tmp_path / 'runs', 'abandoned002', 0.5, written_at=1_700_000_500)
        _condition_on_disk(tmp_path / 'runs', 'succeeded001', 0.5, measured=_measurement(14.944), written_at=1_700_000_100)
        _condition_on_disk(tmp_path / 'runs', 'newest00001', 0.5, written_at=1_700_000_900)
        with dashboard.client as c:
            body = c.get('/api/osmotic/conditions').get_json()
    assert body['attempts_on_disk'] == 4, 'all four are on disk and the count says so'
    assert body['total'] == 1, 'but one molality is one row'
    assert body['conditions'][0]['run_id'] == 'succeeded001'
    assert body['conditions'][0]['measured']['pressure_bar'] == 14.944


def test_an_unmeasured_molality_shows_its_newest_attempt(dashboard, tmp_path):
    """A condition that is running, or whose attempt died, shows as itself -- not as whichever attempt sorts last."""
    database, runs = _stores(dashboard, tmp_path)
    with database, runs:
        _condition_on_disk(tmp_path / 'runs', 'earlier00001', 2.5, written_at=1_700_000_000)
        _condition_on_disk(tmp_path / 'runs', 'running00001', 2.5, written_at=1_700_000_900)
        with dashboard.client as c:
            body = c.get('/api/osmotic/conditions').get_json()
    assert body['total'] == 1
    assert body['conditions'][0]['run_id'] == 'running00001'
    assert body['conditions'][0]['measured'] is None
    assert body['measured'] == 0


def test_the_papers_numbers_are_attached_beside_the_measurement(dashboard, tmp_path):
    """The target is a citation and an uncertainty, and a ratio exists only where something was measured."""
    database, runs = _stores(dashboard, tmp_path)
    with database, runs:
        _condition_on_disk(tmp_path / 'runs', 'measured0001', 1.0, measured=_measurement(29.877), written_at=1_700_000_000)
        _condition_on_disk(tmp_path / 'runs', 'unmeasured01', 2.0, written_at=1_700_000_000)
        with dashboard.client as c:
            body = c.get('/api/osmotic/conditions').get_json()
    measured, unmeasured = body['conditions']
    assert measured['paper'] == {'pressure_bar': 26.54, 'uncertainty_bar': 0.08}
    assert round(measured['ratio'], 4) == round(29.877 / 26.54, 4)
    assert unmeasured['paper'] == {'pressure_bar': 56.09, 'uncertainty_bar': 0.16}
    assert unmeasured['ratio'] is None, 'a ratio against an unmeasured condition would be a number with no subject'
    assert 'doi:10.1016/j.fluid.2016.02.030' in body['citation']
    assert body['measured'] == 1 and body['total'] == 2


def test_the_control_is_a_row_and_not_a_missing_one(dashboard, tmp_path):
    """0 molal has no report by construction -- no solute, no wall -- and the panel shows that rather than omitting it.

    A reader that skipped conditions without measurements would drop the control entirely, and a series whose first
    point is absent reads as one that starts at 0.5.
    """
    database, runs = _stores(dashboard, tmp_path)
    with database, runs:
        _condition_on_disk(tmp_path / 'runs', 'control00001', 0.0, written_at=1_700_000_000)
        _condition_on_disk(tmp_path / 'runs', 'measured0001', 0.5, measured=_measurement(14.944), written_at=1_700_000_000)
        with dashboard.client as c:
            body = c.get('/api/osmotic/conditions').get_json()
    assert body['total'] == 2
    control, first = body['conditions']
    assert control['molality_requested'] == 0.0 and control['measured'] is None
    assert 'paper' not in control, 'the paper reports the control as 0.00 and it is not one of the fitted points'
    assert first['molality_requested'] == 0.5
