"""The reader for the bonded cross-check: which attempt answers, and what it does when none does.

Same shape as the overlap reader's tests, minus the figure: this analysis publishes numbers and a list of terms, so a
report on disk is the whole artifact and there is nothing to lose track of.
"""
import json
import os

from dashboard.web.routes.analyses import newest_cross_check


class _Coordinator:
    """The two things a reader asks of a coordinator: where a run lives, and where runs live."""

    def __init__(self, root):
        self.RUNS = root

    def run_path(self, job):
        return self.RUNS / job['id']


def _attempt(root, attempt_id, *, report=True, mtime=1_000_000.0):
    signature = root / 'analyses/bonded-cross-check/signature' / attempt_id
    output = signature / 'output/key'
    output.mkdir(parents=True)
    record = signature / 'result.json'
    record.write_text(json.dumps({'output_directory': 'output/key'}))
    if report:
        (output / 'bonded-cross-check.json').write_text(json.dumps({
            'molecule': 'DDM', 'threshold': 10000.0, 'temperature': 303.15,
            'rows': [{'beads': ['B01', 'B02'], 'verdicts_agree': False}],
            'disagreements': [['B01', 'B02']], 'scientifically_validated': False}))
    os.utime(record, (mtime, mtime))
    return signature


def test_a_run_with_no_published_cross_check_answers_none(tmp_path):
    job = {'id': 'aaaaaaaaaaaa'}
    (tmp_path / 'aaaaaaaaaaaa').mkdir()

    assert newest_cross_check(_Coordinator(tmp_path), job) is None


def test_the_published_attempt_is_found_through_the_output_directory_its_record_names(tmp_path):
    job = {'id': 'aaaaaaaaaaaa'}
    _attempt(tmp_path / 'aaaaaaaaaaaa', 'attempt-one')

    attempt, published, report = newest_cross_check(_Coordinator(tmp_path), job)

    assert attempt.name == 'attempt-one'
    assert published['disagreements'] == [['B01', 'B02']]
    assert report.name == 'bonded-cross-check.json'


def test_an_attempt_whose_report_is_gone_is_skipped_for_an_older_one(tmp_path):
    """The fall-through the plan asks for. An attempt that names a file the run no longer has is not a published
    analysis, and the card pointing at it would render a table with nothing in it."""
    job = {'id': 'aaaaaaaaaaaa'}
    root = tmp_path / 'aaaaaaaaaaaa'
    _attempt(root, 'attempt-old', mtime=1_000_000.0)
    _attempt(root, 'attempt-new', report=False, mtime=2_000_000.0)

    attempt, _, _ = newest_cross_check(_Coordinator(tmp_path), job)

    assert attempt.name == 'attempt-old'


def test_nothing_published_at_all_still_answers_none(tmp_path):
    job = {'id': 'aaaaaaaaaaaa'}
    _attempt(tmp_path / 'aaaaaaaaaaaa', 'attempt-one', report=False)

    assert newest_cross_check(_Coordinator(tmp_path), job) is None
