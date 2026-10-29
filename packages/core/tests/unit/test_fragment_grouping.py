"""One grouping for a molecule with no verified template.

Heavy atoms are grouped into connected fragments of at most four. It was written twice --
once over a structure, once over an editor context -- so a change to the size cap or to
the ordering could make the two answers disagree about the same molecule.
"""
from dashboard.models.mappings import schema, suggestions


def chain(count, bonds):
    return {'atoms': [{'id': index, 'heavy': True, 'name': f'C{index}', 'xyz': [float(index), 0.0, 0.0]}
                      for index in range(1, count + 1)],
            'bonds': bonds}


def test_fragments_are_connected_groups_of_at_most_four_lowest_id_first():
    assert schema.fragment_groups(chain(6, [[1, 2], [2, 3], [3, 4], [4, 5], [5, 6]])) == [[1, 2, 3, 4], [5, 6]]
    assert schema.fragment_groups(chain(2, [])) == [[1], [2]], 'ascending by id, not by input order'


def test_only_heavy_atoms_join_a_fragment():
    mixed = {'atoms': [{'id': 1, 'heavy': True, 'name': 'C1', 'xyz': [0.0, 0.0, 0.0]},
                       {'id': 2, 'heavy': False, 'name': 'H1', 'xyz': [0.0, 0.0, 0.0]},
                       {'id': 3, 'heavy': True, 'name': 'C2', 'xyz': [0.0, 0.0, 0.0]}],
             'bonds': [[1, 2], [2, 3]]}
    assert schema.fragment_groups(mixed) == [[1], [3]], 'a hydrogen does not bridge two fragments'


def test_the_automatic_candidate_groups_through_the_same_function(monkeypatch):
    monkeypatch.setattr(schema, 'fragment_groups', lambda structure: [[9]])
    structure = {'atoms': [{'id': 9, 'heavy': True, 'name': 'C9', 'xyz': [0.0, 0.0, 0.0]}], 'bonds': []}
    candidate = schema.automatic_candidate(structure, 'NoVerifiedTemplate')
    assert candidate['beads'][0]['atoms'] == [9]


def test_the_suggestion_fallback_groups_through_the_same_function(monkeypatch):
    """The fallback is reached when no verified template matches; it asks the one grouping."""
    from dashboard.models.mappings import context as mapping_context
    from dashboard.models.mappings import suggestions as module
    from dashboard.models.molecules.packaged import SOURCE

    context = mapping_context.build_context(SOURCE.parent, 'DDM')
    context = {**context, 'capabilities': {'automatic': {'available': True}}}
    monkeypatch.setattr(module.carbohydrates, 'candidate', lambda *args, **kwargs: None)
    monkeypatch.setattr(schema, 'fragment_groups', lambda structure: [[1]])
    result = module.generate_baseline(context, {})
    assert result['available'] is True and result['candidate']['beads'][0]['atoms'] == [1]


def test_the_suggestions_module_keeps_no_grouping_of_its_own():
    assert not hasattr(suggestions, '_connected_groups')
