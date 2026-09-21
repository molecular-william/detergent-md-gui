"""Apply trajectory mean x 1.15 ring constraints before fitting flexible links."""
import json
from pathlib import Path
source = Path('../2_mapping/ring_targets.json')
if source.exists():
    targets = {tuple(x['atoms']):x['target_nm'] for x in json.loads(source.read_text())['constraints']}
    path = Path('DDM_initial.itp'); lines = path.read_text().splitlines(); section = ''; seen = set()
    for i,line in enumerate(lines):
        raw = line.split(';')[0].strip()
        if raw.startswith('['): section=raw.strip('[] ')
        elif raw and section == 'constraints':
            f=raw.split(); key=tuple(sorted(map(int,f[:2])))
            if key in targets: lines[i]=f'{f[0]} {f[1]} 1 {targets[key]:.6f}'; seen.add(key)
    if seen != targets.keys(): raise ValueError('Ring constraints do not match the mapped reference')
    # Preserve the coordinate-seeded topology and publish the AA-derived seed.
    path.rename('DDM_coordinate_seed.itp')
    path.write_text('\n'.join(lines)+'\n')
