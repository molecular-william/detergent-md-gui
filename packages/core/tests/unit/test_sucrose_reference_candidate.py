"""The sucrose candidate, checked against the reference entry its connectivity identifies as.

This is the deliverable for "reproduce the reference mapping from the atomic structure": two residues of
three physical beads plus a massless ring site, the reference's bead types, the bridge oxygen on the
residue the reference puts it on, and one inter-residue connection between the two glycosidic beads.
"""
import pytest
from dashboard import paths
from dashboard.models.mappings import context as mapping_context
from dashboard.models.sugars import candidate, reference

MOLECULES = paths.DEFAULT.project_root / 'molecules'


@pytest.fixture(scope='module')
def sucrose():
    return mapping_context.as_structure(mapping_context.build_context(MOLECULES, 'Sucrose'))


@pytest.fixture(scope='module')
def candidate_data(sucrose):
    return candidate(sucrose, 'Sucrose')


def reference_beads(entry, residue):
    return reference.signature(reference.entry(entry))['residues'][residue]


def test_the_candidate_has_two_residues_of_three_beads_and_a_site(candidate_data):
    assert [bead['name'] for bead in candidate_data['beads']] == ['S1A', 'S1B', 'S1C', 'S1VS',
                                                                  'S2A', 'S2B', 'S2C', 'S2VS']
    assert [bead['residue'] for bead in candidate_data['beads']] == [1, 1, 1, 1, 2, 2, 2, 2]


def test_the_bead_types_are_the_reference_types(candidate_data):
    expected = [bead['type'] for bead in reference_beads('SUCR', 1)]
    expected += [bead['type'] for bead in reference_beads('SUCR', 2)]
    assert [bead['type'] for bead in candidate_data['beads']] == expected


def test_the_heavy_atoms_partition_as_the_reference_requires(candidate_data):
    counts = [len(bead['atoms']) for bead in candidate_data['beads'] if bead['atoms']]
    assert counts == [4, 4, 4, 3, 4, 4]
    assert sum(counts) == 23, 'every heavy atom of sucrose, counted exactly once'


def test_the_bridge_oxygen_sits_on_the_residue_the_reference_puts_it_on(candidate_data):
    """Residue 1 bead A is the reference's glycosidic bead (four heavy atoms); residue 2's is the
    receiving bead, which lacks the bridge oxygen and therefore has three."""
    first_length = len(next(bead for bead in candidate_data['beads'] if bead['name'] == 'S1A')['atoms'])
    second = next(bead for bead in candidate_data['beads'] if bead['name'] == 'S2A')
    assert first_length == 4
    assert len(second['atoms']) == 3
    assert second['type'] == 'SN6'


def test_the_virtual_sites_name_their_own_residues_beads(candidate_data):
    parents = [bead['virtual_site']['parents'] for bead in candidate_data['beads']
               if bead.get('virtual_site')]
    assert parents == [['S1A', 'S1B', 'S1C'], ['S2A', 'S2B', 'S2C']]


def test_the_only_inter_residue_connection_joins_the_two_glycosidic_beads(candidate_data):
    residue_of = {bead['name']: bead['residue'] for bead in candidate_data['beads']}
    cross = [edge for edge in candidate_data['connections']
             if residue_of[edge[0]] != residue_of[edge[1]]]
    assert cross == [['S1A', 'S2A']]


def test_the_ring_records_carry_the_reference_bead_groups_and_scale(candidate_data):
    assert [ring['beads'] for ring in candidate_data['rings']] == [['S1A', 'S1B', 'S1C'],
                                                                  ['S2A', 'S2B', 'S2C']]
    assert [ring['scale'] for ring in candidate_data['rings']] == [1.15, 1.15]


def test_the_candidate_records_the_reference_it_follows(candidate_data):
    assert candidate_data['reference']['entry'] == 'SUCR'
    assert candidate_data['reference']['stereochemistry'] == 'unresolved'
    assert candidate_data['reference']['order_basis'] == 'ring size and linkage letters'
    assert candidate_data['name'] == 'Sucrose carbohydrate paper draft'
    assert candidate_data['status'] == 'candidate-unvalidated'


@pytest.fixture(scope='module')
def trehalose_data():
    structure = mapping_context.as_structure(mapping_context.build_context(MOLECULES, 'Trehalose'))
    return candidate(structure, 'Trehalose')


def test_a_symmetric_one_one_linkage_reproduces_the_published_bead_types(trehalose_data):
    """Trehalose's 1,1 linkage makes both linkage carbons C1, so the published entry's choice of which ring owns
    the bridging oxygen is the tie-break: residue 1 bead A is the glycosidic bead (SP1r) and residue 2's is the
    connecting linker (SN6). The candidate has to reproduce that order to conform, and the site carriers take
    their residue from their parents rather than the published column."""
    assert trehalose_data['reference']['entry'] == 'TREH'
    assert [bead['type'] for bead in trehalose_data['beads']] == [
        bead['type'] for bead in reference_beads('TREH', 1)] + [
        bead['type'] for bead in reference_beads('TREH', 2)]
    assert reference.conform(trehalose_data, 'TREH') == []


def _candidate(molecule):
    structure = mapping_context.as_structure(mapping_context.build_context(MOLECULES, molecule))
    return candidate(structure, molecule)


@pytest.fixture(scope='module')
def lactose_data():
    return _candidate('Lactose')


@pytest.fixture(scope='module')
def glucose_data():
    return _candidate('Glucose')


@pytest.fixture(scope='module')
def maltose_data():
    return _candidate('Maltose')


def test_lactose_identifies_and_conforms_to_its_own_lac_entry(lactose_data):
    assert lactose_data['reference']['entry'] == 'LAC'
    assert reference.conform(lactose_data, 'LAC') == []
    assert reference.accepts_identity(lactose_data, 'Lactose', 'LAC') is True
    assert reference.layout_note(lactose_data, 'LAC') is None


def test_glucose_conforms_to_glc_although_its_layout_identifies_gal(glucose_data):
    """Every aldohexose has the same four-bead pattern, so identification is blind to the stereochemistry that makes
    glucose glucose and its first candidate is `GAL`. `GLC` and `GAL` are that one mapping with different published
    lengths, so the molecule's own identity may select `GLC`; the note says the layout could not."""
    assert glucose_data['reference']['entry'] == 'GAL'
    assert reference.conform(glucose_data, 'GLC') == []
    assert reference.accepts_identity(glucose_data, 'Glucose', 'GLC') is True
    assert reference.accepts_identity(glucose_data, 'Glucose', 'SUCR') is False

    note = reference.layout_note(glucose_data, 'GLC')
    assert 'GLC' in note and 'GAL' in note
    assert 'cannot distinguish' in note


def test_maltose_is_not_accepted_as_lactose(maltose_data):
    """Maltose's layout matches `LAC` and conforms to it, and the identifier cannot tell the two apart; only the
    published-for map separates them, so a molecule the entry is not published for stays refused."""
    assert maltose_data['reference']['entry'] == 'LAC'
    assert reference.conform(maltose_data, 'LAC') == []
    assert reference.accepts_identity(maltose_data, 'Maltose', 'LAC') is False
    assert reference.accepts_identity(maltose_data, 'Maltose', 'GLC') is False

