"""A saved mapping candidate is named, and the build resolves it rather than refusing it.

The panel offers the names the mapping store lists -- `mapping_candidate_<hash>.json` -- and a run's record keeps
that name. Reading it as a path from the project root turned every such run into "the detergent mapping is not a
file", which is a wiring failure wearing a missing-file costume.
"""
import json
import shutil

from dashboard.models.mappings import store
from detergent_pdc.execution.adapters import pdc

from tests.harness.pdc_fixtures import TEMPLATE_PATH, molecule_tree
from tests.harness.support import PROJECT_ROOT

CANDIDATE = 'mapping_candidate_0123456789abcdef0123456789abcdef.json'


def test_a_named_candidate_is_resolved_through_the_store(tmp_path, monkeypatch):
    """The name reaches a file: the refusal that follows is about the file's content, not about finding it.

    The stored candidate here is deliberately not a usable mapping, because what is under test is the resolution
    step -- a name the store lists becomes the path the deriver reads. Building a real candidate would test the
    deriver instead, and the repository's rule is that a test builds the record it needs rather than borrowing one.
    """
    root = molecule_tree(tmp_path)
    drafts = tmp_path / 'drafts'
    drafts.mkdir()
    (drafts / CANDIDATE).write_text('{"molecule_id": "DDM", "beads": []}')
    monkeypatch.setattr(store, 'candidate_paths', lambda: {CANDIDATE: drafts / CANDIDATE})

    try:
        pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root,
                    mapping=CANDIDATE)
    except ValueError as error:
        message = str(error)
        assert 'not a file' not in message, f'the name was never resolved: {message}'
        assert str(drafts) in message, f'the error should name the resolved file: {message}'
    else:
        raise AssertionError('a candidate without beads is not a mapping')


def test_an_unknown_name_still_says_the_mapping_is_missing(tmp_path):
    root = molecule_tree(tmp_path)
    try:
        pdc.prepare(tmp_path / 'run', template=TEMPLATE_PATH, settings={'seed': 1}, project_root=root,
                    mapping='mapping_candidate_nothing.json')
    except ValueError as error:
        assert 'not a file' in str(error) and 'mapping_candidate_nothing.json' in str(error)
    else:
        raise AssertionError('a mapping that resolves to nothing must be refused')


def test_a_cg_folder_with_a_mapping_keeps_the_mapping_branch(tmp_path):
    """A mapping is the model when one is given: the CG-only branch is the fallback, not an override.

    The folder here is the imported CG fixture, so it would take the mapping-free branch on its own. With a
    candidate the run instead records the candidate as its `mapping` input and its derived beads, which is exactly
    what a mapped run did before this branch existed.
    """
    (tmp_path / 'molecules').mkdir()
    shutil.copytree(PROJECT_ROOT / 'packages/core/tests/fixtures/cg_og', tmp_path / 'molecules' / 'OG')
    candidate = tmp_path / 'candidate.json'
    candidate.write_text(json.dumps({
        'schema_version': 3, 'molecule_id': 'OG', 'name': 'two beads over the CG fixture', 'martini_version': 3,
        'beads': [{'name': 'TAIL1', 'type': 'C1', 'atoms': [1, 2]},
                  {'name': 'HEAD', 'type': 'P1', 'atoms': [3]}],
        'connections': [['TAIL1', 'HEAD']]}))
    run = tmp_path / 'run'

    pdc.prepare(run, template='molecules/OG/micelle_template.json',
                settings={'seed': 1, 'aggregation_number': 4}, project_root=tmp_path, mapping=str(candidate))

    model = json.loads((run / pdc.INPUTS_DIRECTORY / pdc.SETTINGS_NAME).read_text())['detergent_model']
    assert model['mapping'] == str(candidate) and 'kind' not in model
    roles = [entry['role'] for entry in json.loads((run / 'manifest.json').read_text())['inputs']]
    assert 'mapping' in roles and 'detergent_model' not in roles
