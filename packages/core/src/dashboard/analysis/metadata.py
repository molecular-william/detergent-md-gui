"""Stable explanations for dashboard analysis artifacts.

A kind's description is part of its row in `kinds.TABLE` rather than a mapping of its own here. This was the third of
the four lists that described a kind independently, and the only one that had drifted: it held seventeen entries for
fourteen kinds, and a kind missing from it rendered under a title built from its own name -- which reads exactly like
a registered one.

The evidence sections a report must carry are not the engine's vocabulary: the feature whose report requires them
registers the text, and `features.evidence_sections()` is the merged view.
"""
from .kinds import TABLE


def describe(kind, result=None):
    """The metadata an analysis artifact carries about itself.

    An unregistered kind is refused rather than described. The title it used to be given --
    `kind.replace('-', ' ').title()` -- is indistinguishable from a registered one, so a kind dropped from the
    vocabulary kept rendering under the right shape and with no content, and nothing failed.
    """
    row = TABLE.get(kind)
    if row is None:
        raise ValueError(f'Unknown analysis kind: {kind}')
    return {'schema_version':1,'kind':kind,'title':row.title,'ideal_result':row.ideal_result,
            'units_or_direction':row.units_or_direction,'stats':result or {}}
