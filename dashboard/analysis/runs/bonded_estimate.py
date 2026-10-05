"""The equipartition estimator as arithmetic: k = R T / sigma^2, with the constraint verdict as a stated parameter.

Adapted from shaker (Martini-Force-Field-Initiative/shaker, commit b7680219) as a **reference implementation** rather
than a dependency: the arithmetic is small and standard, so this module is this repository's and shaker is cited.
`test_bonded_estimate_reference.py` pins it to shaker's own numbers on a real case before any analysis relies on it.

**The constraint threshold is a parameter, not a constant.** shaker defaults to 25000; this repository's pipeline
passes `-constraints 10000` to Fast_Forward. That difference is not cosmetic: DDM's inter-ring link fitted near 12965,
so it became a *rigid constraint* under one convention and a *flexible spring* under the other, and which one a run
used has to travel with the numbers the run produced.

Angles are the trap here. GROMACS writes an angle in **degrees** and its force constant per **radian**, so a spread
measured in degrees is converted before the division -- mixing them is a factor of (180/pi)^2, about 3283, hidden
inside a number that still looks like a force constant.
"""
import json
from pathlib import Path

import MDAnalysis as mda
import numpy as np

R_GAS = 8.314462618  # J / mol / K
DEFAULT_CONSTRAINT_THRESHOLD = 10000.0
DEFAULT_TEMPERATURE = 303.15
REPORT = 'bonded-cross-check.json'


def circular_mean_and_spread(angles_deg):
    """The mean and spread of wrapped angles, taken around the circle.

    `+179` and `-179` are two degrees apart, not 358. An arithmetic mean puts them at 0, which is the far side of the
    circle, and it reports a wildly stretched term for a molecule that never moved. The spread comes back through the
    mean resultant length, the same quantity a von Mises fit is built on.
    """
    radians = np.radians(np.asarray(angles_deg, dtype=float))
    mean = np.arctan2(float(np.sin(radians).mean()), float(np.cos(radians).mean()))
    resultant = float(np.hypot(np.sin(radians).mean(), np.cos(radians).mean()))
    # 1 is no spread at all; 0 is a uniform circle, which no finite force constant describes.
    spread = float(np.sqrt(-2.0 * np.log(resultant))) if resultant > 0 else float(np.pi)
    return float(np.degrees(mean)), float(np.degrees(spread))


def force_constant(sigma, temperature, *, kind='bond'):
    """`k = R T / sigma^2` in the units GROMACS writes for that kind of term.

    A bond's constant is per nm^2 and `sigma` is a length in nm. An angle's is per rad^2, so `sigma` arrives in
    degrees and is converted. `sigma` of zero is refused rather than answered with an infinity: a term with no spread
    is a constraint, and saying so is the caller's job.
    """
    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError('a spread of zero has no equipartition force constant; that term is a constraint')
    spread = np.radians(float(sigma)) if kind == 'angle' else float(sigma)
    return float(R_GAS * float(temperature) / 1000.0 / spread ** 2)


def estimate_bond(lengths_nm, temperature, *, constraint_threshold=DEFAULT_CONSTRAINT_THRESHOLD):
    """A bond's length, its spread, and the force constant that spread implies."""
    values = np.asarray(lengths_nm, dtype=float)
    if values.size < 2:
        # One frame has no spread to measure, and `std` would answer 0.0 for it -- which reads as a rigid bond.
        raise ValueError('a spread needs at least two frames, not one')
    sigma = float(values.std(ddof=1))
    return {'kind': 'bond', 'value': float(values.mean()), 'sigma': sigma, 'sigma_units': 'nm',
            'force_constant': force_constant(sigma, temperature, kind='bond'),
            'force_constant_units': 'kJ/mol/nm^2', 'frames': int(values.size),
            'temperature': float(temperature), 'threshold': float(constraint_threshold),
            'constraint': force_constant(sigma, temperature, kind='bond') > float(constraint_threshold)}


def estimate_angle(angles_deg, temperature, *, constraint_threshold=DEFAULT_CONSTRAINT_THRESHOLD):
    """An angle's mean, its spread, and the force constant, all taken around the circle."""
    values = np.asarray(angles_deg, dtype=float)
    if values.size < 2:
        raise ValueError('a spread needs at least two frames, not one')
    value, sigma = circular_mean_and_spread(values)
    k = force_constant(sigma, temperature, kind='angle')
    return {'kind': 'angle', 'value': value, 'sigma': sigma, 'sigma_units': 'degrees',
            'force_constant': k, 'force_constant_units': 'kJ/mol/rad^2', 'frames': int(values.size),
            'temperature': float(temperature), 'threshold': float(constraint_threshold),
            'constraint': k > float(constraint_threshold)}


# --- the fitted topology, and the comparison ----------------------------------------------------------------

#: `[ section ]` names a topology can carry that the equipartition estimator can read back. `[ angles ]` is absent on
#: purpose: it is a triple, and a triple is measured as an angle rather than as a distance, so it is a separate piece
#: of work rather than something to be silently skipped or silently read as a bond.
TOPOLOGY_SECTIONS = {'bonds': 'bond', 'constraints': 'constraint'}


def read_topology_terms(path, kinds=('bond', 'constraint')):
    """The bonded terms a topology file declares -- `parse_topology_terms` for text already in hand."""
    return parse_topology_terms(Path(path).read_text(), kinds=kinds, origin=str(path))


def parse_topology_terms(text, kinds=('bond', 'constraint'), origin='<topology>'):
    """The bonded terms a GROMACS topology declares, as `{'kind', 'atoms', 'value', 'force_constant', 'line'}`.

    A bond is `i j funct b0 kb` and a constraint is `i j funct b0`. The function type is **checked** and refused
    rather than assumed: a topology that switched to a non-harmonic `funct` would otherwise be read as a harmonic term
    with a meaningless length, and the comparison would report a difference that is really a different question.
    """
    section = None
    terms = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        if line.startswith('['):
            section = TOPOLOGY_SECTIONS.get(line.strip('[] \t').split()[0])
            continue
        if section not in kinds:
            continue
        fields = line.split()
        expected = 5 if section == 'bond' else 4
        if len(fields) < expected:
            raise ValueError(f'{origin}:{number}: a {section} needs {expected} fields, found {len(fields)}')
        if fields[2] != '1':
            raise ValueError(f'{origin}:{number}: funct {fields[2]} is not harmonic, and equipartition reads '
                             'harmonic terms only')
        try:
            atoms = tuple(int(index) for index in fields[:2])
            value = float(fields[3])
            constant = float(fields[4]) if section == 'bond' else None
        except ValueError as error:
            raise ValueError(f'{origin}:{number}: {error}') from error
        terms.append({'kind': section, 'atoms': atoms, 'value': value, 'force_constant': constant, 'line': number})
    return terms


def pair_series(universe, pairs, frames=slice(0, None, 1)):
    """Every declared pair's distance per frame, in nanometres, from one read of the trajectory.

    Only the pairs asked for are measured: for an 11-bead molecule every pair is 55, most of which no topology
    declares, and measuring them would cost five times what the comparison needs to answer.
    """
    order = {name: index for index, name in enumerate(universe.atoms.names)}
    collected = {pair: [] for pair in pairs if all(name in order for name in pair)}
    for frame in range(*frames.indices(len(universe.trajectory))):
        universe.trajectory[frame]
        # MDAnalysis reports angstroms; every length in this repository is nanometres.
        positions = universe.atoms.positions / 10.0
        for pair in collected:
            collected[pair].append(
                float(np.linalg.norm(positions[order[pair[0]]] - positions[order[pair[1]]])))
    return {pair: np.asarray(values, dtype=float) for pair, values in collected.items()}


def cross_check(work, payload=None):
    """Our fitted topology against an independent equipartition estimate, term by term, from the same frames.

    Both sides see **the same input on purpose**. The fitted constants came from a fit to the mapped trajectory, so the
    estimate is measured from that same mapped trajectory rather than from the CG simulation. Measuring the simulation
    would answer a different question -- whether the fitted model reproduces itself -- and would agree by construction.

    Rows say which of the two sides calls each term a constraint, because that is the disagreement that matters: a
    term we write as a rigid constraint and the measurement reads as a spring is a different molecule, and the numbers
    alone would not show it.
    """
    work = Path(work)
    payload = dict(payload or {})
    temperature = float(payload.get('temperature', DEFAULT_TEMPERATURE))
    threshold = float(payload.get('constraint_threshold', DEFAULT_CONSTRAINT_THRESHOLD))
    mapped = work / '2_mapping'
    universe = mda.Universe(str(mapped / 'mapped.gro'), str(mapped / 'mapped.xtc'))
    names = list(universe.atoms.names)
    residue = str(universe.residues[0].resname)

    fit = sorted((work / '3_initial_CG').glob('*_ff_inter.itp'))
    drafted = sorted((work / '3_initial_CG').glob('*initial*.itp'))
    if fit:
        topology, provenance = fit[0], 'the Fast_Forward fit'
    elif drafted:
        topology, provenance = drafted[0], 'the draft geometry, because no fit has been run for this job'
    else:
        raise ValueError('no topology to compare: neither a fit nor a draft is in this run')
    terms = read_topology_terms(topology)

    # The topology's indices are positions in the coordinate file it is applied to, so the bead names come from the
    # mapped trajectory's own atom order -- the same file the estimate is measured from, not a second file assumed
    # to agree with it.
    declared = {}
    for term in terms:
        declared[term['line']] = tuple(names[index - 1] if 0 < index <= len(names) else f'#{index}'
                                       for index in term['atoms'])
    frames = slice(int(payload.get('start', 0)), payload.get('stop'), int(payload.get('stride', 1)))
    series = pair_series(universe, set(declared.values()), frames)

    rows, unmeasured = [], []
    for term in terms:
        pair = declared[term['line']]
        if pair not in series:
            absent = [name for name in pair if name.startswith('#') or name not in names]
            unmeasured.append({
                'kind': term['kind'], 'beads': list(pair), 'value': term['value'],
                'force_constant': term['force_constant'],
                'reason': (f'the mapped trajectory has no bead {", ".join(absent)}' if absent
                           else f'the pair {pair[0]}-{pair[1]} could not be measured')})
            continue
        try:
            estimate = estimate_bond(series[pair], temperature, constraint_threshold=threshold)
        except ValueError as error:
            unmeasured.append({'kind': term['kind'], 'beads': list(pair), 'value': term['value'],
                               'force_constant': term['force_constant'], 'reason': str(error)})
            continue
        ours_is_constraint = term['kind'] == 'constraint' or (term['force_constant'] or 0.0) > threshold
        rows.append({
            'kind': term['kind'], 'beads': list(pair),
            'ours': {'value': term['value'], 'force_constant': term['force_constant'],
                     'constraint': ours_is_constraint},
            'estimate': {'value': estimate['value'], 'sigma': estimate['sigma'],
                         'force_constant': estimate['force_constant'], 'constraint': estimate['constraint']},
            'delta_value': estimate['value'] - term['value'],
            'ratio_force_constant': (None if not term['force_constant']
                                     else estimate['force_constant'] / term['force_constant']),
            'verdicts_agree': ours_is_constraint == estimate['constraint'],
        })

    record = {
        'molecule': residue, 'temperature': temperature, 'threshold': threshold,
        'temperature_source': payload.get('temperature_source')
                              or 'the analysis default; the run\'s own fit temperature was not staged',
        'threshold_source': 'this repository\'s Fast_Forward convention; shaker defaults to 25000',
        'frames_measured': int(len(next(iter(series.values())))) if series else 0,
        'frames_in_trajectory': int(len(universe.trajectory)),
        'ours_from': str(topology.relative_to(work)), 'ours_provenance': provenance,
        'estimate_from': '2_mapping/mapped.xtc',
        'estimate_provenance': 'equipartition k = R T / sigma^2 per term, independently of the fit',
        'rows': rows, 'unmeasured': unmeasured,
        'disagreements': [row['beads'] for row in rows if not row['verdicts_agree']],
        'limitations': [
            'Bonds and constraints only: an angle is a triple measured as an angle, so it is not in this report yet.',
            'Both sides read the same mapped frames, which makes this a cross-check of the fit and not a validation of '
            'the model against experiment.',
            'A term the fit wrote with a force constant above the threshold is counted as a constraint here, whatever '
            'Fast_Forward chose to do with it; under shaker\'s 25000 some of those would be springs instead.',
            'The estimate is per term and independent, the fit is a coupled distribution-matching fit, so the force '
            'constants are not expected to be equal even where both are right.',
        ],
        'scientifically_validated': False,
    }
    (work / REPORT).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record
