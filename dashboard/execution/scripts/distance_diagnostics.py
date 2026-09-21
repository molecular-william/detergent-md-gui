"""Pair distances against raw AA and expanded geometry, with ring terms separated.

Wasserstein distances are in nm, not Fast_Forward's unitless score. Expansion
is a design target; neither comparison alone establishes physical validation.
"""
import json
from pathlib import Path
import numpy as np
import MDAnalysis as mda
from scipy.stats import wasserstein_distance

def write_matrix_plot(result, path):
    """Write a physical-pair Wasserstein matrix; virtual-site pairs are masked."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    names = sorted({name for pair in result['pairs'] for name in pair['beads']}, key=lambda x: int(''.join(c for c in x if c.isdigit()) or 0))
    index = {name:i for i,name in enumerate(names)}
    matrix = np.full((len(names),len(names)), np.nan)
    for i in range(len(names)): matrix[i,i]=0.0
    for pair in result['pairs']:
        if pair['kind']=='virtual_site_diagnostic': continue
        a,b=pair['beads']; value=pair['wasserstein_nm'].get('ring_expanded_AA', pair['wasserstein_nm']['raw_AA'])
        matrix[index[a],index[b]]=matrix[index[b],index[a]]=value
    fig, ax = plt.subplots(figsize=(7.2,6.2), constrained_layout=True)
    masked=np.ma.masked_invalid(matrix); image=ax.imshow(masked, cmap='viridis', vmin=0, vmax=max(.1,float(np.nanmax(matrix))))
    ax.set_xticks(range(len(names)),names,rotation=45,ha='right'); ax.set_yticks(range(len(names)),names)
    ax.set_title('Stratified physical distance matrix\nWasserstein distance (nm); lower is better')
    for i in range(len(names)):
        for j in range(len(names)):
            if np.isfinite(matrix[i,j]): ax.text(j,i,f'{matrix[i,j]:.3f}',ha='center',va='center',fontsize=7,color='white' if matrix[i,j]>.05 else 'black')
    fig.colorbar(image, ax=ax, label='Wasserstein distance (nm)')
    fig.savefig(path,dpi=160); plt.close(fig); return True


def compare(root):
    model = json.loads((root/'2_mapping/model.json').read_text())
    n = len(model['beads']); left,right = np.triu_indices(n,1)
    def distances(gro,xtc):
        universe = mda.Universe(str(gro), str(xtc))
        try:
            values = np.array([np.linalg.norm(ts.positions[left]-ts.positions[right],axis=1)/10 for ts in universe.trajectory])
            if not np.isfinite(values).all(): raise ValueError('Nonfinite pair distances')
            return values
        finally: universe.trajectory.close()
    raw = distances(root/'2_mapping/mapped.gro',root/'2_mapping/mapped.xtc')
    cg = distances(root/'4_CG_sim/prod/lig_CG.gro',root/'4_CG_sim/prod/lig_CG.xtc')
    refs = {'raw_AA':raw}
    if (root/'2_mapping/mapped_scaled.xtc').exists():
        refs['ring_expanded_AA'] = distances(root/'2_mapping/mapped_scaled.gro',root/'2_mapping/mapped_scaled.xtc')
    rings = [set(r['beads']+[r['virtual_site']]) for r in model.get('rings',[])]
    export = {b['name']: b.get('export_name', b['name']) for b in model['beads']}
    virtual = {b['name'] for b in model['beads'] if b.get('virtual_site')}
    constrained = set()
    itp = root/'3_initial_CG/DDM_initial.itp'
    section = None
    if itp.is_file():
        for raw_line in itp.read_text().splitlines():
            line = raw_line.split(';', 1)[0].strip()
            if line.startswith('['): section = line.strip('[] ').lower(); continue
            if section == 'constraints' and line:
                fields = line.split()
                if len(fields) >= 2:
                    try: constrained.add(tuple(sorted((int(fields[0]), int(fields[1])))))
                    except ValueError: pass
    pairs=[]
    for k,(i,j) in enumerate(zip(left,right)):
        a,b = model['beads'][i]['name'],model['beads'][j]['name']
        group = 'within_ring' if any({a,b} <= r for r in rings) else 'between_rings_and_tail'
        is_virtual = a in virtual or b in virtual
        pair_kind = 'virtual_site_diagnostic' if is_virtual else ('constrained_physical' if tuple(sorted((i+1,j+1))) in constrained else 'physical')
        pairs.append({'beads':[export.get(a,a),export.get(b,b)], 'model_beads':[a,b], 'group':group, 'kind':pair_kind,
                      'wasserstein_nm':{name:float(wasserstein_distance(values[:,k],cg[:,k])) for name,values in refs.items()}})
    groups = {group:{name:float(np.mean([p['wasserstein_nm'][name] for p in pairs if p['group']==group])) for name in refs} for group in sorted({p['group'] for p in pairs})}
    stratified = {kind:{name:float(np.mean([p['wasserstein_nm'][name] for p in pairs if p['kind']==kind])) for name in refs}
                  for kind in sorted({p['kind'] for p in pairs})}
    return {'metric':'Wasserstein distance (nm); lower is closer', 'frames':{'CG':len(cg), **{k:len(v) for k,v in refs.items()}}, 'group_means_nm':groups,
            'stratified_means_nm':stratified, 'pair_counts':{kind:sum(p['kind']==kind for p in pairs) for kind in sorted({p['kind'] for p in pairs})}, 'pairs':pairs,
            'interpretation':'Raw AA includes deliberate 15% ring expansion mismatch. Expanded geometry is a design target, not independent experimental validation.'}


if __name__=='__main__':
    result=compare(Path('..'))
    Path('distance_diagnostics.json').write_text(json.dumps(result,indent=2)+'\n')
    Path('distance_diagnostics_stratified.json').write_text(json.dumps(result,indent=2)+'\n')
    write_matrix_plot(result, Path('distance_matrix_stratified_DDM.png'))
