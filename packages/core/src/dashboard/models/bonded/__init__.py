"""Validated manual bonded terms, GROMACS interaction I/O, and opt-in circular AA torsion fitting.

GROMACS function 2 uses V = k/2 * wrap(phi - phi0)^2 (radians).
Only flexible interactions are replaced; paper constraints and sites are immutable.
"""
import itertools
import math
from pathlib import Path

import numpy as np

SECTION_WIDTHS = {'bonds': 2, 'constraints': 2, 'angles': 3, 'dihedrals': 4}
FUNCTION_SPECS = {
    'bonds': {
        1: {'description': 'Harmonic',
            'parameters': ['length (nm)', 'force (kJ mol^-1 nm^-2)']},
    },
    'angles': {
        1: {'description': 'Harmonic',
            'parameters': ['angle (deg)', 'force (kJ mol^-1 rad^-2)']},
        2: {'description': 'GROMOS-96 cosine',
            'parameters': ['angle (deg)', 'force (kJ mol^-1)']},
        10: {'description': 'Restricted bending',
             'parameters': ['angle (deg)', 'force (kJ mol^-1)']},
    },
    'dihedrals': {
        1: {'description': 'Proper periodic',
            'parameters': ['phase (deg)', 'force (kJ mol^-1)', 'multiplicity']},
        2: {'description': 'Improper harmonic',
            'parameters': ['phase (deg)', 'force (kJ mol^-1 rad^-2)']},
        9: {'description': 'Proper periodic multi-term',
            'parameters': ['phase (deg)', 'force (kJ mol^-1)', 'multiplicity']},
    },
}
FUNCTION_PARAMETER_LABELS = {
    kind: {function: spec['parameters'] for function, spec in choices.items()}
    for kind, choices in FUNCTION_SPECS.items()
}
FUNCTIONS = {
    kind: {function: len(spec['parameters']) for function, spec in choices.items()}
    for kind, choices in FUNCTION_SPECS.items()
}

#: The editable parameter ranges, one row per (kind, function) and one entry per parameter, in the function's own
#: order. JSON-safe on purpose: lane D publishes it for the browser's parameter editor and ``validate_term`` reads the
#: same table, so the panel cannot offer a range the store would refuse.
#:
#: The bounds are the ones ``validate`` has always applied to a mapping override: a bond length and an angle in nm/deg,
#: a dihedral phase in deg, every force constant 0-100000, and a periodic multiplicity an integer 1-6. Constraints and
#: virtual sites are absent: their values are the mapping's readings, not a draft.
_RANGE_BOUNDS = {
    'bonds': {1: [(0.01, 2, False), (0, 100000, False)]},
    'angles': {
        1: [(0, 180, False), (0, 100000, False)],
        2: [(0, 180, False), (0, 100000, False)],
        10: [(0, 180, False), (0, 100000, False)],
    },
    'dihedrals': {
        1: [(-180, 180, False), (0, 100000, False), (1, 6, True)],
        2: [(-180, 180, False), (0, 100000, False)],
        9: [(-180, 180, False), (0, 100000, False), (1, 6, True)],
    },
}
PARAMETER_RANGES = {
    kind: {
        function: [{'min': low, 'max': high, 'integer': integer,
                    'label': label}
                   for (low, high, integer), label in zip(bounds, FUNCTION_PARAMETER_LABELS[kind][function])]
        for function, bounds in choices.items()
    }
    for kind, choices in _RANGE_BOUNDS.items()
}


def validate_term(kind, function, parameters):
    """Check one term's parameters against ``PARAMETER_RANGES`` and return them normalised.

    The single validator for a hand edit and for a mapping override: an unknown kind/function, a parameter count
    that does not belong to the function, a non-finite value, a value outside its range or a non-integer
    multiplicity is a ``ValueError`` naming the field. A constraint or a virtual site is not in the table, so the
    caller's own "not editable" sentence is the refusal it gets.
    """
    try:
        function = int(function)
    except (TypeError, ValueError):
        raise ValueError(f'Unsupported bonded function: {function!r}') from None
    bounds = PARAMETER_RANGES.get(kind, {}).get(function)
    if bounds is None:
        raise ValueError(f'Unsupported bonded function: {function!r} for {kind}')
    if not isinstance(parameters, list) or len(parameters) != len(bounds):
        raise ValueError(f'Function {function} of {kind} takes {len(bounds)} parameters')
    values = []
    for value, bound in zip(parameters, bounds):
        label = bound['label']
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'The {label} must be a finite number')
        if bound['integer'] and int(value) != value:
            raise ValueError(f"The {label} must be an integer from {bound['min']} to {bound['max']}")
        if not bound['min'] <= value <= bound['max']:
            raise ValueError(f"The {label} must be between {bound['min']} and {bound['max']}")
        values.append(int(value) if bound['integer'] else float(value))
    return values


def _function_options(kind):
    return [
        {'value': str(function), 'label': f'Function {function}',
         'description': spec['description'],
         'parameter_labels': spec['parameters']}
        for function, spec in FUNCTION_SPECS.get(kind, {}).items()
    ]


def parse_interactions(topology):
    """Parse bonded terms from a GROMACS ITP into UI-friendly records."""
    if not isinstance(topology, str):
        return []
    atom_names = {}
    section = None
    section_counts = {}
    rows = []
    for raw in topology.splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().lower()
            continue
        fields = line.split()
        if section == 'atoms' and len(fields) >= 5:
            try: atom_names[int(fields[0])] = fields[4]
            except ValueError: pass
        elif section in ('virtual_sitesn', 'virtual_sites3'):
            if len(fields) < (3 if section == 'virtual_sitesn' else 5):
                continue
            try:
                site, function = int(fields[0]), fields[1]
                if section == 'virtual_sitesn':
                    parents = [int(value) for value in fields[2:]]
                    params = []
                else:
                    parents = [int(value) for value in fields[2:5]]
                    params = fields[5:]
            except ValueError:
                continue
            section_counts[section] = section_counts.get(section, 0) + 1
            rows.append({'kind': section, 'indices': [site],
                         'beads': [atom_names.get(site, str(site))],
                         'function': function, 'parameters': params,
                         'parents': parents,
                         'parent_beads': [atom_names.get(i, str(i)) for i in parents],
                         'id': f"{section}:{section_counts[section]}"})
        elif section in SECTION_WIDTHS:
            width = SECTION_WIDTHS[section]
            if len(fields) < width + 1: continue
            try: indices = [int(x) for x in fields[:width]]
            except ValueError: continue
            params = fields[width:]
            function = params[0] if params else ''
            section_counts[section] = section_counts.get(section, 0) + 1
            rows.append({'kind': section, 'indices': indices,
                         'beads': [atom_names.get(i, str(i)) for i in indices],
                         'function': function,
                         'parameters': params[1:] if params else [],
                         'id': f"{section}:{section_counts[section]}",
                         'editable': section in FUNCTIONS,
                         'function_options': _function_options(section),
                         'parameter_labels': (FUNCTION_PARAMETER_LABELS.get(section, {}).get(int(function), [])
                                              if function.isdigit() else [])})
    return rows


def rewrite_interactions(topology, edits):
    """Replace edited terms' parameters in a topology, preserving every other byte of text.

    ``edits`` maps a term id (the ``kind:n`` ids ``parse_interactions`` produces) to its new parameter values. Only
    the fields after the atom indices and the stored function change; the leading whitespace and the trailing ``;``
    comment are kept, and every other line -- headers, ``#ifdef`` directives, comments, sections with no edit -- is
    copied through. The function is not editable, so it is read from the stored line rather than taken from the
    caller.

    The result is read back through ``parse_interactions``: the per-kind counts must be unchanged and every edited id
    must carry the requested values. A mismatch is a ``RuntimeError`` (a store defect), not a bad request; an unknown
    id is a ``ValueError``.
    """
    if not isinstance(topology, str):
        raise ValueError('A topology is required')
    wanted = {str(term_id): list(parameters) for term_id, parameters in (edits or {}).items()}
    if not wanted:
        return topology
    for term_id in wanted:
        if str(term_id).split(':', 1)[0] not in FUNCTIONS:
            raise ValueError(f'No editable term {term_id} in this topology')
    applied = set()
    section = None
    counts = {}
    lines = []
    for raw in topology.split('\n'):
        clean = raw.split(';', 1)[0].strip()
        replacement = None
        if clean and not clean.startswith('#'):
            if clean.startswith('[') and clean.endswith(']'):
                section = clean[1:-1].strip().lower()
            elif section in SECTION_WIDTHS:
                width = SECTION_WIDTHS[section]
                fields = clean.split()
                if len(fields) >= width + 1:
                    try:
                        indices = [int(value) for value in fields[:width]]
                    except ValueError:
                        indices = None
                    if indices is not None:
                        counts[section] = counts.get(section, 0) + 1
                        term_id = f'{section}:{counts[section]}'
                        parameters = wanted.get(term_id)
                        if parameters is not None:
                            prefix = raw[:len(raw) - len(raw.lstrip())]
                            suffix = ' ;' + raw.split(';', 1)[1] if ';' in raw else ''
                            rendered = ' '.join([*(str(index) for index in indices), fields[width],
                                                 *(f'{value:g}' for value in parameters)])
                            replacement = prefix + rendered + suffix
                            applied.add(term_id)
        lines.append(raw if replacement is None else replacement)
    missing = set(wanted) - applied
    if missing:
        raise ValueError(f'No editable term {sorted(missing)[0]} in this topology')
    rewritten = '\n'.join(lines)
    before = [(row['kind'], row['id']) for row in parse_interactions(topology)]
    after = {row['id']: row for row in parse_interactions(rewritten)}
    if [(row['kind'], row['id']) for row in parse_interactions(rewritten)] != before:
        raise RuntimeError('The edited topology did not read back with the same terms')
    for term_id, parameters in wanted.items():
        row = after.get(term_id)
        if row is None or any(abs(float(stored) - float(value)) > 1e-12
                              for stored, value in zip(row['parameters'], parameters)):
            raise RuntimeError('The edited topology did not read back as the store wrote it')
    return rewritten


def validate(data):
    options = data.get('bonded_options', {})
    if not isinstance(options, dict) or set(options)-{'torsion_model','torsion_scale'}:
        raise ValueError('Unknown bonded fitting option')
    if options.get('torsion_model', 'legacy') not in ('legacy', 'circular-harmonic'):
        raise ValueError('Unknown torsion model')
    scale = options.get('torsion_scale', 1)
    if type(scale) not in (int,float) or not math.isfinite(scale) or not 0.1 <= scale <= 3:
        raise ValueError('Torsion stiffness scale must be between 0.1 and 3')
    if 'torsion_scale' in options and options.get('torsion_model') != 'circular-harmonic':
        raise ValueError('Torsion scale requires circular-harmonic fitting')
    overrides = data.get('bonded_overrides', [])
    if not isinstance(overrides, list) or len(overrides)>300:
        raise ValueError('Bonded overrides must be a list of at most 300 terms')
    physical = {b['name'] for b in data['beads'] if not b.get('virtual_site')}
    constraints = {frozenset(p) for r in data.get('rings',[]) for p in itertools.combinations(r['beads'],2)}
    seen = set()
    for term in overrides:
        if not isinstance(term,dict) or set(term) != {'section','beads','function','parameters'}:
            raise ValueError('Each override needs section, beads, function and parameters')
        section = term['section']
        if not isinstance(section,str): raise ValueError('Bonded section must be a name')
        arity = {'bonds':2,'angles':3,'dihedrals':4}.get(section)
        names = term['beads']; func = term['function']; params = term['parameters']
        if not arity or not isinstance(names,list) or len(names)!=arity or any(not isinstance(n,str) or n not in physical for n in names) or len(set(names))!=arity:
            raise ValueError('Overrides must name distinct massive beads in a flexible bonded term')
        if section=='bonds' and frozenset(names) in constraints:
            raise ValueError('Paper ring constraints cannot be replaced by bond overrides')
        allowed = {'bonds':{1:2}, 'angles':{1:2,2:2,10:2}, 'dihedrals':{1:3,2:2,9:3}}[section]
        if type(func) is not int or func not in allowed or not isinstance(params,list) or len(params)!=allowed[func]:
            raise ValueError('Unsupported bonded function or parameter count')
        # One validator for a mapping override and a revision's hand edit: the ranges and the force/integer rules
        # cannot drift between the two doors.
        validate_term(section, func, params)
        key = (section,min(tuple(names),tuple(reversed(names))))
        if key in seen: raise ValueError('Duplicate bonded override')
        seen.add(key)


def circular_harmonic(degrees, temperature):
    phi = np.radians(np.asarray(degrees, dtype=float))
    if phi.ndim!=1 or len(phi)<3 or not np.isfinite(phi).all():
        raise ValueError('Torsion fit needs at least three finite AA samples')
    mean = np.mean(np.exp(1j*phi))
    if abs(mean)<0.1: raise ValueError('Broad or multimodal torsion needs a periodic model, not harmonic fitting')
    phase = np.angle(mean)
    variance = np.mean(np.angle(np.exp(1j*(phi-phase)))**2)
    if variance<1e-6: raise ValueError('AA torsion variance is too small for a flexible harmonic fit')
    return float(np.degrees(phase)), float(0.008314462618*temperature/variance)


def refine(topology, data, directory, temperature):
    """Rewrite a fitted topology's flexible terms from the mapping's own bonded options.

    **One fitted torsion is eight `funct 9` lines, and it is one interaction.** Fast-Forward writes a periodic
    dihedral as one cosine term per harmonic -- eight lines with the same four atoms. A circular-harmonic fit therefore
    rewrites the interaction **once**, from the first of those lines, and drops the siblings. Rewriting each line
    produced eight identical `funct 2` terms, so the stiffness a run simulated was eight times the one that was fitted
    and `bonded_fit.json` counted eight torsions for one (found 2026-11-09, pinned by
    `test_a_fitted_torsion_is_rewritten_once_not_once_per_harmonic`). The legacy model leaves every line as the fit
    wrote it.

    Grouping is per `[ dihedrals ]` block, so two molecule types carrying the same atom indices stay separate terms.
    """
    validate(data)
    names = {b['name']:i for i,b in enumerate(data['beads'],1)}
    overrides = {}
    for term in data.get('bonded_overrides',[]):
        ids = tuple(names[n] for n in term['beads'])
        overrides[(term['section'], min(ids,ids[::-1]))] = term
    options = data.get('bonded_options',{})
    report = {'temperature_k':temperature, 'options':options, 'torsions':[], 'manual_overrides':[]}
    section = ''; block = 0; lines = []; applied=set(); rewritten=set()
    for line in topology.splitlines():
        raw = line.split(';',1)[0].strip()
        if raw.startswith('['): section=raw.strip('[] '); block += 1
        arity = {'bonds':2,'angles':3,'dihedrals':4}.get(section)
        if raw and not raw.startswith(('[','#')) and arity:
            fields=raw.split(); ids=tuple(map(int,fields[:arity])); key=(section,min(ids,ids[::-1]))
            suffix = ' ;' + line.split(';',1)[1] if ';' in line else ''
            if section=='dihedrals' and options.get('torsion_model')=='circular-harmonic' and key not in overrides:
                # The second and later lines of one fitted torsion are the same interaction's other harmonics: the
                # first line becomes the single harmonic term and these lines are dropped, not rewritten again.
                if (block, key) in rewritten: continue
                rewritten.add((block, key))
                label = '_'.join(f'B{i:02d}' for i in ids)
                samples = np.loadtxt(Path(directory)/f'{label}_dihedrals.dat')
                phase,k = circular_harmonic(samples,temperature)
                k *= options.get('torsion_scale',1)
                line = ' '.join(map(str,ids))+f' 2 {phase:.8g} {k:.8g}'+suffix
                report['torsions'].append({'beads':list(ids),'phase_deg':phase,'k_kj_mol_rad2':k,'frames':len(samples)})
            if key in overrides:
                if key in applied: raise ValueError('Cannot override a multi-term interaction with one term')
                term=overrides[key]
                # Preserve existing orientation and comments for FF assessment labels.
                line=' '.join(map(str,ids))+f' {term["function"]} '+' '.join(f'{v:g}' for v in term['parameters'])+suffix
                applied.add(key); report['manual_overrides'].append(term)
        lines.append(line)
    if applied != overrides.keys(): raise ValueError('Override does not match an existing flexible topology term; edit connectivity first')
    if options.get('torsion_model')=='circular-harmonic' and not report['torsions'] and not any(t['section']=='dihedrals' for t in report['manual_overrides']):
        raise ValueError('Circular torsion fitting requested but topology has no torsions')
    return '\n'.join(lines)+'\n', report
