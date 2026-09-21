import numpy as np
from .geometry import candidate_score
def repack(points, directions, protein, radius, aggregation_number, seed, axis=(0,0,1), span=(-1,1)):
 rng=np.random.default_rng(seed); p=np.asarray(protein,float); center=p.mean(0) if len(p) else np.zeros(3)
 chosen=[]
 for d in directions:
  c=center+radius*d; s=candidate_score(c,p,axis,span,.25)
  if not s['clash']: chosen.append(c)
  if len(chosen)==aggregation_number:return np.asarray(chosen),{'replacements':0,'exact':True}
 # deterministic local radial expansion and unused directions
 for scale in np.linspace(1.05,1.8,16):
  for d in directions:
   c=center+radius*scale*d
   if not candidate_score(c,p,axis,span,.25)['clash'] and (not chosen or np.min(np.linalg.norm(np.asarray(chosen)-c,axis=1))>.25): chosen.append(c)
   if len(chosen)==aggregation_number:return np.asarray(chosen),{'replacements':len(chosen),'exact':True}
 return np.asarray(chosen),{'replacements':len(chosen),'exact':False}
