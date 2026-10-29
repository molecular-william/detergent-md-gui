"""The recorded code a run executes, and the refusal when it changed."""
import pytest
from dashboard.execution import run_scripts


def test_a_script_is_recorded_by_repository_path_and_digest(tmp_path):
    (tmp_path / 'scripts').mkdir()
    script = tmp_path / 'scripts' / 'stage.sh'
    script.write_text('echo hi\n')

    record = run_scripts.record({'Stage': 'scripts/stage.sh'}, root=tmp_path)

    assert record['Stage']['path'] == 'scripts/stage.sh'
    assert run_scripts.verify_one('Stage', record['Stage'], root=tmp_path) == script.resolve()


def test_a_changed_script_is_refused_by_stage_name(tmp_path):
    script = tmp_path / 'stage.sh'
    script.write_text('one\n')
    record = run_scripts.record({'Stage': 'stage.sh'}, root=tmp_path)
    script.write_text('two\n')

    with pytest.raises(ValueError, match='the stage script for Stage changed'):
        run_scripts.verify_one('Stage', record['Stage'], root=tmp_path)


def test_a_script_outside_the_repository_is_refused(tmp_path):
    outside = tmp_path.parent / 'outside.sh'
    outside.write_text('x\n')

    with pytest.raises(ValueError, match='outside the repository'):
        run_scripts.record({'Stage': str(outside)}, root=tmp_path / 'repo')


def test_a_run_without_a_record_still_uses_its_own_copy(tmp_path):
    fallback = tmp_path / 'stages' / '01' / 'run.sh'

    assert run_scripts.script_for({}, 'Stage', fallback, root=tmp_path) == fallback
