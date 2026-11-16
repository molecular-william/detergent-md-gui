"""The recorded code a run executes, and the refusal when its version moved."""
import sys

import pytest
from dashboard import files
from dashboard.execution import run_scripts


def recorded_fixture(tmp_path, monkeypatch, *, version=1, name='fixture_stage', path='scripts/stage.sh'):
    monkeypatch.setitem(run_scripts.CODE_VERSIONS, name, {'path': path, 'version': version})


def test_a_script_is_recorded_by_name_and_version(tmp_path, monkeypatch):
    (tmp_path / 'scripts').mkdir()
    script = tmp_path / 'scripts' / 'stage.sh'
    script.write_text('echo hi\n')
    recorded_fixture(tmp_path, monkeypatch)

    record = run_scripts.record({'Stage': 'scripts/stage.sh'}, root=tmp_path)

    assert record['Stage'] == {'name': 'fixture_stage', 'version': 1}
    assert run_scripts.verify_one('Stage', record['Stage'], root=tmp_path) == script.resolve()


def test_a_changed_code_version_is_refused_by_stage_name(tmp_path, monkeypatch):
    (tmp_path / 'scripts').mkdir()
    script = tmp_path / 'scripts' / 'stage.sh'
    script.write_text('one\n')
    recorded_fixture(tmp_path, monkeypatch)
    record = run_scripts.record({'Stage': 'scripts/stage.sh'}, root=tmp_path)
    script.write_text('two\n')
    assert run_scripts.verify_one('Stage', record['Stage'], root=tmp_path) == script.resolve(), \
        'the bytes are not the claim any more: the recorded version is'

    recorded_fixture(tmp_path, monkeypatch, version=2)
    with pytest.raises(ValueError, match='the stage script for Stage changed since this run was prepared'):
        run_scripts.verify_one('Stage', record['Stage'], root=tmp_path)


def test_a_recorded_name_that_no_longer_resolves_is_refused(tmp_path):
    with pytest.raises(ValueError, match='no code version is registered'):
        run_scripts.verify_one('Stage', {'name': 'gone', 'version': 1}, root=tmp_path)


def test_a_missing_script_is_refused(tmp_path, monkeypatch):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts' / 'stage.sh').write_text('echo hi\n')
    recorded_fixture(tmp_path, monkeypatch)
    record = run_scripts.record({'Stage': 'scripts/stage.sh'}, root=tmp_path)
    (tmp_path / 'scripts' / 'stage.sh').unlink()

    with pytest.raises(ValueError, match='the stage script for Stage is missing'):
        run_scripts.verify_one('Stage', record['Stage'], root=tmp_path)


def test_a_script_outside_the_repository_is_refused(tmp_path):
    outside = tmp_path.parent / 'outside.sh'
    outside.write_text('x\n')

    with pytest.raises(ValueError, match='outside the repository'):
        run_scripts.record({'Stage': str(outside)}, root=tmp_path / 'repo')


def test_a_run_without_a_record_still_uses_its_own_copy(tmp_path):
    fallback = tmp_path / 'stages' / '01' / 'run.sh'

    assert run_scripts.script_for({}, 'Stage', fallback, root=tmp_path) == fallback


def test_a_legacy_digest_record_still_verifies_by_digest(tmp_path):
    script = tmp_path / 'stage.sh'
    script.write_text('echo hi\n')
    declared = {'path': 'stage.sh', 'sha256': files.sha256(script)}

    assert run_scripts.verify_one('Stage', declared, root=tmp_path) == script.resolve()
    script.write_text('changed\n')
    with pytest.raises(ValueError, match='the stage script for Stage changed since this run was prepared'):
        run_scripts.verify_one('Stage', declared, root=tmp_path)


def test_a_recorded_path_moved_into_a_feature_still_resolves(tmp_path, monkeypatch):
    """A run records the spelling of its day. When a feature distribution takes the file over, the record keeps
    verifying: the bytes are the same, only their home moved, and a manifest is never rewritten to say so."""
    package = tmp_path / 'fake_moved_dist'
    (package / 'scripts').mkdir(parents=True)
    (package / '__init__.py').write_text('')
    script = package / 'scripts' / 'stage.sh'
    script.write_text('echo hi\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(run_scripts, '_FEATURE_PREFIXES', [])
    run_scripts.register_prefixes((('dashboard/execution/scripts/fake_', 'fake_moved_dist', 'scripts/'),))

    recorded = {'path': 'dashboard/execution/scripts/fake_stage.sh', 'sha256': files.sha256(script)}

    assert run_scripts.code_path(recorded['path'], root=tmp_path) == script.resolve()
    assert run_scripts.verify_one('Stage', recorded, root=tmp_path) == script.resolve()
    sys.modules.pop('fake_moved_dist', None)
