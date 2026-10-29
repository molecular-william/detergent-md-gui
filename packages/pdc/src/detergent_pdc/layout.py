"""The protein-detergent run layout: its stage directories, roles, review order and topology.

The engine owns the mechanism -- one stage directory per stage, its older spelling still readable, one role per path --
and a run type's own spelling of those is data it supplies. This module is that data, registered when the feature is
loaded, so `analysis/runs/layout.py` never names a pdc stage.
"""
STAGE_DIRECTORIES = {
    'prepare': ('01_prepare', '0_prepare'),
    'system': ('02_system', '1_system'),
    'minimisation': ('03_minimisation', '2_minimisation'),
    'nvt': ('04_nvt', '3_nvt'),
    'npt': ('05_npt', '4_npt'),
    'assessment': ('06_assessment', '2_assessment'),
    'micelle_assessment': ('07_micelle_assessment', '3_assessment'),
    'extension': ('08_extension', '4_extension'),
    'final_assessment': ('09_final_assessment', '5_assessment'),
    'backmap': ('10_backmap', '6_backmap'),
}

#: The detergent topology the build stage writes, and the directory it writes it in.
DETERGENT_TOPOLOGY = 'detergent_CG.itp'

ROLES = {
    # The extension's production: whole-box first, because a frame read raw shows molecules broken across the
    # periodic boundary. Two spellings get two roles, because `resolve` refuses a role spelled twice and a run holds
    # both the whole-box and the raw file.
    'pdc_trajectory': ('08_extension/prod/whole.xtc', '4_extension/prod/whole.xtc'),
    'pdc_raw_trajectory': ('08_extension/prod/run.xtc', '4_extension/prod/run.xtc'),
    'pdc_structure': ('08_extension/prod/run.gro', '4_extension/prod/run.gro'),
    # A run whose removal path is off (or that never reached the extension) still has production MD to review.
    'pdc_assessment_trajectory': ('06_assessment/prod/whole.xtc', '2_assessment/prod/whole.xtc'),
    'pdc_assessment_structure': ('06_assessment/prod/run.gro', '2_assessment/prod/run.gro'),
}

ASSESSMENT_DIRECTORIES = ('09_final_assessment', '5_assessment')

REVIEW_SOURCES = (
    ('pdc_trajectory', 'pdc_structure'),
    ('pdc_raw_trajectory', 'pdc_structure'),
    ('pdc_assessment_trajectory', 'pdc_assessment_structure'),
)


def topology(root, name=None):
    """The detergent moleculetype a run simulated, from the directory its build stage wrote.

    The directory also holds the template's atomistic copy and the Martini libraries the stage copies in, so "the
    only `.itp` here" does not select on a real run; the build's own filename does.
    """
    from dashboard.analysis.runs import layout

    return layout.molecule_topology(root, STAGE_DIRECTORIES['system'], DETERGENT_TOPOLOGY,
                                    'detergent topology', 'candidate detergent topology', name)


def register():
    """Add this run type's layout to the engine's registry."""
    from dashboard.analysis.runs import layout

    layout.register(roles=ROLES, stage_directories=STAGE_DIRECTORIES,
                    review_sources=REVIEW_SOURCES, topology={'pdc': topology}, assessment=ASSESSMENT_DIRECTORIES)
