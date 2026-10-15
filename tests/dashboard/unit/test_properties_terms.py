"""The two reader rules a paper-scale comparison rests on, as properties rather than examples.

`transferability` writes a term's beads into a string and reads them back with a regex, and it
withholds a dihedral's spread because a mean of a wrapped angle is not a difference -- both claims
the repository states in prose (`AGENTS.md`: "a dihedral's spread is withheld ... That is asserted,
not merely commented"). A hand-built four-bead example passes while the regex drops the fourth bead,
so the round trip is drawn from the strings the writer can produce, at every length a term has.

The spread is not a round trip: it is recomputed here from the *result's own* per-molecule means,
which is a second derivation of the same quantity from the same input. The role is recomputed the
same way, from the residues the terms name.

`term_beads` is also the parser the repo calls fuzzable -- it reads a formatted field out of a
published artifact, so the text it receives is whatever a report happened to write. The property is
therefore weaker than a round trip on purpose: for arbitrary text the answer must be *well-formed*
beads, and reading must never raise.
"""
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dashboard.analysis.runs import transferability

PROFILE = settings(max_examples=150, deadline=None, suppress_health_check=(HealthCheck.too_slow,))

# A letter as the reports spell it: `A`, `SP1r`-style names are not what this field carries, but a
# longer identifier is legal there, so the round trip draws one.
LETTERS = st.text(alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', min_size=1, max_size=4)
BEADS = st.lists(st.tuples(st.integers(min_value=1, max_value=99), LETTERS), min_size=2, max_size=6)


def written(beads):
    """A term's beads the way the comparison writes them."""
    return ' - '.join(f'({residue},{letter})' for residue, letter in beads)


def two_ring_candidate():
    """A mapping whose beads sit in two residues, as a disaccharide's do."""
    return {'beads': [{'letter': letter, 'residue': residue, 'name': f'S{residue}{letter}', 'type': bead_type}
                      for residue, pairs in ((1, [('A', 'SP1r'), ('B', 'SP1r')]), (2, [('A', 'SN6'), ('B', 'SP4r')]))
                      for letter, bead_type in pairs]}


def entry(beads, mean, section='bonds'):
    """One molecule's entry: the same candidate everywhere, one term row per call."""
    return {'candidate': two_ring_candidate(),
            'report': {'pairs': {'rows': []},
                       'terms': [{'section': section, 'beads': written(beads),
                                  'aa': {'mean': mean}, 'cg': {'mean': mean}}]}}


@PROFILE
@given(BEADS)
def test_a_written_term_reads_back_as_the_beads_it_names(beads):
    """The round trip, at every length a term has: two beads or six, in the order written."""
    assert transferability.term_beads(written(beads)) == [(residue, letter) for residue, letter in beads]


@PROFILE
@given(st.text())
def test_arbitrary_text_reads_as_no_beads_or_well_formed_ones(text):
    """What a report wrote is not guaranteed to look like a term, and reading it must not raise."""
    beads = transferability.term_beads(text)

    for residue, letter in beads:
        assert isinstance(residue, int) and residue >= 0
        assert isinstance(letter, str) and letter == letter.strip()
        assert ',' not in letter and ')' not in letter, 'a bead name cannot carry the delimiters'


@PROFILE
@given(residue=st.integers(min_value=0, max_value=999), letter=LETTERS)
def test_a_group_that_is_never_closed_is_not_a_bead(residue, letter):
    """An unterminated group must not swallow the text that follows it."""
    assert transferability.term_beads(f'({residue},{letter}') == []
    assert transferability.term_beads(f'({residue},{letter}) - ({residue + 1},{letter}') == [(residue, letter)]


@pytest.mark.parametrize('value', [None, 0, 12.5, [], {}, object()])
def test_a_field_that_is_not_text_reads_as_no_beads(value):
    """`row.get('beads')` is absent or null in a report that predates the field, and both are read."""
    assert transferability.term_beads(value) == []


@PROFILE
@given(section=st.sampled_from(['bonds', 'angles', 'dihedrals']),
       means=st.lists(st.floats(min_value=-180, max_value=180, allow_nan=False, allow_infinity=False),
                      min_size=2, max_size=4))
def test_the_linkage_spread_is_recomputed_the_same_way_or_withheld(section, means):
    """Independent derivation: the result's own per-molecule means, in the order the input gave them."""
    entries = {f'M{index}': entry([(1, 'B'), (2, 'A')], mean, section) for index, mean in enumerate(means)}
    linkages = transferability.compare(entries)['linkages']

    assert len(linkages) == 1, 'one section, one bead-type signature, one role'
    linkage = linkages[0]
    assert linkage['circular'] is (section == 'dihedrals')
    if section == 'dihedrals':
        assert linkage['spread_pct'] is None, 'a wrapped mean has no percentage to report'
    elif sum(means):
        expected = 100.0 * (max(means) - min(means)) / (sum(means) / len(means))

        assert linkage['spread_pct'] == pytest.approx(expected)
    else:
        assert linkage['spread_pct'] is None, 'means that sum to zero have no percentage to report'


@PROFILE
@given(mean=st.floats(min_value=-180, max_value=180, allow_nan=False, allow_infinity=False).filter(bool))
def test_molecules_that_agree_have_a_spread_of_zero(mean):
    """Agreement is a number, not a missing value: `None` means "not comparable", never "identical".

    A mean of exactly zero is excluded because that is the case the guard below covers (a mean that
    sums to zero has no percentage), and it is asserted there rather than skipped here.
    """
    entries = {name: entry([(1, 'B'), (2, 'A')], mean) for name in ('Maltose', 'Sucrose', 'Trehalose')}

    assert transferability.compare(entries)['linkages'][0]['spread_pct'] == 0.0


def test_a_role_is_decided_by_the_residues_the_term_names():
    """Inside one residue is `intra`; a term that joins two is `inter` -- the linkage's whole point."""
    intra = transferability.compare({'Maltose': entry([(1, 'A'), (1, 'B')], 0.31)})['linkages'][0]
    inter = transferability.compare({'Maltose': entry([(1, 'B'), (2, 'A')], 0.27)})['linkages'][0]

    assert intra['role'] == 'intra' and inter['role'] == 'inter'


def test_a_row_naming_fewer_than_two_beads_is_not_a_term():
    """The docstring's rule: one bead is not an interaction, so the row contributes nothing."""
    assert transferability.compare({'Maltose': entry([(1, 'A')], 0.31)})['linkages'] == []
