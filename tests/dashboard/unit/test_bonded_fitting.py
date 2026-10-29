"""The fit job: a mapping and a linked AA reference become a revision, and nothing is simulated.

What these tests pin is the shape of the job and the four claims the design makes about it (D2, D3,
D5, D6): it runs with a status and can be cancelled; it builds the mapped trajectory once per
(mapping, reference) pair and reuses it; each engine records the ensemble it saw; and the two checks
run as part of producing a revision without being able to fail it.

No test runs a real tool. The engines are stood in for at the seam the job itself uses -- the command
runner -- and each stub writes the artefact the job's own guard looks for: `ff_inter`'s
`<residue>.itp` for Fast-Forward, `gmx_out.itp` for BARTENDER. The mapped trajectory a stub writes is
a real one, so the two checks are exercised for real rather than stubbed a second time.

Nothing here reads the developer's workspace: the records, the work directories and the trajectory all
land under the isolated workspace the `dashboard` fixture selects.
"""
import copy
import json
import threading
import time
from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pytest

from dashboard import martini3
from dashboard.execution.adapters import cg
from dashboard.models import mappings
from dashboard.models.bonded import fitting, parameterization
from dashboard.models.mappings.context import as_structure, build_context

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MOLECULES = PROJECT_ROOT / 'molecules'
REFERENCE = {'run_id': 'a' * 12, 'directory': '/nonexistent/reference', 'reference_sha256': 'ab' * 32,
             'record': {'reference_sha256': 'ab' * 32, 'frames': 20001,
                        'aa_reference': {'run_id': 'a' * 12, 'reference_sha256': 'ab' * 32,
                                         'molecule_identity': 'cd' * 32, 'temperature_k': 300.0,
                                         'production_ns': 10.0}}}


def ddm_mapping(name='DDM'):
    """The saved-candidate shape the panel posts: the molecule's snapshot, exported by one mapper."""
    context = build_context(MOLECULES, 'DDM')
    candidate = mappings.automatic_candidate(as_structure(context), name)
    candidate.update(schema_version=3, molecule_id='DDM',
                     molecule_snapshot=copy.deepcopy(context['snapshot']))
    return candidate


def write_frames(directory, beads, frames=5):
    """A real mapped trajectory: the names the mapping gives its beads, and a box per frame."""
    names = [bead['name'] for bead in beads]
    universe = mda.Universe.empty(len(names), trajectory=True)
    universe.add_TopologyAttr('name', names)
    universe.add_TopologyAttr('resname', ['LIG'])
    universe.add_TopologyAttr('resid', [1])
    positions = np.zeros((len(names), 3), dtype=np.float32)
    for index in range(len(names)):
        positions[index] = (index * 0.45, 0.0, 0.0)
    (directory / 'mapped.gro').parent.mkdir(parents=True, exist_ok=True)
    universe.atoms.positions = positions
    universe.atoms.write(str(directory / 'mapped.gro'))
    rng = np.random.default_rng(7)
    trajectory = np.asarray([positions + rng.normal(0.0, 0.02, positions.shape).astype(np.float32)
                             for _ in range(frames)], dtype=np.float32)
    universe.trajectory = mda.coordinates.memory.MemoryReader(trajectory, order='fac')
    with mda.Writer(str(directory / 'mapped.xtc'), n_atoms=len(names)) as writer:
        for _ in universe.trajectory:
            writer.write(universe.atoms)
    (directory / 'mapping_validation.json').write_text(json.dumps({'frames': frames, 'mode': 'stub'}))
    return frames


class Recorder:
    """The stand-in for a tool: it records the command and writes the artefact the job's guard wants."""

    def __init__(self, *, topology=None, fail_fit=False, frames=5, bartender=False):
        self.calls = []
        self.topology = topology or ('[ moleculetype ]\nDDM 1\n\n[ atoms ]\n1 C1 1 DDM B01 1 0 72\n'
                                     '2 C1 1 DDM B02 2 0 72\n\n[ bonds ]\n1 2 1 0.31 5000\n')
        self.fail_fit = fail_fit
        self.frames = frames
        self.bartender = bartender

    def __call__(self, command, cwd, *, env=None, timeout=None, job_id=None, log=None):
        cwd = Path(cwd)
        self.calls.append({'command': [str(part) for part in command], 'cwd': str(cwd), 'env': dict(env or {})})
        if log:
            Path(log).parent.mkdir(parents=True, exist_ok=True)
            with Path(log).open('a') as fp:
                fp.write(' '.join(str(part) for part in command) + '\n')
        if 'scripts.sugar_mapping' in ' '.join(str(part) for part in command):
            model = json.loads((cwd / 'model.json').read_text())
            write_frames(cwd, model['beads'], self.frames)
        elif 'fit_topology.sh' in ' '.join(str(part) for part in command):
            if self.fail_fit:
                return None
            # What `refine_bonded.py` leaves behind: the model, and the fit's own interaction
            # topology under the name the run's readers and the analysis layer's sources look for.
            (cwd / env['FINAL_ITP']).write_text(self.topology)
            (cwd / f"{env['FINAL_ITP'].removesuffix('.itp')}_ff_inter.itp").write_text(self.topology)
            (cwd / 'bonded_fit.json').write_text(json.dumps({'temperature_k': 300.0, 'torsions': [],
                                                             'manual_overrides': []}))
        return None

    @property
    def mappers(self):
        return [call for call in self.calls if 'scripts.sugar_mapping' in ' '.join(call['command'])]

    @property
    def fitters(self):
        return [call for call in self.calls if 'fit_topology.sh' in ' '.join(call['command'])]


@pytest.fixture
def candidate():
    return ddm_mapping()


def run_job(candidate, recorder, **kwargs):
    return fitting.start(candidate, engine='fast-forward', reference=REFERENCE, molecule_root=MOLECULES,
                         background=False, runner=recorder, **kwargs)


def test_a_fit_stores_a_revision_with_the_provenance_a_run_side_reading_needs(candidate):
    """D2/D3: the job's outputs are the terms, the diagnostics, the fit's provenance and the checks."""
    recorder = Recorder()
    record = run_job(candidate, recorder)

    assert record['status'] == 'completed'
    assert record['completed_steps'] == list(fitting.STEPS)
    assert record['revision'] == 1
    revision = parameterization.current(candidate)
    assert revision['engine'] == 'fast-forward'
    assert revision['options']['constraints_threshold'] == 10000.0
    assert revision['options']['temperature_k'] == 300.0
    assert revision['ensemble']['frames'] == 5, 'the frame count of the ensemble the engine saw'
    assert revision['ensemble']['source'].startswith('the mapped AA frames')
    assert revision['aa_reference']['run_id'] == REFERENCE['run_id']
    assert revision['temperature_source'] == 'the fit temperature this job was asked for'
    assert revision['refinement']['temperature_k'] == 300.0
    assert revision['engine_default_source'] == 'ff_inter'
    assert 'source' in revision['topology'] or '[ moleculetype ]' in revision['topology']
    assert revision['scientifically_validated'] is False
    assert record['revision_sha256'] == parameterization.revision_sha256(revision)


def test_the_job_prepares_the_same_stage_three_directory_a_run_prepares(candidate):
    """One definition of the invocation: the job runs the repository stage script with this fit's temperature, in a
    directory holding what stage 3 reads -- and, like a run, it carries no copy of the code."""
    recorder = Recorder()
    record = run_job(candidate, recorder)
    stage = Path(record['work']) / '3_initial_CG'

    assert not (stage / 'fit_topology.sh').exists()
    for name in ('bonded.py', 'refine_bonded.py', 'prepare_ring_constraints.py'):
        assert not (stage / name).exists(), f'{name} belongs to the repository, not to the fit'
    for name in ('DDM_initial.itp', 'topol.top', 'initial.mdp'):
        assert (stage / name).is_file(), name
    fit = recorder.fitters[0]
    assert fit['command'] == ['bash', '-e', '-o', 'pipefail',
                              str(cg.SCRIPTS / 'fit_topology.sh')]
    assert fit['env']['RUN_SETTING_TEMPERATURE_K'] == '300.0', 'the run numbers travel as environment'
    assert fit['env']['PYTHON'] and fit['env']['PYTHONPATH']
    # The Martini force field is installed once in the workspace and read where it lives: the topology names it by a
    # path relative to this scratch tree, so neither the tree nor a prepared run carries a copy of it.
    assert not (stage / 'martini_v3.0.0.itp').exists()
    include = martini3.include(cg.MARTINI_FF, stage)
    assert f'#include "{include}"' in (stage / 'topol.top').read_text()
    assert not Path(include).is_absolute() and (stage / include).is_file()
    assert not (stage.parent / '2_mapping' / 'sugar_mapping.py').exists()
    assert (stage.parent / '2_mapping' / 'mapped.xtc').is_file()
    assert recorder.mappers[0]['command'][1:3] == ['-m', 'dashboard.execution.scripts.sugar_mapping']


def test_the_mapped_frames_are_built_once_for_a_pair_and_reused_afterwards(candidate):
    """`work/<mapping>-<reference>/`: the second fit of the same pair reuses the frames, which is what
    makes "building the mapped trajectory if the AA reference has none" minutes paid once."""
    first = Recorder()
    run_job(candidate, first)
    second = Recorder()
    record = run_job(candidate, second)

    assert len(first.mappers) == 1 and first.fitters
    assert second.mappers == [], 'the frames already exist and the mapper refuses to overwrite them'
    assert second.fitters, 'and the fit still runs'
    assert record['revision'] == 2
    assert [item['revision'] for item in parameterization.revisions(candidate)] == [1, 2]


def test_a_second_engine_against_the_same_reference_reuses_the_same_frames(candidate):
    """The key is the pair and not the job or the engine: a BARTENDER fit of a model Fast-Forward has
    already mapped must read the same trajectory, or the two engines are not comparable."""
    first = Recorder()
    run_job(candidate, first)
    second = Recorder(bartender=True)
    work = fitting.work_dir(candidate, REFERENCE['run_id'])
    (work / '3_initial_CG' / 'gmx_out.itp').write_text('[bonds]\n1 2 1 0.30 5000\n')
    record = fitting.start(candidate, engine='bartender', reference=REFERENCE, molecule_root=MOLECULES,
                           background=False, runner=second)

    assert second.mappers == []
    assert record['status'] == 'completed'
    assert parameterization.current(candidate)['engine'] == 'bartender'
    assert parameterization.current(candidate)['ensemble']['trajectory'] == '1_AA-reference/prod/lig.xtc'
    stage = fitting.work_dir(candidate, REFERENCE['run_id']) / '3_initial_CG'
    assert (stage / 'DDM_ff_inter.itp').is_file(), 'the model is written where the checks read it'
    assert (stage / 'DDM.itp').read_text() == (stage / 'DDM_ff_inter.itp').read_text()


def test_the_engine_that_read_no_frames_is_gone_from_the_job_as_well_as_the_panel(candidate):
    """The button and the model's engine list go together: a job may not be started for the removed engine.

    It read the mapping alone, so it was the one engine a test could run without an ensemble -- and the one revision
    nobody had fitted. A caller still naming it gets the same refusal an unknown engine gets, rather than a job.
    """
    with pytest.raises(ValueError, match='Unknown fitting engine'):
        fitting.start(candidate, engine='reference-informed', molecule_root=MOLECULES,
                      background=False, runner=Recorder())
    assert fitting.jobs(candidate) == [], 'a refused engine leaves no job behind'


def test_the_two_checks_are_published_with_the_revision_and_question_the_terms(candidate):
    """D6: `dihedral-fit` and `bonded-cross-check` need no CG trajectory, so they run as part of
    producing a fit. Both sides of the cross-check read the same mapped frames the fit read."""
    recorder = Recorder()
    run_job(candidate, recorder)
    checks = parameterization.current(candidate)['checks']

    assert set(checks) == {'dihedral-fit', 'bonded-cross-check'}
    assert 'error' not in checks['bonded-cross-check']
    assert checks['bonded-cross-check']['threshold'] == 10000.0
    assert checks['bonded-cross-check']['estimate_from'] == '2_mapping/mapped.xtc'
    assert checks['dihedral-fit']['measured_from'] == '2_mapping/mapped.xtc'


def test_the_checks_read_the_fits_interaction_topology_and_not_the_coordinate_seed(candidate):
    """Both checks read `3_initial_CG/*_ff_inter.itp` when it is there, and the seed beside it when it
    is not -- which is why every engine that fits writes its model under that name: the analysis layer
    copies sources by pattern (`kinds.TABLE[name].sources`), so a model written under any other name is
    never handed to the check that would question it.
    """
    from dashboard.analysis.runs import bonded_estimate, dihedral_fit

    recorder = Recorder()
    record = run_job(candidate, recorder)
    work = Path(record['work'])
    stage = work / '3_initial_CG'

    assert dihedral_fit.publish(work, {})['ours_from'] == '3_initial_CG/DDM_ff_inter.itp'
    assert bonded_estimate.cross_check(work, {})['ours_from'] == '3_initial_CG/DDM_ff_inter.itp'

    (stage / 'DDM_ff_inter.itp').unlink()
    # The seeded topology, whatever this mapping's ring pass left it called: the stub mapper writes no
    # `ring_targets.json`, so `prepare_ring_constraints.py` has nothing to rename it with.
    assert dihedral_fit.publish(work, {})['ours_from'].endswith('DDM_initial.itp'), \
        'and a run with nothing fitted is reported as reading the seed rather than as failing'


def test_a_check_that_cannot_run_is_recorded_and_does_not_fail_the_fit(candidate):
    """A check must not be able to fail the thing it questions: an analysis with no frames is recorded
    with its own reason, and the revision is still stored."""
    recorder = Recorder()
    record = run_job(candidate, recorder)
    assert record['status'] == 'completed'

    work = Path(record['work']) / '2_mapping' / 'mapped.xtc'
    work.unlink()
    report = fitting._checks('fast-forward', {'work': str(Path(record['work']))},
                             {'temperature_k': 300.0, 'constraints_threshold': 10000.0})

    assert report['dihedral-fit']['error'] == 'the mapped trajectory is absent, so neither check has frames to read'
    assert report['bonded-cross-check']['error'] == report['dihedral-fit']['error']


def test_an_engine_that_writes_nothing_fails_the_job_with_its_own_words(candidate):
    recorder = Recorder(fail_fit=True)
    with pytest.raises(RuntimeError, match='did not write DDM.itp'):
        run_job(candidate, recorder)
    assert parameterization.current(candidate) is None, 'a failed fit stores no revision'


def test_a_queued_job_can_be_cancelled_and_the_run_store_is_never_touched(candidate, dashboard):
    """D2: it runs with a status and can be cancelled, and it is listed in the panel and not in Runs."""
    recorder = Recorder()

    def cancel_before_the_fit(command, cwd, **kwargs):
        if 'fit_topology.sh' in ' '.join(str(part) for part in command):
            fitting.cancel(kwargs['job_id'])
        return recorder(command, cwd, **kwargs)

    # A synchronous caller learns that the job did not finish, and the record says the same thing.
    with pytest.raises(fitting.Cancelled):
        fitting.start(candidate, engine='fast-forward', reference=REFERENCE, molecule_root=MOLECULES,
                      background=False, runner=cancel_before_the_fit)

    listed = fitting.jobs(candidate)
    assert len(listed) == 1 and listed[0]['status'] == 'cancelled'
    assert listed[0]['cancelled_at'] and listed[0]['ended_at']
    assert parameterization.current(candidate) is None
    assert dashboard.coordinator.database().all() == [], 'a fit makes no MD and is not a run'


def test_a_cancelled_job_is_not_overwritten_by_the_step_it_was_in(candidate):
    """The status is read back before every step and every poll, so a cancellation that lands while a
    tool runs is seen rather than overwritten by a write of the record that predates it."""
    entered = threading.Event()
    release = threading.Event()

    def blocking(command, cwd, **kwargs):
        entered.set()
        release.wait(timeout=20)
        return None

    queued = fitting.start(candidate, engine='fast-forward', reference=REFERENCE, molecule_root=MOLECULES,
                           background=True, runner=blocking, timeout=60)
    assert entered.wait(timeout=20), 'the job reached the mapper step'
    fitting.cancel(queued['id'])
    release.set()

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and fitting.job(queued['id'])['status'] == 'running':
        time.sleep(0.05)
    record = fitting.job(queued['id'])

    assert record['status'] == 'cancelled', 'a step that completes after a cancel does not reopen the job'
    assert record['cancelled_at'] and record['revision'] is None
    assert parameterization.current(candidate) is None


def test_a_queued_job_runs_in_a_thread_and_is_listed_while_it_does(candidate, monkeypatch):
    """The default is a thread the panel polls: `start` returns the record and does not block."""
    ran = threading.Event()

    def fake_execute(job_id, **kwargs):
        ran.set()
        return fitting.job(job_id)

    monkeypatch.setattr(fitting, 'execute', fake_execute)
    record = fitting.start(candidate, engine='fast-forward', reference=REFERENCE, molecule_root=MOLECULES,
                           timeout=60)

    assert record['id'] and record['status'] in fitting.STATUSES
    assert ran.wait(timeout=20)
    assert fitting.jobs(candidate)[0]['id'] == record['id']
    assert Path(record['log']).is_file()


def test_a_finished_job_is_not_cancellable(candidate):
    recorder = Recorder()
    record = run_job(candidate, recorder)
    assert fitting.cancel(record['id'])['status'] == 'completed'
    assert fitting.job(record['id'])['status'] == 'completed'


def test_the_jobs_are_listed_for_the_mapping_that_owns_them(candidate):
    recorder = Recorder()
    first = run_job(candidate, recorder)
    second = run_job(candidate, recorder)

    listed = [record['id'] for record in fitting.jobs(candidate)]
    assert set(listed) == {first['id'], second['id']}
    assert fitting.latest(candidate)['id'] in (first['id'], second['id'])
    renamed = ddm_mapping(name='DDM · another')
    assert [record['id'] for record in fitting.jobs(renamed)] == listed, 'a rename is the same model'
    changed = copy.deepcopy(candidate)
    changed['beads'][0]['name'] = 'B99'
    assert fitting.jobs(changed) == [], 'a different model has its own jobs'
    assert fitting.job(first['id'])['engine'] == 'fast-forward'
    with pytest.raises(KeyError):
        fitting.job('0' * 16)


def test_the_jobs_are_listed_by_the_hashes_a_hash_addressed_caller_holds(candidate):
    """A route holds hashes, not a mapping, so `jobs` owns the filter -- and the limit follows it.

    `content_hash` answers compatibility (a rename keeps its jobs) and `mapping_hash` answers provenance
    (the candidate a job was queued for, which is all a caller can know before the job saves a record).
    `second` is the newer job and belongs to another model: a limit applied before the filter would
    answer nothing here, hiding this model's own job behind another model's newer one.
    """
    recorder = Recorder()
    first = run_job(candidate, recorder)
    other = ddm_mapping(name='DDM · another')
    other['beads'][0]['label'] = 'v'
    second = run_job(other, recorder)
    content = mappings.content_identity(candidate)

    assert [record['id'] for record in fitting.jobs(content_hash=content)] == [first['id']]
    assert [record['id'] for record in fitting.jobs(
        mapping_hash=mappings.candidate_identity(candidate))] == [first['id']]
    assert [record['id'] for record in fitting.jobs(content_hash=content, limit=1)] == [first['id']]
    assert [record['id'] for record in fitting.jobs()] == [second['id'], first['id']]


def test_a_job_names_its_engine_and_refuses_one_it_does_not_have(candidate):
    with pytest.raises(ValueError, match='Unknown fitting engine'):
        fitting.start(candidate, engine='gromacs', reference=REFERENCE, molecule_root=MOLECULES,
                      background=False, runner=Recorder())
    with pytest.raises(ValueError, match='link an AA reference'):
        fitting.start(candidate, engine='fast-forward', molecule_root=MOLECULES, background=False,
                      runner=Recorder())


def test_the_options_a_job_records_are_the_mappings_and_never_a_free_hand():
    """D4a: the mapping owns the torsion model, and a revision that a run will read cannot carry a
    scale the mapping's own validator would refuse."""
    candidate = ddm_mapping()
    candidate['bonded_options'] = {'torsion_model': 'circular-harmonic', 'torsion_scale': 1.2}
    options = parameterization.normalise_options(candidate, {})
    assert options['torsion_model'] == 'circular-harmonic' and options['torsion_scale'] == 1.2

    with pytest.raises(ValueError, match='Torsion stiffness scale'):
        parameterization.normalise_options(candidate, {'torsion_scale': 9})
    with pytest.raises(ValueError, match='Unknown parameterization option'):
        parameterization.normalise_options(candidate, {'threads': 4})


def test_a_reference_that_cannot_be_resolved_is_refused_before_a_job_is_queued(candidate):
    """D4: a model whose reference is gone says so rather than silently fitting against nothing."""
    with pytest.raises(ValueError, match='Invalid AA source run ID'):
        fitting.resolve_reference('not-a-run-id')
    with pytest.raises((ValueError, FileNotFoundError, OSError)):
        fitting.resolve_reference('f' * 12, runs_root=Path('/nonexistent/runs'))


def test_a_job_is_found_by_its_own_id_whatever_its_mapping_hash_says(candidate):
    """The poll's key. `content_hash` is a mapping's history; `job_id` is the job the panel queued."""
    recorder = Recorder()
    first = run_job(candidate, recorder)
    second = run_job(candidate, recorder)

    assert [record['id'] for record in fitting.jobs(job_id=first['id'])] == [first['id']]
    assert [record['id'] for record in fitting.jobs(job_id=second['id'])] == [second['id']]
    assert fitting.jobs(job_id='0' * 16) == []
