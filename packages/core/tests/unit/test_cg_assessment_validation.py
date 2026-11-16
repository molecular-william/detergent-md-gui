"""What the assessment stage's own validation may call a failure.

`ff_assess` scores two halves and reports both. The interaction half is a comparison per bond, angle and dihedral, and
a molecule can legitimately have none: a rigid ring states its geometry as `[ constraints ]`, so `ff_inter` wrote no
`<group>_bonds_distr.dat` while fitting and the tool prints `Overall Score : nan` -- the mean of an empty set. The
distance half is one entry per bead pair and does not care.

Run 77504a003e5e died on the word `nan`: the simulation had finished and its distance matrix was scored, and the stage
still failed, because the validation could not tell "nothing to compare" from "the comparison broke". The distinction
is read from the ITP the tool was handed (`$INITIAL_DIR/$INITIAL_ITP`), never from the report: a model with bonded
terms that still got `nan` is a baseline that does not cover them, and that keeps failing.
"""
import json
from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pytest
from dashboard.execution import workflow
from dashboard.execution.adapters import cg
from dashboard.execution.scripts import validate_run

#: Two beads of two atoms each, as a mapping's model states them.
MODEL = {'beads': [{'name': 'A', 'export_name': 'B01', 'atoms': [1, 2]},
                   {'name': 'B', 'export_name': 'B02', 'atoms': [3, 4]}]}
#: One atomistic ligand, three frames, in angstroms as GROMACS stores them. The mapped frame is its beads' own COG,
#: which is what the mapper writes and what `validate_run` independently reconstructs.
AA_FRAMES = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 4.0]],
                      [[0.0, 0.0, 2.0], [1.0, 0.0, 2.0], [0.0, 2.0, 2.0], [0.0, 0.0, 6.0]],
                      [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 4.0]]], dtype=np.float32)
TIMES = (0.0, 2.0, 4.0)
BOX = (50.0, 50.0, 50.0, 90.0, 90.0, 90.0)

#: A ring whose geometry is constraints only: the shape the glucose mapping writes, with no bonded section to score.
CONSTRAINT_ONLY = ("[ moleculetype ]\nLIG1 1\n\n[ atoms ]\n"
                   "1 SP4r 1 LIG1 B01 1 0 54\n2 SP4r 1 LIG1 B02 2 0 54\n\n"
                   "[ constraints ]\n1 2 1 0.349407\n\n"
                   "[ bonds ]\n\n[ angles ]\n\n[ dihedrals ]\n")
#: The same molecule with one real bond, so the interaction half has something to score and must be scored.
BONDED = CONSTRAINT_ONLY.replace('[ bonds ]\n', '[ bonds ]\n1 2 1 0.30 5000\n')

#: The tool's report for a model with no interaction to compare, verbatim in shape: an empty per-type list and the
#: mean of an empty set. `ff_assess` prints exactly this for a constraint-only molecule.
NAN_INTERACTIONS = """ [ Interaction Distribution Report ]
   Overall Score : nan ± nan

 Interaction Scores:
 0 - identical, 1 - no overlap

 Score guide:
   0.0-0.3 : good
   0.3-0.5 : ok
   0.5-1.0 : bad

\t\tHellinger distance (Scoring function)

 bonds 

 angles 

 dihedrals 
"""
FINITE_INTERACTIONS = """ [ Interaction Distribution Report ]
   Overall Score : 0.238 ± 0.0208

 bonds 
 B01_B02 : 0.201 (0.238)
"""
DISTANCES = """ [ Distance Distribution Report for LIG1 ]
  Overall Score : 1.0 ± 0.0
"""


def _write(directory, stem, names, frames):
    """One trajectory the way a run's own copy is written: its first frame as `.gro`, every frame as `.xtc`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    universe = mda.Universe.empty(len(names), n_residues=1, atom_resindex=[0] * len(names), trajectory=True)
    universe.add_TopologyAttr('names', list(names))
    universe.add_TopologyAttr('resnames', ['LIG'])
    universe.add_TopologyAttr('resids', [1])
    with mda.Writer(str(directory / f'{stem}.xtc'), n_atoms=len(names)) as writer:
        for index, (time, positions) in enumerate(zip(TIMES, frames)):
            universe.atoms.positions = positions
            universe.trajectory.ts.time = float(time)
            universe.dimensions = BOX
            if index == 0:
                universe.atoms.write(str(directory / f'{stem}.gro'))
            writer.write(universe.atoms)


def _run(tmp_path, topology):
    """A prepared run's directories, and the two reports a finished assessment leaves in its stage directory."""
    reference = tmp_path / 'reference'
    _write(reference, 'lig', ['C1', 'C2', 'C3', 'C4'], AA_FRAMES)
    beads = np.stack([AA_FRAMES[:, 0:2].mean(axis=1), AA_FRAMES[:, 2:4].mean(axis=1)], axis=1)
    run = tmp_path / 'run'
    _write(run / '2_mapping', 'mapped', ['B01', 'B02'], beads)
    (run / '2_mapping' / 'model.json').write_text(json.dumps(MODEL))
    (run / '3_initial_CG').mkdir()
    (run / '3_initial_CG' / 'LIG1_initial.itp').write_text(topology)
    _write(run / '4_CG_sim' / 'prod', 'lig_CG', ['B01', 'B02'], beads + 1.0)
    stage = run / '5_assessment'
    stage.mkdir()
    return run, reference, stage


def _reports(stage, interactions, distances=DISTANCES):
    """The two files a finished `ff_assess` leaves in the stage directory."""
    (stage / 'report_interactions.out').write_text(interactions)
    (stage / 'report_distances.out').write_text(distances)


def test_a_constraint_only_model_records_an_unscored_interaction_half(tmp_path, monkeypatch):
    """The failure this pins: a finished simulation, a scored distance matrix, and no bonded term to compare."""
    run, reference, stage = _run(tmp_path, CONSTRAINT_ONLY)
    _reports(stage, NAN_INTERACTIONS)
    monkeypatch.chdir(stage)
    monkeypatch.setenv('INITIAL_DIR', '../3_initial_CG')
    monkeypatch.setenv('INITIAL_ITP', 'LIG1_initial.itp')

    validate_run.main(root=run, aa_source=reference)

    written = json.loads((stage / 'validation.json').read_text())
    assert written['mechanical_checks_passed'] is True
    assert written['interaction_scores']['scored'] is False
    assert 'constraints' in written['interaction_scores']['reason']
    assert written['report_distances.out'] == DISTANCES
    assert written['report_interactions.out'] == NAN_INTERACTIONS, 'the tool\'s own report is kept, not rewritten'


def test_a_model_with_bonded_terms_still_refuses_a_nan_interaction_report(tmp_path, monkeypatch):
    """The silent failure the check exists for: a bonded term the reference never measured."""
    run, reference, stage = _run(tmp_path, BONDED)
    _reports(stage, NAN_INTERACTIONS)
    monkeypatch.chdir(stage)
    monkeypatch.setenv('INITIAL_DIR', '../3_initial_CG')
    monkeypatch.setenv('INITIAL_ITP', 'LIG1_initial.itp')

    with pytest.raises(ValueError, match='report_interactions.out: nonfinite scores'):
        validate_run.main(root=run, aa_source=reference)
    assert not (stage / 'validation.json').exists()


def test_a_named_itp_the_caller_cannot_find_keeps_the_strict_check(tmp_path, monkeypatch):
    """Fail closed: no topology to read is not evidence of a model with nothing to score."""
    run, reference, stage = _run(tmp_path, CONSTRAINT_ONLY)
    _reports(stage, NAN_INTERACTIONS)
    monkeypatch.chdir(stage)
    monkeypatch.setenv('INITIAL_DIR', '../3_initial_CG')
    monkeypatch.setenv('INITIAL_ITP', 'there-is-no-such.itp')

    with pytest.raises(ValueError, match='nonfinite scores'):
        validate_run.main(root=run, aa_source=reference)


def test_a_scored_interaction_report_passes_for_a_bonded_model(tmp_path, monkeypatch):
    """The ordinary path is untouched: finite scores pass, and no unscored note is added."""
    run, reference, stage = _run(tmp_path, BONDED)
    _reports(stage, FINITE_INTERACTIONS)
    monkeypatch.chdir(stage)
    monkeypatch.setenv('INITIAL_DIR', '../3_initial_CG')
    monkeypatch.setenv('INITIAL_ITP', 'LIG1_initial.itp')

    validate_run.main(root=run, aa_source=reference)

    written = json.loads((stage / 'validation.json').read_text())
    assert written['mechanical_checks_passed'] is True
    assert 'interaction_scores' not in written


def test_the_topology_reader_counts_rows_and_not_commented_ones(tmp_path):
    """Only a section with a real row counts: a commented-out term is not one the tool scores."""
    topology = tmp_path / 'MOL.itp'
    topology.write_text('[ bonds ]\n; 1 2 1 0.30 5000\n\n[ constraints ]\n1 2 1 0.35\n')

    assert validate_run.bonded_sections(topology) == set()
    assert validate_run.bonded_sections(Path(tmp_path / 'absent.itp')) is None


def test_the_fit_path_stages_name_the_histogram_family_not_each_section(tmp_path):
    """A fit of a constraint-only molecule must not be refused for histograms it had nothing to write.

    `missing_files` treats an unmatched glob as missing, so naming `*_bonds_distr.dat` and `*_angles_distr.dat` as
    required refused the fit of a rigid ring before its assessment could run. `ff_inter -dists` writes the family that
    exists, and one pattern names it whatever the molecule states.
    """
    run = tmp_path / 'run'
    fit = run / '3_initial_CG'
    fit.mkdir(parents=True)
    (fit / 'mapped.tpr').write_bytes(b'tpr')
    (fit / 'DDM.itp').write_text('[ moleculetype ]\nDDM 1\n')
    (fit / '1_B01_1_B02_distances_distr.dat').write_text('0.0 1.0\n')

    assert workflow.missing_files(fit, cg.REQUIRED_OUTPUTS['CG parameterization']) == []

    stage = run / '5_assessment'
    stage.mkdir()
    for relative in ('4_CG_sim/prod/lig_CG.xtc', '4_CG_sim/prod/lig_CG.tpr', '4_CG_sim/prod/lig_CG.gro'):
        (run / relative).parent.mkdir(parents=True, exist_ok=True)
        (run / relative).write_bytes(b'x')
    (fit / 'DDM_initial.itp').write_text('[ moleculetype ]\nDDM 1\n')

    assert workflow.missing_files(stage, cg.REQUIRED_INPUTS['CG assessment (ff_assess)']) == []
