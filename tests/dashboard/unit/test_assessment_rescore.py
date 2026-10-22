"""Re-scoring a finished run's stage 5: the attempt's number, and every reason it is refused.

Stage 5 is written once, at run time, so a run scored against a parameterization revision that carried no pairwise
family holds an all-zero matrix for a comparison that never happened. Nothing about the run can be re-run to fix that,
and the panel's Recompute button cannot either -- it re-queues *analyses*, which are derived from the run's outputs,
while the matrix is the stage's own output. `assessment_rescore` stages a second attempt beside the first instead.

What is pinned here is the part a caller meets before anything runs: which number the attempt gets, and the six
answers that are refusals rather than attempts. Each refusal has its own sentence, because "there is no CG trajectory"
and "the model records no pairwise references" send a reader to different places -- and the second has to say how many
histograms it *did* find, since that count is the whole reason the first score was zero.

The coordinator is a two-method stand-in and no application is built: the refusals are decided from the run's own
manifest, so a test of them needs a manifest and a directory, not a dashboard.
"""
import json
from pathlib import Path

import pytest

from dashboard.execution import assessment_rescore
from dashboard.execution.coordination import errors
from dashboard.models.bonded import parameterization

JID = 'a1b2c3d4e5f6'
BEADS = ('B01', 'B02', 'B03')
TOPOLOGY = ('[ moleculetype ]\nMOL 1\n\n[ atoms ]\n'
            '1 C1 1 MOL B01 1 0 72\n2 C1 1 MOL B02 2 0 72\n3 C1 1 MOL B03 3 0 72\n')
REVISION = {'engine': 'fast-forward', 'topology': TOPOLOGY,
            'options': {'constraints_threshold': 10000.0, 'temperature_k': 300.0,
                        'torsion_model': 'legacy', 'torsion_scale': 1.0},
            'ensemble': {'frames': 3},
            'aa_reference': {'run_id': 'a54ac8f64710', 'reference_sha256': 'ab' * 32,
                             'molecule_identity': 'cd' * 32, 'temperature_k': 300.0,
                             'production_ns': 10.0}}


class Run:
    """Just the two members `prepare` reads: the record, and the directory its id addresses."""

    def __init__(self, path):
        self.path = Path(path)

    def lookup(self, jid):
        return {'id': jid, 'status': 'completed'}

    def run_path(self, job):
        return self.path


def mapping(**overrides):
    candidate = {'name': 'DDM fixture', 'beads': [{'name': name} for name in BEADS], 'rings': [],
                 'connections': []}
    candidate.update(overrides)
    return candidate


def fitted(candidate, files=('B01_B02_bonds_distr.dat', 'B01_B02_B03_angles_distr.dat')):
    """Save a revision the way a fit does: with the AA reference's histograms in its working directory.

    The default is the *unscorable* case on purpose -- bonds and angles, no pairwise family -- because that is the
    revision this module exists for and the one whose refusal has to name its count.
    """
    work = parameterization.work_root() / f'{parameterization.content_identity(candidate)}-probe'
    stage = work / '3_initial_CG'
    stage.mkdir(parents=True, exist_ok=True)
    for name in files:
        (stage / name).write_text('0.005 0.0\n0.015 1.0\n')
    return parameterization.save(candidate, REVISION, work=work)


#: `mapping_candidate` is optional in two different ways -- "this run's mapping" and "this run records none" -- so
#: the absent case is spelled with a sentinel rather than with `None`, which is itself one of the two answers.
_UNSET = object()


def run_directory(tmp_path, *, stages=None, status='completed', trajectory=True, mapping_candidate=_UNSET,
                  plan=False):
    """A run as this module reads it: its manifest, its stage directory, and its CG trajectory."""
    run = tmp_path / 'run'
    (run / 'stages/3_initial_CG').mkdir(parents=True)
    (run / 'stages/3_initial_CG/DDM_initial.itp').write_text('[ moleculetype ]\nDDM 1\n')
    (run / 'stages/5_assessment').mkdir()
    if trajectory:
        production = run / 'stages/4_CG_sim/prod'
        production.mkdir(parents=True)
        (production / 'lig_CG.xtc').write_bytes(b'xtc bytes')
        (production / 'lig_CG.gro').write_text('coarse-grained fixture\n    3\n')
    names = stages if stages is not None else ['AA reference', 'CG simulation', assessment_rescore.STAGE]
    manifest = {'id': JID, 'status': status, 'run_type': 'aa_cg',
                'cg_names': {'residue_name': 'DDM', 'initial_itp': 'DDM_initial.itp', 'final_itp': 'DDM.itp'},
                'stages': [{'name': name, 'status': 'completed'} for name in names]}
    if plan:
        manifest['stage_plan'] = [[name, f'{name}/script.sh'] for name in names]
        manifest.pop('stages')
    if mapping_candidate is _UNSET:
        mapping_candidate = mapping()
    if mapping_candidate is not None:
        manifest['mapping_candidate'] = mapping_candidate
    (run / 'manifest.json').write_text(json.dumps(manifest))
    return run


def refusal(run):
    """The refusal `prepare` raises for this run, with the claim it took given back."""
    with pytest.raises(errors.RunError) as caught:
        assessment_rescore.prepare(Run(run), JID)
    assert not assessment_rescore.in_flight(JID), 'a refused prepare left the run claimed'
    return str(caught.value)


def test_the_first_rescore_is_attempt_one_and_each_one_after_it_counts_up(tmp_path):
    assert assessment_rescore.next_attempt({}, tmp_path) == 1, 'a run that was never re-scored starts at 1'
    assert assessment_rescore.next_attempt({'assessment_attempts': [{'attempt': 1}]}, tmp_path) == 2
    assert assessment_rescore.next_attempt(
        {'assessment_attempts': [{'attempt': 1}, {'attempt': 2}]}, tmp_path) == 3


def test_a_directory_a_dead_process_left_behind_is_never_reused(tmp_path):
    """Numbers are named, not counted: a half-staged attempt keeps its directory and the next one skips past it."""
    (tmp_path / '5_assessment@2').mkdir()
    assert assessment_rescore.next_attempt({'assessment_attempts': [{'attempt': 1}]}, tmp_path) == 3


def test_an_entry_with_no_number_does_not_shift_the_others(tmp_path):
    """A record written by hand, or by a later reader, is not a directory to stage over."""
    assert assessment_rescore.next_attempt({'assessment_attempts': [{'directory': 'stages/5_assessment@1'}]},
                                           tmp_path) == 1


def test_a_run_without_the_assessment_stage_is_refused_by_name(tmp_path):
    run = run_directory(tmp_path, stages=['AA reference', 'CG simulation'])

    message = refusal(run)

    assert 'no `CG assessment (ff_assess)` stage' in message and 'no assessment to re-score' in message


def test_a_stage_plan_without_the_stage_is_refused_too(tmp_path):
    """A run that failed before its stages were recorded still says what it was going to run."""
    run = run_directory(tmp_path, stages=['AA reference'], plan=True)

    assert 'no `CG assessment (ff_assess)` stage' in refusal(run)


def test_a_run_that_has_not_finished_is_refused(tmp_path):
    run = run_directory(tmp_path, status='running')

    message = refusal(run)

    assert 'Only a completed run can be re-scored' in message and 'is running' in message


def test_a_run_with_no_cg_trajectory_is_refused_and_the_missing_file_named(tmp_path):
    run = run_directory(tmp_path, trajectory=False)

    message = refusal(run)

    assert 'no CG trajectory to score' in message
    assert 'lig_CG.xtc' in message and 'lig_CG.gro' in message


def test_a_run_that_records_no_mapping_is_refused(tmp_path):
    run = run_directory(tmp_path, mapping_candidate=None)

    assert 'records no mapping' in refusal(run)


def test_a_mapping_without_a_current_revision_is_refused(tmp_path):
    run = run_directory(tmp_path)

    message = refusal(run)

    assert 'carries no current parameterization revision' in message
    assert 'no references to re-score it against' in message


def test_a_revision_with_no_pairwise_family_names_how_many_histograms_it_has(tmp_path):
    """The unscorable state this module exists for: 2 histograms recorded, 3 pairs needed, nothing to score.

    The refusal is `cg.stage_distributions`'s own sentence, so it carries both counts and the consequence -- an
    unbaselined cell scores 0.00, which reads identical -- rather than only saying the request was refused.
    """
    fitted(mapping())
    run = run_directory(tmp_path)

    message = refusal(run)

    assert '2 AA reference histogram(s)' in message, message
    assert '3 expected' in message, 'the count a three-bead molecule needs'
    assert '0.00' in message and 'identical' in message


def test_a_revision_whose_histograms_changed_under_it_is_refused_rather_than_staged(tmp_path):
    """A digest that no longer matches is a store changed under the model, not a model without evidence."""
    candidate = mapping()
    fitted(candidate, files=('1_B01_1_B02_distances_distr.dat', 'B01_B02_bonds_distr.dat'))
    recorded = parameterization.distributions(candidate)
    assert recorded, 'the fit recorded the histograms this test then changes'
    (recorded['directory'] / 'B01_B02_bonds_distr.dat').write_text('0.005 9.9\n')
    run = run_directory(tmp_path)
    before = sorted(path.name for path in (run / 'stages').iterdir())

    message = refusal(run)

    assert 'does not match its digest' in message
    assert sorted(path.name for path in (run / 'stages').iterdir()) == before, 'a refused attempt left nothing behind'


def test_an_attempt_already_running_is_refused(tmp_path):
    """One attempt per run: two at once would stage references and append to the same list."""
    fitted(mapping(), files=('1_B01_1_B02_distances_distr.dat',))
    run = run_directory(tmp_path)
    assessment_rescore.claim(JID)
    try:
        with pytest.raises(errors.RunBusy) as caught:
            assessment_rescore.prepare(Run(run), JID)
        assert 'already being re-scored' in str(caught.value)
    finally:
        assessment_rescore.release(JID)


def test_the_attempt_directory_holds_the_reference_count_and_the_revision_it_read(tmp_path):
    """The staged attempt says what it will score with, from the revision and not from the run's manifest."""
    fitted(mapping(), files=('1_B01_1_B02_distances_distr.dat', '1_B01_1_B03_distances_distr.dat',
                             '1_B02_1_B03_distances_distr.dat', 'B01_B02_bonds_distr.dat'))
    run = run_directory(tmp_path)

    attempt = assessment_rescore.prepare(Run(run), JID)

    assert attempt['relative'] == str(Path('stages/5_assessment@1'))
    assert attempt['references']['files'] == 4 and attempt['references']['pairs'] == {'files': 3, 'expected': 3}
    assert attempt['revision']['revision'] == 1
    written = json.loads((run / 'stages/5_assessment@1/attempt.json').read_text())
    assert written['attempt'] == 1 and written['revision'] == attempt['revision']
    assert written['mapping']['mapping_hash'] == attempt['mapping']['mapping_hash']
    assert written['trajectory']['path'] == str(Path('stages/4_CG_sim/prod/lig_CG.xtc'))
    assert assessment_rescore.in_flight(JID), 'the slot is held from `prepare` until `run` finishes'
    assessment_rescore.release(JID)
