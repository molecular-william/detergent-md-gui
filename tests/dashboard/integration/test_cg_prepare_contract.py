"""What `adapter_for('aa_cg').prepare(run_dir, metadata)` promises, now that it is the only way in.

Option A of the audit's Phase 2. `aa_cg` used to be prepared by `workflow.prepare_run`, which assembled the
arguments, built the stage directory, copied it to `inputs/` and wrote the manifest -- while the four other run
types called `adapter_for(...).prepare(run_dir, metadata)` and did the same choreography inside their own adapters.
Two shapes for one word, and the protocol's own `aa_cg` prepare sat written and uncalled.

These tests were written before the swap as a parity check between the two entries, and they are retained because
what they assert is the contract rather than the comparison: a run root goes in, a prepared run comes out, whoever
is behind the protocol. The adapter is stubbed on purpose -- a real `cg.prepare` would drag in a force field and a
mapping and test those instead of the contract around them.
"""
import json
from pathlib import Path

import pytest

from dashboard.execution.adapters import cg
from dashboard.execution.protocol import adapter_for

# A job whose settings carry a key from each dialect. `aa_nvt_ps` belongs to the AA vocabulary only, so the CG
# dialect drops it -- that rule belongs to the run type, and it used to live in the coordinator.
SETTINGS = {'aa_production_ps': 200, 'cg_production_ps': 20, 'aa_nvt_ps': 5}
SNAPSHOT = {'id': 'DDM', 'sha256': {'molecule.itp': '0' * 64}}

# The metadata the coordinator builds for an AA-to-CG job, plus keys the protocol does not forward so the filter has
# something to drop.
METADATA = dict(
    detergent='DDM', profile='draft-smoke', settings=SETTINGS,
    mapping_candidate={'label': 'a-mapping'}, bonded_state_snapshot={'states': []},
    bonded_intent='fit_and_simulate', molecule_snapshot=SNAPSHOT, molecule_root=Path('/molecules'),
    shared_reference={'source_run_id': '111111111111'}, reference_root=Path('/runs'),
    run_type='aa_cg', molecule_id='DDM', runs_root=Path('/runs'))

RECORD = {'stage_plan': [['AA reference', '1_AA-reference/aa_reference.sh'],
                         ['trajectory mapping', '2_mapping/map_trajectory.sh']],
          'tools': {'gromacs': '2026.3'}, 'molecule_id': 'DDM'}


def stub_prepare(seen):
    """A stand-in for `cg.prepare` that records its arguments and leaves the record the real one leaves."""
    def prepare(run_dir, **kwargs):
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / '1_AA-reference').mkdir(exist_ok=True)
        (run_dir / '1_AA-reference' / 'aa_reference.sh').write_text('#!/bin/bash\n')
        (run_dir / 'manifest.json').write_text(json.dumps(RECORD))
        seen.append({'run_dir': Path(run_dir), 'kwargs': kwargs})
    return prepare


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    """A prepared AA-to-CG run directory, with the adapter's arguments captured.

    The *inner* `cg.prepare` is stubbed, not the protocol's, so what runs for real is the choreography under test --
    the stage directory, the `inputs/` copy, the manifest -- and only the stage-filling is stand-in.
    """
    seen = []
    monkeypatch.setattr(cg, 'prepare', stub_prepare(seen))
    run = tmp_path / 'run'
    run.mkdir()
    adapter_for('aa_cg').prepare(run, METADATA)
    return {'run': run, 'seen': seen}


def test_the_adapter_is_handed_a_stage_directory_beside_the_run(prepared):
    """The contract the protocol states: a run root goes in, and `stages/` is built inside it.

    Before the swap the protocol passed the run root straight to `cg.prepare`, which treats its argument as the stage
    directory -- so a caller that believed the docstring got its stages at the run root, no `inputs/`, no manifest.
    """
    assert prepared['seen'][0]['run_dir'] == prepared['run'] / 'stages'


def test_an_aa_only_setting_never_reaches_the_cg_dialect(prepared):
    assert 'aa_nvt_ps' not in prepared['seen'][0]['kwargs']['settings']
    assert prepared['seen'][0]['kwargs']['settings']['aa_production_ps'] == 200, 'the shared durations still arrive'


def test_metadata_the_run_type_has_no_argument_for_is_dropped(prepared):
    """Dropped rather than forwarded into a `TypeError` three calls down -- and the arguments it does have all
    arrive, which is the half that a filter written by hand gets wrong."""
    kwargs = prepared['seen'][0]['kwargs']
    for absent in ('run_type', 'runs_root', 'molecule_id'):
        assert absent not in kwargs
    assert set(kwargs) == {'detergent', 'profile', 'settings', 'mapping_candidate', 'bonded_state_snapshot',
                           'bonded_intent', 'shared_reference', 'reference_root', 'molecule_snapshot',
                           'molecule_root'}
    assert kwargs['shared_reference']['source_run_id'] == '111111111111', 'the reference still arrives'
    assert kwargs['molecule_snapshot'] == SNAPSHOT


def test_the_run_carries_an_inputs_tree_and_a_manifest(prepared):
    run = prepared['run']
    assert (run / 'inputs' / '1_AA-reference' / 'aa_reference.sh').is_file()
    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['stage_plan'] == RECORD['stage_plan'], 'the plan comes from the adapter that wrote it'
    assert manifest['tools'] == RECORD['tools']
    assert manifest['input_snapshot_sha256'], 'the snapshot the resume path verifies against'


def test_the_adapters_own_record_does_not_survive_into_inputs(prepared):
    """It is the channel the adapter reports through, not a stage input; a stale copy would be a second manifest."""
    assert not (prepared['run'] / 'inputs' / 'manifest.json').exists()
    assert not (prepared['run'] / 'stages' / 'manifest.json').exists()
