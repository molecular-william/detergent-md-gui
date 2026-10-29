"""Stable explanations for dashboard analysis artifacts.

A kind's description is part of its row in `kinds.TABLE` rather than a mapping of its own here. This was the third of
the four lists that described a kind independently, and the only one that had drifted: it held seventeen entries for
fourteen kinds, and a kind missing from it rendered under a title built from its own name -- which reads exactly like
a registered one.
"""
from .kinds import TABLE

EVIDENCE_SECTIONS = {
    'mapped_geometry': ('Carbohydrate geometry and volume', 'SASA, ring geometry, and molecular volume should agree with the cited reference protocol.', 'nm², nm³, and geometric distributions'),
    'transfer_free_energy': ('Water-to-octanol transfer free energy', 'BAR estimates require both solvent legs, uncertainty, and a cited target.', 'kJ/mol; residual to target'),
    'osmotic_pressure': ('Concentration-dependent osmotic pressure', 'Every configured concentration must have a force/area estimate and uncertainty.', 'pressure units; residual to target'),
}
"""Human text for the carbohydrate report's *evidence sections*, which are not analysis kinds.

A section is something `evidence.PROFILES['carbohydrate']` requires a report to contain; a kind is something the
worker can be asked to run. These three sat in the kinds' mapping, which is why that mapping looked over-full rather
than wrong-shaped, and the test that pins them checks them against the profile that requires them.
"""


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
