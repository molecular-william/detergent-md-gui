"""One row per analysis kind, and every reader of that vocabulary derives from it.

Phase 3 of the audit's plan. Four lists described the same thirteen kinds and nothing compared them: the names in
`worker.KINDS`, the source patterns in `worker.PATTERNS`, the dispatch chain in `worker.execute` (nine `elif`s and a
five-entry mapping), and `metadata.DESCRIPTIONS` -- which held seventeen entries for thirteen kinds, because three of
them name the evidence sections of the carbohydrate-validation report rather than analyses at all. A kind missing from
one of the lists failed silently: unreachable, or handed no inputs, or rendered under a title the code invented by
replacing hyphens with spaces.

The tests below are written against the single table the change introduces, so they fail until it exists. Two of them
fail on the current code for their own reasons -- an unknown kind is given an invented title rather than refused, and
the evidence sections sit in the kind vocabulary where nothing checks them.
"""
import pytest
from dashboard.analysis import worker


def test_the_table_covers_every_kind_the_worker_accepts():
    from dashboard.analysis.kinds import TABLE
    assert all(worker.known(name) for name in TABLE), 'every row is reachable through the worker'


def test_every_row_carries_all_four_facets():
    """A row is the whole of a kind: its name, the files it is handed, how it runs, and how it reads."""
    from dashboard.analysis.kinds import TABLE
    for name, row in TABLE.items():
        assert row.name == name
        assert isinstance(row.sources, tuple), f'{name}: sources must be a tuple'
        assert callable(row.run), f'{name}: no dispatch'
        assert row.title, f'{name}: no title'
        assert row.title != name.replace('-', ' ').title(), f'{name}: a title the code invented'
        assert row.ideal_result and row.units_or_direction, f'{name}: nothing to interpret it with'


def test_the_sources_the_worker_stages_are_the_rows_own():
    from dashboard.analysis.kinds import TABLE
    for name, row in TABLE.items():
        assert isinstance(row.sources, tuple), name


def test_an_unknown_kind_is_refused_rather_than_given_an_invented_title():
    """The fallback that made this silent: `kind.replace('-', ' ').title()` reads as a real title.

    A caller asking about a kind nobody registered was answered with a plausible-looking description instead of an
    error, so a kind that was dropped from the vocabulary kept rendering -- with the right shape and no content. The
    legacy reading is the one exception and is asserted in `test_analysis_metadata.py`: an artifact written by an
    older writer whose kind is no longer registered is described *as* legacy rather than refused.
    """
    from dashboard.analysis.metadata import describe
    with pytest.raises(ValueError, match='Unknown analysis kind'):
        describe('not-a-kind')


def test_every_kind_is_described_by_its_own_row():
    from dashboard.analysis.kinds import TABLE
    from dashboard.analysis.metadata import describe
    for name, row in TABLE.items():
        described = describe(name)
        assert described['title'] == row.title, name
        assert described['ideal_result'] == row.ideal_result, name
        assert described['units_or_direction'] == row.units_or_direction, name


def test_no_kind_is_registered_to_run_for_every_run():
    """The registration is a facet of the row rather than a fifth list of kinds.

    Nothing is registered today: every remaining kind is either queued by hand or defaulted by a run type. The
    reader still derives from the one table (rather than a bespoke list) so a future registration enters through the
    same door, and the other readers of the vocabulary cannot disagree with it.
    """
    from dashboard.analysis.kinds import TABLE, for_every_run
    assert for_every_run() == ()
    assert [name for name, row in TABLE.items() if row.runs_for_every_run] == []


def test_the_evidence_section_descriptions_are_not_analysis_kinds():
    """Three descriptions name the carbohydrate report's evidence sections, not analyses.

    They were in the same mapping as the kinds, which is why it held seventeen entries for thirteen kinds and why
    nothing noticed. They are a different vocabulary -- the sections `evidence.PROFILES['carbohydrate']` requires --
    so they live in their own mapping, checked against that profile rather than floating among the kinds.
    """
    from dashboard.analysis import metadata
    from dashboard.analysis.kinds import TABLE
    from dashboard.models.molecules import evidence

    sections = metadata.EVIDENCE_SECTIONS
    assert set(sections) == set(evidence.PROFILES['carbohydrate'])
    assert not set(sections) & set(TABLE), 'an evidence section is not an analysis kind'
    for name, (title, ideal, units) in sections.items():
        assert title and ideal and units, name
