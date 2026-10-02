"""The cross-molecule reader, with reports built by the test rather than borrowed from the workspace."""
from dashboard.analysis.runs import transferability


def _candidate(pairs, residue=1, name_prefix='S'):
    """A mapping in the shape a report names beads in: a residue, a letter, a name, and a type."""
    return {'beads': [{'letter': letter, 'residue': residue, 'name': f'{name_prefix}{residue}{letter}',
                       'type': bead_type} for letter, bead_type in pairs]}


def _report(rows):
    return {'pairs': {'rows': rows}}


def _row(pair, aa, cg=None):
    return {'pair': pair, 'aa': {'mean': aa}, 'cg': {'mean': aa if cg is None else cg}}


def test_the_same_types_in_two_molecules_are_compared_to_each_other():
    """The sucrose ring edge and the trehalose ring edge are the same interaction if the types are a library."""
    entries = {
        'Maltose': {'candidate': _candidate([('A', 'SP1r'), ('B', 'SP1r')]),
                    'report': _report([_row([[1, 'A'], [1, 'B']], 0.310)])},
        'Trehalose': {'candidate': _candidate([('A', 'SP1r'), ('B', 'SP1r')]),
                      'report': _report([_row([[1, 'A'], [1, 'B']], 0.316)])},
    }
    result = transferability.compare(entries)
    signature = result['signatures'][0]

    assert signature['types'] == ['SP1r', 'SP1r'] and signature['role'] == 'intra'
    assert sorted(signature['molecules']) == ['Maltose', 'Trehalose']
    assert signature['molecules']['Maltose']['atomistic_mean_nm'] == 0.310
    assert 0 < signature['spread_pct'] < 3, 'two rings a few percent apart is the whole point of the number'
    assert result['molecules'] == ['Maltose', 'Trehalose']


def test_a_pair_in_one_molecule_only_is_not_padded():
    entries = {
        'Maltose': {'candidate': _candidate([('A', 'C1'), ('B', 'C1')]),
                    'report': _report([_row([[1, 'A'], [1, 'B']], 0.47)])},
        'Sucrose': {'candidate': _candidate([('A', 'SP1r'), ('B', 'SP1r')]),
                    'report': _report([_row([[1, 'A'], [1, 'B']], 0.30)])},
    }
    result = transferability.compare(entries)
    tails = [entry for entry in result['signatures'] if entry['types'] == ['C1', 'C1']]

    assert len(tails) == 1
    assert list(tails[0]['molecules']) == ['Maltose']
    assert tails[0]['spread_pct'] is None, 'one molecule has no spread to report'


def test_a_ring_edge_and_a_linkage_are_different_signatures_even_with_the_same_types():
    """Same two types, different interaction: inside one residue, or joining two."""
    entries = {'Sucrose': {'candidate': _candidate([('A', 'SP1r'), ('B', 'SP1r')]),
                           'report': _report([_row([[1, 'A'], [1, 'B']], 0.31),
                                              _row([[1, 'A'], [2, 'B']], 0.43)])}}
    result = transferability.compare(entries)
    roles = {entry['role'] for entry in result['signatures']}

    assert roles == {'intra', 'inter'}


def test_a_queue_is_a_bead_and_resolves_to_its_type():
    entries = {'Sucrose': {'candidate': _candidate([('A', 'SP1r'), ('VS', 'TC4')]),
                           'report': _report([_row([[1, 'A'], [1, 'VS']], 0.19)])}}
    result = transferability.compare(entries)

    assert result['signatures'][0]['types'] == ['SP1r', 'TC4']


def test_a_report_with_no_rows_is_still_a_molecule():
    result = transferability.compare({'Maltose': {'candidate': _candidate([('A', 'SP1r')]), 'report': _report([])}})

    assert result['molecules'] == ['Maltose'] and result['signatures'] == []
