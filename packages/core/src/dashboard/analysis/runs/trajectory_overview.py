"""The first look at a completed trajectory: RMSD, radius of gyration, shape, RMSF and energy.

One sequential pass over the run's latest playable segment, sampled to at most `MAX_FRAMES` frames. The questions are
the ones a reader asks before any modelling claim: did the protein (or, in an empty micelle, the largest detergent
aggregate) keep its shape, how large is it, how many detergent molecules stay in one aggregate, and do the
temperature, pressure and potential hold still. The record keeps the full series statistics, the gyration tensor's
shape descriptors, per-atom RMSF, the end-to-end distance on a small subject, and one summary per EDR term.

Every inter-molecular distance is minimum-image. The run's `whole.xtc` makes molecules whole and centres the whole
system, but it does not cluster the micelle; a micelle across a box face would otherwise read as two fragments and
its radius of gyration would span two periodic images. Measured on a 9.4 nm box: the raw reading swung the largest
aggregate between 26 and 92 molecules and Rg between 2.25 and 5.36 nm, while the minimum-image answer was one
92-molecule aggregate with Rg 2.09-2.15 nm at every sampled frame.

Nothing here decides whether a run is scientifically valid. The output is a figure, a JSON record of the series it
drew, and a sentence saying what was measured and on how many sampled frames.
"""
import json
import math
import re
import subprocess
from array import array
from pathlib import Path

import numpy as np

from ... import features, files
from ...execution import tools
from . import frame_series, segments, structures
from .statistics import series_summary

try:
    import MDAnalysis as mda
    from scipy.spatial.distance import cdist
except ImportError:  # a trajectory overview needs a reader and a distance matrix; `run` refuses in its own words
    mda = cdist = None

#: The most frames one overview reads. A 900 ns CG leg writes 45,000 frames; sampling 200 of them keeps the pass
#: short while still showing the shape of the series.
MAX_FRAMES = 200
#: The `gmx energy` terms the figure draws, in the order the XVG columns appear.
ENERGY_TERMS = ('Temperature', 'Pressure', 'Potential')
#: The energy terms whose statistics belong with the thermodynamics, whatever else the EDR holds.
ENERGY_COMPONENTS = ('Angle', 'Proper-Dih.', 'Improper-Dih.', 'Bond', 'LJ-14', 'Coulomb-14',
                     'LJ-(SR)', 'Coulomb-(SR)', 'Coul.-recip.', 'Potential')
#: How many energy points the record keeps, so the JSON stays a summary rather than a second copy of the EDR.
ENERGY_POINTS = 600
#: The moving average drawn over the raw samples: a centred window of about this fraction of the plotted points,
#: floored at two samples and capped so a long energy series keeps its shape instead of flattening to one line.
SMOOTHING_FRACTION = 0.05
#: The largest subject whose O(N²) quantities are measured: the pairwise end-to-end distance per sampled frame and
#: the per-atom RMSF list. Above it the record keeps the aggregate RMSF and says why end-to-end is absent.
PAIR_ATOM_CAP = 512
#: A potential slope below this (kJ/mol per ns) is read as no drift, so the energy-balance ratio is not a division
#: by rounding noise.
SLOPE_EPSILON = 1e-9


def _window(length):
    """The moving-average window for a series of `length` points."""
    return max(2, min(25, round(length * SMOOTHING_FRACTION)))


def _moving_average(values, window):
    """A centred moving average, averaging only the points that exist at each end (never zero-padding them away)."""
    values = np.asarray(list(values), dtype=float)
    if values.size < 2:
        return values.copy()
    half = max(0, (max(1, min(int(window), values.size)) - 1) // 2)
    cumulative = np.concatenate(([0.0], np.cumsum(values)))
    return np.array([(cumulative[min(values.size, index + half + 1)] - cumulative[max(0, index - half)])
                     / (min(values.size, index + half + 1) - max(0, index - half))
                     for index in range(values.size)])


def _manifest(work):
    """The run's manifest, or `{}`: a missing record is a state, not a reason to refuse the overview."""
    try:
        data = json.loads((Path(work) / 'manifest.json').read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_type(work):
    return _manifest(work).get('run_type')


def _segment(run_dir):
    """The latest playable segment of the run, or `None` when it offers no trajectory."""
    answer = segments.segments(Path(run_dir), _run_type(run_dir))
    playable = [entry for entry in answer.get('segments', [])
                if entry.get('trajectory') and not entry.get('duplicate_of')]
    return playable[-1] if playable else None


#: The energy file names a GROMACS leg writes, most specific first. Explicit, never a glob: a stage also holds
#: `eq.edr` and `min.edr`, and either would answer a production trajectory.
ENERGY_NAMES = ('md.edr', 'run.edr')


def _energy_beside(trajectory):
    """The energy file of the leg that wrote `trajectory`, or `None`.

    A stage writes a trajectory and the energy file it belongs to in the same directory. One case separates them:
    the AA-CG pipeline extracts the solute into `prod/lig_CG.xtc` while the leg's `md.edr` stays in the stage
    directory above. So the search is the trajectory's own directory first, then that directory's parent. The names
    are explicit because a glob would happily return `eq.edr` or `min.edr` for a production trajectory.
    """
    trajectory = Path(trajectory)
    for directory in (trajectory.parent, trajectory.parent.parent):
        for name in (f'{trajectory.stem}.edr', *ENERGY_NAMES):
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _reference_leg_energy(trajectory):
    """The production leg's energy file for an AA reference publication, or `None`.

    An AA-only run's reviewable trajectory is `07_reference/lig.xtc`, extracted from `06_production/run.xtc` by
    `gmx trjconv`; the leg's energy stays in the production stage directory rather than beside the extracted solute.
    Only that leg is considered: `05_npt/run.edr` and `04_nvt/run.edr` describe other segments of the run.
    """
    stage_root = Path(trajectory).parent.parent
    candidate = stage_root / '06_production' / 'run.edr'
    return candidate if candidate.is_file() else None


def sources(run_dir, payload=None):
    """Stage the latest segment's trajectory, structure and its energy file; nothing else from the run.

    The producer finds the pair again by scanning the staged tree, so the hook and the producer cannot disagree
    about *which* segment this overview describes without disagreeing about the run itself: the staged tree holds
    exactly the one trajectory the hook chose. The energy file is the leg's own, found by `_energy_beside`: beside
    the trajectory, or in the stage directory above it when the trajectory is an extracted solute. An AA-only run's
    extracted reference has no sibling energy, so its production leg's `.edr` is staged instead.
    """
    run_dir = Path(run_dir)
    chosen = _segment(run_dir)
    if chosen is None:
        return {}
    entries = frame_series.sources(run_dir, {'trajectory': chosen['trajectory'],
                                             'structure': chosen['structure']})
    trajectory = segments.present(run_dir, chosen['trajectory'])
    if trajectory is not None:
        edr = _energy_beside(trajectory)
        if edr is None and _run_type(run_dir) == 'aa_only':
            edr = _reference_leg_energy(trajectory)
        if edr is not None and edr.is_relative_to(run_dir):
            entries[str(edr.relative_to(run_dir))] = edr
    return entries


def _chosen(work):
    """The staged trajectory this overview reads: the largest `.xtc`, with its sibling structure."""
    trajectory = max((path for path in Path(work).rglob('*.xtc') if path.is_file()),
                     key=lambda path: (path.stat().st_size, str(path)))
    directory = trajectory.parent
    structures_found = sorted(path for path in directory.glob('*.gro') if path.is_file())
    if not structures_found:
        raise ValueError(f'the run stages no structure beside {trajectory.name}, so its atoms cannot be read')
    preferred = [path for path in structures_found if path.name in ('run.gro', 'system.gro')]
    return trajectory, (preferred or structures_found)[0]


def _protein(universe, work):
    """The protein's atom indices: the moleculetypes' own count, else MDAnalysis' protein selection."""
    try:
        topologies = features.protein_topologies(work) or []
    except (OSError, ValueError):
        topologies = []
    leading = sum(len(row.get('atoms') or ()) for row in topologies)
    if topologies and 0 < leading <= len(universe.atoms):
        return np.arange(leading, dtype=int), 'protein'
    try:
        selected = universe.select_atoms('protein')
    except (AttributeError, ValueError):
        selected = None
    if selected is not None and len(selected):
        return np.asarray(selected.indices, dtype=int), 'protein'
    return None, None


def _molecules(universe, protein):
    """Every non-water residue outside the protein, one array of atom indices each, in file order."""
    water = structures.WATER_RESIDUES
    protein = set(int(index) for index in (protein if protein is not None else ()))
    groups = []
    for residue in universe.residues:
        name = str(residue.resname).strip().upper()
        if name in water:
            continue
        indices = np.asarray(residue.atoms.indices, dtype=int)
        if len(protein) and all(int(index) in protein for index in indices):
            continue
        groups.append(indices)
    return groups


def _minimum_image(delta, box):
    """Fold a displacement into the periodic cell: the shortest vector between two equivalent positions."""
    return delta - np.round(delta / box) * box


def _aggregates(molecule_sizes, positions, threshold, box):
    """The connected aggregates of molecules, by the minimum-image distance between any two of their beads.

    Two molecules belong to one aggregate when their closest beads are within `threshold` nanometres: the same
    contact distance the run's own placement uses (`contact_nm`), so the number means what the build meant by it.
    The distances are minimum-image: `whole.xtc` keeps molecules whole but does not cluster the micelle, so a micelle
    across a box face has its two halves on opposite faces of the same cell. A raw distance would call those halves
    separate aggregates -- measured on a 9.4 nm box, that turned one 92-molecule micelle into fragments of 26, 25,
    22 and 19. The box is the reader's responsibility; this function states it in its one argument.
    """
    offsets = np.cumsum([0, *molecule_sizes])
    labels = np.repeat(np.arange(len(molecule_sizes)), molecule_sizes)
    delta = positions[:, None, :] - positions[None, :, :]
    delta = _minimum_image(delta, box)
    distances = np.sqrt((delta ** 2).sum(axis=-1))
    distances[labels[:, None] == labels[None, :]] = np.inf
    starts = offsets[:-1]
    nearest = np.minimum.reduceat(np.minimum.reduceat(distances, starts, axis=0), starts, axis=1)

    parent = list(range(len(molecule_sizes)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for first in range(len(molecule_sizes)):
        for second in range(first + 1, len(molecule_sizes)):
            if nearest[first, second] <= threshold:
                root, other = find(first), find(second)
                if root != other:
                    parent[other] = root
    groups = {}
    for index in range(len(molecule_sizes)):
        groups.setdefault(find(index), []).append(index)
    return sorted(groups.values(), key=len, reverse=True)


def _unwrap(positions, groups, box):
    """Move whole molecules into one periodic image around their common centre, by minimum image.

    `positions` is the full coordinate array in ångström and `groups` are the atom indices of the molecules to
    bring together. Only the molecules of the aggregate are moved; their internal geometry is untouched.
    """
    moved = positions.copy()
    centres = np.array([positions[group].mean(axis=0) for group in groups])
    # Anchor on a real molecule, not on the mean of wrapped centres: a cluster split symmetrically about the box
    # face has a mean in the middle, where both halves look local and neither is moved. The shift is a whole number
    # of boxes towards the anchor; a cluster wider than half a box is not one image and would need a graph walk.
    anchor = centres[0]
    shifts = -np.round((centres - anchor) / box) * box
    for group, shift in zip(groups, shifts):
        moved[group] += shift
    return moved


def _radius_of_gyration(positions):
    """Rg in nanometres from ångström coordinates already brought into one periodic image."""
    return float(np.sqrt(((positions - positions.mean(axis=0)) ** 2).sum(axis=1).mean()) / 10.0)


def _gyration_tensor_eigenvalues(positions):
    """The gyration tensor's three eigenvalues in nm², largest first, from unwrapped ångström coordinates.

    The tensor is the mean outer product of the centred coordinates, so its trace is Rg²; sorting makes the shape
    metrics below read λ1 ≥ λ2 ≥ λ3 without re-checking order at every call.
    """
    centred = np.asarray(positions, dtype=float) - np.asarray(positions, dtype=float).mean(axis=0)
    tensor = centred.T @ centred / len(centred)
    return np.sort(np.linalg.eigvalsh(tensor))[::-1] / 100.0


def _shape_metrics(eigenvalues):
    """Asphericity, acylindricity and shape anisotropy in nm² from one frame's three eigenvalues."""
    first, second, third = (float(value) for value in eigenvalues)
    total = first + second + third
    # A point subject (all three eigenvalues zero) has no anisotropy to state; zero is the finite limit, not a guess.
    anisotropy = (1.5 * ((first ** 2 + second ** 2 + third ** 2) / total ** 2 - 1.0 / 3.0)
                  if total > 0.0 else 0.0)
    return first - (second + third) / 2.0, second - third, anisotropy


def _rounded(summary):
    """A `series_summary` with its floats rounded to six decimals; ints and `None` pass through unchanged."""
    return {key: round(value, 6) if isinstance(value, float) else value for key, value in summary.items()}


def _eigenvalue_summary(frames):
    """Mean, standard deviation and half-means of each eigenvalue across the sampled frames, rounded to 6 decimals."""
    frames = np.asarray(frames, dtype=float)
    count = len(frames)
    split = count // 2
    std = frames.std(axis=0, ddof=1) if count > 1 else np.zeros(frames.shape[1])
    first = frames[:split].mean(axis=0) if split else frames.mean(axis=0)
    # The odd frame belongs to the second half, the same split `series_summary` uses.
    second = frames[split:].mean(axis=0)
    return {'mean': [round(float(value), 6) for value in frames.mean(axis=0)],
            'std': [round(float(value), 6) for value in std],
            'first_half': [round(float(value), 6) for value in first],
            'second_half': [round(float(value), 6) for value in second]}


def _kabsch_fit(mobile, reference):
    """The least-squares rigid superposition: (fitted mobile, centred reference), both in ångström.

    Translation and rotation are removed, so the residual is the internal difference the two conformations hold.
    """
    mobile = np.asarray(mobile, dtype=float)
    reference = np.asarray(reference, dtype=float)
    centred_m = mobile - mobile.mean(axis=0)
    centred_r = reference - reference.mean(axis=0)
    left, _, right = np.linalg.svd(centred_m.T @ centred_r)
    sign = np.sign(np.linalg.det(left @ right))
    rotation = left @ np.diag([1.0, 1.0, sign]) @ right
    return centred_m @ rotation, centred_r


def _xvg_columns(path):
    """One XVG file's time column, data columns and the legend each column carries.

    `gmx energy` writes its columns in the energy file's own term order, not in the order they were selected -- a
    request for Temperature, Pressure, Potential came back as Potential, Temperature, Pressure -- so a reader that
    trusted the request order would label every curve with the term next to it.

    The file is read line by line and each data column accumulates into an `array('d')`: an all-term EDR is a few
    hundred thousand rows by up to 45 columns, and a list of Python floats would cost several hundred megabytes for
    a record that keeps only summaries. The returned lists are per-column, in the XVG's own order.
    """
    labels, times, columns = [], array('d'), []
    with Path(path).open() as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith('@ s') and 'legend' in line:
                labels.append(line.split('legend', 1)[1].strip().strip('"'))
                continue
            if not line or line.startswith(('#', '@')):
                continue
            try:
                values = [float(value) for value in line.split()]
            except ValueError:
                continue
            if len(values) < 2:
                continue
            if not columns:
                columns = [array('d') for _ in range(len(values) - 1)]
            times.append(values[0])
            for index, column in enumerate(columns):
                column.append(values[index + 1])
    # A hand-written XVG may carry data without legends; name those columns positionally rather than dropping them.
    while len(labels) < len(columns):
        labels.append(f'column{len(labels) + 2}')
    return labels, times, columns


def _energy_menu(text):
    """The `(index, name)` pairs in a `gmx energy` menu, in order, or `[]` when there is no parseable menu.

    `gmx energy` prints its term list on stderr. The rows are numbered from 1 and a zero (or an empty line) ends a
    selection, so the pairs -- not their count -- are what the second call must send. A dashed rule may stand before
    or after the rows (this GROMACS prints it before them), so collection starts at the first numbered row after the
    "Select the terms" heading and stops at the first line that carries no numbered pair.
    """
    start = text.find('Select the terms')
    if start < 0:
        return []
    pairs, seen, started = [], set(), False
    for line in text[start:].splitlines():
        found = re.findall(r'(\d+)\s+(\S+)', line)
        if not found:
            if started:
                break
            continue
        started = True
        for index, name in found:
            if name in seen:
                continue
            seen.add(name)
            pairs.append((int(index), name))
    return pairs


def _is_no(value):
    """Whether a recorded coupling setting says `no` (the MDP's spelling, case and spacing ignored)."""
    return value is not None and str(value).strip().lower() == 'no'


def _coupling(manifest):
    """The AA production leg's recorded (thermostat, barostat) settings, each `None` when unrecorded."""
    settings = manifest.get('settings') or {}
    return settings.get('aa_production_tcoupl'), settings.get('aa_production_pcoupl')


def _nve(manifest):
    """Whether the manifest records an NVE AA production leg.

    A non-AA leg is not NVE (its coupling settings are not the keys this record describes). An AA leg is NVE only
    when both coupling keys are present and both say `no`; a present key that names a coupling is `False`, and a
    missing key is `None` -- an unrecorded coupling is unknown, not conservation.
    """
    if manifest.get('run_type') != 'aa_only':
        return False
    thermostat, barostat = _coupling(manifest)
    if thermostat is None or barostat is None:
        return None
    return _is_no(thermostat) and _is_no(barostat)


def _drift_basis(manifest, nve):
    """One sentence saying what the leg's coupling was and what the drift ratio therefore means."""
    if nve is True:
        return ('No thermostat or barostat is recorded for this AA production leg (aa_production_tcoupl and '
                'aa_production_pcoupl are both "no"), so the ratio is energy balance, not a conservation check.')
    if manifest.get('run_type') == 'aa_only':
        thermostat, barostat = _coupling(manifest)
        if thermostat is None or barostat is None:
            return ('The manifest does not record this AA production leg\'s thermostat and barostat, so the ratio '
                    'is energy balance, not a conservation check.')
        return (f'This AA production leg records tcoupl={thermostat!r} and pcoupl={barostat!r}, so it runs with a '
                'thermostat and/or barostat and the ratio is energy balance, not conservation.')
    return ('This leg is not an AA production leg, so no NVE coupling setting is recorded for it; the ratio is '
            'energy balance, not a conservation check.')


def _energy_term_key(name):
    """A term's name with GROMACS' XVG spelling folded: `Total-Energy` and `Total Energy` are the same term."""
    return name.replace('-', ' ').strip().lower()


def _term_summary(terms, name):
    """The summary of `name`, matching the XVG legend's spelling when it differs from the menu's."""
    if name in terms:
        return terms[name]
    wanted = _energy_term_key(name)
    return next((summary for label, summary in terms.items() if _energy_term_key(label) == wanted), {})


def _drift(work, terms):
    """The Total-Energy/Potential drift and their ratio, with the manifest-derived coupling verdict."""
    manifest = _manifest(work)
    total = _term_summary(terms, 'Total-Energy').get('slope_per_ns')
    potential = _term_summary(terms, 'Potential').get('slope_per_ns')
    ratio = (round(abs(total) / abs(potential), 6)
             if total is not None and potential is not None and abs(potential) > SLOPE_EPSILON else None)
    nve = _nve(manifest)
    return {'total_energy_slope_per_ns': total,
            'potential_slope_per_ns': potential,
            'kinetic_energy_slope_per_ns': _term_summary(terms, 'Kinetic-En.').get('slope_per_ns'),
            'ratio': ratio,
            'nve': nve,
            'basis': _drift_basis(manifest, nve)}


def _energy(work, trajectory):
    """Every term in the leg's EDR as a series summary, or None with the reason energy is absent.

    `sources` stages exactly one energy file, and it need not sit beside the trajectory: an AA reference
    publication extracts `07_reference/lig.xtc` while its `06_production/run.edr` stays in the production stage
    directory. So the staged tree is the fallback, and it is read only when it holds one `.edr` -- two would make
    "which leg" a guess.

    Discovery runs first: `gmx energy` without `-o` prints its term menu on stderr, and the parsed names decide which
    indices the plotting run asks for. The menu is not always parseable, so the three plotted terms remain the
    fallback. Only those three keep `time_ps`/`values`; every other term is statistics-only, which keeps the JSON
    bounded while the shape of the full EDR is still recorded.
    """
    edr = _energy_beside(trajectory)
    if edr is None:
        staged = sorted(path for path in Path(work).rglob('*.edr') if path.is_file())
        edr = staged[0] if len(staged) == 1 else None
    if edr is None:
        return None, 'no .edr is staged beside the trajectory or its stage directory'
    gmx = tools.tool_path('gmx')
    if gmx is None:
        return None, 'gmx is not available, so the .edr cannot be read'
    discovery = subprocess.run([gmx, 'energy', '-f', str(edr)], input='0\n',
                               capture_output=True, text=True)
    menu = _energy_menu(discovery.stderr) or _energy_menu(discovery.stdout)
    output = Path(work) / '.trajectory-overview-energy.xvg'
    try:
        if menu:
            # Every menu index, one per line, then the zero that ends the selection. The XVG carries all terms, not
            # only the selected three: the record summarises each one and the figure picks its own columns by legend.
            selection = '\n'.join([*(str(index) for index, _ in menu), '0', ''])
        else:
            selection = '\n'.join([*ENERGY_TERMS, '0', ''])
        done = subprocess.run([gmx, 'energy', '-f', str(edr), '-o', str(output)],
                              input=selection, capture_output=True, text=True)
        if done.returncode != 0 or not output.is_file():
            return None, f'gmx energy refused the .edr: {(done.stdout + done.stderr).strip().splitlines()[-1:]}'
        labels, times, columns = _xvg_columns(output)
    finally:
        output.unlink(missing_ok=True)
    if not times or not columns:
        return None, 'gmx energy wrote no data'
    time_ns = [time / 1000.0 for time in times]
    step = max(1, math.ceil(len(times) / ENERGY_POINTS))
    terms = {}
    for position, label in enumerate(labels):
        if position >= len(columns):
            continue
        values = columns[position]
        entry = _rounded(series_summary(values, times_ns=time_ns))
        if label in ENERGY_TERMS:
            entry['time_ps'] = [round(times[offset], 4) for offset in range(0, len(values), step)]
            entry['values'] = [round(values[offset], 6) for offset in range(0, len(values), step)]
        terms[label] = entry
    if not terms:
        return None, f'gmx energy wrote no {", ".join(ENERGY_TERMS)} column'
    return {'source': edr.name,
            'terms': terms,
            'components': {name: summary for name in ENERGY_COMPONENTS
                           if (summary := _term_summary(terms, name))},
            'pressure_tensor': {name: summary for name, summary in terms.items()
                                if name.startswith(('Pres-', 'Vir-')) or name == '#Surf*SurfTen'},
            'drift': _drift(work, terms),
            'interactions': {name: summary for name, summary in terms.items() if ':' in name}}, None


def _draw(path, series, labels, energy, reason, *, aggregate=True):
    """Draw the overview: shape, then energy. The aggregate panel is absent for a single-molecule run.

    Titles are generic on purpose: the same figure is drawn for a protein, a micelle and a small molecule, so a
    title that named a detergent would be wrong on most runs.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(14, 8), layout='constrained')
    FigureCanvasAgg(fig)
    rows = fig.subplots(2, 3)
    rmsd_axis, gyration_axis, third = rows[0]
    if aggregate:
        energy_axes = list(rows[1])
    else:
        # No aggregate curve to draw: the first energy term takes its cell and the spare cell is removed, so the
        # figure is five panels rather than a hole with nothing in it.
        energy_axes = [third, rows[1][0], rows[1][1]]
        fig.delaxes(rows[1][2])

    def line(axis, times, values, colour, title, ylabel):
        # The raw samples stay visible at low alpha; the moving average is the line a reader reads. Both are the
        # same data -- the window is stated in the legend -- so the picture never hides the points behind the trend.
        window = _window(len(values))
        axis.plot(times, values, color=colour, linewidth=0.8, alpha=.3, label='sampled')
        axis.plot(times, _moving_average(values, window), color=colour, linewidth=2.2, alpha=1.0,
                  label=f'moving average ({window} samples)')
        axis.set(title=title, xlabel='Time (ns)', ylabel=ylabel)
        axis.legend(fontsize=7, frameon=False)
        axis.grid(alpha=.18)

    line(rmsd_axis, series['times_ns'], series['rmsd_nm'], '#2455b0', 'RMSD', 'RMSD (nm)')
    line(gyration_axis, series['times_ns'], series['gyration_nm'], '#169186', 'Radius of gyration', 'Rg (nm)')
    if aggregate:
        line(third, series['times_ns'], series['aggregate_largest'], '#8a5a12', 'Largest aggregate', 'molecules')

    for axis, term, colour in zip(energy_axes, ENERGY_TERMS, ('#b03a48', '#6a4ea8', '#2f6b3a')):
        entry = (energy or {}).get('terms', {}).get(term)
        if entry:
            line(axis, [t / 1000 for t in entry['time_ps']], entry['values'], colour,
                 f"{term} · mean {entry['mean']:g}", term)
        else:
            axis.text(.5, .5, reason or 'not available', ha='center', va='center', wrap=True, fontsize=9)
            axis.grid(alpha=.18)

    fig.suptitle(f"Trajectory overview · {labels['segment']}", fontsize=13)
    fig.savefig(path, dpi=150)


def run(work, payload=None):
    """Measure one run's latest segment and write `trajectory-overview.png` and `.json`."""
    if mda is None or cdist is None:
        raise RuntimeError('MDAnalysis and scipy are required for a trajectory overview')
    work = Path(work)
    trajectory, structure = _chosen(work)
    universe = mda.Universe(str(structure), str(trajectory))
    frames = len(universe.trajectory)
    if frames < 1:
        raise ValueError(f'{trajectory.name} holds no frames')
    stride = max(1, math.ceil(frames / MAX_FRAMES))
    indices = list(range(0, frames, stride))

    universe.trajectory[indices[0]]
    box = np.asarray(universe.dimensions[:3], dtype=float)
    protein, _ = _protein(universe, work)
    molecules = _molecules(universe, protein)
    molecule_sizes = [len(group) for group in molecules]
    detergent_atoms = np.concatenate(molecules) if molecules else np.array([], dtype=int)
    threshold = float((_manifest(work).get('settings') or {}).get('contact_nm') or 0.6)

    # The subject is one thing: the protein, or -- in an empty micelle -- the aggregate the detergents form. The
    # aggregate is chosen once, on the first sampled frame, and those molecules are tracked for the whole segment;
    # aggregation itself is still measured on every detergent in every frame.
    if protein is not None:
        selection = protein
        groups = [protein]
        subject = 'protein'
    else:
        if not len(molecules):
            raise ValueError('this segment holds no protein and no detergent, so there is nothing to measure')
        first = _aggregates(molecule_sizes, universe.atoms.positions[detergent_atoms] / 10.0, threshold,
                            box / 10.0)
        if not first:
            raise ValueError('this segment holds detergent molecules but no aggregate to measure')
        groups = [molecules[index] for index in first[0]]
        selection = np.concatenate(groups)
        # One molecule is its own subject; only a run holding several has an aggregate to name.
        subject = 'molecule' if len(molecules) == 1 else 'largest detergent aggregate'

    reference = _unwrap(universe.atoms.positions, groups, box)[selection]
    times, rmsds, gyrations, largest, counts, free = [], [], [], [], [], []
    eigenvalues, asphericities, acylindricities, anisotropies, end_to_end = [], [], [], [], []
    # The per-atom squared residual after the same fit that gives RMSD; its frame mean is the atom's RMSF.
    squared_deviation = np.zeros(len(selection), dtype=float)
    pair_cap = len(selection) <= PAIR_ATOM_CAP
    # One sequential pass, not random seeks: a compressed XTC seeks from its start for every random frame (measured
    # on a live 2.5 GB file: 1.7 s a frame), while the same frames read in order cost the whole file once.
    wanted = iter(indices)
    next_wanted = next(wanted, None)
    for index, timestep in enumerate(universe.trajectory[indices[0]:indices[-1] + 1], start=indices[0]):
        if index != next_wanted:
            continue
        next_wanted = next(wanted, None)
        times.append(round(float(universe.trajectory.time) / 1000.0, 4))
        positions = universe.atoms.positions
        box = np.asarray(universe.dimensions[:3], dtype=float)
        # One periodic image for the subject's molecules before its shape is measured; MDAnalysis states positions
        # in ångström, so every length leaves this block in nanometres.
        subject_positions = _unwrap(positions, groups, box)[selection]
        frame_eigenvalues = _gyration_tensor_eigenvalues(subject_positions)
        eigenvalues.append(frame_eigenvalues)
        asphericity, acylindricity, anisotropy = _shape_metrics(frame_eigenvalues)
        asphericities.append(asphericity)
        acylindricities.append(acylindricity)
        anisotropies.append(anisotropy)
        fitted, reference_centred = _kabsch_fit(subject_positions, reference)
        deviation = fitted - reference_centred
        squared_deviation += (deviation ** 2).sum(axis=1)
        rmsds.append(round(float(np.sqrt((deviation ** 2).sum(axis=1).mean()) / 10.0), 6))
        gyrations.append(round(_radius_of_gyration(subject_positions), 6))
        if pair_cap:
            end_to_end.append(round(float(cdist(subject_positions, subject_positions).max()) / 10.0, 6))
        if len(molecules):
            aggregates = _aggregates(molecule_sizes, positions[detergent_atoms] / 10.0, threshold,
                                     box / 10.0)
            largest.append(len(aggregates[0]) if aggregates else 0)
            counts.append(len(aggregates))
            free.append(len(molecules) - len(aggregates[0]) if aggregates else len(molecules))
        else:
            largest.append(0)
            counts.append(0)
            free.append(0)

    energy, energy_reason = _energy(work, trajectory)
    series = {'times_ns': times, 'rmsd_nm': rmsds, 'gyration_nm': gyrations,
              'aggregate_largest': largest, 'aggregates': counts, 'aggregate_free': free}
    segment = _segment(work)
    labels_for_figure = {'segment': segment['name'] if segment else trajectory.stem}
    # One molecule cannot aggregate: its largest aggregate is always itself, so that panel is left out rather than
    # drawn as a flat line at 1. A protein-only segment likewise has no molecule to count.
    aggregate = len(molecules) > 1
    figure = work / 'trajectory-overview.png'
    _draw(figure, series, labels_for_figure, energy,
          (energy_reason if energy is None else '') or 'not available', aggregate=aggregate)

    rmsd_summary = _rounded(series_summary(rmsds, times_ns=times))
    rmsd_summary['se'] = rmsd_summary['block_sem']
    gyration_summary = _rounded(series_summary(gyrations, times_ns=times))
    gyration_summary['se'] = gyration_summary['block_sem']
    largest_summary = _rounded(series_summary(largest, times_ns=times))
    count_summary = _rounded(series_summary(counts, times_ns=times))
    free_summary = _rounded(series_summary(free, times_ns=times))
    rmsf = np.sqrt(squared_deviation / len(times)) / 10.0
    shape = {'rg_eigenvalues_nm': _eigenvalue_summary(eigenvalues),
             'asphericity': _rounded(series_summary(asphericities, times_ns=times)),
             'acylindricity': _rounded(series_summary(acylindricities, times_ns=times)),
             'shape_anisotropy': _rounded(series_summary(anisotropies, times_ns=times))}
    end_to_end_summary = (_rounded(series_summary(end_to_end, times_ns=times)) if pair_cap else None)
    plotted = None
    if energy and energy.get('terms'):
        plotted = next((energy['terms'][term] for term in ENERGY_TERMS if term in energy['terms']), None)
        if plotted is None:
            plotted = next(iter(energy['terms'].values()))
    record = {
        'segment': labels_for_figure['segment'],
        'trajectory': str(trajectory.relative_to(work)),
        'structure': str(structure.relative_to(work)),
        'frames_sampled': len(indices),
        'frames_in_file': frames,
        'stride': stride,
        'subject': subject,
        'molecules': len(molecules),
        'contact_nm': threshold,
        'pbc': {'treatment': 'minimum image (molecules whole, micelle not clustered)',
                'box_nm': [round(float(value) / 10.0, 3) for value in box]},
        'rmsd_nm': rmsd_summary,
        'gyration_nm': gyration_summary,
        'shape': shape,
        'rmsf_nm': {'atoms': int(len(selection)),
                    'mean': round(float(rmsf.mean()), 6),
                    'max': round(float(rmsf.max()), 6),
                    'per_atom': ([round(float(value), 6) for value in rmsf] if pair_cap else None)},
        'end_to_end_nm': end_to_end_summary,
        'aggregates': {'largest_mean': round(largest_summary['mean'], 3),
                       'largest_second_half_mean': round(largest_summary['second_half_mean'], 3),
                       'free_mean': round(free_summary['mean'], 3),
                       'count_mean': round(count_summary['mean'], 3),
                       'largest': largest_summary,
                       'count': count_summary,
                       'free': free_summary},
        'energy': energy,
        'energy_absent': energy_reason,
        'smoothing': {'fraction': SMOOTHING_FRACTION, 'frames': _window(len(times)),
                      'energy_samples': _window(len(plotted['values'])) if plotted else None},
        'series': series,
        'scientifically_validated': False,
        'note': ('A first-look record of one sampled segment. Distances are minimum-image; the radius of gyration is '
                 'the subject\'s, not every molecule in the box. It measures the sampled frames and says nothing '
                 'about convergence or model validity.'),
    }
    if not pair_cap:
        record['end_to_end_absent'] = (f'the subject has {len(selection)} atoms, above the {PAIR_ATOM_CAP}-atom cap '
                                       'for the O(N²) end-to-end distance')
    files.atomic_json(work / 'trajectory-overview.json', record)
    return {'files': ['trajectory-overview.png', 'trajectory-overview.json'],
            'figure': 'trajectory-overview.png', 'frames': len(indices), 'molecules': len(molecules),
            'rmsd_nm': record['rmsd_nm']['mean'], 'gyration_nm': record['gyration_nm']['mean'],
            'largest_aggregate': record['aggregates']['largest_mean']}
