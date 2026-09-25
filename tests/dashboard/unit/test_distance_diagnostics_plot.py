"""The diagnostics plot records the colour range it used.

The matrix colour scale is per run (`vmax = max(.1, nanmax(matrix))`), so two runs' heatmaps are not
colour-comparable. The document already tells a reader to compare numbers rather than colour; the
script now records the range so that instruction is actionable instead of aspirational.

Called directly rather than through the whole comparison, which needs real AA and CG trajectories.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'dashboard/execution/scripts'))
import distance_diagnostics as diagnostics  # noqa: E402


def result_with(values):
    return {'metric': 'Wasserstein distance (nm); lower is closer',
            'pairs': [{'beads': ['B01', 'B02'], 'kind': 'physical',
                       'wasserstein_nm': {'raw_AA': values[0], 'ring_expanded_AA': values[0]}},
                      {'beads': ['B02', 'B03'], 'kind': 'physical',
                       'wasserstein_nm': {'raw_AA': values[1], 'ring_expanded_AA': values[1]}}]}


def test_the_plot_records_the_range_it_plotted(tmp_path):
    result = result_with([0.25, 0.44])

    written = diagnostics.write_matrix_plot(result, tmp_path / 'matrix.png')

    assert written is True
    assert (tmp_path / 'matrix.png').is_file()
    assert result['colour_scale_nm'] == {'min': 0.0, 'max': 0.44, 'per_run': True}


def test_a_tiny_matrix_still_reports_the_floor_it_uses(tmp_path):
    """vmax has a floor of .1, so a near-zero matrix must not claim a smaller range than the plot."""
    result = result_with([0.0, 0.01])

    diagnostics.write_matrix_plot(result, tmp_path / 'matrix.png')

    assert result['colour_scale_nm']['max'] == 0.1


def test_the_written_json_carries_the_scale(tmp_path, monkeypatch):
    """The script writes the JSON after the plot for exactly this reason."""
    source = Path(diagnostics.__file__).read_text()
    plot_line = source.index('write_matrix_plot(result,')
    json_line = source.index("Path('distance_diagnostics_stratified.json').write_text")
    assert plot_line < json_line, 'the plot must run before the JSON is written'
