"""`pdc-structure`: one bounded sample of a run's production leg, read by GROMACS' own analyses.

The definitions are `docs/plans/2026-11-09-pdc-analyses-definitions.md` §3 and the report schema v2 is
`docs/plans/2026-11-24-pdc-complex-data-panel.md` §3.4. The leg is the run's own segmenter's latest playable segment
-- the extension when it ran, else the assessment. It is sampled once, with `gmx trjconv`, and every tool reads that
one file: `gmx gyrate` for the radius of gyration, `gmx rdf` for the radial distributions (receptor COM→head,
receptor COM→tail, head–head, tail–tail), `gmx select` + `gmx mindist -on` for the protein–detergent groups and the
pooled contact, and the producer's periodic KD-tree for the water–head / water–tail bead counts.

The micelle membership is not re-derived. It is the run's own criterion, `pdc_assessment.assess_micelle`, applied
frame by frame: tail beads within the run's `contact_nm`, the largest connected cluster. The gyration tensor is the
one number GROMACS does not give (§1.1): its eigenvalues are a numpy calculation on the same sample, and its derived
shape numbers state their formula in the record.

The four tunable thresholds are the payload contract (`validate_payload`) and are recorded with their effective
values: the RDF bin, the RDF range (cut to half the shortest box edge), the contact cutoff (the run's own micelle
criterion by default) and the water-bead cutoff. Each metric is drawn to its own PNG, so a reader can read a number
without the panel that drew it.

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
from dashboard.analysis.runs import layout, readers, structures, trajectory_header
from dashboard.analysis.runs import segments as engine_segments
from dashboard.analysis.runs.statistics import block_summary
from scipy.spatial import cKDTree

MAX_FRAMES = readers.MAX_FRAMES
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
#: `gmx mindist` writes two optional defaults even when only `-on` is asked for: `-od` (the distance distribution,
#: default `mindist.xvg`) and `-o` (the closest atom pair, default `atm-pair.out`). Every call names both and the
#: producer removes them: an unnamed default leaves `mindist.xvg` plus one `#mindist.xvg.N#` backup per group in the
#: published output, which is clutter a reader cannot use. `-o`'s own parser requires the `.out` suffix.
MINDIST_DISTANCE = 'mindist-distance.out'
MINDIST_DISTRIBUTION = 'mindist-distance-distribution.xvg'
#: The extraction's own output, deleted after clustering so only the file every tool reads is published.
RAW_SAMPLE = 'sample-raw.xtc'
#: The RDF curves' own sample: the final window of the leg, so they describe the late organization rather than the
#: whole trajectory. The other measurements keep the whole-leg sample.
RDF_SAMPLE = 'rdf-sample.xtc'
RDF_WINDOW_NS = 100.0
#: The radial distribution's own interval: 0.05 nm bins, out to 8 nm as the literature-style receptor-centre
#: measurement needs the detergent shell (~2-3 nm). Both are the analysis's choice, not the run's (Q8); `r_max` is
#: cut to half the shortest box edge because a minimum-image distance beyond it is not unique. The payload can
#: override both (`validate_payload`).
BIN_WIDTH_NM = 0.05
R_MAX_NM = 8.0
#: The bead-contact cutoff. The run's own micelle contact distance is the smallest defensible default: it is a
#: number the run recorded and the distance its own criterion already calls a contact (Q8's cutoff is the user's).
CONTACT_NM = pdc_assessment.CONTACT_NM
#: The water-bead contact cutoff: a Martini W bead near a head or tail bead. It is a bead coordination count, not
#: the papers' all-atom hydration number -- one W bead stands for several waters.
WATER_CUTOFF_NM = 0.6
#: The only residue name the water contact groups count. Ions are not water, so `SOLVENT_RESIDUES` is not reused.
WATER_RESIDUE = 'W'
#: The allowed range of each payload threshold (plan §3.3). A blank field means the default.
THRESHOLD_RANGES = {'rdf_bin_nm': (0.01, 0.20), 'rdf_rmax_nm': (0.5, 8.0),
                    'contact_nm': (0.2, 1.5), 'water_cutoff_nm': (0.2, 1.5)}
#: One PNG per plotted metric, published beside the report and named there (`figures`).
FIGURES = ('pdc-structure-rdf.png', 'pdc-structure-contacts-protein.png', 'pdc-structure-contacts-water.png',
           'pdc-structure-shape.png', 'pdc-structure-aggregation.png')
#: One pass over a multi-gigabyte leg is minutes, not the seconds a parsed xvg takes.
EXTRACT_TIMEOUT_S = 1800
TOOL_TIMEOUT_S = 600
#: The solvent residue names the protein selection excludes. The engine's own set, reused rather than restated.
SOLVENT_RESIDUES = structures.WATER_RESIDUES


# ------------------------------------------------------------------------------------------------------------ units

def parse_xvg(path):
    """`(x, {legend: values})` from one XVG, every column labelled by its own `@ sN legend` line.

    The columns are not in the order a request named them, so a reader that counted columns would label every curve
    with the one next to it. This is the shared rule `readers.xvg_columns` keeps for `gmx energy`; `gmx gyrate`
    writes `Rg`, `Rg/sX/N`, ... and `gmx mindist` writes `<reference>-<probe>`.
    """
    labels, times, columns = readers.xvg_columns(path)
    data: dict[str, list[float]] = {}
    # Row-major, so two columns sharing a legend interleave exactly as they did when this walked the rows itself.
    for row in range(len(times)):
        for index, column in enumerate(columns):
            data.setdefault(labels[index], []).append(column[row])
    return list(times), data


def stride_for(frames_in_file, max_frames=MAX_FRAMES):
    """The existing frame bound: one frame in every `stride`, at most `max_frames` frames."""
    return readers.frame_stride(frames_in_file, max_frames)


def rdf_window(first_ns, span_ns, frame_dt_ps, max_frames=MAX_FRAMES):
    """The final RDF window: `min(100 ns, half the leg)`, and the stride that samples at most `max_frames`.

    The user asked for the shorter of the final 100 ns and the final half of the leg. The window is a *time* window;
    `frames_in_window` is its frame count and `stride` is the frame stride that keeps the sample within the bound.
    `None` when the leg states no usable time span, so the caller can fall back to the whole-leg sample.
    """
    try:
        first_ns = float(first_ns)
        span_ns = float(span_ns)
        frame_dt_ps = float(frame_dt_ps)
    except (TypeError, ValueError):
        return None
    if not (span_ns > 0 and frame_dt_ps > 0):
        return None
    window_ns = min(RDF_WINDOW_NS, span_ns / 2.0)
    start_ns = first_ns + span_ns - window_ns
    frames_in_window = max(1, int(round(window_ns * 1000.0 / frame_dt_ps)))
    stride = max(1, math.ceil(frames_in_window / int(max_frames)))
    end_ns = first_ns + span_ns
    return {'window_ns': round(window_ns, 6), 'start_ns': round(start_ns, 6),
            'end_ns': round(end_ns, 6),
            # `trjconv -e` includes a frame exactly at the end; stop half a step short so the window's frame count
            # is the one the stride was computed for (a 100 ns, 25 ps window is 4000 frames, not 4001).
            'extraction_end_ns': round(end_ns - frame_dt_ps / 2000.0, 6),
            'frames_in_window': frames_in_window, 'stride': stride,
            'basis': ('last 100 ns' if RDF_WINDOW_NS <= span_ns / 2.0 else 'last 50% of the leg')}


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


# ------------------------------------------------------------------------------------------------------- thresholds

def validate_payload(payload):
    """The queue-time threshold contract: the four tunable values, or `ValueError` naming the bad one.

    A blank field -- absent, `None` or an empty string -- means the default, so it is dropped rather than stored as a
    second spelling of it. The returned dict is the payload the attempt's identity is built from: floats for the
    values that were given, nothing else. Unknown keys are refused, because a payload that silently lost a misspelt
    threshold would report the default while the reader believed otherwise.
    """
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError('the pdc-structure payload must be an object of threshold values')
    unknown = sorted(set(payload) - set(THRESHOLD_RANGES))
    if unknown:
        raise ValueError(f'unknown pdc-structure threshold(s): {", ".join(unknown)}')
    cleaned = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f'{key} must be a number') from None
        if not math.isfinite(number):
            raise ValueError(f'{key} must be a finite number')
        low, high = THRESHOLD_RANGES[key]
        if not low <= number <= high:
            raise ValueError(f'{key} must be between {low:g} and {high:g}')
        cleaned[key] = number
    return cleaned


def resolve_thresholds(payload, contact_nm):
    """The thresholds one attempt uses: the validated payload over the run's own contact and the defaults."""
    given = validate_payload(payload)
    return {'rdf_bin_nm': given.get('rdf_bin_nm', BIN_WIDTH_NM),
            'rdf_rmax_nm': given.get('rdf_rmax_nm', R_MAX_NM),
            'contact_nm': given.get('contact_nm', float(contact_nm)),
            'water_cutoff_nm': given.get('water_cutoff_nm', WATER_CUTOFF_NM)}


def effective_rmax(requested_nm, box_nm):
    """The requested `r_max`, cut to half the shortest box edge; beyond it a minimum-image distance is not unique."""
    box_nm = [float(value) for value in (box_nm or [])]
    half = min(box_nm) / 2.0 if len(box_nm) == 3 and min(box_nm) > 0 else None
    return round(min(float(requested_nm), half) if half else float(requested_nm), 4)


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


def strongest_peak(r_nm, g):
    """The global maximum of `g`, as `(r_nm, g)`: the shell maximum the receptor-centre rows report.

    A receptor-centre RDF can have a small depletion bump below bulk at short range; calling that the "first peak"
    would report the wrong thing. The strongest point is the detergent shell, and the record states that kind.
    """
    values = [float(value) for value in g]
    if not values:
        return None, None
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
    return readers.run_manifest(work)


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


def _leg(work):
    """The one staged trajectory this attempt reads, with the structure beside it.

    The shared reader selects both; this translates its refusals into this analysis's own vocabulary -- the leg's
    absent trajectory is `NoTrajectory` (the worker records a producer with nothing to do as `skipped`), and the
    structure it names is the beads this report reads.
    """
    try:
        return readers.chosen_trajectory(work, exclude=(SAMPLE,))
    except readers.MissingTrajectory:
        raise layout.NoTrajectory('this run offers no trajectory to sample') from None
    except readers.MissingStructure as error:
        raise ValueError(f'the run stages no structure beside {error.trajectory.name}, so its beads cannot be '
                         'read') from None


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


def _water_selection():
    """The water group: `resname W` only. `SOLVENT_RESIDUES` also names ions, and an ion is not a water bead."""
    return f'resname {WATER_RESIDUE}'


#: A hair past the stated cutoff, so the KD-tree's candidate search never drops a pair that numpy would call a
#: contact. The tree's C distance and numpy's can disagree in the last bits at exactly the cutoff; the distance
#: filter below makes the decision, as `pdc_assessment` does for the micelle graph.
_CONTACT_SLACK = 1.0 + 1e-12


def periodic_contact_counts(first, second, box, cutoff_nm):
    """Pairs within `cutoff_nm` between two point sets, minimum image, for an orthorhombic box.

    `gmx mindist -on` is the reference definition -- one contact per bead pair -- but on a 20k-bead water group it
    spent 34 s and 18 s in the two water groups of a 199-frame sample. The same counts from a periodic KD-tree took
    about 2 s, and all four groups plus the pooled count matched `gmx mindist -on` on every frame of that sample.
    A triclinic box has no rectangular `boxsize`, so the caller keeps GROMACS for it.
    """
    first = np.asarray(first, dtype=float)
    second = np.asarray(second, dtype=float)
    box = np.asarray(box, dtype=float)
    if len(first) == 0 or len(second) == 0:
        return 0
    first = np.mod(first, box)
    second = np.mod(second, box)
    found = cKDTree(second, boxsize=box).query_ball_point(first, r=cutoff_nm * _CONTACT_SLACK)
    counts = np.fromiter((len(neighbours) for neighbours in found), dtype=int, count=len(found))
    if counts.sum() == 0:
        return 0
    row = np.repeat(np.arange(len(first)), counts)
    column = np.concatenate([np.asarray(neighbours, dtype=int) for neighbours in found])
    # The tree found the pair; numpy decides the cutoff on the minimum image, so a boundary pair is not counted
    # from the two points' raw separation.
    difference = first[row] - second[column]
    difference -= box * np.round(difference / box)
    return int(np.count_nonzero(np.einsum('ij,ij->i', difference, difference) <= cutoff_nm ** 2))


#: The four contact groups the report states, in the order the panel reads them. `first`/`second` are the labels the
#: report and the panel use; the cutoff is a thresholds key, never a literal, because the payload can move it.
CONTACT_GROUPS = (
    ('protein', 'head', 'contact_nm',
     'protein bead–head bead pairs within the cutoff, minimum image (one contact per bead pair); '
     'not hydrogen bonds'),
    ('protein', 'tail', 'contact_nm',
     'protein bead–tail bead pairs within the cutoff, minimum image (one contact per bead pair); '
     'not hydrogen bonds'),
    ('water', 'head', 'water_cutoff_nm',
     'W beads within the cutoff of a head bead, minimum image (one contact per bead pair); a bead '
     'coordination count, not an all-atom hydration number, and not hydrogen bonds'),
    ('water', 'tail', 'water_cutoff_nm',
     'W beads within the cutoff of a tail bead, minimum image (one contact per bead pair); a bead '
     'coordination count, not an all-atom hydration number, and not hydrogen bonds'),
)


# --------------------------------------------------------------------------------------------- the MDAnalysis pass

def _measure(work, structure, trajectory, criterion, water_cutoff_nm):
    """Aggregation, the gyration tensor and the water contacts over the extracted sample, with the run's criterion.

    The sample is opened through symlinks in a temporary directory: MDAnalysis writes its `*_offsets.npz` cache
    beside the file it is given, and every file this producer leaves in `work` is published as the attempt's output.
    The water contacts are counted in the same one pass as the aggregation; `gmx mindist` reads the water group from
    the sample again for those two groups, which was the producer's largest cost.
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
        head_atoms, water_atoms = [], []
        water_present = False
        for group in universe.residues:
            name = str(group.resname).strip()
            indices = np.asarray(group.atoms.indices, dtype=int)
            if name == residue:
                molecules.append(indices)
                detergent_atoms.append(indices)
                tail_group = np.asarray([atom.index for atom in group.atoms
                                         if str(atom.name).strip() in tails], dtype=int)
                tail_groups.append(tail_group)
                head_atoms.extend(np.setdiff1d(indices, tail_group, assume_unique=True).tolist())
            elif name.upper() in SOLVENT_RESIDUES:
                if name.upper() == WATER_RESIDUE:
                    water_present = True
                    water_atoms.extend(indices.tolist())
                continue
            else:
                protein_atoms.append(indices)
        if not molecules:
            raise ValueError(f'{trajectory.name} holds no {residue} beads, so the analysis has nothing to read')
        protein = np.concatenate(protein_atoms) if protein_atoms else np.array([], dtype=int)
        if criterion['protein_present'] and len(protein) == 0:
            raise ValueError(f'the run records a protein but {trajectory.name} holds no non-solvent bead for it')
        cloud = np.concatenate(detergent_atoms)
        head_atoms = np.asarray(head_atoms, dtype=int)
        water_atoms = np.asarray(water_atoms, dtype=int)
        tail_atoms = np.concatenate(tail_groups) if tail_groups else np.array([], dtype=int)
        head_beads = int(len(head_atoms))
        largest, counts, free, sizes, eigenvalues = [], [], [], [], []
        box_nm = None
        frames = 0
        orthorhombic = None
        water_contacts = None
        contact_times_ns = []
        for _step in universe.trajectory:
            frames += 1
            positions = universe.atoms.positions / 10.0
            box = np.asarray(universe.dimensions[:3], dtype=float) / 10.0
            if box_nm is None:
                box_nm = box
                # `cKDTree` has a rectangular `boxsize` only; a triclinic box keeps the GROMACS path, which is
                # why the water contacts are optional in this record.
                orthorhombic = bool(np.allclose(np.asarray(universe.dimensions, dtype=float)[3:], 90.0))
                if orthorhombic and len(water_atoms):
                    water_contacts = {}
                    if len(head_atoms):
                        water_contacts[('water', 'head')] = []
                    if len(tail_atoms):
                        water_contacts[('water', 'tail')] = []
                    if not water_contacts:
                        water_contacts = None
            if water_contacts is not None:
                wrapped = np.mod(positions, box)
                if ('water', 'head') in water_contacts:
                    water_contacts[('water', 'head')].append(
                        periodic_contact_counts(wrapped[head_atoms], wrapped[water_atoms], box, water_cutoff_nm))
                if ('water', 'tail') in water_contacts:
                    water_contacts[('water', 'tail')].append(
                        periodic_contact_counts(wrapped[tail_atoms], wrapped[water_atoms], box, water_cutoff_nm))
                contact_times_ns.append(round(float(_step.time) / 1000.0, 4))
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
            'protein_beads': int(len(protein)), 'water_present': water_present,
            'box_nm': [float(value) for value in box_nm] if box_nm is not None else [],
            'largest': largest, 'counts': counts, 'free': free, 'sizes': sizes, 'eigenvalues': eigenvalues,
            'water_contacts': water_contacts, 'contact_times_ns': contact_times_ns}


# ------------------------------------------------------------------------------------------------------- the figures

#: One colour per RDF pair, in report order: protein→head, protein→tail, head–head, tail–tail.
RDF_COLOURS = ('#2455b0', '#c98a1f', '#2f7d5b', '#7a4fa0')
#: One colour per contact group within a figure: the head group then the tail group.
CONTACT_COLOURS = ('#2455b0', '#c98a1f')


def _figure(figsize=(10, 6)):
    """One Agg figure and its canvas. No pyplot: a producer's figure is never shown, only saved."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=figsize, layout='constrained')
    FigureCanvasAgg(figure)
    return figure


def _note(figure, text):
    """A figure's own method footnote: the sample size and the cutoff belong on the picture, not only in the JSON."""
    figure.text(0.01, 0.005, text, fontsize=7.5, color='#5a697d')


def _rdf_label(first, second, reference=None):
    if first == 'protein':
        return f'receptor COM→{second}' if reference == 'com' else f'protein→{second}'
    return f'{first}–{second}'


def draw_rdf_figure(path, rdf, thresholds, frames, window=None):
    """The g(r) curves on one axis, each pair's reported peak marked and named in the legend."""
    figure = _figure((10, 6))
    axis = figure.subplots()
    for entry, colour in zip(rdf, RDF_COLOURS):
        axis.plot(entry['r_nm'], entry['g'], color=colour, linewidth=1.4,
                  label=_rdf_label(entry['first'], entry['second'], entry.get('reference')))
        peak_r, peak_g = entry.get('first_peak_nm'), entry.get('first_peak_g')
        if peak_r is not None and peak_g is not None:
            axis.plot([peak_r], [peak_g], 'o', color=colour, markersize=4)
    axis.set(xlabel='r (nm)', ylabel='g(r)', title='Radial distribution · reported peaks marked')
    axis.legend(frameon=False)
    axis.grid(alpha=.18)
    where = (f' · final {window["window_ns"]:g} ns' if window else '')
    _note(figure, f'{frames} sampled frames{where} · bin {thresholds["rdf_bin_nm"]:g} nm · '
                  f'r_max {thresholds["rdf_rmax_nm"]:g} nm · gmx rdf -norm rdf')
    figure.savefig(path, dpi=150)


def draw_contact_figure(path, groups, first, title, frames):
    """One contact figure: the per-frame counts of the two groups whose first selection is `first`."""
    figure = _figure((10, 6))
    axis = figure.subplots()
    plotted = 0
    for entry, colour in zip([entry for entry in groups if entry['first'] == first], CONTACT_COLOURS):
        series = entry.get('series')
        if not series:
            continue
        label = f'{entry["first"]}–{entry["second"]} · mean {entry["mean"]:.1f} ± {entry["sem"]:.1f}'
        axis.plot(series['time_ns'], series['contacts'], color=colour, linewidth=1.0, label=label)
        plotted += 1
    cutoff = next((entry['cutoff_nm'] for entry in groups if entry['first'] == first), None)
    if plotted:
        axis.set(xlabel='time (ns)', ylabel='contacts (bead pairs)',
                 title=f'{title} · cutoff {cutoff:g} nm')
        axis.legend(frameon=False)
    else:
        axis.text(.5, .5, 'not measured for this run', ha='center', va='center', transform=axis.transAxes)
        axis.set(title=title)
    axis.grid(alpha=.18)
    _note(figure, f'{frames} sampled frames · minimum image, one contact per bead pair · not hydrogen bonds')
    figure.savefig(path, dpi=150)


def draw_shape_figure(path, shape, frames):
    """Rg, asphericity and relative shape anisotropy over the sampled frames."""
    figure = _figure((11, 9))
    axes = figure.subplots(3, 1)
    panels = (('rg', 'series', 'rg_nm', 'Radius of gyration', 'Rg (nm)'),
              ('asphericity_nm2', 'series', 'values', 'Asphericity', 'nm²'),
              ('relative_shape_anisotropy', 'series', 'values', 'Relative shape anisotropy', 'κ²'))
    for axis, (key, series_key, values_key, title, ylabel) in zip(axes, panels):
        block = shape.get(key) or {}
        series = block.get(series_key) or {}
        times, values = series.get('time_ns'), series.get(values_key)
        if times and values:
            axis.plot(times, values, color='#2455b0', linewidth=1.0)
            axis.set(title=f'{title} · mean {block.get("mean", 0.0):g}', xlabel='time (ns)', ylabel=ylabel)
        else:
            axis.text(.5, .5, 'not measured for this run', ha='center', va='center', transform=axis.transAxes)
            axis.set(title=title, ylabel=ylabel)
        axis.grid(alpha=.18)
    _note(figure, f'{frames} sampled frames · Rg from gmx gyrate (mass-weighted); the shape numbers are the '
                  "producer's own unweighted gyration tensor")
    figure.savefig(path, dpi=150)


def draw_aggregation_figure(path, aggregation, frames):
    """Largest cluster and free detergents per sampled frame."""
    figure = _figure((10, 6))
    axis = figure.subplots()
    series = (aggregation or {}).get('series') or {}
    if series.get('time_ns') and series.get('largest'):
        axis.plot(series['time_ns'], series['largest'], color='#2455b0', linewidth=1.0, label='largest cluster')
        axis.plot(series['time_ns'], series['free'], color='#c98a1f', linewidth=1.0, label='free detergents')
        axis.set(xlabel='time (ns)', ylabel='molecules',
                 title='Aggregation · ' + (f'largest mean {aggregation["largest_mean"]:g}, '
                                           f'free mean {aggregation["free_mean"]:g}'))
        axis.legend(frameon=False)
    else:
        axis.text(.5, .5, 'not measured: the run records no tail beads', ha='center', va='center',
                  transform=axis.transAxes)
        axis.set(title='Aggregation')
    axis.grid(alpha=.18)
    _note(figure, f'{frames} sampled frames · the run\'s own micelle criterion (tail beads within the run\'s '
                  'contact distance, largest connected cluster)')
    figure.savefig(path, dpi=150)


def write_figures(work, *, rdf, contact_groups, shape, aggregation, thresholds, frames,
                  rdf_frames=None, rdf_window=None):
    """Write the five per-metric PNGs and return their names, in the report's order."""
    work = Path(work)
    draw_rdf_figure(work / FIGURES[0], rdf, thresholds, rdf_frames if rdf_frames is not None else frames,
                    rdf_window)
    draw_contact_figure(work / FIGURES[1], contact_groups, 'protein', 'Protein–detergent contacts', frames)
    draw_contact_figure(work / FIGURES[2], contact_groups, 'water', 'Water-bead contacts', frames)
    draw_shape_figure(work / FIGURES[3], shape, frames)
    draw_aggregation_figure(work / FIGURES[4], aggregation, frames)
    return list(FIGURES)


# ----------------------------------------------------------------------------------------------------------- the report

def build_report(*, leg, sampling, thresholds, micelle, shape, aggregation, rdf, contacts, figures, commands,
                 caveats, protein_present):
    """The §3.4 v2 record, with its method paragraph and the two flags every report carries.

    Every v1 key is retained. The v2 additions are `thresholds` (the effective values the measurements used), the
    protein→tail RDF entry, `contacts.groups` and `figures`; a v1 reader that ignores them still reads every number it
    read before.
    """
    return {
        'kind': 'pdc-structure',
        'schema_version': 2,
        'leg': leg,
        'sampling': sampling,
        'thresholds': thresholds,
        'micelle': micelle,
        'shape_nm': shape,
        'aggregation': aggregation,
        'rdf': rdf,
        'contacts': contacts,
        'figures': list(figures),
        'commands': commands,
        'method': ('one production leg: gmx trjconv extracted a whole-leg sample for the shape, contacts and '
                   'aggregation numbers, and a second final-window sample for the radial distributions; gmx gyrate '
                   '(Rg) and the bead-contact pair counts read the whole-leg file, gmx rdf reads the final-window '
                   'file. The two '
                   "protein RDF rows use the receptor's centre of mass as one reference point and report the "
                   'strongest shell; head–head and tail–tail report their first contact peak. The protein '
                   'groups are gmx mindist -on; the water groups are the same pair counts from a periodic KD-tree '
                   'over the sample, with gmx mindist as the fallback for a triclinic box. The '
                   "micelle membership is the run's own criterion (pdc_assessment.assess_micelle: tail beads "
                   'within the contact distance, largest connected cluster); the gyration tensor and its shape '
                   "numbers are the producer's own (numpy eigvalsh: b = λ1 - (λ2 + λ3)/2, "
                   'κ² = (3/2)(Σλ²/(Σλ)² - 1/3)); the water groups count Martini W beads, not waters'),
        'caveats': list(caveats),
        'scientifically_validated': False,
        'protein_present': bool(protein_present),
    }


def rdf_pairs(criterion, head_present):
    """The RDF pairs this report states, in report order, as `(first, second, reference, selection, excl)`.

    Protein→head and protein→tail use the receptor's **center of mass** as one reference point, the literature-style
    measurement of detergent organization around the receptor; head–head and tail–tail are the packing curves and
    keep their group reference. A pair whose selection is empty is absent, never measured as zero.
    """
    residue, tails = criterion['detergent_residue'], criterion['tail_beads']
    head = _head_selection(residue, tails)
    tail = _tail_selection(residue, tails)
    receptor = f'com of {_protein_selection(residue)} pbc'
    pairs = []
    if criterion['protein_present']:
        if head_present:
            pairs.append(('protein', 'head', receptor, head, False))
        if tails:
            pairs.append(('protein', 'tail', receptor, tail, False))
    if head_present:
        pairs.append(('head', 'head', head, head, True))
    if tails:
        pairs.append(('tail', 'tail', tail, tail, True))
    return pairs


def _rdf_entries(work, gmx, commands, structure, criterion, thresholds, head_present, sample=SAMPLE):
    """The radial distributions this report states.

    The receptor-centre rows report the **strongest shell** (`strongest_peak`); the detergent–detergent rows report
    their **first contact peak** (`first_peak`), because a receptor-centre curve can have a depletion bump below bulk
    at short range that is not the shell a reader means.
    """
    entries = []
    for first, second, reference, selection, excl in rdf_pairs(criterion, head_present):
        name = f'rdf-{first}-{second}.xvg'
        arguments = ['rdf', '-s', _work_name(work, structure), '-f', sample,
                     '-ref', reference, '-sel', selection,
                     '-bin', f'{thresholds["rdf_bin_nm"]:g}', '-rmax', f'{thresholds["rdf_rmax_nm"]:g}',
                     '-norm', 'rdf', '-o', name, *(['-excl'] if excl else [])]
        progress.report(f'pdc-structure: gmx rdf ({first}–{second})')
        _invoke(gmx, commands, f'gmx rdf ({first}–{second})', arguments, work)
        r_nm, columns = parse_xvg(work / name)
        if not columns:
            raise RuntimeError(f'gmx rdf wrote no dataset for {first}–{second}')
        legend = next(iter(columns))
        g = columns[legend]
        peak_kind = 'strongest_shell' if first == 'protein' else 'first_peak'
        peak_r, peak_g = (strongest_peak(r_nm, g) if peak_kind == 'strongest_shell' else first_peak(r_nm, g))
        entries.append({'tool': 'gmx rdf', 'first': first, 'second': second,
                        'reference': 'com' if first == 'protein' else 'group',
                        'peak_kind': peak_kind,
                        'r_nm': [round(value, 4) for value in r_nm],
                        'g': [round(value, 6) for value in g],
                        'norm': 'rdf', 'excl': excl,
                        'normalization': 'gmx rdf -norm rdf (bulk density per selection)',
                        'bin_width_nm': thresholds['rdf_bin_nm'], 'r_max_nm': thresholds['rdf_rmax_nm'],
                        'first_peak_nm': peak_r, 'first_peak_g': peak_g})
    return entries


def _contact_reading(path, cutoff_nm, first, second, definition):
    """One `gmx mindist -on` XVG as the report's group entry: mean, SEM and the per-frame series."""
    times_ps, columns = parse_xvg(path)
    if not columns:
        raise RuntimeError(f'gmx mindist wrote no contact column for {first}–{second}')
    values = columns[next(iter(columns))]
    summary = block_summary(values)
    return {'first': first, 'second': second, 'cutoff_nm': float(cutoff_nm),
            'mean': round(summary['mean'], 3), 'sem': round(summary['stderr'], 3),
            'series': {'time_ns': [round(value / 1000.0, 4) for value in times_ps],
                       'contacts': [round(value, 3) for value in values]},
            'definition': definition}


def contact_group_plan(criterion, head_present, water_present):
    """The four reported groups, each with the selections it reads and whether this run can measure it.

    A group the run cannot measure stays in the list with null numbers, so the panel's four rows never change shape:
    no protein means no protein–detergent interface, no tail beads means no tail group, and no `W` bead means no
    water group. A zero would claim a measurement this run never made.
    """
    residue, tails = criterion['detergent_residue'], criterion['tail_beads']
    head = _head_selection(residue, tails)
    tail = _tail_selection(residue, tails)
    plan = []
    for first, second, cutoff_key, definition in CONTACT_GROUPS:
        first_selection = _protein_selection(residue) if first == 'protein' else _water_selection()
        second_selection = head if second == 'head' else tail
        available = (water_present if first == 'water' else criterion['protein_present']) \
            and (head_present if second == 'head' else bool(tails))
        plan.append({'first': first, 'second': second, 'cutoff_key': cutoff_key,
                     'first_selection': first_selection, 'second_selection': second_selection,
                     'available': available, 'definition': definition})
    return plan


def _contact_groups(work, gmx, commands, structure, plan, thresholds, *, water_series=None, water_times=None):
    """Protein–head/tail and water–head/tail bead contacts, per frame.

    The protein groups use `gmx mindist -on`: one index file holds their selections and `mindist` is asked for one
    group pair at a time (`-ng 1`), its two group numbers answering its two prompts. The water groups come from the
    producer's own KD-tree pass over the sampled frames when the box is orthorhombic (`_measure`), because the same
    pair counts from GROMACS over a 20k-bead water group were the producer's largest cost. A triclinic box, or a
    sample this pass did not measure, keeps the GROMACS path for every group. The groups a run cannot measure are
    reported with null numbers rather than dropped, so the panel's four rows are stable.
    """
    available = [group for group in plan if group['available']]
    measured = {}
    from_sample, from_gmx = [], []
    for group in available:
        key = (group['first'], group['second'])
        if (group['first'] == 'water' and water_series is not None and key in water_series
                and water_times is not None and len(water_times) == len(water_series[key])):
            from_sample.append(group)
        else:
            from_gmx.append(group)
    for group in from_sample:
        key = (group['first'], group['second'])
        cutoff = thresholds[group['cutoff_key']]
        summary = block_summary(water_series[key])
        measured[key] = {'first': group['first'], 'second': group['second'], 'cutoff_nm': float(cutoff),
                         'tool': 'producer periodic KD-tree (same pair definition as gmx mindist -on)',
                         'mean': round(summary['mean'], 3), 'sem': round(summary['stderr'], 3),
                         'series': {'time_ns': [round(float(value), 4) for value in water_times],
                                    'contacts': [round(float(value), 3) for value in water_series[key]]},
                         'definition': group['definition']}
    if from_gmx:
        selections = []
        for group in from_gmx:
            for key in ('first_selection', 'second_selection'):
                if group[key] not in selections:
                    selections.append(group[key])
        _invoke(gmx, commands, 'gmx select (contact group selections)',
                ['select', '-s', _work_name(work, structure), '-select', *selections,
                 '-on', 'contact-groups.ndx'], work)
        for group in from_gmx:
            cutoff = thresholds[group['cutoff_key']]
            name = f'contacts-{group["first"]}-{group["second"]}.xvg'
            (work / MINDIST_DISTANCE).unlink(missing_ok=True)
            (work / MINDIST_DISTRIBUTION).unlink(missing_ok=True)
            arguments = ['mindist', '-s', _work_name(work, structure), '-f', SAMPLE, '-n', 'contact-groups.ndx',
                         '-ng', '1', '-d', f'{cutoff:g}', '-on', name,
                         '-od', MINDIST_DISTRIBUTION, '-o', MINDIST_DISTANCE]
            progress.report(f'pdc-structure: gmx mindist ({group["first"]}–{group["second"]})')
            _invoke(gmx, commands, f'gmx mindist ({group["first"]}–{group["second"]})', arguments, work,
                    stdin=f'{selections.index(group["first_selection"])}\n'
                          f'{selections.index(group["second_selection"])}\n')
            (work / MINDIST_DISTANCE).unlink(missing_ok=True)
            (work / MINDIST_DISTRIBUTION).unlink(missing_ok=True)
            entry = _contact_reading(work / name, cutoff, group['first'], group['second'], group['definition'])
            entry['tool'] = 'gmx mindist -on'
            measured[(group['first'], group['second'])] = entry
    return [measured.get((group['first'], group['second']))
            or {'first': group['first'], 'second': group['second'],
                'cutoff_nm': thresholds[group['cutoff_key']], 'tool': None,
                'mean': None, 'sem': None, 'series': None, 'definition': group['definition']}
            for group in plan]


def _contacts(work, gmx, commands, structure, residue, cutoff_nm):
    """The pooled protein–detergent contacts the v1 record and the Run view read, per frame.

    The new groups split this interface into head and tail; this object stays because it is the v1 contract and the
    Run view's one contact number, and because it is measured on the same sample with the same cutoff.
    """
    _invoke(gmx, commands, 'gmx select (index groups)',
            ['select', '-s', _work_name(work, structure), '-select', _protein_selection(residue),
             _detergent_selection(residue), '-on', 'contacts.ndx'], work)
    (work / MINDIST_DISTANCE).unlink(missing_ok=True)
    (work / MINDIST_DISTRIBUTION).unlink(missing_ok=True)
    arguments = ['mindist', '-s', _work_name(work, structure), '-f', SAMPLE, '-n', 'contacts.ndx', '-ng', '1',
                 '-d', f'{cutoff_nm:g}', '-on', 'numcont.xvg',
                 '-od', MINDIST_DISTRIBUTION, '-o', MINDIST_DISTANCE]
    progress.report('pdc-structure: gmx mindist (contacts)')
    _invoke(gmx, commands, 'gmx mindist (contacts)', arguments, work, stdin='0\n1\n')
    (work / MINDIST_DISTANCE).unlink(missing_ok=True)
    (work / MINDIST_DISTRIBUTION).unlink(missing_ok=True)
    entry = _contact_reading(work / 'numcont.xvg', cutoff_nm, 'protein', 'detergent',
                             'protein bead–detergent bead pairs within the cutoff, minimum image '
                             '(gmx mindist -on, one contact per bead pair); not hydrogen bonds')
    return {'definition': entry['definition'], 'tool': 'gmx mindist -on',
            'cutoff_nm': entry['cutoff_nm'], 'group': False,
            'mean': entry['mean'], 'sem': entry['sem'], 'series': entry['series']}


# ----------------------------------------------------------------------------------------------------------- the run

def run(work, payload=None):
    """Sample the run's production leg once and write `pdc-structure.json` and its five per-metric PNGs."""
    if mda is None:
        raise RuntimeError('MDAnalysis is required for the aggregation pass of pdc-structure')
    work = Path(work)
    trajectory, structure = _leg(work)
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

    thresholds = resolve_thresholds(payload, criterion['contact_nm'])
    measured = _measure(work, structure, trajectory, criterion, thresholds['water_cutoff_nm'])
    box_nm = measured['box_nm']
    box_half = min(box_nm) / 2.0 if len(box_nm) == 3 and min(box_nm) > 0 else None
    requested_rmax_nm = thresholds['rdf_rmax_nm']
    thresholds['rdf_rmax_nm'] = effective_rmax(requested_rmax_nm, box_nm)

    rdf_info = rdf_window(header.get('first_ns'), header.get('time_ns'), header.get('dt_ps'))
    rdf_sample = SAMPLE
    if rdf_info is not None:
        progress.report(f'pdc-structure: extracting the RDF sample from the final '
                        f'{rdf_info["window_ns"]:g} ns')
        rdf_arguments = ['-b', f'{rdf_info["start_ns"] * 1000:g}', '-e', f'{rdf_info["extraction_end_ns"] * 1000:g}',
                         '-skip', str(rdf_info['stride'])]
        _invoke(gmx, commands, 'extract RDF sample',
                ['trjconv', '-s', _work_name(work, source), '-f', _work_name(work, trajectory),
                 '-o', RDF_SAMPLE, *rdf_arguments], work, stdin='0\n', timeout=EXTRACT_TIMEOUT_S)
        rdf_header = trajectory_header.read(structure, work / RDF_SAMPLE)
        rdf_info['frames_sampled'] = rdf_header.get('frames') if rdf_header else None
        rdf_info['extracted_trajectory'] = RDF_SAMPLE
        rdf_sample = RDF_SAMPLE

    progress.report('pdc-structure: gmx gyrate (Rg)')
    _invoke(gmx, commands, 'gmx gyrate (Rg)',
            ['gyrate', '-s', _work_name(work, source), '-f', SAMPLE, '-o', 'gyrate.xvg',
             '-sel', _detergent_selection(criterion['detergent_residue'])],
            work)
    times_ps, gyrate = parse_xvg(work / 'gyrate.xvg')
    rg = gyrate.get('Rg')
    if not rg:
        raise RuntimeError('gmx gyrate wrote no Rg column')
    times_ns = [round(value / 1000.0, 4) for value in times_ps]
    rg_summary = block_summary(rg)
    axis_components = {label: round(block_summary(values)['mean'], 6)
                       for label, values in gyrate.items() if label != 'Rg'}
    shape = {
        'rg': {'tool': 'gmx gyrate', 'weighting': 'mass',
               'mean': round(rg_summary['mean'], 6), 'sem': round(rg_summary['stderr'], 6),
               'axis_components_nm': axis_components,
               'series': {'time_ns': times_ns,
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
                          'mean': round(summary['mean'], 6), 'sem': round(summary['stderr'], 6),
                          'series': {'time_ns': times_ns,
                                     'values': [round(value, 6) for value in values]}}

    head_present = measured['head_beads'] > 0
    water_present = measured['water_present']
    rdf = _rdf_entries(work, gmx, commands, source, criterion, thresholds, head_present, rdf_sample)
    group_plan = contact_group_plan(criterion, head_present, water_present)
    groups = _contact_groups(work, gmx, commands, source, group_plan, thresholds,
                             water_series=measured.get('water_contacts'),
                             water_times=measured.get('contact_times_ns'))
    pooled = _contacts(work, gmx, commands, source, criterion['detergent_residue'],
                       thresholds['contact_nm']) if criterion['protein_present'] else None
    contacts = {
        'definition': (pooled['definition'] if pooled else
                       'protein bead–detergent bead pairs within the cutoff, minimum image '
                       '(gmx mindist -on, one contact per bead pair); not hydrogen bonds'),
        'tool': 'gmx mindist -on', 'group': False,
        'cutoff_nm': thresholds['contact_nm'],
        'mean': pooled['mean'] if pooled else None,
        'sem': pooled['sem'] if pooled else None,
        'series': pooled['series'] if pooled else None,
        'groups': groups,
    }

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
                                  'counts': [sizes.count(size) for size in bins]},
            'series': {'time_ns': times_ns,
                       'largest': [int(value) for value in largest],
                       'clusters': [int(value) for value in measured['counts']],
                       'free': [int(value) for value in measured['free']]}}
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
                'read': ('one whole-leg gmx trjconv sample extracted and clustered on the detergent '
                         '(sample.xtc) for shape, contacts and aggregation; a second final-window sample '
                         '(rdf-sample.xtc) for the RDF curves; the header was read by trajectory_header.read'),
                'rdf': rdf_info}
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
        (f'The RDF curves use their own sample: {rdf_info["frames_sampled"]} frames from the final '
         f'{rdf_info["window_ns"]:g} ns (the shorter of 100 ns and half the leg; {rdf_info["basis"]}), while the '
         'shape, contact and aggregation numbers use the whole-leg sample.'
         if rdf_info else
         'The RDF curves use the whole-leg sample because the leg states no usable time span for a final-window '
         'sample.'),
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
        "The two protein RDF rows use the receptor's centre of mass as a single reference point (the "
        'literature-style measurement) and report the strongest shell; head–head and tail–tail use a group '
        'reference and report their first contact peak. A receptor-centre curve can have a small depletion bump '
        'below bulk at short range, which the first local maximum would otherwise mistake for the shell.',
        'The gyration-tensor eigenvalues, asphericity and relative shape anisotropy are the producer\'s own, '
        "unweighted calculation; gmx gyrate's axis components are a different quantity reported beside them.",
        'Molecules are brought into one periodic image around the first detergent molecule; an assembly wider than '
        'half a box is not one image.',
        'Not validation: scientifically_validated is false, and this record states what was measured and on how '
        'many frames.',
    ]
    if box_half and thresholds['rdf_rmax_nm'] < requested_rmax_nm:
        caveats.append(f'r_max is {thresholds["rdf_rmax_nm"]:g} nm, the smaller of the requested '
                       f'{requested_rmax_nm:g} nm and half the shortest box edge ({box_half:g} nm); beyond it a '
                       'minimum-image distance is not unique.')
    if not criterion['tail_beads']:
        caveats.append('The run records no tail beads, so its own micelle criterion could not be applied: the '
                       'aggregation numbers are not reported, and the tail RDF and tail contact groups are not '
                       'measured.')
    if not criterion['aggregation_number']:
        caveats.append('The run records no requested aggregation number, so the criterion was run without one.')
    if not head_present:
        caveats.append('The run names every detergent bead a tail, so no head bead set exists and the head–head, '
                       'protein→head, protein–head and water–head measurements are not reported.')
    if not criterion['protein_present']:
        caveats.append('This run has no protein, so the protein–detergent interface is not defined; only the '
                       'detergent-only forms and the water-bead groups are reported.')
    if not water_present:
        caveats.append('The run stages no W bead, so the water–head and water–tail bead contacts are not measured.')
    caveats.append('The water–head and water–tail numbers count Martini W beads within the cutoff of a head or tail '
                   'bead (one contact per bead pair); a W bead stands for several waters, so this is a bead '
                   'coordination count, not an all-atom hydration number.')
    caveats.append('The water groups use the same pair definition as gmx mindist -on, computed by a periodic '
                   'KD-tree over the sample; a pair at the cutoff can be decided differently by GROMACS (it '
                   'undercounts), so a frame may differ by one pair.')
    caveats.append('The measurement cutoff (thresholds.contact_nm) is the bead-contact distance; it is separate '
                   'from the micelle criterion\'s own contact distance (micelle.contact_nm), which is unchanged by '
                   'the payload.')
    if fallback_reason:
        caveats.append('This run\'s extension leg did not run, so the production leg is the CG assessment\'s: its '
                       'system was never rebuilt, and its numbers are not comparable with an extension leg\'s.')

    figures = write_figures(work, rdf=rdf, contact_groups=groups, shape=shape_summary,
                            aggregation=aggregation, thresholds=thresholds, frames=measured['frames'],
                            rdf_frames=(rdf_info or {}).get('frames_sampled') or measured['frames'],
                            rdf_window=rdf_info)
    report = build_report(leg=leg, sampling=sampling, thresholds=thresholds, micelle=micelle,
                          shape=shape_summary, aggregation=aggregation, rdf=rdf, contacts=contacts,
                          figures=figures, commands=commands, caveats=caveats,
                          protein_present=criterion['protein_present'])
    files.atomic_json(work / RECORD, report)
    labels = [path.name for path in work.iterdir() if path.is_file() and path.name != 'manifest.json']
    return {'files': sorted(labels), 'figures': figures, 'thresholds': thresholds, 'leg': leg['name'],
            'frames_sampled': measured['frames'], 'stride': stride, 'molecules': measured['molecules'],
            'rg_nm': shape['rg']['mean'], 'aggregation': aggregation is not None,
            'rdf': [f'{entry["first"]}–{entry["second"]}' for entry in rdf],
            'contacts': contacts['mean'],
            'contact_groups': {f'{entry["first"]}–{entry["second"]}': entry['mean'] for entry in groups}}


def _segment_name(stage_directory):
    """The segment name the run's own segment table gives a stage directory."""
    key = layout.stage_key(stage_directory)
    for name, stage, *_rest in pdc_segments.STAGES:
        if stage == key:
            return name
    return stage_directory
