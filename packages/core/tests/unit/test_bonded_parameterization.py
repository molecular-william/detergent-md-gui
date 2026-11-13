"""A mapping's parameterization: its revisions, the identities that address them, and its two states.

D1 of `docs/design/2026-10-16-parameterization-and-new-run.md`: the parameterization belongs to the
mapping and the bonded states become its revisions. What a run reads is the *current* revision, so
what these tests pin is the reading side: which record a mapping is found by, which revision is
current, and what a revision is not allowed to claim.

Nothing here touches the run store, and nothing reads a developer's workspace: the records are
written into the isolated workspace the `dashboard` fixture selects.
"""
import json

import pytest
from dashboard.models import mappings
from dashboard.models.bonded import parameterization

from tests.harness.support import PARAMETERIZATION_TOPOLOGY as TOPOLOGY
from tests.harness.support import parameterization_mapping as mapping
from tests.harness.support import parameterization_revision as revision


def test_a_mapping_with_no_record_has_no_current_revision_and_that_is_a_state_not_a_fault():
    """D5's second honest state: the run fits the model and records that it did."""
    assert parameterization.current(mapping()) is None
    assert parameterization.document(mapping())['revisions'] == []
    assert parameterization.summary(mapping())['parameterized'] is False
    assert parameterization.summary(mapping())['revision'] is None


def test_revisions_accumulate_and_the_newest_is_current():
    candidate = mapping()
    first = parameterization.save(candidate, revision())
    second = parameterization.save(candidate, revision(engine='bartender'))

    assert (first['revision'], second['revision']) == (1, 2)
    assert [item['revision'] for item in parameterization.document(candidate)['revisions']] == [1, 2]
    assert parameterization.current(candidate)['engine'] == 'bartender'
    assert parameterization.get(candidate, 1)['engine'] == 'fast-forward'
    assert parameterization.summary(candidate)['revision'] == 2


def test_a_renamed_candidate_keeps_its_revisions_and_a_reassigned_one_does_not():
    """The doctrine `bonded.states.belongs_to` keeps: provenance by name, compatibility by content.

    Only the content identity selects the record file. A rename therefore keeps its fitted revisions
    -- which is what makes "revisions of this mapping" survive the same save that mints a new name --
    while a bead that moved to another atom is a different model, and a fit of the old one must not be
    handed to it.
    """
    candidate = mapping()
    parameterization.save(candidate, revision())
    renamed = mapping(name='DDM · renamed')
    assert parameterization.current(renamed)['revision'] == 1

    changed = json.loads(json.dumps(candidate))
    changed['beads'][0]['name'] = 'B99'
    assert parameterization.current(changed) is None


def test_a_record_that_belongs_to_another_mapping_is_refused_rather_than_read_as_absent():
    """A corrupt or mis-addressed record is not the same answer as no record, and a run must not fit
    over the top of one it failed to read."""
    candidate = mapping()
    parameterization.save(candidate, revision())
    path = parameterization.records_root() / f'{parameterization.content_identity(candidate)}.json'
    record = json.loads(path.read_text())
    record['mapping_content_hash'] = 'ff' * 32
    path.write_text(json.dumps(record))

    with pytest.raises(ValueError, match='belongs to another mapping'):
        parameterization.current(candidate)


@pytest.mark.parametrize('override, message', [
    ({'engine': 'geometry'}, 'Unknown fitting engine'),
    ({'topology': 'not a topology'}, 'complete ITP topology'),
    ({'topology': '[ moleculetype ]\nMOL 1\n'}, 'complete ITP topology'),
    ({'options': {'torsion_model': 'harmonic'}}, 'Unknown torsion model'),
    ({'options': {'torsion_scale': 2.0}}, 'circular-harmonic'),
    ({'options': {'unknown': 1}}, 'Unknown parameterization option'),
    ({'ensemble': {'trajectory': 'x'}}, 'ensemble its engine saw'),
    ({'ensemble': {'frames': -1}}, 'non-negative integer'),
    ({'checks': {'dihedral-fit': [], 'other': {}}}, 'Unknown check name'),
    ({'aa_reference': {'run_id': 'nope'}}, 'Invalid AA source run ID'),
    ({'aa_reference': {'run_id': 'a54ac8f64710', 'extra': 1}}, 'Unknown AA reference field'),
])
def test_a_revision_that_a_run_could_not_read_is_refused_at_the_door(override, message):
    with pytest.raises(ValueError, match=message):
        parameterization.save(mapping(), revision(**override))


def test_a_revision_cannot_call_itself_scientifically_validated():
    """A fit produced here has never been validated, and the record says so rather than taking a word
    for it: this is the field every other store in the tree refuses to let a caller set."""
    stored = parameterization.save(mapping(), revision(scientifically_validated=True))
    assert stored['scientifically_validated'] is False


def test_a_stale_writer_is_refused_so_two_fits_cannot_silently_become_one():
    candidate = mapping()
    parameterization.save(candidate, revision())
    with pytest.raises(ValueError, match='changed; reload'):
        parameterization.save(candidate, revision(), expected_revision=0)
    assert parameterization.save(candidate, revision(), expected_revision=1)['revision'] == 2


def test_an_earlier_revision_can_be_made_current_without_rewriting_history():
    candidate = mapping()
    parameterization.save(candidate, revision())
    parameterization.save(candidate, revision(engine='bartender'))
    parameterization.make_current(candidate, 1)

    assert parameterization.current(candidate)['revision'] == 1
    assert [item['revision'] for item in parameterization.document(candidate)['revisions']] == [1, 2]


def test_the_options_start_from_the_mappings_own_torsion_model():
    """D4a: the refinement is driven by the mapping, never by a run setting, so a job that is asked
    for nothing fits the torsions the mapping declares."""
    candidate = mapping(bonded_options={'torsion_model': 'circular-harmonic', 'torsion_scale': 1.4})
    assert parameterization.default_options(candidate)['torsion_model'] == 'circular-harmonic'
    assert parameterization.default_options(candidate)['torsion_scale'] == 1.4
    assert parameterization.default_options(mapping())['torsion_model'] == 'legacy'
    assert parameterization.default_options(candidate)['constraints_threshold'] == 10000.0


def test_the_terms_are_counted_without_the_sites_and_each_one_names_its_source():
    """The panel's `source` column: a ring constraint is the mapping's, an override is a hand edit, a
    term the automatic draft had no reference for is geometry, and everything else is the engine's."""
    candidate = mapping(beads=[{'name': 'B01'}, {'name': 'B02'}, {'name': 'B03'}, {'name': 'B04'}],
                        rings=[{'beads': ['B01', 'B02', 'B03']}],
                        bonded_overrides=[{'section': 'bonds', 'beads': ['B02', 'B03'],
                                           'function': 1, 'parameters': [0.31, 6000]}])
    topology = ('[ moleculetype ]\nMOL 1\n\n[ atoms ]\n'
                '1 C1 1 MOL B01 1 0 72\n2 C1 1 MOL B02 2 0 72\n'
                '3 C1 1 MOL B03 3 0 72\n4 TC4 1 MOL B04 4 0 0\n\n'
                '[ constraints ]\n1 2 1 0.310\n1 3 1 0.359\n\n'
                '[ bonds ]\n2 3 1 0.31 6000\n3 4 1 0.40 5000\n\n'
                '[ angles ]\n1 2 3 1 120 25\n\n'
                '[ dihedrals ]\n1 2 3 4 1 -102.273 36.636 2\n\n'
                '[ virtual_sitesn ]\n4 1 1 2 3\n')
    stored = parameterization.save(candidate, revision(
        topology=topology,
        engine_terms=[{'kind': 'bonds', 'beads': ['B03', 'B04'], 'provenance': {'fallback': True}},
                      {'kind': 'bonds', 'beads': ['B02', 'B03'], 'provenance': {'fallback': False}}]))

    sources = {row['id']: row['source'] for row in stored['sources']}

    assert stored['sources'] == parameterization.term_sources(stored, candidate)
    assert sources['constraints:1'] == 'mapping' and sources['constraints:2'] == 'mapping'
    assert sources['bonds:1'] == 'manual', 'a pair the mapping overrides is a hand edit'
    assert sources['bonds:2'] == 'geometry', 'the draft had no reference for it'
    assert sources['angles:1'] == 'ff_inter'
    assert sources['virtual_sitesn:1'] == 'mapping'
    assert parameterization.total_terms(stored) == 6, 'the virtual site is not a fitted interaction'


def test_the_summary_says_which_engine_against_which_reference_in_bs_words():
    candidate = mapping()
    parameterization.save(candidate, revision(options={'torsion_model': 'circular-harmonic',
                                                       'torsion_scale': 1.0,
                                                       'constraints_threshold': 10000.0,
                                                       'temperature_k': 300.0}))
    summary = parameterization.summary(candidate)
    sentence = parameterization.describe(parameterization.current(candidate))

    assert summary['engine_label'] == 'Fast-Forward fit (ff_inter)'
    assert summary['checks'] == ['bonded-cross-check', 'dihedral-fit']
    assert summary['torsion_model'] == 'circular-harmonic'
    assert summary['aa_reference']['run_id'] == 'a54ac8f64710'
    assert 'a54ac8f64710' in sentence and 'circular-harmonic' in sentence
    assert summary['revision_sha256'] == parameterization.revision_sha256(parameterization.current(candidate))


def test_the_revision_digest_changes_with_the_terms_and_not_with_the_clock():
    first = parameterization.revision_sha256(dict(revision(), created_at='2026-01-01T00:00:00+00:00'))
    later = parameterization.revision_sha256(dict(revision(), created_at='2026-06-01T00:00:00+00:00'))
    changed = parameterization.revision_sha256(dict(revision(engine='bartender'), created_at='2026-01-01T00:00:00+00:00'))

    assert first == later, 'the digest names the terms, not the moment they were stored'
    assert first != changed


def test_the_record_lives_in_the_workspace_the_application_selected(dashboard):
    candidate = mapping()
    parameterization.save(candidate, revision())
    path = dashboard.paths.workspace / 'parameterizations' / 'records' / f'{parameterization.content_identity(candidate)}.json'
    assert path.is_file()
    assert list(dashboard.paths.workspace.glob('bonded_states/*.json')) == [], 'not beside the old states'


def test_a_record_can_be_read_by_hash_because_the_panel_works_from_hashes():
    """A hash-addressed reader and a run's manifest hold hashes, not the mapping document: the store answers
    both without one, and an unknown hash is the no-parameterization state rather than an error."""
    candidate = mapping()
    parameterization.save(candidate, revision())
    content = parameterization.content_identity(candidate)

    record = parameterization.one(content)
    state = parameterization.view(record)

    assert record['mapping_content_hash'] == content
    assert state['parameterized'] is True and state['revision'] == 1
    assert state['revisions'] == [1]
    assert state['mapping_content_hash'] == content
    assert parameterization.view(parameterization.one('a' * 64))['parameterized'] is False
    with pytest.raises(ValueError, match='Invalid mapping content identity'):
        parameterization.one('nope')


def test_matches_answers_for_a_rename_and_for_a_changed_bead():
    """The two identities, in the order `bonded.states.matches` asks them: the candidate identity is
    provenance, the content identity is compatibility."""
    candidate = mapping()
    parameterization.save(candidate, revision())
    record = parameterization.one(parameterization.content_identity(candidate))

    assert parameterization.matches(record, candidate_hash=mappings.candidate_identity(mapping(name='DDM · renamed'))) is False
    assert parameterization.matches(record, content_hash=parameterization.content_identity(mapping(name='DDM · renamed'))) is True
    assert parameterization.matches(record, candidate_hash=mappings.candidate_identity(candidate)) is True
    changed = json.loads(json.dumps(candidate))
    changed['beads'][0]['name'] = 'B99'
    assert parameterization.matches(record, content_hash=parameterization.content_identity(changed)) is False
    assert parameterization.matches(None) is False


def test_the_records_are_listed_newest_first_and_a_broken_one_is_skipped():
    first = mapping()
    parameterization.save(first, revision())
    second = mapping(rings=[{'beads': ['B01', 'B02'], 'scale': 1.2}])
    parameterization.save(second, revision())

    listed = parameterization.records()

    assert {record['mapping_content_hash'] for record in listed} == {
        parameterization.content_identity(first), parameterization.content_identity(second)}
    (parameterization.records_root() / f'{"f" * 64}.json').write_text('{not json')
    assert {record['mapping_content_hash'] for record in parameterization.records()} == {
        parameterization.content_identity(first), parameterization.content_identity(second)}


def test_the_engines_are_published_once_for_the_panel_to_render():
    """The panel's select reads this rather than keeping a second copy of the vocabulary: another
    engine is one edit here, and the picker's AA reference follows from `needs_reference`."""
    published = parameterization.published()

    assert [engine['value'] for engine in published] == list(parameterization.ENGINES)
    assert [engine['label'] for engine in published] == [parameterization.ENGINE_LABELS[name]
                                                         for name in parameterization.ENGINES]
    # Every engine left fits to an ensemble; the reference-free one was removed with its button.
    assert {engine['value'] for engine in published} == {'fast-forward', 'bartender'}
    assert all(engine['needs_reference'] for engine in published)
    assert all(isinstance(engine[key], (str, bool)) for engine in published
               for key in ('value', 'label', 'needs_reference'))


def test_the_source_identity_is_the_mappings_content_and_not_its_file():
    candidate = mapping()
    parameterization.save(candidate, revision())
    identities = parameterization.identities(candidate)
    assert identities['mapping_content_hash'] == mappings.content_identity(candidate)
    assert identities['mapping_hash'] == mappings.candidate_identity(candidate)


def test_a_record_written_before_numbers_were_normalised_is_still_this_mappings():
    """The identity bug the fit panel showed: one mapping, two digests, and a revision filed under the wrong one.

    A candidate is read out of JSON by the browser and posted back, and JavaScript writes a stored `1.0` as `1`.
    While the identity hashed the two spellings differently, a fit queued from the panel was keyed by the posted
    digest while every other reader asked by the file's -- so the panel reported "no parameterization" for a mapping
    it had just fitted. The identity now normalises the number, and a record already on disk under the old digest is
    still found, which is what this pins.
    """
    candidate = mapping(rings=[{'name': 'R1', 'atoms': [1, 2, 3], 'scale': 1.0}])
    saved = parameterization.save(candidate, revision())
    path = parameterization.records_root() / f"{parameterization.content_identity(candidate)}.json"

    # Rewrite the record the way it was written before the change: under the legacy digest, saying so itself.
    legacy = mappings.legacy_content_identity(candidate)
    assert legacy != parameterization.content_identity(candidate), 'the two digests must differ for this to test anything'
    record = json.loads(path.read_text())
    record['mapping_content_hash'] = legacy
    for item in record.get('revisions') or []:
        item['mapping_content_hash'] = legacy
    path.unlink()
    (parameterization.records_root() / f'{legacy}.json').write_text(json.dumps(record))

    assert parameterization.current(mapping(rings=[{'name': 'R1', 'atoms': [1, 2, 3], 'scale': 1.0}]))['revision'] == 1
    assert parameterization.current(candidate)['revision'] == saved['revision']

    # The half that fixes the panel: the same mapping posted back the way a browser sends it -- an integer, not a
    # float -- is the same mapping, so a fit queued from the panel is addressed by the digest the file produces.
    as_posted = mapping(rings=[{'name': 'R1', 'atoms': [1, 2, 3], 'scale': 1}])
    assert parameterization.content_identity(as_posted) == parameterization.content_identity(candidate)


# --- editing a stored revision's terms ------------------------------------------------------------------------


def _sha(revision):
    return parameterization.revision_sha256(revision)


@pytest.mark.parametrize('engine, edited, editable, save_in_place, reason', [
    ('fast-forward', False, True, False, 'fitted by fast-forward; Save as new to edit it'),
    ('bartender', False, True, False, 'fitted by bartender; Save as new to edit it'),
    ('fast-forward', True, True, True, ''),
    ('martini-reference', False, False, False, 'a Martini 3 reference transcription is read-only'),
    ('martini-reference', True, False, False, 'a Martini 3 reference transcription is read-only'),
])
def test_the_edit_gate_is_the_one_rule_for_fits_and_transcriptions(engine, edited, editable, save_in_place, reason):
    """A fit's own revision is editable but its first edit is Save as new; a transcription is not editable at all.

    `edited_terms` is the one marker of hand edits, and it unlocks Save in place only on a revision that may be
    edited -- a transcription carrying an edit history is still a transcription, not a fit.
    """
    payload = revision(engine=engine,
                       edited_terms=[{'id': 'bonds:1', 'after': [0.33, 6200]}] if edited else [])
    gate = parameterization.edit_gate(payload)

    assert gate['editable'] is editable
    assert gate['save_in_place'] is save_in_place
    assert gate['reason'] == reason


def test_the_edit_gate_is_derived_at_read_time_and_never_enters_the_digest():
    candidate = mapping()
    stored = parameterization.save(candidate, revision())

    assert 'parameters_editable' not in stored and 'save_in_place' not in stored
    assert parameterization.edit_gate(stored)['save_in_place'] is False
    assert parameterization.revision_sha256(stored) == _sha(parameterization.get(candidate, 1))


def test_saving_terms_in_place_rewrites_the_current_revision_and_says_manual():
    """Save in place keeps the revision's number and provenance and rewrites only its topology.

    It writes only a revision that already carries hand edits -- a fresh fit's first edit is Save as new -- so this
    edits the clone that Save as new produced. The Source column is the reason `edited_terms` is recorded: the stored
    topology no longer says the fit wrote that value, so the row must read ``manual``. The checks are cleared because
    they described the pre-edit terms.
    """
    candidate = mapping()
    first = parameterization.save(candidate, revision())
    clone = parameterization.save_terms(
        candidate, mode='new', revision=1, expected_revision=1, expected_sha256=_sha(first),
        edits=[{'id': 'bonds:2', 'parameters': [0.32, 6000]}])['current']

    record = parameterization.save_terms(
        candidate, mode='in_place', revision=2, expected_revision=2, expected_sha256=_sha(clone),
        edits=[{'id': 'bonds:2', 'parameters': [0.33, 6200]}])
    updated = record['current']

    assert updated['revision'] == 2 and record['revision'] == 2
    assert '2 3 1 0.33 6200' in updated['topology'] and '1 2 1 0.30 5000' in updated['topology']
    assert updated['engine'] == first['engine'] and updated['options'] == first['options']
    assert updated['checks'] == {}
    sources = {row['id']: row['source'] for row in updated['sources']}
    assert sources['bonds:2'] == 'manual' and sources['bonds:1'] == 'ff_inter'
    assert updated['edited_terms'] == [{
        'id': 'bonds:2', 'kind': 'bonds', 'beads': ['B02', 'B03'], 'function': '1',
        'before': [0.32, 6000], 'after': [0.33, 6200.0], 'at': updated['edited_terms'][0]['at']}]
    assert _sha(updated) != _sha(first), 'the digest names the terms, so an edit changes it'
    assert [item['revision'] for item in record['revisions']] == [1, 2]


def test_save_in_place_is_refused_on_a_fresh_fit_revision_and_writes_nothing():
    """The one rule at the writer: a fit's own revision has no hand edits, so Save as new is the way to edit it."""
    candidate = mapping()
    first = parameterization.save(candidate, revision(engine='bartender'))
    before = parameterization.get(candidate, 1)

    with pytest.raises(parameterization.Refused, match='fitted by bartender; Save as new'):
        parameterization.save_terms(candidate, mode='in_place', revision=1, expected_revision=1,
                                    expected_sha256=_sha(first),
                                    edits=[{'id': 'bonds:1', 'parameters': [0.3, 5000]}])

    assert parameterization.get(candidate, 1) == before, 'a refused save writes nothing'


def test_save_as_new_is_the_first_edit_and_the_clone_then_saves_in_place():
    candidate = mapping()
    first = parameterization.save(candidate, revision())

    record = parameterization.save_terms(
        candidate, mode='new', revision=1, expected_revision=1, expected_sha256=_sha(first),
        edits=[{'id': 'bonds:2', 'parameters': [0.33, 6200]}])
    clone = record['current']

    assert record['revision'] == 2
    assert clone['edited_terms'], 'the clone carries the hand edit'
    assert parameterization.edit_gate(clone)['save_in_place'] is True

    updated = parameterization.save_terms(
        candidate, mode='in_place', revision=2, expected_revision=2, expected_sha256=_sha(clone),
        edits=[{'id': 'bonds:2', 'parameters': [0.34, 6300]}])

    assert updated['current']['revision'] == 2
    assert '2 3 1 0.34 6300' in updated['current']['topology']


def test_a_stored_transcription_is_readable_and_read_only_and_a_refused_save_writes_nothing():
    """Old records carry a `martini-reference` revision -- the seed wrote them before 2026-11-12.

    Nothing may create one now, but the record is still read (``describe``) and the gate keeps it read-only in both
    modes: the revision was never fitted, so there is no fit to clone and no table to edit.
    """
    candidate = mapping()
    parameterization.save(candidate, revision())
    path = parameterization.records_root() / f'{parameterization.content_identity(candidate)}.json'
    record = json.loads(path.read_text())
    transcription = {'engine': 'martini-reference', 'engine_default_source': 'martini-reference',
                     'transcription': {'entry': 'SUCR'}, 'ensemble': {'frames': None}}
    for entry in record['revisions'] + [record['current']]:
        entry.update(transcription)
    path.write_text(json.dumps(record))
    stored = parameterization.get(candidate, 1)

    assert 'transcribed from the published Martini 3 reference SUCR' in parameterization.describe(stored)
    assert parameterization.edit_gate(stored) == {
        'editable': False, 'save_in_place': False,
        'reason': 'a Martini 3 reference transcription is read-only'}
    for mode in ('in_place', 'new'):
        with pytest.raises(parameterization.Refused, match='read-only'):
            parameterization.save_terms(
                candidate, mode=mode, revision=1, expected_revision=1, expected_sha256=_sha(stored),
                edits=[{'id': 'bonds:1', 'parameters': [0.3, 5000]}])
    assert parameterization.get(candidate, 1)['topology'] == stored['topology'], 'a refused save writes nothing'


def test_saving_terms_in_place_refuses_a_stale_number_digest_or_earlier_revision():
    candidate = mapping()
    first = parameterization.save(candidate, revision())
    second = parameterization.save(candidate, revision(engine='bartender'))

    with pytest.raises(parameterization.StaleRevision, match='changed; reload'):
        parameterization.save_terms(candidate, mode='in_place', revision=2, expected_revision=1,
                                    expected_sha256=_sha(second), edits=[{'id': 'bonds:1', 'parameters': [0.3, 1]}])
    with pytest.raises(parameterization.StaleRevision, match='changed since it was read'):
        parameterization.save_terms(candidate, mode='in_place', revision=2, expected_revision=2,
                                    expected_sha256='0' * 64, edits=[{'id': 'bonds:1', 'parameters': [0.3, 1]}])
    with pytest.raises(parameterization.Refused, match='not the current revision'):
        parameterization.save_terms(candidate, mode='in_place', revision=1, expected_revision=2,
                                    expected_sha256=_sha(first), edits=[{'id': 'bonds:1', 'parameters': [0.3, 1]}])
    with pytest.raises(KeyError, match='Unknown parameterization revision'):
        parameterization.save_terms(candidate, mode='in_place', revision=9, expected_revision=2,
                                    expected_sha256=_sha(second), edits=[{'id': 'bonds:1', 'parameters': [0.3, 1]}])
    assert parameterization.current(candidate)['revision'] == 2, 'a refused save writes nothing'


def test_saving_terms_in_place_validates_every_edit_against_the_stored_topology():
    candidate = mapping()
    topology = TOPOLOGY.replace(
        '[ bonds ]', '[ virtual_sitesn ]\n4 1 1 2 3\n\n[ constraints ]\n1 2 1 0.31\n\n[ bonds ]')
    item = parameterization.save(candidate, revision(topology=topology))
    clone = parameterization.save_terms(
        candidate, mode='new', revision=1, expected_revision=1, expected_sha256=_sha(item),
        edits=[{'id': 'bonds:1', 'parameters': [0.29, 4900]}])['current']
    for edits, message in [
        ([{'id': 'virtual_sitesn:1', 'parameters': []}], "virtual site's parents"),
        ([{'id': 'bonds:9', 'parameters': [0.3, 5000]}], 'No editable term'),
        ([{'id': 'bonds:1', 'parameters': [0.3, 5000, 1]}], 'takes 2 parameters'),
        ([{'id': 'bonds:1', 'parameters': [9, 5000]}], 'between 0.01 and 2'),
        ([{'id': 'constraints:1', 'parameters': [9]}], 'between 0.01 and 2'),
        ([], 'No parameter edits'),
    ]:
        with pytest.raises(ValueError, match=message):
            parameterization.save_terms(candidate, mode='in_place', revision=2, expected_revision=2,
                                        expected_sha256=_sha(clone), edits=edits)
    # The stored terms are untouched by every refusal above.
    assert parameterization.get(candidate, 2)['topology'] == clone['topology']


def test_a_rigid_constraints_length_is_editable_and_reads_manual():
    """The mapping's ring target is the starting value, not a lock; a revision may override it and says so."""
    candidate = mapping()
    topology = TOPOLOGY.replace('[ bonds ]', '[ constraints ]\n1 2 1 0.31\n\n[ bonds ]')
    item = parameterization.save(candidate, revision(topology=topology))
    clone = parameterization.save_terms(
        candidate, mode='new', revision=1, expected_revision=1, expected_sha256=_sha(item),
        edits=[{'id': 'bonds:1', 'parameters': [0.30, 5100]}])['current']
    record = parameterization.save_terms(
        candidate, mode='in_place', revision=2, expected_revision=2, expected_sha256=_sha(clone),
        edits=[{'id': 'constraints:1', 'parameters': [0.33]}])

    saved = record['current']
    assert '1 2 1 0.33' in saved['topology']
    edits = {term['id']: term for term in saved['edited_terms']}
    assert edits['constraints:1']['before'] == [0.31]
    assert edits['constraints:1']['after'] == [0.33]
    assert {row['id']: row['source'] for row in saved['sources']}['constraints:1'] == 'manual'


def test_saving_terms_as_new_clones_the_shown_revision_and_leaves_it_alone():
    candidate = mapping()
    first = parameterization.save(candidate, revision())
    before = parameterization.get(candidate, 1)

    record = parameterization.save_terms(
        candidate, mode='new', revision=1, expected_revision=1, expected_sha256=_sha(first),
        edits=[{'id': 'bonds:2', 'parameters': [0.33, 6200]}])
    cloned = record['current']

    assert (record['revision'], cloned['revision']) == (2, 2)
    assert parameterization.get(candidate, 1) == before, 'the source revision is not rewritten'
    assert '2 3 1 0.33 6200' in cloned['topology']
    for key in ('engine', 'ensemble', 'aa_reference', 'options', 'engine_default_source'):
        assert cloned[key] == before[key], key
    assert cloned['checks'] == {}
    assert any('cloned from revision 1' in note for note in cloned['notes'])
    sources = {row['id']: row['source'] for row in cloned['sources']}
    assert sources['bonds:2'] == 'manual' and sources['bonds:1'] == 'ff_inter'


def test_saving_terms_as_new_from_an_earlier_revision_makes_the_clone_current():
    candidate = mapping()
    first = parameterization.save(candidate, revision())
    parameterization.save(candidate, revision(engine='bartender'))

    record = parameterization.save_terms(
        candidate, mode='new', revision=1, expected_revision=2, expected_sha256=_sha(first),
        edits=[{'id': 'angles:1', 'parameters': [118, 30]}])

    assert record['revision'] == 3 and record['current']['revision'] == 3
    assert record['current']['engine'] == 'fast-forward', 'the clone keeps the shown revision\'s engine'
    assert [item['revision'] for item in record['revisions']] == [1, 2, 3]


def test_a_stored_transcription_is_validated_and_described_but_a_fit_no_longer_creates_one():
    """`validate`/`describe` still accept a stored transcription, because old records carry one.

    The writer does not: a revision `save` produces is fitted, and the published reference is display-only -- a CG
    run consumes it directly, so there is no seed and no second way to get the same model.
    """
    payload = revision(engine='martini-reference', revision=1, transcription={'entry': 'SUCR'})

    with pytest.raises(ValueError, match='transcription is read-only'):
        parameterization.save(mapping(), payload)

    stored = parameterization.validate(payload)
    assert stored['engine'] == 'martini-reference'
    assert 'transcribed from the published Martini 3 reference SUCR' in parameterization.describe(stored)
    assert [item['value'] for item in parameterization.published()] == list(parameterization.ENGINES)
    assert parameterization.ENGINES == ('fast-forward', 'bartender')
