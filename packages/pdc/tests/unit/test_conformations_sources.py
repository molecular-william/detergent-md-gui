"""Source validation: the one ensemble a library may be built from, and a refusal that names the run.

Every refusal here stands between a protein-contacted or differently-mapped micelle and a library of conformations,
so each one is pinned by the run id and the reason rather than by "something went wrong".
"""
import pytest
from detergent_pdc.conformations import sources

from tests.harness.conformation_fixtures import MAPPING_SHA256, itp_text, run_tree


def record(workspace, run_id='b920391735dd'):
    return sources(workspace, [run_id])[0]


def test_a_completed_protein_free_run_is_a_source(tmp_path):
    fixture = run_tree(tmp_path, 'b920391735dd')
    found = record(tmp_path)
    assert found['run_id'] == 'b920391735dd'
    assert found['detergent'] == 'DDM'
    assert found['mapping_sha256'] == MAPPING_SHA256
    assert found['trajectory'] == '06_assessment/prod/whole.xtc'
    assert found['trajectory_path'] == fixture['trajectory']
    assert found['structure_path'] == fixture['structure']
    assert found['stage_root'] == fixture['stage_root']
    assert [bead['name'] for bead in found['beads']] == [bead['name'] for bead in fixture['beads']]
    assert len(found['trajectory_identity']) == 64
    bonds = {(first, second): length for first, second, length in found['bonds']}
    assert bonds[(0, 1)] is not None, 'a constraint states its own length'
    assert bonds[(0, 10)] is not None, 'a bond states its own length'
    assert bonds[(0, 3)] is None, 'a virtual site\'s parent is connectivity only, never a length check'


def test_runs_stay_in_the_callers_order(tmp_path):
    run_tree(tmp_path, 'first')
    run_tree(tmp_path, 'second')
    assert [found['run_id'] for found in sources(tmp_path, ['second', 'first'])] == ['second', 'first']
    assert [found['index'] for found in sources(tmp_path, ['second', 'first'])] == [0, 1]


def test_an_unfinished_run_is_refused(tmp_path):
    run_tree(tmp_path, status='failed')
    assert_refusal(tmp_path, 'is not completed')


def test_a_protein_carrying_run_is_refused(tmp_path):
    run_tree(tmp_path, protein='molecules/DDM/protein.pdb')
    assert_refusal(tmp_path, 'carries a protein')


def test_a_non_pdc_run_is_refused(tmp_path):
    run_tree(tmp_path, run_type='aa_cg')
    assert_refusal(tmp_path, 'not a pdc run')


def test_a_missing_run_is_refused(tmp_path):
    with pytest.raises(ValueError) as error:
        sources(tmp_path, ['deleted'])
    assert 'run deleted is not in this workspace' in str(error.value)


def test_a_missing_manifest_is_refused(tmp_path):
    run_tree(tmp_path, omit=('manifest',))
    assert_refusal(tmp_path, 'has no manifest.json')


def test_a_run_without_a_mapping_is_refused(tmp_path):
    run_tree(tmp_path, omit=('mapping',))
    assert_refusal(tmp_path, 'no mapping input')


def test_a_run_without_geometry_is_refused(tmp_path):
    run_tree(tmp_path, omit=('geometry',))
    assert_refusal(tmp_path, 'has no detergent_CG.json')


def test_a_run_without_topology_is_refused(tmp_path):
    run_tree(tmp_path, omit=('topology',))
    assert_refusal(tmp_path, 'has no detergent_CG.itp')


def test_a_nonpositive_stated_length_is_refused(tmp_path):
    fixture = run_tree(tmp_path, ('b920391735dd'), molecules=2, frames=1)
    (fixture['inputs'] / 'detergent_CG.itp').write_text(itp_text(overrides={(2, 5): 0.0}))
    with pytest.raises(ValueError, match='must be a positive number'):
        sources(tmp_path, ['b920391735dd'])


def test_a_run_without_a_production_trajectory_is_refused(tmp_path):
    run_tree(tmp_path, omit=('trajectory',))
    assert_refusal(tmp_path, 'no production trajectory')


def test_two_detergents_are_refused(tmp_path):
    run_tree(tmp_path, 'one', residue='DDM')
    run_tree(tmp_path, 'two', residue='LIP')
    with pytest.raises(ValueError) as error:
        sources(tmp_path, ['one', 'two'])
    assert 'run two is \'LIP\' but run one is \'DDM\'' in str(error.value)


def test_two_mappings_are_refused(tmp_path):
    run_tree(tmp_path, 'one')
    run_tree(tmp_path, 'two', mapping_sha256='0' * 64)
    with pytest.raises(ValueError) as error:
        sources(tmp_path, ['one', 'two'])
    assert 'run two was built from mapping' in str(error.value)
    assert 'run one from' in str(error.value)


def test_no_run_ids_is_refused(tmp_path):
    with pytest.raises(ValueError, match='at least one source run'):
        sources(tmp_path, [])


def test_a_path_is_not_a_run_id(tmp_path):
    with pytest.raises(ValueError, match='is not a run id'):
        sources(tmp_path, ['../escape'])


def test_a_run_named_twice_is_refused(tmp_path):
    run_tree(tmp_path, 'once')
    with pytest.raises(ValueError, match='named twice'):
        sources(tmp_path, ['once', 'once'])


def assert_refusal(workspace, sentence):
    with pytest.raises(ValueError) as error:
        sources(workspace, ['b920391735dd'])
    assert sentence in str(error.value)
    assert 'b920391735dd' in str(error.value)
