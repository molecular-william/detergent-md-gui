import numpy as np


def golden_angle_directions(count,seed):
 if count<1: return np.empty((0,3))
 rng=np.random.default_rng(seed); phase=float(rng.uniform(0,2*np.pi)); i=np.arange(count)+.5; z=1-2*i/count; a=np.pi*(3-np.sqrt(5))*i+phase
 return np.c_[np.sqrt(1-z*z)*np.cos(a),np.sqrt(1-z*z)*np.sin(a),z]
def pack_micelle(protein,template,aggregation_number,seed,radius=3.):
 dirs=golden_angle_directions(aggregation_number,seed); p=np.asarray(protein) if protein is not None else np.zeros((0,3));
 if len(p): center=p.mean(0); dirs=dirs[np.argsort([min(np.linalg.norm(center+radius*d-p,axis=1)) for d in dirs])]
 centers=(p.mean(0) if len(p) else np.zeros(3))+radius*dirs
 return centers,dirs
def minimum_distance(points):
 if len(points)<2:return float('inf')
 d=points[:,None,:]-points[None,:,:]; d[np.arange(len(points)),np.arange(len(points))]=np.inf
 return float(np.sqrt((d*d).sum(2)).min())
