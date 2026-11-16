"""The energy-conservation test of de Jong et al. (2016) on a run's own dynamics.

de Jong, Baoukina, Ingólfsson & Marrink, "Martini straight", Comput. Phys. Commun. 199 (2016) 1-7, section 2.4.
Their test of a non-bonded scheme and a timestep is the drift of the temperature and the drift in the total energy
divided by the drift in the potential energy, measured over the last 600 ps of a leg. They report, for NVE water:

    'Old' shifted Martini 2 parameters   temperature drift -46.2 K   ratio 1.3
    'Common' shifted set                 temperature drift   0.2 K   ratio 0.07
    'New' straight cutoff + modifiers    temperature drift   0.3 K   ratio 0.12

Those numbers are the reference this record quotes, not a pass mark of our own: the ratio is a conservation check
only when the leg is NVE (or, with GROMACS' `Conserved En.`, NVT). Every CG production leg here is NpT -- the profile
runs a V-rescale thermostat and a Parrinello-Rahman barostat -- so the thermostat and barostat exchange energy with
the system and the ratio measures that exchange. For those legs the record states the ensemble, reports the paper's
numbers as the reference, and checks the two things the ensemble does say: the temperature holds its target and the
potential energy is stationary in the window. The ratio is still recorded, for comparison with the paper and with
later runs.

The producer reads the run's own production `.edr` through `gmx energy` (the reader `trajectory_overview` already
owns) and publishes `energy-conservation.json` and `energy-conservation.png` into the analysis output.
"""
import json
import math
from pathlib import Path

from . import layout
from .statistics import series_summary
from .trajectory_overview import read_energy

#: The paper's window: its NVE runs were 1.2 ns long and the analysis covers the last 600 ps.
WINDOW_NS = 0.6

#: The terms the window keeps as raw series and the figure draws. `Total Energy` and `Potential` are the paper's
#: ratio's two members; `Conserved En.`/`Enthalpy` are the ensemble-dependent conserved quantity.
SERIES_TERMS = ('Temperature', 'Potential', 'Total Energy', 'Conserved En.', 'Enthalpy')

#: The production leg's energy file, by the paths a run records it under: a CG run's `md.edr`, an AA run's
#: `06_production/run.edr`, a publication's extracted reference, and the two pdc assessment/extension legs. Explicit,
#: never a glob: `eq.edr`/`min.edr` sit beside them and would answer a production question with another leg.
PRODUCTION_ENERGY = ('4_CG_sim/md.edr', '06_production/run.edr', '07_reference/run.edr',
                     '06_assessment/prod/run.edr', '08_extension/prod/run.edr')

#: The conserved quantity per ensemble, in GROMACS' own XVG spelling.
CONSERVED_TERM = {'NVE': 'Total Energy', 'NVT': 'Conserved En.', 'NpT': 'Enthalpy'}

#: The paper's own thresholds, quoted in the record: a ratio at or below `steady` is what its recommended scheme
#: reaches, `watch` is between its schemes and its discarded one, and anything above `watch` is its 'Old' behaviour.
STEADY_RATIO = 0.2
WATCH_RATIO = 0.5
TEMPERATURE_TOLERANCE_K = 2.0
DRIFT_TOLERANCE_K = 1.0

#: What the paper measured, kept in the record so a reader sees the scale the thresholds come from.
REFERENCE = {
    'citation': 'de Jong, Baoukina, Ingólfsson & Marrink, Comput. Phys. Commun. 199 (2016) 1-7, section 2.4',
    'nve': {'old_shifted': {'temperature_drift_k': -46.2, 'ratio': 1.3},
            'common_shifted': {'temperature_drift_k': 0.2, 'ratio': 0.07},
            'straight_cutoff': {'temperature_drift_k': 0.3, 'ratio': 0.12}},
    'thresholds': {'steady_ratio': STEADY_RATIO, 'watch_ratio': WATCH_RATIO,
                   'temperature_k': TEMPERATURE_TOLERANCE_K, 'drift_k': DRIFT_TOLERANCE_K},
}


def _window(times_ns):
    """The sample indices of the paper's window: the last 600 ps, or the whole leg when it is shorter."""
    end = times_ns[-1]
    start = max(0.0, end - WINDOW_NS)
    indices = [index for index, time in enumerate(times_ns) if time >= start]
    if len(indices) < 3:
        # A leg shorter than three samples of its own window is not a drift measurement at all; take its second half
        # and let `span_ns` say what was actually covered.
        indices = list(range(len(times_ns) // 2, len(times_ns)))
    return indices


def _summary(values, times_ns):
    """One term over the window, as `series_summary` reads it, with the drift over the window's own span."""
    summary = series_summary(values, times_ns=times_ns)
    span = times_ns[-1] - times_ns[0]
    summary['drift'] = summary['slope_per_ns'] * span
    return summary


def _ensemble(manifest):
    """`(ensemble, basis)`: the leg's ensemble from the recorded coupling, and the sentence a reader needs."""
    settings = manifest.get('settings') or {}
    if manifest.get('run_type') == 'aa_only':
        thermostat = str(settings.get('aa_production_tcoupl') or '').strip().lower()
        barostat = str(settings.get('aa_production_pcoupl') or '').strip().lower()
        if thermostat == 'no' and barostat == 'no':
            return 'NVE', ('This AA production leg records tcoupl=no and pcoupl=no, so the total energy is the '
                           'conserved quantity and the paper\'s drift ratio is a conservation check.')
        if barostat == 'no':
            return 'NVT', ('This AA production leg records pcoupl=no, so it is NVT and GROMACS\' conserved energy '
                           '(the total energy plus the thermostat\'s exchange) is the conserved quantity.')
        return 'NpT', ('This AA production leg records a thermostat and a barostat, so the drift ratio is the '
                       'exchange with the bath, not a conservation check; the ensemble checks are temperature and '
                       'the stationarity of the potential energy.')
    return 'NpT', ('Every CG production leg runs the reviewed profile\'s V-rescale thermostat and Parrinello-Rahman '
                   'barostat, so the drift ratio is the exchange with the bath, not a conservation check. The paper\'s '
                   'NVE ratio needs an NVE leg; the ensemble checks here are that the temperature holds its target '
                   'and the potential energy is stationary.')


def measure(times_ns, series, *, target_k, ensemble):
    """The paper's numbers over its window for one leg. Pure: `times_ns` and `{term: values}` in, a record out."""
    times_ns = [float(time) for time in times_ns]
    if len(times_ns) < 2:
        raise ValueError('an energy leg needs at least two samples to measure a drift')
    indices = _window(times_ns)
    window_times = [times_ns[index] for index in indices]
    span = window_times[-1] - window_times[0]

    def summary(term):
        values = series.get(term)
        if not values or len(values) != len(times_ns):
            return None
        return _summary([float(values[index]) for index in indices], window_times)

    temperature = summary('Temperature')
    potential = summary('Potential')
    conserved_term = CONSERVED_TERM[ensemble]
    conserved = summary(conserved_term)
    ratio = None
    if conserved is not None and potential is not None and abs(potential['slope_per_ns']) > 1e-9:
        ratio = abs(conserved['slope_per_ns']) / abs(potential['slope_per_ns'])

    temperature_check = None
    if temperature is not None:
        holds = (abs(temperature['mean'] - target_k) <= TEMPERATURE_TOLERANCE_K
                 and abs(temperature['drift']) <= DRIFT_TOLERANCE_K)
        temperature_check = {'name': 'the temperature holds its target', 'ok': holds,
                             'detail': (f"mean {temperature['mean']:.2f} K against {target_k:.1f} K, "
                                        f"drift {temperature['drift']:+.2f} K over {span:.3f} ns")}
    checks = [temperature_check] if temperature_check is not None else []
    if ensemble in ('NVE', 'NVT'):
        # The paper's test: the conserved quantity's drift over the potential's. A potential that does not drift at
        # all leaves nothing to divide by, and that is a measurement this window cannot take -- a watch, not a pass.
        if conserved is not None:
            checks.append({'name': f'the conserved energy ({conserved_term}) does not drift',
                           'ok': ratio is not None and ratio <= STEADY_RATIO,
                           'detail': (f"|drift| / |potential drift| = {ratio:.3f}" if ratio is not None
                                      else 'the potential energy does not drift in this window, so the ratio has '
                                           'no denominator')})
        if ratio is None:
            state = 'watch'
        elif ratio <= STEADY_RATIO:
            state = 'steady' if temperature_check is None or temperature_check['ok'] else 'watch'
        elif ratio <= WATCH_RATIO:
            state = 'watch'
        else:
            state = 'poor'
    else:
        # The ratio is exchange with the bath here; what the ensemble does say is that the thermostat tracks its
        # target and the potential energy is stationary in the window.
        if potential is not None:
            stationary = abs(potential['drift']) <= max(0.5 * potential['std'], 1.0)
            checks.append({'name': 'the potential energy is stationary in the window', 'ok': stationary,
                           'detail': (f"drift {potential['drift']:+.2f} kJ/mol against a standard deviation of "
                                      f"{potential['std']:.2f} kJ/mol over {span:.3f} ns")})
        state = 'steady' if checks and all(check['ok'] for check in checks) else 'drift'

    return {
        'ensemble': ensemble,
        'window': {'start_ns': round(window_times[0], 4), 'end_ns': round(window_times[-1], 4),
                   'span_ns': round(span, 4), 'samples': len(window_times)},
        'temperature': None if temperature is None else {
            'mean_k': round(temperature['mean'], 4), 'drift_k': round(temperature['drift'], 4),
            'slope_per_ns': round(temperature['slope_per_ns'], 6), 'std_k': round(temperature['std'], 4),
            'target_k': round(float(target_k), 4)},
        'potential': None if potential is None else {
            'mean_kj_mol': round(potential['mean'], 4), 'drift_kj_mol': round(potential['drift'], 4),
            'slope_per_ns': round(potential['slope_per_ns'], 6), 'std_kj_mol': round(potential['std'], 4)},
        'conserved': None if conserved is None else {
            'term': conserved_term, 'mean_kj_mol': round(conserved['mean'], 4),
            'drift_kj_mol': round(conserved['drift'], 4), 'slope_per_ns': round(conserved['slope_per_ns'], 6),
            'ratio_to_potential': None if ratio is None else round(ratio, 6)},
        'checks': checks,
        'state': state,
    }


def _figure(path, times_ns, series, record):
    """The three traces the record measures, whole leg and the measured window. A PNG, as the figure viewer lists."""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError:
        return False
    figure = Figure(figsize=(10.2, 6.0), constrained_layout=True)
    FigureCanvasAgg(figure)
    rows = (('Temperature', 'Temperature (K)', 'K'), ('Potential', 'Potential (kJ mol$^{-1}$)', 'kJ/mol'),
            ('Total Energy', 'Total energy (kJ mol$^{-1}$)', 'kJ/mol'))
    window_start, window_end = record['window']['start_ns'], record['window']['end_ns']
    stride = max(1, math.ceil(len(times_ns) / 4000))
    picked = [index for index, time in enumerate(times_ns) if time >= window_start]
    window_times = [times_ns[index] for index in picked]
    axes = figure.subplots(len(rows), 2, sharey='row')
    for row, (term, label, unit) in enumerate(rows):
        values = series.get(term)
        whole, window = axes[row]
        if not values:
            whole.set_visible(False)
            window.set_visible(False)
            continue
        whole.plot(times_ns[::stride], values[::stride], lw=0.6, color='#2f5c8a')
        whole.axvspan(window_start, window_end, color='#e0c268', alpha=0.35, lw=0)
        whole.set_ylabel(label)
        window.plot(window_times, [values[index] for index in picked], lw=0.8, color='#2f5c8a')
        # The drift the record quotes, drawn as its least-squares line: a flat line is the ideal for a thermostatted
        # leg's temperature and potential energy, and the conserved quantity in NVE/NVT.
        if len(window_times) > 2:
            summary = series_summary([values[index] for index in picked], times_ns=window_times)
            mean = sum(window_times) / len(window_times)
            fitted = [summary['mean'] + summary['slope_per_ns'] * (time - mean) for time in window_times]
            window.plot(window_times, fitted, '--', lw=1.2, color='#b4452e')
            window.set_title(f"drift {summary['slope_per_ns'] * (window_times[-1] - window_times[0]):+.2f} {unit}"
                             f" over {window_times[-1] - window_times[0]:.3f} ns", fontsize=8)
    axes[-1, 0].set_xlabel('Time (ns)  (whole leg, measured window shaded)')
    axes[-1, 1].set_xlabel('Time (ns)  (measured window)')
    figure.suptitle(f"Energy conservation \u00b7 {record['leg']} \u00b7 {record['ensemble']}, state "
                    f"{record['state']}")
    figure.savefig(path, dpi=150)
    return True


def run(work, payload=None):
    """Measure one run's production energy file and publish its energy-conservation record and figure."""
    work = Path(work)
    leg = next((relative for relative in PRODUCTION_ENERGY if (work / relative).is_file()), None)
    if leg is None:
        raise layout.NoTrajectory('this run staged no production energy file (.edr) to read; '
                                  'looked for ' + ', '.join(PRODUCTION_ENERGY))
    data, reason = read_energy(work / leg, work)
    if data is None:
        raise RuntimeError(f'the production energy file {leg} could not be read: {reason}')
    times_ns = [float(time) / 1000.0 for time in data['times_ps']]
    series = {label: data['columns'][position] for position, label in enumerate(data['labels'])
              if position < len(data['columns']) and label in SERIES_TERMS}
    manifest_path = work / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    target_k = float((manifest.get('settings') or {}).get('temperature_k') or 300.0)
    ensemble, basis = _ensemble(manifest)

    record = measure(times_ns, series, target_k=target_k, ensemble=ensemble)
    record['leg'] = leg
    record['basis'] = basis
    record['reference'] = REFERENCE
    record['figure'] = 'energy-conservation.png'
    _figure(work / record['figure'], times_ns, series, record)
    (work / 'energy-conservation.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record
