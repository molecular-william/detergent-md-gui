"""Stable explanations for dashboard analysis artifacts.

A kind's description is part of its row in `kinds.TABLE` rather than a mapping of its own here. This was the third of
the four lists that described a kind independently, and the only one that had drifted: it held seventeen entries for
fourteen kinds, and a kind missing from it rendered under a title built from its own name -- which reads exactly like
a registered one.

The evidence sections a report must carry are not the engine's vocabulary: the feature whose report requires them
registers the text, and `evidence_sections()` is the merged view.
"""
from .. import features
from .kinds import TABLE


def evidence_sections():
    """The evidence-section text the installed features require a report to carry.

    A section is report vocabulary, not an analysis kind; a feature owns the sections its own report needs, and the
    registry refuses two features that claim the same name.
    """
    return features.evidence_sections()


def describe(kind, result=None, legacy=False):
    """The metadata an analysis artifact carries about itself.

    An unregistered kind is refused rather than described. The title it used to be given --
    `kind.replace('-', ' ').title()` -- is indistinguishable from a registered one, so a kind dropped from the
    vocabulary kept rendering under the right shape and with no content, and nothing failed.

    `legacy` is the one exception, for an artifact written by an older writer whose kind is no longer registered:
    that is described *as* legacy, which is what its reader needs to know, rather than refused.
    """
    row = TABLE.get(kind)
    if row is not None:
        title, ideal, units = row.title, row.ideal_result, row.units_or_direction
    elif legacy:
        title, ideal, units = (kind.replace('-', ' ').title(),
                               'Interpret with the run protocol and source metadata.', 'native units')
    else:
        raise ValueError(f'Unknown analysis kind: {kind}')
    return {'schema_version':1,'kind':kind,'title':title,'ideal_result':ideal,'units_or_direction':units,
            'legacy':bool(legacy),'stats':result or {}}
