"""The validation analyses: the comparison, fit, surface and osmotic kinds this workspace owns.

Each row is a `dashboard.analysis.kinds.Kind`; registration is the table, so the worker, the descriptions and the
analysis control all read them through the engine's one vocabulary.
"""
from dashboard.analysis.kinds import Kind, sources_only

from .analysis.runs import mapping_consistency, osmotic_pressure, overlap, refinement, surfaces
from .analysis.validation import report as carbohydrate_validation
from .analysis.validation import targets

KINDS = (
    Kind(
        'carbohydrate-validation',
        (
            "1_AA-reference/prod/lig.gro",
            "1_AA-reference/prod/lig.xtc",
            "2_mapping/model.json",
            "4_CG_sim/prod/lig_CG.gro",
            "4_CG_sim/prod/lig_CG.xtc",
            "3_initial_CG/*.itp",
        ),
        carbohydrate_validation.run,
        "Carbohydrate validation report",
        "Three independent evidence classes are required; setup checks remain diagnostic-only.",
        "status and native evidence units",
        reads_aa_reference=True, records_gmx_version=True,
        payload=('tier', 'representation_mode', 'mapping_snapshot', 'molecule_id', 'target_dataset_id')),

    Kind(
        'mapping-consistency',
        (
            "1_AA-reference/prod/lig.gro",
            "1_AA-reference/prod/lig.xtc",
            "2_mapping/mapped.gro",
            "2_mapping/mapped.xtc",
            "4_CG_sim/prod/lig_CG.gro",
            "4_CG_sim/prod/lig_CG.xtc",
            "3_initial_CG/*.itp",
        ),
        mapping_consistency.publish,
        "Mapping consistency",
        "A model should reproduce the atomistic structure it was built from; agreement here is not experimental evidence.",
        "nm, degrees, and distribution metrics",
        reads_aa_reference=True),

    Kind(
        'osmotic-pressure',
        (
            "01_simulate/osmotic_condition.json",
            "01_simulate/plumed.dat",
            "01_simulate/solvated.gro",
            "01_simulate/prod/md_whole.xtc",
        ),
        osmotic_pressure.publish,
        "Osmotic pressure \u00b7 one condition",
        "The wall force the confined solute exerts, recomputed from the run's own trajectory at the paper's 1000 kJ/mol/nm2 and divided by the dividing area. Both walls are reported: their mean is the pressure, and their ratio says whether the average has converged -- a one-sided load halves the mean, which is the failure the ratio exists to catch.",
        "bar, and each wall's force in kJ/mol/nm"),

    Kind(
        'overlap',
        (
            "1_AA-reference/prod/lig.gro",
            "1_AA-reference/prod/lig.xtc",
            "2_mapping/model.json",
            "4_CG_sim/prod/lig_CG.gro",
            "4_CG_sim/prod/lig_CG.xtc",
        ),
        overlap.publish,
        "AA/CG bead overlap",
        "The coarse-grained model should reproduce the intra-bead distance distributions of the atomistic reference it was built from; agreement is internal consistency, not experimental evidence.",
        "overlap coefficient 0-1; higher is closer"),

    Kind(
        'refinement-score',
        ("5_assessment/validation.json",),
        sources_only(refinement.score),
        "Refinement score",
        "Mismatch metrics are lower-is-better; 0 means identical distributions where the scorer defines that range.",
        "native metric units",
        takes_dependencies=True),

    Kind(
        'surfaces',
        (
            "1_AA-reference/prod/lig.gro",
            "1_AA-reference/prod/lig.xtc",
            "2_mapping/model.json",
            "4_CG_sim/prod/lig_CG.gro",
            "4_CG_sim/prod/lig_CG.xtc",
        ),
        sources_only(surfaces.generate),
        "AA/CG solvent-accessible surface overlay",
        "Aligned envelopes should occupy similar regions; a snapshot is not ensemble validation.",
        "nm; visual agreement",
        reads_aa_reference=True, records_gmx_version=True),

    Kind(
        'targets',
        (),
        targets.build,
        "Analysis targets",
        "Targets describe the comparison protocol; they are not a quality score.",
        "protocol metadata"),
)
