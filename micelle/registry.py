import json
from pathlib import Path
from .model import DetergentTemplate
def load_template(path):
 d=json.loads(Path(path).read_text()); root=Path(path).parent
 for k in ('coordinates','topology'):
  if not (root/d[k]).is_file(): raise ValueError(f'missing template {k}')
 beads=tuple(d['beads']); names=[b['name'] for b in beads]
 if len(names)!=len(set(names)): raise ValueError('duplicate bead names')
 return DetergentTemplate(d['name'],d.get('residue',d['name']),beads,root/d['coordinates'],root/d['topology'],tuple(d.get('headgroup',(0,0,0))),tuple(d.get('tail_direction',(0,0,-1))))
def validate_template(t):
 e=[]
 if not t.beads:e.append('template has no beads')
 if not t.coordinates.is_file():e.append('coordinates missing')
 if not t.topology.is_file():e.append('topology missing')
 return e
