"""Radius-consistent GROMACS SASA and rotatable solvent-accessible envelopes.

The smooth mesh is the union of probe-inflated spheres (SAS), not a claim to
reconstruct the re-entrant solvent-excluded surface. GROMACS dot surfaces are
retained separately for inspection.
"""
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from dashboard import files
from dashboard.analysis import progress
from dashboard.analysis.runs.radii import AA_RADII, PROBE
from dashboard.execution import tools
from dashboard.models import sugars as carbohydrates

NDOTS = 240
SASA_TIMEOUT = 300
SNAPSHOT_TIMEOUT = 120


def envelope(positions, radii, spacing=.04):
    from skimage.measure import marching_cubes
    radii = np.asarray(radii) + PROBE
    low = (positions-radii[:,None]).min(axis=0)-spacing
    high = (positions+radii[:,None]).max(axis=0)+spacing
    shape = np.ceil((high-low)/spacing).astype(int)+1
    if np.prod(shape)>8_000_000: raise ValueError('Surface grid too large; check molecule-whole coordinates')
    grid = np.indices(shape,dtype=np.float32)*spacing+low[:,None,None,None]
    field = np.full(shape,-np.inf,dtype=np.float32)
    for p,r in zip(positions,radii):
        field = np.maximum(field,r-np.sqrt(((grid-p[:,None,None,None])**2).sum(axis=0)))
    vertices,faces,_,_ = marching_cubes(field,level=0,spacing=(spacing,)*3)
    return vertices+low,faces


def align(points, target, physical):
    a=points[physical]; b=target[physical]
    u,_,v=np.linalg.svd((a-a.mean(axis=0)).T@(b-b.mean(axis=0)))
    fix=np.eye(3);fix[2,2]=np.linalg.det(u@v)
    return (points-a.mean(axis=0))@(u@fix@v)+b.mean(axis=0)


def _sasa_commands(gmx):
    """The two GROMACS calls one variant makes: full trajectory, then the one-frame Connolly snapshot.

    Pure so the reviewed knobs -- probe, ndots, surface/output -- are pinned without running GROMACS.
    """
    full = [gmx, 'sasa', '-s', 'surface.gro', '-f', 'surface.xtc', '-o', 'sasa.xvg',
            '-probe', str(PROBE), '-ndots', str(NDOTS), '-surface', 'all', '-output', 'all']
    snapshot = [gmx, 'sasa', '-s', 'surface.gro', '-f', 'surface.gro', '-o', 'snapshot-sasa.xvg',
                '-q', 'connolly.pdb', '-probe', str(PROBE), '-ndots', str(NDOTS), '-surface', 'all',
                '-output', 'all']
    return full, snapshot


def _write_variant(label, universe, reader, radii, model, work):
    """Write one variant's XTC/GRO/radii and return its frame-0 positions in nm.

    Runs on the main thread: the MDAnalysis readers are stateful, and a reader writes its offsets cache beside its
    input, so two readers of the same file must never overlap.
    """
    import MDAnalysis as mda
    mapped = label.startswith('Mapped')
    first = None
    # Derived portable GRO/XTCs keep source times; source trajectories never change.
    with mda.Writer(str(work/'surface.xtc'), n_atoms=len(universe.atoms)) as writer:
        for idx, frame in enumerate(reader.trajectory):
            if mapped:
                positions = carbohydrates.coordinates(model, frame.positions, scaled=label == 'Mapped ring-scaled')
                universe.atoms.positions = positions; universe.dimensions = frame.dimensions
                universe.trajectory.ts.time = frame.time
            if not np.isfinite(universe.atoms.positions).all(): raise ValueError('Nonfinite surface coordinates')
            if idx == 0:
                first = universe.atoms.positions.copy()/10
                universe.atoms.write(str(work/'surface.gro'))
            writer.write(universe.atoms)
    (work/'vdwradii.dat').write_text(''.join(f'{a.resname} {a.name} {r}\n' for a, r in zip(universe.atoms, radii)))
    return first


def _gmx_variant(label, work, gmx):
    """Run one variant's two gmx commands in its own directory; return (commands, statistics).

    `work` is `<run>/analysis/surfaces/<variant>`, so a command's recorded cwd is run-relative. Raises with the label
    and the failed command's stderr tail, which the orchestrator joins across variants.
    """
    root = work.parents[2]
    commands = []
    for command, log, timeout in zip(_sasa_commands(gmx), ('sasa.log', 'connolly.log'),
                                     (SASA_TIMEOUT, SNAPSHOT_TIMEOUT)):
        result = subprocess.run(command, cwd=work, text=True, capture_output=True, timeout=timeout)
        (work/log).write_text(result.stdout+result.stderr)
        commands.append({'cwd': str(work.relative_to(root)), 'command': command, 'exit_code': result.returncode})
        if result.returncode: raise RuntimeError(f'{label}: {result.stderr[-2000:]}')
    try:
        values = np.array([[float(x) for x in line.split()[:2]] for line in (work/'sasa.xvg').read_text().splitlines() if line.strip() and not line.startswith(('#', '@'))])
        if len(values) < 2 or not np.isfinite(values).all(): raise ValueError('SASA requires at least two finite frames')
        stats = {'frames': len(values), 'start_ps': float(values[0, 0]), 'end_ps': float(values[-1, 0]),
                 'mean_nm2': float(values[:, 1].mean()), 'std_nm2': float(values[:, 1].std()),
                 'xvg': str((work/'sasa.xvg').relative_to(root))}
    except Exception as exc:
        raise RuntimeError(f'{label}: {exc}') from exc
    return commands, stats


def generate(run_dir):
    import MDAnalysis as mda
    root=Path(run_dir); output=root/'analysis/surfaces'; output.mkdir(parents=True,exist_ok=True)
    if (output/'metadata.json').exists(): raise FileExistsError('Generate a new immutable surface analysis attempt')
    model=json.loads((root/'2_mapping/model.json').read_text())
    aa=mda.Universe(str(root/'1_AA-reference/prod/lig.gro'),str(root/'1_AA-reference/prod/lig.xtc'))
    cg=mda.Universe(str(root/'4_CG_sim/prod/lig_CG.gro'),str(root/'4_CG_sim/prod/lig_CG.xtc'))
    if len(cg.atoms)!=len(model['beads']): raise ValueError('CG atom order/count does not match candidate')
    if list(cg.atoms.names)!=[b['export_name'] for b in model['beads']]: raise ValueError('CG bead names differ from mapping')
    aa_r=[]
    import re
    for name in aa.atoms.names:
        element=re.sub('[^A-Za-z]','',name)
        element=element[:2].title() if element[:2].title() in ('Cl','Br') else element[:1].upper()
        if element not in AA_RADII: raise ValueError(f'No verified Rowland–Taylor radius for {name}')
        aa_r.append(AA_RADII[element])
    cg_r=[carbohydrates.RADII_NM[b['size']] for b in model['beads']]
    physical=[i for i,b in enumerate(model['beads']) if not b.get('virtual_site')]
    variants={'AA':(aa,aa_r),'Mapped raw':(cg,cg_r)}
    if model.get('rings'): variants['Mapped ring-scaled']=(cg,cg_r)
    variants['Simulated CG']=(cg,cg_r)
    gmx=tools.tool_path('gmx')
    if not gmx: raise FileNotFoundError('GROMACS not available')
    first={};stats={};commands=[]
    try:
        # Extract each variant on this thread, submit its gmx work as soon as its XTC is closed, then extract the
        # next: that overlaps the 26 s of extraction with the AA variant's long full-trajectory sasa.
        with ThreadPoolExecutor(max_workers=min(len(variants),os.cpu_count() or 1)) as pool:
            futures={}
            for label,(universe,radii) in variants.items():
                work=output/label.lower().replace(' ','-');work.mkdir()
                mapped=label.startswith('Mapped')
                reader=aa if mapped else universe
                progress.report(f'Surfaces: extracting {label}')
                first[label]=_write_variant(label,universe,reader,radii,model,work)
                progress.report(f'Surfaces: {label} · gmx sasa')
                futures[label]=pool.submit(_gmx_variant,label,work,gmx)
                futures[label].add_done_callback(lambda _,label=label: progress.report(f'Surfaces: {label} done'))
            # Join in variant order so metadata['commands'] is deterministic even when completions interleave.
            failures=[]
            for label,future in futures.items():
                try:
                    variant_commands,variant_stats=future.result()
                except Exception as exc:
                    failures.append(str(exc) if label in str(exc) else f'{label}: {exc}')
                    continue
                commands.extend(variant_commands);stats[label]=variant_stats
            if failures: raise RuntimeError('surface variants failed: '+'; '.join(failures))
            progress.report('Surfaces: envelopes and pair')
            target=first['Mapped raw']
        first['Simulated CG']=align(first['Simulated CG'],target,physical)
        center=first['AA'].mean(axis=0)
        # Only the two panels the pair JSON carries: the AA-vs-each-variant envelopes fed the removed figure.
        meshes={label:envelope(positions-center,variants[label][1]) for label,positions in first.items()
                if label in ('AA','Simulated CG')}
        colors={'AA':'#2864b5','Simulated CG':'#188b75'}
        extent=max(np.max(np.abs(v)) for v,_ in meshes.values())+.1
        # The primary pair as its own machine-readable panels: the dashboard draws AA and Simulated CG side by side,
        # on the same centred coordinates and the same extent. Data only, so the reader reuses the dashboard's
        # Plotly instead of loading another bundle; vertices/faces are the same meshes the SASA work built.
        def panel(label, kind, marker_name, marker_colour, marker_size):
            vertices, faces = meshes[kind]
            markers = first[kind] - center
            return {'label': label, 'colour': colors[label],
                    'mesh': {'x': np.round(vertices[:,0],6).tolist(),'y': np.round(vertices[:,1],6).tolist(),
                             'z': np.round(vertices[:,2],6).tolist(),
                             'i': faces[:,0].astype(int).tolist(),'j': faces[:,1].astype(int).tolist(),
                             'k': faces[:,2].astype(int).tolist()},
                    'markers': {'name': marker_name, 'colour': marker_colour, 'size': marker_size,
                                'x': np.round(markers[:,0],6).tolist(),'y': np.round(markers[:,1],6).tolist(),
                                'z': np.round(markers[:,2],6).tolist()}}
        aa_cg={'probe_nm':float(PROBE),'extent':float(extent),'rendering':'SAS mesh, AA vs Simulated CG',
               'scientifically_validated':False,
               'panels':[panel('AA','AA','AA atoms','#26384f',3),
                         panel('Simulated CG','Simulated CG','Simulated CG beads',colors['Simulated CG'],5)]}
        aa_cg_path=output/'surface-comparison-aa-cg.json';aa_cg_path.write_text(json.dumps(aa_cg)+'\n')
        metadata={'probe_nm':PROBE,'AA_radii_nm':AA_RADII,'CG_radii_nm':carbohydrates.RADII_NM,'grid_spacing_nm':.04,'statistics':stats,'commands':commands,'scientifically_validated':False,'aa_cg_comparison':str(aa_cg_path.relative_to(root)),'rendering':'SAS mesh, GROMACS Connolly dots retained separately','source_sha256':{str(p.relative_to(root)):files.sha256(p) for p in [root/'2_mapping/model.json',root/'1_AA-reference/prod/lig.xtc',root/'4_CG_sim/prod/lig_CG.xtc']}}
        (output/'metadata.json').write_text(json.dumps(metadata,indent=2));return metadata
    finally:
        aa.trajectory.close();cg.trajectory.close()
