"""Radius-consistent GROMACS SASA and rotatable solvent-accessible envelopes.

The smooth mesh is the union of probe-inflated spheres (SAS), not a claim to
reconstruct the re-entrant solvent-excluded surface. GROMACS dot surfaces are
retained separately for inspection.
"""
import json
from pathlib import Path
import shutil
import subprocess
import os
import numpy as np
from ...models import sugars as carbohydrates
from ... import files

AA_RADII = {'H':.109,'C':.175,'N':.161,'O':.156,'F':.144,'P':.180,'S':.179,'Cl':.174,'Br':.185,'I':.200}
PROBE = .191


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


def generate(run_dir):
    import MDAnalysis as mda
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
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
    gmx=shutil.which('gmx',path=f'{Path.home()}/Downloads/gromacs-2026.0/build/bin:'+os.environ.get('PATH',''))
    if not gmx: raise FileNotFoundError('GROMACS not available')
    first={};stats={};commands=[]
    try:
        for label,(universe,radii) in variants.items():
            work=output/label.lower().replace(' ','-');work.mkdir()
            mapped=label.startswith('Mapped')
            reader=aa if mapped else universe
            # Derived portable GRO/XTCs keep source times; source trajectories never change.
            with mda.Writer(str(work/'surface.xtc'),n_atoms=len(universe.atoms)) as writer:
                for idx,frame in enumerate(reader.trajectory):
                    if mapped:
                        positions=carbohydrates.coordinates(model,frame.positions,scaled=label=='Mapped ring-scaled')
                        universe.atoms.positions=positions;universe.dimensions=frame.dimensions
                        universe.trajectory.ts.time=frame.time
                    if not np.isfinite(universe.atoms.positions).all(): raise ValueError('Nonfinite surface coordinates')
                    if idx==0:
                        first[label]=universe.atoms.positions.copy()/10
                        universe.atoms.write(str(work/'surface.gro'))
                    writer.write(universe.atoms)
            (work/'vdwradii.dat').write_text(''.join(f'{a.resname} {a.name} {r}\n' for a,r in zip(universe.atoms,radii)))
            cmd=[gmx,'sasa','-s','surface.gro','-f','surface.xtc','-o','sasa.xvg','-probe',str(PROBE),'-ndots','240','-surface','all','-output','all']
            result=subprocess.run(cmd,cwd=work,text=True,capture_output=True,timeout=300)
            (work/'sasa.log').write_text(result.stdout+result.stderr);commands.append({'cwd':str(work.relative_to(root)),'command':cmd,'exit_code':result.returncode})
            if result.returncode: raise RuntimeError(result.stderr[-2000:])
            dots=[gmx,'sasa','-s','surface.gro','-f','surface.gro','-o','snapshot-sasa.xvg','-q','connolly.pdb','-probe',str(PROBE),'-ndots','240','-surface','all','-output','all']
            result=subprocess.run(dots,cwd=work,text=True,capture_output=True,timeout=120)
            (work/'connolly.log').write_text(result.stdout+result.stderr);commands.append({'cwd':str(work.relative_to(root)),'command':dots,'exit_code':result.returncode})
            if result.returncode: raise RuntimeError(result.stderr[-2000:])
            values=np.array([[float(x) for x in line.split()[:2]] for line in (work/'sasa.xvg').read_text().splitlines() if line.strip() and not line.startswith(('#','@'))])
            if len(values)<2 or not np.isfinite(values).all(): raise ValueError('SASA requires at least two finite frames')
            stats[label]={'frames':len(values),'start_ps':float(values[0,0]),'end_ps':float(values[-1,0]),'mean_nm2':float(values[:,1].mean()),'std_nm2':float(values[:,1].std()),'xvg':str((work/'sasa.xvg').relative_to(root))}
        target=first['Mapped raw']
        first['Simulated CG']=align(first['Simulated CG'],target,physical)
        center=first['AA'].mean(axis=0)
        meshes={label:envelope(positions-center,variants[label][1]) for label,positions in first.items()}
        others=[k for k in variants if k!='AA']; count=len(others)
        fig=make_subplots(rows=1,cols=count,specs=[[{'type':'scene'}]*count],subplot_titles=[f'AA vs {k}' for k in others])
        colors={'AA':'#2864b5','Mapped raw':'#d95454','Mapped ring-scaled':'#e89123','Simulated CG':'#188b75'}
        for col,label in enumerate(others,1):
            for kind in ('AA',label):
                v,f=meshes[kind]
                fig.add_trace(go.Mesh3d(x=v[:,0],y=v[:,1],z=v[:,2],i=f[:,0],j=f[:,1],k=f[:,2],color=colors[kind],opacity=.45,name=kind,showlegend=kind!='AA' or col==1,legendgroup=kind),row=1,col=col)
            # Show the molecular structure inside the envelope: small atom markers
            # and bonds provide orientation while keeping the surface readable.
            aa_xyz=first['AA']-center
            fig.add_trace(go.Scatter3d(x=aa_xyz[:,0],y=aa_xyz[:,1],z=aa_xyz[:,2],mode='markers',
                marker={'size':3,'color':'#26384f','opacity':.9},name='AA atoms',showlegend=col==1,
                legendgroup='AA atoms',hoverinfo='skip'),row=1,col=col)
            if label != 'AA':
                cg_xyz=first[label]-center
                fig.add_trace(go.Scatter3d(x=cg_xyz[:,0],y=cg_xyz[:,1],z=cg_xyz[:,2],mode='markers',
                    marker={'size':5,'color':colors[label],'opacity':.95},name=f'{label} beads',showlegend=col==1,
                    legendgroup=f'{label} beads',hoverinfo='skip'),row=1,col=col)
        extent=max(np.max(np.abs(v)) for v,_ in meshes.values())+.1
        fig.update_scenes(aspectmode='cube',**{axis:{'title':axis[0]+' (nm)','range':[-extent,extent]} for axis in ('xaxis','yaxis','zaxis')})
        fig.update_layout(title='Solvent-accessible envelopes · probe 0.191 nm · drag to rotate',height=600,margin={'l':0,'r':0,'b':0,'t':65})
        sync="""const plot=document.getElementById('{plot_id}'); let updating=false;
plot.on('plotly_relayout',event=>{if(updating)return;const key=Object.keys(event).find(k=>/^scene[0-9]*\\.camera$/.test(k));if(!key)return; const changes={}; for(const s of Object.keys(plot.layout).filter(k=>/^scene[0-9]*$/.test(k)))changes[s+'.camera']=event[key]; updating=true;Plotly.relayout(plot,changes).finally(()=>updating=false);});"""
        path=output/'surface-comparison.html';fig.write_html(path,include_plotlyjs=True,post_script=sync)
        import html
        table='<table><tr><th>Model</th><th>Frames</th><th>Duration (ps)</th><th>Mean SASA (nm²)</th><th>SD (nm²)</th></tr>'+''.join(f'<tr><td>{html.escape(k)}</td><td>{v["frames"]}</td><td>{v["end_ps"]-v["start_ps"]:.1f}</td><td>{v["mean_nm2"]:.3f}</td><td>{v["std_nm2"]:.3f}</td></tr>' for k,v in stats.items())+'</table>'
        text=path.read_text();text=text.replace('</head>', '<style>body{font:15px/1.5 system-ui,sans-serif;color:#24344d;margin:16px}p{max-width:1100px}table{border-collapse:collapse;margin:18px 0}td,th{padding:8px 16px;text-align:left;border-bottom:1px solid #dbe2ea}th{background:#f1f5f9}</style></head>');text=text.replace('</body>','<p>Meshes show the union of probe-inflated spheres (SAS), not a re-entrant solvent-excluded surface. Original GROMACS Connolly dot files are downloadable separately. Simulated CG is fitted to the raw mapped first frame using massive sites. Local ring dilation is illustrative; inter-sugar fitting targets remain unscaled.</p>'+table+'<p>Statistics cover all supplied frames; SD is frame variability, not uncertainty of the mean. Short trajectories do not establish convergence. Paper comparisons averaged at least 200 ns.</p></body>');path.write_text(text)
        metadata={'probe_nm':PROBE,'AA_radii_nm':AA_RADII,'CG_radii_nm':carbohydrates.RADII_NM,'grid_spacing_nm':.04,'statistics':stats,'commands':commands,'scientifically_validated':False,'comparison_html':str(path.relative_to(root)),'rendering':'SAS mesh, GROMACS Connolly dots retained separately','source_sha256':{str(p.relative_to(root)):files.sha256(p) for p in [root/'2_mapping/model.json',root/'1_AA-reference/prod/lig.xtc',root/'4_CG_sim/prod/lig_CG.xtc']}}
        (output/'metadata.json').write_text(json.dumps(metadata,indent=2));return metadata
    finally:
        aa.trajectory.close();cg.trajectory.close()
