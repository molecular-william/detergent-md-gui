"""Post-fit correction; preserve the original FF topology and exact provenance."""
import hashlib
import json
from pathlib import Path
import bonded
import os

model_path = Path('../2_mapping/model.json')
model = json.loads(model_path.read_text())
# Read the temperature passed to ff_inter, recorded in its generated ITP header.
import re
path = Path(os.environ.get('FINAL_ITP', 'DDM.itp'))
original = path.read_text()
match = re.search(r'-temperature\s+([\d.]+)', original)
if not match: raise ValueError('Fitted topology has no recorded fitting temperature')
result, report = bonded.refine(original, model, Path('.'), float(match[1]))
preserved = Path(f'{path.stem}_ff_inter.itp')
if not preserved.exists():
    preserved.write_text(original)
report.update(source_sha256=hashlib.sha256(original.encode()).hexdigest(),
              fitted_sha256=hashlib.sha256(result.encode()).hexdigest(),
              model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest())
path.write_text(result)
Path('bonded_fit.json').write_text(json.dumps(report, indent=2)+'\n')
