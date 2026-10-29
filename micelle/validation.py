import json
from pathlib import Path

import numpy as np


def validate_positions(centers,aggregation_number,min_distance=.25):
 c=np.asarray(centers); issues=[]
 if not np.isfinite(c).all(): issues.append('nonfinite coordinates')
 if len(c)!=aggregation_number: issues.append(f'aggregation count {len(c)} != {aggregation_number}')
 if len(c)>1:
  d=c[:,None,:]-c[None,:,:]; d[np.arange(len(c)),np.arange(len(c))]=np.inf
  md=float(np.sqrt((d*d).sum(2)).min())
  if md<min_distance: issues.append(f'detergent overlap: minimum {md:.3f} nm')
 else: md=None
 return {'valid':not issues,'issues':issues,'aggregation_number':len(c),'minimum_distance_nm':md}
def write_report(report,out):
 Path(out).mkdir(parents=True,exist_ok=True);Path(out,'validation.json').write_text(json.dumps(report,indent=2));Path(out,'validation.md').write_text('# Micelle validation\n\n'+('\n'.join('- '+x for x in report['issues']) if report['issues'] else 'All geometry gates passed.')+'\n')
