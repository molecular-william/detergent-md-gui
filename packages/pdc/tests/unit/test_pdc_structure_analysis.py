"""The pure units behind `pdc-structure`: the xvg reader, the sampling bound, the shape arithmetic and the v2 contract.

Nothing here opens a trajectory or runs GROMACS; the one GROMACS-shaped input is a written XVG. The numbers are
chosen so a reader can check them by hand, the payload ranges are the plan's, and the report's required fields and
the five per-metric PNGs are pinned so a producer edit cannot quietly drop one.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from detergent_pdc.analysis.runs import structure

REQUIRED = ('kind', 'schema_version', 'leg', 'sampling', 'thresholds', 'micelle', 'shape_nm', 'aggregation', 'rdf',
            'contacts', 'figures', 'method', 'caveats', 'scientifically_validated', 'protein_present')


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
    """At most 400 frames, stride `ceil(frames / 400)`, exactly as `trajectory_overview` does it."""
    assert structure.stride_for(200) == 1
    assert structure.stride_for(201) == 1
    assert structure.stride_for(45001) == 113
    for frames in (1, 199, 200, 201, 4_501, 45_001, 100_000):
        stride = structure.stride_for(frames)
        assert len(range(0, frames, stride)) <= structure.MAX_FRAMES


def test_the_sample_is_extracted_with_the_stride_converted_to_the_files_own_step():
    arguments, stride = structure.sample_arguments(45_001, 0.0, 20.0)
    assert stride == 113
    assert arguments == ['-dt', '2260']
    # A file whose first frame is not t = 0, or that states no step, keeps the exact frame stride.
    assert structure.sample_arguments(45_001, 100.0, 20.0)[0] == ['-skip', '113']
    assert structure.sample_arguments(4_501, 0.0, None)[0] == ['-skip', '12']


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


def test_strongest_peak_ignores_a_short_range_depletion_bump():
    """The receptor-centre curve can have a below-bulk bump first; the shell is the highest point."""
    assert structure.strongest_peak([0, 1, 2, 3], [0, 0.3, 2.0, 0.4]) == (2.0, 2.0)
    assert structure.strongest_peak([0, 1, 2, 3], [0.2, 0.3, 0.1, 0.05]) == (1.0, 0.3)
    assert structure.strongest_peak([], []) == (None, None)


def test_the_report_carries_every_field_the_schema_names_and_never_a_validation_label():
    thresholds = {'rdf_bin_nm': 0.05, 'rdf_rmax_nm': 2.0, 'contact_nm': 0.6, 'water_cutoff_nm': 0.6}
    report = structure.build_report(
        leg={'name': 'CG extension MD'}, sampling={'frames_sampled': 200}, thresholds=thresholds,
        micelle={'contact_nm': 0.6}, shape={'rg': {'mean': 2.4}}, aggregation=None, rdf=[],
        contacts={'groups': []}, figures=list(structure.FIGURES), commands=[], caveats=['a caveat'],
        protein_present=True)

    assert set(REQUIRED) <= set(report), set(REQUIRED) - set(report)
    assert report['kind'] == 'pdc-structure'
    assert report['schema_version'] == 2
    assert report['thresholds'] == thresholds
    assert report['figures'] == list(structure.FIGURES)
    assert report['scientifically_validated'] is False
    assert report['caveats'] == ['a caveat']
    assert 'gmx gyrate' in report['method'] and 'gmx rdf' in report['method']


def test_the_threshold_defaults_and_ranges_are_the_plan():
    assert (structure.BIN_WIDTH_NM, structure.R_MAX_NM, structure.CONTACT_NM, structure.WATER_CUTOFF_NM) \
        == (0.05, 8.0, 0.6, 0.6)
    assert structure.THRESHOLD_RANGES == {'rdf_bin_nm': (0.01, 0.20), 'rdf_rmax_nm': (0.5, 8.0),
                                         'contact_nm': (0.2, 1.5), 'water_cutoff_nm': (0.2, 1.5)}
    assert structure.FIGURES == ('pdc-structure-rdf.png', 'pdc-structure-contacts-protein.png',
                                 'pdc-structure-contacts-water.png', 'pdc-structure-shape.png',
                                 'pdc-structure-aggregation.png')


def test_the_payload_accepts_blank_fields_and_returns_the_given_values_as_numbers():
    """A blank field means the default, so it is dropped rather than stored as a second spelling of it."""
    assert structure.validate_payload(None) == {}
    assert structure.validate_payload({}) == {}
    assert structure.validate_payload({'contact_nm': None, 'water_cutoff_nm': '  '}) == {}
    assert structure.validate_payload({'contact_nm': '0.65', 'rdf_bin_nm': 0.1}) \
        == {'contact_nm': 0.65, 'rdf_bin_nm': 0.1}


def test_the_payload_refuses_a_value_beyond_its_range_an_unknown_key_or_a_non_number():
    for bad in ({'rdf_bin_nm': 0.001}, {'rdf_bin_nm': 0.5}, {'rdf_rmax_nm': 0.4}, {'rdf_rmax_nm': 8.5},
                {'contact_nm': 0.1}, {'contact_nm': 2.0}, {'water_cutoff_nm': 0.1},
                {'water_cutoff_nm': 2.0}, {'nonsense': 1}, {'contact_nm': 'abc'},
                {'contact_nm': math.nan}, {'contact_nm': math.inf}):
        with pytest.raises(ValueError):
            structure.validate_payload(bad)
    assert structure.validate_payload({'rdf_rmax_nm': 8.0}) == {'rdf_rmax_nm': 8.0}


def test_the_thresholds_use_the_run_own_contact_as_the_default():
    assert structure.resolve_thresholds({}, 0.75) == {'rdf_bin_nm': 0.05, 'rdf_rmax_nm': 8.0,
                                                      'contact_nm': 0.75, 'water_cutoff_nm': 0.6}
    given = structure.resolve_thresholds({'contact_nm': 0.8, 'rdf_rmax_nm': 1.5}, 0.6)
    assert given['contact_nm'] == 0.8 and given['rdf_rmax_nm'] == 1.5
    assert given['rdf_bin_nm'] == 0.05 and given['water_cutoff_nm'] == 0.6


def test_the_effective_rmax_is_cut_to_half_the_shortest_box_edge():
    assert structure.effective_rmax(2.0, [5.0, 6.0, 7.0]) == 2.0
    assert structure.effective_rmax(2.0, [3.0, 6.0, 7.0]) == 1.5
    # A requested value below the box limit is not raised to it.
    assert structure.effective_rmax(1.2, [3.0, 6.0, 7.0]) == 1.2
    assert structure.effective_rmax(2.0, []) == 2.0
    assert structure.effective_rmax(2.0, [0.0, 6.0, 7.0]) == 2.0


def test_the_rdf_pairs_report_protein_tail_between_the_head_curve_and_the_packing_curves():
    criterion = {'protein_present': True, 'detergent_residue': 'NG', 'tail_beads': ['T1', 'T2']}

    pairs = structure.rdf_pairs(criterion, head_present=True)

    assert [(first, second) for first, second, *_rest in pairs] == [
        ('protein', 'head'), ('protein', 'tail'), ('head', 'head'), ('tail', 'tail')]
    assert [excl for *_rest, excl in pairs] == [False, False, True, True]
    # The two protein rows use the receptor's centre of mass as one reference point; the packing rows keep a group.
    assert pairs[0][2].startswith('com of ') and pairs[1][2].startswith('com of ')
    assert pairs[2][2] == 'resname NG and not name T1 T2'
    assert 'name T1 T2' in pairs[1][3] and 'not name T1 T2' in pairs[0][3]


def test_an_unmeasurable_rdf_pair_is_absent_rather_than_reported_as_zero():
    no_protein = {'protein_present': False, 'detergent_residue': 'NG', 'tail_beads': ['T1']}
    assert [(first, second) for first, second, *_rest in structure.rdf_pairs(no_protein, head_present=True)] \
        == [('head', 'head'), ('tail', 'tail')]

    no_tails = {'protein_present': True, 'detergent_residue': 'NG', 'tail_beads': []}
    assert [(first, second) for first, second, *_rest in structure.rdf_pairs(no_tails, head_present=True)] \
        == [('protein', 'head'), ('head', 'head')]

    all_tail = {'protein_present': True, 'detergent_residue': 'NG', 'tail_beads': ['T1']}
    assert [(first, second) for first, second, *_rest in structure.rdf_pairs(all_tail, head_present=False)] \
        == [('protein', 'tail'), ('tail', 'tail')]


def test_the_four_contact_groups_stay_four_rows_and_null_what_the_run_cannot_measure():
    no_protein = {'protein_present': False, 'detergent_residue': 'NG', 'tail_beads': ['T1']}
    plan = structure.contact_group_plan(no_protein, head_present=True, water_present=True)

    assert [(group['first'], group['second']) for group in plan] == [
        ('protein', 'head'), ('protein', 'tail'), ('water', 'head'), ('water', 'tail')]
    assert [group['available'] for group in plan] == [False, False, True, True]
    assert plan[0]['cutoff_key'] == 'contact_nm' and plan[2]['cutoff_key'] == 'water_cutoff_nm'
    # Water is `resname W` only: ions are not water.
    assert plan[2]['first_selection'] == structure._water_selection() == 'resname W'

    no_water = structure.contact_group_plan({'protein_present': True, 'detergent_residue': 'NG',
                                             'tail_beads': ['T1']}, head_present=True, water_present=False)
    assert [group['available'] for group in no_water] == [True, True, False, False]

    no_tails = structure.contact_group_plan({'protein_present': True, 'detergent_residue': 'NG',
                                             'tail_beads': []}, head_present=True, water_present=True)
    assert [group['available'] for group in no_tails] == [True, False, True, False]


def test_a_contact_reading_carries_the_mean_sem_and_the_per_frame_series(tmp_path):
    path = tmp_path / 'numcont.xvg'
    path.write_text('\n'.join(['@ s0 legend "Protein-Head"', '0.0 2.0', '10.0 4.0', '20.0 6.0', '']))

    entry = structure._contact_reading(path, 0.6, 'protein', 'head', 'a definition')

    assert entry['first'] == 'protein' and entry['second'] == 'head'
    assert entry['cutoff_nm'] == 0.6 and entry['definition'] == 'a definition'
    assert entry['mean'] == 4.0
    assert entry['sem'] == round(2.0 / math.sqrt(3), 3)
    assert entry['series']['time_ns'] == [0.0, 0.01, 0.02]
    assert entry['series']['contacts'] == [2.0, 4.0, 6.0]


def _figure_data():
    """Small valid series for every plotted metric: three sampled frames at 0.0, 0.5 and 1.0 ns."""
    times = [0.0, 0.5, 1.0]
    rdf = [
        {'first': 'protein', 'second': 'head', 'r_nm': [0.0, 0.1, 0.2], 'g': [0.0, 1.5, 0.8],
         'first_peak_nm': 0.1, 'first_peak_g': 1.5},
        {'first': 'protein', 'second': 'tail', 'r_nm': [0.0, 0.1, 0.2], 'g': [0.0, 2.0, 0.9],
         'first_peak_nm': 0.1, 'first_peak_g': 2.0},
        {'first': 'head', 'second': 'head', 'r_nm': [0.0, 0.1, 0.2], 'g': [0.0, 2.5, 1.0],
         'first_peak_nm': 0.1, 'first_peak_g': 2.5},
        {'first': 'tail', 'second': 'tail', 'r_nm': [0.0, 0.1, 0.2], 'g': [0.0, 3.0, 1.1],
         'first_peak_nm': 0.1, 'first_peak_g': 3.0},
    ]
    groups = [
        {'first': 'protein', 'second': 'head', 'cutoff_nm': 0.6, 'mean': 200.0, 'sem': 5.0,
         'series': {'time_ns': times, 'contacts': [190.0, 205.0, 205.0]}, 'definition': 'a definition'},
        {'first': 'protein', 'second': 'tail', 'cutoff_nm': 0.6, 'mean': 300.0, 'sem': 8.0,
         'series': {'time_ns': times, 'contacts': [290.0, 300.0, 310.0]}, 'definition': 'a definition'},
        {'first': 'water', 'second': 'head', 'cutoff_nm': 0.6, 'mean': 1800.0, 'sem': 30.0,
         'series': {'time_ns': times, 'contacts': [1780.0, 1800.0, 1820.0]}, 'definition': 'a definition'},
        {'first': 'water', 'second': 'tail', 'cutoff_nm': 0.6, 'mean': 2400.0, 'sem': 40.0,
         'series': {'time_ns': times, 'contacts': [2380.0, 2400.0, 2420.0]}, 'definition': 'a definition'},
    ]
    shape = {
        'rg': {'mean': 5.4, 'series': {'time_ns': times, 'rg_nm': [5.3, 5.4, 5.5]}},
        'asphericity_nm2': {'mean': 0.28, 'series': {'time_ns': times, 'values': [0.27, 0.28, 0.29]}},
        'relative_shape_anisotropy': {'mean': 0.07, 'series': {'time_ns': times, 'values': [0.06, 0.07, 0.08]}},
    }
    aggregation = {'largest_mean': 151.0, 'free_mean': 4.0,
                   'series': {'time_ns': times, 'largest': [150, 151, 152], 'clusters': [2, 2, 2],
                              'free': [5, 4, 3]}}
    thresholds = {'rdf_bin_nm': 0.05, 'rdf_rmax_nm': 2.0, 'contact_nm': 0.6, 'water_cutoff_nm': 0.6}
    return rdf, groups, shape, aggregation, thresholds


def test_the_five_per_metric_figures_are_published_non_empty_and_named_as_the_record_says(tmp_path):
    rdf, groups, shape, aggregation, thresholds = _figure_data()

    names = structure.write_figures(tmp_path, rdf=rdf, contact_groups=groups, shape=shape,
                                    aggregation=aggregation, thresholds=thresholds, frames=3)

    assert names == list(structure.FIGURES)
    for name in names:
        path = tmp_path / name
        assert path.is_file(), name
        assert path.stat().st_size > 0, name
        assert path.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n', name


def test_a_figure_is_still_published_when_the_run_could_not_measure_that_metric(tmp_path):
    """A run with no protein and no aggregation still gets the named file: an absent picture is not a missing one."""
    rdf, _groups, shape, aggregation, thresholds = _figure_data()
    missing = [{'first': first, 'second': second, 'cutoff_nm': 0.6, 'mean': None, 'sem': None,
                'series': None, 'definition': 'a definition'}
               for first, second in (('protein', 'head'), ('protein', 'tail'),
                                     ('water', 'head'), ('water', 'tail'))]

    names = structure.write_figures(tmp_path, rdf=rdf, contact_groups=missing, shape=shape,
                                    aggregation=None, thresholds=thresholds, frames=3)

    assert names == list(structure.FIGURES)
    for name in names:
        assert (tmp_path / name).stat().st_size > 0, name


def _fake_gmx(monkeypatch):
    """Record the producer's GROMACS calls and write the XVG a real call would have written."""
    calls = []

    def invoke(gmx, commands, step, arguments, work, *, stdin=None, timeout=None):
        calls.append({'step': step, 'arguments': arguments, 'stdin': stdin})
        flag = '-o' if arguments[0] == 'rdf' else '-on'
        output = arguments[arguments.index(flag) + 1]
        times = (0.0, 10.0) if arguments[0] == 'mindist' else (0.0, 0.1, 0.2)
        values = (2.0, 4.0) if arguments[0] == 'mindist' else (0.0, 1.2, 0.5)
        legend = 'contacts' if arguments[0] == 'mindist' else 'g'
        path = work / output
        path.write_text('\n'.join([f'@ s0 legend "{legend}"']
                                  + [f'{time} {value}' for time, value in zip(times, values)] + ['']))
        if arguments[0] == 'mindist':
            # A real `mindist` writes its minimum distance and distance distribution too; the producer names them so
            # the call cannot leave GROMACS' default `mindist.xvg` and its `#mindist.xvg.N#` backups in the output.
            (work / arguments[arguments.index('-o') + 1]).write_text('distance\n')
            (work / arguments[arguments.index('-od') + 1]).write_text('distribution\n')
        return None

    monkeypatch.setattr(structure, '_invoke', invoke)
    return calls


def test_the_contact_groups_run_one_mindist_per_available_group_with_its_own_cutoff(tmp_path, monkeypatch):
    criterion = {'protein_present': True, 'detergent_residue': 'NG', 'tail_beads': ['T1']}
    plan = structure.contact_group_plan(criterion, head_present=True, water_present=True)
    thresholds = {'rdf_bin_nm': 0.05, 'rdf_rmax_nm': 2.0, 'contact_nm': 0.7, 'water_cutoff_nm': 0.5}
    calls = _fake_gmx(monkeypatch)
    source = tmp_path / 'run.tpr'
    source.write_text('')

    groups = structure._contact_groups(tmp_path, 'gmx', [], source, plan, thresholds)

    assert [(group['first'], group['second']) for group in groups] == [
        ('protein', 'head'), ('protein', 'tail'), ('water', 'head'), ('water', 'tail')]
    assert all(group['mean'] == 3.0 and group['sem'] == 1.0 for group in groups)
    assert [group['cutoff_nm'] for group in groups] == [0.7, 0.7, 0.5, 0.5]
    mindists = [call for call in calls if call['arguments'][0] == 'mindist']
    assert len(mindists) == 4
    assert [call['arguments'][call['arguments'].index('-d') + 1] for call in mindists] == ['0.7', '0.7', '0.5', '0.5']
    # Each call names its otherwise-default distance output, and the producer removes it so only the contact XVG is
    # published -- not `mindist.xvg` with one GROMACS `#mindist.xvg.N#` backup per group.
    assert all(call['arguments'][call['arguments'].index('-o') + 1] == structure.MINDIST_DISTANCE
               for call in mindists)
    assert all(call['arguments'][call['arguments'].index('-od') + 1] == structure.MINDIST_DISTRIBUTION
               for call in mindists)
    assert not (tmp_path / structure.MINDIST_DISTANCE).exists()
    assert not (tmp_path / structure.MINDIST_DISTRIBUTION).exists()
    assert not list(tmp_path.glob('#mindist*')), 'no GROMACS backup of the default output is left behind'
    # The selections are staged once; each mindist answers its two prompts with group numbers.
    assert len([call for call in calls if call['arguments'][0] == 'select']) == 1
    assert mindists[0]['stdin'] == '0\n1\n' and mindists[2]['stdin'] == '3\n1\n'


def test_a_periodic_contact_count_matches_a_brute_force_minimum_image_count():
    """The KD-tree pass counts the same pairs as `gmx mindist -on`, including pairs across a box face.

    The two water groups were 52 s of a 108 s producer run; the same counts from this helper took about 2 s, and on
    the run's own 199-frame sample all four groups and the pooled count matched GROMACS exactly.
    """
    box = np.array([2.0, 2.0, 2.0])
    first = np.array([[0.1, 0.1, 0.1], [1.9, 0.1, 0.1], [0.5, 0.5, 0.5]])
    second = np.array([[1.95, 0.1, 0.1], [0.15, 0.1, 0.1], [1.4, 0.1, 0.1]])

    # (0, 0) and (0, 1) are across/inside the boundary; (1, 0) is the mirror image of (0, 0).
    assert structure.periodic_contact_counts(first, second, box, 0.2) == 3
    assert structure.periodic_contact_counts(first, second, box, 0.01) == 0
    assert structure.periodic_contact_counts(first[:1], second, box, 0.2) == 2
    assert structure.periodic_contact_counts(np.empty((0, 3)), second, box, 0.2) == 0


def test_the_water_groups_use_the_measured_series_and_only_the_protein_groups_run_gmx(tmp_path, monkeypatch):
    """The measured water counts are the group entries; GROMACS is not asked for them again."""
    criterion = {'protein_present': True, 'detergent_residue': 'NG', 'tail_beads': ['T1']}
    plan = structure.contact_group_plan(criterion, head_present=True, water_present=True)
    thresholds = {'rdf_bin_nm': 0.05, 'rdf_rmax_nm': 2.0, 'contact_nm': 0.7, 'water_cutoff_nm': 0.5}
    calls = _fake_gmx(monkeypatch)
    source = tmp_path / 'run.tpr'
    source.write_text('')

    groups = structure._contact_groups(
        tmp_path, 'gmx', [], source, plan, thresholds,
        water_series={('water', 'head'): [10, 20], ('water', 'tail'): [1, 2]}, water_times=[0.0, 10.0])

    mindists = [call for call in calls if call['arguments'][0] == 'mindist']
    assert [call['step'] for call in mindists] == ['gmx mindist (protein–head)', 'gmx mindist (protein–tail)']
    water = {(group['first'], group['second']): group for group in groups if group['first'] == 'water'}
    assert water[('water', 'head')]['mean'] == 15.0
    assert water[('water', 'head')]['series'] == {'time_ns': [0.0, 10.0], 'contacts': [10.0, 20.0]}
    assert water[('water', 'tail')]['mean'] == 1.5
    assert 'KD-tree' in water[('water', 'head')]['tool']
    assert water[('water', 'head')]['definition'].startswith('W beads within the cutoff of a head bead')


def test_an_unavailable_contact_group_is_reported_with_null_numbers_not_a_zero(tmp_path, monkeypatch):
    criterion = {'protein_present': False, 'detergent_residue': 'NG', 'tail_beads': ['T1']}
    plan = structure.contact_group_plan(criterion, head_present=True, water_present=False)
    thresholds = {'rdf_bin_nm': 0.05, 'rdf_rmax_nm': 2.0, 'contact_nm': 0.6, 'water_cutoff_nm': 0.6}

    source = tmp_path / 'run.tpr'
    source.write_text('')
    groups = structure._contact_groups(tmp_path, 'gmx', [], source, plan, thresholds)

    assert all(group['mean'] is None and group['sem'] is None and group['series'] is None for group in groups)
    assert [group['cutoff_nm'] for group in groups] == [0.6] * 4


def test_the_rdf_entries_include_protein_tail_and_use_the_payload_interval(tmp_path, monkeypatch):
    criterion = {'protein_present': True, 'detergent_residue': 'NG', 'tail_beads': ['T1']}
    thresholds = {'rdf_bin_nm': 0.1, 'rdf_rmax_nm': 1.5, 'contact_nm': 0.6, 'water_cutoff_nm': 0.6}
    calls = _fake_gmx(monkeypatch)
    source = tmp_path / 'run.tpr'
    source.write_text('')

    entries = structure._rdf_entries(tmp_path, 'gmx', [], source, criterion, thresholds, head_present=True)

    assert [(entry['first'], entry['second']) for entry in entries] == [
        ('protein', 'head'), ('protein', 'tail'), ('head', 'head'), ('tail', 'tail')]
    assert [entry['reference'] for entry in entries] == ['com', 'com', 'group', 'group']
    assert [entry['peak_kind'] for entry in entries] == [
        'strongest_shell', 'strongest_shell', 'first_peak', 'first_peak']
    assert {entry['bin_width_nm'] for entry in entries} == {0.1}
    assert {entry['r_max_nm'] for entry in entries} == {1.5}
    for call in calls:
        assert call['arguments'][call['arguments'].index('-bin') + 1] == '0.1'
        assert call['arguments'][call['arguments'].index('-rmax') + 1] == '1.5'
    assert calls[0]['arguments'][calls[0]['arguments'].index('-ref') + 1].startswith('com of ')


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
