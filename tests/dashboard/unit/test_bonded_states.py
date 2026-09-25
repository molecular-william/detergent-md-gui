import json

import pytest

from dashboard.models import bonded, mappings
from dashboard.models.bonded import states as bonded_states


def mapping():
    return {'name':'DDM','beads':[{'name':'B01'}],'rings':[],'connections':[]}


def test_candidate_identity_covers_virtual_site_definition():
    candidate = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    first = mappings.candidate_identity(candidate)
    changed = json.loads(json.dumps(candidate))
    changed['beads'][3]['virtual_site']['parents'][0] = changed['beads'][1]['name']
    assert mappings.candidate_identity(changed) != first


def test_parse_virtual_sites_preserves_parent_links():
    rows = bonded_states.parse_interactions(
        '[ atoms ]\n'
        '1 X 1 RES B01 1 X 0\n'
        '2 X 1 RES B02 1 X 0\n'
        '3 X 1 RES B03 1 X 0\n'
        '4 X 1 RES VS1 1 X 0\n'
        '[ virtual_sitesn ]\n'
        '4 1 1 2 3\n'
    )
    assert rows == [{'kind': 'virtual_sitesn', 'indices': [4], 'beads': ['VS1'],
                     'function': '1', 'parameters': [], 'parents': [1, 2, 3],
                     'parent_beads': ['B01', 'B02', 'B03'], 'id': 'virtual_sitesn:1'}]


def test_apply_interaction_parameters_updates_only_editable_terms():
    topology = '[ bonds ]\n1 2 1 0.30 100\n[ virtual_sitesn ]\n3 1 1 2\n'
    updated = bonded_states.apply_interaction_parameters(
        topology, [{'id': 'bonds:1', 'parameters': ['0.33', '1200']}]
    )
    assert '1 2 1 0.33 1200' in updated
    assert '3 1 1 2' in updated


def test_function_edits_update_function_and_parameter_labels():
    topology = (
        '[ atoms ]\n'
        '1 C1 1 RES B01 1 0 72\n'
        '2 C1 1 RES B02 2 0 72\n'
        '3 C1 1 RES B03 3 0 72\n'
        '[ bonds ]\n1 2 1 0.30 100 ; keep this\n'
        '[ angles ]\n1 2 3 1 120 25\n'
        '[ constraints ]\n1 2 1 0.30\n'
        '[ virtual_sitesn ]\n3 1 1 2\n'
    )
    rows = bonded_states.parse_interactions(topology)
    bond = next(row for row in rows if row['kind'] == 'bonds')
    angle = next(row for row in rows if row['kind'] == 'angles')
    constraint = next(row for row in rows if row['kind'] == 'constraints')
    site = next(row for row in rows if row['kind'] == 'virtual_sitesn')
    assert bond['editable'] is True
    assert bond['id'] == 'bonds:1'
    assert angle['id'] == 'angles:1'
    assert bond['parameter_labels'] == ['length (nm)', 'force (kJ mol^-1 nm^-2)']
    assert angle['parameter_labels'] == ['angle (deg)', 'force (kJ mol^-1 rad^-2)']
    assert constraint['editable'] is False
    assert site.get('editable', False) is False

    updated = bonded_states.apply_interaction_edits(
        topology, [{'id': 'bonds:1', 'function': 1, 'parameters': ['0.33', '1200']}]
    )
    assert '1 2 1 0.33 1200 ; keep this' in updated


def test_function_metadata_has_correct_units_and_descriptions():
    assert bonded.FUNCTION_SPECS['angles'][2]['description'] == 'GROMOS-96 cosine'
    assert bonded.FUNCTION_PARAMETER_LABELS['angles'][2][1] == 'force (kJ mol^-1)'
    assert bonded.FUNCTION_PARAMETER_LABELS['angles'][10][1] == 'force (kJ mol^-1)'
    assert bonded.FUNCTION_PARAMETER_LABELS['dihedrals'][1][1] == 'force (kJ mol^-1)'
    assert bonded.FUNCTION_PARAMETER_LABELS['dihedrals'][9][1] == 'force (kJ mol^-1)'
    assert bonded.FUNCTION_PARAMETER_LABELS['dihedrals'][2][1] == 'force (kJ mol^-1 rad^-2)'

    row = next(row for row in bonded.parse_interactions('[ angles ]\n1 2 3 2 150 50\n')
               if row['kind'] == 'angles')
    assert row['function_options'][1]['description'] == 'GROMOS-96 cosine'


@pytest.mark.parametrize('update', [
    {'id': 'bonds:1', 'function': 2, 'parameters': ['0.33', '1200']},
    {'id': 'bonds:1', 'function': 1, 'parameters': ['0.33']},
    {'id': 'constraints:1', 'function': 1, 'parameters': ['0.33', '100']},
    {'id': 'bonds:9', 'function': 1, 'parameters': ['0.33', '100']},
])
def test_function_edits_reject_invalid_targets_and_shapes(update):
    topology = '[ bonds ]\n1 2 1 0.30 100\n[ constraints ]\n1 2 1 0.30\n'
    with pytest.raises(ValueError):
        bonded_states.apply_interaction_edits(topology, [update])


def test_state_revisions_and_candidate_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(bonded_states, 'storage_root', lambda: tmp_path)
    m=mapping(); m['mapping_hash']=mappings.candidate_identity(m)
    state=bonded_states.create(m,'fit',kind='fast-forward-fit',topology='[ moleculetype ]\n[ atoms ]',status='complete')
    updated=bonded_states.revise(state['state_id'],{'topology':'[ moleculetype ]\n[ atoms ]\n; v2'},1,in_place=True)
    assert updated['revision']==2 and bonded_states.get(state['state_id'],1)['topology'] != updated['current']['topology']
    with pytest.raises(ValueError,match='mapping identity'):
        bonded_states.revise(state['state_id'],{'mapping_hash':'wrong'},2)


def test_save_as_new_preserves_source_and_in_place_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(bonded_states, 'storage_root', lambda: tmp_path)
    m = mapping(); m['mapping_hash'] = mappings.candidate_identity(m)
    state = bonded_states.create(m, 'fit', topology='[ moleculetype ]\n[ atoms ]', status='complete')
    original = (tmp_path / f"{state['state_id']}.json").read_bytes()
    copy = bonded_states.revise(state['state_id'], {'name': 'edited'}, 1, in_place=False)
    assert copy['state_id'] != state['state_id']
    assert copy['parent_state_id'] == state['state_id']
    assert copy['parent_revision'] == 1
    assert (tmp_path / f"{state['state_id']}.json").read_bytes() == original
    revised = bonded_states.revise(state['state_id'], {'name': 'r2'}, 1, in_place=True)
    assert revised['state_id'] == state['state_id']
    assert revised['revision'] == 2


def test_save_as_new_applies_function_and_parameter_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(bonded_states, 'storage_root', lambda: tmp_path)
    m = mapping(); m['mapping_hash'] = mappings.candidate_identity(m)
    topology = '[ moleculetype ]\n[ atoms ]\n1 C1 1 RES B01 1 0 72\n2 C1 1 RES B02 2 0 72\n[ bonds ]\n1 2 1 0.30 100\n'
    state = bonded_states.create(m, 'fit', topology=topology, status='complete')
    copy = bonded_states.revise(state['state_id'], {
        'name': 'edited',
        'interaction_edits': [{'id': 'bonds:1', 'function': 1, 'parameters': ['0.33', '1200']}],
    }, 1, in_place=False)
    assert '1 2 1 0.33 1200' in copy['current']['topology']
    assert '1 2 1 0.30 100' in bonded_states.get(state['state_id'])['current']['topology']


def test_in_place_revision_rejects_stale_expected_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(bonded_states, 'storage_root', lambda: tmp_path)
    m = mapping(); m['mapping_hash'] = mappings.candidate_identity(m)
    state = bonded_states.create(m, 'fit', topology='[ moleculetype ]\n[ atoms ]', status='complete')
    with pytest.raises(ValueError, match='changed; reload'):
        bonded_states.revise(state['state_id'], {'name': 'stale'}, 2, in_place=True)


def test_delete_requires_job_reference_to_be_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(bonded_states, 'storage_root', lambda: tmp_path)
    m=mapping(); m['mapping_hash']=mappings.candidate_identity(m)
    state=bonded_states.create(m,'fit',topology='[ moleculetype ]\n[ atoms ]',status='complete')
    with pytest.raises(ValueError,match='run1'):
        bonded_states.delete(state['state_id'],[{'id':'run1','bonded_state_id':state['state_id']}])
    assert bonded_states.delete(state['state_id'],[]) == state['state_id']
