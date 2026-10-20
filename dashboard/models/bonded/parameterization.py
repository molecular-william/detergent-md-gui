"""A mapping's parameterization: its revisions, what produced each, and what a run reads.

D1 of `docs/design/2026-10-16-parameterization-and-new-run.md`: the parameterization belongs to the
mapping and the bonded states become its revisions. A run consumes a *model* -- a mapping plus its
current revision -- and never re-fits a parameterized one, so there is no bonded-parameter control
on the run panel and its absence is the point.

One document per mapping holds every revision and which of them is current. Two identities are
recorded and only one selects the file, which is the doctrine `bonded.states` already keeps: the
*candidate* identity hashes the name and answers provenance, and the *content* identity ignores it,
so a renamed candidate keeps its fitted revisions instead of orphaning them. A revision fitted
against one candidate is therefore readable for a rename of it, and not for a mapping whose beads,
rings or connections changed.

The engine is recorded with what it saw, because a force constant without its ensemble is not a
measurement: `-constraints 10000` decides whether a fitted pair becomes a constraint or a spring,
and BARTENDER takes forty seconds against one trajectory and four hundred against another.

`fitting.py` produces a revision; this module stores one, and is the whole reader a run needs.
"""
from __future__ import annotations

import itertools
import json
import math
import re
import shutil
from pathlib import Path

from ... import files, paths
from .. import mappings
from . import parse_interactions

#: The engines a parameterization can be produced by (D3). Each names the ensemble it saw on its
#: result, and each has one label published for the panel; the labels live here rather than in the
#: web layer so a new engine is one edit and the route cannot invent a fourth.
ENGINES = ('fast-forward', 'bartender')

ENGINE_LABELS = {
    'fast-forward': 'Fast-Forward fit (ff_inter)',
    'bartender': 'BARTENDER fit (-refit -owntraj)',
}

#: What each engine's terms are called in the `source` column of the interactions table.
ENGINE_SOURCES = {'fast-forward': 'ff_inter', 'bartender': 'bartender'}

#: The provenance of a term that came from the mapping rather than from an engine, and of one the
#: automatic draft could not find a reference for. Both are named so a hand-edited row is visible.
MAPPING_SOURCE = 'mapping'
MANUAL_SOURCE = 'manual'
GEOMETRY_SOURCE = 'geometry'

CHECKS = ('dihedral-fit', 'bonded-cross-check')

TORSION_MODELS = ('legacy', 'circular-harmonic')

#: The default `-constraints` threshold, which is Fast_Forward's own default and the value every
#: run here passes. shaker defaults to 25000, and the difference is not cosmetic: DDM's inter-ring
#: link fitted near 12965, so the same fit is a rigid constraint under one and a spring under the
#: other. It is recorded with every revision because it decides what the model *is*.
DEFAULT_CONSTRAINTS = 10000.0

DEFAULT_TEMPERATURE = 300.0

_OPTION_KEYS = ('constraints_threshold', 'temperature_k', 'torsion_model', 'torsion_scale')


def storage_root() -> Path:
    """Where parameterization records live: one directory beside the mapping drafts.

    `paths.Paths` gains no property for this: the store is this module's, it is derived from the
    workspace the application was built with, and a second path property is a second thing to keep
    in step with the workspace selector.
    """
    return paths.current().workspace / 'parameterizations'


def records_root() -> Path:
    return storage_root() / 'records'


def work_root() -> Path:
    """Where a fit job's working directory lives: the frames it built, the engine's output, the checks."""
    return storage_root() / 'work'


def _validate_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Invalid mapping content identity')
    return value


def _path(mapping) -> Path:
    """This mapping's record, or the one written before numbers were normalised, or where a new one goes.

    `identity.candidate_identity` now hashes `1` and `1.0` alike, so a mapping that was fitted before that change
    is addressed by a digest its record does not carry. The legacy digest is tried second, and only when the first
    names no file: a record already on disk stays findable, and a mapping fitted since is untouched by the fallback.
    """
    path = records_root() / f'{content_identity(mapping)}.json'
    if path.is_file():
        return path
    legacy = records_root() / f'{mappings.legacy_content_identity(mapping)}.json'
    return legacy if legacy.is_file() else path


def identities(mapping) -> dict:
    """The two identities a revision records: how it is found, and which candidate produced it."""
    if not isinstance(mapping, dict):
        raise ValueError('A mapping is required to address its parameterization')
    return {'mapping_hash': mappings.candidate_identity(mapping),
            'mapping_content_hash': mappings.content_identity(mapping)}


def content_identity(mapping) -> str:
    return _validate_id(mappings.content_identity(mapping))


def default_options(mapping=None) -> dict:
    """The options a job starts from: the mapping's own torsion model, and this repository's threshold.

    D4a: the refinement is driven by the mapping and never by a run setting, because it changes the
    topology's terms and the mapping is what gets hashed into a run. So the torsion model's default
    is read off the mapping; a request may still choose another one, and the revision records the
    one it used.
    """
    declared = mapping.get('bonded_options') if isinstance(mapping, dict) else None
    declared = declared if isinstance(declared, dict) else {}
    return {'constraints_threshold': DEFAULT_CONSTRAINTS, 'temperature_k': DEFAULT_TEMPERATURE,
            'torsion_model': declared.get('torsion_model', 'legacy'),
            'torsion_scale': float(declared.get('torsion_scale', 1.0))}


def normalise_options(mapping, options=None) -> dict:
    """The four options a revision records, checked here rather than trusted from a caller.

    The rules are `bonded.validate`'s, which already guards the same two `bonded_options` keys at the
    point a mapping saves them; repeating them is deliberate, because this is the door a job comes
    through and a scale outside 0.1-3 or a torsion model that is not one of the two must not reach a
    stored revision.
    """
    values = default_options(mapping)
    for key, value in (options or {}).items():
        if key not in _OPTION_KEYS:
            raise ValueError(f'Unknown parameterization option: {key}')
        if key == 'torsion_model':
            if value not in TORSION_MODELS:
                raise ValueError('Unknown torsion model')
            values[key] = value
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{key} must be a finite number')
        values[key] = float(value)
    if values['constraints_threshold'] <= 0:
        raise ValueError('The constraint threshold must be positive')
    if not 0 < values['temperature_k'] <= 1000:
        raise ValueError('The fit temperature must be between 0 and 1000 K')
    if not 0.1 <= values['torsion_scale'] <= 3:
        raise ValueError('Torsion stiffness scale must be between 0.1 and 3')
    if values['torsion_model'] != 'circular-harmonic' and values['torsion_scale'] != 1.0:
        raise ValueError('Torsion scale requires circular-harmonic fitting')
    return {key: values[key] for key in _OPTION_KEYS}


def _empty(identities_) -> dict:
    return {**identities_, 'revision': 0, 'current': None, 'revisions': []}


def empty_document(mapping) -> dict:
    """The document a mapping with no record answers with: no revisions, and nothing current."""
    return _empty(identities(mapping))


def document(mapping) -> dict:
    """Every revision of this mapping, or an empty document when it has none.

    A record whose name no identity can address, or whose JSON does not parse, is a record nothing can
    read: it is refused rather than reported as a mapping with no parameterization, because the two
    mean different things to a run -- one re-fits, the other is a fit that was made and lost.
    """
    content = content_identity(mapping)
    path = _path(mapping)
    if not path.is_file():
        return empty_document(mapping)
    record = _read(path)
    # A record written before numbers were normalised carries the legacy digest, and `_path` has already decided the
    # file is this mapping's -- by its name, from this mapping. Accepting that digest here keeps such a record readable
    # without letting a record address itself: either digest is one this mapping computes for itself.
    acceptable = {content, mappings.legacy_content_identity(mapping)}
    if record.get('mapping_content_hash') not in acceptable:
        raise ValueError('Parameterization record belongs to another mapping')
    return record


def _read(path) -> dict:
    try:
        record = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f'Unreadable parameterization record: {path.name}') from exc
    if not isinstance(record, dict):
        raise ValueError('Parameterization record must be an object')
    return record


def one(content_hash) -> dict:
    """The record a content identity addresses, for a reader that holds hashes and not a mapping.

    The revision strip and the run panel both work from hashes: the strip is addressed by the candidate
    the workspace already loaded, and a run's manifest carries the hashes it was prepared with. An
    unknown hash answers with an empty document rather than an error, because "this model has no
    parameterization" is the state a caller is asking about.
    """
    content = _validate_id(content_hash)
    path = records_root() / f'{content}.json'
    if not path.is_file():
        return _empty({'mapping_hash': None, 'mapping_content_hash': content})
    return _read(path)


def records() -> list:
    """Every stored record, newest first, for a listing that has no mapping in hand."""
    root = records_root()
    if not root.is_dir():
        return []
    found = []
    for path in sorted(root.glob('*.json')):
        try:
            found.append(_read(path))
        except ValueError:
            continue
    found.sort(key=lambda record: record.get('updated_at') or '', reverse=True)
    return found


# --- deletion: a mapping's parameterization goes when the mapping does ---------------------------------


def delete(content_hash) -> dict:
    """Remove a mapping's parameterization: its record, every revision in it, and what was built for it.

    A revision is a field of the record rather than a file of its own, so removing the record removes
    the whole history at once. What sits beside it under the same storage root is removed with it:
    the fit jobs that produced it (`fitting.jobs_root`, which is this root's `jobs/`) and the
    (mapping, AA reference) working directories those jobs built (`work_root`). Both are keyed by the
    same content identity this record is keyed by, which is why this module is the one that can
    delete them and `fitting.py` does not need to know a mapping was deleted.

    Idempotent by design: a content identity with no record removed nothing, and that is an answer
    rather than an error. The caller (`mappings.store.delete_draft`) asks after every save, and most
    mappings were never fitted. What was removed is returned rather than assumed, because a caller
    that reported a guess would be reporting a guess.
    """
    content = _validate_id(content_hash)
    removed = {'content_hash': content, 'deleted': False, 'revisions': [], 'jobs': [], 'work': []}
    path = records_root() / f'{content}.json'
    if path.is_file():
        try:
            revisions = [item.get('revision') for item in (_read(path).get('revisions') or [])
                         if isinstance(item, dict)]
        except ValueError:
            # A record nothing can read is still this mapping's record: remove it, and report no
            # revision numbers rather than refusing to delete what the caller already decided on.
            revisions = []
        path.unlink()
        removed.update(deleted=True, revisions=revisions)
    removed['jobs'] = _delete_jobs(content)
    removed['work'] = _delete_work(content)
    removed['deleted'] = removed['deleted'] or bool(removed['jobs'] or removed['work'])
    return removed


def _delete_jobs(content) -> list:
    """The fit jobs of this mapping, removed with it; each job's id is returned.

    A job carries the same two identities a revision does, and `fitting.jobs` decides which jobs are a
    model's by content (compatibility) or candidate (provenance). Content is the one this deletion can
    honour: it is the identity the record was keyed by, so it is the identity the jobs are matched by.
    """
    root = storage_root() / 'jobs'
    if not root.is_dir():
        return []
    removed = []
    for path in sorted(root.glob('*.json')):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or record.get('mapping_content_hash') != content:
            continue
        if isinstance(record.get('id'), str):
            removed.append(record['id'])
        path.unlink(missing_ok=True)
        path.with_suffix('.log').unlink(missing_ok=True)
    return removed


def _delete_work(content) -> list:
    """The pair directories this mapping's fits worked in, removed with it; their names are returned.

    `fitting.work_dir` names them `<content hash>-<AA run id or no-reference>`. The content prefix is
    the half this module owns, and it is unambiguous: a digest is hexadecimal and cannot contain the
    separator, so no other mapping's directory can match it.
    """
    root = work_root()
    if not root.is_dir():
        return []
    removed = []
    for path in sorted(root.glob(f'{content}-*')):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
            removed.append(path.name)
    return removed


def matches(record, *, candidate_hash=None, content_hash=None) -> bool:
    """Whether a record belongs to the mapping a caller can name only by its hashes.

    The same two questions `bonded.states.matches` asks, in the same order and for the same reason: the
    candidate identity answers *provenance* -- which saved candidate this fit was made for -- and the
    content identity answers *compatibility*, so a renamed candidate keeps its revisions. A record
    answers for any of its revisions, not only the current one, because the strip shows the history.
    """
    if not isinstance(record, dict):
        return False
    revisions = [record.get('current') or {}] + list(record.get('revisions') or [])
    for revision in revisions:
        if candidate_hash and revision.get('mapping_hash') == candidate_hash:
            return True
        if content_hash and revision.get('mapping_content_hash') == content_hash:
            return True
    if candidate_hash and record.get('mapping_hash') == candidate_hash:
        return True
    return bool(content_hash) and record.get('mapping_content_hash') == content_hash


def current(mapping):
    """The current revision of a mapping's parameterization, or None when it has none.

    `None` is the answer the run side branches on: a model with no parameterization is fitted by the
    run, which records that it did (D5's second honest state).
    """
    return document(mapping).get('current')


def revisions(mapping) -> list:
    """Every stored revision, oldest first, each carrying its own `revision` number."""
    return list(document(mapping).get('revisions') or [])


def get(mapping, revision=None) -> dict:
    record = document(mapping)
    if not record['revisions']:
        raise KeyError('This mapping carries no parameterization')
    if revision is None:
        return record['current']
    for item in record['revisions']:
        if item.get('revision') == int(revision):
            return item
    raise KeyError(f'Unknown parameterization revision: {revision}')


def validate(payload) -> dict:
    """Everything a stored revision must carry, checked once at the door.

    A revision is what a run stages and simulates from, so the shape it must have is the shape the
    run reads: a complete ITP, the provenance of the terms, the ensemble the engine saw, the AA
    reference it was fitted against, the options, and the checks. `scientifically_validated` is not
    a field a caller may set: a fit produced here has never been validated, and the record says so.
    """
    if not isinstance(payload, dict):
        raise ValueError('A parameterization revision must be an object')
    engine = payload.get('engine')
    if engine not in ENGINES:
        raise ValueError(f'Unknown fitting engine: {engine!r}')
    topology = payload.get('topology')
    if (not isinstance(topology, str) or '[ moleculetype ]' not in topology
            or '[ atoms ]' not in topology):
        raise ValueError('A revision needs a complete ITP topology')
    options = payload.get('options')
    if not isinstance(options, dict) or set(options) - set(_OPTION_KEYS):
        raise ValueError('Unknown parameterization option')
    normalise_options({}, options)
    reference = payload.get('aa_reference')
    if reference is not None:
        if not isinstance(reference, dict):
            raise ValueError('The AA reference must be an object')
        if set(reference) - {'run_id', 'reference_sha256', 'molecule_identity', 'temperature_k', 'production_ns'}:
            raise ValueError('Unknown AA reference field')
        run_id = reference.get('run_id')
        if not isinstance(run_id, str) or not re.fullmatch(r'[a-f0-9]{12}', run_id):
            raise ValueError('Invalid AA source run ID')
    ensemble = payload.get('ensemble')
    if not isinstance(ensemble, dict) or 'frames' not in ensemble:
        raise ValueError('A revision records the ensemble its engine saw')
    # `None` and `0` are different claims and both are legal: a revision whose engine read no AA frames
    # never looked at a trajectory, where `0 frames` would say it looked at an empty one. No engine reads
    # none now -- the reference-free one was removed -- but records written by it are still read, and a
    # stored revision is not rewritten to suit the vocabulary that followed it.
    frames = ensemble.get('frames')
    if frames is not None and (isinstance(frames, bool) or not isinstance(frames, int) or frames < 0):
        raise ValueError('The frame count must be a non-negative integer, or null for an engine that read none')
    checks = payload.get('checks')
    if checks is None:
        checks = {}
    if not isinstance(checks, dict) or set(checks) - set(CHECKS):
        raise ValueError('Unknown check name')
    for name, report in checks.items():
        if report is not None and not isinstance(report, dict):
            raise ValueError(f'The {name} check must be an object or null')
    sources = payload.get('sources')
    if sources is not None and not isinstance(sources, list):
        raise ValueError('The term sources must be a list')
    # `sources` is computed by `save` from the topology and the mapping, so whatever a caller sent is
    # dropped rather than trusted: the column is a reading of the terms, and a stored copy that could
    # disagree with them would be a second answer to the same question.
    return dict(payload, checks=checks, sources=None, scientifically_validated=False)


def save(mapping, payload, *, expected_revision=None) -> dict:
    """Append a revision and make it current, refusing a stale writer.

    `expected_revision` is the optimistic check the panel needs and the reason revisions are numbered
    rather than replaced: two fits started from the same strip must not silently make the later one
    the only one.
    """
    record = document(mapping)
    if expected_revision is not None and int(expected_revision) != record['revision']:
        raise ValueError('Parameterization changed; reload it before saving')
    checked = validate(payload)
    # The identities a revision records, stamped here and not taken from the caller: `bonded.states`
    # carries the same two on every revision item, and they are what a hash-addressed reader answers
    # `matches` from without holding the mapping.
    checked.update(identities(mapping))
    checked['sources'] = term_sources(checked, mapping)
    revision = record['revision'] + 1
    item = {'revision': revision, 'created_at': files.now_iso(), **checked}
    record['revisions'].append(item)
    record['revision'] = revision
    record['current'] = item
    record['updated_at'] = files.now_iso()
    files.atomic_json(_path(mapping), record)
    return item


def make_current(mapping, revision) -> dict:
    """Point a mapping at an earlier revision without rewriting history."""
    record = document(mapping)
    item = get(mapping, revision)
    record['current'] = item
    record['revision'] = item['revision']
    record['updated_at'] = files.now_iso()
    files.atomic_json(_path(mapping), record)
    return item


# --- reading a revision: the terms, their sources, and what a run panel prints ----------------------


def _canonical(kind, beads):
    values = tuple(beads)
    ordered = tuple(sorted(values)) if kind == 'bonds' else min(values, tuple(reversed(values)))
    return kind, ordered


def _override_keys(mapping):
    keys = set()
    for term in mapping.get('bonded_overrides') or []:
        if isinstance(term, dict) and isinstance(term.get('beads'), list):
            keys.add(_canonical(term.get('section'), term['beads']))
    return keys


def _ring_pairs(mapping):
    return {frozenset(pair) for ring in mapping.get('rings') or []
            for pair in itertools.combinations(ring.get('beads') or [], 2)}


def term_sources(revision, mapping) -> list:
    """One row per term of a stored topology, saying where that term came from.

    The panel's `source` column, and the reason it exists: a hand-edited row has to be visible as
    one. Three answers are computed rather than declared -- a ring constraint is the mapping's (its
    length is the AA reference's own mean, dilated), a pair the mapping overrides is a manual edit,
    and a term the automatic draft had no reference for is geometry, which its own provenance
    already says. Everything else is the engine's.
    """
    engine = revision.get('engine')
    fallback = revision.get('engine_default_source') or ENGINE_SOURCES.get(engine, engine)
    reported = {}
    for term in revision.get('engine_terms') or []:
        if isinstance(term, dict) and isinstance(term.get('beads'), list):
            provenance = term.get('provenance') or {}
            reported[_canonical(term.get('kind'), term['beads'])] = bool(provenance.get('fallback'))
    override_keys, ring_pairs = _override_keys(mapping), _ring_pairs(mapping)
    rows = []
    for row in parse_interactions(revision.get('topology')):
        kind, beads = row['kind'], row['beads']
        if kind == 'virtual_sitesn':
            source = MAPPING_SOURCE
        elif kind == 'constraints' and frozenset(beads) in ring_pairs:
            source = MAPPING_SOURCE
        elif _canonical(kind, beads) in override_keys:
            source = MANUAL_SOURCE
        elif reported.get(_canonical(kind, beads)):
            source = GEOMETRY_SOURCE
        else:
            source = fallback
        rows.append({'id': row['id'], 'kind': kind, 'beads': beads, 'source': source})
    return rows


def term_counts(revision) -> dict:
    """How many terms of each kind a revision's topology carries, for a one-line result box."""
    counts = {}
    for row in parse_interactions(revision.get('topology')):
        counts[row['kind']] = counts.get(row['kind'], 0) + 1
    return counts


def total_terms(revision) -> int:
    """The count a panel prints as '34 terms': the fitted interactions, not the atom list."""
    counts = term_counts(revision)
    return sum(values for kind, values in counts.items() if kind != 'virtual_sitesn')


def view(record) -> dict:
    """The shape a panel renders about a stored record: one for both honest states (D5).

    A record with no revisions answers `parameterized: False` and the sentence the run panel shows in
    place of the terms; the run then fits in stage 3 and records that it did. Nothing here raises for
    an absent record, because absence is a state and not a fault -- and a hash-addressed reader (the
    revision strip, a run's manifest) can produce this without holding the mapping.
    """
    revision = (record or {}).get('current')
    if not revision:
        # `terms: None` and not `0`: this model carries no parameterization, and a count of zero would
        # read as a parameterization of nothing rather than as the absence of one.
        return {'parameterized': False, 'revision': None, 'engine': None, 'engine_label': None,
                'terms': None, 'torsion_model': None, 'checks': [], 'aa_reference': None,
                'revision_sha256': None, 'mapping_hash': (record or {}).get('mapping_hash'),
                'mapping_content_hash': (record or {}).get('mapping_content_hash'),
                'revisions': []}
    return {'parameterized': True, 'revision': revision['revision'], 'engine': revision['engine'],
            'engine_label': ENGINE_LABELS.get(revision['engine']), 'terms': total_terms(revision),
            'torsion_model': (revision.get('options') or {}).get('torsion_model'),
            'checks': sorted((revision.get('checks') or {}).keys()),
            'aa_reference': revision.get('aa_reference'), 'revision_sha256': revision_sha256(revision),
            'created_at': revision.get('created_at'),
            'mapping_hash': revision.get('mapping_hash') or (record or {}).get('mapping_hash'),
            'mapping_content_hash': revision.get('mapping_content_hash') or (record or {}).get('mapping_content_hash'),
            'revisions': [item.get('revision') for item in record.get('revisions') or []]}


def summary(mapping) -> dict:
    """`view` for a caller that holds the mapping rather than a stored record."""
    return view(document(mapping))


def published() -> list:
    """The engines as JSON-safe dicts, for the panel's select.

    The same argument `analysis.kinds.published` makes for the analyses control: the vocabulary gets one
    home, so a fourth engine is one edit here and the panel cannot invent one or render a name the job
    would refuse. `needs_reference` is what decides whether the panel's AA-reference picker is required.
    """
    # Every engine left fits to an ensemble, so `needs_reference` is true for each of them. The key stays because
    # it is the panel's contract (`/engines` is what makes the AA-reference picker required), and a caller that reads
    # it should not have to know how many engines there are.
    return [{'value': name, 'label': ENGINE_LABELS[name], 'needs_reference': True} for name in ENGINES]


def revision_sha256(revision) -> str:
    """The digest of a revision as stored, so a run can name the exact terms it consumed.

    Taken over the stored fields with `created_at` removed: the digest names the terms, not the moment
    they were written, so the same fit re-saved answers the same and a run's record of what it consumed
    cannot change under it.
    """
    return mappings.canonical_sha256({key: value for key, value in revision.items() if key != 'created_at'})


def describe(revision) -> str:
    """D5's first honest sentence: this model is parameterized, and by what."""
    options = revision.get('options') or {}
    reference = revision.get('aa_reference') or {}
    return (f"fitted with {ENGINE_LABELS.get(revision['engine'], revision['engine'])}"
            f" against {reference.get('run_id') or 'no AA reference'}, revision {revision['revision']},"
            f" hash {revision_sha256(revision)[:12]}, torsion model {options.get('torsion_model')}")
