from pathlib import Path
import json
from .geometry import box_for
def write_gro(path, atoms, title='Micelle', box=None):
 path=Path(path); atoms=list(atoms); lines=[title,str(len(atoms))]
 for i,a in enumerate(atoms,1):
  # The residue number is the caller's when it has one: a coarse-grained system has real residues (eight DDM
  # molecules, say), and writing the atom index there would claim every bead is its own molecule.
  residue_id = a.get('residue_id', i)
  lines.append(f'{residue_id%100000:5d}{a.get("residue","MCL"):<5}{a.get("name","B"):>5}{i%100000:5d}'+''.join(f'{float(x):8.3f}' for x in a['position']))
 b=[10,10,10] if box is None else box
 # One line, not one per value: a .gro's last line is the box vector, and three separate lines are not a box.
 lines.append(''.join(f'{x:10.5f}' for x in b));path.write_text('\n'.join(lines)+'\n');return path
def write_manifest(path,data): Path(path).write_text(json.dumps(data,indent=2,default=str))
