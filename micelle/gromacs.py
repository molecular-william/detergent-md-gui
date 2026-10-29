import shutil
import subprocess
from pathlib import Path


def grompp(topology,coordinate,mdp,workdir,timeout=120):
 gmx=shutil.which('gmx')
 if not gmx:return {'status':'unavailable','error':'gmx executable not found'}
 cmd=[gmx,'grompp','-f',str(mdp),'-c',str(coordinate),'-p',str(topology),'-o',str(Path(workdir)/'validation.tpr'),'-maxwarn','0']
 r=subprocess.run(cmd,cwd=workdir,text=True,capture_output=True,timeout=timeout)
 return {'status':'passed' if r.returncode==0 else 'failed','returncode':r.returncode,'command':cmd,'stderr':r.stderr[-4000:]}
