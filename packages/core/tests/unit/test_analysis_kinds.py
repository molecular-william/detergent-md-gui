"""One row per analysis kind, and every reader of that vocabulary derives from it.

Phase 3 of the audit's plan. Four lists described the same thirteen kinds and nothing compared them: the names in
`worker.KINDS`, the source patterns in `worker.PATTERNS`, the dispatch chain in `worker.execute` (nine `elif`s and a
five-entry mapping), and `metadata.DESCRIPTIONS` -- which held seventeen entries for thirteen kinds, because three of
them name the evidence sections of the carbohydrate-validation report rather than analyses at all. A kind missing from
one of the lists failed silently: unreachable, or handed no inputs, or rendered under a title the code invented by
replacing hyphens with spaces.

The table is the single source now, so the rows themselves are not re-asserted here: a test that reads the table and
compares it with the table cannot fail. What can fail is a reader inventing an answer for a kind nobody registered,
which is the test below.
"""
import pytest


def test_an_unknown_kind_is_refused_rather_than_given_an_invented_title():
    """The fallback that made this silent: `kind.replace('-', ' ').title()` reads as a real title.

    A caller asking about a kind nobody registered was answered with a plausible-looking description instead of an
    error, so a kind that was dropped from the vocabulary kept rendering -- with the right shape and no content.
    """
    from dashboard.analysis.metadata import describe
    with pytest.raises(ValueError, match='Unknown analysis kind'):
        describe('not-a-kind')
