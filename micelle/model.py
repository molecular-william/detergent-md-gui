from dataclasses import dataclass,asdict
from pathlib import Path
import json
@dataclass(frozen=True)
class DetergentTemplate:
 name:str; residue:str; beads:tuple; coordinates:Path; topology:Path; headgroup:tuple; tail_direction:tuple=(0,0,-1)
@dataclass
class BuildConfig:
 aggregation_number:int; seed:int; output:Path; detergent:DetergentTemplate; box_shape:str='cubic'; box_margin:float=2.; run_minimization:bool=False
class BuildManifest:
 def __init__(self,**kw): self.data=kw
 def write(self,path): path.write_text(json.dumps(self.data,indent=2,default=str))
