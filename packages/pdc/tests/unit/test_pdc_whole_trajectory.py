"""Rebuilding a pdc run's derived whole.xtc from its raw mdrun output.

The raw trajectory is a simulation output and is never written; the derived file is what the analyses and the Run
view read, so it can be rebuilt at a smaller cadence or precision. The tests use a stand-in `gmx` that writes a file,
so they pin the command, the atomic replacement and the records without a conversion.
"""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from detergent_pdc.execution import rebuild_whole


def fake_gmx(tmp_path, body='printf converted > "$out"\n', exit_code=0):
    """A stand-in gmx: it reads `-o`, writes that file, and exits as told."""
    script = tmp_path / 'gmx'
    script.write_text('#!/bin/bash\nfor ((i=1;i<=$#;i++)); do\n'
                      ' if [ "${!i}" = "-o" ]; then j=$((i+1)); out=${!j}; fi\ndone\n'
                      + (body or '') + f'exit {exit_code}\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def written_run(tmp_path, *, stage='08_extension'):
    root = tmp_path / 'run'
    prod = root / 'stages' / stage / 'prod'
    prod.mkdir(parents=True)
    (prod / 'run.xtc').write_text('raw trajectory')
    (prod / 'run.tpr').write_text('tpr')
    (prod / 'run.gro').write_text('gro')
    (prod / 'whole.xtc').write_text('OLD')
    return root, prod


@pytest.fixture(autouse=True)
def clear_running():
    rebuild_whole._RUNNING.clear()
    yield
    rebuild_whole._RUNNING.clear()


def test_the_command_states_the_pbc_treatment_and_the_size_choices(tmp_path):
    raw = tmp_path / 'run.xtc'
    argv = rebuild_whole.command('/usr/bin/gmx', raw, Path('/t.tpr'), Path('/out.xtc'), dt_ps=100, decimals=2)

    assert argv[:2] == ['/usr/bin/gmx', 'trjconv']
    assert '-pbc' in argv and argv[argv.index('-pbc') + 1] == 'mol'
    assert '-center' in argv
    assert argv[argv.index('-ndec') + 1] == '2'
    assert argv[argv.index('-dt') + 1] == '100'
    assert argv[argv.index('-o') + 1] == '/out.xtc'


def test_the_latest_stage_is_chosen_and_a_run_without_one_is_refused(tmp_path):
    root, prod = written_run(tmp_path, stage='06_assessment')
    stage, raw, tpr = rebuild_whole.locate(root)
    assert stage == 'assessment' and raw == prod / 'run.xtc' and tpr == prod / 'run.tpr'

    extension = root / 'stages/08_extension/prod'
    extension.mkdir(parents=True)
    (extension / 'run.xtc').write_text('raw')
    (extension / 'run.tpr').write_text('tpr')
    assert rebuild_whole.locate(root)[0] == 'extension'

    empty = tmp_path / 'empty'
    empty.mkdir()
    with pytest.raises(ValueError) as refused:
        rebuild_whole.locate(empty)
    assert 'no raw trajectory' in str(refused.value)


def test_a_rebuild_replaces_the_derived_file_and_records_what_it_did(tmp_path, monkeypatch):
    root, prod = written_run(tmp_path)
    monkeypatch.setattr(rebuild_whole.tools, 'tool_path', lambda command: str(fake_gmx(tmp_path)))

    rebuild_whole.rebuild(root, dt_ps=100, decimals=2)

    assert (prod / 'whole.xtc').read_text() == 'converted'
    sidecar = json.loads((prod / 'whole.xtc.json').read_text())
    assert sidecar['options'] == {'pbc': 'mol -center', 'dt_ps': 100.0, 'decimals': 2}
    assert sidecar['bytes'] == len('converted') and sidecar['source']['bytes'] == len('raw trajectory')
    state = rebuild_whole.read_state(root)
    assert state['status'] == 'completed' and state['before_bytes'] == 3 and state['after_bytes'] == len('converted')
    assert not list(prod.glob('.*tmp')), 'the temporary file survived the replacement'


def test_a_failed_conversion_leaves_the_previous_file_alone(tmp_path, monkeypatch):
    root, prod = written_run(tmp_path)
    monkeypatch.setattr(rebuild_whole.tools, 'tool_path', lambda command: str(fake_gmx(tmp_path, body='echo nope >&2\n', exit_code=2)))

    rebuild_whole.rebuild(root, dt_ps=100, decimals=2)

    assert (prod / 'whole.xtc').read_text() == 'OLD'
    state = rebuild_whole.read_state(root)
    assert state['status'] == 'failed' and 'trjconv refused' in state['error']
    assert not list(prod.glob('.*tmp'))


def test_a_missing_gmx_or_raw_file_is_recorded_not_raised(tmp_path, monkeypatch):
    root, prod = written_run(tmp_path)
    monkeypatch.setattr(rebuild_whole.tools, 'tool_path', lambda command: None)

    rebuild_whole.rebuild(root)
    assert rebuild_whole.read_state(root)['status'] == 'failed'
    assert (prod / 'whole.xtc').read_text() == 'OLD'


def test_describe_reports_both_files_and_a_restart_interrupts_a_running_state(tmp_path):
    root, prod = written_run(tmp_path)
    rebuild_whole._write_state(root, {'status': 'running', 'dt_ps': 100, 'decimals': 2})

    answer = rebuild_whole.describe(root)

    assert answer['stage'] == 'extension'
    assert answer['raw']['bytes'] == len('raw trajectory')
    assert answer['whole']['bytes'] == 3
    assert answer['state']['status'] == 'failed'
    assert 'interrupted' in answer['state']['error']
    assert answer['defaults'] == {'dt_ps': 100, 'decimals': 2}


def test_one_rebuild_at_a_time_and_only_the_offered_decimals(tmp_path, monkeypatch):
    root, _ = written_run(tmp_path)
    rebuild_whole._RUNNING[str(root)] = {'started_at': 'now'}
    with pytest.raises(ValueError) as refused:
        rebuild_whole.start(root)
    assert 'already running' in str(refused.value)

    rebuild_whole._RUNNING.clear()
    with pytest.raises(ValueError):
        rebuild_whole.start(root, decimals=4)
    with pytest.raises(ValueError):
        rebuild_whole.start(root, dt_ps=0)


def test_the_header_is_read_with_the_structure_beside_the_trajectory(tmp_path, monkeypatch):
    """The sibling `run.gro` is the structure the header reader needs; joining the stage-relative name twice broke it."""
    root, prod = written_run(tmp_path)
    seen = []

    def read(structure, trajectory):
        seen.append((Path(structure), Path(trajectory)))
        return {'frames': 3, 'time_ns': 0.04}

    monkeypatch.setattr(rebuild_whole.trajectory_header, 'read', read)

    answer = rebuild_whole.describe(root)

    assert seen == [(prod / 'run.gro', prod / 'run.xtc'), (prod / 'run.gro', prod / 'whole.xtc')], seen
    assert answer['raw']['frames'] == 3 and answer['raw']['cadence_ps'] == 20.0


def test_the_temporary_output_keeps_the_xtc_suffix(tmp_path, monkeypatch):
    """gmx trjconv picks its writer from the suffix; a `.tmp` output is refused before it writes anything."""
    root, prod = written_run(tmp_path)
    monkeypatch.setattr(rebuild_whole.tools, 'tool_path', lambda command: str(fake_gmx(tmp_path)))

    rebuild_whole.rebuild(root, dt_ps=100, decimals=2)

    state = rebuild_whole.read_state(root)
    assert state['status'] == 'completed', state
    command = json.loads((prod / 'whole.xtc.json').read_text())['command']
    output = command[command.index('-o') + 1]
    assert Path(output).suffix == '.xtc' and Path(output) != prod / 'whole.xtc'
