"""Mechanical validation of a short draft run, not scientific model approval."""
import json
import os
import re
from pathlib import Path

import MDAnalysis as mda
import numpy as np

root = Path.cwd().parent
aa_source=Path(os.environ.get('AA_REFERENCE_DIR',str(root/'1_AA-reference/prod')))
model = json.loads((root / '2_mapping/model.json').read_text())
result = {'purpose': 'draft-smoke', 'scientifically_validated': False, 'trajectories': {}}
for label, topology, trajectory, count in (
    # AA reference trajectories may include solvent; validate against the
    # topology actually produced by the run instead of a stale atom constant.
    ('AA ligand', aa_source/'lig.gro', aa_source/'lig.xtc', None),
    ('mapped', '2_mapping/mapped.gro', '2_mapping/mapped.xtc', len(model['beads'])),
    ('CG ligand', '4_CG_sim/prod/lig_CG.gro', '4_CG_sim/prod/lig_CG.xtc', len(model['beads'])),
):
    u = mda.Universe(str(root / topology), str(root / trajectory))
    minimum_frames = 2
    if (count is not None and len(u.atoms) != count) or len(u.atoms) == 0 or len(u.trajectory) < minimum_frames:
        raise ValueError(f'{label}: unexpected atom count or insufficient frames for a smoke test')
    times = []
    for frame in u.trajectory:
        if not np.isfinite(frame.positions).all():
            raise ValueError(f'{label}: nonfinite coordinates')
        times.append(float(frame.time))
    if not np.all(np.diff(times) > 0):
        raise ValueError(f'{label}: frame times must increase')
    result['trajectories'][label] = {'atoms': len(u.atoms), 'frames': len(times), 'start_ps': times[0], 'end_ps': times[-1]}
    u.trajectory.close()
# Independently verify that the mapper actually performed the exported heavy-atom COG. This is a separate script
# from the mapper on purpose: the check reconstructs the expected beads from the AA coordinates rather than trusting
# anything the mapper wrote about itself, so it catches a writer bug, a frame misalignment or a unit error.
aa = mda.Universe(str(aa_source/'lig.gro'),str(aa_source/'lig.xtc'))
cg = mda.Universe(str(root/'2_mapping/mapped.gro'), str(root/'2_mapping/mapped.xtc'))
if len(aa.trajectory) != len(cg.trajectory):
    raise ValueError('Mapping changed the frame count')
if list(cg.atoms.names) != [b['export_name'] for b in model['beads']]:
    raise ValueError('Mapping changed the bead order')
error = 0.0
for aaframe, cgframe in zip(aa.trajectory, cg.trajectory):
    if abs(float(aaframe.time)-float(cgframe.time)) > 1e-5:
        raise ValueError('Mapping changed frame times')
    # Independent construction verifies physical COGs and virtual parent COGs.
    expected = np.zeros((len(model['beads']),3))
    names = {b['name']:i for i,b in enumerate(model['beads'])}
    for i,b in enumerate(model['beads']):
        if not b.get('virtual_site'): expected[i] = aaframe.positions[np.array(b['atoms'])-1].mean(axis=0)
    for i,b in enumerate(model['beads']):
        if b.get('virtual_site'): expected[i] = expected[[names[n] for n in b['virtual_site']['parents']]].mean(axis=0)

    error = max(error, float(np.max(np.abs(expected-cgframe.positions))) / 10)
if error > 0.002:
    raise ValueError(f'the mapped trajectory differs from the exported COG by {error} nm')
result['mapping_max_coordinate_error_nm'] = error
aa.trajectory.close(); cg.trajectory.close()
for report in ('report_interactions.out', 'report_distances.out'):
    text = Path(report).read_text()
    if re.search(r'\b(?:nan|inf)\b', text, re.I):
        raise ValueError(f'{report}: nonfinite scores')
    if not re.search(r'Overall (?:Score|distance score)\s*:', text, re.I):
        raise ValueError(f'{report}: missing score summary')
    result[report] = text
result['mechanical_checks_passed'] = True
result['limitations'] = ['Sampling durations are recorded per trajectory; no convergence claim',
    'Draft bead types and short-trajectory bonded fit; no thermodynamic validation',
    'Neutral detergent in pure water; salt and aggregation validation deferred']
Path('validation.json').write_text(json.dumps(result, indent=2))
