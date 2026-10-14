"""A run with nothing to sample skips; a run with a trajectory publishes frames.

The producer refuses a run with no trajectory in its own words (`layout.NoTrajectory`, a `ValueError`). That refusal
is not a failure: what the analysis subprocess does about it is the workflow contract's *skip* -- exit 4 with
`skip.json` beside the request -- and the coordinator records `skipped` from it (`test_default_analyses.py` pins that
half). These drive the subprocess's own entry point, because that is where the contract is decided.

The frames case is here too, so the two outcomes sit side by side: the same kind, the same entry point, and the only
difference is whether the run holds a trajectory.
"""
import json

import pytest

from dashboard import files
from dashboard.analysis import worker
from dashboard.execution import workflow


def _request(root, kind='snapshots'):
    """A request where the coordinator writes one: `<attempt>/request.json`, naming the run."""
    attempt = root / 'analyses' / kind / 'signature' / 'attempt'
    attempt.mkdir(parents=True, exist_ok=True)
    path = attempt / 'request.json'
    path.write_text(json.dumps({'run': str(root), 'kind': kind, 'payload': {}, 'code_signature': 'signature',
                                'dependencies': {}}))
    return path


def _aa_only_run(root, frames=5, atoms=4):
    """A completed AA-only run's own layout: a published reference under `stages/07_reference/`.

    The manifest and the reference document are the two files the kind's sources are resolved through
    (`analysis.source_entries` verifies an AA-only run's reference before staging it), and the trajectory is a real
    one, so what the frames hold is the trajectory's own coordinates rather than a placeholder.
    """
    import MDAnalysis as mda
    import numpy as np

    reference = root / 'stages/07_reference'
    reference.mkdir(parents=True)
    universe = mda.Universe.empty(atoms, n_residues=1, atom_resindex=[0] * atoms, trajectory=True)
    universe.add_TopologyAttr('names', [f'C{index:02d}' for index in range(1, atoms + 1)])
    universe.add_TopologyAttr('resnames', ['LIG'])
    universe.add_TopologyAttr('resids', [1])
    base = np.arange(atoms * 3, dtype=float).reshape(atoms, 3) * 10.0
    with mda.Writer(str(reference / 'lig.xtc'), n_atoms=atoms) as writer:
        for frame in range(frames):
            universe.atoms.positions = base + frame * 10.0
            if frame == 0:
                universe.atoms.write(str(reference / 'lig.gro'))
            writer.write(universe.atoms)
    files.atomic_json(root / 'manifest.json', {'run_type': 'aa_only', 'status': 'completed', 'stages': []})
    files.atomic_json(reference / 'reference.json', {
        'reference_eligible': True,
        'sha256': {f'stages/07_reference/{name}': files.sha256(reference / name)
                   for name in ('lig.gro', 'lig.xtc')}})
    return root


def test_a_run_with_nothing_to_sample_skips_with_the_producers_own_reason(tmp_path):
    run = tmp_path / 'run'
    (run / 'stages').mkdir(parents=True)
    request = _request(run)

    with pytest.raises(SystemExit) as stopped:
        worker.execute(request)

    assert stopped.value.code == workflow.SKIPPED_EXIT_CODE
    record = json.loads((request.parent / 'skip.json').read_text())
    assert record['kind'] == 'snapshots'
    assert 'no trajectory to review' in record['reason']
    assert not (request.parent / 'result.json').exists(), 'a skip is not a published attempt'


def test_a_run_with_a_trajectory_publishes_its_frames_through_the_same_kind(tmp_path):
    """One run chooses: the atomistic reference it published is what a frame is drawn from.

    The layout is an AA-only run's own (`stages/07_reference/`), because that is the shape six of the eight runs
    in the workspace are written in -- and the reference is staged under the role the kind asks for, so this also
    pins that the kind's sources reach the producer.
    """
    run = tmp_path / 'run'
    _aa_only_run(run, frames=5, atoms=4)
    request = _request(run)

    worker.execute(request)

    published = json.loads((request.parent / 'result.json').read_text())
    output = request.parent / published['output_directory']
    assert published['result']['role'] == 'aa_trajectory'
    assert published['result']['trajectory'] == '1_AA-reference/prod/lig.xtc'
    frames = sorted(path.name for path in (output / 'snapshots').glob('*'))
    assert {'AA-first.pdb', 'AA-first.svg', 'AA-last.pdb', 'AA-last.svg', 'AA-frames.pdb'} <= set(frames)
    assert {'snapshots/AA-first.pdb', 'snapshots/AA-frames.pdb'} <= set(published['outputs_sha256'])
