"""Every prepared run records the same manifest keys.

Four modules emitted this document and they disagreed: the composition adapter wrote no input
snapshot at all -- the key the resume path verifies a run's inputs against -- and only the AA
adapter recorded the environment its stages ran in. The shared writer is the one place that
decides the key set now, so a run type cannot quietly omit what resume checks.
"""
import json

from dashboard import files
from dashboard.execution import protocol


def test_the_shared_writer_records_the_keys_every_run_type_needs(tmp_path):
    run = tmp_path / 'run'; (run / 'inputs').mkdir(parents=True)
    (run / 'inputs' / 'system.top').write_text('topology')
    document = protocol.write_prepared_manifest(
        run, {'run_type': 'aa_only'}, tools={'gmx': {'path': '/usr/bin/gmx'}},
        plan=['AA solvation'], environment={'PATH': '/bin'})
    on_disk = json.loads((run / 'manifest.json').read_text())
    assert on_disk == document, 'the caller must be able to act on what was written'
    assert on_disk['layout_version'] == 2 and on_disk['stages'] == []
    assert on_disk['stage_plan'] == ['AA solvation']
    assert on_disk['input_snapshot_sha256'] == files.hashes(run / 'inputs')
    assert on_disk['prepared_at'] and on_disk['tools'] and on_disk['environment']
    assert on_disk['run_type'] == 'aa_only', 'what the caller knows about the run is kept'


def test_an_absent_environment_is_not_invented(tmp_path):
    """A caller that records no environment gets no environment key, not an empty one."""
    run = tmp_path / 'run'; (run / 'inputs').mkdir(parents=True)
    assert 'environment' not in protocol.write_prepared_manifest(run, {}, tools={}, plan=[])
