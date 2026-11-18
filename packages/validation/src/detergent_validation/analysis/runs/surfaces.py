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
from dashboard.analysis.runs import structures
from dashboard.analysis.runs.radii import AA_RADII, PROBE
from dashboard.execution import tools
from dashboard.models import sugars as carbohydrates

NDOTS = 240
SASA_TIMEOUT = 300
SNAPSHOT_TIMEOUT = 120


def envelope(positions, radii, spacing=.04):
    from skimage.measure import marching_cubes
    positions = np.asarray(positions, dtype=float)
    radii = np.asarray(radii) + PROBE
    low = (positions-radii[:,None]).min(axis=0)-spacing
    high = (positions+radii[:,None]).max(axis=0)+spacing
    shape = np.ceil((high-low)/spacing).astype(int)+1
    if np.prod(shape)>8_000_000: raise ValueError('Surface grid too large; check molecule-whole coordinates')
    axes = [np.arange(n,dtype=np.float32)*spacing+low[i] for i,n in enumerate(shape)]
    field = np.full(shape,-np.inf,dtype=np.float64)
    for p,r in zip(positions,radii):
        # A sphere's contribution is negative outside its own bounding box, and a grid point whose value can sit on
        # a level-0 edge is never more than one cell beyond it, so evaluating the sphere only over its box plus one
        # cell leaves every intersected edge's endpoints -- and therefore every mesh vertex -- as the whole-grid
        # pass computed them. Outside it the point's value cannot be the maximum and is negative either way.
        start = np.floor((p-r-spacing-low)/spacing).astype(int)-1
        stop = np.ceil((p+r+spacing-low)/spacing).astype(int)+2
        start = np.clip(start,0,shape); stop = np.clip(stop,0,shape)
        sub = tuple(slice(a,b) for a,b in zip(start,stop))
        dx = axes[0][sub[0]]-p[0]; dy = axes[1][sub[1]]-p[1]; dz = axes[2][sub[2]]-p[2]
        contribution = r-np.sqrt((dx[:,None,None]**2+dy[None,:,None]**2)+dz[None,None,:]**2)
        field[sub] = np.maximum(field[sub],contribution)
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


def _write_mapped_variants(labels, variants, aa, model, output):
    """Every mapped variant from ONE read of the AA trajectory.

    `Mapped raw` and `Mapped ring-scaled` read the same atomistic file through the mapping, so before this pass each
    decoded it (measured 4.05-4.84 s and 4.94-5.77 s; one of the two decodes was pure duplicate work). One pass
    writes both.

    The mapped variants keep calling `sugars.coordinates` per frame, not `coordinates_many`: `coordinates` is
    dtype-sensitive -- a float32 trajectory makes its bead centre of geometry a float32 mean -- and the published
    surfaces were built through that rounding, so a float64 batch changes every mapped byte (measured on the real
    24-atom reference: 18 378 of 20 001 frames still differ after the timestep's float32 store, and both
    `surface.xtc`s). One decode is what this pass buys; the arithmetic stays the oracle's.

    Runs on the main thread, like `_write_variant`: the AA reader is stateful and its offsets cache sits beside it.
    Returns `{label: frame-0 positions in nm}`.
    """
    import MDAnalysis as mda
    writers = {}
    for label in labels:
        universe = variants[label][0]
        work = output / label.lower().replace(' ', '-')
        writers[label] = (mda.Writer(str(work / 'surface.xtc'), n_atoms=len(universe.atoms)), work)
    first = {}
    try:
        for idx, frame in enumerate(aa.trajectory):
            for label in labels:
                universe, radii = variants[label]
                universe.atoms.positions = carbohydrates.coordinates(
                    model, frame.positions, scaled=label == 'Mapped ring-scaled')
                universe.dimensions = frame.dimensions
                universe.trajectory.ts.time = frame.time
                if not np.isfinite(universe.atoms.positions).all():
                    raise ValueError('Nonfinite surface coordinates')
                if idx == 0:
                    first[label] = universe.atoms.positions.copy() / 10
                    universe.atoms.write(str(writers[label][1] / 'surface.gro'))
                writers[label][0].write(universe.atoms)
    finally:
        for writer, _ in writers.values():
            writer.close()
    for label in labels:
        universe, radii = variants[label]
        work = writers[label][1]
        (work / 'vdwradii.dat').write_text(''.join(f'{a.resname} {a.name} {r}\n'
                                                   for a, r in zip(universe.atoms, radii)))
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
    for name in aa.atoms.names:
        element=structures.atom_element(name)
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
        # Every variant is extracted on this thread, and each one's `gmx sasa` legs are submitted as soon as its files
        # close. The order is by what frees the tail earliest: the CG variant is independent, the AA variant's leg is
        # the longest (a full-trajectory sasa), and the two mapped variants share one read of the AA file (see
        # `_write_mapped_variants`). Submissions are collected by label and joined in variant order below, so the
        # record's `commands` order stays the one it always had.
        with ThreadPoolExecutor(max_workers=min(len(variants),os.cpu_count() or 1)) as pool:
            submitted={}
            mapped=[label for label in variants if label.startswith('Mapped')]
            others=[label for label in variants if label != 'AA' and label not in mapped]
            for label in variants:
                (output/label.lower().replace(' ','-')).mkdir()
            def submit(label):
                work=output/label.lower().replace(' ','-')
                progress.report(f'Surfaces: {label} · gmx sasa')
                future=pool.submit(_gmx_variant,label,work,gmx)
                future.add_done_callback(lambda _,label=label: progress.report(f'Surfaces: {label} done'))
                submitted[label]=future
            for label in others:
                universe,radii=variants[label]
                progress.report(f'Surfaces: extracting {label}')
                first[label]=_write_variant(label,universe,universe,radii,model,output/label.lower().replace(' ','-'))
                submit(label)
            progress.report('Surfaces: extracting AA')
            first['AA']=_write_variant('AA',aa,aa,variants['AA'][1],model,output/'aa')
            submit('AA')
            for label in mapped:
                progress.report(f'Surfaces: extracting {label}')
            first.update(_write_mapped_variants(mapped, variants, aa, model, output))
            for label in mapped:
                submit(label)
            # Join in variant order so metadata['commands'] is deterministic even when completions interleave.
            failures=[]
            for label in variants:
                try:
                    variant_commands,variant_stats=submitted[label].result()
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
