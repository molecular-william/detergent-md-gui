from pathlib import Path
import re

def resolve_includes(topology,root):
 missing=[]
 for name in re.findall(r'^\s*#include\s+"([^"]+)"',Path(topology).read_text(),re.M):
  if not (Path(root)/name).is_file():missing.append(name)
 return missing

def write_topology(path,forcefield,detergent_itp,residue,count):
 path=Path(path);path.write_text(f'#include "{forcefield}"\n#include "{detergent_itp}"\n\n[ system ]\nDetergent micelle\n\n[ molecules ]\n{residue:<16} {count}\n')
