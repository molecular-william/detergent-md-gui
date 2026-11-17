"""Each equilibration leg's potential, temperature and pressure, from that leg's own `.edr`.

The diagnostics a reader opens under a completed run's row: three stacked traces per leg, sampled to
`ENERGY_POINTS` points, beside the targets the run itself recorded. Nothing here is a validation claim -- the record
says what the leg's own energy file held, and a leg whose file or term the .edr does not carry is absent rather than
drawn from another file.

The leg table, the reader and the sampling bound are `trajectory_overview`'s: that producer already resolves each
leg's energy file from explicit candidate paths and reads it through `gmx energy`. This producer adds no parser of its
own; it asks `read_energy` once per leg and keeps the three terms the panel draws.
"""
import math
import re
from pathlib import Path

from ... import files
from . import readers, segments
from .trajectory_overview import ENERGY_POINTS, STAGE_ENERGY, read_energy

#: The tool's own version line, e.g. "GROMACS version:     2026.3". The recorded output is the whole of `gmx --version`,
#: banner and "Command line:" section included, so the line is found by its label rather than by position.
_VERSION_LINE = re.compile(r'^GROMACS version:\s*(\S+)', re.MULTILINE)

#: The terms the panel draws, in the order its charts are stacked. A term an EDR does not carry is omitted from that
#: leg's `terms` rather than drawn empty.
TRACE_TERMS = ('Potential', 'Temperature', 'Pressure')

#: The source paths this kind stages: every explicit EDR candidate from `STAGE_ENERGY`, each once. `4_CG_sim/eq.edr`
#: answers both the nvt and npt keys, so the flat list would otherwise name it twice.
SOURCES = tuple(dict.fromkeys(relative for spec in STAGE_ENERGY.values() for relative in spec['candidates']))


def _number(value):
    """A finite float from a manifest setting, or None. A value the run never recorded is not 300 K."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 6) if math.isfinite(number) else None


def _gmx_version(work):
    """The GROMACS build the run recorded in its own manifest, as one line, or None.

    The tool prints its banner first, so the line that names the version is preferred over the first non-empty one;
    a record whose output has no such line keeps that first line rather than nothing.
    """
    recorded = (readers.run_manifest(Path(work)).get('tools') or {}).get('gmx') or {}
    text = recorded.get('version_output') if isinstance(recorded, dict) else None
    body = str(text or '')
    found = _VERSION_LINE.search(body)
    if found is not None:
        return found.group(1)
    # A record with no labelled line keeps something rather than nothing: the first line it has.
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return lines[0] if lines else None


def _targets(work):
    """The run's own temperature and pressure targets, when its settings recorded them.

    Recorded rather than assumed: a target line is only drawn where the run stated the number, so a run that recorded
    no pressure target gets no invented 1 bar.
    """
    settings = readers.run_manifest(Path(work)).get('settings') or {}
    # The run types spell their target differently: an AA or CG run states temperature_k/pressure_bar, the CG
    # equilibration editor states cg_equil_ref_p, and a pdc run states ref_t and the NPT leg's pdc_npt_ref_p.
    temperature = _number(settings.get('temperature_k'))
    if temperature is None:
        temperature = _number(settings.get('ref_t'))
    pressure = _number(settings.get('pressure_bar'))
    if pressure is None:
        pressure = _number(settings.get('cg_equil_ref_p'))
    if pressure is None:
        pressure = _number(settings.get('pdc_npt_ref_p'))
    found = {}
    if temperature is not None:
        found['Temperature'] = temperature
    if pressure is not None:
        found['Pressure'] = pressure
    return found


def _resolved(work):
    """Each leg that has an energy file: `{leg: (path, spec)}`, first existing candidate winning.

    One file can answer several keys: `4_CG_sim/eq.edr` is a CG run's single equilibration and is named by both the
    nvt and npt candidates. Such a file is the *later* key's leg -- the equilibration table runs minimisation, NVT,
    NPT, and a combined equilibration is the one with pressure coupling -- so it is recorded once and not claimed as
    two legs.
    """
    resolved = {}
    for leg, spec in STAGE_ENERGY.items():
        for relative in spec['candidates']:
            edr = segments.present(Path(work), relative)
            if edr is not None:
                resolved[leg] = (edr, spec)
                break
    claimed = {path: leg for leg, (path, _) in resolved.items()}
    return {leg: entry for leg, entry in resolved.items() if claimed[entry[0]] == leg}


def _trace(work, leg, edr, spec):
    """One leg's three traces, or None when its .edr is unreadable or carries none of them."""
    data, _ = read_energy(edr, work)
    if data is None:
        return None
    times, stats, labels, columns = data['times_ps'], data['terms'], data['labels'], data['columns']
    if not times:
        return None
    step = max(1, math.ceil(len(times) / ENERGY_POINTS))
    terms = {}
    for term in TRACE_TERMS:
        summary = stats.get(term)
        if summary is None or term not in labels:
            continue
        position = labels.index(term)
        if position >= len(columns):
            continue
        values = columns[position]
        terms[term] = {'values': [round(values[offset], 6) for offset in range(0, len(values), step)],
                       'mean': summary.get('mean')}
    if not terms:
        return None
    if spec['x_unit'] == 'step':
        # A minimisation EDR counts steps, not time; its duration is not a wall-clock or simulated span.
        x = [int(round(times[offset])) for offset in range(0, len(times), step)]
        duration = None
    else:
        x = [round(times[offset], 4) for offset in range(0, len(times), step)]
        duration = round(times[-1] - times[0], 4) if len(times) > 1 else 0.0
    return {'x': x,
            'x_unit': spec['x_unit'],
            'duration_ps': duration,
            'source': str(edr.relative_to(work)),
            'terms': terms}


def run(work, payload=None):
    """Write `equilibration-traces.json`: one bounded trace per equilibration leg that has an energy file."""
    work = Path(work)
    legs = {}
    for leg, (edr, spec) in _resolved(work).items():
        trace = _trace(work, leg, edr, spec)
        if trace is not None:
            legs[leg] = trace
    record = {'legs': legs,
              'terms': list(TRACE_TERMS),
              'targets': _targets(work),
              'gmx_version': _gmx_version(work)}
    files.atomic_json(work / 'equilibration-traces.json', record)
    return {'legs': list(legs), 'gmx_version': record['gmx_version']}
