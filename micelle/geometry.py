import numpy as np

def candidate_score(point, protein, axis=(0,0,1), span=(-1,1), radius=3., min_distance=.25):
 p=np.asarray(protein,float)
 if not len(p): return {'score':1.,'clash':False,'exposure':1.}
 c=np.asarray(point); d=np.linalg.norm(p-c,axis=1); clash=bool(d.min()<min_distance)
 axial=np.dot(p-p.mean(0),np.asarray(axis)/np.linalg.norm(axis)); belt=((axial>=span[0])&(axial<=span[1]))
 coverage=float(belt.mean()); exposure=float((~belt).mean())
 return {'score':coverage+exposure*.25-(10 if clash else 0), 'clash':clash,'coverage':coverage,'exposure':exposure}

def box_for(positions, margin=2., shape='cubic', dimensions=None):
 p=np.asarray(positions,float); ext=p.max(0)-p.min(0)+2*margin if len(p) else np.ones(3)*2*margin
 if dimensions is not None: ext=np.asarray(dimensions,float)
 if shape not in ('cubic','rectangular'): raise ValueError('box shape must be cubic or rectangular')
 if shape=='cubic': ext=np.ones(3)*max(ext)
 return ext
