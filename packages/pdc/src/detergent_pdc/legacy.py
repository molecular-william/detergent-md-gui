"""The pdc stage directories a run prepared before the numbered layout may hold at its root.

`dashboard.cli.migrate_run_layout` reads this through the feature registry (`Feature.legacy_stages`), so the engine
does not carry a table of one feature's stage names. These are the pre-numbering spellings, in the order the migration
moves them; `layout.STAGE_DIRECTORIES` names the numbered spelling each one resolves to.
"""

#: The stage directories a legacy pdc run leaves at its root, named as that run's manifest named them.
LEGACY_STAGES = (
    '0_prepare', '1_system', '2_minimisation', '3_nvt', '4_npt',
    '2_assessment', '3_assessment', '4_extension', '5_assessment', '6_backmap',
)
