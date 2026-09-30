"""The snapshot series endpoint: the merge across stages, and the two ways a path can fail to be a snapshot.

The merge is the part worth testing: the snapshots live in the stage that took them (so a resumed stage re-derives
its own), and a reader wants one series. The path guard is the part worth attacking: a snapshot is a file inside the
run and nothing else.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.web.routes.pdc import snapshot_entries, snapshot_file


def index(stage: Path, entries) -> Path:
    stage.mkdir(parents=True, exist_ok=True)
    (stage / 'snapshots.json').write_text(json.dumps({'snapshots': entries,
                                                      'note': 'derived: a resumed run re-derives these'}))
    return stage


def test_the_series_is_every_stages_index_merged_with_the_placement_first(tmp_path):
    index(tmp_path / '1_system', [{'name': 'placement', 'time_ps': None, 'pdb': 'snapshots/placement.pdb',
                                   'verdict': None}])
    index(tmp_path / '2_assessment', [
        {'name': 'assessment_100ps', 'time_ps': 100.0, 'pdb': 'snapshots/assessment_100ps.pdb',
         'verdict': {'verdict': True}},
        {'name': '2_assessment', 'time_ps': 100000.0, 'pdb': 'snapshots/2_assessment.pdb',
         'verdict': {'verdict': False}}])

    entries = snapshot_entries(tmp_path)

    assert [entry['name'] for entry in entries] == ['placement', 'assessment_100ps', '2_assessment']
    assert [entry['stage'] for entry in entries] == ['1_system', '2_assessment', '2_assessment']
    assert entries[0]['time_ps'] is None, 'the placement is a moment without a time'
    assert entries[2]['verdict'] == {'verdict': False}, 'each entry keeps the numbers of its own moment'


def test_an_index_that_is_not_json_is_skipped_rather_than_failing_the_panel(tmp_path):
    (tmp_path / '2_assessment').mkdir()
    (tmp_path / '2_assessment' / 'snapshots.json').write_text('{not json')
    index(tmp_path / '3_assessment', [{'name': 'kept', 'time_ps': 1.0, 'pdb': 'snapshots/kept.pdb'}])

    assert [entry['name'] for entry in snapshot_entries(tmp_path)] == ['kept']


def test_a_snapshot_is_a_pdb_inside_the_run(tmp_path):
    (tmp_path / 'snapshots').mkdir()
    (tmp_path / 'snapshots' / 'placement.pdb').write_text('END\n')

    assert snapshot_file(tmp_path, 'snapshots/placement.pdb').is_file()


@pytest.mark.parametrize('relative', ['../../etc/passwd', '../outside.pdb', 'snapshots/nothing.pdb',
                                      'snapshots/notes.txt'])
def test_anything_that_is_not_a_snapshot_inside_the_run_is_refused(tmp_path, relative):
    (tmp_path / 'snapshots').mkdir()
    (tmp_path / 'snapshots' / 'notes.txt').write_text('not a picture\n')
    (tmp_path.parent / 'outside.pdb').write_text('END\n')

    with pytest.raises(Exception) as refusal:
        snapshot_file(tmp_path, relative)
    assert '404' in str(refusal.value) or 'not found' in str(refusal.value).lower()
