"""The reader for the overlap analysis: which attempt answers, and what it does when none does.

`newest_overlap` is a function of a run directory, so it is tested as one -- a stub coordinator handing back a
directory this test built. The rules it keeps are the ones every analysis reader here keeps: the newest attempt whose
*named file is still on disk* answers, an older one that still stands may answer instead, and a run with nothing
published answers `None` rather than a substitute.
"""
import json
import os

from dashboard.web.routes.analyses import newest_overlap


class _Coordinator:
    """The two things the reader asks of a coordinator: where a run lives, and where runs live."""

    def __init__(self, root):
        self.RUNS = root

    def run_path(self, job):
        return self.RUNS / job['id']


def _attempt(root, attempt_id, *, figure=True, mtime=1_000_000.0):
    """A published attempt laid out the way the worker lays one out: output/<key>/ under a signature."""
    signature = root / 'analyses/overlap/signature' / attempt_id
    output = signature / 'output/key'
    output.mkdir(parents=True)
    record = signature / 'result.json'
    record.write_text(json.dumps({'output_directory': 'output/key'}))
    (output / 'overlap.json').write_text(json.dumps({
        'figure': 'overlap.html', 'overlaps': [0.9], 'bead_names': ['B01', 'B02'], 'residue': 'DDM',
        'range_nm': [0.1, 0.6], 'limitations': ['Intra-residue bead distances only.'],
        'scientifically_validated': False}))
    if figure:
        (output / 'overlap.html').write_text('<html><body>heatmap</body></html>')
    # The reader sorts on this file's mtime, so the test sets it rather than relying on how fast files were written.
    os.utime(record, (mtime, mtime))
    return signature


def test_a_run_with_no_published_overlap_answers_none(tmp_path):
    """`None` is a state the card has to be able to state; an invented empty one would send it to a broken frame."""
    job = {'id': 'aaaaaaaaaaaa'}
    (tmp_path / 'aaaaaaaaaaaa').mkdir()

    assert newest_overlap(_Coordinator(tmp_path), job) is None


def test_the_published_attempt_is_found_through_the_output_directory_its_record_names(tmp_path):
    """Two content-addressed levels: the attempt's `result.json` names the output root and the report is relative to
    that. A reader that assumes `output/<hash>` directly reads nothing at all."""
    job = {'id': 'aaaaaaaaaaaa'}
    _attempt(tmp_path / 'aaaaaaaaaaaa', 'attempt-one')

    attempt, published, report, figure = newest_overlap(_Coordinator(tmp_path), job)

    assert attempt.name == 'attempt-one'
    assert published['overlaps'] == [0.9]
    assert report.name == 'overlap.json'
    assert figure is not None and figure.name == 'overlap.html'


def test_an_attempt_whose_figure_is_gone_falls_through_to_an_older_one(tmp_path):
    """'Published' means the file read back, not that a record exists: a card pointing at a deleted figure is a
    broken frame, and an older attempt that still stands may answer."""
    job = {'id': 'aaaaaaaaaaaa'}
    root = tmp_path / 'aaaaaaaaaaaa'
    _attempt(root, 'attempt-old', mtime=1_000_000.0)
    _attempt(root, 'attempt-new', figure=False, mtime=2_000_000.0)

    attempt, _, _, figure = newest_overlap(_Coordinator(tmp_path), job)

    assert attempt.name == 'attempt-old' and figure is not None


def test_when_no_attempt_has_a_figure_the_newest_is_still_reported_without_one(tmp_path):
    """Not `None`: the analysis *did* publish, so the card owes the reader that fact and the reason it cannot draw
    anything, rather than the sentence it uses for a run that was never analysed."""
    job = {'id': 'aaaaaaaaaaaa'}
    _attempt(tmp_path / 'aaaaaaaaaaaa', 'attempt-one', figure=False)

    attempt, published, _, figure = newest_overlap(_Coordinator(tmp_path), job)

    assert attempt.name == 'attempt-one' and figure is None and published['residue'] == 'DDM'
