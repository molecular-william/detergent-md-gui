"""Repairing one published reference: drop its absent copied launchers, then stamp the edition.

The reference this migration exists for (`dbc366ae772b`) names a copied `run.sh` it no longer holds, and that one
entry keeps the whole DDM chain on the legacy digest pin. The repair removes launchers only -- a missing trajectory is
a refused run, not a smaller map -- records what it dropped in the record itself, backs the original up in a ledger,
and proves the result resolves by edition.
"""
import json

import pytest
from dashboard import files
from dashboard.analysis.runs import references
from dashboard.cli import repair_reference_edition as repair

RUN = repair.DEFAULT_RUN


@pytest.fixture
def world(tmp_path):
    """One completed AA reference that names three present artifacts and two absent launchers."""
    run = tmp_path / 'runs' / RUN
    (run / 'stages/07_reference').mkdir(parents=True)
    files.atomic_json(run / 'manifest.json', {'id': RUN, 'run_type': 'aa_only', 'status': 'completed', 'stages': []})
    for name in ('lig.gro', 'lig.xtc', 'lig.tpr'):
        (run / 'stages/07_reference' / name).write_text(name)
    record = {
        'schema_version': 2, 'reference_eligible': True,
        'artifacts': {'lig.gro': 'stages/07_reference/lig.gro',
                      'run.sh': 'stages/07_reference/run.sh',
                      'lig.xtc': 'stages/07_reference/lig.xtc'},
        'sha256': {'stages/07_reference/lig.gro': 'a', 'stages/07_reference/lig.xtc': 'b',
                   'stages/07_reference/lig.tpr': 'c', 'stages/07_reference/run.sh': 'd',
                   'stages/07_reference/helper.py': 'e'},
        'molecule_snapshot': {'metadata': {'name': 'DDM'}},
    }
    files.atomic_json(run / 'stages/07_reference/reference.json', record)
    return tmp_path, run, record


def record_of(run):
    return json.loads((run / 'stages/07_reference/reference.json').read_text())


def test_a_dry_run_reports_the_repair_and_writes_nothing(world):
    workspace, run, original = world

    entries = repair.plan(workspace)

    assert [entry['status'] for entry in entries] == ['repair']
    assert set(entries[0]['removed']) == {'stages/07_reference/run.sh', 'stages/07_reference/helper.py'}
    assert record_of(run) == original
    assert not (workspace / repair.BACKUP).exists()


def test_apply_drops_only_the_absent_launchers_and_stamps_the_edition(world):
    workspace, run, original = world

    repair.apply(repair.plan(workspace), workspace)
    repaired = record_of(run)

    assert repaired['edition'] == references.EDITION and repaired['molecule'] == 'DDM'
    assert 'stages/07_reference/run.sh' not in repaired['sha256']
    assert 'stages/07_reference/helper.py' not in repaired['sha256']
    assert 'run.sh' not in repaired['artifacts'] and repaired['artifacts']['lig.xtc']
    assert {'stages/07_reference/lig.gro', 'stages/07_reference/lig.xtc',
            'stages/07_reference/lig.tpr'} <= set(repaired['sha256'])
    # The record itself says what left it and keeps the map entries it dropped.
    notes = {entry['name']: entry for entry in repaired['repaired']}
    assert set(notes) == {'stages/07_reference/run.sh', 'stages/07_reference/helper.py'}
    assert notes['stages/07_reference/run.sh']['artifacts'] == {
        'run.sh': 'stages/07_reference/run.sh'}
    assert notes['stages/07_reference/run.sh']['sha256'] == {'stages/07_reference/run.sh': 'd'}
    assert all(entry['note'].startswith('removed at ') and
               entry['note'].endswith('a copied launcher is not used by layout 4')
               for entry in notes.values())
    # The original is in the ledger, and the repaired record resolves by edition.
    ledger = json.loads((workspace / repair.BACKUP).read_text())
    assert [entry['original'] for entry in ledger['runs']] == [original]
    assert references.resolve(workspace / 'runs', RUN, expected={'edition': 1})[1]['edition'] == 1
    # A second pass has nothing to do.
    assert [entry['status'] for entry in repair.plan(workspace)] == ['unchanged']
    assert repair.apply(repair.plan(workspace), workspace) == []


def test_a_digest_is_not_a_reference_pin(world):
    """The repaired record is pinned by its edition; the digest spellings a legacy attachment carried are refused."""
    workspace, run, _ = world
    repair.apply(repair.plan(workspace), workspace)
    record = run / 'stages/07_reference/reference.json'

    with pytest.raises(ValueError, match='must be an edition'):
        references.verify(run, files.sha256(record))
    with pytest.raises(ValueError, match='must be an edition'):
        references.verify(run, {'stages/07_reference/lig.xtc': 'b'})


def test_a_launcher_that_is_present_is_kept(world):
    workspace, run, _ = world
    (run / 'stages/07_reference/run.sh').write_text('#!/bin/bash\n')
    (run / 'stages/07_reference/helper.py').write_text('print(1)\n')

    repair.apply(repair.plan(workspace), workspace)
    repaired = record_of(run)

    assert 'stages/07_reference/run.sh' in repaired['sha256']
    assert 'stages/07_reference/helper.py' in repaired['sha256']
    assert 'repaired' not in repaired


def test_a_missing_non_launcher_refuses_the_run_and_writes_nothing(world):
    workspace, run, original = world
    (run / 'stages/07_reference/lig.xtc').unlink()

    entries = repair.plan(workspace)

    assert entries[0]['status'] == 'refused' and 'non-launcher' in entries[0]['reason']
    with pytest.raises(ValueError, match='writes nothing'):
        repair.apply(entries, workspace)
    assert record_of(run) == original and not (workspace / repair.BACKUP).exists()


def test_rollback_restores_the_original_record(world):
    workspace, run, original = world
    repair.apply(repair.plan(workspace), workspace)
    assert record_of(run)['edition'] == references.EDITION

    assert repair.rollback(workspace) == 1

    assert record_of(run) == original
    assert [entry['status'] for entry in repair.plan(workspace)] == ['repair']
    assert repair.rollback(workspace / 'absent-workspace') is None


def test_main_is_a_dry_run_until_apply(world):
    workspace, run, original = world

    assert repair.main(['--workspace', str(workspace)]) == 0
    assert record_of(run) == original and not (workspace / repair.BACKUP).exists()
    assert repair.main(['--workspace', str(workspace), '--apply']) == 0
    assert record_of(run)['edition'] == references.EDITION
    assert repair.main(['--workspace', str(workspace), '--rollback']) == 0
    assert record_of(run) == original
