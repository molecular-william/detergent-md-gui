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
    derived_digest = saved['snapshot']['artifacts']['composition.itp']
    assert manifest['parameterization'] == {
        'kind': 'composition', 'composition_id': saved['id'], 'composition_revision': 0,
        'base': 'derived', 'base_sha256': derived_digest, 'topology_sha256': derived_digest,
        'molecule_id': saved['id'], 'head_molecule_id': 'Trehalose'}
    assert manifest['molecule_name'] == 'GLC-C12'
    assert any('derived' in limitation and 'not fitted' in limitation for limitation in manifest['limitations'])
    assert any(composition.NO_REFERENCE in limitation for limitation in manifest['limitations'])


# --- edited parameterization revisions ------------------------------------------------------------------------------

import hashlib

from dashboard.models.compositions import parameterizations

OVERRIDE = [{'section': 'bonds', 'beads': ['C', 'C01'], 'function': 1, 'parameters': [0.47, 3000]}]


def _save(composition, overrides, expected=0):
    return parameterizations.save(composition['id'], {'overrides': overrides}, expected_revision=expected)


def test_an_edit_appends_a_revision_seeded_from_the_derived_model():
    saved = compositions.create_composition(dict(PAYLOAD))
    view = parameterizations.view(saved['id'])
    assert view['current'] == 0 and view['edited'] is False
    assert view['current_parameterization']['revision'] == 0
    assert view['ranges']['bonds'][1][1]['label'] == 'force (kJ mol^-1 nm^-2)'
    # The CG stage's own clamp, not the mapping editor's 100000: the input and the simulated number are one.
    assert view['ranges']['bonds'][1][1]['max'] == parameterizations.BOND_FORCE_CAP

    item = _save(saved, OVERRIDE)
    assert item['revision'] == 1 and item['base'] == 'derived-revision-0'
    assert item['base_sha256'] == saved['snapshot']['artifacts']['composition.itp']
    assert item['topology_sha256'] == hashlib.sha256(item['topology'].encode()).hexdigest()

    view = parameterizations.view(saved['id'])
    assert view['current'] == 1 and view['edited'] is True
    manual = [row for row in view['terms'] if row['source'] == 'manual']
    assert manual and manual[0]['beads'] == ['C', 'C01'] and manual[0]['parameters'] == ['0.47', '3000']
    descriptor = compositions.parameterization(saved['id'])
    assert descriptor['revision'] == 1 and descriptor['base'] == 'edited'
    assert descriptor['topology']['sha256'] == item['topology_sha256']


def test_a_second_edit_is_applied_to_the_derived_base_not_the_previous_revision():
    saved = compositions.create_composition(dict(PAYLOAD))
    _save(saved, OVERRIDE)
    _save(saved, [{'section': 'bonds', 'beads': ['C01', 'C02'], 'function': 1,
                   'parameters': [0.47, 2000]}], expected=1)
    view = parameterizations.view(saved['id'])
    assert view['current'] == 2
    lines = {tuple(row['beads']): row['parameters'] for row in view['terms'] if row['kind'] == 'bonds'}
    assert lines[('C', 'C01')] == ['0.47000', '5000.0'], 'the removed override returns to the derived value'
    # The rewrite writes one line per interaction; the derived line keeps the file's own spelling.
    assert lines[('C01', 'C02')] == ['0.47', '2000']


def test_a_stale_writer_is_refused_and_writes_nothing():
    saved = compositions.create_composition(dict(PAYLOAD))
    _save(saved, OVERRIDE)
    with pytest.raises(parameterizations.StaleRevision, match='changed'):
        _save(saved, OVERRIDE, expected=0)
    assert parameterizations.view(saved['id'])['current'] == 1


def test_constraints_virtual_sites_and_unknown_terms_are_refused():
    saved = compositions.create_composition(dict(PAYLOAD))
    for overrides, message in (
            ([{'section': 'bonds', 'beads': ['A', 'VS'], 'function': 1, 'parameters': [0.47, 3000]}],
             'distinct massive beads'),
            ([{'section': 'bonds', 'beads': ['A', 'C01'], 'function': 1, 'parameters': [0.47, 3000]}],
             'Override does not match'),
            ([{'section': 'bonds', 'beads': ['C', 'C01'], 'function': 1, 'parameters': [0.47, 300000]}],
             'must be between 0 and 100000'),
            ([{'section': 'bonds', 'beads': ['C', 'C01'], 'function': 1, 'parameters': [0.47, 60000]}],
             'capped at 50000'),
            ([{'section': 'constraints', 'beads': ['A', 'C'], 'function': 1, 'parameters': [0.47]}],
             'massive beads')):
        with pytest.raises(ValueError, match=message):
            _save(saved, overrides, expected=0)
    assert parameterizations.view(saved['id'])['revision'] == 0


def test_revision_resolution_is_named_current_then_derived():
    saved = compositions.create_composition(dict(PAYLOAD))
    assert parameterizations.revision(saved['id'])['revision'] == 0
    item = _save(saved, OVERRIDE)
    assert parameterizations.revision(saved['id'], None)['revision'] == 1
    assert parameterizations.revision(saved['id'], 1)['topology_sha256'] == item['topology_sha256']
    assert parameterizations.revision(saved['id'], 0)['engine'] == 'composition-derivation'
    with pytest.raises(ValueError, match='Unknown composition parameterization revision'):
        parameterizations.revision(saved['id'], 7)


def test_a_prepared_run_stages_the_revision_it_names(tmp_path):
    saved = compositions.create_composition(dict(PAYLOAD))
    item = _save(saved, OVERRIDE)
    cg_run.PROTOCOL.prepare(tmp_path / 'run', {
        'composition_id': saved['id'], 'profile': 'draft-smoke-reference',
        'parameterization': {'kind': 'composition', 'composition_id': saved['id'], 'composition_revision': 1}})
    staged = (tmp_path / 'run/stages/3_initial_CG/GLC.itp').read_text()
    assert staged == item['topology']
    manifest = json.loads((tmp_path / 'run/manifest.json').read_text())
    assert manifest['parameterization']['composition_revision'] == 1
    assert manifest['parameterization']['base'] == 'derived-revision-0'
    assert manifest['parameterization']['topology_sha256'] == item['topology_sha256']
    assert manifest['parameterization']['base_sha256'] == item['base_sha256']


def test_readiness_answers_the_named_revision(monkeypatch):
    saved = compositions.create_composition(dict(PAYLOAD))
    _save(saved, OVERRIDE)
    monkeypatch.setattr(composition.tools, 'tool_path', lambda name, **kwargs: f'/injected/{name}')
    ready = composition.readiness(saved['id'], saved['id'], 1)
    assert ready['ready'] is True
    assert 'parameterization revision 1' in {check['label'] for check in ready['checks']}
    unknown = composition.readiness(saved['id'], saved['id'], 7)
    assert unknown['ready'] is False and 'Unknown composition parameterization revision' in unknown['blockers'][0]
