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

TOPOLOGY = ('[ moleculetype ]\nMOL 1\n\n[ atoms ]\n'
            '1 C1 1 MOL B01 1 0 72\n2 C1 1 MOL B02 2 0 72\n3 C1 1 MOL B03 3 0 72\n\n'
            '[ bonds ]\n1 2 1 0.30 5000\n2 3 1 0.31 5000\n\n'
            '[ angles ]\n1 2 3 1 120 25\n\n'
            '[ dihedrals ]\n1 2 3 1 -102.273 36.636 2\n')


def mapping(**overrides):
    candidate = {'name': 'DDM', 'beads': [{'name': 'B01'}, {'name': 'B02'}, {'name': 'B03'}],
                 'rings': [], 'connections': []}
    candidate.update(overrides)
    return candidate


def revision(**overrides):
    payload = {'engine': 'fast-forward', 'topology': TOPOLOGY,
               'options': {'constraints_threshold': 10000.0, 'temperature_k': 300.0,
                           'torsion_model': 'legacy', 'torsion_scale': 1.0},
               'ensemble': {'frames': 20001, 'trajectory': '2_mapping/mapped.xtc',
                            'source': 'the mapped AA frames'},
               'aa_reference': {'run_id': 'a54ac8f64710', 'reference_sha256': 'ab' * 32,
                                'molecule_identity': 'cd' * 32, 'temperature_k': 300.0,
                                'production_ns': 10.0},
               'terms': {'bonds': 2, 'angles': 1, 'dihedrals': 1},
               'engine_default_source': 'ff_inter',
               'checks': {'dihedral-fit': {'rows': []}, 'bonded-cross-check': {'rows': []}}}
    payload.update(overrides)
    return payload


def test_a_mapping_with_no_record_has_no_current_revision_and_that_is_a_state_not_a_fault():
    """D5's second honest state: the run fits the model and records that it did."""
    assert parameterization.current(mapping()) is None
    assert parameterization.revisions(mapping()) == []
    assert parameterization.summary(mapping())['parameterized'] is False
    assert parameterization.summary(mapping())['revision'] is None


def test_revisions_accumulate_and_the_newest_is_current():
    candidate = mapping()
    first = parameterization.save(candidate, revision())
    second = parameterization.save(candidate, revision(engine='bartender'))

    assert (first['revision'], second['revision']) == (1, 2)
    assert [item['revision'] for item in parameterization.revisions(candidate)] == [1, 2]
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
    assert [item['revision'] for item in parameterization.revisions(candidate)] == [1, 2]


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
    """The revision strip and a run's manifest hold hashes, not the mapping document: the store answers
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
    """The panel's select reads this rather than keeping a second copy of the vocabulary: a fourth
    engine is one edit, and the picker's AA reference cannot be required for a draft that reads none."""
    published = parameterization.published()

    assert [engine['value'] for engine in published] == list(parameterization.ENGINES)
    assert [engine['label'] for engine in published] == [parameterization.ENGINE_LABELS[name]
                                                         for name in parameterization.ENGINES]
    assert {engine['value']: engine['needs_reference'] for engine in published} == {
        'fast-forward': True, 'bartender': True, 'reference-informed': False}
    assert all(isinstance(engine[key], (str, bool)) for engine in published
               for key in ('value', 'label', 'needs_reference'))


def test_the_source_identity_is_the_mappings_content_and_not_its_file():
    candidate = mapping()
    parameterization.save(candidate, revision())
    identities = parameterization.identities(candidate)
    assert identities['mapping_content_hash'] == mappings.content_identity(candidate)
    assert identities['mapping_hash'] == mappings.candidate_identity(candidate)
