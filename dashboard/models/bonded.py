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


def _function_options(kind):
    return [
        {'value': str(function), 'label': f'Function {function}',
         'description': spec['description'],
         'parameter_labels': spec['parameters']}
        for function, spec in FUNCTION_SPECS.get(kind, {}).items()
    ]


def _validate_edit(kind, function, parameters):
    try:
        function = int(function)
    except (TypeError, ValueError):
        raise ValueError('Bonded function must be an integer') from None
    expected = FUNCTIONS.get(kind, {}).get(function)
    if expected is None or not isinstance(parameters, list) or len(parameters) != expected:
        raise ValueError(f'Unsupported {kind} function or parameter count')
    values = []
    for value in parameters:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError('Bonded parameters must be finite numbers') from None
        if not math.isfinite(number):
            raise ValueError('Bonded parameters must be finite numbers')
        values.append(number)
    if kind == 'bonds' and not 0.01 <= values[0] <= 2:
        raise ValueError('Bond length outside allowed range')
    if kind == 'angles' and not 0 <= values[0] <= 180:
        raise ValueError('Bond angle outside allowed range')
    if kind == 'dihedrals' and not -180 <= values[0] <= 180:
        raise ValueError('Dihedral phase outside allowed range')
    if len(values) >= 2 and not 0 <= values[1] <= 100000:
        raise ValueError('Bonded force constant outside allowed range')
    if len(values) == 3 and (int(values[2]) != values[2] or not 1 <= values[2] <= 6):
        raise ValueError('Dihedral multiplicity must be an integer from 1 to 6')
    return function, values


def _format_number(value):
    return format(float(value), '.12g')


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


def apply_interaction_edits(topology, updates):
    """Apply function and numeric edits to ordinary flexible bonded terms."""
    if not isinstance(topology, str) or not isinstance(updates, list):
        raise ValueError('Interaction edits need topology text and a list')
    by_id = {}
    for update in updates:
        if not isinstance(update, dict) or not isinstance(update.get('id'), str):
            raise ValueError('Interaction edit needs an interaction ID')
        if update['id'] in by_id:
            raise ValueError('Duplicate interaction edit')
        parts = update['id'].split(':', 1)
        if len(parts) != 2 or parts[0] not in FUNCTIONS:
            raise ValueError('Only bonds, angles, and dihedrals can be edited')
        function, values = _validate_edit(parts[0], update.get('function'), update.get('parameters'))
        by_id[update['id']] = (function, values)
    section = None
    counts = {}
    output = []
    for raw in topology.splitlines():
        line = raw.split(';', 1)[0].strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().lower()
            output.append(raw)
            continue
        if section not in SECTION_WIDTHS or not line or line.startswith(('#', '[')):
            output.append(raw)
            continue
        count = counts.get(section, 0) + 1
        counts[section] = count
        interaction_id = f'{section}:{count}'
        update = by_id.get(interaction_id)
        if update is None:
            output.append(raw)
            continue
        if section not in FUNCTIONS:
            raise ValueError(f'Interaction cannot be edited: {interaction_id}')
        fields = line.split()
        width = SECTION_WIDTHS[section]
        if len(fields) < width + 1:
            raise ValueError(f'Unknown interaction: {interaction_id}')
        function, values = update
        replacement = fields[:width] + [str(function)] + [_format_number(value) for value in values]
        comment = raw.split(';', 1)[1] if ';' in raw else ''
        rewritten = ' '.join(replacement)
        if comment:
            rewritten += ' ;' + comment
        output.append(rewritten)
    known = {f'{kind}:{index}' for kind, count in counts.items() for index in range(1, count + 1)}
    unknown = set(by_id) - known
    if unknown:
        raise ValueError('Unknown interaction: ' + ', '.join(sorted(unknown)))
    return '\n'.join(output) + ('\n' if topology.endswith('\n') else '')


def apply_interaction_parameters(topology, updates):
    """Apply numeric parameters while preserving each term's function."""
    rows = {row['id']: row for row in parse_interactions(topology)}
    edits = []
    for update in updates:
        row = rows.get(update.get('id'))
        if row is None:
            edits.append({'id': update.get('id'), 'function': 0, 'parameters': update.get('parameters')})
        else:
            edits.append({'id': update['id'], 'function': row['function'], 'parameters': update.get('parameters')})
    return apply_interaction_edits(topology, edits)


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
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in params):
            raise ValueError('Bonded parameters must be finite numbers')
        if not 0 <= params[1] <= 100000:
            raise ValueError('Bonded force constant must be between 0 and 100000')
        lo, hi = {'bonds':(0.01,2), 'angles':(0,180), 'dihedrals':(-180,180)}[section]
        if not lo <= params[0] <= hi: raise ValueError('Bonded equilibrium value outside allowed range')
        if len(params)==3 and (int(params[2])!=params[2] or not 1<=params[2]<=6):
            raise ValueError('Periodic torsion multiplicity must be an integer from 1 to 6')
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
    validate(data)
    names = {b['name']:i for i,b in enumerate(data['beads'],1)}
    overrides = {}
    for term in data.get('bonded_overrides',[]):
        ids = tuple(names[n] for n in term['beads'])
        overrides[(term['section'], min(ids,ids[::-1]))] = term
    options = data.get('bonded_options',{})
    report = {'temperature_k':temperature, 'options':options, 'torsions':[], 'manual_overrides':[]}
    section = ''; lines = []; applied=set()
    for line in topology.splitlines():
        raw = line.split(';',1)[0].strip()
        if raw.startswith('['): section=raw.strip('[] ')
        arity = {'bonds':2,'angles':3,'dihedrals':4}.get(section)
        if raw and not raw.startswith(('[','#')) and arity:
            fields=raw.split(); ids=tuple(map(int,fields[:arity])); key=(section,min(ids,ids[::-1]))
            suffix = ' ;' + line.split(';',1)[1] if ';' in line else ''
            if section=='dihedrals' and options.get('torsion_model')=='circular-harmonic' and key not in overrides:
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
