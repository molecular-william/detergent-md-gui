"""A run's own trajectory sampled into one multi-model PDB a viewer can play, on request.

Run view plays a trajectory by loading a file, and the vendored NGL has no XTC or TRR parser, so the frames have to be
written server-side. This is that writer as an on-demand analysis rather than a cadence: a person asks for a segment, a
time window, one model every N nanoseconds and a view -- PBC, centre, fit and the group they act on -- and the attempt
records exactly what it was asked for beside the frames.

Nothing here reads a trajectory on page load. The panel names the files it wants through the payload -- the same
run-relative paths `GET /api/jobs/<id>/trajectory` reports -- and the queue resolves and hashes them through `sources`,
so the chosen trajectory is part of the analysis signature and a changed file is a new attempt rather than a stale
series. `sources` is the strict half (it runs before an attempt exists, so a bad request is a 400 and no task);
`run` is the producer (it reads the staged copies the worker made).

The view is a view, never a rewrite: `pbc`, `center`, `fit` and `group` move the coordinates for display with
MDAnalysis's in-process transforms -- `pbc` and `center` are the operations `gmx trjconv` performs (a differential
test pins them), and `fit` superposes every sampled frame on the first one. `structures.series_pdb` writes a REMARK
naming what was done. An old attempt's `assembled`, `fit: protein|beads` and `fragment` arguments are read as the view
they described and are recorded as such rather than relabelled.
"""
import json
import math
from pathlib import Path

import numpy as np

from ... import features, files
from . import layout, segments, structures

try:
    import MDAnalysis as mda
    from MDAnalysis import transformations as mda_transforms
except ImportError:  # a frame series needs a trajectory reader; `run` refuses in its own words
    mda = mda_transforms = None

#: The most models one series may hold. A viewer loads the whole file, so this is the cap that keeps a long
#: trajectory from publishing a file no browser should be handed.
MAX_MODELS = 240
#: The most a series may be estimated to weigh, in bytes: one HETATM line per atom per model, plus the model's
#: records. Refused before any frame is read.
MAX_BYTES = 250_000_000
#: What a null `interval_ns` aims at: about one model every `frames / AUTO_MODELS` frames.
AUTO_MODELS = 120
#: The bytes one atom contributes to the estimate: a HETATM record plus its share of a CONECT record.
BYTES_PER_ATOM = 120

#: The PBC treatments this producer performs in process. `res`, `atom` and `cluster` are deliberately absent: the
#: panel does not ask for them, and `cluster` is the one operation MDAnalysis does not provide.
PBC_MODES = ('none', 'mol', 'whole', 'nojump')
#: The fits the view offers; `trans` removes translation only, `rot+trans` the Kabsch rotation too.
FIT_MODES = ('none', 'trans', 'rot+trans')
#: The fits an attempt built before `trans`/`rot+trans` could be written with; both meant a rigid superposition.
LEGACY_FIT_MODES = ('protein', 'beads')
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


def _interval(payload):
    """Nanoseconds per model: a finite number greater than zero, or `None` for the automatic cadence."""
    value = payload.get('interval_ns')
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'interval_ns must be a number of nanoseconds or null, not {value!r}')
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f'interval_ns must be a finite number of nanoseconds greater than zero, not {value!r}')
    return value


def _legacy_stride(payload):
    """The old `stride` argument, kept only so an attempt built before `interval_ns` still reads."""
    stride = payload.get('stride')
    if stride is None or stride == 'auto':
        return None
    if isinstance(stride, bool) or not isinstance(stride, int) or stride < 1:
        raise ValueError(f"stride must be a whole number of frames at least 1, 'auto', or null, not {stride!r}")
    return stride


def _boolean(payload, field, default):
    """One optional switch: strictly a boolean, because `'yes'` in a payload is a caller's mistake, not a truth."""
    value = payload.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f'{field} must be true or false, not {value!r}')
    return value


def _fragment(payload):
    """The old `fragment` letter, when one was sent; still validated so an old attempt cannot drift."""
    value = payload.get('fragment')
    if value is None:
        return None
    letter = value.strip() if isinstance(value, str) else ''
    if len(letter) != 1 or not letter.isalpha():
        raise ValueError(f"fragment must be one letter of the run's mapping, not {value!r}")
    return letter.upper()


def _group_argument(payload):
    """The `group` key when it names a selection; `None` when the caller left it to the legacy keys or the default."""
    value = payload.get('group')
    if value is None:
        return None
    if value in ('protein', 'solute'):
        return value
    if isinstance(value, str) and value.startswith('fragment:'):
        letter = value[len('fragment:'):]
        if len(letter) == 1 and letter.isalpha():
            return f'fragment:{letter.upper()}'
    raise ValueError(f"group must be 'protein', 'solute' or 'fragment:<letter>', not {value!r}")


def _view(payload):
    """The PBC/centre/fit/group request, with old attempts' keys read as the view they described.

    The new keys win; a key an old attempt never sent is filled from `assembled`, `fit: protein|beads` and `fragment`.
    The tuple returned beside the view names the old keys that supplied it, so `frames.json` and the file can say a
    request was legacy instead of pretending it always had the new shape.
    """
    assembled = _boolean(payload, 'assembled', False)
    legacy = []
    if 'pbc' in payload:
        pbc = payload['pbc']
        if not isinstance(pbc, str) or pbc not in PBC_MODES:
            raise ValueError(f"pbc must be one of {', '.join(PBC_MODES)}, not {pbc!r}")
    else:
        pbc = 'mol' if assembled else 'none'
        if assembled and 'assembled' not in legacy:
            legacy.append('assembled')
    if 'center' in payload:
        center = _boolean(payload, 'center', False)
    else:
        center = assembled
        if assembled and 'assembled' not in legacy:
            legacy.append('assembled')
    fit_raw = payload.get('fit', 'none')
    if not isinstance(fit_raw, str) or fit_raw not in FIT_MODES + LEGACY_FIT_MODES:
        raise ValueError(f"fit must be one of {', '.join(FIT_MODES)}, not {fit_raw!r}")
    fragment = _fragment(payload)
    if fit_raw in LEGACY_FIT_MODES:
        fit = 'rot+trans'
        marker = f'fit {fit_raw!r}'
        if fit_raw == 'beads' and fragment:
            marker += f' fragment {fragment}'
        legacy.append(marker)
    else:
        fit = fit_raw
    group = _group_argument(payload)
    if group is None:
        if fit_raw == 'protein':
            group = 'protein'
        elif fit_raw == 'beads':
            if fragment is None:
                raise ValueError("fit 'beads' needs a fragment letter: the run's own mapping states which beads "
                                 'make up which ring')
            group = f'fragment:{fragment}'
        else:
            group = 'solute'
    return {'pbc': pbc, 'center': center, 'fit': fit, 'group': group}, tuple(legacy)


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
    view, legacy = _view(payload)
    atoms = payload.get('atoms', 'beads')
    if not isinstance(atoms, str) or atoms not in ATOM_MODES:
        raise ValueError(f"atoms must be one of {', '.join(ATOM_MODES)}, not {atoms!r}")
    return {'trajectory': _run_relative(payload, 'trajectory'), 'structure': _run_relative(payload, 'structure'),
            'start_ns': start, 'end_ns': end, 'interval_ns': _interval(payload), 'stride': _legacy_stride(payload),
            'atoms': atoms, 'view': view, 'legacy': legacy}


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
    """`(frame indices, effective stride)` for the window, interval and legacy stride, first selected frame always in.

    Frame numbers are computed from the trajectory's own first time and time step rather than from a list of every
    frame's time: reading that list means walking the whole file (40 s for a live 100 ns, 2.5 GB XTC), and the walk
    is what the producer then has to repeat for the frames it samples. A GROMACS `.xtc` writes its frames on a fixed
    step, which is what this arithmetic is; a file whose steps vary is not one this window can name exactly.

    `interval_ns` is converted with the trajectory's own step. A request finer than the step becomes one frame, and
    the effective cadence is then the step rather than the request; the caller records that, never the wish.
    """
    start, end = settings['start_ns'], settings['end_ns']
    selected = list(range(n_frames))
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
    if settings['interval_ns'] is not None:
        if not dt_ps or dt_ps <= 0:
            raise ValueError('this trajectory states no time step, so one model every N nanoseconds cannot be '
                             'selected: ask for the whole file at its own frames instead')
        stride = max(1, round(settings['interval_ns'] * 1000.0 / dt_ps))
    elif settings['stride'] is not None:
        stride = settings['stride']
    else:
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


def _group_selection(universe, view, written, subunits, protein):
    """The atoms the view's `group` names, cut to the atoms this file writes, and the fragment it names.

    `protein` is the run's own protein moleculetypes, `solute` is what the writer keeps -- the same water and ion
    exclusion `structures.series_pdb` applies by residue name -- and `fragment:<letter>` is the run's mapping, the
    selection an old `fit: beads` named. A selection that holds no atom this file writes is refused rather than
    centred or fitted on everything, because that would answer a different question with the same picture.
    """
    target = None
    group = view['group']
    if group == 'protein':
        selection = protein
        missing = "group 'protein' selected no protein atom: this run states no protein to centre or fit on"
    elif group == 'solute':
        names = universe.atoms.resnames
        selection = np.asarray([index for index, name in enumerate(names)
                                if str(name).strip().upper() not in structures.WATER_RESIDUES], dtype=int)
        missing = "group 'solute' selected no atom this series writes: this trajectory holds only solvent"
    else:
        target = group.split(':', 1)[1]
        names = [str(name).strip().upper() for name in universe.atoms.names]
        selection = np.asarray([index for index, name in enumerate(names) if subunits.get(name) == target],
                               dtype=int)
        if not len(selection):
            stated = {}
            for name, fragment in subunits.items():
                stated.setdefault(fragment, []).append(name)
            words = ', '.join(f'{fragment} ({", ".join(sorted(members))})'
                              for fragment, members in sorted(stated.items())) or 'no fragment'
            raise ValueError(f"The run's own mapping places no bead in fragment '{target}', so there is nothing to "
                             f'centre or fit on: it states {words}')
        missing = 'the fragment selection holds no atom this series writes: centre or fit something the file shows'
    selection = selection[np.isin(selection, written)]
    if not len(selection):
        raise ValueError(missing)
    return selection, target


def _fit_record(rmsds, atoms, *, target=None, of=None, group=None, mode=None):
    """What a fitted series states about its own fit: how many atoms were held and how far they moved, in nm."""
    record = {'reference': 1, 'atoms': int(atoms),
              'rmsd_nm': {'min': round(min(rmsds) / 10.0, 4), 'max': round(max(rmsds) / 10.0, 4),
                          'mean': round(float(np.mean(rmsds)) / 10.0, 4)}}
    if target:
        # Which fragment was held still: a reader comparing two fittings has to tell one ring's fit from another's.
        record['target'] = target
    if group:
        record['group'] = group
    if mode:
        record['fit'] = mode
    if of is not None:
        record['of'] = int(of)
    return record


def _molecules(universe):
    """The trajectory's atoms grouped by molecule, in the order the coordinates first show them.

    GROMACS numbers residues across the whole system, so `(residue name, residue number)` is the only molecule
    identity a `.gro` states -- the same grouping `structures.structure_records` writes a file by. A protein's
    residues are separate groups here; that is the definition this display view uses.
    """
    groups = {}
    for index, key in enumerate(zip(universe.atoms.resnames, universe.atoms.resids)):
        groups.setdefault((str(key[0]), int(key[1])), []).append(index)
    return [np.asarray(indices, dtype=int) for indices in groups.values()]


def _declare_molecule_bonds(universe, groups):
    """Declare each molecule as a bonded fragment, because a GROMACS `.gro` carries no bonds.

    MDAnalysis's `unwrap` moves bonded *fragments*; a universe read from a `.gro` and an `.xtc` alone has no bonds, so
    every atom would be its own fragment and `pbc: mol` would do nothing. One bond between consecutive atoms of each
    molecule gives `make_whole` the same chain of nearest-image moves GROMACS makes inside a molecule. A universe whose
    structure states its own bonds (a PDB with CONECT) keeps them.

    ponytail: a molecule is `(resname, resid)` -- the only identity a `.gro` states. Exact for a detergent, a water or
    an ion, which are one residue; a protein chain spans many residues, so a chain crossing the boundary unwraps per
    residue and can differ from `gmx trjconv -pbc mol`. Reading a `.tpr`/topology for the real molecule split is the
    upgrade path; the differential fixture is one residue and does not exercise it.
    """
    if getattr(universe, 'bonds', None) is not None:
        return
    pairs = [(int(group[index]), int(group[index + 1]))
             for group in groups for index in range(len(group) - 1)]
    if pairs:
        universe.add_bonds(pairs)


def _box(universe, structure):
    """The frame's box in ångström (`ts.dimensions` order), or `None` when neither source states one."""
    if universe.dimensions is not None:
        values = np.asarray(universe.dimensions, dtype=float)
        if values.size >= 3 and np.all(np.isfinite(values[:3])) and np.all(values[:3] > 0):
            return values
    try:
        values = np.asarray(structures.read_gro_box(structure), dtype=float) * 10.0  # nm -> Angstrom
    except (OSError, ValueError):
        return None
    if values.size < 3 or not np.all(np.isfinite(values[:3])) or not np.all(values[:3] > 0):
        return None
    return np.array([*values[:3], 90.0, 90.0, 90.0])


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


def _note(trajectory, stride, cadence_ns, legacy):
    """The build sentence: nanoseconds when the trajectory states a time step, frames when it does not."""
    if cadence_ns is not None:
        note = f'one model every {cadence_ns:g} ns of {trajectory.name}'
    else:
        note = f'every {stride}th frame of {trajectory.name}'
    if legacy:
        note += f" (requested as the old {', '.join(legacy)})"
    return note


def run(work, payload):
    """Sample the chosen trajectory into `run-frames.pdb`, and record the arguments and the timeline in `frames.json`."""
    if mda is None:
        raise RuntimeError('MDAnalysis is not installed; a frame series cannot read a trajectory')
    work = Path(work)
    settings = _settings(payload)
    view = settings['view']
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
    centred = view['center'] or view['fit'] != 'none'
    selection, target = _group_selection(universe, view, written, subunits, protein) if centred else (None, None)
    box = _box(universe, structure)
    if box is None and (view['pbc'] != 'none' or view['center']):
        raise ValueError(f"this view needs a box: pbc '{view['pbc']}' and centre both move atoms by it, and neither "
                         'the trajectory nor the structure states one')
    if box is not None and (universe.dimensions is None or not np.all(np.asarray(universe.dimensions[:3]) > 0)):
        universe.dimensions = box
    unwrap = wrap = nojump = centre_transform = fit_transform = None
    if view['pbc'] in ('mol', 'whole'):
        # MDAnalysis's unwrap moves bonded fragments; a `.gro` states none, so the molecule groups are declared.
        _declare_molecule_bonds(universe, _molecules(universe))
        unwrap = mda_transforms.unwrap(universe.atoms)
        if view['pbc'] == 'mol':
            wrap = mda_transforms.wrap(universe.atoms, compound='fragments')
    elif view['pbc'] == 'nojump':
        nojump = mda_transforms.NoJump()
    if view['center']:
        centre_transform = mda_transforms.center_in_box(universe.atoms[selection])
    frames, times, rmsds, reference = [], [], [], None
    wanted = iter(indices)
    wanted_index = next(wanted, None)
    for index, timestep in enumerate(universe.trajectory[indices[0]:indices[-1] + 1], start=indices[0]):
        if wanted_index is None:
            break
        # A frame-local transform is only needed for the frames this file writes; nojump is history-dependent, so it
        # is applied to every frame of the selected window in order or its answer differs from `gmx trjconv`.
        if nojump is not None or index == wanted_index:
            if unwrap is not None:
                unwrap(timestep)
            if wrap is not None:
                wrap(timestep)
            if nojump is not None:
                nojump(timestep)
        if index != wanted_index:
            continue
        if centre_transform is not None:
            centre_transform(timestep)
        rmsd = None
        if view['fit'] != 'none':
            if reference is None:
                reference = universe.atoms.positions.copy()
                fixed = mda.Merge(universe.atoms[selection])
                fixed.atoms.positions = reference[selection]
                fit_transform = (mda_transforms.fit_rot_trans(universe.atoms[selection], fixed.atoms)
                                 if view['fit'] == 'rot+trans'
                                 else mda_transforms.fit_translation(universe.atoms[selection], fixed.atoms))
            fit_transform(timestep)
            judged = universe.atoms.positions[selection] - reference[selection]
            rmsd = float(np.sqrt((judged ** 2).sum(axis=1).mean()))
        positions = np.asarray(universe.atoms.positions, dtype=float)
        frames.append(_frame_atoms(universe, positions, written))
        times.append(round(float(timestep.time) / 1000.0, 6))
        if rmsd is not None:
            rmsds.append(rmsd)
        wanted_index = next(wanted, None)
    fit_record = (_fit_record(rmsds, len(selection), target=target, of=atoms, group=view['group'],
                              mode=view['fit'])
                  if rmsds else None)
    cadence_ns = round(dt_ps * stride / 1000.0, 6) if dt_ps > 0 and models > 1 else None
    note = _note(trajectory, stride, cadence_ns, settings['legacy'])
    text = structures.series_pdb(frames, topology=topology, detergent_residue=None, subunits=subunits,
                                 include_water=False, times_ns=times, protein_topologies=protein_topologies or None,
                                 view=view, fit=fit_record,
                                 title=f'{trajectory.name} frame series', note=note)
    output = work / 'run-frames.pdb'
    output.write_text(text)
    size = output.stat().st_size
    trajectory_identity, structure_identity = segments.identity(trajectory), segments.identity(structure)
    files.atomic_json(work / 'frames.json', {
        'args': payload, 'models': models, 'atoms': atoms, 'times_ns': times, 'indices': indices,
        'trajectory': settings['trajectory'], 'structure': settings['structure'],
        'trajectory_identity': trajectory_identity, 'structure_identity': structure_identity,
        'bytes': size, 'cadence_ns': cadence_ns, 'interval_ns': settings['interval_ns'], 'stride': stride,
        'view': view, 'legacy': list(settings['legacy']), 'fit': fit_record})
    return {'models': models, 'atoms': atoms, 'times': len(times), 'trajectory': settings['trajectory'],
            'structure': settings['structure'], 'trajectory_identity': trajectory_identity,
            'structure_identity': structure_identity, 'bytes': size, 'cadence_ns': cadence_ns,
            'interval_ns': settings['interval_ns'], 'stride': stride, 'view': view,
            'legacy': list(settings['legacy']), 'fit': fit_record,
            'files': ['run-frames.pdb', 'frames.json']}
