"""Which files a kind is handed, resolved the way the analysis subprocess resolves them.

`bartender-fit` declares its atomistic pair as `1_AA-reference/prod/lig.{gro,xtc}`, a name no consumer run holds:
a CG run's own `stages/1_AA-reference/` contains only its stage script, and the trajectory it was fitted against
lives in the *paired* AA run under `stages/07_reference/`. `worker.source_entries` substitutes the consumer
manifest's `shared_reference` for a kind that reads one and stages the reference's two files under that declared
name, which is the role the producer looks for inside its work directory.

These build the workspace they read -- a reference run and the CG run that names it -- rather than touching the
developer's `workspace/`. A consumer that no longer has its reference run is answered from the one copy the run
keeps under `sources/`, or -- for an attempt the previous lane published -- from that attempt's own copy.
"""
import json
import shutil

import pytest
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
    document = {'reference_eligible': True, 'edition': 1, 'molecule': 'LIG1',
                'sha256': {relative: files.sha256(run / relative) for relative in staged}}
    files.atomic_json(run / 'stages/07_reference/reference.json', document)
    files.atomic_json(run / 'manifest.json', {'run_type': 'aa_only', 'status': 'completed', 'stages': []})
    return run, document['edition']


def _consumer_run(runs_root, expected=None):
    """An AA-CG run: its own stages, and -- when `expected` is given -- the reference run it was fitted against."""
    run = runs_root / 'b2b2b2b2b2b2'
    _write(run / 'stages/1_AA-reference/aa_reference.sh', b'#!/bin/bash\nexit 0\n')
    _write(run / 'stages/2_mapping/model.json', b'{"beads": []}\n')
    _write(run / 'stages/2_mapping/mapping.ndx', b'[ LIG1 ]\n1\n')
    _write(run / 'stages/3_initial_CG/LIG1.itp', b'[ moleculetype ]\nLIG1 1\n')
    manifest = {'run_type': 'aa_cg', 'status': 'completed', 'stages': []}
    if expected is not None:
        manifest['shared_reference'] = {'source_run_id': REFERENCE_ID, 'edition': expected}
    files.atomic_json(run / 'manifest.json', manifest)
    return run


def test_bartender_fit_is_handed_the_shared_references_own_trajectory(tmp_path):
    """The declared pair names the reference's files, staged under the role the producer reads them by."""
    reference, expected = _reference_run(tmp_path)
    consumer = _consumer_run(tmp_path, expected)

    entries = worker.source_entries(workflow.stage_root(consumer), 'bartender-fit')

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

    entries = worker.source_entries(workflow.stage_root(consumer), 'bartender-fit')

    assert '1_AA-reference/prod/lig.gro' not in entries
    assert '1_AA-reference/prod/lig.xtc' not in entries
    assert json.loads((consumer / 'manifest.json').read_text()).get('shared_reference') is None

def _attempt_copy(consumer, name, reference):
    """An attempt copy the previous lane published, named as it recorded the outside source."""
    target = consumer / 'analyses' / 'bartender-fit' / '0001-20261001' / 'sources' / \
        f'shared/{REFERENCE_ID}/stages/07_reference' / name
    _write(target, (reference / 'stages/07_reference' / name).read_bytes())
    return target


def test_a_run_copied_without_its_reference_stages_an_earlier_attempts_copy(tmp_path):
    """The reference run did not travel; a copy the previous lane's attempt recorded is what this run reads now.

    The copy keeps the name that attempt recorded, and is promoted to the run's own `sources/` copy, so a later
    attempt records a run-relative name instead of nesting the attempt path it now sits under.
    """
    reference, expected = _reference_run(tmp_path)
    consumer = _consumer_run(tmp_path, expected)
    copies = {name: _attempt_copy(consumer, name, reference) for name in ('lig.gro', 'lig.xtc')}
    shutil.rmtree(reference)

    entries = worker.source_entries(workflow.stage_root(consumer), 'bartender-fit')

    for name, copy in copies.items():
        assert entries[f'1_AA-reference/prod/{name}'] == copy
        assert worker._source_provenance(consumer, copy) == \
            f'sources/shared/{REFERENCE_ID}/stages/07_reference/{name}'


def test_a_run_that_kept_the_reference_copy_answers_from_its_own_sources(tmp_path):
    """Only the run travelled: the one copy it keeps under `sources/` is the whole reference the consumer needs."""
    reference, expected = _reference_run(tmp_path)
    consumer = _consumer_run(tmp_path, expected)
    staged = {}
    for name in ('lig.gro', 'lig.xtc'):
        target = consumer/'sources'/'shared'/REFERENCE_ID/'stages'/'07_reference'/name
        _write(target, (reference/'stages/07_reference'/name).read_bytes())
        staged[name] = target
    shutil.rmtree(reference)

    entries = worker.source_entries(workflow.stage_root(consumer), 'bartender-fit')

    for name, copy in staged.items():
        assert entries[f'1_AA-reference/prod/{name}'] == copy
        assert worker._source_provenance(consumer, copy) == \
            f'sources/shared/{REFERENCE_ID}/stages/07_reference/{name}'


def test_the_queue_charges_the_runs_copy_of_an_outside_source_once(tmp_path):
    """Admission counts the durable copy an outside source needs, and nothing for one the run already holds."""
    reference, expected = _reference_run(tmp_path)
    consumer = _consumer_run(tmp_path, expected)
    entries = worker.source_entries(workflow.stage_root(consumer), 'bartender-fit')
    external = [path for name, path in entries.items() if name.startswith('1_AA-reference/')]
    assert worker.source_copy_bytes(consumer, entries) == sum(path.stat().st_size for path in external)

    for path in external:
        _write(consumer/'sources'/'shared'/REFERENCE_ID/'stages'/'07_reference'/path.name, path.read_bytes())

    assert worker.source_copy_bytes(consumer, entries) == 0, \
        'the run already holds both files, so a second attempt is charged no durable bytes'


def test_a_copied_run_with_no_copy_of_its_reference_names_the_missing_run(tmp_path):
    """An absent reference run and no recorded copy is the refusal it always was, naming both facts."""
    reference, expected = _reference_run(tmp_path)
    consumer = _consumer_run(tmp_path, expected)
    shutil.rmtree(reference)

    with pytest.raises(ValueError, match='holds no copy'):
        worker.source_entries(workflow.stage_root(consumer), 'bartender-fit')
