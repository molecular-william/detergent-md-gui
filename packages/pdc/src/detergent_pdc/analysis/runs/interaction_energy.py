"""`pdc-interaction-energy`: the force field's short-range pair energies between named parts of the stored system.

The run's own `.edr` carries whole-system terms because the pdc MDPs set no `energygrps`. This producer extracts the
same bounded sample the structural analysis reads, builds a rerun input that declares `Protein`, `Detergent` and
`Water` as energy groups, re-evaluates the stored coordinates with `mdrun -rerun`, and reads the `LJ-SR` and `Coul-SR`
cross terms with `gmx energy`.

The pair rows are the user's three: receptor–detergent, receptor–receptor ("receptor only") and receptor–water. The
numbers are short-range Lennard-Jones plus the reaction-field Coulomb term at the run's own cutoffs. They are not a
binding free energy, do not include bonded terms, and do not add up to the whole-system potential. The rerun uses CPU
nonbonded because GROMACS refuses multiple energy groups on the GPU.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from dashboard import files
from dashboard.analysis.runs import readers, trajectory_header
from dashboard.analysis.runs.statistics import series_summary
from dashboard.analysis.runs.trajectory_overview import read_energy
from dashboard.execution import tools
from detergent_pdc.analysis.runs import structure

RECORD = 'pdc-interaction-energy.json'
SAMPLE = 'sample.xtc'
#: The rerun's own scratch names; every one is removed before the report is returned, so only the sample and JSON
#: are published.
MDP = 'rerun.mdp'
INDEX = 'energy.ndx'
TPR = 'rerun.tpr'
EDR = 'rerun.edr'
LOG = 'rerun.log'
TRR = 'rerun.trr'
#: A 199-frame rerun of a 20k-bead system is seconds on CPU; the cap is for a stalled or enormous sample.
RERUN_TIMEOUT_S = 1800
#: The three reported pairs: `(first, second, label, gmx-energy label suffix)`. `first`/`second` are the group names
#: in the rerun index; the suffix is the pair spelling `gmx energy` uses after `LJ-SR:` and `Coul-SR:`.
PAIRS = (
    ('protein', 'detergent', 'Receptor – detergent', 'Protein-Detergent'),
    ('protein', 'protein', 'Receptor only', 'Protein-Protein'),
    ('protein', 'water', 'Receptor – water', 'Protein-Water'),
)
#: The exact terms requested from `gmx energy`; the report records the labels it actually received.
TERMS = tuple(f'{kind}:{suffix}' for _first, _second, _label, suffix in PAIRS for kind in ('LJ-SR', 'Coul-SR'))


# ------------------------------------------------------------------------------------------------------------ sources

def sources(run_dir, payload=None):
    """The structural sources plus the leg's topology and MDP, which the rerun needs.

    `structure.sources` stages the chosen leg's trajectory, structure, run input and assessment. The rerun also reads
    the leg's `system.top`, `system.gro` and `mdout.mdp`; the topology's own `#include`s are read in place beside the
    real file, so the staged paths are symlinks to the run's files and the producer resolves them before `grompp`.
    """
    run_dir = Path(run_dir)
    entries = structure.sources(run_dir, payload)
    trajectory = next((relative for relative in entries if str(relative).endswith('.xtc')), None)
    if trajectory is None:
        return entries
    stage = structure._stage_directory(trajectory)
    candidates = [run_dir / 'stages' / str(stage), run_dir / 'stages' / '06_assessment',
                  run_dir / 'stages' / '02_system']
    build = next((base for base in candidates
                  if (base / 'system.top').is_file() and (base / 'system.gro').is_file()), None)
    if build is not None:
        for name in ('system.top', 'system.gro'):
            entries[str((build / name).relative_to(run_dir))] = build / name
    mdp = next((base / 'mdout.mdp' for base in candidates if (base / 'mdout.mdp').is_file()), None)
    if mdp is not None:
        entries[str(mdp.relative_to(run_dir))] = mdp
    return entries


# --------------------------------------------------------------------------------------------------------- commands

def _gmx(gmx, arguments, work, *, stdin=None, timeout=None):
    result = subprocess.run([gmx, *arguments], cwd=work, input=stdin, capture_output=True, text=True,
                            timeout=timeout)
    if result.returncode:
        tail = ' / '.join(line.strip() for line in (result.stdout + result.stderr).splitlines() if line.strip())
        raise RuntimeError(f'gmx {arguments[0]} failed ({result.returncode}): {tail[-500:]}')
    return result


def _command(step, arguments):
    return {'step': step, 'argv': ['gmx', *arguments]}


def _rename_index(path):
    """Rename the four `gmx select` groups, in selection order, to the names the rerun MDP asks for."""
    names = ('Protein', 'Detergent', 'Water', 'System')
    lines = Path(path).read_text().splitlines()
    renamed = iter(names)
    out = []
    for line in lines:
        if line.startswith('['):
            try:
                out.append(f'[ {next(renamed)} ]')
            except StopIteration:
                out.append(line)
        else:
            out.append(line)
    Path(path).write_text('\n'.join(out) + '\n')


def _mdp_with_groups(source, target):
    """The run's own expanded MDP with `energygrps` set; every other line is the run's physics unchanged."""
    lines = Path(source).read_text().splitlines()
    out = []
    found = False
    for line in lines:
        if line.lstrip().startswith('energygrps'):
            out.append('energygrps               = Protein Detergent Water')
            found = True
        else:
            out.append(line)
    if not found:
        out.append('energygrps               = Protein Detergent Water')
    Path(target).write_text('\n'.join(out) + '\n')


def _group_counts(path):
    counts, name = {}, None
    for line in Path(path).read_text().splitlines():
        if line.startswith('['):
            name = line.strip().strip('[]').strip()
            counts[name] = 0
        elif name and line.strip():
            counts[name] += len(line.split())
    return counts


def _cutoff_model(mdp):
    """The energy-model values the rerun actually used, read from the run's expanded MDP."""
    wanted = {'coulombtype': 'coulombtype', 'epsilon_r': 'epsilon-r', 'epsilon_rf': 'epsilon-rf',
              'rcoulomb_nm': 'rcoulomb', 'rvdw_nm': 'rvdw', 'rlist_nm': 'rlist',
              'vdw_type': 'vdw-type', 'vdw_modifier': 'vdw-modifier'}
    values = {}
    for line in Path(mdp).read_text().splitlines():
        text = line.split(';', 1)[0].strip()
        if '=' not in text:
            continue
        key, value = (part.strip() for part in text.split('=', 1))
        for field, mdp_key in wanted.items():
            if key == mdp_key:
                values[field] = value
    return {**values, 'long_range_correction': 'none',
            'mdp': 'the run\'s own expanded MDP, plus energygrps'}


def _column(data, label):
    try:
        return [float(value) for value in data['columns'][data['labels'].index(label)]]
    except (ValueError, IndexError):
        return None


def _summary(values, times_ns):
    if values is None:
        return None
    summary = series_summary(values, times_ns=times_ns)
    return {key: (round(value, 6) if isinstance(value, float) else value) for key, value in summary.items()
            if key in ('n', 'mean', 'std', 'sem', 'block_sem', 'median', 'p05', 'p95', 'min', 'max')}


def _pair_records(data):
    times_ns = [round(time / 1000.0, 4) for time in data['times_ps']]
    pairs = []
    for first, second, label, suffix in PAIRS:
        lj_label, coul_label = f'LJ-SR:{suffix}', f'Coul-SR:{suffix}'
        lj, coul = _column(data, lj_label), _column(data, coul_label)
        if lj is None or coul is None:
            pairs.append({'first': first, 'second': second, 'label': label,
                          'lj_sr_mean_kj_mol': None, 'lj_sr_sem_kj_mol': None,
                          'coul_sr_mean_kj_mol': None, 'coul_sr_sem_kj_mol': None,
                          'total_mean_kj_mol': None, 'total_sem_kj_mol': None,
                          'frames': 0, 'energy_labels': [], 'series': None})
            continue
        total = [a + b for a, b in zip(lj, coul)]
        lj_summary, coul_summary, total_summary = _summary(lj, times_ns), _summary(coul, times_ns), _summary(total, times_ns)
        pairs.append({
            'first': first, 'second': second, 'label': label,
            'lj_sr_mean_kj_mol': lj_summary['mean'], 'lj_sr_sem_kj_mol': lj_summary['sem'],
            'coul_sr_mean_kj_mol': coul_summary['mean'], 'coul_sr_sem_kj_mol': coul_summary['sem'],
            'total_mean_kj_mol': total_summary['mean'], 'total_sem_kj_mol': total_summary['sem'],
            'frames': len(total), 'energy_labels': [lj_label, coul_label],
            'series': {'time_ns': times_ns, 'lj_sr_kj_mol': [round(value, 6) for value in lj],
                       'coul_sr_kj_mol': [round(value, 6) for value in coul],
                       'total_kj_mol': [round(value, 6) for value in total]},
        })
    return pairs


# ------------------------------------------------------------------------------------------------------------- run

def run(work, payload=None):
    """Rerun the sampled leg with energy groups and write `pdc-interaction-energy.json`."""
    work = Path(work)
    trajectory, structure_file = structure._leg(work)
    manifest = readers.run_manifest(work)
    criterion = structure._criterion(manifest, None)
    residue = criterion['detergent_residue']
    gmx = tools.tool_path('gmx')
    if not gmx:
        raise FileNotFoundError('GROMACS is not available')

    relative_trajectory = structure._work_name(work, trajectory)
    stage = structure._stage_directory(relative_trajectory)
    candidates = [work / 'stages' / str(stage), work / 'stages' / '06_assessment', work / 'stages' / '02_system']
    topology = next((base / 'system.top' for base in candidates if (base / 'system.top').is_file()), None)
    geometry = next((base / 'system.gro' for base in candidates if (base / 'system.gro').is_file()), None)
    mdp = next((base / 'mdout.mdp' for base in candidates if (base / 'mdout.mdp').is_file()), None)
    if topology is None or geometry is None or mdp is None:
        raise ValueError('the run stages no system.top/system.gro/mdout.mdp, so an energy rerun cannot be built')
    # The staged files are symlinks; resolving them lets the topology's own #include paths keep working in place.
    topology, geometry, mdp = topology.resolve(), geometry.resolve(), mdp.resolve()

    run_input = structure._run_input(work, trajectory) or structure_file
    header = trajectory_header.read(structure_file, trajectory)
    if not header or not header.get('frames'):
        raise ValueError(f'{trajectory.name} states no readable frame count, so it cannot be sampled')
    arguments, stride = structure.sample_arguments(header['frames'], header['first_ns'], header['dt_ps'])
    commands = []
    commands.append(_command('extract sample',
                             ['trjconv', '-s', str(run_input), '-f', str(trajectory), '-o', SAMPLE, *arguments]))
    commands.append(_command('build index',
                             ['select', '-s', str(run_input), '-select', structure._protein_selection(residue),
                              structure._detergent_selection(residue), structure._water_selection(), 'all',
                              '-on', INDEX]))
    commands.append(_command('build rerun input',
                             ['grompp', '-f', MDP, '-c', str(geometry), '-p', str(topology), '-n', INDEX,
                              '-o', TPR, '-maxwarn', '2']))
    commands.append(_command('rerun',  # the exact chain is recorded for a reader; `-nb cpu` is required by energy groups
                             ['mdrun', '-s', TPR, '-rerun', SAMPLE, '-deffnm', 'rerun', '-nb', 'cpu']))

    _gmx(gmx, ['trjconv', '-s', str(run_input), '-f', str(trajectory), '-o', SAMPLE, *arguments],
         work, stdin='0\n', timeout=structure.EXTRACT_TIMEOUT_S)
    _gmx(gmx, ['select', '-s', str(run_input), '-select', structure._protein_selection(residue),
               structure._detergent_selection(residue), structure._water_selection(), 'all', '-on', INDEX], work)
    _rename_index(work / INDEX)
    _mdp_with_groups(mdp, work / MDP)
    _gmx(gmx, ['grompp', '-f', MDP, '-c', str(geometry), '-p', str(topology), '-n', INDEX, '-o', TPR,
               '-maxwarn', '2'], work)
    threads = str(max(1, min(8, int((manifest.get('settings') or {}).get('mdrun_ntomp') or 8))))
    _gmx(gmx, ['mdrun', '-s', TPR, '-rerun', SAMPLE, '-deffnm', 'rerun', '-nb', 'cpu', '-ntomp', threads,
               '-pin', 'off'], work, timeout=RERUN_TIMEOUT_S)

    data, reason = read_energy(work / EDR, work, terms=TERMS)
    energy_absent = reason
    pairs = _pair_records(data) if data else [
        {'first': first, 'second': second, 'label': label,
         'lj_sr_mean_kj_mol': None, 'lj_sr_sem_kj_mol': None, 'coul_sr_mean_kj_mol': None,
         'coul_sr_sem_kj_mol': None, 'total_mean_kj_mol': None, 'total_sem_kj_mol': None,
         'frames': 0, 'energy_labels': [], 'series': None}
        for first, second, label, _suffix in PAIRS]
    groups = _group_counts(work / INDEX)
    times_ns = [round(time / 1000.0, 4) for time in (data['times_ps'] if data else [])]
    record = {
        'kind': 'pdc-interaction-energy', 'schema_version': 1,
        'leg': {'name': structure._segment_name(stage), 'stage_directory': stage,
                'trajectory': relative_trajectory, 'structure': structure._work_name(work, structure_file),
                'run_input': structure._work_name(work, run_input) if run_input else None,
                'chosen_by': "the run's own segmenter: the latest playable segment (extension, else assessment)",
                'fallback_reason': (manifest.get('skipped_stages') or {}).get('CG extension MD')
                if stage in ('06_assessment', '2_assessment') else None},
        'sampling': {'frames_in_file': header['frames'], 'frames_sampled': len(times_ns), 'stride': stride,
                     'first_ns': header.get('first_ns'), 'last_ns': (round(header['first_ns'] + header['time_ns'], 6)
                                                                     if header.get('first_ns') is not None
                                                                     and header.get('time_ns') is not None else None),
                     'span_ns': header.get('time_ns'), 'frame_dt_ps': header.get('dt_ps'),
                     'extracted_trajectory': SAMPLE},
        'groups': [{'name': 'protein', 'definition': structure._protein_selection(residue),
                    'beads': groups.get('Protein', 0)},
                   {'name': 'detergent', 'definition': structure._detergent_selection(residue),
                    'beads': groups.get('Detergent', 0)},
                   {'name': 'water', 'definition': structure._water_selection(), 'beads': groups.get('Water', 0)}],
        'cutoff_model': _cutoff_model(mdp), 'pairs': pairs, 'commands': commands,
        'method': ('the run\'s own force field re-evaluated on the sampled stored coordinates with gmx mdrun -rerun; '
                   'short-range Lennard-Jones and reaction-field Coulomb between the stated groups, at the run\'s own '
                   'cutoffs; no long-range correction and no bonded or free-energy term'),
        'caveats': [
            'The pair energies are a view of the force field\'s short-range terms, not a decomposition of the '
            'whole-system potential: the missing bonded terms and the unreported pairs mean the rows do not add up '
            'to the total energy.',
            'These are not binding free energies: no entropy and no long-range correction are included.',
            'A bounded sample of the stored leg, not a converged ensemble.',
            'The rerun uses CPU nonbonded because GROMACS does not support multiple energy groups on the GPU.',
            'Reaction-field electrostatics: the short-range Coulomb term is the whole electrostatic treatment the '
            'run used, with no reciprocal-space term.',
        ],
        'scientifically_validated': False,
        'energy_absent': energy_absent,
    }
    files.atomic_json(work / RECORD, record)
    for name in (MDP, INDEX, TPR, EDR, LOG, TRR):
        (work / name).unlink(missing_ok=True)
    for path in work.glob('#*'):
        path.unlink(missing_ok=True)
    return {'files': sorted(path.name for path in work.iterdir() if path.is_file()),
            'frames_sampled': len(times_ns), 'stride': stride,
            'pairs': {pair['label']: pair['total_mean_kj_mol'] for pair in pairs},
            'energy_absent': energy_absent}
