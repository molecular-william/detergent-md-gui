"""What the mapping validator promises for input nobody wrote by hand.

Every other test of `check_schema` hands it a document the test built to be valid, or one field
changed to be invalid, which pins the rules for the shapes those tests name. The surface a caller
actually reaches with junk is wider: a document arrives from a browser, from a stored candidate
edited by hand, or from an uploaded file, and the contract a route depends on is narrower than "it
complains". It is *the refusal is a `ValueError` carrying a sentence*, because `dashboard/app.py`
turns exactly that into a 400 and anything else into a 500 -- so a `KeyError`, `TypeError` or
`IndexError` escaping from here is a server error on a request a user can send.

Three properties, none of them a round trip:

1. arbitrary input -- junk in any field, or a value that is not a document at all -- is either
   accepted or refused with `ValueError`, never with another exception;
2. the ring scale is a *range* guard, and both ends are decided by the one constant `RING_SCALES`
   (the standing decision: a mapping states the scale it was built with, 1.15 is only what the
   recogniser writes, and a bool is not a number);
3. the bounds the refusal messages state are the bounds the code enforces, at both ends.

The document builder is the one `test_ring_scale.py` uses, kept local so a change to that file
cannot quietly change what is asserted here.

One note from writing it: the name bound applies to the *stripped* name, so the first version of
the bound test drew 161 characters and the validator accepted them -- 160 after the strip, which is
inside the bound. That failure was the generator's and not the code's, and the test now draws the
stripped length. The one failure that *was* the code's is the reason `refuses` reports the
exception's own name: a non-dict body reached `data.get` before the isinstance check that was meant
to catch it, so the validator raised `AttributeError` where its contract is a `ValueError`.
"""
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dashboard.models.mappings import schema

BEADS = [{'name': 'A', 'type': 'SP1r', 'size': 'S', 'atoms': [1, 2, 3, 4]},
         {'name': 'B', 'type': 'SP1r', 'size': 'S', 'atoms': [5, 6, 7, 8]},
         {'name': 'C', 'type': 'SP1r', 'size': 'S', 'atoms': [9, 10, 11, 12]},
         {'name': 'VS', 'type': 'TC4', 'size': 'T', 'atoms': [],
          'virtual_site': {'function': 1, 'parents': ['A', 'B', 'C']}}]

LO, HI = schema.RING_SCALES
PROFILE = settings(max_examples=150, deadline=None, suppress_health_check=(HealthCheck.too_slow,))

# A name's letters, and the spaces a browser can leave around one. Kept apart because the bound is
# measured after `strip()`.
IDENTIFIER = st.characters(whitelist_categories=('Ll', 'Lu', 'Nd', 'Pd'))
PADDING = st.text(alphabet=' ', max_size=5)

# Any value a JSON body can carry, however deeply nested: the point is that nothing here is shaped
# like a mapping, which is what a caller with a bug sends.
JUNK = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | st.text(max_size=12),
    lambda child: st.lists(child, max_size=3) | st.dictionaries(st.text(max_size=8), child, max_size=3),
    max_leaves=6)


def document(scale):
    """One ring of three beads at a stated scale -- the shape a valid candidate has."""
    return {'schema_version': 3, 'molecule_id': 'DDM', 'name': 'a ring',
            'beads': BEADS, 'connections': [['A', 'B'], ['A', 'C'], ['B', 'C']],
            'rings': [{'beads': ['A', 'B', 'C'], 'virtual_site': 'VS', 'scale': scale}]}


def refuses(value, **kwargs):
    """Run the validator and report how it answered: 'accepted', or the exception type's name."""
    try:
        schema.check_schema(value, **kwargs)
    except ValueError:
        return 'refused'
    except Exception as exc:  # the property is exactly which exception escapes here
        return type(exc).__name__
    return 'accepted'


@PROFILE
@given(JUNK)
def test_a_body_that_is_not_a_document_is_accepted_or_refused_with_a_value_error(value):
    """A request body of any shape: the answer must be a 400 or a 201, never a 500."""
    assert refuses(value) in ('refused', 'accepted'), refuses(value)


@PROFILE
@given(name=st.text(max_size=200), beads=JUNK, connections=JUNK, rings=JUNK)
def test_junk_in_any_field_is_accepted_or_refused_with_a_value_error(name, beads, connections, rings):
    """Junk *inside* a document that has the right top-level keys, one field at a time."""
    value = {'name': name, 'beads': beads, 'connections': connections, 'rings': rings}

    assert refuses(value) in ('refused', 'accepted'), refuses(value)


@PROFILE
@given(scale=st.floats(min_value=LO, max_value=HI, allow_nan=False, allow_infinity=False))
def test_every_scale_inside_the_range_is_accepted(scale):
    """The guard is a range: 1.15 is the convention, not the only admissible value."""
    assert refuses(document(scale)) == 'accepted'


@PROFILE
@given(scale=st.floats(allow_nan=False, allow_infinity=False).filter(lambda s: not LO <= s <= HI))
def test_every_scale_outside_the_range_is_refused(scale):
    assert refuses(document(scale)) == 'refused'


@given(scale=st.booleans())
def test_a_boolean_is_not_a_scale(scale):
    """`True` is an `int` in Python, so the range check alone would accept it as 1.0."""
    assert refuses(document(scale)) == 'refused'


@PROFILE
@given(core=st.text(alphabet=IDENTIFIER, min_size=161, max_size=200), padding=PADDING)
def test_a_name_whose_stripped_length_exceeds_the_bound_is_refused(core, padding):
    """The bound is on `name.strip()`, so it is the stripped length this draws -- see the note above."""
    assert refuses({**document(1.15), 'name': padding + core + padding}) == 'refused'


@PROFILE
@given(core=st.text(alphabet=IDENTIFIER, min_size=1, max_size=160), padding=PADDING)
def test_a_name_whose_stripped_length_is_inside_the_bound_is_accepted(core, padding):
    assert refuses({**document(1.15), 'name': padding + core + padding}) == 'accepted'


@PROFILE
@given(name=st.one_of(st.just(''), st.text(alphabet=' ', min_size=1, max_size=200)))
def test_a_name_with_nothing_but_whitespace_is_refused(name):
    assert refuses({**document(1.15), 'name': name}) == 'refused'


@PROFILE
@given(count=st.integers(min_value=101, max_value=140))
def test_more_bead_groups_than_the_cap_are_refused(count):
    beads = [{'name': f'BEAD{i:03d}', 'type': 'C1', 'size': 'T', 'atoms': []} for i in range(count)]

    assert refuses({'name': 'many beads', 'beads': beads}) == 'refused'


def test_the_ends_of_the_admissible_ranges_are_the_ends_the_messages_state():
    """Both ends of every bound in the docstring, plus the one bead the empty case needs."""
    assert refuses(document(LO)) == 'accepted' and refuses(document(HI)) == 'accepted'
    assert refuses({**document(1.15), 'name': 'x' * 160}) == 'accepted'
    assert refuses({'name': 'a', 'beads': []}) == 'refused'
    assert refuses({'name': 'a', 'beads': []}, allow_empty=True) == 'accepted'
    assert refuses({'name': 'a', 'beads': [{'name': 'A', 'type': 'C1', 'size': 'T', 'atoms': []}]}) == 'accepted'


def test_a_ring_scale_of_the_papers_convention_still_passes():
    """The recogniser's own output must keep validating: the guard was loosened, not deleted."""
    assert refuses(document(1.15)) == 'accepted'
