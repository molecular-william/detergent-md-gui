"""The six routes the CG Bond Interactions panel calls, against the contract in the design record.

`docs/design/2026-10-16-parameterization-and-new-run.md` names each route, the body the panel sends and the model
call behind it; these tests hold the route to that table rather than to the panel's rendering. One test per route,
plus the refusals the contract states (a bad engine, a missing AA reference, an unknown hash or job id, a `PATCH`
without confirmation).

Where a real fit would run, the *job* is stood in for: `fitting.start` is the seam, and a test that stubs it asserts
that the route handed it the payload the contract names -- the resolved reference included. The tests that need a
stored record run the job for real at the command-runner seam instead (as `packages/core/tests/unit/test_bonded_fitting.py`
does), so the revision, the job list and the history are the store's own records and not fixtures written by hand.

Everything lands in the workspace the `dashboard` fixture built under `tmp_path`; the developer's `workspace/` is
never read or written.
"""
import copy
import hashlib
import json
from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pytest
from dashboard.models import mappings
from dashboard.models.bonded import fitting, parameterization
from dashboard.models.mappings.context import as_structure, build_context

from tests.harness.support import PROJECT_ROOT

MOLECULES = PROJECT_ROOT / 'molecules'
TOPOLOGY = ('[ moleculetype ]\nDDM 1\n\n[ atoms ]\n1 C1 1 DDM B01 1 0 72\n2 C1 1 DDM B02 2 0 72\n\n'
            '[ bonds ]\n1 2 1 0.31 5000\n')
REFERENCE = {'run_id': 'a' * 12, 'directory': '/nonexistent/reference', 'reference_sha256': 'ab' * 32,
             'record': {'reference_sha256': 'ab' * 32, 'frames': 20001,
                        'aa_reference': {'run_id': 'a' * 12, 'reference_sha256': 'ab' * 32,
                                         'molecule_identity': 'cd' * 32, 'temperature_k': 300.0,
                                         'production_ns': 10.0}}}


def ddm_mapping(name='DDM'):
    """The saved-candidate shape the panel posts: the molecule's snapshot, exported by one mapper."""
    context = build_context(MOLECULES, 'DDM')
    candidate = mappings.automatic_candidate(as_structure(context), name)
    candidate.update(schema_version=3, molecule_id='DDM',
                     molecule_snapshot=copy.deepcopy(context['snapshot']))
    return candidate


def variant(candidate, label='a'):
    """A different bead assignment: a renamed candidate keeps its content identity, an edited one does not."""
    changed = copy.deepcopy(candidate)
    changed['beads'][0]['label'] = label
    return changed


def reference_run(workspace, run_id='a' * 12, frames=900):
    """A completed AA-only run's reference, as `analysis.runs.references.resolve` verifies one.

    Two files are what that reader needs: the manifest that says this run is a completed AA-only run, and the
    `reference.json` its stage publishes. The hash map is the reader's own, so it is left for the reader to fill.
    """
    directory = Path(workspace) / 'runs' / run_id
    (directory / 'stages' / '07_reference').mkdir(parents=True)
    (directory / 'manifest.json').write_text(json.dumps({'run_type': 'aa_only', 'status': 'completed'}))
    published = directory / 'stages' / '07_reference' / 'reference.json'
    published.write_text(json.dumps({'reference_eligible': True, 'sha256': {},
                                     'molecule_identity': 'cd' * 32, 'frames': {'count': frames},
                                     'settings': {'temperature_k': 300.0, 'aa_production_ps': 10000.0}}))
    return run_id, hashlib.sha256(published.read_bytes()).hexdigest()


def write_frames(directory, beads, frames=5):
    """A real mapped trajectory, under the names the mapping gives its beads."""
    names = [bead['name'] for bead in beads]
    universe = mda.Universe.empty(len(names), trajectory=True)
    universe.add_TopologyAttr('name', names)
    universe.add_TopologyAttr('resname', ['LIG'])
    universe.add_TopologyAttr('resid', [1])
    positions = np.asarray([[index * 0.45, 0.0, 0.0] for index in range(len(names))], dtype=np.float32)
    universe.atoms.positions = positions
    universe.atoms.write(str(Path(directory) / 'mapped.gro'))
    # A little spread, so a fit has something to measure rather than a degenerate ensemble.
    rng = np.random.default_rng(7)
    trajectory = np.asarray([positions + rng.normal(0.0, 0.02, positions.shape).astype(np.float32)
                             for _ in range(frames)])
    universe.trajectory = mda.coordinates.memory.MemoryReader(trajectory, order='fac')
    with mda.Writer(str(Path(directory) / 'mapped.xtc'), n_atoms=len(names)) as writer:
        for _ in universe.trajectory:
            writer.write(universe.atoms)
    (Path(directory) / 'mapping_validation.json').write_text(json.dumps({'frames': frames}))


def engine(command, cwd, *, env=None, timeout=None, job_id=None, log=None):
    """The stand-in for the two tools: each writes the artefact the job's own guard looks for."""
    cwd = Path(cwd)
    joined = ' '.join(str(part) for part in command)
    if 'scripts.sugar_mapping' in joined:
        write_frames(cwd, json.loads((cwd / 'model.json').read_text())['beads'])
    elif 'fit_topology.sh' in joined:
        (cwd / env['FINAL_ITP']).write_text(TOPOLOGY)
        (cwd / f"{env['FINAL_ITP'].removesuffix('.itp')}_ff_inter.itp").write_text(TOPOLOGY)
        (cwd / 'bonded_fit.json').write_text(json.dumps({'temperature_k': 300.0}))
    return None


def fit(candidate, **kwargs):
    """Run one fit for real at the command-runner seam, in this test's own workspace."""
    return fitting.start(candidate, engine=kwargs.pop('engine', 'fast-forward'), reference=REFERENCE,
                         molecule_root=MOLECULES, background=False, runner=engine, **kwargs)


@pytest.fixture
def started(monkeypatch):
    """The job seam, recording what the route handed it. Returns the list of calls."""
    calls = []

    def start(mapping, **kwargs):
        calls.append({'mapping': mapping, **kwargs})
        return {'id': '0123456789abcdef', 'status': 'queued', 'engine': kwargs.get('engine')}

    monkeypatch.setattr(fitting, 'start', start)
    return calls


# --- GET /api/bonded-parameterizations/engines -------------------------------------------------------

def test_the_engines_route_publishes_the_engines_a_fit_accepts(dashboard):
    response = dashboard.client.get('/api/bonded-parameterizations/engines')

    assert response.status_code == 200
    engines = response.json['engines']
    assert [item['value'] for item in engines] == list(parameterization.ENGINES)
    assert [item['label'] for item in engines] == [parameterization.ENGINE_LABELS[name]
                                                   for name in parameterization.ENGINES]
    # `needs_reference` is what the panel's picker reads to know whether an AA reference is required, and every engine
    # left fits to an ensemble -- the reference-free one and its button were removed.
    assert [item['value'] for item in engines] == ['fast-forward', 'bartender']
    assert all(item['needs_reference'] for item in engines)


# --- POST /api/bonded-parameterizations --------------------------------------------------------------

def test_a_fit_is_queued_with_the_payload_the_panel_sends(dashboard, started):
    run_id, digest = reference_run(dashboard.paths.workspace)
    payload = {'mapping': ddm_mapping(), 'engine': 'fast-forward', 'aa_reference': run_id,
               'options': {'constraints_threshold': 12000, 'temperature_k': 310.0,
                           'torsion_model': 'circular-harmonic', 'torsion_scale': 1.2},
               'molecule_root': 'molecules', 'timeout': 900}

    response = dashboard.client.post('/api/bonded-parameterizations', json=payload)

    assert response.status_code == 201
    assert response.json['status'] == 'queued'
    assert len(started) == 1
    call = started[0]
    assert call['engine'] == 'fast-forward'
    # The four options travel as the panel sent them: normalising them is the job's rule, not the route's.
    assert call['options'] == payload['options']
    assert call['timeout'] == 900
    assert call['molecule_root'] == dashboard.coordinator.ROOT / 'molecules'
    # The twelve-hex run id was resolved through the model's own resolver -- the same verification every other
    # AA-reference consumer performs -- and handed over as the reference, not as a name to resolve later.
    assert call['reference']['run_id'] == run_id
    assert call['reference']['reference_sha256'] == digest
    assert call['reference']['record']['aa_reference']['run_id'] == run_id
    assert not call.get('aa_reference'), 'the route resolves the id it is given'


def test_the_engine_that_read_no_reference_is_no_longer_an_engine(dashboard, started):
    """Every engine left needs an ensemble, so a reference-free request is refused at the door, not queued.

    The engine existed until 2026-10-20; a caller still sending it -- a script, a stale tab -- gets the same answer an
    unknown engine gets, and no job is created for one nothing can run.
    """
    response = dashboard.client.post('/api/bonded-parameterizations',
                                     json={'mapping': ddm_mapping(), 'engine': 'reference-informed'})

    assert response.status_code == 400
    assert 'Unknown fitting engine' in response.json['error']
    assert started == [], 'a job is not queued for an engine the job would refuse'


def test_an_engine_this_build_does_not_have_is_refused(dashboard, started):
    response = dashboard.client.post('/api/bonded-parameterizations',
                                     json={'mapping': ddm_mapping(), 'engine': 'gromacs-magic',
                                           'aa_reference': 'a' * 12})

    assert response.status_code == 400
    assert 'Unknown fitting engine' in response.json['error']
    assert started == [], 'a job is not queued for an engine the job would refuse'


def test_an_engine_that_fits_to_an_ensemble_needs_its_reference(dashboard, started):
    response = dashboard.client.post('/api/bonded-parameterizations',
                                     json={'mapping': ddm_mapping(), 'engine': 'fast-forward'})

    assert response.status_code == 400
    assert 'link an AA reference' in response.json['error']
    assert started == []


def test_a_reference_that_is_not_a_run_in_this_workspace_is_not_found(dashboard, started):
    response = dashboard.client.post('/api/bonded-parameterizations',
                                     json={'mapping': ddm_mapping(), 'engine': 'fast-forward',
                                           'aa_reference': 'b' * 12})

    assert response.status_code == 404
    assert 'b' * 12 in response.json['error']
    assert started == [], 'an unresolvable reference is refused before a job exists'


def test_a_malformed_reference_id_is_a_bad_request(dashboard, started):
    response = dashboard.client.post('/api/bonded-parameterizations',
                                     json={'mapping': ddm_mapping(), 'engine': 'fast-forward',
                                           'aa_reference': 'not-a-run'})

    assert response.status_code == 400
    assert 'Invalid AA source run ID' in response.json['error']


def test_an_option_a_revision_cannot_record_is_refused_by_the_job_that_would_record_it(dashboard):
    """No stubbed job here: the refusal is `fitting.start`'s own, reached through the real route."""
    run_id, _ = reference_run(dashboard.paths.workspace)
    response = dashboard.client.post('/api/bonded-parameterizations',
                                     json={'mapping': ddm_mapping(), 'engine': 'fast-forward',
                                           'aa_reference': run_id, 'options': {'torsion_scale': 9.0}})

    assert response.status_code == 400
    assert 'Torsion stiffness scale' in response.json['error']
    assert fitting.jobs() == [], 'a refused payload leaves no job behind'


def test_a_body_without_a_mapping_is_a_bad_request(dashboard, started):
    response = dashboard.client.post('/api/bonded-parameterizations',
                                     json={'engine': 'fast-forward'})

    assert response.status_code == 400
    assert 'mapping snapshot' in response.json['error']


# --- GET /api/bonded-parameterizations ----------------------------------------------------------------

def test_a_record_answers_its_summary_its_whole_history_and_its_jobs(dashboard):
    candidate = ddm_mapping()
    job = fit(candidate)
    content_hash = parameterization.content_identity(candidate)

    response = dashboard.client.get('/api/bonded-parameterizations', query_string={'content_hash': content_hash})

    assert response.status_code == 200
    body = response.json
    assert set(body) == {'summary', 'revisions', 'jobs'}
    summary = body['summary']
    assert summary['parameterized'] is True
    assert summary['revision'] == 1
    assert summary['engine'] == 'fast-forward'
    assert summary['engine_label'] == parameterization.ENGINE_LABELS['fast-forward']
    assert summary['terms'] and summary['terms'] > 0
    assert summary['revisions'] == [1]
    # The whole history, not a summary of it: a revision carries the terms the compare view reads.
    assert [item['revision'] for item in body['revisions']] == [1]
    assert '[ moleculetype ]' in body['revisions'][0]['topology']
    assert [item['id'] for item in body['jobs']] == [job['id']]


def test_a_record_is_also_found_by_the_candidate_its_revisions_were_made_for(dashboard):
    candidate = ddm_mapping()
    fit(candidate)

    response = dashboard.client.get('/api/bonded-parameterizations',
                                   query_string={'mapping_hash': mappings.candidate_identity(candidate)})

    assert response.status_code == 200
    assert response.json['summary']['revision'] == 1
    assert response.json['summary']['mapping_hash'] == mappings.candidate_identity(candidate)


def test_every_record_is_listed_when_the_caller_names_no_mapping(dashboard):
    fit(ddm_mapping())

    response = dashboard.client.get('/api/bonded-parameterizations')

    assert response.status_code == 200
    assert set(response.json) == {'records'}
    assert len(response.json['records']) == 1


def test_a_model_with_no_parameterization_answers_the_honest_absence(dashboard):
    """D5's second state: absence is something the panel renders, not an error it cannot act on."""
    response = dashboard.client.get('/api/bonded-parameterizations',
                                   query_string={'content_hash': 'f' * 64})

    assert response.status_code == 200
    assert response.json['summary']['parameterized'] is False
    assert response.json['summary']['terms'] is None, 'no terms, and not a count of zero'
    assert response.json['revisions'] == []
    assert response.json['jobs'] == []


def test_a_candidate_with_no_record_is_answered_with_none_of_the_other_models_jobs(dashboard):
    """A hash-addressed question answers about *that* model, even when the answer is "nothing yet".

    The panel holds only hashes, and a job is queued before any record exists, so the empty document the
    store answers with has no record -- but the request named a candidate hash, and the jobs beside it in
    the workspace belong to other models. Answering them would be an answer about three models at once.
    """
    candidate = ddm_mapping()
    fit(candidate)
    fit(variant(candidate, 'd'))
    fit(variant(candidate, 'e'))
    never_fitted = variant(candidate, 'v')

    response = dashboard.client.get('/api/bonded-parameterizations',
                                    query_string={'mapping_hash': mappings.candidate_identity(never_fitted)})

    assert response.status_code == 200
    assert response.json['summary']['parameterized'] is False
    assert response.json['revisions'] == []
    assert response.json['jobs'] == [], 'the three stored jobs belong to other models'
    assert len(fitting.jobs()) == 3, 'and they are still stored, not hidden'


def test_a_job_queued_before_its_record_exists_is_still_this_models(dashboard):
    """Provenance is why a candidate hash is a filter at all: a job is queued before it saves a revision.

    A fit that failed leaves the job and no record, and the panel must still see the job it is waiting on.
    Filtering the empty answer by the hash the request named -- rather than by the record's content hash,
    which an absent record does not have -- is what makes both cases true at once.
    """
    candidate = ddm_mapping()

    def writes_nothing(command, cwd, **kwargs):
        return None

    with pytest.raises(RuntimeError):
        fitting.start(candidate, engine='fast-forward', reference=REFERENCE, molecule_root=MOLECULES,
                      background=False, runner=writes_nothing)
    assert parameterization.one(parameterization.content_identity(candidate))['revisions'] == []

    response = dashboard.client.get('/api/bonded-parameterizations',
                                    query_string={'mapping_hash': mappings.candidate_identity(candidate)})

    assert response.status_code == 200
    assert response.json['summary']['parameterized'] is False
    assert [job['mapping_hash'] for job in response.json['jobs']] == [
        mappings.candidate_identity(candidate)], 'the job exists before its revision does'


# --- GET /api/bonded-parameterizations/jobs -----------------------------------------------------------

def test_the_job_box_lists_one_mappings_jobs_newest_first(dashboard):
    candidate = ddm_mapping()
    first = fit(candidate)
    second = fit(candidate)
    other = fit(variant(candidate))
    content_hash = parameterization.content_identity(candidate)

    response = dashboard.client.get('/api/bonded-parameterizations/jobs',
                                   query_string={'content_hash': content_hash})

    assert response.status_code == 200
    jobs = response.json['jobs']
    assert [item['id'] for item in jobs] == [second['id'], first['id']]
    assert [item['created_at'] for item in jobs] == sorted((item['created_at'] for item in jobs), reverse=True)
    assert other['id'] not in [item['id'] for item in jobs], 'another model\'s fit is not this box\'s'


# --- POST /api/bonded-parameterizations/jobs/<job_id>/cancel ------------------------------------------

def test_a_job_is_cancelled_through_the_jobs_own_cancel(dashboard, monkeypatch):
    seen = []

    def cancel(job_id):
        seen.append(job_id)
        return {'id': job_id, 'status': 'cancelled', 'cancelled_at': '2026-10-20T00:00:00+00:00'}

    monkeypatch.setattr(fitting, 'cancel', cancel)

    response = dashboard.client.post('/api/bonded-parameterizations/jobs/0123456789abcdef/cancel')

    assert response.status_code == 200
    assert response.json['status'] == 'cancelled'
    assert seen == ['0123456789abcdef']


def test_cancelling_a_job_nobody_queued_is_not_found(dashboard):
    assert dashboard.client.post('/api/bonded-parameterizations/jobs/ffffffffffffffff/cancel').status_code == 404


# --- PATCH /api/bonded-parameterizations/<content_hash> -----------------------------------------------

def test_making_a_revision_current_requires_confirmation(dashboard):
    candidate = ddm_mapping()
    fit(candidate)
    content_hash = parameterization.content_identity(candidate)

    response = dashboard.client.patch(f'/api/bonded-parameterizations/{content_hash}',
                                      json={'current': 1})

    assert response.status_code == 400
    assert 'confirmation' in response.json['error']
    assert parameterization.current(candidate)['revision'] == 1, 'nothing moved'


def test_an_earlier_revision_is_made_current_again_by_a_content_hash(dashboard):
    candidate = ddm_mapping()
    fit(candidate)
    fit(candidate)
    content_hash = parameterization.content_identity(candidate)
    # Saved, so the route can find the candidate from the hash alone -- which is what a panel holding only a
    # record needs, and what keeps the re-point working for a candidate that has since been renamed.
    mappings.save_draft(candidate)

    response = dashboard.client.patch(f'/api/bonded-parameterizations/{content_hash}',
                                      json={'current': 1, 'confirm': True})

    assert response.status_code == 200
    body = response.json
    assert body['current']['revision'] == 1
    assert body['revision'] == 1
    assert [item['revision'] for item in body['revisions']] == [1, 2], 'the history is kept'
    assert parameterization.current(candidate)['revision'] == 1


def test_an_unknown_hash_cannot_be_made_current(dashboard):
    response = dashboard.client.patch(f'/api/bonded-parameterizations/{"e" * 64}',
                                      json={'current': 1, 'confirm': True})

    assert response.status_code == 404
    assert 'No saved mapping' in response.json['error']


def test_a_revision_that_does_not_exist_is_not_found(dashboard):
    candidate = ddm_mapping()
    fit(candidate)
    content_hash = parameterization.content_identity(candidate)
    mappings.save_draft(candidate)

    response = dashboard.client.patch(f'/api/bonded-parameterizations/{content_hash}',
                                      json={'current': 9, 'confirm': True})

    assert response.status_code == 404
    assert 'Unknown parameterization revision' in response.json['error']


def test_the_jobs_route_answers_a_job_by_its_own_id(dashboard):
    """What the panel's poll asks while a fit runs: its job, by the id it was given when it queued it.

    The content-hash question is a mapping's history; a running job's state is the job's own. A poll answered by the
    mapping's hash is right only while the job's hash agrees with it, and when they disagreed the box kept the record
    it queued and sat on `queued` with nothing saying why.
    """
    candidate = ddm_mapping()
    other = ddm_mapping(name='DDM · another')
    other['beads'][0]['label'] = 'v'
    first = fit(candidate)
    second = fit(other)

    by_id = dashboard.client.get('/api/bonded-parameterizations/jobs',
                                 query_string={'job_id': first['id']}).json['jobs']
    assert [item['id'] for item in by_id] == [first['id']]
    assert by_id[0]['status'] == 'completed'
    assert dashboard.client.get('/api/bonded-parameterizations/jobs',
                                query_string={'job_id': '0' * 16}).json['jobs'] == []
    # And the hash-addressed question still answers the whole history, newest first.
    history = dashboard.client.get('/api/bonded-parameterizations/jobs',
                                   query_string={'content_hash': parameterization.content_identity(candidate)}).json['jobs']
    assert [item['id'] for item in history] == [first['id']]
    assert second['id'] != first['id']


# --- DELETE /api/bonded-parameterizations/<content_hash> ----------------------------------------------


def test_deleting_a_parameterization_removes_the_model_and_leaves_the_mapping_alone(dashboard):
    """The panel's destructive control removes a *parameterization*, not the user's model.

    The mapping is the file a run is queued from, and the editor owns the catalogue; this panel edits models. So the
    revision, the fit job that produced it and the work those fits built go, and the saved candidate is still there
    afterwards -- which is the difference between this route and `DELETE /api/mappings/drafts/<name>`.
    """
    candidate = ddm_mapping()
    job = fit(candidate)
    content_hash = parameterization.content_identity(candidate)
    workspace = Path(dashboard.paths.workspace)
    drafts = Path(dashboard.paths.mapping_drafts)
    (drafts).mkdir(parents=True, exist_ok=True)
    saved = drafts / 'mapping_candidate_ddm.json'
    saved.write_text(json.dumps(candidate))
    work = Path(job['work'])
    assert work.is_dir() and (workspace / 'parameterizations' / 'records' / f'{content_hash}.json').is_file()

    response = dashboard.client.delete(f'/api/bonded-parameterizations/{content_hash}',
                                       json={'confirm': True, 'revision': 1})

    assert response.status_code == 200, response.data
    report = response.json
    assert report['deleted'] is True and report['revisions'] == [1] and report['jobs'] == [job['id']]
    assert not (workspace / 'parameterizations' / 'records' / f'{content_hash}.json').exists()
    assert not work.exists()
    # The model the user made is untouched, and so is the catalogue that lists it.
    assert saved.is_file() and json.loads(saved.read_text())['beads'] == candidate['beads']


def test_deleting_a_parameterization_needs_confirmation_and_a_revision_that_still_matches(dashboard):
    """Two refusals, both about irreversibility: no confirmation, and a record that moved on since the panel read it."""
    candidate = ddm_mapping()
    fit(candidate)
    content_hash = parameterization.content_identity(candidate)

    without = dashboard.client.delete(f'/api/bonded-parameterizations/{content_hash}', json={})
    assert without.status_code == 400 and 'requires confirmation' in without.json['error']

    stale = dashboard.client.delete(f'/api/bonded-parameterizations/{content_hash}',
                                    json={'confirm': True, 'revision': 9})
    assert stale.status_code == 409 and 'reload it before deleting' in stale.json['error']

    # A second fit makes revision 2 current, so a panel still holding revision 1 is stale by this rule.
    fit(candidate)
    current = parameterization.summary(candidate)['revision']
    assert current == 2
    held = dashboard.client.delete(f'/api/bonded-parameterizations/{content_hash}',
                                   json={'confirm': True, 'revision': 1})
    assert held.status_code == 409
    assert parameterization.one(content_hash)['revision'] == 2, 'nothing was deleted by a refused call'


def test_deleting_a_parameterization_that_does_not_exist_is_not_an_error(dashboard):
    """Idempotent, like the store's own delete: a caller asking about absence is answered, not faulted."""
    response = dashboard.client.delete(f'/api/bonded-parameterizations/{"e" * 64}', json={'confirm': True})

    assert response.status_code == 200
    assert response.json['deleted'] is False and response.json['revisions'] == []
