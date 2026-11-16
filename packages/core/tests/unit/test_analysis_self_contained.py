"""A run directory alone must hold every input its analyses read, not only what they published.

`ff-interactions` reads the reference histograms from the parameterization store, which sits beside `runs/`, outside
the run. The worker copies every source that lives outside the run into the **run** under `sources/<recorded name>`
-- once per run, not once per attempt -- and `worker.source_path` answers that copy when the original is not on the
machine. This builds such a run, runs two attempts, copies **only** the run directory to a workspace with no store,
and proves the recorded external source resolves inside the copied run, that its published record travelled with it,
and that the second attempt bought no second copy.
"""
import json
import shutil

import pytest
from dashboard import features
from dashboard.analysis import worker
from detergent_validation.analysis.runs import ff_interactions

#: The stable name of the outside source, and the run-relative name the worker records for its one copy.
SHARED = 'shared/parameterizations/records/ddm.revisions/1/B01_B02_bonds_distr.dat'
EXTERNAL = 'sources/' + SHARED


@pytest.fixture(autouse=True)
def _installed_features():
    """`ff-interactions` is the validation feature's kind, so the table is complete before the worker reads it."""
    features.ensure()


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _distribution(rows=('0.0 0.2', '0.5 0.8')):
    return '\n'.join(rows) + '\n'


def _run(tmp_path):
    """An AA-CG run that consumed a revision recording one bond histogram, which lives outside the run."""
    workspace = tmp_path/'workspace'
    run = workspace/'runs'/'bbbbbbbbbbbb'
    store = workspace/'parameterizations'/'records'/'ddm.revisions'/'1'/'B01_B02_bonds_distr.dat'
    _write(store, _distribution())
    _write(run/'stages'/'5_assessment'/'B01_B02_bonds_distr.dat', _distribution(('0.0 0.3', '0.5 0.7')))
    _write(run/'stages'/'5_assessment'/'report_interactions.out',
           'bonds\nB01_B02 : 0.12 (0.88)\nOverall Score : 0.12 ± 0.01\n')
    _write(run/'stages'/'2_mapping'/'model.json',
           json.dumps({'beads': [{'export_name': 'B01'}, {'export_name': 'B02'}]}))
    _write(run/'stages'/'3_initial_CG'/'parameterization_used.json', json.dumps({
        'fitted': False, 'revision': 1, 'engine': 'fast-forward',
        'reference_distributions': [{'name': str(store), 'sha256': 'x'}]}))
    _write(run/'manifest.json', json.dumps({'run_type': 'aa_cg', 'status': 'completed', 'stages': []}))
    return run, store


def _execute(run, attempt='0001-20261001'):
    """One worker attempt, through the same entry point the coordinator starts."""
    request = run/'analyses'/'ff-interactions'/attempt/'request.json'
    request.parent.mkdir(parents=True, exist_ok=True)
    request.write_text(json.dumps({'run': str(run), 'kind': 'ff-interactions', 'payload': {}}))
    worker.execute(request)
    return request.parent


def test_the_run_copies_an_external_source_once_and_records_its_run_relative_name(tmp_path):
    run, store = _run(tmp_path)
    attempt = _execute(run)

    recorded = json.loads((attempt/'sources.json').read_text())
    assert recorded == sorted(recorded), 'sources.json is still a sorted list of names'
    assert EXTERNAL in recorded
    assert (run/'sources'/SHARED).read_bytes() == store.read_bytes(), 'the run copy preserves the bytes'
    assert not (attempt/'sources').exists(), 'the attempt carries no copy of its own'
    result = json.loads((attempt/'result.json').read_text())
    assert 'ff-interactions.json' in result['outputs_sha256']
    assert (attempt/result['output_directory']/'ff-interactions.json').is_file()


def test_a_second_attempt_reuses_the_runs_copy_and_stages_no_second_file(tmp_path):
    run, store = _run(tmp_path)
    first = _execute(run)
    copy = run/'sources'/SHARED
    stamp = copy.stat().st_ino

    second = _execute(run, '0002-20261002')

    assert json.loads((second/'sources.json').read_text()) == json.loads((first/'sources.json').read_text())
    assert [path for path in (run/'sources').rglob('*') if path.is_file()] == [copy], \
        'the run keeps one copy, not one per attempt'
    assert copy.stat().st_ino == stamp, 'the second attempt replaced the run copy instead of reusing it'
    assert not (second/'sources').exists()


def test_a_run_copied_without_its_store_resolves_every_source_from_the_run_alone(tmp_path):
    run, store = _run(tmp_path)
    attempt = _execute(run)

    fresh = tmp_path/'elsewhere'/'workspace'/'runs'/run.name
    shutil.copytree(run, fresh)
    assert not (tmp_path/'elsewhere'/'workspace'/'parameterizations').exists(), 'the store did not travel'

    copied_attempt = fresh/'analyses'/'ff-interactions'/attempt.name
    for name in json.loads((copied_attempt/'sources.json').read_text()):
        assert worker.source_path(fresh, copied_attempt, name) is not None, name
    resolved = worker.source_path(fresh, copied_attempt, EXTERNAL)
    assert resolved is not None and resolved.is_relative_to(fresh/'sources'), \
        'the copy answers from the run, not from an attempt'
    assert resolved.read_bytes() == store.read_bytes()
    assert (copied_attempt/'output'/'ff-interactions.json').is_file(), 'the published output is in the attempt'


def test_the_copied_run_rebuilds_from_its_own_copy_without_nesting_it(tmp_path):
    run, store = _run(tmp_path)
    _execute(run)
    fresh = tmp_path/'elsewhere'/'workspace'/'runs'/run.name
    shutil.copytree(run, fresh)
    # The recorded distribution was an absolute path. Removing it is what the copy onto another machine does to it:
    # the path the run's own record names no longer opens, and only the run's copy is left.
    store.unlink()

    entries = ff_interactions.sources(fresh)
    assert 'store/B01_B02_bonds_distr.dat' in entries
    assert entries['store/B01_B02_bonds_distr.dat'].is_relative_to(fresh/'sources')

    attempt = _execute(fresh, '0002-20261002')
    recorded = json.loads((attempt/'sources.json').read_text())
    assert recorded.count(EXTERNAL) == 1
    assert not [name for name in recorded if name.startswith('analyses/')], \
        'a copy read from the run keeps its recorded name instead of nesting the attempt path'
    assert [path for path in (fresh/'sources').rglob('*') if path.is_file()] == [fresh/'sources'/SHARED]
    record = json.loads((attempt/'output'/'ff-interactions.json').read_text())
    assert not any(term.get('reference_missing') for term in record['terms'])
    assert all(term.get('reference') for term in record['terms'])
