"""The composition's derived parameterization, and the run manifest that records the model it consumed.

A composition is never fitted: its parameterization is derived from the tail recipe and the head fragment's
published Martini 3 terms. `compositions.derived_parameterization` is that model in the CG catalog's own shape, and
a CG run records the same identity in its manifest. These tests pin the shape and the counts, because a reader that
had to parse the topology itself would have a second place to keep right.
"""
import json

import pytest
from dashboard import itp
from dashboard.execution.adapters import cg_run, composition
from dashboard.models import catalog, compositions

PAYLOAD = {'head_fragment_id': 'builtin:martini-sugars-v2:GLC', 'tail_recipe_id': 'linear-c1',
           'carbon_count': 12, 'head_endpoint': {'bead': 'C'}, 'tail_endpoint': {'bead': 'C01'},
           'linkage_profile_id': 'sugar-alkyl-ether-ddm-transfer', 'molecule_name': 'GLC-C12'}


@pytest.fixture(autouse=True)
def no_tool_probe(monkeypatch):
    monkeypatch.setattr(composition, 'tool_metadata', lambda: {})


def test_the_parameterization_is_derived_with_the_artifacts_own_counts():
    saved = compositions.create_composition(dict(PAYLOAD))
    parameterization = compositions.derived_parameterization(saved['id'])

    assert parameterization['kind'] == 'composition' and parameterization['revision'] == 0
    assert parameterization['engine'] == 'composition-derivation'
    assert parameterization['source'] == 'recipe-only'
    assert parameterization['head_molecule_id'] is None

    artifacts = compositions.artifacts(compositions.get(saved['id']))
    topology = parameterization['topology']
    assert topology['path'] == str(artifacts['composition.itp'])
    assert topology['sha256'] == saved['snapshot']['artifacts']['composition.itp']
    counts = {name: len(rows) for name, rows in itp.sections(artifacts['composition.itp'].read_text())
              if rows and name in compositions.TERM_SECTIONS}
    assert topology['beads'] == counts.pop('atoms')
    assert topology['terms'] == counts
    assert topology['terms']['bonds'] > 0
    assert parameterization['coordinates']['path'] == str(artifacts['composition.gro'])
    assert parameterization['coordinates']['sha256'] == saved['snapshot']['artifacts']['composition.gro']


def test_a_head_link_records_the_reference_the_head_terms_came_from():
    """`recipe+reference` is the source when the model names the AA molecule its head came from."""
    saved = compositions.create_composition(dict(PAYLOAD, head_molecule_id='Trehalose'))
    assert saved['head_molecule_id'] == 'Trehalose'
    parameterization = compositions.derived_parameterization(saved['id'])
    assert parameterization['head_molecule_id'] == 'Trehalose'
    assert parameterization['source'] == 'recipe+reference'
    row = next(item for item in catalog.list_models()
               if item['kind'] == 'composition' and item['id'] == saved['id'])
    assert row['head_molecule_id'] == 'Trehalose' and row['parameterization']['source'] == 'recipe+reference'


def test_a_linked_head_must_be_a_catalogued_molecule():
    with pytest.raises(ValueError, match='catalogue'):
        compositions.create_composition(dict(PAYLOAD, head_molecule_id='NoSuchMolecule'))
    with pytest.raises(ValueError):
        compositions.create_composition(dict(PAYLOAD, head_molecule_id='../Trehalose'))


def test_the_manifest_records_the_model_the_run_consumed(tmp_path):
    saved = compositions.create_composition(dict(PAYLOAD, head_molecule_id='Trehalose'))
    cg_run.PROTOCOL.prepare(tmp_path / 'run', {
        'composition_id': saved['id'], 'profile': 'draft-smoke-reference',
        'parameterization': {'kind': 'composition', 'composition_id': saved['id']}})

    manifest = json.loads((tmp_path / 'run/manifest.json').read_text())
    assert manifest['parameterization'] == {'kind': 'composition', 'composition_id': saved['id'],
                                            'molecule_id': saved['id'], 'head_molecule_id': 'Trehalose'}
    assert manifest['molecule_name'] == 'GLC-C12'
    assert any('derived' in limitation and 'not fitted' in limitation for limitation in manifest['limitations'])
    assert any(composition.NO_REFERENCE in limitation for limitation in manifest['limitations'])
