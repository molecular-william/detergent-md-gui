"""The pure units behind `pdc-structure`: the xvg reader, the sampling bound and the shape arithmetic.

Nothing here opens a trajectory or runs GROMACS. The numbers are chosen so a reader can check them by hand, and the
report's required fields are pinned so a producer edit cannot quietly drop one.
"""
from __future__ import annotations

import numpy as np
from detergent_pdc.analysis.runs import structure

REQUIRED = ('kind', 'schema_version', 'leg', 'sampling', 'micelle', 'shape_nm', 'aggregation', 'rdf',
            'contacts', 'method', 'caveats', 'scientifically_validated', 'protein_present')


def test_xvg_columns_are_labelled_by_their_own_legend_not_by_request_order(tmp_path):
    """`gmx rdf` and `gmx gyrate` write their columns in their own order; the legend is the only label."""
    path = tmp_path / 'out.xvg'
    path.write_text('\n'.join([
        '# comment', '@ title "Rg"', '@ s0 legend "Rg"', '@ s1 legend "Rg/sX/N"', '@ s2 legend "Rg/sZ/N"',
        '0.0 1.5 1.1 0.9', '10.0 1.6 1.2 0.8', '']))
    x, columns = structure.parse_xvg(path)

    assert x == [0.0, 10.0]
    assert list(columns) == ['Rg', 'Rg/sX/N', 'Rg/sZ/N']
    assert columns['Rg'] == [1.5, 1.6]
    assert columns['Rg/sZ/N'] == [0.9, 0.8]


def test_xvg_without_legends_keeps_a_positional_name_rather_than_losing_the_column(tmp_path):
    path = tmp_path / 'plain.xvg'
    path.write_text('0 1 2\n1 3 4\n')
    _, columns = structure.parse_xvg(path)

    assert columns == {'column2': [1.0, 3.0], 'column3': [2.0, 4.0]}


def test_the_existing_frame_bound_survives_every_length():
    """At most 200 frames, stride `ceil(frames / 200)`, exactly as `trajectory_overview` does it."""
    assert structure.stride_for(200) == 1
    assert structure.stride_for(201) == 2
    assert structure.stride_for(45001) == 226
    for frames in (1, 199, 200, 201, 4_501, 45_001, 100_000):
        stride = structure.stride_for(frames)
        assert len(range(0, frames, stride)) <= structure.MAX_FRAMES


def test_the_sample_is_extracted_with_the_stride_converted_to_the_files_own_step():
    arguments, stride = structure.sample_arguments(45_001, 0.0, 20.0)
    assert stride == 226
    assert arguments == ['-dt', '4520']
    # A file whose first frame is not t = 0, or that states no step, keeps the exact frame stride.
    assert structure.sample_arguments(45_001, 100.0, 20.0)[0] == ['-skip', '226']
    assert structure.sample_arguments(4_501, 0.0, None)[0] == ['-skip', '23']


def test_gyration_tensor_is_ordered_and_scales_with_the_square_of_the_coordinates():
    cube = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=float)
    eigenvalues = structure.gyration_tensor(cube)

    assert eigenvalues[0] >= eigenvalues[1] >= eigenvalues[2]
    assert np.allclose(eigenvalues, [1.0, 1.0, 1.0])
    assert np.allclose(structure.gyration_tensor(cube * 3), np.array(eigenvalues) * 9)
    # The shape ratios do not move when the whole point set is scaled.
    assert np.isclose(structure.shape_metrics(eigenvalues)['relative_shape_anisotropy'],
                      structure.shape_metrics(structure.gyration_tensor(cube * 3))['relative_shape_anisotropy'])


def test_shape_metrics_zero_on_a_sphere_and_one_on_a_line():
    sphere = structure.shape_metrics([1.0, 1.0, 1.0])
    line = structure.shape_metrics([2 / 3, 0.0, 0.0])

    assert np.isclose(sphere['asphericity_nm2'], 0.0)
    assert np.isclose(sphere['relative_shape_anisotropy'], 0.0)
    assert np.isclose(line['asphericity_nm2'], 2 / 3)
    assert np.isclose(line['relative_shape_anisotropy'], 1.0)


def test_unwrap_brings_a_molecule_across_the_box_face_back_to_its_neighbour():
    """The measured failure: one micelle read as fragments because it straddles the periodic boundary."""
    box = np.array([10.0, 10.0, 10.0])
    positions = np.array([[9.5, 5.0, 5.0], [0.2, 5.0, 5.0]])
    molecules = [np.array([0]), np.array([1])]

    moved = structure.unwrap(molecules, positions, box)

    assert np.isclose(moved[1, 0], 10.2)
    assert np.isclose(moved[0, 0], 9.5)


def test_unwrap_does_not_move_a_molecule_already_beside_its_neighbour():
    box = np.array([10.0, 10.0, 10.0])
    positions = np.array([[5.0, 5.0, 5.0], [5.5, 5.0, 5.0]])

    moved = structure.unwrap([np.array([0]), np.array([1])], positions, box)

    assert np.allclose(moved, positions)


def test_first_peak_is_the_first_interior_maximum_and_falls_back_to_the_global_one():
    assert structure.first_peak([0, 1, 2, 3], [0, 0.5, 2.0, 0.4]) == (2.0, 2.0)
    assert structure.first_peak([0, 1, 2], [0.1, 0.2, 0.3]) == (2.0, 0.3)
    assert structure.first_peak([], []) == (None, None)


def test_the_report_carries_every_field_the_schema_names_and_never_a_validation_label():
    report = structure.build_report(
        leg={'name': 'CG extension MD'}, sampling={'frames_sampled': 200}, micelle={'contact_nm': 0.6},
        shape={'rg': {'mean': 2.4}}, aggregation=None, rdf=[], contacts=None, commands=[],
        caveats=['a caveat'], protein_present=True)

    assert set(REQUIRED) <= set(report)
    assert report['kind'] == 'pdc-structure'
    assert report['schema_version'] == 1
    assert report['scientifically_validated'] is False
    assert report['caveats'] == ['a caveat']
    assert 'gmx gyrate' in report['method'] and 'gmx rdf' in report['method']


def test_the_sample_is_clustered_on_the_detergent_before_any_tool_reads_it():
    """Whole molecules are not enough: on `d17de0a443f3` the stored sample's Rg was 6.48 nm and the clustered one 1.96 nm.

    The two answers to trjconv's prompts are the detergent (group 1, built second) and everything (group 0), and the
    file every tool reads is the clustered one, never the raw extraction.
    """
    steps, arguments, stdin = structure.cluster_steps('run.tpr', 'DDM')

    assert steps == [['select', '-s', 'run.tpr', '-select', 'all', 'resname DDM', '-on', 'cluster.ndx']]
    assert arguments[:2] == ['trjconv', '-s'] and arguments[-2:] == ['-pbc', 'cluster']
    assert arguments[arguments.index('-f') + 1] == structure.RAW_SAMPLE
    assert arguments[arguments.index('-o') + 1] == structure.SAMPLE
    assert structure.SAMPLE != structure.RAW_SAMPLE
    assert stdin == '1\n0\n', 'cluster group is the detergent, the output group is everything'


def test_a_failed_gmx_call_reports_the_reason_not_the_mpi_shutdown_banner():
    """One live cluster run failed and the producer reported only MPI's boilerplate; the real line was above it."""
    output = ('Clustering iteration 80 of 80...\n'
              'Error in user input:\n'
              'Selection 1 has no atoms in this frame\n'
              '\n--------------------------------------------------------------------------\n'
              'MPI_ABORT was invoked on rank 0\n'
              'You may or may not see output from other processes\n'
              '-----------------------------------------------------\n')

    tail = structure.error_tail(output)

    assert 'has no atoms in this frame' in tail, tail
    assert 'MPI_ABORT' not in tail and 'You may or may not' not in tail, tail


def test_an_empty_output_still_says_something():
    assert structure.error_tail('') == 'no output'
