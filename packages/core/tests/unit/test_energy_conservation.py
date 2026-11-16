"""The energy-conservation test of de Jong et al. (2016) on a run's production leg.

The paper (Comput. Phys. Commun. 199 (2016) 1-7, section 2.4) measures the temperature drift and the drift in the
total energy divided by the drift in the potential energy over the last 600 ps: 0.3 K and 0.12 with its recommended
straight cutoff, 1.3 with the shifted Martini 2 potential it replaces. The producer applies that window and those
numbers to the run's own `.edr`, and states the ensemble -- every CG production leg here is NpT, where the ratio is
exchange with the thermostat and barostat rather than conservation.
"""
import math

import pytest
from dashboard.analysis import kinds
from dashboard.analysis.runs import energy_conservation, layout

#: 1 ns in eleven samples, so the paper's 600 ps window is the last seven of them.
TIMES = [index / 10.0 for index in range(11)]


def series(*, potential=0.0, potential_slope=0.0, total_slope=0.0, temperature=300.0):
    """The terms the producer reads, on one shared clock; a slope is in the term's unit per nanosecond."""
    return {'Temperature': [temperature for _ in TIMES],
            'Potential': [potential + potential_slope * time for time in TIMES],
            'Total Energy': [potential + total_slope * time for time in TIMES],
            'Enthalpy': [potential + total_slope * time for time in TIMES],
            'Conserved En.': [potential + total_slope * time for time in TIMES]}


def test_the_window_is_the_papers_last_600_ps_and_the_ratio_is_the_conservation_test():
    """NVE: the total energy drifting a tenth of the potential energy is the paper's straight-cutoff scale."""
    record = energy_conservation.measure(TIMES, series(potential_slope=10.0, total_slope=1.0),
                                         target_k=300.0, ensemble='NVE')

    assert record['window'] == {'start_ns': 0.4, 'end_ns': 1.0, 'span_ns': 0.6, 'samples': 7}
    assert record['conserved']['term'] == 'Total Energy'
    assert math.isclose(record['conserved']['ratio_to_potential'], 0.1, rel_tol=1e-9)
    assert math.isclose(record['conserved']['drift_kj_mol'], 0.6, rel_tol=1e-9)
    assert record['state'] == 'steady', record['checks']
    assert [check['ok'] for check in record['checks']] == [True, True]


def test_a_run_whose_total_energy_drifts_against_its_potential_is_flagged():
    """The paper's discarded set: twice the potential energy's drift is worse than anything it measured."""
    record = energy_conservation.measure(TIMES, series(potential_slope=10.0, total_slope=20.0),
                                         target_k=300.0, ensemble='NVE')

    assert record['conserved']['ratio_to_potential'] == pytest.approx(2.0)
    assert record['state'] == 'poor', record['checks']


def test_a_thermostatted_leg_is_judged_on_holding_its_target_and_on_a_stationary_potential():
    """NpT: the ratio is exchange with the bath, so the ensemble checks are what the record tests."""
    stationary = energy_conservation.measure(TIMES, series(potential=0.0,
                                                           potential_slope=0.0),
                                             target_k=300.0, ensemble='NpT')
    assert stationary['state'] == 'steady', stationary['checks']

    warming = energy_conservation.measure(TIMES, series(temperature=320.0), target_k=300.0, ensemble='NpT')
    drifting = energy_conservation.measure(TIMES, series(potential_slope=10.0), target_k=300.0, ensemble='NpT')
    assert warming['state'] == 'drift' and warming['checks'][0]['ok'] is False
    assert drifting['state'] == 'drift' and drifting['checks'][-1]['ok'] is False


def test_the_ensemble_comes_from_the_recorded_coupling():
    """An AA production leg's coupling is recorded; every CG family leg runs the reviewed NpT profile."""
    def run_type(kind, **settings):
        return energy_conservation._ensemble({'run_type': kind, 'settings': settings})[0]

    assert run_type('aa_only', aa_production_tcoupl='no', aa_production_pcoupl='no') == 'NVE'
    assert run_type('aa_only', aa_production_tcoupl='V-rescale', aa_production_pcoupl='no') == 'NVT'
    assert run_type('aa_only', aa_production_tcoupl='V-rescale', aa_production_pcoupl='Parrinello-Rahman') == 'NpT'
    assert run_type('cg', mdrun_gpu=0) == 'NpT'
    assert run_type('pdc') == 'NpT'


def test_a_run_with_no_production_energy_file_is_skipped_not_failed(tmp_path):
    """Nothing to read is the analysis layer's skip, with the paths it looked for in the reason."""
    with pytest.raises(layout.NoTrajectory, match='production energy file'):
        energy_conservation.run(tmp_path)


def test_the_kind_is_registered_as_a_cg_default_and_reads_an_edr():
    """The whole wire: the worker stages the production legs, and every CG run owes the kind."""
    assert 'energy-conservation' in kinds.default_for('cg')
    assert 'energy-conservation' not in kinds.default_for('aa_only')
    row = kinds.TABLE['energy-conservation']
    assert row.records_gmx_version is True
    assert '4_CG_sim/md.edr' in row.sources and '06_production/run.edr' in row.sources
    assert row.run is energy_conservation.run
