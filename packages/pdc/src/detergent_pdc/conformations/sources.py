"""Validating the micelle-only runs a conformation library is built from.

A library is only as pure as its sources, so this module refuses a source run before a single frame is read and says
which run and why. The one ensemble a library may be built from is an **empty micelle**: a completed `pdc` run with
no protein. A protein-contacted micelle is a different ensemble, and pooling the two would put shapes into the
library the builder never asked them to fit.

What a run has to state for itself:

* the run directory is `<workspace>/runs/<id>` and holds a `manifest.json`;
* the run ended `completed` and is a `pdc` run;
* the manifest's `protein` is blank;
* its `inputs` record holds a `mapping` entry, which carries the mapping's digest;
* `inputs/detergent_CG.json` states the residue and each bead's name, type and position -- the geometry the mapping
  derived -- and `inputs/detergent_CG.itp` states the bead connectivity and, for a `funct 1` bond or constraint, its
  own reference length;
* a production trajectory exists, found the way the analysis code finds one: the last segment that is not skipped,
  not a duplicate of another segment, and not the re-declared copy a final assessment names.

Every run in one library must also agree with every other: one residue, one mapping digest, the same bead names and
the same connectivity. The library's detergent block is that one agreement, so a run whose mapping differs is
refused here rather than discovered by a placement that stamps the wrong beads.

The trajectory is read from the run's stage root and recorded relative to it, which is the spelling
`detergent_pdc.segments` reports; `trajectory_identity` is the cheap content hash the segments reader already uses,
so a library's key changes when a trajectory is re-written and not when it is copied.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from dashboard import features
from dashboard.analysis.runs import layout
from dashboard.analysis.runs import segments as engine
from detergent_pdc import segments as pdc_segments

MANIFEST = 'manifest.json'
GEOMETRY = 'detergent_CG.json'
TOPOLOGY = 'detergent_CG.itp'
#: A run id is a directory name: letters, digits, dot, dash or underscore. A path is never a run id.
RUN_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
#: A residue name is a directory name in the store, so it is limited to what GROMACS itself writes.
RESIDUE = re.compile(r'[A-Za-z0-9][A-Za-z0-9+-]*')


def sources(workspace, run_ids):
    """The validated source records for one library, in the caller's order.

    Each record carries what the library document names (`run_id`, `detergent`, `trajectory`,
    `trajectory_identity`) and what the extraction needs (`beads`, `bonds`, `structure_path`,
    `trajectory_path`, `stage_root`, `index`). `frames` and `pool` are not here: only a trajectory read can count
    them, and `library.build` fills them from the extraction's own counts.
    """
    if isinstance(run_ids, str) or not hasattr(run_ids, '__iter__'):
        raise ValueError(f'run ids must be a list of run ids, not {run_ids!r}')
    names = []
    for value in run_ids:
        name = str(value).strip()
        if not RUN_ID.fullmatch(name) or name in ('.', '..'):
            raise ValueError(f'{value!r} is not a run id: expected letters, digits, dot, dash or underscore')
        names.append(name)
    if not names:
        raise ValueError('a conformation library needs at least one source run')
    seen = set()
    for name in names:
        if name in seen:
            raise ValueError(f'the run {name} is named twice: each source run counts once')
        seen.add(name)
    records = [_record(Path(workspace), name, index) for index, name in enumerate(names)]
    _agree(records)
    return records


def _record(workspace, run_id, index):
    run = workspace / 'runs' / run_id
    if not run.is_dir():
        raise ValueError(f'run {run_id} is not in this workspace: {run} is missing')
    manifest = _json(run / MANIFEST, run_id)
    status = str(manifest.get('status') or '').strip()
    if status != 'completed':
        raise ValueError(f'run {run_id} is not completed (status {status or "missing"}): '
                         'only a completed run supplies settled conformations')
    run_type = str(manifest.get('run_type') or '').strip()
    if run_type != 'pdc':
        raise ValueError(f'run {run_id} is a {run_type or "missing"} run, not a pdc run: '
                         'only a protein-detergent build places detergents')
    protein = manifest.get('protein')
    if protein:
        raise ValueError(f'run {run_id} carries a protein ({protein}): '
                         'a protein-contacted micelle is a different ensemble')
    mapping = next((entry for entry in manifest.get('inputs') or ()
                    if isinstance(entry, dict) and entry.get('role') == 'mapping'), None)
    if mapping is None or not str(mapping.get('sha256') or '').strip():
        raise ValueError(f'run {run_id} records no mapping input: its detergent has no bead model to shape')
    residue, beads = _geometry(run / 'inputs' / GEOMETRY, run_id)
    bonds = _connectivity(run / 'inputs' / TOPOLOGY, run_id, len(beads))
    stage_root = layout.stage_root(run)
    segment, trajectory_path, structure_path = _production(run_id, stage_root)
    return {'index': index, 'run_id': run_id, 'detergent': residue, 'mapping_sha256': str(mapping['sha256']).strip(),
            'beads': beads, 'bonds': bonds, 'stage_root': stage_root, 'structure': segment['structure'],
            'trajectory': segment['trajectory'], 'trajectory_identity': engine.identity(trajectory_path),
            'structure_path': structure_path, 'trajectory_path': trajectory_path}


def _json(path, run_id):
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise ValueError(f'run {run_id} has no {path.name}: {path} is missing') from error
    except (OSError, ValueError) as error:
        raise ValueError(f'run {run_id} has an unreadable {path.name}: {error}') from error
    if not isinstance(data, dict):
        raise ValueError(f'run {run_id} has a {path.name} that is not a JSON object')
    return data


def _geometry(path, run_id):
    """The residue and each bead's name, type and position, from the run's own mapping-derived geometry."""
    geometry = _json(path, run_id)
    residue = str(geometry.get('residue') or '').strip()
    if not residue:
        raise ValueError(f'run {run_id} states no residue in {GEOMETRY}')
    if not RESIDUE.fullmatch(residue):
        raise ValueError(f'run {run_id} names the residue {residue!r}, which is not a residue name')
    stated = geometry.get('beads')
    if not isinstance(stated, list) or not stated:
        raise ValueError(f'run {run_id} states no beads in {GEOMETRY}: there is no molecule to shape')
    beads, names = [], set()
    for bead in stated:
        name = str(bead.get('name') or '').strip() if isinstance(bead, dict) else ''
        position = bead.get('position') if isinstance(bead, dict) else None
        if not name or name in names or not isinstance(position, (list, tuple)) or len(position) != 3:
            raise ValueError(f'run {run_id} has an unreadable bead in {GEOMETRY}: {bead!r}')
        try:
            point = [float(value) for value in position]
        except (TypeError, ValueError) as error:
            raise ValueError(f'run {run_id} has a non-numeric position for bead {name!r}: {position!r}') from error
        if not all(math.isfinite(value) for value in point):
            raise ValueError(f'run {run_id} has a non-finite position for bead {name!r}: {position!r}')
        names.add(name)
        beads.append({'name': name, 'type': str(bead.get('type') or ''), 'position': point})
    return residue, beads


def _connectivity(path, run_id, bead_count):
    """The bead pairs one molecule is built from, 0-based in the geometry's order, with a stated length or `None`.

    The itp's `[ bonds ]` are the terms a reader expects; `[ constraints ]` and `[ virtual_sitesn ]` say the same
    thing about which beads share one image, and a molecule made whole from its bonds alone leaves a ring sugar's
    beads in their own fragments. All three are read so `make_whole` sees one connected molecule.

    A `funct 1` bond or constraint states its own reference length in the fourth column, and that is what the
    extraction checks against. A pair without one -- a virtual site's parents, or a bonded function whose columns do
    not carry a length -- is connectivity only: its separation is derived rather than bonded, so it is never measured
    against a length. Refused here: an unreadable index, a stated length that is not a positive finite number, and a
    pair the topology states two different lengths for (one reference, or no check at all).

    A molecule whose graph is not connected is refused: an isolated bead would keep whatever image the trajectory
    gave it, and nothing would notice.
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'run {run_id} has no {TOPOLOGY}: {path} is missing')
    pairs = {}
    section = ''
    try:
        text = path.read_text(errors='replace')
    except OSError as error:
        raise ValueError(f'run {run_id} has an unreadable {TOPOLOGY}: {error}') from error
    for index, line in enumerate(text.splitlines(), start=1):
        content = line.split(';', 1)[0].strip()
        if not content:
            continue
        if content.startswith('[') and content.endswith(']'):
            section = content[1:-1].strip().lower()
            continue
        fields = content.split()
        found = []
        if section in ('bonds', 'constraints') and len(fields) >= 2:
            found = [(fields[0], fields[1], _stated(fields, run_id, section, index, line))]
        elif section == 'virtual_sitesn' and len(fields) >= 3:
            found = [(fields[0], parent, None) for parent in fields[2:]]
        for first, second, length in found:
            try:
                left, right = int(first) - 1, int(second) - 1
            except ValueError as error:
                raise ValueError(f'run {run_id} has an unreadable {TOPOLOGY} {section} line {index}: {line!r}') from error
            if not (0 <= left < bead_count and 0 <= right < bead_count):
                raise ValueError(f'run {run_id} has a {TOPOLOGY} {section} line {index} naming a bead outside its '
                                 f'{bead_count} beads: {line!r}')
            if left == right:
                continue
            pair = (min(left, right), max(left, right))
            if length is None:
                pairs.setdefault(pair, None)
            elif pair in pairs and pairs[pair] is not None and pairs[pair] != length:
                raise ValueError(f'run {run_id} states two lengths in {TOPOLOGY} for the beads {pair}: '
                                 f'{pairs[pair]} and {length}')
            else:
                pairs[pair] = length
    if not pairs:
        raise ValueError(f'run {run_id} states no connectivity in {TOPOLOGY}: a molecule with no bonds cannot be made whole')
    _connected(run_id, bead_count, list(pairs))
    return sorted((first, second, length) for (first, second), length in pairs.items())


def _stated(fields, run_id, section, index, line):
    """The length a `funct 1` bond or constraint states, or `None` for a term that states none."""
    if len(fields) < 4 or fields[2] != '1':
        return None
    try:
        length = float(fields[3])
    except ValueError as error:
        raise ValueError(f'run {run_id} has an unreadable {TOPOLOGY} {section} line {index}: {line!r}') from error
    if not math.isfinite(length) or length <= 0:
        raise ValueError(f'run {run_id} states a length of {fields[3]!r} in {TOPOLOGY} {section} line {index}: '
                         'a reference length must be a positive number')
    return length


def _connected(run_id, bead_count, pairs):
    """Refuse a molecule whose connectivity does not reach every bead; see `_connectivity`."""
    parent = list(range(bead_count))

    def root(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for left, right in pairs:
        parent[root(left)] = root(right)
    islands = sorted({root(node) + 1 for node in range(bead_count)})
    if len(islands) > 1:
        raise ValueError(f'run {run_id} states a molecule in {TOPOLOGY} whose beads are not all connected '
                         f'(beads {islands} start separate molecules): every bead must share one image')


def _production(run_id, stage_root):
    """The run's production trajectory as `detergent_pdc.segments` reports it, with its own structure."""
    features.ensure()
    chosen = None
    for entry in pdc_segments.segments(stage_root):
        if entry.get('skipped') or entry.get('duplicate_of') or not entry.get('trajectory'):
            continue
        chosen = entry
    if chosen is None:
        raise ValueError(f'run {run_id} has no production trajectory: its stage root {stage_root} holds no leg with one')
    trajectory = stage_root / chosen['trajectory']
    structure = stage_root / chosen['structure']
    if not trajectory.is_file():
        raise ValueError(f'run {run_id} names the trajectory {chosen["trajectory"]} but {trajectory} is missing')
    if not structure.is_file():
        raise ValueError(f'run {run_id} names the structure {chosen["structure"]} but {structure} is missing')
    return chosen, trajectory, structure


def _agree(records):
    """Every run in one library states one detergent: the same residue, mapping, bead names and connectivity."""
    first = records[0]
    first_names = [bead['name'] for bead in first['beads']]
    for record in records[1:]:
        if record['detergent'] != first['detergent']:
            raise ValueError(f'run {record["run_id"]} is {record["detergent"]!r} but run {first["run_id"]} is '
                             f'{first["detergent"]!r}: a library holds one detergent')
        if record['mapping_sha256'] != first['mapping_sha256']:
            raise ValueError(f'run {record["run_id"]} was built from mapping {record["mapping_sha256"]} but run '
                             f'{first["run_id"]} from {first["mapping_sha256"]}: one library needs one mapping')
        names = [bead['name'] for bead in record['beads']]
        if names != first_names:
            raise ValueError(f'run {record["run_id"]} states the beads {names} but run {first["run_id"]} states '
                             f'{first_names}: one library needs one bead order')
        if record['bonds'] != first['bonds']:
            raise ValueError(f'run {record["run_id"]} states different connectivity from run {first["run_id"]}: '
                             'one library needs one molecule')
