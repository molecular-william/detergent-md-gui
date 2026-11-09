"""`pdc-structure`: one bounded sample of a run's production leg, read by GROMACS' own analyses.

The definitions are `docs/plans/2026-11-09-pdc-analyses-definitions.md` §3 and the report schema is §3.4. The leg is
the run's own segmenter's latest playable segment -- the extension when it ran, else the assessment. It is sampled
once, with `gmx trjconv`, and every tool reads that one file: `gmx gyrate` for the radius of gyration, `gmx rdf` for
the radial distributions, `gmx select` + `gmx mindist -on` for bead contacts.

The micelle membership is not re-derived. It is the run's own criterion, `pdc_assessment.assess_micelle`, applied
frame by frame: tail beads within the run's `contact_nm`, the largest connected cluster. The gyration tensor is the
one number GROMACS does not give (§1.1): its eigenvalues are a numpy calculation on the same sample, and its derived
shape numbers state their formula in the record.

Nothing here decides whether a run is scientifically valid. The record carries `scientifically_validated: false`,
its method, its sampling, its cutoffs and its caveats beside every number.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from dashboard import files
from dashboard.analysis import progress
from dashboard.analysis.runs import layout, structures, trajectory_header
from dashboard.analysis.runs import segments as engine_segments
from dashboard.analysis.runs.statistics import block_summary
from dashboard.analysis.runs.trajectory_overview import MAX_FRAMES
from dashboard.execution import tools
from detergent_pdc import segments as pdc_segments
from detergent_pdc.execution.adapters import pdc_assessment

try:  # the aggregation pass needs a reader; `run` refuses in its own words when it is absent
    import MDAnalysis as mda
except ImportError:  # pragma: no cover - exercised by an install without the dependency
    mda = None

RECORD = 'pdc-structure.json'
#: The one extracted sample every tool reads. It is published with the report, so a reader can rerun a tool on the
#: same frames without copying the leg.
SAMPLE = 'sample.xtc'
#: The extraction's own output, deleted after clustering so only the file every tool reads is published.
RAW_SAMPLE = 'sample-raw.xtc'
#: The radial distribution's own interval: 0.05 nm bins (the interval measured in §1.1) and 2 nm. Both are the
#: analysis's choice, not the run's (Q8); `r_max` is cut to half the shortest box edge because a minimum-image
#: distance beyond it is not unique.
BIN_WIDTH_NM = 0.05
R_MAX_NM = 2.0
#: The bead-contact cutoff. The run's own micelle contact distance is the smallest defensible default: it is a
#: number the run recorded and the distance its own criterion already calls a contact (Q8's cutoff is the user's).
CONTACT_NM = pdc_assessment.CONTACT_NM
#: One pass over a multi-gigabyte leg is minutes, not the seconds a parsed xvg takes.
EXTRACT_TIMEOUT_S = 1800
TOOL_TIMEOUT_S = 600
#: The solvent residue names the protein selection excludes. The engine's own set, reused rather than restated.
SOLVENT_RESIDUES = structures.WATER_RESIDUES


# ------------------------------------------------------------------------------------------------------------ units

def parse_xvg(path):
    """`(x, {legend: values})` from one XVG, every column labelled by its own `@ sN legend` line.

    The columns are not in the order a request named them, so a reader that counted columns would label every curve
    with the one next to it. This is the rule `trajectory_overview._xvg_columns` keeps for `gmx energy`; `gmx
    gyrate` writes `Rg`, `Rg/sX/N`, ... and `gmx mindist` writes `<reference>-<probe>`.
    """
    x, columns, labels = [], {}, []
    for line in Path(path).read_text().splitlines():
        text = line.strip()
        if text.startswith('@ s') and 'legend' in text:
            labels.append(text.split('legend', 1)[1].strip().strip('"'))
            continue
        if not text or text.startswith(('#', '@')):
            continue
        try:
            values = [float(value) for value in text.split()]
        except ValueError:
            continue
        if len(values) < 2:
            continue
        x.append(values[0])
        for index, value in enumerate(values[1:]):
            legend = labels[index] if index < len(labels) else f'column{index + 2}'
            columns.setdefault(legend, []).append(value)
    return x, columns


def stride_for(frames_in_file, max_frames=MAX_FRAMES):
    """The existing frame bound: one frame in every `stride`, at most `max_frames` frames."""
    frames_in_file = int(frames_in_file)
    if frames_in_file < 1:
        raise ValueError('a trajectory with no frames has nothing to sample')
    return max(1, math.ceil(frames_in_file / int(max_frames)))


def sample_arguments(frames_in_file, first_ns, dt_ps):
    """`(trjconv arguments, stride)` for the one extraction.

    `-dt` takes a time, not a frame count, so the stride is converted with the file's own step. A file whose first
    frame is not at t = 0, or that states no step, is sampled with `-skip`: the stride is then exact and the bound
    still holds, and the command list shows which of the two was used.
    """
    stride = stride_for(frames_in_file)
    if dt_ps and not first_ns:
        return ['-dt', f'{stride * float(dt_ps):g}'], stride
    return ['-skip', str(stride)], stride


def first_peak(r_nm, g):
    """The first local maximum of `g`, as `(r_nm, g)`; the global maximum when the curve has no interior one."""
    values = [float(value) for value in g]
    if not values:
        return None, None
    for index in range(1, len(values) - 1):
        if values[index] > 0 and values[index] >= values[index - 1] and values[index] >= values[index + 1]:
            return float(r_nm[index]), values[index]
    best = int(np.argmax(values))
    return float(r_nm[best]), values[best]


def gyration_tensor(points):
    """The gyration tensor's eigenvalues in nm², largest first, from points already in one periodic image.

    `S = (1/N) Σ (r_i - <r>)(r_i - <r>)^T` (§3.2), unweighted on purpose: every bead is one point, and `gmx
    gyrate`'s mass-weighted Rg is a different number reported beside it.
    """
    points = np.asarray(points, dtype=float)
    centred = points - points.mean(axis=0)
    return [float(value) for value in np.linalg.eigvalsh(centred.T @ centred / len(points))[::-1]]


def shape_metrics(eigenvalues):
    """Asphericity in nm² and the relative shape anisotropy from the eigenvalues, largest first.

    `b = λ1 - (λ2 + λ3) / 2` and `κ² = (3/2) (Σλ² / (Σλ)² - 1/3)` (Q2's option a). Both are stated as formulas in
    the report's method; a sphere gives 0 and a line gives 1 for `κ²`.
    """
    first, second, third = (float(value) for value in eigenvalues[:3])
    total = first + second + third
    anisotropy = (1.5 * (sum(value ** 2 for value in (first, second, third)) / total ** 2 - 1.0 / 3.0)
                  if total > 0 else 0.0)
    return {'asphericity_nm2': first - (second + third) / 2.0,
            'relative_shape_anisotropy': max(0.0, min(1.0, anisotropy))}


def _minimum_image(delta, box):
    """Fold a displacement into the periodic cell: the shortest vector between two equivalent positions."""
    return delta - np.round(delta / box) * box


def unwrap(molecules, positions, box):
    """Move whole molecules into one periodic image around the first molecule; nm in, nm out.

    `whole.xtc` keeps molecules whole but does not cluster the micelle, so a micelle across a box face would
    otherwise read as two fragments and its shape would span two periodic images (measured on a 9.4 nm box:
    `trajectory_overview.py:180-188`). Only whole molecules are moved; their internal geometry is untouched.
    """
    moved = np.asarray(positions, dtype=float).copy()
    centres = np.array([moved[group].mean(axis=0) for group in molecules])
    if len(centres) < 2:
        return moved
    box = np.asarray(box, dtype=float)
    shifts = -np.round((centres - centres[0]) / box) * box
    for group, shift in zip(molecules, shifts):
        moved[group] += shift
    return moved


# --------------------------------------------------------------------------------------------------------- the files

def _manifest(work):
    try:
        data = json.loads((Path(work) / 'manifest.json').read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_type(run_dir):
    return _manifest(run_dir).get('run_type') or 'pdc'


def _run_input(root, trajectory):
    """The run input beside a trajectory: its own stem, then a production `run.tpr`, then `topol.tpr`."""
    directory = Path(root) / Path(trajectory).parent
    for name in (f'{Path(trajectory).stem}.tpr', 'run.tpr', 'topol.tpr'):
        path = directory / name
        if path.is_file():
            return path
    return None


def _assessment_path(root):
    """The newest micelle assessment the run wrote, or `None`: the final assessment answers first."""
    for stage in ('final_assessment', 'micelle_assessment'):
        path = layout.stage_path(Path(root), stage, 'assessment.json')
        if path is not None:
            return path
    return None


def _trajectory(work):
    """The one staged trajectory this attempt reads."""
    found = [path for path in Path(work).rglob('*.xtc') if path.is_file() and path.name != SAMPLE]
    if not found:
        raise layout.NoTrajectory('this run offers no trajectory to sample')
    return max(found, key=lambda path: (path.stat().st_size, str(path)))


def _structure(work, trajectory):
    """The staged structure beside the trajectory: the leg's own `run.gro` when there is one."""
    found = sorted(path for path in trajectory.parent.glob('*.gro') if path.is_file())
    if not found:
        raise ValueError(f'the run stages no structure beside {trajectory.name}, so its beads cannot be read')
    preferred = [path for path in found if path.name in ('run.gro', 'system.gro')]
    return (preferred or found)[0]


def _staged_assessment(work):
    """The staged assessment record, newest stage first, or `None` when this run wrote none."""
    found = sorted(path for path in Path(work).rglob('assessment.json') if path.is_file())
    for path in reversed(found):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _work_name(work, path):
    return Path(path).relative_to(Path(work)).as_posix()


# ----------------------------------------------------------------------------------------------------------- the leg

def sources(run_dir, payload=None):
    """Stage exactly what this report reads: the chosen leg's trajectory, structure and run input, its assessment.

    The leg is the pdc segmenter's latest playable segment (`segments.py:50-97`), which for a removal run is the
    extension and for a removal-off run is the assessment. `09_final_assessment` can never be chosen: it writes no
    trajectory. The run's manifest is staged by the worker itself.
    """
    run_dir = Path(run_dir)
    answer = engine_segments.segments(run_dir, _run_type(run_dir))
    playable = [entry for entry in answer.get('segments', [])
                if entry.get('trajectory') and not entry.get('duplicate_of')]
    if not playable:
        return {}
    chosen = playable[-1]
    entries = {}
    for field in ('trajectory', 'structure'):
        relative = chosen.get(field)
        path = engine_segments.present(run_dir, relative) if relative else None
        if path is not None:
            entries[str(path.relative_to(run_dir))] = path
    run_input = _run_input(run_dir, chosen['trajectory'])
    if run_input is not None:
        entries[str(run_input.relative_to(run_dir))] = run_input
    assessment = _assessment_path(run_dir)
    if assessment is not None:
        entries[str(assessment.relative_to(run_dir))] = assessment
    return entries


def _criterion(manifest, assessment):
    """The run's own micelle criterion and its system's names, read from its own records.

    `assessment.json` answers first because the run wrote those values when it judged the micelle; the manifest's
    settings answer for a run whose removal path was off and wrote no assessment at all. Neither is re-derived.
    """
    settings = manifest.get('settings') or {}
    record = assessment or {}
    residue = record.get('detergent_residue') or (settings.get('detergent_model') or {}).get('residue')
    if not residue:
        raise ValueError('the run records no detergent residue, so its detergent molecules cannot be told apart')
    tails = record.get('tail_beads') or settings.get('tail_beads') or []
    aggregation = record.get('aggregation_number') or settings.get('aggregation_number')
    contact = record.get('contact_nm') or settings.get('contact_nm') or CONTACT_NM
    return {'detergent_residue': str(residue),
            'tail_beads': [str(name) for name in tails],
            'contact_nm': float(contact),
            'aggregation_number': int(aggregation) if aggregation else None,
            'protein_present': bool(str(manifest.get('protein') or '').strip())}


def _stage_directory(trajectory):
    """The stage directory a run-relative trajectory sits in, as the run spells it."""
    parts = Path(trajectory).parts
    return parts[1] if parts and parts[0] == 'stages' else (parts[0] if parts else None)


# ---------------------------------------------------------------------------------------------------------- GROMACS

def cluster_steps(source, residue):
    """The two GROMACS calls that put the assembly in one periodic image before any tool reads the sample.

    Whole molecules are not enough: a micelle can sit across a box face with every molecule intact, and then
    `gmx gyrate` measures the distance between its two images. Measured on `d17de0a443f3` (80 DDM): Rg 6.48 nm on
    the staged `whole.xtc`, 1.96 nm once clustered — the wrong answer is a factor of three, so this is part of the
    measurement, not a polish. `trjconv` asks twice: which group to cluster (the detergent) and which to write
    (everything). The index is built with `all` first and the detergent second, so the answers are `1` and `0`.
    """
    return ([['select', '-s', source, '-select', 'all', f'resname {residue}', '-on', 'cluster.ndx']],
            ['trjconv', '-s', source, '-f', RAW_SAMPLE, '-n', 'cluster.ndx', '-o', SAMPLE, '-pbc', 'cluster'],
            '1\n0\n')


def error_tail(output):
    """The last few lines a person can act on: MPI's abort banner is not an error message.

    `trjconv -pbc cluster` prints one progress line per clustering iteration, and on failure GROMACS ends with the
    MPI shutdown banner. Reporting the last three lines therefore reported "You may or may not see output from other
    processes" and nothing else (seen once in four live runs of this producer); the real reason is above that.
    """
    lines = [line.strip() for line in str(output or '').splitlines() if line.strip()]
    boilerplate = ('MPI_ABORT', 'Open MPI', 'mpirun', 'You may or may not see output')
    useful = [line for line in lines if not any(phrase in line for phrase in boilerplate)
              and not set(line) <= {'-', '='}]
    return ' / '.join(useful[-4:]) or 'no output'


def _gmx(gmx, arguments, work, *, stdin=None, timeout=TOOL_TIMEOUT_S):
    result = subprocess.run([gmx, *arguments], cwd=work, input=stdin, capture_output=True, text=True,
                            timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'gmx {arguments[0]} failed ({result.returncode}): '
                           f'{error_tail(result.stdout + result.stderr)}')
    return result


def _invoke(gmx, commands, step, arguments, work, *, stdin=None, timeout=TOOL_TIMEOUT_S):
    commands.append({'step': step, 'argv': ['gmx', *arguments]})
    return _gmx(gmx, arguments, work, stdin=stdin, timeout=timeout)


def _detergent_selection(residue):
    return f'resname {residue}'


def _tail_selection(residue, tails):
    return f'resname {residue} and name {" ".join(tails)}'


def _head_selection(residue, tails):
    return f'resname {residue} and not name {" ".join(tails)}' if tails else _detergent_selection(residue)


def _protein_selection(residue):
    return f'not resname {residue} {" ".join(SOLVENT_RESIDUES)}'


# --------------------------------------------------------------------------------------------- the MDAnalysis pass

def _measure(work, structure, trajectory, criterion):
    """Aggregation and the gyration tensor over the extracted sample, with the run's own criterion.

    The sample is opened through symlinks in a temporary directory: MDAnalysis writes its `*_offsets.npz` cache
    beside the file it is given, and every file this producer leaves in `work` is published as the attempt's output.
    """
    residue = criterion['detergent_residue']
    tails = set(criterion['tail_beads'])
    with tempfile.TemporaryDirectory(prefix='pdc-structure-reader-') as directory:
        linked_structure = Path(directory) / f'structure{structure.suffix or ".gro"}'
        linked_sample = Path(directory) / f'sample{trajectory.suffix or ".xtc"}'
        os.symlink((work / structure).resolve(), linked_structure)
        os.symlink((work / SAMPLE).resolve(), linked_sample)
        universe = mda.Universe(str(linked_structure), str(linked_sample))
        molecules, tail_groups, protein_atoms, detergent_atoms = [], [], [], []
        for group in universe.residues:
            name = str(group.resname).strip()
            indices = np.asarray(group.atoms.indices, dtype=int)
            if name == residue:
                molecules.append(indices)
                detergent_atoms.append(indices)
                tail_groups.append(np.asarray([atom.index for atom in group.atoms
                                               if str(atom.name).strip() in tails], dtype=int))
            elif name.upper() in SOLVENT_RESIDUES:
                continue
            else:
                protein_atoms.append(indices)
        if not molecules:
            raise ValueError(f'{trajectory.name} holds no {residue} beads, so the analysis has nothing to read')
        protein = np.concatenate(protein_atoms) if protein_atoms else np.array([], dtype=int)
        if criterion['protein_present'] and len(protein) == 0:
            raise ValueError(f'the run records a protein but {trajectory.name} holds no non-solvent bead for it')
        cloud = np.concatenate(detergent_atoms)
        head_beads = sum(1 for group in universe.residues if str(group.resname).strip() == residue
                         for atom in group.atoms if str(atom.name).strip() not in tails)
        largest, counts, free, sizes, eigenvalues = [], [], [], [], []
        box_nm = None
        frames = 0
        for _step in universe.trajectory:
            frames += 1
            positions = universe.atoms.positions / 10.0
            box = np.asarray(universe.dimensions[:3], dtype=float) / 10.0
            if box_nm is None:
                box_nm = box
            moved = unwrap(molecules, positions, box)
            if tails:
                detergents = [{'name': f'{residue}{index + 1}', 'tail': moved[group].tolist()}
                              for index, group in enumerate(tail_groups)]
                verdict = pdc_assessment.assess_micelle(
                    detergents, None, contact_nm=criterion['contact_nm'],
                    aggregation_number=criterion['aggregation_number'] or 1)
                largest.append(verdict['largest_cluster'])
                counts.append(len(verdict['cluster_sizes']))
                free.append(len(molecules) - verdict['largest_cluster'])
                sizes.extend(verdict['cluster_sizes'])
            eigenvalues.append(gyration_tensor(moved[cloud]))
    return {'frames': frames, 'molecules': len(molecules), 'head_beads': head_beads,
            'protein_beads': int(len(protein)),
            'box_nm': [float(value) for value in box_nm] if box_nm is not None else [],
            'largest': largest, 'counts': counts, 'free': free, 'sizes': sizes, 'eigenvalues': eigenvalues}


# ----------------------------------------------------------------------------------------------------------- the report

def build_report(*, leg, sampling, micelle, shape, aggregation, rdf, contacts, commands, caveats,
                 protein_present):
    """The §3.4 record, with its method paragraph and the two flags every report carries."""
    return {
        'kind': 'pdc-structure',
        'schema_version': 1,
        'leg': leg,
        'sampling': sampling,
        'micelle': micelle,
        'shape_nm': shape,
        'aggregation': aggregation,
        'rdf': rdf,
        'contacts': contacts,
        'commands': commands,
        'method': ('one bounded sample of one production leg: gmx trjconv extracted it once, and gmx gyrate (Rg), '
                   'gmx rdf (radial distributions) and gmx mindist -on (bead contacts) read that one file; the '
                   "micelle membership is the run's own criterion (pdc_assessment.assess_micelle: tail beads "
                   'within the contact distance, largest connected cluster); the gyration tensor and its shape '
                   "numbers are the producer's own (numpy eigvalsh: b = λ1 - (λ2 + λ3)/2, "
                   'κ² = (3/2)(Σλ²/(Σλ)² - 1/3))'),
        'caveats': list(caveats),
        'scientifically_validated': False,
        'protein_present': bool(protein_present),
    }


def _rdf_entries(work, gmx, commands, structure, criterion, r_max_nm, head_present):
    """The radial distributions this report states: protein→head, head–head and tail–tail."""
    residue, tails = criterion['detergent_residue'], criterion['tail_beads']
    head = _head_selection(residue, tails)
    tail = _tail_selection(residue, tails)
    pairs = []
    if criterion['protein_present']:
        pairs.append(('protein', 'head', _protein_selection(residue), head, False))
    if head_present:
        pairs.append(('head', 'head', head, head, True))
    if tails:
        pairs.append(('tail', 'tail', tail, tail, True))
    entries = []
    for first, second, reference, selection, excl in pairs:
        name = f'rdf-{first}-{second}.xvg'
        arguments = ['rdf', '-s', _work_name(work, structure), '-f', SAMPLE,
                     '-ref', reference, '-sel', selection,
                     '-bin', f'{BIN_WIDTH_NM:g}', '-rmax', f'{r_max_nm:g}', '-norm', 'rdf',
                     '-o', name, *(['-excl'] if excl else [])]
        progress.report(f'pdc-structure: gmx rdf ({first}–{second})')
        _invoke(gmx, commands, f'gmx rdf ({first}–{second})', arguments, work)
        r_nm, columns = parse_xvg(work / name)
        if not columns:
            raise RuntimeError(f'gmx rdf wrote no dataset for {first}–{second}')
        legend = next(iter(columns))
        g = columns[legend]
        peak_r, peak_g = first_peak(r_nm, g)
        entries.append({'tool': 'gmx rdf', 'first': first, 'second': second,
                        'r_nm': [round(value, 4) for value in r_nm],
                        'g': [round(value, 6) for value in g],
                        'norm': 'rdf', 'excl': excl,
                        'normalization': 'gmx rdf -norm rdf (bulk density per selection)',
                        'bin_width_nm': BIN_WIDTH_NM, 'r_max_nm': r_max_nm,
                        'first_peak_nm': peak_r, 'first_peak_g': peak_g})
    return entries


def _contacts(work, gmx, commands, structure, criterion):
    """Protein–detergent bead contacts, per frame: `gmx mindist -on` over the two index groups."""
    residue = criterion['detergent_residue']
    protein = _protein_selection(residue)
    detergent = _detergent_selection(residue)
    _invoke(gmx, commands, 'gmx select (index groups)',
            ['select', '-s', _work_name(work, structure), '-select', protein, detergent, '-on', 'contacts.ndx'],
            work)
    arguments = ['mindist', '-s', _work_name(work, structure), '-f', SAMPLE, '-n', 'contacts.ndx', '-ng', '1',
                 '-d', f'{criterion["contact_nm"]:g}', '-on', 'numcont.xvg']
    progress.report('pdc-structure: gmx mindist (contacts)')
    _invoke(gmx, commands, 'gmx mindist (contacts)', arguments, work, stdin='0\n1\n')
    times_ps, columns = parse_xvg(work / 'numcont.xvg')
    if not columns:
        raise RuntimeError('gmx mindist wrote no contact column')
    values = columns[next(iter(columns))]
    summary = block_summary(values)
    return {'definition': ('protein bead–detergent bead pairs within the cutoff, minimum image '
                           '(gmx mindist -on, one contact per bead pair); not hydrogen bonds'),
            'tool': 'gmx mindist -on',
            'cutoff_nm': criterion['contact_nm'], 'group': False,
            'mean': round(summary['mean'], 3), 'sem': round(summary['stderr'], 3),
            'series': {'time_ns': [round(value / 1000.0, 4) for value in times_ps],
                       'contacts': [round(value, 3) for value in values]}}


def run(work, payload=None):
    """Sample the run's production leg once and write `pdc-structure.json`."""
    if mda is None:
        raise RuntimeError('MDAnalysis is required for the aggregation pass of pdc-structure')
    work = Path(work)
    trajectory = _trajectory(work)
    structure = _structure(work, trajectory)
    manifest = _manifest(work)
    criterion = _criterion(manifest, _staged_assessment(work))
    run_input = _run_input(work, trajectory)
    source = run_input or structure
    header = trajectory_header.read(structure, trajectory)
    if not header or not header.get('frames'):
        raise ValueError(f'{trajectory.name} states no readable frame count, so it cannot be sampled')
    arguments, stride = sample_arguments(header['frames'], header['first_ns'], header['dt_ps'])
    gmx = tools.tool_path('gmx')
    if not gmx:
        raise FileNotFoundError('GROMACS is not available')

    commands = []
    progress.report(f'pdc-structure: extracting one sample of at most {MAX_FRAMES} frames')
    _invoke(gmx, commands, 'extract sample',
            ['trjconv', '-s', _work_name(work, source), '-f', _work_name(work, trajectory),
             '-o', RAW_SAMPLE, *arguments],
            work, stdin='0\n', timeout=EXTRACT_TIMEOUT_S)

    select_steps, cluster_arguments, cluster_stdin = cluster_steps(_work_name(work, source),
                                                                   criterion['detergent_residue'])
    for step in select_steps:
        _invoke(gmx, commands, 'gmx select (cluster groups)', step, work)
    progress.report('pdc-structure: clustering the sample on the detergent')
    _invoke(gmx, commands, 'gmx trjconv -pbc cluster', cluster_arguments, work, stdin=cluster_stdin,
            timeout=EXTRACT_TIMEOUT_S)
    (work / RAW_SAMPLE).unlink(missing_ok=True)

    measured = _measure(work, structure, trajectory, criterion)
    box_nm = measured['box_nm']
    box_half = min(box_nm) / 2.0 if len(box_nm) == 3 and min(box_nm) > 0 else None
    r_max_nm = round(min(R_MAX_NM, box_half) if box_half else R_MAX_NM, 4)

    progress.report('pdc-structure: gmx gyrate (Rg)')
    _invoke(gmx, commands, 'gmx gyrate (Rg)',
            ['gyrate', '-s', _work_name(work, source), '-f', SAMPLE, '-o', 'gyrate.xvg',
             '-sel', _detergent_selection(criterion['detergent_residue'])],
            work)
    times_ps, gyrate = parse_xvg(work / 'gyrate.xvg')
    rg = gyrate.get('Rg')
    if not rg:
        raise RuntimeError('gmx gyrate wrote no Rg column')
    rg_summary = block_summary(rg)
    axis_components = {label: round(block_summary(values)['mean'], 6)
                       for label, values in gyrate.items() if label != 'Rg'}
    shape = {
        'rg': {'tool': 'gmx gyrate', 'weighting': 'mass',
               'mean': round(rg_summary['mean'], 6), 'sem': round(rg_summary['stderr'], 6),
               'axis_components_nm': axis_components,
               'series': {'time_ns': [round(value / 1000.0, 4) for value in times_ps],
                          'rg_nm': [round(value, 6) for value in rg]}},
        'gyration_eigenvalues_nm2': {
            'tool': 'producer (numpy eigvalsh)',
            'mean': [round(float(np.mean([row[index] for row in measured['eigenvalues']])), 6)
                     for index in range(3)]},
        'asphericity_nm2': None,
        'relative_shape_anisotropy': None,
        'subject': 'every detergent bead in the sample',
    }
    if measured['eigenvalues']:
        metrics = [shape_metrics(row) for row in measured['eigenvalues']]
        for key in ('asphericity_nm2', 'relative_shape_anisotropy'):
            values = [row[key] for row in metrics]
            summary = block_summary(values)
            shape[key] = {'formula': ('λ1 - (λ2 + λ3)/2' if key == 'asphericity_nm2'
                                      else '(3/2)(Σλ²/(Σλ)² - 1/3)'),
                          'mean': round(summary['mean'], 6), 'sem': round(summary['stderr'], 6)}

    head_present = measured['head_beads'] > 0
    rdf = _rdf_entries(work, gmx, commands, source, criterion, r_max_nm, head_present)
    contacts = _contacts(work, gmx, commands, source, criterion) if criterion['protein_present'] else None

    largest = measured['largest']
    aggregation = None
    if largest:
        sizes = measured['sizes']
        bins = sorted(set(sizes))
        aggregation = {
            'largest_mean': round(float(np.mean(largest)), 3),
            'cluster_count_mean': round(float(np.mean(measured['counts'])), 3),
            'free_mean': round(float(np.mean(measured['free'])), 3),
            'size_distribution': {'bins': bins,
                                  'counts': [sizes.count(size) for size in bins]}}
    shape_summary = {key: value for key, value in shape.items() if value is not None}

    stage_directory = _stage_directory(_work_name(work, trajectory))
    skipped = manifest.get('skipped_stages') or {}
    fallback_reason = skipped.get('CG extension MD') if stage_directory in ('06_assessment', '2_assessment') else None
    leg = {'name': _segment_name(stage_directory),
           'stage_directory': stage_directory,
           'trajectory': _work_name(work, trajectory),
           'structure': _work_name(work, structure),
           'run_input': _work_name(work, run_input) if run_input else None,
           'chosen_by': "the run's own segmenter: the latest playable segment (extension, else assessment)",
           'fallback_reason': fallback_reason}

    first_ns, span_ns = header.get('first_ns'), header.get('time_ns')
    sampling = {'frames_in_file': header['frames'],
                'frames_sampled': measured['frames'],
                'stride': stride,
                'first_ns': first_ns,
                'last_ns': (round(first_ns + span_ns, 6) if first_ns is not None and span_ns is not None else None),
                'span_ns': span_ns,
                'frame_dt_ps': header.get('dt_ps'),
                'read': ('one gmx trjconv sample extracted once and clustered on the detergent '
                         '(sample.xtc), then every tool read that file; the header was read by '
                         'trajectory_header.read')}
    micelle = {'definition': ('largest connected cluster of tail beads, run criterion '
                              '(pdc_assessment.assess_micelle)'),
               'contact_nm': criterion['contact_nm'],
               'aggregation_number_requested': criterion['aggregation_number'],
               'tail_beads': sorted(criterion['tail_beads']),
               'detergent_residue': criterion['detergent_residue']}

    caveats = [
        f'{measured["frames"]} frames of {header["frames"]} (stride {stride}): the {MAX_FRAMES}-frame bound is a '
        'cost bound, not a sampling-science claim, and frames that far apart are neither independent nor a '
        'converged ensemble.',
        "These numbers describe this leg's coordinates only; they are not comparable with another run's, or with a "
        'leg of a different atom count.',
        f'Rg is gmx gyrate\'s mass-weighted radius over every {criterion["detergent_residue"]} bead in the sample; '
        'the aggregation numbers are the run\'s own criterion (tail beads within the run\'s contact distance, the '
        'largest connected cluster).',
        'The sample is made whole and clustered on the detergent (gmx trjconv -pbc cluster) before any tool '
        'reads it, so a micelle across a box face is one object. gmx gyrate is mass-weighted over the detergent '
        'beads; the gyration tensor is the producer\'s own unweighted eigenvalues, so the two Rg numbers are '
        'not one measurement.',
        'Bead contacts, not hydrogen bonds: a Martini bead has no hydrogen, so gmx hbond cannot run on this system.',
        'The gyration-tensor eigenvalues, asphericity and relative shape anisotropy are the producer\'s own, '
        "unweighted calculation; gmx gyrate's axis components are a different quantity reported beside them.",
        'Molecules are brought into one periodic image around the first detergent molecule; an assembly wider than '
        'half a box is not one image.',
        'Not validation: scientifically_validated is false, and this record states what was measured and on how '
        'many frames.',
    ]
    if box_half:
        caveats.append(f'r_max is {r_max_nm:g} nm, the smaller of {R_MAX_NM:g} nm and half the shortest box edge '
                       f'({box_half:g} nm); beyond it a minimum-image distance is not unique.')
    if not criterion['tail_beads']:
        caveats.append('The run records no tail beads, so its own micelle criterion could not be applied: the '
                       'aggregation numbers are not reported.')
    if not criterion['aggregation_number']:
        caveats.append('The run records no requested aggregation number, so the criterion was run without one.')
    if not head_present:
        caveats.append('The run names every detergent bead a tail, so no head bead set exists and the head–head '
                       'and protein→head curves are not reported.')
    if not criterion['protein_present']:
        caveats.append('This run has no protein, so the protein–detergent interface is not defined; only the '
                       'detergent-only forms are reported.')
    if fallback_reason:
        caveats.append('This run\'s extension leg did not run, so the production leg is the CG assessment\'s: its '
                       'system was never rebuilt, and its numbers are not comparable with an extension leg\'s.')

    report = build_report(leg=leg, sampling=sampling, micelle=micelle, shape=shape_summary,
                          aggregation=aggregation, rdf=rdf, contacts=contacts, commands=commands,
                          caveats=caveats, protein_present=criterion['protein_present'])
    files.atomic_json(work / RECORD, report)
    labels = [path.name for path in work.iterdir() if path.is_file() and path.name != 'manifest.json']
    return {'files': sorted(labels), 'leg': leg['name'], 'frames_sampled': measured['frames'],
            'stride': stride, 'molecules': measured['molecules'],
            'rg_nm': shape['rg']['mean'], 'aggregation': aggregation is not None,
            'rdf': [f'{entry["first"]}–{entry["second"]}' for entry in rdf],
            'contacts': contacts['mean'] if contacts else None}


def _segment_name(stage_directory):
    """The segment name the run's own segment table gives a stage directory."""
    key = layout.stage_key(stage_directory)
    for name, stage, *_rest in pdc_segments.STAGES:
        if stage == key:
            return name
    return stage_directory
