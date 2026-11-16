"""What decides an analysis result is what an attempt's identity names -- never a digest of the sources or the code.

A hand-written list of module files once stood in this place and had drifted: `bonded_terms`, `consistency`,
`mapping_consistency`, `layout` and `sugar_ensemble` were not in it, so fixing the overlap metric changed no
signature. The fix of the day walked the packages and hashed every module; the contract now is the opposite. An
attempt is identified by what it was asked -- its kind, payload, the source *names*, the run name -- and by the code
*version* the deployment states, so an analysis over a 2 GB trajectory no longer reads the checkout, and a source
replaced in place is still the input the same analysis already read.
"""
import json

from dashboard import files
from dashboard.execution.coordination import analysis_coordinator as coordinator


def test_identity_names_its_sources_and_never_reads_their_bytes(monkeypatch, tmp_path):
    """Two files with different bytes under the same name are the same input to the same analysis."""
    monkeypatch.setenv('DASHBOARD_CODE_VERSION', 'release-7')
    coordinator.code_version.cache_clear()
    try:
        first = tmp_path / 'first.xvg'
        first.write_text('0 10\n1 12\n')
        other = tmp_path / 'other.xvg'
        other.write_text('0 99\n1 98\n')

        one = coordinator.identity('overlap', {'threshold': 1.0}, {'2_mapping/mapped.gro': first}, 'sucrose-cg')
        two = coordinator.identity('overlap', {'threshold': 1.0}, {'2_mapping/mapped.gro': other}, 'sucrose-cg')

        assert one == two, 'the name decides, not the bytes behind it'
        recorded = json.loads(one)
        assert recorded['sources'] == ['2_mapping/mapped.gro']
        assert recorded['run'] == 'sucrose-cg'
        assert recorded['code'] == 'release-7'
    finally:
        coordinator.code_version.cache_clear()


def test_a_moved_source_an_edited_payload_or_another_run_is_a_new_attempt(monkeypatch):
    monkeypatch.setenv('DASHBOARD_CODE_VERSION', 'release-7')
    coordinator.code_version.cache_clear()
    try:
        base = coordinator.identity('overlap', {'threshold': 1.0}, {'a.xtc': None}, 'run-one')

        assert coordinator.identity('overlap', {'threshold': 1.0}, {'b.xtc': None}, 'run-one') != base
        assert coordinator.identity('overlap', {'threshold': 2.0}, {'a.xtc': None}, 'run-one') != base
        assert coordinator.identity('overlap', {'threshold': 1.0}, {'a.xtc': None}, 'run-two') != base
        assert coordinator.identity('overlap', {'threshold': 1.0}, {'a.xtc': None}, 'run-one') == base
    finally:
        coordinator.code_version.cache_clear()


def test_a_newer_dependency_is_a_new_attempt_without_hashing_it(monkeypatch):
    """A refinement re-reads what another analysis published; the published set's name is the change."""
    monkeypatch.setenv('DASHBOARD_CODE_VERSION', 'release-7')
    coordinator.code_version.cache_clear()
    try:
        older = coordinator.identity('refinement-score', {}, {}, 'run-one',
                                     {'numerical_stability.json': 'analyses/stability/0001-20261101/output/x/n.json'})
        newer = coordinator.identity('refinement-score', {}, {}, 'run-one',
                                     {'numerical_stability.json': 'analyses/stability/0002-20261102/output/y/n.json'})

        assert older != newer
    finally:
        coordinator.code_version.cache_clear()


def test_the_code_version_is_the_deployments_statement_and_is_read_once(monkeypatch):
    """The version changes when the deployment says the code changed; a running process keeps the one it read."""
    monkeypatch.setenv('DASHBOARD_CODE_VERSION', 'release-7')
    coordinator.code_version.cache_clear()
    try:
        assert coordinator.code_version() == 'release-7'
        monkeypatch.setenv('DASHBOARD_CODE_VERSION', 'release-8')
        assert coordinator.code_version() == 'release-7', 'a running dashboard reads its code version once'
    finally:
        coordinator.code_version.cache_clear()


def test_a_copy_with_no_git_and_no_statement_answers_a_constant(monkeypatch, tmp_path):
    monkeypatch.delenv('DASHBOARD_CODE_VERSION', raising=False)
    monkeypatch.setattr(coordinator.paths, 'PROJECT_ROOT', tmp_path)
    coordinator.code_version.cache_clear()
    try:
        assert coordinator.code_version() == coordinator.UNKNOWN_CODE_VERSION
    finally:
        coordinator.code_version.cache_clear()


def test_an_identity_carries_no_digest_of_a_source(tmp_path):
    source = tmp_path / 'mapped.gro'
    source.write_text('a gro file\n')

    assert files.sha256(source) not in coordinator.identity(
        'bonded-cross-check', {}, {'2_mapping/mapped.gro': source}, 'run-one')


def test_no_walk_of_the_code_files_remains():
    """The walk named files and hashed them; an attempt is named by the deployment's version instead."""
    assert not hasattr(coordinator, 'code_fingerprint_files')
