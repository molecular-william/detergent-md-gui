"""Run artifact indexing and trajectory analyses for the local dashboard."""
import json
import re
import subprocess
from datetime import datetime, timezone

from ... import files
from ...execution import tools

try:
    import MDAnalysis as mda
except ImportError:  # trajectory analyses remain unavailable with an explicit explanation
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
