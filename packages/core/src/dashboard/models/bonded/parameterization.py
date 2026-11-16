"""A mapping's parameterization: its revisions, what produced each, and what a run reads.

D1 of `docs/design/2026-10-16-parameterization-and-new-run.md`: the parameterization belongs to the
mapping and the bonded states become its revisions. A run consumes a *model* -- a mapping plus its
current revision -- and never re-fits a parameterized one, so there is no bonded-parameter control
on the run panel and its absence is the point.

One document per mapping holds every revision and which of them is current. The document is
addressed by the mapping's *name*: `records/<slug>.json`, where the slug is `run_names.slug` of the
display name, unique casefolded. The two content identities are still recorded on every revision, but
they are provenance now rather than addresses: a reader that holds a run's manifest (which names its
model by slug and keeps the identity hashes it was prepared with) compares them instead of selecting a
file. A record is read by the name it carries.

The engine is recorded with what it saw, because a force constant without its ensemble is not a
measurement: `-constraints 10000` decides whether a fitted pair becomes a constraint or a spring,
and BARTENDER takes forty seconds against one trajectory and four hundred against another.

`fitting.py` produces a revision; this module stores one, and is the whole reader a run needs.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import shutil
from pathlib import Path

from ... import files, paths, run_names
from .. import mappings
from . import PARAMETER_RANGES, canonical_term, parse_interactions, rewrite_interactions, validate_term

#: The engines a parameterization can be produced by (D3). Each names the ensemble it saw on its
#: result, and each has one label published for the panel; the labels live here rather than in the
#: web layer so a new engine is one edit and the route cannot invent a fourth.
ENGINES = ('fast-forward', 'bartender')

#: A revision's source when it is a transcription of the published Martini 3 reference rather than a fit. The seed
#: that produced one is gone (2026-11-12: the published reference is display-only, and a CG run consumes it directly),
#: but ``validate``/``describe`` still read the records that carry it, and ``edit_gate`` keeps such a revision read-only.
TRANSCRIPTION_SOURCE = 'martini-reference'

#: What ``validate`` accepts on a stored revision: the two fit engines and the reference transcription.
REVISION_SOURCES = ENGINES + (TRANSCRIPTION_SOURCE,)

ENGINE_LABELS = {
    'fast-forward': 'Fast-Forward fit (ff_inter)',
    'bartender': 'BARTENDER fit (-refit -owntraj)',
    TRANSCRIPTION_SOURCE: 'Martini 3 reference transcription',
}

#: What each engine's terms are called in the `source` column of the interactions table.
ENGINE_SOURCES = {'fast-forward': 'ff_inter', 'bartender': 'bartender',
                  TRANSCRIPTION_SOURCE: TRANSCRIPTION_SOURCE}


class StaleRevision(ValueError):
    """The record or revision this writer read has moved on: the caller must reload before saving (409)."""


class Refused(ValueError):
    """A write that this revision's state cannot accept (an earlier revision in place, a read-only revision)."""


class NameConflict(ValueError):
    """A record already answers this mapping's name, and it belongs to a different model.

    Not a validation failure: the mapping is well formed and its name is already claimed by another
    model's revisions. The name travels on the exception so the route can answer 409 with the record to
    open instead, and the caller chooses whether to rename the mapping or overwrite the record.
    """

    def __init__(self, existing):
        self.existing = existing
        super().__init__(f'Another model\'s parameterization is already stored as {existing}')

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
DEFAULT_CONSTRAINTS = 10000

DEFAULT_TEMPERATURE = 300.0

_OPTION_KEYS = ('constraints_threshold', 'temperature_k', 'torsion_model', 'torsion_scale')

#: The mapped starting coordinates, stored with the revision so a CG run can start without re-reading the AA
#: trajectory. `mapped.gro` is the starting frame; `mapped.xtc` is the bead trajectory the fit built, kept because a
#: stored run's mapping-based analyses read it. Both travel with the terms and are hashed into the record.
COORDINATE_FILES = ('mapped.gro', 'mapped.xtc')

#: The AA reference's own histograms: what `ff_assess` scores a CG run *against*. It reads them from its `-d` directory
#: and never computes them, so a run that consumes a parameterization needs them copied into the run.
#:
#: The pattern is the tool's own file map, which is `glob(f'{reference}/*distr.dat')` -- every histogram in the
#: directory, and not only the bonded ones. The assessment scores two families: one histogram per bond/angle/dihedral,
#: and one per bead pair over its whole distance range (`<resid>_<a>_<resid>_<b>_distances_distr.dat`). A copy that took
#: only the first family leaves the second half of the score with no baseline, and that half does not fail: `ff_assess`
#: `continue`s past a pair whose reference file is missing, so an unbaselined distance matrix reads 0.00 -- "identical" --
#: which is the most flattering possible wrong answer.
DISTRIBUTION = re.compile(r'.+_distr\.dat$')

#: The one family of those histograms the pairwise score is built from, and the only one whose absence is silent.
#:
#: `score.py` asks for `<resid1>_<name1>_<resid2>_<name2>_distances_distr.dat` per bead pair and `continue`s when the
#: file is missing, leaving that cell of the matrix at its 0.00 default -- "identical". So a revision that recorded
#: bonds and angles but no pairwise family is not a scorable baseline, and whoever stages it has to say so.
PAIR_DISTRIBUTION = re.compile(r'^\d+_\w+_\d+_\w+_distances_distr\.dat$')


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


def display_name(mapping) -> str:
    """The name a person gave this mapping, which is what its record is called."""
    if not isinstance(mapping, dict):
        raise ValueError('A mapping is required to address its parameterization')
    return str(mapping.get('name') or mapping.get('file') or 'mapping')


def address(mapping) -> str:
    """The record name this mapping is stored under: its display name's slug."""
    return run_names.slug(display_name(mapping))


def address_from(label) -> str:
    """The record name a label suggests, for a caller that holds a name and not a mapping."""
    return run_names.slug(label)


def _validate_id(value):
    """A record address: a name, and never a path out of the records root.

    The name rule is `run_names`', the one every other path component in this repository uses, and the
    containment check is explicit because this value becomes a file name: the two together are the door a
    `DELETE` or an edit arrives through.
    """
    if not isinstance(value, str):
        raise ValueError('Invalid parameterization name')
    try:
        run_names.validate(value, what='A parameterization name')
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    root = records_root().resolve()
    if (root / f'{value}.json').resolve().parent != root:
        raise ValueError('Parameterization name escapes the records directory')
    return value


def _record_path(name) -> Path:
    """The file this address names, preferring the exact spelling and then the casefolded one.

    A workspace copied from a case-sensitive filesystem can hold both spellings of one name. The record
    already on disk is the record, so a reader finds it and a writer is told which name to keep.
    """
    root = records_root()
    path = root / f'{name}.json'
    if path.is_file() or not root.is_dir():
        return path
    folded = name.casefold()
    for candidate in sorted(root.glob('*.json')):
        if candidate.stem.casefold() == folded:
            return candidate
    return path


def _path(mapping) -> Path:
    """This mapping's record, or where a new one goes: `records/<slug>.json`."""
    return _record_path(address(mapping))


def conflict(mapping):
    """The name of a record this mapping's name already answers and which belongs to another model, or None.

    This is the uniqueness rule. The store refuses two models under one name up front rather than
    mixing their revisions; the route answers 409 naming the record so the caller can rename the mapping
    or ask to overwrite.
    """
    path = _record_path(address(mapping))
    if not path.is_file():
        return None
    try:
        record = _read(path)
    except ValueError:
        return path.stem
    return None if record.get('mapping_content_hash') == content_identity(mapping) else path.stem


def exists(identifier) -> bool:
    """Whether a record file answers this address."""
    return _record_path(_validate_id(identifier)).is_file()


def revisions_root(identifier) -> Path:
    """Where a mapping's recorded reference distributions live: one directory per revision, beside its record."""
    return records_root() / f'{_validate_id(identifier)}.revisions'


def _record_distributions(name, revision, work):
    """Copy this fit's reference histograms beside the revision, hashed, and say which files they are.

    A working directory is scratch -- `delete` removes it with the mapping -- and a re-fit overwrites it, so leaving the
    baseline there would make a run's score depend on a folder that can change underneath it. Copying them with the
    revision makes "the baseline this model was fitted to" a fact the record states, and a run that consumes the
    revision carries its own copy.
    """
    if work is None:
        return None
    source = Path(work) / '3_initial_CG'
    if not source.is_dir():
        return None
    found = sorted(path for path in source.iterdir() if path.is_file() and DISTRIBUTION.match(path.name))
    if not found:
        return None
    target = revisions_root(name) / str(revision)
    target.mkdir(parents=True, exist_ok=True)
    listing = []
    for path in found:
        data = path.read_bytes()
        (target / path.name).write_bytes(data)
        listing.append({'name': path.name, 'sha256': hashlib.sha256(data).hexdigest()})
    return {'directory': str(target.relative_to(storage_root())), 'files': listing}


def _record_coordinates(name, revision, work):
    """Copy this fit's mapped starting coordinates beside the revision, hashed, and say which files they are.

    The fit already builds `2_mapping/mapped.gro` and `mapped.xtc`; a run that consumes this revision should not have
    to read the AA trajectory again to start. The files are copied (not referenced) for the same reason the
    histograms are: a work directory is scratch, and a re-fit overwrites it. They are streamed to disk rather than
    read whole because an XTC of a long reference is large.
    """
    if work is None:
        return None
    source = Path(work) / '2_mapping'
    found = [source / name for name in COORDINATE_FILES if (source / name).is_file()]
    if not found:
        return None
    target = revisions_root(name) / str(revision)
    target.mkdir(parents=True, exist_ok=True)
    listing = []
    for path in found:
        digest = hashlib.sha256()
        destination = target / path.name
        with path.open('rb') as reader, destination.open('wb') as writer:
            while chunk := reader.read(1024 * 1024):
                digest.update(chunk)
                writer.write(chunk)
        listing.append({'name': path.name, 'sha256': digest.hexdigest(), 'bytes': destination.stat().st_size})
    return {'directory': str(target.relative_to(storage_root())), 'files': listing,
            'source': 'the mapped AA frames this fit built (stage 2 of a run)'}


def coordinates(mapping, revision=None) -> dict | None:
    """The revision's stored starting coordinates as an absolute directory and a hashed file list, or None.

    None is an honest answer: a revision fitted before coordinates were stored has none, and a run that wanted them
    has to say so rather than silently fall back to re-mapping.
    """
    try:
        item = get(mapping, revision)
    except KeyError:
        return None
    recorded = item.get('coordinates')
    if not isinstance(recorded, dict) or not recorded.get('files'):
        return None
    directory = Path(recorded.get('directory') or '')
    if not directory.is_absolute():
        directory = storage_root() / directory
    return {'directory': directory, 'files': recorded['files'], 'revision': item['revision']}


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
        # `ff_inter` declares `-constraints` an int, so this option is a whole number: a decimal in it
        # made the fit die in the tool's parser (`invalid int value: '10000.0'`). Rounding here keeps the
        # recorded option, the revision's note and the argument the engine was given one number.
        values[key] = round(float(value)) if key == 'constraints_threshold' else float(value)
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


def owners(record) -> list:
    """The saved mappings this record's content belongs to, oldest claim first."""
    listed = record.get('owners') if isinstance(record, dict) else None
    return [item for item in listed or [] if isinstance(item, dict) and item.get('mapping_hash')]





def empty_document(mapping) -> dict:
    """The document a mapping with no record answers with: no revisions, and nothing current."""
    return {**_empty(identities(mapping)), 'name': address(mapping)}


def document(mapping) -> dict:
    """Every revision of this mapping, or an empty document when it has none.

    A record at this mapping's name whose identity is a different model's is refused rather than reported as a
    mapping with no parameterization, because the two mean different things to a run -- one re-fits, the
    other is a fit that was made and lost (or another model's, sitting under a name this mapping wants).
    """
    path = _path(mapping)
    if not path.is_file():
        return empty_document(mapping)
    record = _read(path)
    if record.get('mapping_content_hash') != content_identity(mapping):
        raise ValueError('Parameterization record belongs to another mapping')
    # `owners` is a legacy claim list: the panel still shows which saved mappings a pre-name record's content belonged
    # to, and the deletion fallback reads it. A record written now carries no claims, because its name is the answer.
    return {**record, 'owners': owners(record), 'name': path.stem}


def _read(path) -> dict:
    try:
        record = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f'Unreadable parameterization record: {path.name}') from exc
    if not isinstance(record, dict):
        raise ValueError('Parameterization record must be an object')
    return record


def one(identifier) -> dict:
    """The record a name addresses, for a reader that holds no mapping.

    The display selector works from a saved candidate's name; a run's manifest names its model by slug.
    An unknown address answers with an empty document rather than an error, because "this model has no
    parameterization" is the state a caller is asking about.
    """
    value = _validate_id(identifier)
    path = _record_path(value)
    if not path.is_file():
        return {**_empty({'mapping_hash': None, 'mapping_content_hash': None}), 'name': value}
    record = _read(path)
    return {**record, 'owners': owners(record), 'name': path.stem}


def records() -> list:
    """Every stored record, newest first, for a listing that has no mapping in hand."""
    root = records_root()
    if not root.is_dir():
        return []
    found = []
    for path in sorted(root.glob('*.json')):
        try:
            found.append({**_read(path), 'name': path.stem})
        except ValueError:
            continue
    found.sort(key=lambda record: record.get('updated_at') or '', reverse=True)
    return found


# --- deletion: a mapping's parameterization goes when the mapping does ---------------------------------


def delete(identifier) -> dict:
    """Remove a mapping's parameterization: its record, every revision in it, and what was built for it.

    A revision is a field of the record rather than a file of its own, so removing the record removes
    the whole history at once. What sits beside it under the same storage root is removed with it:
    the fit jobs that produced it (`fitting.jobs_root`, which is this root's `jobs/`), the
    (mapping, AA reference) working directories those jobs built (`work_root`), and the revision
    directory.

    Idempotent by design: an address with no record removed nothing, and that is an answer rather than
    an error. The caller (`mappings.store.delete_draft`) asks after every save, and most mappings were
    never fitted. What was removed is returned rather than assumed, because a caller that reported a
    guess would be reporting a guess.
    """
    value = _validate_id(identifier)
    path = _record_path(value)
    removed = {'name': path.stem if path.is_file() else value, 'content_hash': None,
               'deleted': False, 'revisions': [], 'jobs': [], 'work': [], 'distributions': None}
    content = None
    if path.is_file():
        try:
            record = _read(path)
            revisions = [item.get('revision') for item in (record.get('revisions') or [])
                         if isinstance(item, dict)]
            content = record.get('mapping_content_hash')
        except ValueError:
            # A record nothing can read is still this mapping's record: remove it, and report no
            # revision numbers rather than refusing to delete what the caller already decided on.
            revisions = []
        path.unlink()
        removed.update(deleted=True, revisions=revisions)
    removed['content_hash'] = content
    # The revision directory is the record's name.
    revisions = revisions_root(removed['name'])
    if revisions.is_dir():
        shutil.rmtree(revisions)
        removed['distributions'] = revisions.name
    removed['jobs'] = _delete_jobs(removed['content_hash'], removed['name'])
    removed['work'] = _delete_work(removed['name'])
    removed['deleted'] = removed['deleted'] or bool(removed['jobs'] or removed['work'])
    return removed


def _delete_jobs(content, name) -> list:
    """The fit jobs of this mapping, removed with it; each job's id is returned.

    A job is stamped with the record name it was queued for, and with the two content identities a
    revision carries. Either is enough to recognise it -- the name catches a job queued for a model
    whose content has since changed, the content catches a job queued before names were stamped.
    """
    root = storage_root() / 'jobs'
    if not root.is_dir():
        return []
    folded = name.casefold() if isinstance(name, str) else None
    removed = []
    for path in sorted(root.glob('*.json')):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        stamped = record.get('parameterization_name')
        if not (content and record.get('mapping_content_hash') == content) and not (
                folded and isinstance(stamped, str) and stamped.casefold() == folded):
            continue
        if isinstance(record.get('id'), str):
            removed.append(record['id'])
        path.unlink(missing_ok=True)
        path.with_suffix('.log').unlink(missing_ok=True)
    return removed


def _delete_work(name) -> list:
    """The pair directories this mapping's fits worked in, removed with it; their names are returned.

    `fitting.work_dir` names a directory `<slug>--<AA run id or no-reference>`, and a slug cannot contain `--`,
    so the prefix is unambiguous.
    """
    root = work_root()
    if not root.is_dir():
        return []
    removed = []
    for path in sorted(root.glob(f'{name}--*')):
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
    if engine not in REVISION_SOURCES:
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
        if set(reference) - {'run_id', 'reference_sha256', 'edition', 'molecule_identity', 'temperature_k',
                             'production_ns'}:
            raise ValueError('Unknown AA reference field')
        run_id = reference.get('run_id')
        try: run_names.validate(run_id, what='AA source run ID')
        except ValueError as exc: raise ValueError(f'Invalid AA source run ID: {exc}') from exc
        edition = reference.get('edition')
        if edition is not None and (isinstance(edition, bool) or not isinstance(edition, int) or edition < 1):
            raise ValueError('The AA reference edition must be a positive integer')
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


def _append_revision(record, mapping, checked, *, work=None, source=None) -> dict:
    """Append one revision and make it current, in one atomic write under the mapping's name.

    The one writer for a fit (``save``) and for both term saves: it stamps the identities and the computed
    ``sources``, numbers the revision, and attaches the coordinate/distribution records either
    from ``source`` (a clone of an earlier revision shares them) or from the fit's ``work`` directory.
    The file it writes is `records/<slug>.json`.
    """
    name = address(mapping)
    record['name'] = name
    # A record belongs to the one mapping whose name it carries, so a new write stamps no claim list.
    # The identities a revision records, stamped here and not taken from the caller: they are provenance a run
    # compares, and `matches` answers from them without holding the mapping.
    checked.update(identities(mapping))
    checked['sources'] = term_sources(checked, mapping)
    revision = record['revision'] + 1
    item = {'revision': revision, 'created_at': files.now_iso(), **checked}
    if source is not None:
        for key in ('coordinates', 'distributions'):
            if isinstance(source.get(key), dict):
                item[key] = source[key]
    if work is not None:
        distributions = _record_distributions(name, revision, work)
        if distributions:
            item['distributions'] = distributions
        stored_coordinates = _record_coordinates(name, revision, work)
        if stored_coordinates:
            item['coordinates'] = stored_coordinates
    record['revisions'].append(item)
    record['revision'] = revision
    record['current'] = item
    record['updated_at'] = files.now_iso()
    files.atomic_json(_record_path(name), record)
    return item


def save(mapping, payload, *, expected_revision=None, work=None, overwrite=False) -> dict:
    """Append a revision and make it current, refusing a stale writer or a name another model holds.

    `expected_revision` is the optimistic check the panel needs and the reason revisions are numbered
    rather than replaced: two fits started from the same strip must not silently make the later one
    the only one.

    `work` is the directory the fit ran in. When it holds the AA reference's interaction histograms
    (`refine_bonded` writes them while fitting), they are copied beside the revision and hashed into it,
    so the baseline a later run's assessment scores against belongs to the model rather than to scratch.

    `overwrite` is the caller's explicit answer to a name another model holds: the record is replaced
    with this fit's revision 1 rather than the two models' revisions being mixed. It is never inferred,
    because it discards history that is recoverable only by fitting again.
    """
    existing = conflict(mapping)
    if existing and not overwrite:
        raise NameConflict(existing)
    record = empty_document(mapping) if existing else document(mapping)
    if expected_revision is not None and int(expected_revision) != record['revision']:
        raise ValueError('Parameterization changed; reload it before saving')
    checked = validate(payload)
    # `validate` still reads a stored transcription, because old records carry one; producing a new one here is the
    # seed path that is gone -- a CG run consumes the published reference directly.
    if checked['engine'] not in ENGINES:
        raise ValueError('A stored revision is fitted; a Martini 3 reference transcription is read-only')
    return _append_revision(record, mapping, checked, work=work)


def _find_revision(record, revision):
    for item in record.get('revisions') or []:
        if item.get('revision') == revision:
            return item
    raise KeyError(f'Unknown parameterization revision: {revision}')


def _number(text):
    value = float(text)
    return int(value) if value.is_integer() else value


def _validated_edits(topology, edits):
    """Check one request's term edits against the stored topology, with the value it is replacing.

    The function is read from the row, never taken from the caller: a parameter edit changes values, not the
    potential form. Constraints and virtual sites have no ``PARAMETER_RANGES`` row and are refused by their own
    reading sentinel.
    """
    if not isinstance(edits, list) or len(edits) > 300:
        raise ValueError('terms must be a list of at most 300 edits')
    rows = {row['id']: row for row in parse_interactions(topology)}
    validated = {}
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'id', 'parameters'}:
            raise ValueError('Each edit needs id and parameters')
        term_id = edit['id']
        if not isinstance(term_id, str) or term_id in validated:
            raise ValueError(f'Duplicate or invalid term id: {term_id!r}')
        row = rows.get(term_id)
        if row is None:
            raise ValueError(f'No editable term {term_id} in this revision')
        kind = row['kind']
        if kind not in PARAMETER_RANGES:
            if kind.startswith('virtual_sites'):
                raise ValueError("A virtual site's parents are the mapping's; they are not editable")
            raise ValueError(f'{kind} terms are not editable')
        validated[term_id] = {'kind': kind, 'beads': list(row['beads']), 'function': str(row['function']),
                              'before': [_number(value) for value in row['parameters']],
                              'parameters': validate_term(kind, row['function'], edit['parameters'])}
    return validated


def _merge_edits(existing, validated):
    """Fold this request's edits into a revision's edit history, keeping the values they replaced."""
    at = files.now_iso()
    merged = {term['id']: term for term in existing or []
              if isinstance(term, dict) and isinstance(term.get('id'), str)}
    for term_id, edit in validated.items():
        merged[term_id] = {'id': term_id, 'kind': edit['kind'], 'beads': list(edit['beads']),
                           'function': edit['function'], 'before': list(edit['before']),
                           'after': list(edit['parameters']), 'at': at}
    return list(merged.values())


def save_terms(mapping, *, mode, edits, revision=None, expected_revision=None, expected_sha256=None) -> dict:
    """Write edited terms into the mapping's parameterization record.

    ``mode='in_place'`` rewrites the *current* revision's topology and only that; the revision number and its fit
    provenance stay, its ``checks`` are cleared (they described the pre-edit terms), and ``edited_terms`` keeps the
    values it replaced. ``mode='new'`` clones the shown revision -- current or earlier -- with its engine, ensemble,
    AA reference, options and coordinate/distribution records, replaces the topology, clears the checks, appends it
    and makes it current; the source revision is untouched.

    Whether either write is allowed is ``edit_gate``'s answer: a fresh fit revision is editable but its first edit is
    Save as new, and a ``martini-reference`` transcription is read-only. Returns the stored record.
    """
    if mode not in ('in_place', 'new'):
        raise ValueError('mode must be "in_place" or "new"')
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise ValueError('A revision number is required')
    record = document(mapping)
    if expected_revision != record['revision']:
        raise StaleRevision('This parameterization changed; reload it before saving')
    if not isinstance(expected_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_sha256):
        raise ValueError('expected_sha256 is required to save a stored revision')
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise ValueError('A revision number is required')
    item = _find_revision(record, revision)
    if revision_sha256(item) != expected_sha256:
        raise StaleRevision('This revision changed since it was read; reload it before saving')
    gate = edit_gate(item)
    if mode == 'in_place':
        current = (record.get('current') or {}).get('revision')
        if revision != current:
            raise Refused(f'Revision {revision} is not the current revision; Save in place writes the revision a '
                          'run consumes')
        if not gate['save_in_place']:
            raise Refused(gate['reason'])
        validated = _validated_edits(item['topology'], edits)
        if not validated:
            raise ValueError('No parameter edits were given')
        rewritten = rewrite_interactions(item['topology'], {term_id: edit['parameters']
                                                            for term_id, edit in validated.items()})
        updated = validate({**item, 'topology': rewritten, 'terms': term_counts({'topology': rewritten}),
                            'checks': {}, 'edited_terms': _merge_edits(item.get('edited_terms'), validated)})
        updated['sources'] = term_sources(updated, mapping)
        record['revisions'] = [updated if candidate.get('revision') == revision else candidate
                               for candidate in record['revisions']]
        record['current'] = next(candidate for candidate in record['revisions']
                                 if candidate.get('revision') == revision)
        record['updated_at'] = files.now_iso()
        files.atomic_json(_record_path(address(mapping)), record)
        return record
    if not gate['editable']:
        raise Refused(gate['reason'])
    validated = _validated_edits(item['topology'], edits)
    rewritten = (rewrite_interactions(item['topology'], {term_id: edit['parameters']
                                                        for term_id, edit in validated.items()})
                 if validated else item['topology'])
    payload = {key: item.get(key) for key in ('engine', 'engine_default_source', 'ensemble', 'aa_reference',
                                              'options', 'temperature_source', 'engine_terms', 'engine_command',
                                              'refinement', 'diagnostics', 'transcription') if key in item}
    payload.update(topology=rewritten, terms=term_counts({'topology': rewritten}), checks={},
                   edited_terms=_merge_edits(item.get('edited_terms'), validated),
                   notes=list(item.get('notes') or []) + [f'cloned from revision {revision}; '
                                                          'its checks were not re-run'])
    _append_revision(record, mapping, validate(payload), source=item)
    return record


def distributions(mapping, revision=None) -> dict | None:
    """The revision's recorded reference histograms as an absolute directory and a hashed file list, or None.

    None is an answer and not an error: a revision fitted before these were recorded, or by an engine that measured
    none, carries no baseline -- and a run that needs one has to say so rather than score against nothing.
    """
    item = get(mapping, revision)
    recorded = item.get('distributions')
    if not isinstance(recorded, dict) or not recorded.get('files'):
        return None
    directory = Path(recorded.get('directory') or '')
    if not directory.is_absolute():
        directory = storage_root() / directory
    return {'directory': directory, 'files': recorded['files'], 'revision': item['revision']}


def make_current(mapping, revision) -> dict:
    """Point a mapping at an earlier revision without rewriting history."""
    record = document(mapping)
    item = get(mapping, revision)
    record['current'] = item
    record['revision'] = item['revision']
    record['updated_at'] = files.now_iso()
    files.atomic_json(_record_path(address(mapping)), record)
    return item


def _rebase_recorded_directories(record, old_name, new_name):
    """Rewrite a revision's recorded directory from the old revision directory to the new one.

    A revision records where its histograms and starting coordinates live as a path relative to the
    store (`records/<name>.revisions/<n>`). Moving the record without those is a record whose baseline
    cannot be read, so a rename of the record renames them with it.
    """
    prefix, target = f'records/{old_name}.revisions', f'records/{new_name}.revisions'
    changed = False
    for item in record.get('revisions') or []:
        if not isinstance(item, dict):
            continue
        for key in ('coordinates', 'distributions'):
            block = item.get(key)
            if isinstance(block, dict) and isinstance(block.get('directory'), str) \
                    and block['directory'].startswith(prefix):
                block['directory'] = target + block['directory'][len(prefix):]
                changed = True
    return changed


def rename(old_label, new_label) -> str | None:
    """Move a mapping's whole record to the name its new display label suggests.

    A rename is an in-place save of the same mapping, and the revisions belong to the mapping, so the
    record follows the name: the file, its revision directory and the directories the revisions record.
    A target that already holds another model's record raises `NameConflict`; the caller answers 409
    with the name and the mapping is not written.
    """
    old_name, new_name = address_from(old_label), address_from(new_label)
    if old_name == new_name:
        return None
    source = _record_path(old_name)
    if not source.is_file():
        return None
    target = records_root() / f'{new_name}.json'
    if target.exists() and not target.samefile(source):
        raise NameConflict(target.stem)
    record = _read(source)
    record['name'] = new_name
    _rebase_recorded_directories(record, source.stem, new_name)
    if target.exists() and target.samefile(source):
        # A case-only rename on a case-insensitive filesystem is one file: rename its spelling, never unlink it.
        source.rename(target)
        files.atomic_json(target, record)
    else:
        files.atomic_json(target, record)
        if source != target:
            source.unlink(missing_ok=True)
    previous, moved = revisions_root(old_name), revisions_root(new_name)
    if previous.is_dir() and not (moved.exists() and moved.samefile(previous)):
        if moved.is_dir():
            for child in sorted(previous.iterdir()):
                shutil.move(str(child), str(moved / child.name))
            previous.rmdir()
        else:
            shutil.move(str(previous), str(moved))
    return new_name


# --- reading a revision: the terms, their sources, and what a run panel prints ----------------------


def _override_keys(mapping):
    keys = set()
    for term in mapping.get('bonded_overrides') or []:
        if isinstance(term, dict) and isinstance(term.get('beads'), list):
            keys.add(canonical_term(term.get('section'), term['beads']))
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
            reported[canonical_term(term.get('kind'), term['beads'])] = bool(provenance.get('fallback'))
    # A hand-edited term is recorded by the revision itself, not by the mapping: the edit rewrote the stored
    # topology, so its ids are what the row is read from. This is checked before the mapping-override and geometry
    # fallbacks, because those describe where the *fitted* term came from, not the value now stored.
    edited_ids = {term.get('id') for term in revision.get('edited_terms') or []
                  if isinstance(term, dict) and isinstance(term.get('id'), str)}
    override_keys, ring_pairs = _override_keys(mapping), _ring_pairs(mapping)
    rows = []
    for row in parse_interactions(revision.get('topology')):
        kind, beads = row['kind'], row['beads']
        if kind == 'virtual_sitesn':
            source = MAPPING_SOURCE
        elif row['id'] in edited_ids:
            # Before the ring check: a constraint's length is the mapping's *until* a reader edits it, and from then
            # on the revision's hand edit is what the stored number came from.
            source = MANUAL_SOURCE
        elif kind == 'constraints' and frozenset(beads) in ring_pairs:
            source = MAPPING_SOURCE
        elif canonical_term(kind, beads) in override_keys:
            source = MANUAL_SOURCE
        elif reported.get(canonical_term(kind, beads)):
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


def edit_gate(revision) -> dict:
    """Whether a revision's terms may be edited, and whether Save in place may write it.

    The one rule for bonded editability, derived from the stored revision at read time and never persisted, so a
    revision's digest names its terms and not this answer. A fit's own revision (``fast-forward`` or ``bartender``)
    is editable in the table, but its first edit is Save as new: Save in place rewrites the revision a run consumes,
    and only hand edits say a person has looked at the fit. ``edited_terms`` is the one marker of hand edits -- a
    mapping's ``bonded_overrides`` are the mapping's property, not this revision's. A ``martini-reference``
    transcription is read-only whatever it carries, because nothing fitted it.
    """
    revision = revision or {}
    if revision.get('engine') == TRANSCRIPTION_SOURCE:
        return {'editable': False, 'save_in_place': False,
                'reason': 'a Martini 3 reference transcription is read-only'}
    if revision.get('edited_terms'):
        return {'editable': True, 'save_in_place': True, 'reason': ''}
    return {'editable': True, 'save_in_place': False,
            'reason': f'fitted by {revision.get("engine")}; Save as new to edit it'}


def view(record) -> dict:
    """The shape a panel renders about a stored record: one for both honest states (D5).

    A record with no revisions answers `parameterized: False` and the sentence the run panel shows in
    place of the terms; the run then fits in stage 3 and records that it did. Nothing here raises for
    an absent record, because absence is a state and not a fault -- and a hash-addressed reader (the
    the display selector, a run's manifest) can produce this without holding the mapping.
    """
    revision = (record or {}).get('current')
    if not revision:
        # `terms: None` and not `0`: this model carries no parameterization, and a count of zero would
        # read as a parameterization of nothing rather than as the absence of one.
        return {'parameterized': False, 'revision': None, 'engine': None, 'engine_label': None,
                'terms': None, 'torsion_model': None, 'checks': [], 'aa_reference': None,
                'revision_sha256': None, 'name': (record or {}).get('name'),
                'mapping_hash': (record or {}).get('mapping_hash'),
                'mapping_content_hash': (record or {}).get('mapping_content_hash'),
                'parameters_editable': False, 'save_in_place': False,
                'save_in_place_reason': 'this model carries no parameterization', 'revisions': []}
    gate = edit_gate(revision)
    return {'parameterized': True, 'revision': revision['revision'], 'engine': revision['engine'],
            'engine_label': ENGINE_LABELS.get(revision['engine']), 'terms': total_terms(revision),
            'torsion_model': (revision.get('options') or {}).get('torsion_model'),
            'checks': sorted((revision.get('checks') or {}).keys()),
            'aa_reference': revision.get('aa_reference'), 'revision_sha256': revision_sha256(revision),
            'created_at': revision.get('created_at'), 'name': (record or {}).get('name'),
            'mapping_hash': revision.get('mapping_hash') or (record or {}).get('mapping_hash'),
            'mapping_content_hash': revision.get('mapping_content_hash') or (record or {}).get('mapping_content_hash'),
            'parameters_editable': gate['editable'], 'save_in_place': gate['save_in_place'],
            'save_in_place_reason': gate['reason'],
            'revisions': [item.get('revision') for item in record.get('revisions') or []]}


def summary(mapping) -> dict:
    """`view` for a caller that holds the mapping rather than a stored record."""
    return view(document(mapping))


def published() -> list:
    """The engines as JSON-safe dicts, for the panel's select.

    One home for the vocabulary, so a fourth engine is one edit here and the panel cannot invent one or
    render a name the job would refuse. `needs_reference` is what decides whether the panel's AA-reference
    picker is required.
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
    engine = revision['engine']
    if engine == TRANSCRIPTION_SOURCE:
        transcription = revision.get('transcription') or {}
        inherited = (f"; AA source {reference.get('run_id')} inherited for a run, not fitted against"
                     if reference.get('run_id') else '; no AA source recorded')
        return (f"transcribed from the published Martini 3 reference {transcription.get('entry') or 'unknown'}"
                f"{inherited}, revision {revision['revision']}, hash {revision_sha256(revision)[:12]},"
                f" torsion model {options.get('torsion_model')}")
    return (f"fitted with {ENGINE_LABELS.get(engine, engine)}"
            f" against {reference.get('run_id') or 'no AA reference'}, revision {revision['revision']},"
            f" hash {revision_sha256(revision)[:12]}, torsion model {options.get('torsion_model')}")
