"""Which files a kind is handed, resolved the way the analysis subprocess resolves them.

`bartender-fit` declares its atomistic pair as `1_AA-reference/prod/lig.{gro,xtc}`, a name no consumer run holds:
a CG run's own `stages/1_AA-reference/` contains only its stage script, and the trajectory it was fitted against
lives in the *paired* AA run under `stages/07_reference/`. `worker.source_entries` substitutes the consumer
manifest's `shared_reference` for a kind that reads one and stages the reference's two files under that declared
name, which is the role the producer looks for inside its work directory.

These build the workspace they read -- a reference run and the CG run that names it -- rather than touching the
developer's `workspace/`.
"""
import json

from dashboard import files
from dashboard.analysis import worker
from dashboard.execution import workflow

REFERENCE_ID = 'a1a1a1a1a1a1'


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _reference_run(runs_root):
    """A completed AA-only run's published reference, and the checksums a consumer records to attach it."""
    run = runs_root / REFERENCE_ID
    staged = {'stages/07_reference/lig.gro': b'LIG1     1\n    1LIG     C1    1   0.000   0.000   0.000\n',
              'stages/07_reference/lig.xtc': b'GROMACS xtc placeholder\n'}
    for relative, content in staged.items():
        _write(run / relative, content)
    document = {'reference_eligible': True,
                'sha256': {relative: files.sha256(run / relative) for relative in staged}}
    files.atomic_json(run / 'stages/07_reference/reference.json', document)
    files.atomic_json(run / 'manifest.json', {'run_type': 'aa_only', 'status': 'completed', 'stages': []})
    expected = dict(document['sha256'])
    expected['stages/07_reference/reference.json'] = files.sha256(run / 'stages/07_reference/reference.json')
    return run, expected


def _consumer_run(runs_root, expected=None):
    """An AA-CG run: its own stages, and -- when `expected` is given -- the reference run it was fitted against."""
    run = runs_root / 'b2b2b2b2b2b2'
    _write(run / 'stages/1_AA-reference/aa_reference.sh', b'#!/bin/bash\nexit 0\n')
    _write(run / 'stages/2_mapping/model.json', b'{"beads": []}\n')
    _write(run / 'stages/2_mapping/mapping.ndx', b'[ LIG1 ]\n1\n')
    _write(run / 'stages/3_initial_CG/LIG1.itp', b'[ moleculetype ]\nLIG1 1\n')
    manifest = {'run_type': 'aa_cg', 'status': 'completed', 'stages': []}
    if expected is not None:
        manifest['shared_reference'] = {'source_run_id': REFERENCE_ID, 'sha256': expected}
    files.atomic_json(run / 'manifest.json', manifest)
    return run


def test_bartender_fit_is_handed_the_shared_references_own_trajectory(tmp_path):
    """The declared pair names the reference's files, staged under the role the producer reads them by."""
    reference, expected = _reference_run(tmp_path)
    consumer = _consumer_run(tmp_path, expected)

    entries = worker.source_entries(workflow.execution_root(consumer), 'bartender-fit')

    assert entries['1_AA-reference/prod/lig.gro'] == reference / 'stages/07_reference/lig.gro'
    assert entries['1_AA-reference/prod/lig.xtc'] == reference / 'stages/07_reference/lig.xtc'
    assert sorted(path.name for path in (consumer / 'stages/1_AA-reference').iterdir()) == ['aa_reference.sh'], \
        'the consumer run holds no atomistic trajectory of its own, so the substitution is the only source'
    assert entries['2_mapping/model.json'] == consumer / 'stages/2_mapping/model.json'
    assert entries['2_mapping/mapping.ndx'] == consumer / 'stages/2_mapping/mapping.ndx'
    assert entries['3_initial_CG/LIG1.itp'] == consumer / 'stages/3_initial_CG/LIG1.itp'


def test_without_a_shared_reference_the_declared_aa_pair_resolves_to_nothing(tmp_path):
    """The same run, minus the attachment: the two names are supplied by the substitution and by nothing else."""
    consumer = _consumer_run(tmp_path)

    entries = worker.source_entries(workflow.execution_root(consumer), 'bartender-fit')

    assert '1_AA-reference/prod/lig.gro' not in entries
    assert '1_AA-reference/prod/lig.xtc' not in entries
    assert json.loads((consumer / 'manifest.json').read_text()).get('shared_reference') is None
