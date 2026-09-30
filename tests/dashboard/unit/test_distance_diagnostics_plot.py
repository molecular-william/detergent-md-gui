"""The diagnostics plot draws every run on the same colour scale.

It used to use each run's own maximum (`vmax = max(.1, nanmax(matrix))`), which is why the figure carried a note
telling readers to compare numbers rather than colour: two matrices were drawn on different ranges, so a run
with worse distances could come out looking like a run with better ones. The scale is fixed now, the record says
it is shared, and it says whether this run's values ran past it.

Called directly rather than through the whole comparison, which needs real AA and CG trajectories.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'dashboard/execution/scripts'))
import distance_diagnostics as diagnostics  # noqa: E402


def result_with(values):
    return {'metric': 'Wasserstein distance (nm); lower is closer',
            'pairs': [{'beads': ['B01', 'B02'], 'kind': 'physical',
                       'wasserstein_nm': {'raw_AA': values[0], 'ring_expanded_AA': values[0]}},
                      {'beads': ['B02', 'B03'], 'kind': 'physical',
                       'wasserstein_nm': {'raw_AA': values[1], 'ring_expanded_AA': values[1]}}]}


def test_two_runs_with_different_maxima_are_drawn_on_the_same_scale(tmp_path):
    """The comparability claim, which is the whole reason the scale is not per run."""
    small, large = result_with([0.02, 0.04]), result_with([0.07, 0.09])

    diagnostics.write_matrix_plot(small, tmp_path / 'small.png')
    diagnostics.write_matrix_plot(large, tmp_path / 'large.png')

    assert small['colour_scale_nm'] == {'min': 0.0, 'max': 0.1, 'per_run': False, 'clipped': False}
    assert small['colour_scale_nm']['max'] == large['colour_scale_nm']['max']


def test_a_run_past_the_scale_says_so_rather_than_widening_it(tmp_path):
    result = result_with([0.05, 0.44])

    written = diagnostics.write_matrix_plot(result, tmp_path / 'matrix.png')

    assert written is True and (tmp_path / 'matrix.png').is_file()
    assert result['colour_scale_nm'] == {'min': 0.0, 'max': 0.1, 'per_run': False, 'clipped': True}


def test_a_near_zero_matrix_reports_the_shared_scale_rather_than_a_smaller_one(tmp_path):
    result = result_with([0.0, 0.01])

    diagnostics.write_matrix_plot(result, tmp_path / 'matrix.png')

    assert result['colour_scale_nm']['max'] == diagnostics.COLOUR_SCALE_NM
    assert result['colour_scale_nm']['clipped'] is False


def test_the_scale_the_plot_used_is_the_scale_it_records(tmp_path):
    """`colour_scale` is the one place the value is decided, so the figure and the record cannot drift."""
    matrix = np.array([[0.0, 0.23], [0.23, 0.0]])
    low, high, clipped = diagnostics.colour_scale(matrix)
    assert (low, high) == (0.0, diagnostics.COLOUR_SCALE_NM) and clipped is True

    result = result_with([0.23, 0.23])
    diagnostics.write_matrix_plot(result, tmp_path / 'matrix.png')

    assert (result['colour_scale_nm']['min'], result['colour_scale_nm']['max']) == (low, high)


def test_the_written_json_carries_the_scale(tmp_path, monkeypatch):
    """The script writes the JSON after the plot for exactly this reason."""
    source = Path(diagnostics.__file__).read_text()
    plot_line = source.index('write_matrix_plot(result,')
    json_line = source.index("Path('distance_diagnostics_stratified.json').write_text")
    assert plot_line < json_line, 'the plot must run before the JSON is written'
