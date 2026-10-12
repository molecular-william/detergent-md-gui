"""`workflow._plan_pairs` reads a run's stage plan, and the adapters record it in more than one shape.

D5 in the audit. The converter assumed `Stage` records or `(name, relative)` pairs, and its fallback indexed
whatever else it was handed. An `aa_cg` prepared manifest records a plain list of names, so the fallback read the
first two *characters* of the first two names:

    _plan_pairs({'run_type': 'aa_cg', 'stage_plan': ['AA reference', 'trajectory mapping']})
    -> [['A', 'A'], ['t', 'r']]

That is the failure mode this file exists to prevent, and the reason its third test asserts the *manifest's* shape
rather than only the converter's tolerance: handling a bad shape at the reader leaves the writer free to keep
producing it.
"""
import pytest

from dashboard.execution.adapters import cg
from dashboard.execution.stages import Stage
from dashboard.execution.workflow import _plan_pairs, stage_definitions

AA_CG_NAMES = {'run_type': 'aa_cg', 'stage_plan': ['AA reference', 'trajectory mapping']}


def test_a_name_list_is_resolved_through_the_stage_definitions_rather_than_indexed():
    """The third shape: names only. Their relative paths come from the definitions, not from the string."""
    pairs = _plan_pairs(AA_CG_NAMES)
    expected = stage_definitions(AA_CG_NAMES)[0]
    assert pairs, 'a name list must not produce an empty plan'
    assert [name for name, _ in pairs] == ['AA reference', 'trajectory mapping']
    assert pairs == [list(pair) for pair in expected[:2]], (
        'the resolved pairs are the definitions for those names, not the first two characters of each')


def test_a_stage_record_and_a_pair_still_convert():
    """The two shapes the converter already knew, kept working -- a fix must not narrow what it accepts."""
    records = {'run_type': 'pdc', 'stage_plan': [Stage('AA reference', '1_AA-reference/aa.sh')]}
    pairs = {'run_type': 'aa_cg', 'stage_plan': [['AA reference', '1_AA-reference/aa.sh']]}
    for metadata in (records, pairs):
        assert _plan_pairs(metadata) == [['AA reference', '1_AA-reference/aa.sh']]


def test_an_entry_the_converter_cannot_read_raises_rather_than_guessing():
    """The old fallback read characters off whatever it was given. A shape nobody taught it is an error."""
    with pytest.raises((TypeError, ValueError)):
        _plan_pairs({'run_type': 'aa_cg', 'stage_plan': [42]})
    with pytest.raises((TypeError, ValueError)):
        _plan_pairs({'run_type': 'aa_cg', 'stage_plan': ['a name that is not a stage']})


def test_a_cg_prepared_manifest_records_pairs_so_the_shape_cannot_come_back():
    """A source guard, and its limits are worth stating: it reads the adapter's text, so it catches the writer
    regressing to bare names but proves nothing about behaviour. The behavioural cover for the *reader* is the first
    test above; this one exists so the tolerant branch is for manifests written before the fix rather than after.
    """
    import inspect
    source = inspect.getsource(cg)
    assert 'stage_plan=[name for name, _ in stage_plan]' not in source, (
        'the CG adapter must record (name, relative) pairs, not bare names')
