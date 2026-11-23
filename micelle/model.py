"""The detergent template every micelle geometry helper is handed."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DetergentTemplate:
 name:str; residue:str; beads:tuple; coordinates:Path; topology:Path; headgroup:tuple; tail_direction:tuple=(0,0,-1)
