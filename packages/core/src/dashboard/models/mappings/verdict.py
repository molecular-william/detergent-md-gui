"""One verdict for a candidate: can it be saved, reused, exported, approved?

"Does this finding matter?" was answered in five places -- the graph checker kept two code
sets, the store's save message a third, the exporter's blocker list a fourth and the
molecule draft loader a fifth -- so a finding could block an export and not a save for
reasons that lived nowhere in particular. The table lives here. A finding is described by
its code, and this module is the only place that decides which code blocks which
operation.

The shape is deliberately the same for every question: the codes, the findings and the
four permissions. A candidate whose document does not parse is reported as a finding
rather than raised, because that is also an answer to "can this be saved?".
"""

#: Findings that describe coarse-graining conventions rather than an incomplete or unsafe
#: graph: they are review advisories, so they do not block export or reuse.
ADVISORY = frozenset({'size', 'mismatch'})

#: Findings that make a document unsalvageable as a candidate, as opposed to a draft that
#: is still being edited.
STRUCTURAL = frozenset({'duplicate', 'unknown', 'hydrogen', 'name', 'virtual_ring'})

#: A document that does not parse at all, reported by evaluate(): every operation refuses it.
MALFORMED = 'malformed'

#: How a code decides a permission: 'any_of' blocks on these codes, 'always' blocks on
#: every finding, 'except' blocks on everything that is not listed.
RULES = {
    'can_save': ('any_of', STRUCTURAL | {MALFORMED}),
    'can_approve': ('always', frozenset()),
    'can_export': ('except', ADVISORY),
    'can_reuse': ('except', ADVISORY),
}


def blocks(code, permission):
    """Whether a finding with this code blocks this permission."""
    mode, codes = RULES[permission]
    if mode == 'always':
        return True
    if mode == 'any_of':
        return code in codes
    return code not in codes


def blocking(issues, permission):
    """The findings that block a permission, in the order they were found."""
    return [item for item in issues if blocks(item['code'], permission)]


def derive(issues):
    """The four permissions a set of findings allows."""
    return {permission: not blocking(issues, permission) for permission in RULES}


def codes(issues):
    """The distinct finding codes, sorted."""
    return sorted({item['code'] for item in issues})


def evaluate(candidate, *, context=None, structure=None, allow_partial=False):
    """One shape for every question about a candidate's usability.

    Asks the graph checker once and reports what it found. A candidate the checker cannot
    even read comes back as a ``malformed`` finding, so a caller that is asking a question
    gets a verdict instead of an exception.
    """
    # Deferred: the checker asks this module for the table, so importing it here keeps the
    # table independent of the checker.
    from . import graph
    try:
        found = dict(graph.validate(candidate, structure, context=context, allow_partial=allow_partial))
        issues = found['issues']
    except (ValueError, KeyError, TypeError) as exc:
        issues, found = [{'code': MALFORMED, 'message': str(exc), 'bead': None}], {}
    return {**found, **derive(issues), 'codes': codes(issues), 'issues': issues}
