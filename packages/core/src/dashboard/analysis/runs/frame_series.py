"""A run's own trajectory sampled into one multi-model PDB a viewer can play, on request.

Run view plays a trajectory by loading a file, and the vendored NGL has no XTC or TRR parser, so the frames have to be
written server-side. This is that writer as an on-demand analysis rather than a cadence: a person asks for a segment, a
time window, a stride and a view, and the attempt records exactly what it was asked for beside the frames.

Nothing here reads a trajectory on page load. The panel names the files it wants through the payload -- the same
run-relative paths `GET /api/jobs/<id>/trajectory` reports -- and the queue resolves and hashes them through `sources`,
so the chosen trajectory is part of the analysis signature and a changed file is a new attempt rather than a stale
series. `sources` is the strict half (it runs before an attempt exists, so a bad request is a 400 and no task);
`run` is the producer (it reads the staged copies the worker made).

Two things are views rather than measurements, and the file says so: `fit` superposes every model on the first one, and
`assembled` moves whole molecules by periodic images and centres the protein for display. Neither rewrites the run.
"""
import json
import math
from pathlib import Path

import numpy as np

from ... import features, files
from . import layout, segments, structures

try:
    import MDAnalysis as mda
except ImportError:  # a frame series needs a trajectory reader; `run` refuses in its own words
    mda = None

#: The most models one series may hold. A viewer loads the whole file, so this is the cap that keeps a long
#: trajectory from publishing a file no browser should be handed.
MAX_MODELS = 240
#: The most a series may be estimated to weigh, in bytes: one HETATM line per atom per model, plus the model's
#: records. Refused before any frame is read.
MAX_BYTES = 250_000_000
#: What `stride: 'auto'` aims at: about one model every `frames / AUTO_MODELS` frames.
AUTO_MODELS = 120
#: The bytes one atom contributes to the estimate: a HETATM record plus its share of a CONECT record.
BYTES_PER_ATOM = 120

FIT_MODES = ('none', 'protein', 'beads')
ATOM_MODES = ('all', 'beads', 'ca')


def _nanoseconds(payload, field):
    """One optional window edge in nanoseconds: a finite number, or `None` for the file's own end."""
    value = payload.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{field} must be a number of nanoseconds or null, not {value!r}')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{field} must be a finite number of nanoseconds, not {value!r}')
    return value


def _run_relative(payload, field):
    """One required path, exactly as the trajectory endpoint spells it: relative, and with no way out of the run."""
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"frame-series needs a {field} path: a run-relative file from the run's trajectory endpoint")
    relative = Path(value)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError(f'the {field} must be a path inside this run, not {value!r}')
    return value


def _settings(payload):
    """The arguments, validated strictly and filled with their defaults. Unknown keys are ignored."""
    if not isinstance(payload, dict):
        raise ValueError(f'frame-series takes an object of arguments, not {type(payload).__name__}')
    start, end = _nanoseconds(payload, 'start_ns'), _nanoseconds(payload, 'end_ns')
    if start is not None and end is not None and start > end:
        raise ValueError(f'start_ns {start:g} is after end_ns {end:g}: a window starts at or before it ends')
    stride = payload.get('stride')
    if stride is None or stride == 'auto':
        stride = None
    elif isinstance(stride, bool) or not isinstance(stride, int) or stride < 1:
        raise ValueError(f"stride must be a whole number of frames at least 1, 'auto', or null, not {stride!r}")
    fit = payload.get('fit', 'none')
    if not isinstance(fit, str) or fit not in FIT_MODES:
        raise ValueError(f"fit must be one of {', '.join(FIT_MODES)}, not {fit!r}")
    fragment = payload.get('fragment')
    if fragment is not None:
        letter = fragment.strip() if isinstance(fragment, str) else ''
        if len(letter) != 1 or not letter.isalpha():
            raise ValueError(f"fragment must be one letter of the run's mapping, not {fragment!r}")
        fragment = letter.upper()
    if fit == 'beads' and fragment is None:
        raise ValueError("fit 'beads' needs a fragment letter: the run's own mapping states which beads make up "
                         'which ring')
    atoms = payload.get('atoms', 'beads')
    if not isinstance(atoms, str) or atoms not in ATOM_MODES:
        raise ValueError(f"atoms must be one of {', '.join(ATOM_MODES)}, not {atoms!r}")
    assembled = payload.get('assembled', False)
    if not isinstance(assembled, bool):
        raise ValueError(f'assembled must be true or false, not {assembled!r}')
    return {'trajectory': _run_relative(payload, 'trajectory'), 'structure': _run_relative(payload, 'structure'),
            'start_ns': start, 'end_ns': end, 'stride': stride, 'fit': fit, 'fragment': fragment,
            'atoms': atoms, 'assembled': assembled}


def _manifest(run_dir):
    """A run's manifest, or `{}` when it has none: an absent record is a state, not a reason to refuse a picture."""
    try:
        data = json.loads((Path(run_dir) / 'manifest.json').read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _inside(run_dir, path):
    """Whether `path` is a file strictly inside the run, reachable without a symbolic link.

    The payload names files, so this is a trust boundary: `segments.present` is happy with anything that exists, and
    a symlink anywhere on the way to it is refused rather than followed out of the run.
    """
    root = Path(run_dir)
    candidate = Path(path)
    if not candidate.is_file():
        return False
    anchor = root.absolute()
    candidate = candidate.absolute()
    try:
        candidate.resolve().relative_to(anchor.resolve())
    except ValueError:
        return False
    return not any(part.is_symlink() for part in (candidate, *candidate.parents)
                   if part == anchor or part.is_relative_to(anchor))


def _recorded_inside(run_dir, path):
    """Whether a file the run recorded resolves to a file inside it -- a symlink into `inputs/` included.

    The payload's pair is stricter (`_inside`): a request names those paths. These are outputs the run itself records,
    and a stage may keep one as a symlink into the run's `inputs/` (measured: `b920391735dd`'s `detergent_CG.itp`). The
    target must still be this run's file; only the link is allowed.
    """
    try:
        target = Path(path).resolve()
    except OSError:
        return False
    return target.is_file() and target.is_relative_to(Path(run_dir).resolve())


def _spelling(run_dir, path):
    """A recorded file's path under the run, as the run spells it, without following a link.

    The stage spelling is what the producer's `layout` resolver looks for in its work directory: keying by the
    resolved target would stage `inputs/detergent_CG.itp` where the resolver looks under `stages/`.
    """
    try:
        return Path(path).relative_to(Path(run_dir)).as_posix()
    except ValueError:
        return None


def sources(run_dir, payload=None):
    """The files this request reads: the chosen trajectory and structure, and the run's writer inputs when present.

    The keys are what the producer looks its files up by in the work directory. The trajectory and the structure keep
    the payload's own spelling, because that is the name `/trajectory` answered with and the name `frames.json` has to
    repeat; the writer's extras are keyed by their run-relative path, which is the spelling `structures` and `layout`
    already read a staged tree by. A missing extra is not an error -- a run with no mapping, topology or protein is
    still a run of coordinates -- but a malformed payload always is.
    """
    run_dir = Path(run_dir)
    settings = _settings({} if payload is None else payload)
    entries = {}
    for field in ('trajectory', 'structure'):
        relative = settings[field]
        found = segments.present(run_dir, relative)
        if found is None or not _inside(run_dir, found):
            raise ValueError(f'the {field} {relative!r} is not a file inside this run: a frame series reads the '
                             'paths the run trajectory endpoint reports')
        entries[relative] = found
    # The run's own mapping, topologies and protein chains: the writer needs them for beads, fragments and bonds, and
    # they are recorded outputs rather than paths a request names, so a stage's symlink into `inputs/` is still this
    # run's file. Each is staged under its own run-relative spelling, because that is where `layout` looks for it.
    for relative in ('2_mapping/model.json', 'stages/2_mapping/model.json'):
        path = run_dir / relative
        if path.is_file() and _recorded_inside(run_dir, path):
            entries.setdefault(relative, path)
            break
    manifest = _manifest(run_dir)
    topology = layout.recorded_topology(run_dir, manifest.get('run_type'), manifest)
    if topology is not None:
        relative = _spelling(run_dir, topology)
        if relative and _recorded_inside(run_dir, topology):
            entries.setdefault(relative, topology)
    try:
        protein = features.protein_topologies(run_dir) or []
    except (OSError, ValueError):
        protein = []
    for row in protein:
        path = Path(str((row or {}).get('path') or ''))
        if not path.name:
            continue
        relative = _spelling(run_dir, path)
        if relative and _recorded_inside(run_dir, path):
            entries.setdefault(relative, path)
    return entries


def _sample_indices(n_frames, first_ns, dt_ps, settings):
    """`(frame indices, effective stride)` for the window and stride asked for, first selected frame always in.

    Frame numbers are computed from the trajectory's own first time and time step rather than from a list of every
    frame's time: reading that list means walking the whole file (40 s for a live 100 ns, 2.5 GB XTC), and the walk
    is what the producer then has to repeat for the frames it samples. A GROMACS `.xtc` writes its frames on a fixed
    step, which is what this arithmetic is; a file whose steps vary is not one this window can name exactly.
    """
    start, end = settings['start_ns'], settings['end_ns']
    stride = settings['stride']
    if start is not None or end is not None:
        if not dt_ps or dt_ps <= 0:
            raise ValueError('this trajectory states no time step, so a window in nanoseconds selects nothing: '
                             'ask for the whole file instead')
        last_ns = first_ns + (n_frames - 1) * dt_ps / 1000.0
        low = 0 if start is None else max(0, math.ceil((start - first_ns) * 1000.0 / dt_ps - 1e-9))
        high = (n_frames - 1 if end is None
                else min(n_frames - 1, math.floor((end - first_ns) * 1000.0 / dt_ps + 1e-9)))
        if high < low:
            raise ValueError(f'the window {start!r}-{end!r} ns selects no frame; this trajectory runs '
                             f'{first_ns:g}-{last_ns:g} ns')
        selected = list(range(low, high + 1))
    else:
        selected = list(range(n_frames))
    if stride is None:
        stride = max(1, math.ceil(len(selected) / AUTO_MODELS))
    return selected[::stride], stride


def _written_atoms(universe, mode):
    """The atoms the file holds: every one for a bead system, the named CA for an atomistic backbone."""
    if mode != 'ca':
        return np.arange(len(universe.atoms), dtype=int)
    selected = universe.select_atoms('name CA')
    if not len(selected):
        raise ValueError("atoms 'ca' selected no atom named CA: this trajectory is coarse-grained or holds no backbone")
    return np.asarray(selected.indices, dtype=int)


def _protein_atoms(universe, protein_topologies):
    """The protein's leading atoms: the moleculetypes' own bead counts, else MDAnalysis's own selection.

    A protein-detergent trajectory puts the protein first, so the chains' atom counts name its block exactly (the same
    rule `structures._detergent_residue` reads the detergent by). A run with no protein moleculetype -- an AA run, or
    a CG consumer whose build wrote none -- is read by the topology's residue names instead.
    """
    leading = sum(len(row.get('atoms') or ()) for row in protein_topologies or ())
    if protein_topologies and 0 < leading <= len(universe.atoms):
        return np.arange(leading, dtype=int)
    return np.asarray(universe.select_atoms('protein').indices, dtype=int)


def _fit_selection(universe, settings, written, subunits, protein):
    """The atoms the fit is computed on, or `None` when no fit was asked for; and the fragment it names.

    The fit's own atoms are the ones the Kabsch rotation comes from; applying it to every atom is what leaves the rest
    of the molecule free to move relative to them. A selection that holds no atom this file writes is refused rather
    than fitted on everything, because that would answer a different question with the same picture.
    """
    if settings['fit'] == 'none':
        return None, None
    if settings['fit'] == 'protein':
        selection, target = protein, None
    else:
        wanted = settings['fragment']
        names = [str(name).strip().upper() for name in universe.atoms.names]
        selection = np.asarray([index for index, name in enumerate(names) if subunits.get(name) == wanted],
                               dtype=int)
        target = wanted
        if not len(selection):
            groups = {}
            for name, fragment in subunits.items():
                groups.setdefault(fragment, []).append(name)
            stated = ', '.join(f'{fragment} ({", ".join(sorted(members))})'
                               for fragment, members in sorted(groups.items())) or 'no fragment'
            raise ValueError(f"The run's own mapping places no bead in fragment '{wanted}', so there is nothing to "
                             f'fit on: it states {stated}')
    if not len(selection):
        raise ValueError("fit 'protein' selected no protein atom: this run states no protein to hold still")
    selection = selection[np.isin(selection, written)]
    if not len(selection):
        raise ValueError('the fit selection holds no atom this series writes: fit something the file shows')
    return selection, target


def _fit_positions(mobile, reference, selection):
    """The rotation and translation that superpose `mobile` on `reference`, and the RMSD that remains, in ångström.

    Kabsch, written out rather than called: the reference is the first sampled frame's coordinate array, and the fit is
    a dozen lines a test can hold against a known rotation. A reflection is flipped to a rotation explicitly -- an
    improper fit would mirror the molecule and call it motion.
    """
    mobile_centroid, reference_centroid = mobile[selection].mean(axis=0), reference[selection].mean(axis=0)
    centred, target = mobile - mobile_centroid, reference - reference_centroid
    left, _, right = np.linalg.svd(centred[selection].T @ target[selection])
    rotation = left @ right
    if np.linalg.det(rotation) < 0:
        left[:, -1] *= -1
        rotation = left @ right
    fitted = centred @ rotation + reference_centroid
    judged = fitted[selection] - reference[selection]
    return fitted, float(np.sqrt((judged ** 2).sum(axis=1).mean()))


def _fit_record(rmsds, atoms, *, target=None, of=None):
    """What a fitted series states about its own fit: how many atoms were held and how far they moved, in nm."""
    record = {'reference': 1, 'atoms': int(atoms),
              'rmsd_nm': {'min': round(min(rmsds) / 10.0, 4), 'max': round(max(rmsds) / 10.0, 4),
                          'mean': round(float(np.mean(rmsds)) / 10.0, 4)}}
    if target:
        # Which fragment was held still: a reader comparing two fittings has to tell one ring's fit from another's.
        record['target'] = target
    if of is not None:
        record['of'] = int(of)
    return record


def _molecules(universe):
    """The trajectory's atoms grouped by molecule, in the order the coordinates first show them."""
    groups = {}
    for index, key in enumerate(zip(universe.atoms.resnames, universe.atoms.resids)):
        groups.setdefault((str(key[0]), int(key[1])), []).append(index)
    return [np.asarray(indices, dtype=int) for indices in groups.values()]


def _box(universe, structure):
    """The frame's box vectors in ångström: the trajectory's own, else the structure's, or `None` when neither states one."""
    if universe.dimensions is not None:
        lengths = np.asarray(universe.dimensions[:3], dtype=float)
        if np.all(np.isfinite(lengths)) and np.all(lengths > 0):
            return lengths
    try:
        lengths = np.asarray(structures.read_gro_box(structure), dtype=float)[:3] * 10.0  # nm -> Angstrom
    except (OSError, ValueError):
        return None
    return lengths if np.all(np.isfinite(lengths)) and np.all(lengths > 0) else None


def _assemble(positions, box, groups, fixed):
    """Every molecule moved by whole periodic images to the anchor, then the anchor centred for display.

    A view, not a rewrite: the trajectory keeps its own frames and only the file says it was assembled. The anchor is
    the protein when the run states one, and the first molecule when it does not -- a run with no protein still gets
    its molecules gathered instead of split across the box.
    """
    if box is None:
        raise ValueError('assembled needs a box: neither the trajectory nor the structure states one')
    moved = np.asarray(positions, dtype=float).copy()
    # ponytail: orthogonal boxes only -- whole images are the box lengths. A triclinic box would need its own vectors.
    anchor = moved[fixed].mean(axis=0)
    fixed_atoms = set(fixed.tolist())
    for group in groups:
        if all(index in fixed_atoms for index in group):
            continue
        shift = np.round((anchor - moved[group].mean(axis=0)) / box)
        moved[group] += shift * box
    return moved - moved[fixed].mean(axis=0)


def _frame_atoms(universe, positions, written):
    """One frame as the `read_gro`-shaped dicts `structures.series_pdb` takes, in nanometres.

    The three topology columns are read once per frame, not once per atom: `atoms.names[i]` rebuilds the whole
    column on every access, which made a 120-model, 10,427-atom series spend two seconds a model in this loop.
    """
    atoms = universe.atoms
    names, residues, resids = atoms.names, atoms.resnames, atoms.resids
    return [{'name': str(names[index]), 'residue': str(residues[index]),
             'residue_id': int(resids[index]),
             'position': tuple(float(value) / 10.0 for value in positions[index])} for index in written]


def _protein_topologies(work):
    """The protein's moleculetypes the staged run states, or `[]`; an unreadable one is no model, not no picture."""
    try:
        return features.protein_topologies(work) or []
    except (OSError, ValueError):
        return []


def run(work, payload):
    """Sample the chosen trajectory into `run-frames.pdb`, and record the arguments and the timeline in `frames.json`."""
    if mda is None:
        raise RuntimeError('MDAnalysis is not installed; a frame series cannot read a trajectory')
    work = Path(work)
    settings = _settings(payload)
    trajectory, structure = work / settings['trajectory'], work / settings['structure']
    for path, label in ((trajectory, 'trajectory'), (structure, 'structure')):
        if not path.is_file():
            raise ValueError(f'the {label} {settings[label]!r} was not staged for this attempt')
    universe = mda.Universe(str(structure), str(trajectory))
    n_frames = len(universe.trajectory)
    if n_frames < 1:
        raise ValueError(f'{trajectory.name} holds no frames')
    # The trajectory's own first moment and step, so a window is arithmetic on frame numbers rather than a list of
    # 50,000 times. One frame is read for this; the sampled frames are then collected in a single sequential pass,
    # because random access to an `.xtc` seeks the file from its start (measured here: 1.7 s a frame on a 2.5 GB one).
    dt_ps = float(getattr(universe.trajectory, 'dt', 0.0) or 0.0)
    universe.trajectory[0]
    first_ns = float(universe.trajectory.time) / 1000.0  # ps -> ns
    indices, stride = _sample_indices(n_frames, first_ns, dt_ps, settings)
    written = _written_atoms(universe, settings['atoms'])
    models, atoms = len(indices), int(len(written))
    if models > MAX_MODELS:
        raise ValueError(f'{models} models requested, but a frame series holds at most {MAX_MODELS}')
    estimate = models * atoms * BYTES_PER_ATOM
    if estimate > MAX_BYTES:
        raise ValueError(f'{models} models of {atoms} atoms is about {estimate} bytes, and a frame series may weigh '
                         f'at most {MAX_BYTES}')
    subunits = structures.read_subunits(work)
    manifest = _manifest(work)
    protein_topologies = [] if settings['atoms'] == 'ca' else _protein_topologies(work)
    topology = None
    if settings['atoms'] != 'ca':
        # `atoms: 'ca'` states no bonds: a moleculetype read from a CG build would bond an atomistic frame wrongly.
        topology_path = layout.recorded_topology(work, manifest.get('run_type'), manifest)
        if topology_path is not None:
            try:
                topology = structures.read_moleculetype(topology_path)
            except (OSError, ValueError):
                topology = None
    protein = _protein_atoms(universe, protein_topologies)
    selection, target = _fit_selection(universe, settings, written, subunits, protein)
    groups = _molecules(universe)
    frames, times, rmsds, reference = [], [], [], None
    wanted = iter(indices)
    wanted_index = next(wanted, None)
    for index, timestep in enumerate(universe.trajectory):
        if wanted_index is None:
            break
        if index != wanted_index:
            continue
        positions = np.asarray(universe.atoms.positions, dtype=float)
        if settings['assembled']:
            positions = _assemble(positions, _box(universe, structure), groups,
                                  protein if len(protein) else groups[0])
        rmsd = None
        if selection is not None:
            if reference is None:
                reference = positions.copy()
            positions, rmsd = _fit_positions(positions, reference, selection)
        frames.append(_frame_atoms(universe, positions, written))
        times.append(round(float(timestep.time) / 1000.0, 6))
        if rmsd is not None:
            rmsds.append(rmsd)
        wanted_index = next(wanted, None)
    fit = _fit_record(rmsds, len(selection), target=target, of=atoms) if rmsds else None
    cadence_ns = round(dt_ps * stride / 1000.0, 6) if dt_ps > 0 and models > 1 else None
    note = f'every {stride}th frame of {trajectory.name}'
    text = structures.series_pdb(frames, topology=topology, detergent_residue=None, subunits=subunits,
                                 include_water=False, times_ns=times, protein_topologies=protein_topologies or None,
                                 assembled=settings['assembled'], fit=fit,
                                 title=f'{trajectory.name} frame series', note=note)
    output = work / 'run-frames.pdb'
    output.write_text(text)
    size = output.stat().st_size
    trajectory_identity, structure_identity = segments.identity(trajectory), segments.identity(structure)
    files.atomic_json(work / 'frames.json', {
        'args': payload, 'models': models, 'atoms': atoms, 'times_ns': times, 'indices': indices,
        'trajectory': settings['trajectory'], 'structure': settings['structure'],
        'trajectory_identity': trajectory_identity, 'structure_identity': structure_identity,
        'bytes': size, 'cadence_ns': cadence_ns, 'fit': fit, 'assembled': settings['assembled']})
    return {'models': models, 'atoms': atoms, 'times': len(times), 'trajectory': settings['trajectory'],
            'structure': settings['structure'], 'trajectory_identity': trajectory_identity,
            'structure_identity': structure_identity, 'bytes': size, 'cadence_ns': cadence_ns, 'fit': fit,
            'assembled': settings['assembled'], 'files': ['run-frames.pdb', 'frames.json']}
