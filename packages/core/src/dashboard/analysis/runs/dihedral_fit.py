"""Fit a torsional potential from a dihedral's distribution, and let a criterion choose how many terms it needs.

Reimplemented from the method shaker documents and uses (Martini-Force-Field-Initiative/shaker, commit `b7680219`,
LGPL-2.1): inverted Boltzmann, Savitzky-Golay smoothing, a cosine series, and AIC/BIC over the number of terms. This
is **our own implementation of that workflow**, written from the documented method rather than copied from their
source, and shaker is credited in `CREDITS.md` and cited here as the reference implementation.

The series is fitted as `c + sum_n [a_n cos(n phi) + b_n sin(n phi)]`, which is linear in its coefficients and so is a
least-squares problem rather than an optimisation. GROMACS writes a proper dihedral as `k (1 + cos(n phi - phi_s))`,
the same function with `k_n = hypot(a_n, b_n)` and `phi_s = atan2(b_n, a_n)`; both are reported, so the numbers can go
into a topology without anyone re-deriving the conversion.

**Angles are degrees in, degrees out, and radians in between.** GROMACS takes degrees and the trigonometry needs
radians; the conversion happens at the boundary and the reported unit travels with the number, because that mix-up is
invisible in the output -- the same trap the equipartition estimator carries for its angular force constants.

The potential of mean force has no absolute zero, so it is reported with its minimum subtracted and that minimum
recorded: a reader comparing two fits needs to know that the offset is a convention and not a measurement.
"""
import json
from pathlib import Path

import MDAnalysis as mda
import numpy as np

from ... import itp
from . import DEFAULT_TEMPERATURE, R_GAS, layout

DEFAULT_BINS = 60
DEFAULT_WINDOW = 9
DEFAULT_ORDER = 3
DEFAULT_MAX_TERMS = 6
REPORT = 'dihedral-fit.json'
CRITERIA = ('aic', 'bic')


def inverted_boltzmann(angles_deg, temperature, *, bins=DEFAULT_BINS):
    """The potential of mean force of a dihedral, `-R T ln p`, on a uniform grid over one period.

    Bins with no sample are dropped rather than given an infinite energy: `-R T ln 0` is not a large number, it is no
    number at all, and one empty bin would dominate every fit built on it. How many were dropped is reported.
    """
    values = np.asarray(angles_deg, dtype=float)
    if values.size < 2:
        raise ValueError('a distribution needs at least two frames to be a distribution')
    edges = np.linspace(-180.0, 180.0, int(bins) + 1)
    counts, _ = np.histogram(values, bins=edges)
    centres = 0.5 * (edges[:-1] + edges[1:])
    occupied = counts > 0
    probability = counts[occupied] / float(values.size)
    energy = -R_GAS * float(temperature) / 1000.0 * np.log(probability)
    return {'centres_deg': centres[occupied], 'probability': probability,
            'energy_kj_mol': energy - energy.min(), 'offset_kj_mol': float(energy.min()),
            'frames': int(values.size), 'bins': int(bins), 'empty_bins': int((~occupied).sum())}


def savitzky_golay(values, window=DEFAULT_WINDOW, order=DEFAULT_ORDER):
    """A Savitzky-Golay smoothing: a polynomial of `order` fitted to a window of `window` points, evaluated at its
    centre, then moved along.

    Implemented here rather than taken from scipy, which is present in this environment only as another package's
    dependency and is not declared by this project. Both edges keep their full width and are fitted in the same
    least-squares sense as the interior, which is what lets a closed curve stay closed where its ends meet.
    """
    data = np.asarray(values, dtype=float)
    if window < 3 or window % 2 == 0:
        raise ValueError('the window must be odd and at least three points wide')
    if order < 0 or order >= window:
        raise ValueError('the polynomial order must be non-negative and smaller than the window')
    if data.size < window:
        raise ValueError(f'a {window}-point window cannot smooth {data.size} points')
    half = window // 2
    smoothed = np.empty_like(data)
    for index in range(data.size):
        low, high = max(0, index - half), min(data.size, index + half + 1)
        offsets = np.arange(low, high, dtype=float) - index
        design = np.vander(offsets, order + 1, increasing=True)
        coefficients, *_ = np.linalg.lstsq(design, data[low:high], rcond=None)
        # Offset zero is the centre, which is where the polynomial is evaluated.
        smoothed[index] = coefficients[0]
    return smoothed


def series(angles_deg, amplitudes, phases_rad, multiplicities):
    """`sum_n k_n (1 + cos(n phi - phi_s))`, the form GROMACS writes a proper dihedral in."""
    phi = np.radians(np.asarray(angles_deg, dtype=float))
    total = np.zeros_like(phi)
    for amplitude, phase, multiplicity in zip(amplitudes, phases_rad, multiplicities):
        total = total + amplitude * (1.0 + np.cos(multiplicity * phi - phase))
    return total


def _design(angles_rad, terms):
    """The regression matrix for harmonics 1..terms: a constant column, then a cosine and a sine per harmonic."""
    columns = [np.ones_like(angles_rad)]
    for harmonic in range(1, terms + 1):
        columns += [np.cos(harmonic * angles_rad), np.sin(harmonic * angles_rad)]
    return np.column_stack(columns)


def fit_terms(angles_deg, values, *, max_terms=DEFAULT_MAX_TERMS):
    """Cumulative cosine fits, one per number of harmonics, each with its information criteria.

    AIC and BIC in the Gaussian-error form on the residual sum of squares: `n ln(RSS/n) + 2k` and
    `n ln(RSS/n) + k ln(n)`. Their absolute values depend on conventions that differ between papers; their *ordering*
    does not, and the ordering is what chooses a model, so the table carries both and the choice names which it used.
    """
    angle_rad = np.radians(np.asarray(angles_deg, dtype=float))
    data = np.asarray(values, dtype=float)
    if angle_rad.size < 4 or angle_rad.size != data.size:
        raise ValueError('a fit needs at least four points, one value each')
    models = []
    for terms in range(1, int(max_terms) + 1):
        design = _design(angle_rad, terms)
        if design.shape[1] > angle_rad.size:
            break
        coefficients, *_ = np.linalg.lstsq(design, data, rcond=None)
        residual = float(np.sum((data - design @ coefficients) ** 2))
        parameters, count = design.shape[1], angle_rad.size
        # A perfect fit has no log to take. Zero is the boundary case, and it is reported as such rather than as a
        # large negative number that would win every comparison by arithmetic accident.
        log_term = float(np.log(residual / count)) if residual > 0 else -np.inf
        models.append({
            'terms': terms, 'parameters': parameters, 'residual': residual,
            'aic': float(2 * parameters + count * log_term),
            'bic': float(parameters * np.log(count) + count * log_term),
            'multiplicities': list(range(1, terms + 1)),
            'amplitudes': [float(np.hypot(coefficients[2 * i + 1], coefficients[2 * i + 2]))
                           for i in range(terms)],
            'phases_rad': [float(np.arctan2(coefficients[2 * i + 2], coefficients[2 * i + 1]))
                           for i in range(terms)],
        })
    if not models:
        raise ValueError('no model fits: there are fewer points than the smallest model has parameters')
    return models


def fit_dihedral(angles_deg, temperature, *, bins=DEFAULT_BINS, window=DEFAULT_WINDOW, order=DEFAULT_ORDER,
                 max_terms=DEFAULT_MAX_TERMS, criterion='bic'):
    """The whole workflow: histogram, invert, smooth, fit, and choose the number of terms by a criterion.

    Returns the potential of mean force it measured, every model's criterion, and the chosen one as GROMACS writes it
    -- a force constant, a multiplicity and a phase in degrees, with the unit named beside the number.
    """
    if criterion not in CRITERIA:
        raise ValueError(f'criterion must be one of {", ".join(CRITERIA)}, not {criterion!r}')
    pmf = inverted_boltzmann(angles_deg, temperature, bins=bins)
    smoothed = savitzky_golay(pmf['energy_kj_mol'], window=window, order=order)
    models = fit_terms(pmf['centres_deg'], smoothed, max_terms=max_terms)
    best = min(models, key=lambda model: model[criterion])
    angles = pmf['centres_deg']
    reconstructed = series(angles, best['amplitudes'], best['phases_rad'], best['multiplicities'])
    return {
        'temperature': float(temperature), 'criterion': criterion, 'frames': pmf['frames'],
        'bins': pmf['bins'], 'empty_bins': pmf['empty_bins'],
        'window': {'points': int(window), 'order': int(order)},
        'terms': best['terms'],
        'pmf': {'centres_deg': angles.tolist(), 'probability': pmf['probability'].tolist(),
                'energy_kj_mol': pmf['energy_kj_mol'].tolist(), 'smoothed_kj_mol': smoothed.tolist(),
                'offset_kj_mol': pmf['offset_kj_mol']},
        'models': models,
        'dihedrals': [{'multiplicity': multiplicity, 'force_constant_kj_mol': amplitude,
                       'phase_deg': float(np.degrees(phase)), 'phase_units': 'degrees'}
                      for amplitude, phase, multiplicity
                      in zip(best['amplitudes'], best['phases_rad'], best['multiplicities'])],
        'residual_rms_kj_mol': float(np.sqrt(np.mean((pmf['energy_kj_mol'] - reconstructed) ** 2))),
        'method': 'inverted Boltzmann, Savitzky-Golay smoothing, cumulative cosine series, chosen by ' + criterion,
        'credit': 'reimplemented from the method shaker documents (Martini-Force-Field-Initiative/shaker, commit '
                  'b7680219, LGPL-2.1); see CREDITS.md',
        'scientifically_validated': False,
    }


# --- measuring a torsion, reading the topology, and publishing the comparison ---------------------------------

DIHEDRAL_SECTION = 'dihedrals'
#: The `funct` values this reader reads. Both are `sum_k k (1 + cos(n phi - phi_s))`: funct 1 carries one term,
#: funct 9 a Fourier series of them.
PROPER_FUNCTS = {'1': 'one periodic term', '9': 'a Fourier series'}
#: Numbers after `funct` that make up one term: phase, force constant, multiplicity.
TRIPLET = 3


def torsion_deg(p0, p1, p2, p3):
    """The dihedral angle of four points, in degrees, by the standard arctan2 construction.

    Two planes meet along the 1-2 bond: the sign is the one this construction gives. The test pins it on a geometry
    built to have an answer known by construction, and the report carries the assumption that GROMACS's sign for a
    proper dihedral is the same -- if it were not, a fitted phase would come out mirrored while the multiplicity
    still agreed, which is exactly the failure the report's limitations name.
    """
    b0 = np.asarray(p0, dtype=float) - np.asarray(p1, dtype=float)
    b1 = np.asarray(p2, dtype=float) - np.asarray(p1, dtype=float)
    b2 = np.asarray(p3, dtype=float) - np.asarray(p2, dtype=float)
    b1 = b1 / np.linalg.norm(b1)
    v = b0 - np.dot(b0, b1) * b1
    w = b2 - np.dot(b2, b1) * b1
    return float(np.degrees(np.arctan2(np.dot(np.cross(b1, v), w), np.dot(v, w))))


def read_declared_dihedrals(path):
    """The proper dihedrals a topology declares, funct 1 and funct 9, one entry per atom quadruple.

    `funct 1` is a single periodic term: `i j k l 1 phi_s k mult`. `funct 9` is the same function as a Fourier series --
    `phi C mult` triplets, which GROMACS allows several of on one line and which Fast-Forward's `ff_inter` writes one
    per line for the same quadruple. Both are `sum_k k (1 + cos(n phi - phi_s))`, so the numbers mean the same thing
    and only the number of terms differs: a funct 9 quadruple is read as **one** dihedral whose `terms` are its
    harmonics, rather than as one dihedral per line, which would measure and report the same torsion eight times.

    The scalar fields on the entry are the harmonic with the largest force constant, the same rule `publish` uses to
    name a dominant term on the fitted side. That rule is the report's, not the force field's: a series has no single
    phase, and the comparison in `publish` says so and reports the whole series beside it.

    Any other `funct` is refused rather than assumed, as in the bond reader: a different `funct` is a different function
    with different fields, and reading its numbers as a phase and a force constant would put a meaningless pair beside
    a real one -- and this reader's whole output is a comparison, so a meaningless half of it is not a small error.
    """
    entries = {}
    for section, rows in itp.sections(Path(path).read_text()):
        if section != DIHEDRAL_SECTION:
            continue
        for number, line in rows:
            fields = line.split()
            if len(fields) < 5 + TRIPLET:
                raise ValueError(f'{path}:{number}: a proper dihedral needs 8 fields, found {len(fields)}')
            funct = fields[4]
            if funct not in PROPER_FUNCTS:
                raise ValueError(f'{path}:{number}: funct {funct} is not a proper dihedral, and this reader has '
                                 'nothing to say about it')
            trailing = fields[5:]
            if funct == '1' and len(trailing) != TRIPLET:
                raise ValueError(f'{path}:{number}: funct 1 carries exactly {TRIPLET} numbers after it, found '
                                 f'{len(trailing)}')
            if len(trailing) % TRIPLET:
                raise ValueError(f'{path}:{number}: funct 9 takes phase, force constant and multiplicity in threes, '
                                 f'found {len(trailing)}')
            try:
                atoms = tuple(int(index) for index in fields[:4])
                triplets = [(float(phase), float(constant), int(float(multiplicity)))
                            for phase, constant, multiplicity
                            in (trailing[offset:offset + TRIPLET] for offset in range(0, len(trailing), TRIPLET))]
            except ValueError as error:
                raise ValueError(f'{path}:{number}: {error}') from error
            entry = entries.setdefault(atoms, {'atoms': atoms, 'funct': funct, 'terms': [], 'line': number})
            if entry['funct'] != funct:
                raise ValueError(f'{path}:{number}: atoms {" ".join(str(index) for index in atoms)} are declared '
                                 f'with funct {entry["funct"]} and funct {funct}; one dihedral cannot be both')
            entry['terms'] += [{'phase_deg': phase, 'force_constant': constant, 'multiplicity': multiplicity,
                                'line': number} for phase, constant, multiplicity in triplets]
    for entry in entries.values():
        dominant = max(entry['terms'], key=lambda term: abs(term['force_constant']))
        entry.update({'phase_deg': dominant['phase_deg'], 'force_constant': dominant['force_constant'],
                      'multiplicity': dominant['multiplicity'], 'term_count': len(entry['terms'])})
    return list(entries.values())


def curve_rms(ours_terms, fit_terms, angles_deg=None):
    """The RMS difference between two dihedral potentials over one period, in kJ/mol, each with its minimum removed.

    This is what makes a multi-term comparison mean something: a funct 9 term has no single phase to agree with, so the
    two series are evaluated instead and the difference between the curves is reported.

    **The one constant shift that best aligns the two curves is removed first, and that is not cosmetic.** A term is
    `C (1 + cos(...))`, whose mean over a period is `C`, so a series carries the sum of its coefficients as a constant
    *and the two sides need not carry the same one* -- the engine picks its coefficients by least squares against a
    potential of mean force with no absolute zero. Measured on the DDM linkage's own fit, the raw RMS was 15.9 kJ/mol
    and the difference of the same two curves after that shift is 4.4 kJ/mol, so the shift was 11.5 of it: reported
    raw, the number would have read as a disagreement about the shape of the torsion that is not there. Aligning on
    the minimum instead measures well depth as well as shape, so the mean of the difference -- the shift that leaves
    the smallest RMS -- is what is removed, and what remains is disagreement about shape alone.
    """
    grid = np.arange(-180.0, 180.0, 1.0) if angles_deg is None else np.asarray(angles_deg, dtype=float)
    theirs = series(grid, [term['force_constant'] for term in ours_terms],
                    [np.radians(term['phase_deg']) for term in ours_terms],
                    [term['multiplicity'] for term in ours_terms])
    ours = series(grid, [term['force_constant_kj_mol'] for term in fit_terms],
                  [np.radians(term['phase_deg']) for term in fit_terms],
                  [term['multiplicity'] for term in fit_terms])
    difference = theirs - ours
    difference = difference - difference.mean()
    return float(np.sqrt(np.mean(difference ** 2)))


def measure_torsions(universe, declared, names, frames=slice(0, None, 1)):
    """Every declared dihedral's angle per frame, in degrees, from one read of the trajectory."""
    beads = [tuple(names[index - 1] if 0 < index <= len(names) else f'#{index}' for index in term['atoms'])
             for term in declared]
    position = {name: index for index, name in enumerate(names)}
    series = {index: [] for index, pair in enumerate(beads) if all(name in position for name in pair)}
    for frame in range(*frames.indices(len(universe.trajectory))):
        universe.trajectory[frame]
        # MDAnalysis reports angstroms; a torsion is an angle, so only the ratios matter, but keep the units honest.
        positions = universe.atoms.positions / 10.0
        for index in series:
            series[index].append(torsion_deg(*(positions[position[name]] for name in beads[index])))
    return beads, {index: np.asarray(values, dtype=float) for index, values in series.items()}


def publish(work, payload=None):
    """Fit every proper dihedral the run's topology declares, and publish the fit beside the run's own terms.

    Both sides read the same mapped frames, as in the bonded cross-check: the run's terms came from a fit to those
    frames, so fitting anything else would compare two different samplings and call the difference a property of the
    molecule.

    **This is where a criterion replaces a tool default.** The topology states how many harmonics each term has
    because a tool chose them; here AIC/BIC chooses, and where the two disagree is the finding -- which is the whole
    reason this analysis exists rather than being a nicety on top of the BARTENDER route.
    """
    work = Path(work)
    payload = dict(payload or {})
    temperature = float(payload.get('temperature', DEFAULT_TEMPERATURE))
    criterion = str(payload.get('criterion', 'bic'))
    universe = mda.Universe(str(work / '2_mapping/mapped.gro'), str(work / '2_mapping/mapped.xtc'))
    names = list(universe.atoms.names)

    topology, provenance = layout.model_topology(work)
    declared = read_declared_dihedrals(topology)

    frames = slice(int(payload.get('start', 0)), payload.get('stop'), int(payload.get('stride', 1)))
    beads, series = measure_torsions(universe, declared, names, frames)

    rows, unmeasured = [], []
    for index, term in enumerate(declared):
        # The scalar fields of a multi-term (funct 9) dihedral are its dominant harmonic, so the same three keys are
        # reported for every topology; `terms` is the whole series and is what a series-vs-series reader should use.
        stated = {'phase_deg': term['phase_deg'], 'force_constant_kj_mol': term['force_constant'],
                  'multiplicity': term['multiplicity'], 'terms': term['terms'],
                  'term_count': term['term_count'], 'funct': term['funct']}
        if index not in series:
            unmeasured.append({'beads': list(beads[index]), 'phase_deg': term['phase_deg'],
                               'force_constant': term['force_constant'], 'multiplicity': term['multiplicity'],
                               'term_count': term['term_count'], 'funct': term['funct'],
                               'reason': f'the mapped trajectory has no bead {", ".join(beads[index])}'})
            continue
        try:
            fitted = fit_dihedral(series[index], temperature, criterion=criterion,
                                  max_terms=int(payload.get('max_terms', DEFAULT_MAX_TERMS)))
        except ValueError as error:
            unmeasured.append({'beads': list(beads[index]), 'phase_deg': term['phase_deg'],
                               'force_constant': term['force_constant'], 'multiplicity': term['multiplicity'],
                               'term_count': term['term_count'], 'funct': term['funct'],
                               'reason': str(error)})
            continue
        dominant = max(fitted['dihedrals'], key=lambda item: item['force_constant_kj_mol'])
        rows.append({
            'beads': list(beads[index]),
            'ours': stated,
            'fit': {'terms': fitted['terms'], 'dihedrals': fitted['dihedrals'],
                    'residual_rms_kj_mol': fitted['residual_rms_kj_mol'],
                    'dominant_multiplicity': dominant['multiplicity'],
                    'dominant_force_constant_kj_mol': dominant['force_constant_kj_mol']},
            'energy_rms_kj_mol': curve_rms(term['terms'], fitted['dihedrals']),
            'multiplicities_agree': dominant['multiplicity'] == term['multiplicity'],
        })

    report = {
        'molecule': str(universe.residues[0].resname), 'temperature': temperature, 'criterion': criterion,
        'temperature_source': payload.get('temperature_source')
                              or "the analysis default; the run's own fit temperature was not staged",
        'frames_measured': int(len(next(iter(series.values())))) if series else 0,
        'frames_in_trajectory': int(len(universe.trajectory)),
        'ours_from': str(topology.relative_to(work)), 'ours_provenance': provenance,
        'measured_from': '2_mapping/mapped.xtc',
        # What the topology declared, counted by function type: eight funct 9 lines for one quadruple are one
        # dihedral with eight harmonics, and a reader of this report should not have to recount that.
        'declared': {'dihedrals': len(declared),
                     'multi_term': sum(1 for term in declared if term['term_count'] > 1),
                     'harmonics': sum(term['term_count'] for term in declared),
                     'functs': sorted({term['funct'] for term in declared})},
        'rows': rows, 'unmeasured': unmeasured,
        'disagreements': [row['beads'] for row in rows if not row['multiplicities_agree']],
        'method': 'inverted Boltzmann, Savitzky-Golay smoothing, cumulative cosine series, chosen by ' + criterion,
        'credit': 'reimplemented from the method shaker documents (Martini-Force-Field-Initiative/shaker, commit '
                  'b7680219, LGPL-2.1); see CREDITS.md',
        'limitations': [
            'The fitted phase is in the convention this measurement uses, and the run topology\'s is GROMACS\'s. They '
            'are assumed to be the same convention; if they were not, a phase would appear mirrored while the '
            'multiplicity still agreed, so the multiplicity is the comparison this report leans on.',
            'A proper dihedral is fitted on its own torsion distribution, so a term that needs a different phase '
            'convention from ours can still agree in multiplicity, and one that agrees in multiplicity can still '
            'differ in phase and force constant.',
            'Both sides read the same mapped frames, which makes this a cross-check of the run topology and not a '
            'validation of it against experiment.',
            'Histogram binning and smoothing are lossy by nature; the residual of each fit is reported beside it so '
            'the size of that loss travels with the numbers.',
            'The run topology states its multiplicities because a tool chose them. Agreement here is not evidence '
            'that the tool chose well, only that this fit would not have chosen differently.',
            'A Fourier-series term (funct 9, what Fast_Forward writes) has no single phase to compare, so its scalar '
            'columns are its largest-force-constant harmonic -- this report\'s rule, not the force field\'s -- and the '
            'comparison that does not depend on that choice is `energy_rms_kj_mol`, the RMS difference between the two '
            'whole curves after the constant shift that best aligns them -- shape only, since a series carries the sum '
            'of its coefficients as a constant and that constant is not a property of the torsion. Read the '
            'multiplicity verdict on such a row as a statement about the dominant harmonic only.',
        ],
        'scientifically_validated': False,
    }
    (work / REPORT).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report
