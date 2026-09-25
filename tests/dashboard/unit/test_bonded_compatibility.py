"""A renamed candidate must not orphan the states fitted for it.

Written before the fix, so it fails on import of `belongs_to`. The rule it pins:

`candidate_identity` hashes the candidate's *name* along with its beads, so renaming a saved
candidate makes every state fitted for it look like a stranger -- the workspace selector hid them and
run admission refused reuse with 'Bonded state does not belong to the selected mapping'. A state now
records the name-free `content_identity` as well, and compatibility accepts either: the name still
answers *which* candidate produced a state, which is what provenance needs it for, while the
chemistry decides whether a state belongs to a mapping.
"""
import json

from dashboard.models import mappings
from dashboard.models.bonded import states as bonded_states


def test_the_selector_rule_answers_from_hashes_alone():
    """The workspace selector holds hashes, not a mapping, so the rule has to work from those.

    Same two questions as belongs_to: the candidate identity first, the chemistry second. This is what
    keeps a renamed candidate's states listed -- the rename changes the first hash and not the second.
    """
    fitted = {'name': 'DDM candidate', 'beads': [{'name': 'B01'}], 'rings': [], 'connections': []}
    state = bonded_states.create(fitted, 'Fitted', 'mapping-only', status='incomplete')
    candidate, content = mappings.candidate_identity(fitted), mappings.content_identity(fitted)

    assert bonded_states.matches(state, candidate_hash=candidate, content_hash=content)
    assert bonded_states.matches(state, content_hash=content), 'the chemistry is enough'
    assert bonded_states.matches(state, candidate_hash=candidate), 'the candidate identity is enough'
    assert not bonded_states.matches(state, candidate_hash='0' * 64)
    assert not bonded_states.matches(state, content_hash='0' * 64)
    assert not bonded_states.matches(state), 'asked with nothing, it matches nothing'


def test_a_renamed_candidate_no_longer_orphans_its_fitted_state():
    fitted = {'name': 'DDM candidate', 'beads': [{'name': 'B01'}], 'rings': [], 'connections': []}
    state = bonded_states.create(fitted, 'Fitted', 'fast-forward-fit',
                                 topology='[ moleculetype ]\nLIG 1\n[ atoms ]\n1 X 1 LIG B01 1 X 0\n',
                                 status='complete')

    renamed = json.loads(json.dumps(fitted)); renamed['name'] = 'Renamed candidate'
    assert mappings.candidate_identity(renamed) != mappings.candidate_identity(fitted), 'the name is in the identity'
    assert bonded_states.belongs_to(state, renamed), 'the chemistry is unchanged'

    rebeaded = json.loads(json.dumps(fitted)); rebeaded['beads'][0]['name'] = 'ZZZ'
    assert mappings.content_identity(rebeaded) != mappings.content_identity(fitted)
    assert not bonded_states.belongs_to(state, rebeaded), 'different bead names are different chemistry'


def test_a_state_written_before_the_content_hash_still_matches_by_candidate():
    """Records made before this field existed have no content hash; they keep working as they did."""
    fitted = {'name': 'DDM candidate', 'beads': [{'name': 'B01'}], 'rings': [], 'connections': []}
    state = bonded_states.create(fitted, 'Fitted', 'mapping-only', status='incomplete')
    legacy = {**state, 'current': {k: v for k, v in state['current'].items()
                                  if k != 'mapping_content_hash'}}

    renamed = json.loads(json.dumps(fitted)); renamed['name'] = 'Renamed candidate'
    assert bonded_states.belongs_to(legacy, fitted)
    assert not bonded_states.belongs_to(legacy, renamed), 'without a content hash, only the candidate identity answers'
