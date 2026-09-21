from dataclasses import dataclass
import numpy as np
@dataclass(frozen=True)
class OrientationReport:
 axis:tuple; span:tuple; method:str; confidence:float; evidence:tuple

def infer_orientation(positions, opm=None, explicit_axis=None, explicit_span=None):
 if opm is not None:
  axis=np.asarray(opm.get('axis',(0,0,1)),float);method='opm';conf=1.;ev=('OPM metadata',)
 elif explicit_axis is not None:
  axis=np.asarray(explicit_axis,float);method='explicit';conf=.9;ev=('explicit axis',)
 else:
  p=np.asarray(positions,float); _,_,v=np.linalg.svd(p-p.mean(0),full_matrices=False);axis=v[0];method='heuristic';conf=.35;ev=('principal-axis fallback',)
 axis=axis/np.linalg.norm(axis); span=explicit_span or (-1.,1.)
 return OrientationReport(tuple(axis),tuple(span),method,conf,ev)
