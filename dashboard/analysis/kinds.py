"""One row per analysis kind: its name, the sources it is handed, how it runs, and how it reads.

Four lists described the same fourteen kinds and nothing compared them -- the names in `worker.KINDS`, the source
patterns in `worker.PATTERNS`, the dispatch chain in `worker.execute`, and `metadata.DESCRIPTIONS`. They agreed about
the names and the sources. The descriptions did not: seventeen entries for fourteen kinds, because three of them name
the evidence sections of the carbohydrate-validation report rather than analyses, and a kind missing from any one list
failed silently -- unreachable, or handed no inputs, or described under a title the code invented by replacing hyphens
with spaces, which reads exactly like a registered one.

This table is the single source. `worker` takes the names, the sources and the dispatch from it, and
`metadata.describe` takes the description, so a new kind is one row and the readers agree because they derive from one
place rather than because someone remembered four.
"""
from dataclasses import dataclass
from typing import Callable

from .runs import bartender_fit, bonded_estimate, dihedral_fit, mapping_consistency, observability, osmotic_pressure, overlap, refinement, surfaces
from .validation import report as carbohydrate_validation
from .validation import targets


def _sources_only(function: Callable) -> Callable:
    """Adapt an analysis that reads only the sources it was handed to the `(work, payload)` shape of every row."""
    return lambda work, payload=None: function(work)


def _snapshots(work, payload=None):
    """The snapshots producer, which is the one row whose payload changes what it writes.

    Three settings reach it: `interval_ns` (nanoseconds per frame), `samples` (the even spread used when no cadence
    is asked for) and `align` (whether every model is superposed on the first). All three are checked at the route,
    so a producer that receives one has already been told it is usable -- and all three have to be *forwarded* here:
    a setting the route accepts and this row drops is a switch that does nothing, which is how the fit was queued
    and never applied.
    """
    payload = payload or {}
    return observability.generate(work, samples=int(payload.get('samples', observability.SERIES_SAMPLES)),
                                  interval_ns=payload.get('interval_ns'), align=bool(payload.get('align')),
                                  align_on=payload.get('align_on'))


@dataclass(frozen=True)
class Kind:
    """Everything one kind is. `run` is called as `run(work, payload)` for every kind, without exception."""

    name: str
    sources: tuple[str, ...]
    run: Callable[..., object]
    title: str
    ideal_result: str
    units_or_direction: str
    #: The kind stages the shared AA reference's own trajectory as its atomistic source.
    reads_aa_reference: bool = False
    #: Sources used instead when the run has neither a shared reference nor a staged trajectory -- the shape of a run
    #: written before the reference/consumer split.
    legacy_sources: tuple[str, ...] = ()
    #: The kind records the resolved GROMACS build in its versions, because it runs or reads gmx.
    records_gmx_version: bool = False
    #: The kind's request may name dependencies: already-published reports it is scored against.
    takes_dependencies: bool = False
    #: The kind runs for a run because the run can answer it, without anyone asking. Only the frames are registered
    #: so: looking at a trajectory is what every completed run owes its reader, and a run with nothing to sample is
    #: not an error -- the producer refuses it in its own words and the attempt is recorded as a skip.
    runs_for_every_run: bool = False


TABLE: dict[str, Kind] = {row.name: row for row in (
    # The atomistic solute and its trajectory (what the fit is checked against), the mapping that
    # defines the beads, and the generated topology whose terms the fit is compared with. Optional by
    # design: nothing queues it.
    Kind(
        'bartender-fit',
        (
            "1_AA-reference/prod/lig.gro",
            "1_AA-reference/prod/lig.xtc",
            "2_mapping/model.json",
            "2_mapping/mapping.ndx",
            "3_initial_CG/*.itp",
        ),
        bartender_fit.run,
        "BARTENDER bonded fit",
        "A fitted term inside the reference ensemble's own spread reproduces the geometry the molecule has; agreement is a check against our own reference, not experimental evidence.",
        "nm, degrees, and force constants",
        reads_aa_reference=True),
    # Our fitted topology against an independent estimate taken from the frames the fit saw. The
    # draft is staged too, because a job whose fit stage skipped still has a topology, and the
    # report says which of the two answered.
    Kind(
        'bonded-cross-check',
        (
            "2_mapping/mapped.gro",
            "2_mapping/mapped.xtc",
            "2_mapping/model.json",
            "3_initial_CG/*_ff_inter.itp",
            "3_initial_CG/*initial*.itp",
        ),
        bonded_estimate.cross_check,
        "Bonded terms \u00b7 our fit against the estimate",
        "The fitted force constants beside the ones an independent equipartition estimate reads from the same frames. The two are not expected to be equal -- one is a coupled distribution-matching fit, the other is per term -- but a term we write as a rigid constraint and the estimate reads as a spring is a different molecule.",
        "nm, kJ/mol/nm^2, and which side calls each term a constraint"),
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
        reads_aa_reference=True, records_gmx_version=True),
    # The same inputs as the cross-check, because it asks the same kind of question of the same frames:
    # what would a criterion-driven fit say, beside what the run's own tool-chosen terms say.
    Kind(
        'dihedral-fit',
        (
            "2_mapping/mapped.gro",
            "2_mapping/mapped.xtc",
            "2_mapping/model.json",
            "3_initial_CG/*_ff_inter.itp",
            "3_initial_CG/*initial*.itp",
        ),
        dihedral_fit.publish,
        "Dihedral terms \u00b7 a criterion against the tool default",
        "For every proper dihedral the topology declares, the multiplicity and force constant an AIC/BIC-chosen cosine fit reads from the same frames, beside the ones the tool wrote. Where they disagree, the tool default is what is being questioned -- agreement is not evidence the tool chose well.",
        "degrees, kJ/mol, and a multiplicity"),
    # All three ensembles of one consumer run: its atomistic reference, the trajectory mapped onto
    # the beads, and the simulated coarse-grained trajectory, plus the topology that names the
    # beads.
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
        'observables',
        ("2_mapping/mapped.gro", "2_mapping/mapped.xtc", "3_initial_CG/DDM_initial.itp"),
        _sources_only(observability.unparameterized_observables),
        "Interaction distributions",
        "Bond, angle, and dihedral distributions should reproduce AA shapes and populations.",
        "native observable units; mismatch is lower-is-better"),
    # One condition's own files, all of them: the walls the run was built with (`plumed.dat` names
    # the grouping, the box centre and KAPPA), the record that holds the dividing area, the structure
    # the trajectory is read against, and the trajectory itself. The walls are staged deliberately
    # rather than re-derived -- the analysis and the simulation disagreeing about what a molecule is
    # would be invisible in the number.
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
    # The model against the reference it was built from: both ensembles, and the model for the bead names.
    # The *mapped* trajectory is deliberately not staged -- it is a third thing, and this analysis says
    # nothing about it.
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
        'plots',
        ("*SASA*/AA/*.xvg", "*SASA*/CG/*.xvg"),
        _sources_only(observability.sasa_plot),
        "SASA over time",
        "AA and CG SASA should agree in mean and temporal variability; larger is not inherently better.",
        "nm\u00b2; agreement of mean/SD is desired"),
    Kind(
        'refinement-score',
        ("5_assessment/validation.json",),
        _sources_only(refinement.score),
        "Refinement score",
        "Mismatch metrics are lower-is-better; 0 means identical distributions where the scorer defines that range.",
        "native metric units",
        takes_dependencies=True),
    # Both trajectories are staged: an AA-only run's published reference, and a CG consumer's own coarse-grained
    # output. `layout.frame_source` reads whichever the run holds and prefers the coarse-grained one, so the kind
    # does not have to know which run type asked for it. The legacy pair is where a run wrote its reference before
    # the reference/consumer split.
    Kind(
        'snapshots',
        ("1_AA-reference/prod/lig.gro", "1_AA-reference/prod/lig.xtc",
         "4_CG_sim/prod/lig_CG.gro", "4_CG_sim/prod/lig_CG.xtc",
         "4_CG_sim/md.gro", "4_CG_sim/md.xtc",
         "4_CG_sim/eq.gro", "4_CG_sim/eq.xtc",
         # The run's own mapping, which is what says which beads make up which fragment: a reader fitting on one
         # ring of a sugar is asking about a grouping only this document states, and the file carries it too.
         "2_mapping/model.json",
         # The moleculetype the frames are drawn with. A series must carry the model's own bonds and each bead's
         # Martini 3 family or the panel can only draw grey spheres -- measured on the first series published -- and
         # both of those live in the run's `3_initial_CG/` moleculetype, so it is a source like any other rather than
         # something the producer hunts for outside the tree it was handed.
         "3_initial_CG/*.itp"),
        _snapshots,
        "Trajectory snapshots",
        "Snapshots provide visual inspection and are not a distributional validation.",
        "coordinates",
        reads_aa_reference=True, legacy_sources=('1_AA-reference/3-run.xtc', '1_AA-reference/3-run.tpr'),
        runs_for_every_run=True),
    Kind(
        'stability',
        ("*.log", "*.xtc"),
        _sources_only(observability.numerical_stability),
        "Numerical stability",
        "No LINCS warnings and finite coordinates are required, but passing does not establish physical validity.",
        "counts and diagnostic signals",
        records_gmx_version=True),
    Kind(
        'surfaces',
        (
            "1_AA-reference/prod/lig.gro",
            "1_AA-reference/prod/lig.xtc",
            "2_mapping/model.json",
            "4_CG_sim/prod/lig_CG.gro",
            "4_CG_sim/prod/lig_CG.xtc",
        ),
        _sources_only(surfaces.generate),
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
)}


def for_every_run() -> tuple[str, ...]:
    """The kinds a run runs for itself, in table order.

    `analysis_coordinator` queues these for a run whose stages are finished, so a person does not have to know the
    kind's name to get the artifact it publishes. It is a facet of the row -- the one place a kind is registered --
    rather than a list kept beside the table, because a second list is a second thing to keep in step.
    """
    return tuple(name for name, row in TABLE.items() if row.runs_for_every_run)
