import json
from pathlib import Path


def write_gro(path, atoms, title='Micelle', box=None):
 path=Path(path); atoms=list(atoms); lines=[title,str(len(atoms))]
 for i,a in enumerate(atoms,1):
  # The residue number is the caller's when it has one: a coarse-grained system has real residues (eight DDM
  # molecules, say), and writing the atom index there would claim every bead is its own molecule. Names are
  # truncated to the five-character field the format gives them, because a longer one shifts every column.
  residue_id = a.get('residue_id', i)
  lines.append(f'{residue_id%100000:5d}{a.get("residue","MCL")[:5]:<5}{a.get("name","B")[:5]:>5}{i%100000:5d}'+''.join(f'{float(x):8.3f}' for x in a['position']))
 b=[10,10,10] if box is None else box
 # One line, not one per value: a .gro's last line is the box vector, and three separate lines are not a box. A
 # rectangular cell keeps its three values; a shaped cell's three vectors write the nine values the format defines,
 # in its own order (v1x v2y v3z v1y v1z v2x v2z v3x v3y).
 if len(b) == 9:
  values=list(b)
 elif len(b)==3 and all(not hasattr(value,'__len__') for value in b):
  values=[b[0],b[1],b[2]]
 else:
  v1,v2,v3=b
  values=[v1[0],v2[1],v3[2],v1[1],v1[2],v2[0],v2[2],v3[0],v3[1]]
 lines.append(''.join(f'{float(x):10.5f}' for x in values));path.write_text('\n'.join(lines)+'\n');return path
def write_manifest(path,data): Path(path).write_text(json.dumps(data,indent=2,default=str))
