"""One resolver for stage-log locations, so the writer and the reader cannot disagree.

The location used to be encoded in three places (workflow.run's writer, the
coordinator's resume directory, and a candidate list in the ETA view) and decoded
in one, which is why reading an ETA meant trying paths in order and hoping.
"""
from pathlib import Path

from dashboard.execution.coordination import manifest


def test_a_normal_attempt_is_encoded_under_logs(tmp_path):
    assert manifest.stage_log_path(tmp_path, name='02_ions') == tmp_path / 'logs' / '02_ions.log'


def test_a_resumed_attempt_is_encoded_in_its_own_directory(tmp_path):
    assert (manifest.stage_log_path(tmp_path, name='02_ions', resume_count=2)
            == tmp_path / 'logs' / 'resume-0002' / '02_ions.log')


def test_a_relative_recorded_log_resolves_within_the_run(tmp_path):
    log = tmp_path / 'stages' / '02_ions' / '02_ions.log'
    log.parent.mkdir(parents=True)
    log.write_text('stage output\n')
    assert manifest.stage_log_path(tmp_path, recorded='stages/02_ions/02_ions.log') == log


def test_an_absolute_recorded_log_is_anchored_to_the_run(tmp_path):
    """A moved workspace must not lose provenance: the run's own portion is used."""
    log = tmp_path / 'logs' / '02_ions.log'
    log.parent.mkdir(parents=True)
    log.write_text('stage output\n')
    moved = Path('/workspace/runs') / tmp_path.name / 'logs' / '02_ions.log'
    assert manifest.stage_log_path(tmp_path, recorded=str(moved)) == log


def test_a_recorded_log_outside_the_run_is_refused(tmp_path):
    outside = tmp_path.parent / 'elsewhere.log'
    outside.write_text('not this run\n')
    assert manifest.stage_log_path(tmp_path, recorded=str(outside)) is None


def test_a_recorded_log_that_is_not_there_is_refused(tmp_path):
    assert manifest.stage_log_path(tmp_path, recorded='logs/02_ions.log') is None


def test_a_symlinked_recorded_log_is_refused(tmp_path):
    target = tmp_path.parent / 'real.log'
    target.write_text('elsewhere\n')
    link = tmp_path / 'logs' / '02_ions.log'
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    assert manifest.stage_log_path(tmp_path, recorded='logs/02_ions.log') is None


def test_the_writer_and_the_reader_agree(tmp_path):
    """Encode then decode returns the same path -- what the guessing loop could not guarantee."""
    encoded = manifest.stage_log_path(tmp_path, name='02_ions', resume_count=3)
    encoded.parent.mkdir(parents=True)
    encoded.write_text('stage output\n')
    relative = encoded.relative_to(tmp_path)
    assert manifest.stage_log_path(tmp_path, recorded=str(relative)) == encoded
    anchored = Path('/workspace/runs') / tmp_path.name / relative
    assert manifest.stage_log_path(tmp_path, recorded=str(anchored)) == encoded


def test_neither_a_name_nor_a_recorded_path_resolves_to_nothing(tmp_path):
    assert manifest.stage_log_path(tmp_path) is None
