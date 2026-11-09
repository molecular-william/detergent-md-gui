"""A source hook may stage a file from outside the run tree; the digest list must still name it."""

from dashboard.analysis.worker import _source_provenance


def test_a_parameterization_store_file_is_named_from_the_workspace(tmp_path):
    run = tmp_path / 'workspace/dashboard/runs/run1'
    run.mkdir(parents=True)
    store = tmp_path / 'workspace/dashboard/parameterizations/records/r.revisions/1/term_distr.dat'
    store.parent.mkdir(parents=True)
    store.write_text('0 1\n')
    assert _source_provenance(run, store) == \
        'shared/parameterizations/records/r.revisions/1/term_distr.dat'


def test_a_file_inside_the_run_keeps_the_run_relative_name(tmp_path):
    run = tmp_path / 'workspace/dashboard/runs/run1'
    run.mkdir(parents=True)
    source = run / 'stages/5_assessment/term_distr.dat'
    source.parent.mkdir(parents=True)
    source.write_text('0 1\n')
    assert _source_provenance(run, source) == 'stages/5_assessment/term_distr.dat'
