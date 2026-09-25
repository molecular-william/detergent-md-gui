"""Preserve source frame times/boxes when exporting bundled Fast_Forward output.

The bundled ff_map writes a new MemoryReader with dt=1 ps and writes its final
frame as the .gro. Keep that raw output and explicitly restore the source frame
metadata; coordinates must pass an independent heavy-atom COG comparison.
"""
import json
import os
from pathlib import Path

import MDAnalysis as mda
import numpy as np

root = Path.cwd().parent
model = json.loads(Path('model.json').read_text())
aa_source=Path(os.environ.get('AA_REFERENCE_DIR',str(root/'1_AA-reference/prod')))
aa = mda.Universe(str(aa_source/'lig.gro'),str(aa_source/'lig.xtc'))
cg = mda.Universe('mapped_raw.gro', 'mapped_raw.xtc')
if len(aa.trajectory) != len(cg.trajectory):
    raise ValueError('ff_map changed the number of frames')
if list(cg.atoms.names) != [b['export_name'] for b in model['beads']]:
    raise ValueError('ff_map changed the bead order')
if Path('mapped.xtc').exists() or Path('mapped.gro').exists():
    raise FileExistsError('Refusing to overwrite a previous mapped trajectory')
max_error_nm = 0.0
with mda.Writer('mapped.xtc', n_atoms=len(cg.atoms)) as writer:
    for index, (aa_frame, cg_frame) in enumerate(zip(aa.trajectory, cg.trajectory)):
        expected = np.array([aa_frame.positions[np.array(b['atoms'])-1].mean(axis=0) for b in model['beads']])
        if not np.isfinite(cg_frame.positions).all():
            raise ValueError('ff_map produced nonfinite coordinates')
        error_nm = float(np.max(np.abs(expected-cg_frame.positions))) / 10
        max_error_nm = max(max_error_nm, error_nm)
        if error_nm > 0.002:
            raise ValueError(f'ff_map coordinate mismatch at frame {index}: {error_nm} nm')
        cg_frame.time = float(aa_frame.time)
        cg_frame.dimensions = aa_frame.dimensions.copy()
        writer.write(cg.atoms)
        if index == 0:
            cg.atoms.write('mapped.gro')
Path('mapping_validation.json').write_text(json.dumps({
    'source_trajectory': str(aa_source/'lig.xtc'),
    'raw_ff_output': 'mapped_raw.xtc', 'frames': len(aa.trajectory),
    'max_coordinate_error_nm': max_error_nm,
    'adjustments': ['Frame times and boxes copied from the matching AA frames', 'mapped.gro is the first frame'],
    'scientifically_validated': False,
}, indent=2))
