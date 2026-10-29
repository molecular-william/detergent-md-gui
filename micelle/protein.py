import shutil
import subprocess
from pathlib import Path


def martinize2(atomistic,output,extra=()):
 exe=shutil.which('martinize2') or shutil.which('martinize.py')
 if not exe: return {'status':'unavailable','error':'martinize2 executable not found'}
 cmd=[exe,'-f',str(atomistic),'-x',str(Path(output)/'protein-CG.pdb'),'-o',str(Path(output)/'protein.top'),*extra]
 r=subprocess.run(cmd,cwd=output,text=True,capture_output=True)
 return {'status':'passed' if r.returncode==0 else 'failed','returncode':r.returncode,'command':cmd,'stderr':r.stderr[-4000:]}
