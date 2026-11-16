"""Mechanical validation of a short draft run, not scientific model approval.

Run as a repository module (`"$PYTHON" -m dashboard.execution.scripts.validate_run`) from the stage directory it
checks; the stage directory is the working directory, so the run it validates is its parent.
"""
import json
import os
import re
from pathlib import Path

import MDAnalysis as mda
import numpy as np

#: The topology sections `ff_assess` scores in its interaction report. A molecule whose geometry is held by
#: `[ constraints ]` alone -- a rigid ring, no bond, angle or dihedral -- has nothing for that half of the report to
#: score, and the tool prints `nan` for the mean of an empty set. That is not a comparison that failed.
BONDED_SECTIONS = ('bonds', 'angles', 'dihedrals')


def bonded_sections(path):
    """The bonded sections `path` declares rows for, or `None` when the file cannot be read.

    `None` is not the empty set: a topology nobody could read is a reason to keep the strict check, so the caller
    reads it as "expect a scored interaction report" rather than as a molecule with nothing to score.
    """
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return None
    found, section = set(), None
    for line in lines:
        clean = line.split(';', 1)[0].strip()
        if not clean:
            continue
        if clean.startswith('['):
            section = clean.strip('[] \t')
            continue
        if section in BONDED_SECTIONS:
            found.add(section)
    return found


def scored_topology():
    """The ITP `ff_assess -i` was handed, from the two variables `assess.sh` sets: `INITIAL_DIR` and `INITIAL_ITP`.

    A run hands `../3_initial_CG` and its own initial ITP; a re-score hands the attempt's own pair. A caller that
    names no ITP is answered `None`, which keeps the strict check without guessing at a default name.
    """
    name = os.environ.get('INITIAL_ITP')
    return None if not name else Path(os.environ.get('INITIAL_DIR') or '../3_initial_CG') / name


def main(root=None, aa_source=None):
    root = Path(root) if root is not None else Path.cwd().parent
    aa_source = (Path(aa_source) if aa_source is not None
                 else Path(os.environ.get('AA_REFERENCE_DIR', str(root / '1_AA-reference/prod'))))
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
        result['trajectories'][label] = {'atoms': len(u.atoms), 'frames': len(times),
                                         'start_ps': times[0], 'end_ps': times[-1]}
        u.trajectory.close()
    # Independently verify that the mapper actually performed the exported heavy-atom COG. This is a separate script
    # from the mapper on purpose: the check reconstructs the expected beads from the AA coordinates rather than
    # trusting anything the mapper wrote about itself, so it catches a writer bug, a frame misalignment or a unit error.
    aa = mda.Universe(str(aa_source/'lig.gro'), str(aa_source/'lig.xtc'))
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
        expected = np.zeros((len(model['beads']), 3))
        names = {b['name']: i for i, b in enumerate(model['beads'])}
        for i, b in enumerate(model['beads']):
            if not b.get('virtual_site'):
                expected[i] = aaframe.positions[np.array(b['atoms'])-1].mean(axis=0)
        for i, b in enumerate(model['beads']):
            if b.get('virtual_site'):
                expected[i] = expected[[names[n] for n in b['virtual_site']['parents']]].mean(axis=0)

        error = max(error, float(np.max(np.abs(expected-cgframe.positions))) / 10)
    if error > 0.002:
        raise ValueError(f'the mapped trajectory differs from the exported COG by {error} nm')
    result['mapping_max_coordinate_error_nm'] = error
    aa.trajectory.close(); cg.trajectory.close()
    # The interaction report is only required to be finite when the topology that was scored has something for it to
    # score: `ff_assess` prints `nan` for the mean of an empty per-type set, and a constraint-only ring has no bond,
    # angle or dihedral. The answer is read from the ITP the tool was handed, never from the report, so a model that
    # does have bonded terms and still got `nan` -- a baseline that does not cover them -- keeps failing.
    topology = scored_topology()
    bonded = bonded_sections(topology) if topology is not None else None
    for report in ('report_interactions.out', 'report_distances.out'):
        text = Path(report).read_text()
        if re.search(r'\b(?:nan|inf)\b', text, re.I):
            unscored = report == 'report_interactions.out' and bonded is not None and not bonded
            if not unscored:
                raise ValueError(f'{report}: nonfinite scores')
            result['interaction_scores'] = {
                'scored': False,
                'topology': str(topology),
                'reason': ('the topology this assessment scored declares no bond, angle or dihedral rows -- its '
                           'geometry is held by constraints -- so `ff_assess` had no interaction to compare and '
                           'reported `nan` for an empty set'),
            }
        if not re.search(r'Overall (?:Score|distance score)\s*:', text, re.I):
            raise ValueError(f'{report}: missing score summary')
        result[report] = text
    result['mechanical_checks_passed'] = True
    result['limitations'] = ['Sampling durations are recorded per trajectory; no convergence claim',
                             'Draft bead types and short-trajectory bonded fit; no thermodynamic validation',
                             'Neutral detergent in pure water; salt and aggregation validation deferred']
    Path('validation.json').write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
