"""Run artifact indexing and coordinate snapshots for the local dashboard."""
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ... import files
from ...execution import tools
from ...execution.adapters import pdc_view
from . import layout

try:
    import MDAnalysis as mda
except ImportError:  # snapshots remain unavailable with an explicit explanation
    mda = None



def _safe_id(jid):
    if not re.fullmatch(r'[a-f0-9]{12}', jid):
        raise ValueError('Invalid run ID')


def artifacts(run_dir):
    """Return immutable run files, excluding transient lock/cache files."""
    def metadata_for(path):
        for parent in (path.parent, *path.parents):
            if parent == run_dir.parent:
                break
            candidate = parent / 'analysis-metadata.json'
            if not candidate.is_file() or candidate == path:
                continue
            try:
                payload = json.loads(candidate.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(payload, dict):
                return payload
        return None

    entries = []
    if not run_dir.is_dir():
        return entries
    for path in files.safe_files(run_dir):
        if not path.is_file() or path.name.endswith(('.tmp', '.lock')):
            continue
        stat = path.stat()
        entry = {'path': str(path.relative_to(run_dir)), 'bytes': stat.st_size,
                 'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}
        metadata = metadata_for(path)
        if metadata is not None:
            entry['metadata'] = metadata
        entries.append(entry)
    return entries


def _fit_positions(mobile, reference, selection=None):
    """The rotation and translation that superpose `mobile` on `reference`, and the RMSD that remains.

    Kabsch, written out rather than called: the reference here is a coordinate array of the first sampled frame
    rather than a Universe, and the fit is twelve lines that a test can hold against a known rotation. A reflection
    is flipped to a rotation explicitly -- an improper fit would mirror the molecule and call it motion.
    """
    if selection is not None:
        # A fit on a *selection*: the rotation and translation come from those beads alone, and are then applied to
        # every bead -- which is what leaves the rest of the molecule free to move relative to them.
        mobile_centroid = mobile[selection].mean(axis=0)
        reference_centroid = reference[selection].mean(axis=0)
    else:
        mobile_centroid, reference_centroid = mobile.mean(axis=0), reference.mean(axis=0)
    centred, target = mobile - mobile_centroid, reference - reference_centroid
    rows = slice(None) if selection is None else selection
    left, _, right = np.linalg.svd(centred[rows].T @ target[rows])
    rotation = left @ right
    if np.linalg.det(rotation) < 0:
        left[:, -1] *= -1
        rotation = left @ right
    fitted = centred @ rotation + reference_centroid
    # The RMSD is measured on what was fitted: a reader fitting on one ring is asking about that ring, and the
    # motion of the rest is the point of the picture, not an error in it.
    judged = fitted[selection] - reference[selection] if selection is not None else fitted - reference
    return fitted, float(np.sqrt((judged ** 2).sum(axis=1).mean()))


def _frame_atoms(universe, index, *, reference=None, selection=None):
    """One frame's coordinates as the `read_gro`-shaped dicts `pdc_view` writes from, in nanometres.

    The one unit conversion lives here: MDAnalysis holds ångström and every writer in `pdc_view` takes what a
    `.gro` states, which is nanometres, so a bead two units apart in the two readers is caught by the coordinates
    the writers emit rather than silently drawn at the wrong scale.

    `reference` is the first sampled frame's coordinates: given one, this frame is superposed on it before its
    coordinates are read, so the molecule's own translation and rotation come out and its internal motion stays.
    Returns the frame's atoms and, when a reference was given, the RMSD the fit left in ångström.
    """
    universe.trajectory[index]
    positions = np.asarray(universe.atoms.positions, dtype=float)
    rmsd = None
    if reference is not None:
        positions, rmsd = _fit_positions(positions, reference, selection)
    return [{'name': str(getattr(atom, 'name', 'X')), 'residue': str(getattr(atom, 'resname', 'MOL')),
             'residue_id': int(getattr(atom, 'resid', 1)),
             'position': tuple(float(value) / 10.0 for value in position)}
            for atom, position in zip(universe.atoms, positions)], rmsd


def _run_topology(run_dir, role=None):
    """The moleculetype the run simulated, by the run's own layout rule, or `None` when it states none.

    The same resolution the structure route makes, because a series and the run's own structure must read one
    topology: `layout.coarse_topology` answers from the directory the *role* keeps its model in -- `3_initial_CG/`
    for a single-molecule CG build, `1_system/` for a protein-detergent run's detergent -- and the manifest's
    `FINAL_ITP` names the `.itp` a CG stage simulated when the run recorded one. Either directory refuses an
    ambiguous answer rather than ranking one.
    """
    run_dir = Path(run_dir)
    run_type = 'pdc' if str(role or '').startswith('pdc_') else None
    name = None
    try:
        manifest = json.loads((run_dir / 'manifest.json').read_text())
    except (OSError, ValueError):
        manifest = {}
    for stage in manifest.get('stages') or []:
        name = (stage.get('environment') or {}).get('FINAL_ITP')
        if name:
            break
    try:
        return layout.coarse_topology(run_dir, run_type, name)
    except ValueError:
        return None


def _recorded_path(path, root):
    """A path as the record should carry it: relative to the tree the producer was handed, never a staged copy.

    The producer reads a staged directory, so an absolute path into it names a temporary file that is gone by the
    time a reader looks -- while the same path relative to that tree is the run-relative name every other record
    uses (`sources.json`'s keys). A path outside the tree is recorded in full rather than guessed at.
    """
    if path is None:
        return None
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return str(path)


def _pdb_snapshot(universe, index, output, stem, *, topology=None, coarse=False, reference=None, selection=None,
                  subunits=None):
    if coarse:
        # A coarse-grained moment is written through the writer the run's own structure uses: the size-class element
        # stand-in, the Martini 3 family code in the b-factor column, and the moleculetype's own bonds as CONECT.
        # The run view draws a CG file with `colorScheme: 'bfactor'` and its distance guess off, so a moment written
        # as bare coordinates is drawn as grey spheres with no bonds -- measured on this run's own first series.
        atoms, _ = _frame_atoms(universe, index, reference=reference, selection=selection)
        if not atoms:
            raise ValueError('Trajectory contains no atoms')
        moment = float(universe.trajectory.time)
        output.write_text(pdc_view.system_pdb(
            atoms, detergent_residue=atoms[0]['residue'], topology=topology, subunits=subunits,
            title=f'{stem} frame {index} at {moment:.3f} ps'))
        return
    # An all-atom moment keeps the reader's own records: real elements from the atom names, which is the column an
    # all-atom view colours from, and no bonds, because a real molecule's are what the viewer's guess reproduces.
    universe.trajectory[index]
    with output.open('w') as fp:
        fp.write(f"REMARK Dashboard {stem} snapshot frame {index} time {float(universe.trajectory.time):.3f} ps\n")
        for serial, atom in enumerate(universe.atoms, 1):
            name = str(getattr(atom, 'name', 'X'))[:4].rjust(4)
            resname = str(getattr(atom, 'resname', 'MOL'))[:3].rjust(3)
            resid = int(getattr(atom, 'resid', 1))
            x, y, z = atom.position
            element = re.sub(r'[^A-Za-z]', '', name).upper()[:1] or 'X'
            fp.write(f"ATOM  {serial:5d} {name} {resname} A{resid:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element:>2}\n")
        fp.write('END\n')


def _svg_snapshot(universe, index, output, stem):
    universe.trajectory[index]
    atoms = universe.atoms
    if len(atoms) == 0:
        raise ValueError('Trajectory contains no atoms')
    coords = atoms.positions
    width, height, margin = 900, 560, 45
    xmin, xmax = float(coords[:, 0].min()), float(coords[:, 0].max())
    ymin, ymax = float(coords[:, 1].min()), float(coords[:, 1].max())
    scale = min((width-2*margin) / max(xmax-xmin, 1e-6),
                (height-2*margin) / max(ymax-ymin, 1e-6))
    colors = {'C':'#374151', 'O':'#d13b45', 'N':'#285ea8', 'S':'#b47817', 'P':'#b04bb8', 'H':'#9ca3af'}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{stem} trajectory snapshot frame {index}">',
             '<rect width="100%" height="100%" fill="#f8fafc"/>',
             f'<text x="{margin}" y="25" font-family="sans-serif" font-size="16">{stem} snapshot · frame {index} · time {float(universe.trajectory.time):.3f} ps</text>']
    for atom, (x, y, _z) in zip(atoms, coords):
        px = margin + (float(x)-xmin) * scale
        py = height-margin - (float(y)-ymin) * scale
        name = str(getattr(atom, 'name', 'X'))
        element = re.sub(r'[^A-Za-z]', '', name).upper()[:1] or 'X'
        label = f'atom {getattr(atom, "index", 0)+1} {name}'
        parts.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="4" fill="{colors.get(element, "#6b7280")}"><title>{label}</title></circle>')
    parts.append(f'<text x="{margin}" y="{height-14}" font-family="sans-serif" font-size="12" fill="#64748b">XY projection · coordinates are from the original trajectory; this is a review image.</text></svg>')
    output.write_text(''.join(parts))


def _sample_indices(n_frames, samples):
    """`samples` frame numbers spread over the whole trajectory, first and last included."""
    if samples < 1:
        raise ValueError('A frame series needs at least one sample')
    if n_frames <= samples:
        return list(range(n_frames))
    step = (n_frames - 1) / (samples - 1)
    return [round(position * step) for position in range(samples)]


#: The frames a series holds by default: an even spread over the whole trajectory, first and last included. A
#: cadence in nanoseconds is the other way to ask, and it needs a trajectory that states its own time step.
SERIES_SAMPLES = 40
#: The most frames a series may hold however it was asked for. A series is one multi-model PDB the browser loads
#: whole, so the cap is what keeps a long trajectory from publishing a file no viewer should be handed.
SERIES_CAP = 200


def _series_indices(n_frames, dt_ps, samples, interval_ns, cap):
    """The frames the series holds: an even spread, or every `interval_ns` of the trajectory's own time.

    A requested cadence is honoured in *frames* -- `interval_ns * 1000 / dt` -- because a frame is what a reader
    indexes and the trajectory's time step is what turns one into a moment. The first frame is always in the
    series: a series that starts after the trajectory's start hides the state the run began from, which is the
    same rule the reference pair follows. Refused rather than guessed when the trajectory states no time step,
    because then a cadence in nanoseconds names nothing.
    """
    if interval_ns is None:
        return _sample_indices(n_frames, samples)
    if not dt_ps or dt_ps <= 0:
        raise ValueError('this trajectory states no time step, so a cadence in nanoseconds names nothing: '
                         'ask for an even spread instead')
    step = max(1, int(round(float(interval_ns) * 1000.0 / float(dt_ps))))
    return list(range(0, n_frames, step))[:cap]


def _cadence_ns(indices, dt_ps):
    """The nanoseconds between the frames a series actually holds, whatever was asked for.

    Recorded rather than re-derived by the reader: the panel prints this number beside the series it plays, and the
    prompt that asks before replacing one names it, so it has to be the cadence of the file rather than the request.
    """
    if len(indices) < 2 or not dt_ps or dt_ps <= 0:
        return None
    return round((indices[-1] - indices[0]) * float(dt_ps) / 1000.0 / (len(indices) - 1), 6)


def _stride(n_frames, samples):
    """How far apart the sampled frames sat, as a whole number of frames; 1 when every frame was taken."""
    return max(1, round((n_frames - 1) / (samples - 1))) if samples > 1 and n_frames > samples else 1


def _fit_record(rmsds, atoms, *, target=None, of=None):
    """What a fitted series states about its own fit: how many beads were superposed and how far they moved.

    Recorded in nanometres, like every other length in this record, and read off the fit itself rather than
    re-derived by a reader: this is the number that says whether fitting a series was worth it.
    """
    record = {'reference': 1, 'atoms': atoms,
              'rmsd_nm': {'min': round(min(rmsds) / 10.0, 4), 'max': round(max(rmsds) / 10.0, 4),
                          'mean': round(float(np.mean(rmsds)) / 10.0, 4)}}
    if target:
        # Which fragment was held still, and how many beads the molecule has: a reader comparing two fittings has to
        # be able to tell the fit of one ring from the fit of another.
        record['target'] = target
        record['of'] = of
    return record


def _frames_series(universe, indices, output, *, topology=None, coarse=False, note=None, reference=None,
                   selection=None, subunits=None, target=None, title='frame series'):
    """One multi-model PDB holding every sampled frame, so a viewer loads the series in a single request.

    A coarse-grained series goes through `pdc_view.series_pdb`, the writer the run's own structure uses, so every
    model carries the two things the run view reads a bead from: the family code that colours it and the model's own
    bonds. Written straight out of the reader it carries neither, and the panel -- which draws a CG file with
    `bfactor` colours and its distance guess off -- shows grey, unbonded spheres beside the same run's own
    structure. Measured on `a2a457cf9413`'s first series: b-factor `0.00` on every bead, zero CONECT records.

    An all-atom series keeps the reader's own multi-model output: the elements are real chemistry there, and the
    viewer's own guess reproduces its bonds.
    """
    if coarse:
        built = [_frame_atoms(universe, index, reference=reference, selection=selection) for index in indices]
        frames = [atoms for atoms, _ in built]
        if not frames:
            raise ValueError('A frame series needs at least one sample')
        rmsds = [rmsd for _, rmsd in built if rmsd is not None]
        fitted = len(selection) if selection is not None else len(frames[0])
        fit = _fit_record(rmsds, fitted, target=target, of=len(frames[0])) if rmsds else None
        output.write_text(pdc_view.series_pdb(frames, topology=topology, note=note, title=title, fit=fit,
                                              subunits=subunits))
        return fit
    rmsds = []
    with mda.Writer(str(output), n_atoms=len(universe.atoms), multiframe=True) as writer:
        for index in indices:
            universe.trajectory[index]
            if reference is not None:
                positions, rmsd = _fit_positions(np.asarray(universe.atoms.positions, dtype=float), reference,
                                                 selection)
                universe.atoms.positions = positions
                rmsds.append(rmsd)
            writer.write(universe.atoms)
    fitted = len(selection) if selection is not None else len(universe.atoms)
    return _fit_record(rmsds, fitted, target=target, of=len(universe.atoms)) if rmsds else None


def generate(run_dir, labels=('first', 'middle', 'last'), samples=SERIES_SAMPLES, interval_ns=None,
             cap=SERIES_CAP, align=False, align_on=None):
    """Write coordinate and SVG snapshots from the run's own trajectory, resolved by its own layout.

    Which trajectory that is is the run's own answer rather than a stage name: an AA-only run publishes its
    reference under `07_reference/`, a CG consumer keeps its output under `4_CG_sim/`, and a run that holds a
    coarse-grained trajectory is reviewed on that rather than on the atomistic one it was mapped from.
    `layout.frame_source` reads whichever layout the run was written in and refuses a run that spells the same
    role two ways, so the returned `role` and `trajectory` say which file a frame came from instead of leaving a
    reader to guess. `samples` frames are also written to one multi-model PDB, which is what a viewer plays.

    `align` superposes every model on the first sampled frame, which removes the translation and rotation the
    molecule does as a whole and leaves its internal motion. Measured on this workspace's own 200 ns sucrose
    trajectory: 60% of the raw displacement to the first frame is the molecule's own movement, so without the fit
    the motion worth watching is the minority of what a reader sees.

    `align_on` names the fragment to fit *on* -- one ring of a mapped sugar, say -- and the fit is then computed on
    that ring's beads and applied to every bead, so the rest of the molecule is what moves on screen. Fitting on
    everything spreads the motion over the whole model; fitting on one fragment concentrates it in the others, which
    is what a reader asking to watch one ring relative to another is asking for. A fragment the run's own mapping
    does not place is refused rather than quietly fitted on everything.
    """
    if mda is None:
        raise RuntimeError('MDAnalysis is not installed; cannot read trajectory snapshots')
    trajectory, topology, role = layout.frame_source(run_dir)
    universe = mda.Universe(str(topology), str(trajectory))
    n_frames = len(universe.trajectory)
    if n_frames < 1:
        raise ValueError(f'{trajectory.name} contains no frames')
    stem = 'CG' if role.startswith(('cg_', 'pdc_')) else 'AA'
    # Resolved before anything is written: the moments and the series are both written through the run's own
    # conventions, and which conventions those are is decided by the source's role and the moleculetype the run
    # simulated -- a coarse-grained frame gets the family code and the model's own bonds, an all-atom frame keeps
    # real elements and no records it cannot know. A protein-detergent run's film is beads like any CG one, so its
    # role is coarse here as well as in the panel, which draws `pdc` with b-factor colours and no distance guess.
    coarse = role.startswith(('cg_', 'pdc_'))
    topology_path = _run_topology(run_dir, role) if coarse else None
    moleculetype = None
    if topology_path is not None:
        try:
            moleculetype = pdc_view.read_moleculetype(topology_path)
        except (OSError, ValueError):
            moleculetype = None
    # The run's own mapping, when it has one: which beads make up which fragment. It is read here and not in the
    # writer, because the fit needs the same grouping the file states, and two readers of one document drift.
    subunits = pdc_view.read_subunits(run_dir) if coarse else {}
    indices = {'first': 0, 'middle': (n_frames - 1)//2, 'last': n_frames - 1}
    target = run_dir / 'snapshots'; target.mkdir(exist_ok=True)
    created = []
    # Resolved before either writer runs: the moments and the series are the same view of the same frames, so a
    # fitted series has fitted moments -- a strip button that jumped to an unfitted moment would leave the molecule
    # where the series does not have it.
    series_indices = _series_indices(n_frames, float(universe.trajectory.dt or 0), samples, interval_ns, cap)
    cadence = _cadence_ns(series_indices, float(universe.trajectory.dt or 0))
    reference, selection = None, None
    if align_on:
        align = True
    if align:
        # The reference is the first sampled frame: a fit against an arbitrary frame would be a fit against a
        # structure the series does not show.
        universe.trajectory[series_indices[0]]
        reference = np.asarray(universe.atoms.positions, dtype=float).copy()
    if align_on:
        wanted = {name for name, letter in subunits.items() if letter == str(align_on).strip().upper()[:1]}
        names = [str(name).strip().upper() for name in universe.atoms.names]
        selection = np.array([index for index, name in enumerate(names) if name in wanted], dtype=int)
        if not len(selection):
            # Grouped once, from the same document the writer groups from: a message that listed the beads
            # differently from the file's own REMARK would be a second answer to one question.
            groups = {}
            for name, letter in subunits.items():
                groups.setdefault(letter, []).append(name)
            stated = ', '.join(f'{letter} ({", ".join(sorted(members))})'
                               for letter, members in sorted(groups.items())) or 'no fragment'
            raise ValueError(f"The run's own mapping places no bead in fragment '{align_on}', so there is nothing "
                             f'to fit on: it states {stated}')
    # A coarse-grained run gets the series and no moments: first/middle/last pictures of a bead cloud say nothing the
    # playable series does not, and three of them is most of the analysis panel's width for no measurement.
    moments = [] if coarse else list(labels)
    for label in moments:
        if label not in indices:
            raise ValueError(f'Unknown snapshot label: {label}')
        index = indices[label]
        pdb = target / f'{stem}-{label}.pdb'; svg = target / f'{stem}-{label}.svg'
        _pdb_snapshot(universe, index, pdb, stem, topology=moleculetype, coarse=coarse, reference=reference,
                      selection=selection, subunits=subunits)
        _svg_snapshot(universe, index, svg, stem)
        created.extend([pdb.name, svg.name])
    series = target / f'{stem}-frames.pdb'
    fit = _frames_series(universe, series_indices, series, topology=moleculetype, coarse=coarse,
                   reference=reference, selection=selection, subunits=subunits,
                   target=(str(align_on).strip().upper()[:1] if align_on else None),
                   title=f'{trajectory.name} sampled frames',
                   # A trajectory with no time step has no cadence to state: the REMARK says how many models it
                   # holds and stops there rather than printing a number the reader would take for a measurement.
                   note=(f'{cadence} ns per frame' if coarse and cadence else None))
    created.append(series.name)
    universe.trajectory.close()
    try:
        recorded = str(trajectory.relative_to(run_dir))
    except ValueError:  # a resolved path outside the root the caller named is reported in full rather than guessed
        recorded = str(trajectory)
    return {'frames': n_frames, 'files': created, 'trajectory': recorded, 'role': role,
            'series': {'file': series.name, 'sampled': len(series_indices),
                       'topology': _recorded_path(topology_path, run_dir),
                       # The spacing the series actually holds: a requested cadence is what the frames were taken
                       # at, and the even spread's own stride would describe a file this is not.
                       'stride': ((series_indices[1] - series_indices[0]) if (interval_ns is not None
                                                                              and len(series_indices) > 1)
                                  else _stride(n_frames, samples)),
                       'aligned': fit,
                       'interval_ns': cadence,
                       'duration_ns': round(n_frames * float(universe.trajectory.dt or 0) / 1000.0, 6),
                       'frame_ps': float(universe.trajectory.dt or 0),
                       'requested_interval_ns': interval_ns}}



def sasa_plot(run_dir):
    """Plot measured total SASA from GROMACS XVG files, preserving source data."""
    import hashlib
    import math

    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    root = run_dir.resolve()
    sources = []
    for label in ('AA', 'CG'):
        candidates = sorted(run_dir.glob(f'*SASA*/{label}/SASA-{label}.xvg'))
        if len(candidates) > 1:
            raise ValueError(f'Multiple {label} SASA sources found; cannot select one unambiguously')
        if not candidates:
            continue
        path = candidates[0]
        if not path.resolve().is_relative_to(root):
            raise ValueError('SASA source must be inside this run')
        raw = path.read_bytes()
        rows = []
        for number, line in enumerate(raw.decode('utf-8').splitlines(), 1):
            line = line.strip()
            if not line or line.startswith(('#', '@')):
                continue
            try:
                time, area = map(float, line.split()[:2])
            except ValueError as exc:
                raise ValueError(f'{path.name}:{number}: invalid SASA row') from exc
            if not math.isfinite(time) or not math.isfinite(area) or area < 0:
                raise ValueError(f'{path.name}:{number}: invalid SASA measurement')
            if rows and time <= rows[-1][0]:
                raise ValueError(f'{path.name}: SASA times must increase')
            rows.append((time, area))
        if len(rows) < 2:
            raise ValueError(f'{path.name}: at least two measured frames are required')
        sources.append({'label': label, 'path': str(path.relative_to(run_dir)),
                        'sha256': hashlib.sha256(raw).hexdigest(), 'rows': rows})
    if not sources:
        raise FileNotFoundError('No completed SASA-AA.xvg or SASA-CG.xvg analysis is available for this run')
    key = hashlib.sha256(json.dumps([(s['path'], s['sha256']) for s in sources]).encode()).hexdigest()[:16]
    directory = run_dir / 'analysis_plots'
    if directory.is_symlink():
        raise ValueError('Plot directory must not be a symbolic link')
    directory.mkdir(exist_ok=True)
    output = directory / f'sasa-{key}.png'
    record = directory / f'sasa-{key}.json'
    if output.is_symlink() or record.is_symlink():
        raise ValueError('Plot output must not be a symbolic link')
    if not output.is_file() or not record.is_file():
        fig = Figure(figsize=(12, 4.5), layout='constrained')
        FigureCanvasAgg(fig)
        timeline, histogram = fig.subplots(1, 2)
        for source in sources:
            times, areas = zip(*source['rows'])
            color = {'AA': '#2864b5', 'CG': '#169186'}[source['label']]
            timeline.plot(times, areas, label=source['label'], color=color, linewidth=1.3)
            histogram.hist(areas, bins='auto', density=True, alpha=.45, color=color, label=source['label'])
        timeline.set(xlabel='Time (ps)', ylabel='Total SASA (nm²)', title='Measured SASA over time')
        histogram.set(xlabel='Total SASA (nm²)', ylabel='Probability density (nm⁻²)', title='Sampled distributions')
        for axis in (timeline, histogram):
            axis.legend(); axis.grid(alpha=.18)
        fig.suptitle('AA and CG solvent-accessible surface area')
        fig.savefig(output, dpi=160)
        record.write_text(json.dumps({'plot': str(output.relative_to(run_dir)),
            'quantity': 'Total SASA, first XVG data column; time in ps, area in nm^2',
            'sources': [{k:v for k,v in source.items() if k != 'rows'} | {'frames':len(source['rows'])} for source in sources],
            'scientifically_validated': False}, indent=2))
    return {'plot': str(output.relative_to(run_dir)), 'sources': [s['path'] for s in sources]}


def unparameterized_observables(run_dir):
    """Summarize mapped-trajectory observables absent from the fitted ITP."""
    import itertools
    import math

    import numpy as np
    if mda is None:
        raise RuntimeError('MDAnalysis is not installed; cannot analyze observables')
    gro = run_dir / '2_mapping/mapped.gro'; xtc = run_dir / '2_mapping/mapped.xtc'
    itp = run_dir / '3_initial_CG/DDM_initial.itp'
    if not all(path.is_file() for path in (gro, xtc, itp)):
        raise FileNotFoundError('Mapped trajectory and fitted interaction inputs are required')
    from .bonded_terms import read_terms, term_sets
    parsed = term_sets(read_terms(itp.read_text()))
    bonded, angles, dihedrals = parsed['bonds'], parsed['angles'], parsed['dihedrals']
    universe = mda.Universe(str(gro), str(xtc))
    n = len(universe.atoms)
    if any(i >= n for row in bonded | angles | dihedrals for i in row): raise ValueError('Topology references an unknown bead')
    neighbors = {i:set() for i in range(n)}
    for i,j in bonded: neighbors[i].add(j); neighbors[j].add(i)
    pairs = [(i,j) for i,j in itertools.combinations(range(n),2) if (i,j) not in bonded]
    triples = [(i,j,k) for j in range(n) for i,k in itertools.combinations(sorted(neighbors[j]),2) if (i,j,k) not in angles and (k,j,i) not in angles]
    paths = set()
    for j,k in bonded:
        for i in neighbors[j]-{k}:
            for l in neighbors[k]-{j,i}:
                path = (i,j,k,l); canonical = min(path,path[::-1])
                if path not in dihedrals and path[::-1] not in dihedrals: paths.add(canonical)
    quads = sorted(paths)
    def summary(kind, definitions, calculate):
        if not definitions: return {'count': 0, 'items': []}
        values = [[] for _ in definitions]
        for ts in universe.trajectory:
            for index, definition in enumerate(definitions): values[index].append(float(calculate(ts.positions, definition)))
        items = []
        for definition, numbers in zip(definitions, values):
            arr = np.asarray(numbers)
            items.append({'beads': [f'B{x+1:02d}' for x in definition], 'mean': float(arr.mean()), 'std': float(arr.std()), 'p05': float(np.percentile(arr,5)), 'p95': float(np.percentile(arr,95)), 'frames': len(arr)})
        return {'count': len(items), 'items': items}
    def distance(pos, d): return np.linalg.norm(pos[d[0]] - pos[d[1]]) / 10
    def angle(pos, d):
        a,b,c = (pos[d[0]],pos[d[1]],pos[d[2]]); u=a-b; v=c-b
        return math.degrees(math.acos(max(-1,min(1,float(np.dot(u,v)/(np.linalg.norm(u)*np.linalg.norm(v)))))))
    def dihedral(pos, d):
        p0,p1,p2,p3=(pos[x] for x in d); b0=-(p1-p0); b1=p2-p1; b2=p3-p2; b1/=np.linalg.norm(b1); v=b0-np.dot(b0,b1)*b1; w=b2-np.dot(b2,b1)*b1
        return math.degrees(math.atan2(np.dot(np.cross(b1,v),w),np.dot(v,w)))
    result = {'source': {'trajectory': str(xtc.relative_to(run_dir)), 'topology': str(itp.relative_to(run_dir)), 'frames': len(universe.trajectory), 'trajectory_sha256': files.sha256(xtc)}, 'definitions_excluded': {'bonds': len(bonded), 'angles': len(angles), 'dihedrals': len(dihedrals)}, 'distance_nm': summary('distance', pairs, distance), 'angle_deg': summary('angle', triples, angle), 'dihedral_deg': summary('dihedral', quads, dihedral), 'scientifically_validated': False, 'interpretation': 'Exploratory observables absent from the fitted topology; broad or multimodal distributions are review signals, not automatic topology edits.'}
    target = run_dir / 'analysis'; target.mkdir(exist_ok=True); output = target / 'unparameterized_observables.json'; output.write_text(json.dumps(result, indent=2)); universe.trajectory.close()
    return {'artifact': str(output.relative_to(run_dir)), 'distance_count': len(pairs), 'angle_count': len(triples), 'dihedral_count': len(quads)}


def numerical_stability(run_dir):
    """Collect reproducible numerical stability signals from logs and trajectories."""
    logs = [p for p in files.safe_files(run_dir) if p.suffix == '.log']
    lincs = []
    for path in logs:
        count = len(re.findall(r'(?im)^.*lincs.*warning.*$', path.read_text(errors='replace')))
        if count:
            lincs.append({'path': str(path.relative_to(run_dir)), 'warnings': count})
    traces = [{'path': str(path.relative_to(run_dir)), 'bytes': path.stat().st_size,
               'sha256': files.sha256(path)}
              for path in files.safe_files(run_dir) if path.suffix == '.xtc']
    report = {'lincs_warnings': lincs, 'trajectory_count': len(traces), 'trajectories': traces,
              'checks': {'gmx_check': 'not_run'}, 'scientifically_validated': False,
              'interpretation': 'Diagnostic checks only; passing signals do not establish physical stability.'}
    gmx = tools.tool_path('gmx')
    checks = []
    if gmx:
        for trace in traces:
            command = [gmx, 'check', '-f', str(run_dir/trace['path'])]
            print('Command:', command, flush=True)
            proc = subprocess.run(command, cwd=run_dir, capture_output=True, text=True, timeout=60)
            checks.append({'trajectory': trace['path'], 'command': command, 'exit_code': proc.returncode, 'output_tail': (proc.stdout+proc.stderr)[-1200:]})
    if checks:
        report['checks']['gmx_check'] = {'exit_code': max(abs(c['exit_code']) for c in checks), 'trajectories': checks}
    target = run_dir / 'analysis'; target.mkdir(exist_ok=True)
    (target / 'numerical_stability.json').write_text(json.dumps(report, indent=2))
    return report
