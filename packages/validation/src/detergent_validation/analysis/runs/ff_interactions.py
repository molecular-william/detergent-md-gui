"""Fast-Forward's interaction distributions beside the mapping comparison's own terms.

The analysis reads what Fast-Forward already measured, in the two shapes a completed AA-to-CG run can have:

* **fitted** -- stage 3 ran `ff_inter`, so the reference histograms are beside the fitted topology:
  `3_initial_CG/<name>_<kind>_distr.dat`.
* **consumed** -- stage 3 consumed a mapping's current parameterization revision; the reference histograms are the
  revision's own files in the immutable parameterization store, named by
  `3_initial_CG/parameterization_used.json` (`reference_distributions`).

Stage 5's `5_assessment/<name>_<kind>_distr.dat` is the **simulated CG** side in both shapes, and
`5_assessment/report_interactions.out` carries Fast-Forward's own Hellinger distance and score per term. The record
states which shape it read and names any absent side rather than drawing one curve as a comparison.

Only text files are read. `ff_inter`/`ff_assess` also write pickles (`plot_data.p`), which the web process must never
unpickle; the `.dat`/`.out` files carry the same numbers.

Scope is a **bonded term** (bond, angle, proper dihedral). A non-bonded bead-pair distance is a different record; the
shape here is a list of terms with a `scope` field so such a view can be added without relabelling these.
"""
import json
from pathlib import Path

from dashboard.analysis.runs import layout

MODEL = '2_mapping/model.json'
USED = '3_initial_CG/parameterization_used.json'
REPORT = '5_assessment/report_interactions.out'
RECORD = 'ff-interactions.json'

SECTIONS = ('bonds', 'angles', 'dihedrals')
#: FF writes one interaction family per suffix; the pairwise-distance family is `_distances_distr.dat` and is not a
#: bonded term, so it is deliberately not staged here.
SUFFIX = {'bonds': '_bonds_distr.dat', 'angles': '_angles_distr.dat', 'dihedrals': '_dihedrals_distr.dat'}


def _interaction_files(directory):
    """``{name: {'section': section, 'path': path}}`` for the interaction families in one directory.

    The suffix carries the section, and it is stripped from the name because Fast-Forward's report names the same
    term without it. Keeping the section beside the path is what lets a 3-bead term stay an angle instead of
    falling back to a default section.
    """
    directory = Path(directory)
    found = {}
    if not directory.is_dir():
        return found
    for section, suffix in SUFFIX.items():
        for path in sorted(directory.glob('*' + suffix)):
            name = path.name[:-len(suffix)]
            # A pairwise file is `1_B01_1_B02_distances_distr.dat`; it never ends in one of these suffixes, but a
            # name carrying the distance family's `1_` prefix is refused as a belt too.
            if name and not name.startswith('1_'):
                found[name] = {'section': section, 'path': path}
    return found


def _parse_distr(path):
    """Two columns: bin centre and probability density. A malformed row is refused rather than skipped silently."""
    x, density = [], []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        clean = line.strip()
        if not clean or clean.startswith(('#', '@')):
            continue
        fields = clean.split()
        if len(fields) < 2:
            raise ValueError(f'{path}:{number}: expected two columns')
        try:
            x.append(float(fields[0])); density.append(float(fields[1]))
        except ValueError as error:
            raise ValueError(f'{path}:{number}: {error}') from error
    if len(x) < 2:
        raise ValueError(f'{path}: fewer than two finite rows')
    return {'x': x, 'density': density}


def _parse_report(path):
    """Fast-Forward's report: per section, ``name -> (hellinger, score)``, plus the overall mean ± sem.

    The report's first number is the Hellinger distance (0 identical, 1 no overlap) and the parenthesised second is
    the tool's own score. The dashboard's overlap coefficient is a different metric and is not in this file.
    """
    sections, current = {}, None
    overall = None
    for line in Path(path).read_text().splitlines():
        clean = line.strip()
        if clean in SECTIONS:
            current = clean; sections.setdefault(clean, {})
            continue
        if clean.startswith('Overall Score') and overall is None:
            # "Overall Score : 0.238 ± 0.0208"
            overall = clean.split(':', 1)[1].strip() if ':' in clean else None
            continue
        if current is None or ':' not in clean:
            continue
        name, values = clean.split(':', 1)
        fields = values.split()
        try:
            hellinger = float(fields[0]); score = float(fields[1].strip('()'))
        except (IndexError, ValueError):
            continue
        sections[current][name.strip()] = {'hellinger': hellinger, 'ff_score': score}
    return {'sections': sections, 'overall': overall}


def _label_map(model):
    """The FF token (`B01`) to the comparison's own label (`(1,A)`), from the run's model."""
    labels = {}
    for index, bead in enumerate(model.get('beads') or [], 1):
        name = str(bead.get('export_name') or f'B{index:02d}')
        # A tail bead has a name but no residue/letter; the comparison labels it `(1,TAIL1)`, so the fallback uses
        # the bead's own name under residue 1 rather than dropping the token.
        residue = bead.get('residue') if bead.get('residue') is not None else 1
        letter = bead.get('letter') or bead.get('name')
        if letter:
            labels[name] = f'({residue},{letter})'
    return labels


def _source_record(work, consumed):
    """Where the reference side came from, in the record's own words."""
    if consumed:
        used = json.loads((work / USED).read_text())
        return {'from': 'parameterization store', 'revision': used.get('revision'),
                'engine': used.get('engine'), 'fitted_into_this_run': bool(used.get('fitted')),
                'record': USED}
    temperature = None
    fit = work / '3_initial_CG/bonded_fit.json'
    if fit.is_file():
        try:
            temperature = json.loads(fit.read_text()).get('temperature_k')
        except ValueError:
            temperature = None
    return {'from': 'stage 3 ff_inter', 'fit_temperature_k': temperature}


def sources(run_dir, payload=None):
    """Stage the text distributions and the report; for a consuming run, the revision's own histograms too.

    The store is outside the run, so its histograms cannot be named by a source pattern. They are read from
    `parameterization_used.json` and staged under `store/`, which is what lets the worker record their digests in
    `sources.json` and the producer read them from its own work directory. A store file that is gone is skipped; the
    record's `reference_missing` then names the side, rather than the whole analysis failing.
    """
    run = Path(run_dir)
    stages = layout.stage_root(run)
    entries = {}

    def add(relative, path):
        path = Path(path)
        if path.is_file():
            entries[relative] = path

    add(MODEL, stages / MODEL)
    add(USED, stages / USED)
    add(REPORT, stages / REPORT)
    add('3_initial_CG/bonded_fit.json', stages / '3_initial_CG/bonded_fit.json')
    for entry in _interaction_files(stages / '5_assessment').values():
        add(f'5_assessment/{entry["path"].name}', entry['path'])
    for entry in _interaction_files(stages / '3_initial_CG').values():
        add(f'3_initial_CG/{entry["path"].name}', entry['path'])
    used = stages / USED
    if used.is_file():
        try:
            record = json.loads(used.read_text())
        except ValueError:
            record = {}
        for entry in record.get('reference_distributions') or []:
            path = Path(str(entry.get('name') or ''))
            if not path.is_file() or not any(path.name.endswith(suffix) for suffix in SUFFIX.values()):
                continue
            add(f'store/{path.name}', path)
    return entries


def publish(work, payload=None):
    """Read the staged Fast-Forward outputs and publish one record of per-term distributions and metrics."""
    work = Path(work)
    consumed = (work / USED).is_file()
    simulated = _interaction_files(work / '5_assessment')
    reference = _interaction_files(work / 'store' if consumed else work / '3_initial_CG')
    model_path = work / MODEL
    model = json.loads(model_path.read_text()) if model_path.is_file() else {}
    labels = _label_map(model)
    report = _parse_report(work / REPORT) if (work / REPORT).is_file() else {'sections': {}, 'overall': None}

    names = sorted(set(simulated) | set(reference))
    terms = []
    for name in names:
        found = simulated.get(name) or reference.get(name)
        section = found['section']
        tokens = name.split('_')
        term = {'name': name, 'section': section, 'beads': tokens,
                'label': ' - '.join(labels.get(token, token) for token in tokens),
                'unit': 'nm' if section == 'bonds' else 'degrees'}
        metrics = report['sections'].get(section, {}).get(name)
        if metrics:
            term.update(metrics)
        if name in reference:
            term['reference'] = _parse_distr(reference[name]['path'])
        else:
            term['reference_missing'] = ('the consumed revision recorded no reference histogram for this term'
                                         if consumed else 'this run fitted no reference histogram for this term')
        if name in simulated:
            term['simulated'] = _parse_distr(simulated[name]['path'])
        else:
            term['simulated_missing'] = 'the CG assessment published no simulated histogram for this term'
        terms.append(term)

    record = {
        'schema_version': 1,
        'scope': 'bonded-terms',
        'available': bool(terms),
        'source': 'consumed' if consumed else ('fitted' if reference else 'unknown'),
        'reference': _source_record(work, consumed),
        'simulated': {'from': 'stage 5 ff_assess', 'report': REPORT},
        'metrics': {
            'hellinger': "Fast-Forward's Hellinger distance between the reference and simulated histograms; "
                         '0 identical, 1 no overlap. Lower is closer.',
            'ff_score': "Fast-Forward's score for the same term (the report's parenthesised second number).",
            'overlap': 'The dashboard mapping comparison\u2019s overlap coefficient (histogram intersection) is a '
                       'different metric and is not in this record.',
        },
        'overall': report.get('overall'),
        'terms': terms,
        'scientifically_validated': False,
        'interpretation': 'The distributions are the run\u2019s own Fast-Forward reference and its CG assessment. '
                          'Agreement is internal consistency, not experimental validation.',
    }
    if not terms:
        record['reason'] = ('No Fast-Forward interaction distributions were staged for this run. The assessment '
                            'may have been skipped, or stage 3 consumed a revision that recorded none.')
    (work / RECORD).write_text(json.dumps(record, indent=2) + '\n')
    return record
