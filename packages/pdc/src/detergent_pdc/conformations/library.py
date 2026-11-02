"""The conformation library: one canonical file per detergent and source set, with its digest beside it.

A library is a pure function of its sources and its selection, so the file is too: no timestamp, no version, sorted
keys, entries in canonical order, floats rounded. That is what makes its digest a pin a run can trust across
workspaces and rebuilds, and what makes a rebuild that changes the bytes visible instead of silent.

The store is one directory per detergent and key, under `<workspace>/conformations/`. A write is atomic under an
exclusive `flock` on the directory's `.lock`, so two prepares that need the same library end with one file and never
with half of one. The sidecar `library.sha256` is the file's own digest written beside it, so a directory copied
between workspaces can be verified before it is trusted.

A library is named in one of two ways, and the difference is what a run may rely on:

* **build** -- source run ids, a size and a seed. The key is derived from the runs' identities, so a stored copy is
  reused when it is there and built when it is not.
* **reference** -- a key and the digest of a stored file. The copy is used as it is and never rebuilt, because its
  source runs may live in another workspace. Losing it is a refusal that says to copy the original back.

Either way the resolved library carries its key and digest, and the caller records them on the run. A library whose
bead names, count, residue or mapping digest differ from the run's own detergent model is refused by
`Library.assert_matches`, never silently used.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import extract, select
from .sources import sources

FORMAT = 'detergent-conformations-v1'
METHOD = 'stratified-median-split'
DESCRIPTORS = ('length_nm', 'rg_nm', 'reach_nm', 'radial_nm')
DEFAULT_SIZE, MAX_SIZE = 2000, 5000
#: The two files a stored library is: the canonical document and the digest of its bytes.
DOCUMENT = 'library.json'
SIDECAR = 'library.sha256'
#: The directory the store lives in, under the workspace.
STORE = 'conformations'


@dataclass
class Conformations:
    """What a placement draws from: one head-anchored, +z profile per entry, in the library's key order."""

    key: str
    size: int
    profiles: tuple


class Library:
    """One stored library: its key, the digest of its bytes, its path and its canonical document."""

    def __init__(self, *, key, sha256, path, document):
        self.key = str(key)
        self.sha256 = str(sha256)
        self.path = Path(path)
        self.document = document

    @property
    def residue(self):
        return str(self.document['detergent']['residue'])

    @property
    def beads(self):
        return [str(name) for name in self.document['detergent']['beads']]

    @property
    def mapping_sha256(self):
        return str(self.document['detergent']['mapping_sha256'])

    @property
    def size(self):
        return int(self.document['selection']['size'])

    @property
    def sources(self):
        return self.document['sources']

    @property
    def entries(self):
        return self.document['entries']

    def offsets(self):
        """The entries' beads as one `(K, n_beads, 3)` float64 array: head at the origin, head-ward axis +z."""
        return np.asarray([entry['beads'] for entry in self.entries], dtype=np.float64)

    def conformations(self):
        """The profiles a placement draws: the same fields `pdc_placement.detergent_profile` returns."""
        profiles = tuple({'offsets': np.asarray(entry['beads'], dtype=np.float64),
                          'axis': [0.0, 0.0, 1.0],
                          'length_nm': float(entry['descriptors'][0]),
                          'reach_nm': float(entry['descriptors'][2]),
                          'radial_nm': float(entry['descriptors'][3]),
                          'bead_count': len(entry['beads']),
                          'source': 'conformations', 'head_source': 'library'}
                         for entry in self.entries)
        return Conformations(key=self.key, size=self.size, profiles=profiles)

    def assert_matches(self, *, residue, beads, mapping_sha256):
        """Refuse a library that is not the run's own detergent: which two values differ, by name."""
        if str(residue) != self.residue:
            raise ValueError(f'the library {self.key} is for residue {self.residue!r}, not the run\'s {str(residue)!r}')
        names = [str(name) for name in beads]
        if names != self.beads:
            if len(names) != len(self.beads):
                raise ValueError(f'the library {self.key} holds {len(self.beads)} beads but the run names '
                                 f'{len(names)}: {self.beads} against {names}')
            index = next(position for position, (left, right) in enumerate(zip(self.beads, names)) if left != right)
            raise ValueError(f'the library {self.key} bead {index + 1} is {self.beads[index]!r} but the run names '
                             f'{names[index]!r}: {self.beads} against {names}')
        if str(mapping_sha256) != self.mapping_sha256:
            raise ValueError(f'the library {self.key} was built from mapping {self.mapping_sha256} but the run uses '
                             f'{str(mapping_sha256)}: one library needs one mapping')


def normalise_spec(spec):
    """The one spelling of the two ways to name a library, or `None` for "no library".

    A build is `{'runs': [id, ...], 'size': K, 'seed': S}`; a reference is `{'key': <16 hex>, 'sha256': <64 hex>}`.
    Anything else is a refusal that names the field, including a spec that carries both: a library cannot be both
    built from local runs and taken as a stored copy.

    The answer carries `mode`, and passing an answer back in is the same answer: `prepare` hands the normalised spec
    it validated to `resolve`, which normalises it again.
    """
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise ValueError(f'a conformation library is an object naming runs or a key, not {spec!r}')
    mode = spec.get('mode')
    if mode is None:
        if 'key' in spec and 'runs' in spec:
            raise ValueError('a conformation library names either runs (build) or a key (reference), not both')
        if 'key' in spec or 'sha256' in spec:
            mode = 'reference'
        elif 'runs' in spec:
            mode = 'build'
        else:
            raise ValueError('a conformation library names either its source runs (`runs`) or a stored library '
                             '(`key` and `sha256`)')
    if mode == 'reference':
        unknown = sorted(set(spec) - {'mode', 'key', 'sha256'})
        if unknown:
            raise ValueError(f'a reference library names only key and sha256, not {", ".join(unknown)}')
        if 'key' not in spec or 'sha256' not in spec:
            raise ValueError('a reference library names both key and sha256')
        return {'mode': 'reference', 'key': _hex(spec['key'], 16, 'key'),
                'sha256': _hex(spec['sha256'], 64, 'sha256')}
    if mode == 'build':
        unknown = sorted(set(spec) - {'mode', 'runs', 'size', 'seed'})
        if unknown:
            raise ValueError(f'a build library names runs, size and seed, not {", ".join(unknown)}')
        stated = spec.get('runs')
        if isinstance(stated, str) or not hasattr(stated, '__iter__'):
            raise ValueError(f'runs must be a list of run ids, not {stated!r}')
        runs = [str(value).strip() for value in stated]
        if not runs or any(not value for value in runs):
            raise ValueError('a build library needs at least one non-empty run id')
        return {'mode': 'build', 'runs': runs,
                'size': _integer(spec.get('size', DEFAULT_SIZE), 'size', 1, MAX_SIZE),
                'seed': _integer(spec.get('seed', 0), 'seed', -2 ** 63, 2 ** 63 - 1)}
    raise ValueError(f"the library mode must be 'build' or 'reference', not {mode!r}")


def _hex(value, length, name):
    text = str(value).strip().lower()
    if len(text) != length or any(character not in '0123456789abcdef' for character in text):
        raise ValueError(f'{name} must be {length} hexadecimal characters, not {value!r}')
    return text


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f'{name} must be an integer, not {value!r}')
    if not low <= value <= high:
        raise ValueError(f'{name} must be between {low} and {high}, not {value!r}')
    return value


def key_for(workspace, spec):
    """The key a spec names: its own for a reference, derived from the source runs' identities for a build."""
    spec = normalise_spec(spec)
    if spec is None:
        raise ValueError('no conformation library was named')
    if spec['mode'] == 'reference':
        return spec['key']
    return _key_of(sources(Path(workspace), spec['runs']), spec['size'], spec['seed'])


def key_of_document(document):
    """The key a stored document's own content names, which a directory name must agree with."""
    detergent = _detergent_of_document(document['detergent'])
    pairs = [(entry['run_id'], entry['trajectory_identity']) for entry in document['sources']]
    return _key_block(detergent, document['selection'], pairs)


def resolve(workspace, spec, *, build=True):
    """The library a spec names, building it from its runs only when it has to.

    A build spec reuses a stored copy whose sidecar and digest match; a corrupt copy is rebuilt when `build` allows
    it. A reference spec never builds: a missing or changed copy is a refusal, because its source runs need not be
    in this workspace.
    """
    workspace = Path(workspace)
    spec = normalise_spec(spec)
    if spec is None:
        raise ValueError('no conformation library was named')
    if spec['mode'] == 'reference':
        return _resolve_reference(workspace, spec)
    return _resolve_build(workspace, spec, build=build)


def _resolve_reference(workspace, spec):
    directory = _locate(workspace, spec['key'])
    if directory is None:
        raise ValueError(f'the library {spec["key"]} is not in {store_root(workspace)}: copy the original back, '
                         'because its source runs need not be in this workspace')
    library = load(directory / DOCUMENT)
    if library.key != spec['key']:
        raise ValueError(f'{directory} is filed as {spec["key"]} but its content names the key {library.key}')
    verify(library, key=spec['key'], sha256=spec['sha256'])
    return library


def _resolve_build(workspace, spec, *, build):
    records = sources(workspace, spec['runs'])
    key = _key_of(records, spec['size'], spec['seed'])
    document = store_dir(workspace, records[0]['detergent'], key) / DOCUMENT
    if document.is_file():
        try:
            library = load(document)
            verify(library, key=key)
            return library
        except (OSError, ValueError):
            pass  # a corrupt copy is rebuilt below; `build=False` reports the key rather than the corruption
    if not build:
        raise ValueError(f'no library for these runs: {key} ({", ".join(spec["runs"])})')
    library, _record = _build(workspace, spec, records=records)
    return library


def build(workspace, spec):
    """Build a library from its source runs and write it into the store. Returns `(library, record)`.

    The record is the operator's, not the file's: kept, broken and non-finite counts, the frames read, the time it
    took and the producer versions. None of it is in `library.json`, because a rebuild from the same inputs must
    write the same bytes.
    """
    spec = normalise_spec(spec)
    if spec is None or spec['mode'] != 'build':
        raise ValueError('a library is built from source runs, not from a stored key')
    return _build(Path(workspace), spec)


def _build(workspace, spec, records=None):
    started = time.monotonic()
    records = records if records is not None else sources(workspace, spec['runs'])
    entries, counts = [], []
    for record in records:
        found, count = extract.candidates(workspace, record)
        entries.extend(found)
        counts.append(count)
    pool = sum(count['pool'] for count in counts)
    size = spec['size']
    if pool < size:
        raise ValueError(f'the pool holds {pool} molecules, fewer than the {size} asked for: '
                         f'{", ".join(spec["runs"])}')
    # The canonical candidate order, which is what the selection and the document both name.
    entries.sort(key=lambda entry: (entry['source']['run'], entry['source']['time_ns'], entry['source']['resid']))
    chosen = select.stratified(np.asarray([entry['descriptors'] for entry in entries], dtype=float),
                               size, spec['seed'])
    entries = [entries[index] for index in chosen]
    detergent = _detergent_of_record(records[0])
    # `stride` is the frame sampling the extraction used: `frames` alone does not say which frames the pool came
    # from, and the document has to let a reader audit the selection.
    stated = [{'run_id': record['run_id'], 'detergent': record['detergent'], 'trajectory': record['trajectory'],
               'trajectory_identity': record['trajectory_identity'], 'frames': count['frames'],
               'stride': count['stride'], 'pool': count['pool'], 'protein': False}
              for record, count in zip(records, counts)]
    document = {'format': FORMAT, 'detergent': detergent,
                'selection': {'size': size, 'seed': spec['seed'], 'method': METHOD,
                              'descriptors': list(DESCRIPTORS)},
                'sources': stated, 'pool': pool, 'entries': entries}
    key = _key_block(detergent, document['selection'],
                     [(entry['run_id'], entry['trajectory_identity']) for entry in stated])
    path = store(workspace, records[0]['detergent'], key, document)
    library = Library(key=key, sha256=hashlib.sha256(canonical_bytes(document)).hexdigest(), path=path,
                      document=document)
    record = {'key': key, 'path': str(path), 'sha256': library.sha256, 'size': size, 'pool': pool,
              'sources': stated, 'kept': sum(count['kept'] for count in counts),
              'broken': sum(count['broken'] for count in counts),
              'non_finite': sum(count['non_finite'] for count in counts),
              'seconds': round(time.monotonic() - started, 3), 'producer': extract.producer()}
    return library, record


def load(path):
    """One stored library from its `library.json` (or the directory holding it), verified only as JSON and schema.

    The digest is the file's own bytes. A caller that holds a recorded digest compares it itself (or through
    `verify`); `load` does not demand a sidecar, because a caller may be reading a file the store does not own.
    """
    path = Path(path)
    if path.is_dir():
        path = path / DOCUMENT
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ValueError(f'{path} is not a conformation library: {error}') from error
    try:
        document = json.loads(data)
    except ValueError as error:
        raise ValueError(f'{path} is not a readable conformation library: {error}') from error
    _check_document(document, path)
    return Library(key=key_of_document(document), sha256=hashlib.sha256(data).hexdigest(), path=path,
                   document=document)


def verify(library, *, key=None, sha256=None):
    """Refuse a stored library whose sidecar, digest, key or entry count disagrees with the caller's record."""
    sidecar = library.path.parent / SIDECAR
    if not sidecar.is_file():
        raise ValueError(f'{library.path} has no {SIDECAR} beside it: it cannot be verified')
    stated = sidecar.read_text().strip()
    if stated != library.sha256:
        raise ValueError(f'{library.path} has digest {library.sha256} but its {SIDECAR} states {stated}: '
                         'the file was changed after the digest was written')
    if key is not None and str(key) != library.key:
        raise ValueError(f'{library.path} is filed as {key} but its content names the key {library.key}')
    if sha256 is not None and str(sha256).strip().lower() != library.sha256:
        raise ValueError(f'{library.path} has digest {library.sha256}, not the recorded {sha256}')
    if library.size != len(library.entries):
        raise ValueError(f'{library.path} states {library.size} entries but holds {len(library.entries)}')


def store(workspace, residue, key, document):
    """Write one library into the workspace store and return the path of its `library.json`.

    The write is a temp file in the same directory and `os.replace`, under an exclusive flock on `<dir>.lock`, so a
    reader never sees a partial document and two builders end with one. An existing valid copy with different bytes
    is refused rather than overwritten: a run may pin its digest.
    """
    directory = store_dir(workspace, residue, key)
    directory.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(document)
    digest = hashlib.sha256(payload).hexdigest()
    lock = Path(str(directory) + '.lock')
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            current = directory / DOCUMENT
            _refuse_overwrite(current, digest, key)
            _atomic_write(current, payload)
            _atomic_write(directory / SIDECAR, (digest + '\n').encode('ascii'))
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    return directory / DOCUMENT


def _refuse_overwrite(path, digest, key):
    """Refuse to replace a valid stored library with different bytes; a broken copy is repaired instead."""
    if not path.is_file():
        return
    state = path.parent / SIDECAR
    current = path.read_bytes()
    if not state.is_file() or state.read_text().strip() != hashlib.sha256(current).hexdigest():
        return
    if hashlib.sha256(current).hexdigest() != digest:
        raise ValueError(f'{path} holds a different library for key {key}: refusing to replace a digest a run may pin')


def _atomic_write(path, payload):
    """Write one file by replacing it, so no reader or crash ever sees a partial one."""
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def available(workspace, residue=None):
    """The stored libraries a caller may select, newest-agnostic and sorted: only readable, verified directories."""
    root = store_root(workspace)
    found = []
    for detergent in sorted(root.glob('*')) if root.is_dir() else ():
        if not detergent.is_dir() or (residue is not None and detergent.name != str(residue)):
            continue
        for directory in sorted(detergent.glob('*')):
            if not directory.is_dir():
                continue
            try:
                library = load(directory / DOCUMENT)
                verify(library, key=directory.name)
            except (OSError, ValueError):
                continue
            found.append({'key': library.key, 'residue': library.residue, 'size': library.size,
                          'sha256': library.sha256, 'sources': [entry['run_id'] for entry in library.sources],
                          'path': str(directory / DOCUMENT)})
    return found


def store_root(workspace):
    return Path(workspace) / STORE


def store_dir(workspace, residue, key):
    return store_root(workspace) / str(residue) / str(key)


def canonical_bytes(document):
    """The one byte spelling of a library document: sorted keys, no spaces, ASCII, one trailing newline."""
    return (json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def _locate(workspace, key):
    """The store directory filed under one key, or `None`; more than one is a corrupt store rather than a guess."""
    root = store_root(workspace)
    matches = sorted(path for path in root.glob(f'*/{key}') if path.is_dir())
    if len(matches) > 1:
        raise ValueError(f'the key {key} is filed under more than one residue '
                         f'({", ".join(path.parent.name for path in matches)}): one copy is corrupt')
    return matches[0] if matches else None


def _key_of(records, size, seed):
    return _key_block(_detergent_of_record(records[0]), {'size': size, 'seed': seed, 'method': METHOD},
                      [(record['run_id'], record['trajectory_identity']) for record in records])


def _key_block(detergent, selection, pairs):
    canonical = {'format': FORMAT, 'detergent': detergent,
                 'selection': {'size': int(selection['size']), 'seed': int(selection['seed']),
                               'method': str(selection.get('method') or METHOD)},
                 'sources': sorted([str(run_id), str(identity)] for run_id, identity in pairs)}
    return hashlib.sha256(_compact(canonical)).hexdigest()[:16]


def _detergent_of_record(record):
    """A validated source record's detergent block: its beads are the geometry records the extraction reads."""
    return {'residue': str(record['detergent']), 'beads': [str(bead['name']) for bead in record['beads']],
            'mapping_sha256': str(record['mapping_sha256'])}


def _detergent_of_document(block):
    """A stored document's detergent block, in the words the key derivation and the placement both read."""
    return {'residue': str(block['residue']), 'beads': [str(name) for name in block['beads']],
            'mapping_sha256': str(block['mapping_sha256'])}


def _compact(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def _check_document(document, path):
    """The schema a stored library must have before anything trusts its fields."""
    def require(condition, sentence):
        if not condition:
            raise ValueError(f'{path} is not a conformation library: {sentence}')

    require(isinstance(document, dict), 'it is not a JSON object')
    require(document.get('format') == FORMAT, f'its format is {document.get("format")!r}, not {FORMAT!r}')
    detergent = document.get('detergent')
    require(isinstance(detergent, dict) and isinstance(detergent.get('residue'), str) and detergent['residue'],
            'its detergent block names no residue')
    require(isinstance(detergent.get('beads'), list) and detergent['beads']
            and all(isinstance(name, str) and name for name in detergent['beads']),
            'its detergent block names no beads')
    require(isinstance(detergent.get('mapping_sha256'), str) and len(detergent['mapping_sha256']) == 64,
            'its detergent block names no mapping digest')
    selection = document.get('selection')
    require(isinstance(selection, dict), 'it states no selection')
    require(isinstance(selection.get('size'), int) and 1 <= selection['size'] <= MAX_SIZE,
            f'its selection size is {selection.get("size")!r}')
    require(isinstance(selection.get('seed'), int) and not isinstance(selection['seed'], bool),
            f'its selection seed is {selection.get("seed")!r}')
    require(selection.get('method') == METHOD, f'its selection method is {selection.get("method")!r}')
    require(list(selection.get('descriptors') or ()) == list(DESCRIPTORS), 'its descriptors are not the four the '
            'format states')
    stated = document.get('sources')
    require(isinstance(stated, list) and stated, 'it names no sources')
    for entry in stated:
        require(isinstance(entry, dict) and isinstance(entry.get('run_id'), str) and entry['run_id']
                and isinstance(entry.get('detergent'), str) and isinstance(entry.get('trajectory'), str)
                and isinstance(entry.get('trajectory_identity'), str) and entry['trajectory_identity'],
                f'one source is unreadable: {entry!r}')
        require(isinstance(entry.get('frames'), int) and entry['frames'] >= 0, f'one source has no frame count: {entry!r}')
        require(isinstance(entry.get('stride'), int) and entry['stride'] >= 1, f'one source has no frame stride: {entry!r}')
        require(isinstance(entry.get('pool'), int) and entry['pool'] >= 0, f'one source has no pool: {entry!r}')
        require(entry.get('protein') is False, f'one source names a protein: {entry!r}')
    require(isinstance(document.get('pool'), int) and document['pool'] >= 0,
            f'its pool is {document.get("pool")!r}')
    entries = document.get('entries')
    require(isinstance(entries, list), 'it holds no entry list')
    width = len(detergent['beads'])
    for entry in entries:
        require(isinstance(entry, dict), f'one entry is not an object: {entry!r}')
        beads = entry.get('beads')
        require(isinstance(beads, list) and len(beads) == width
                and all(isinstance(point, list) and len(point) == 3 and all(_finite(value) for value in point)
                        for point in beads), f'one entry does not hold {width} finite beads: {entry!r}')
        descriptors = entry.get('descriptors')
        require(isinstance(descriptors, list) and len(descriptors) == len(DESCRIPTORS)
                and all(_finite(value) for value in descriptors), f'one entry has no descriptors: {entry!r}')
        stated_source = entry.get('source')
        require(isinstance(stated_source, dict) and isinstance(stated_source.get('run'), int)
                and 0 <= stated_source['run'] < len(stated) and _finite(stated_source.get('time_ns'))
                and isinstance(stated_source.get('resid'), int), f'one entry has no source: {entry!r}')


def _finite(value):
    """Whether a stored number is finite and not a bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and np.isfinite(float(value))
