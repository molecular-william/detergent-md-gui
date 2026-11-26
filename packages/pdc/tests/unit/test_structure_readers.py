"""The shared file readers `pdc-structure` now uses, pinned against the copies they replaced.

The goldens below were captured from the pre-refactor `structure.parse_xvg`, `structure.stride_for`,
`trajectory_overview._chosen`, `trajectory_overview._minimum_image` and `segments._manifest` on the fixtures in
this file: same labels, same column order, same selected files, same refusals. They are the parity evidence for the
refactor, so a change to a shared reader is a change to this module's published record.
"""
from __future__ import annotations

import numpy as np
import pytest
from dashboard.analysis.runs import readers
from detergent_pdc.analysis.runs import structure


def _xvg(path, text):
    path.write_text(text)
    return path


def test_the_golden_columns_are_the_labels_the_pre_refactor_reader_returned(tmp_path):
    path = _xvg(tmp_path / 'out.xvg', '\n'.join([
        '# comment', '@ title "Rg"', '@ s0 legend "Rg"', '@ s1 legend "Rg/sX/N"', '@ s2 legend "Rg/sZ/N"',
        '0.0 1.5 1.1 0.9', '10.0 1.6 1.2 0.8', '']))

    labels, times, columns = readers.xvg_columns(path)
    x, data = structure.parse_xvg(path)

    assert labels == ['Rg', 'Rg/sX/N', 'Rg/sZ/N']
    assert list(times) == [0.0, 10.0]
    assert [list(column) for column in columns] == [[1.5, 1.6], [1.1, 1.2], [0.9, 0.8]]
    assert x == [0.0, 10.0]
    assert data == {'Rg': [1.5, 1.6], 'Rg/sX/N': [1.1, 1.2], 'Rg/sZ/N': [0.9, 0.8]}


def test_a_column_without_a_legend_keeps_its_positional_name(tmp_path):
    path = _xvg(tmp_path / 'plain.xvg', '0 1 2\n1 3 4\n')

    assert structure.parse_xvg(path) == ([0.0, 1.0], {'column2': [1.0, 3.0], 'column3': [2.0, 4.0]})
    labels, _, columns = readers.xvg_columns(path)
    assert [list(column) for column in columns] == [[1.0, 3.0], [2.0, 4.0]]
    assert labels == ['column2', 'column3']


def test_two_columns_sharing_one_legend_still_interleave_row_major(tmp_path):
    """The golden from the old dict-append reader: both columns merge under one key, row by row."""
    path = _xvg(tmp_path / 'dup.xvg', '@ s0 legend "A"\n@ s1 legend "A"\n0 1 2\n1 3 4\n')

    assert structure.parse_xvg(path) == ([0.0, 1.0], {'A': [1.0, 2.0, 3.0, 4.0]})
    labels, times, columns = readers.xvg_columns(path)
    assert labels == ['A', 'A']
    assert list(times) == [0.0, 1.0]
    assert [list(column) for column in columns] == [[1.0, 3.0], [2.0, 4.0]]


def test_the_frame_bound_is_the_pre_refactor_stride_table(tmp_path):
    assert (structure.MAX_FRAMES, readers.MAX_FRAMES) == (400, 400)
    assert [structure.stride_for(frames) for frames in (1, 199, 200, 201, 45001, 100000)] == [1, 1, 1, 1, 113, 250]
    with pytest.raises(ValueError, match='no frames'):
        structure.stride_for(0)
    with pytest.raises(ValueError, match='no frames'):
        readers.frame_stride(0)


def test_the_selected_leg_is_the_largest_trajectory_and_its_run_structure(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'a.xtc').write_bytes(b'a' * 10)
    (work / 'b.xtc').write_bytes(b'b' * 20)
    (work / 'x.gro').write_text('x')
    (work / 'run.gro').write_text('run')
    (work / 'system.gro').write_text('sys')

    trajectory, sibling = readers.chosen_trajectory(work)
    assert (trajectory.name, sibling.name) == ('b.xtc', 'run.gro')
    assert structure._leg(work)[0].name == 'b.xtc'


def test_the_pdc_leg_excludes_the_published_sample(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'leg.xtc').write_bytes(b'leg')
    (work / structure.SAMPLE).write_bytes(b'x' * 100)
    (work / 'run.gro').write_text('run')

    assert readers.chosen_trajectory(work)[0].name == structure.SAMPLE
    assert structure._leg(work)[0].name == 'leg.xtc'


def test_the_refusals_keep_the_pre_refactor_types_and_words(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    with pytest.raises(readers.MissingTrajectory):
        readers.chosen_trajectory(empty)
    with pytest.raises(structure.layout.NoTrajectory, match='this run offers no trajectory to sample'):
        structure._leg(empty)

    bare = tmp_path / 'bare'
    bare.mkdir()
    (bare / 'c.xtc').write_bytes(b'c')
    with pytest.raises(readers.MissingStructure) as missing:
        readers.chosen_trajectory(bare)
    assert missing.value.trajectory.name == 'c.xtc'
    with pytest.raises(ValueError, match='so its beads cannot be read'):
        structure._leg(bare)


def test_minimum_image_is_the_golden_vector():
    assert np.array_equal(readers.minimum_image(np.array([2.0]), np.array([1.5])), np.array([0.5]))
    assert np.allclose(readers.minimum_image(np.array([0.1, 1.4]), np.array([1.0, 1.0])),
                       np.array([0.1, 0.4]))


def test_the_manifest_is_the_golden_record_and_the_stages_parent_fallback(tmp_path):
    (tmp_path / 'manifest.json').write_text('{"run_type": "pdc", "n": 1}')
    work = tmp_path / 'work'
    work.mkdir()

    assert readers.run_manifest(tmp_path) == {'run_type': 'pdc', 'n': 1}
    assert structure._manifest(tmp_path) == {'run_type': 'pdc', 'n': 1}
    assert readers.run_manifest(work) == {}
    assert structure._manifest(work) == {}
    stages = tmp_path / 'stages'
    stages.mkdir()
    assert readers.run_manifest(stages) == {'run_type': 'pdc', 'n': 1}
