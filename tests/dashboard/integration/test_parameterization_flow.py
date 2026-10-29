"""The whole seam: a fit produces a revision, a run consumes it, and the layers agree about which.

This is the integration of the pieces the unit tests each hold still: the job (which never touches the
run store), the store (whose current revision is what a run reads), `prepare` (which resolves the
run's own stage plan from what it recorded), the coordinator's reader of that plan, and the analysis
layer's declared inputs (which have to match the files the consuming stage writes, or the two checks
would be declared against a directory that no longer holds what they read).

No tool is run: the job's engine is stood in for at the command runner, as in the unit tests, and the
AA reference is a resolved dictionary rather than a store lookup.
"""
import copy
import json
from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pytest

from dashboard.analysis import kinds
from dashboard.execution import workflow
from dashboard.execution.adapters import cg
from dashboard.models import mappings
from dashboard.models.bonded import fitting, parameterization
from dashboard.models.mappings.context import as_structure, build_context
from dashboard.models.molecules import aa as aa_molecules

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MOLECULES = PROJECT_ROOT / 'molecules'
REFERENCE = {'source_run_id': '2' * 12, 'sha256': {}}
RESOLVED = {'run_id': '2' * 12, 'directory': '/nonexistent/reference', 'reference_sha256': 'ab' * 32,
            'record': {'reference_sha256': 'ab' * 32, 'frames': 900,
                       'aa_reference': {'run_id': '2' * 12, 'reference_sha256': 'ab' * 32,
                                        'molecule_identity': 'cd' * 32, 'temperature_k': 300.0,
                                        'production_ns': 10.0}}}
TOPOLOGY = ('[ moleculetype ]\nDDM 1\n\n[ atoms ]\n1 C1 1 DDM B01 1 0 72\n2 C1 1 DDM B02 2 0 72\n\n'
            '[ bonds ]\n1 2 1 0.31 5000\n')


def ddm_mapping():
    context = build_context(MOLECULES, 'DDM')
    candidate = mappings.automatic_candidate(as_structure(context), 'DDM')
    candidate.update(schema_version=3, molecule_id='DDM',
                     molecule_snapshot=copy.deepcopy(context['snapshot']))
    return candidate


def engine(mapping_dir, beads, frames=5):
    """A stand-in for `sugar_mapping.py`: it writes the frames into the directory it was run in."""
    names = [bead['name'] for bead in beads]
    universe = mda.Universe.empty(len(names), trajectory=True)
    universe.add_TopologyAttr('name', names)
    universe.add_TopologyAttr('resname', ['LIG'])
    universe.add_TopologyAttr('resid', [1])
    positions = np.asarray([[index * 0.45, 0.0, 0.0] for index in range(len(names))], dtype=np.float32)
    universe.atoms.positions = positions
    universe.atoms.write(str(Path(mapping_dir) / 'mapped.gro'))
    trajectory = np.asarray([positions] * frames, dtype=np.float32)
    universe.trajectory = mda.coordinates.memory.MemoryReader(trajectory, order='fac')
    with mda.Writer(str(Path(mapping_dir) / 'mapped.xtc'), n_atoms=len(names)) as writer:
        for _ in universe.trajectory:
            writer.write(universe.atoms)
    (Path(mapping_dir) / 'mapping_validation.json').write_text(json.dumps({'frames': frames}))


def runner(command, cwd, *, env=None, timeout=None, job_id=None, log=None):
    cwd = Path(cwd)
    if 'scripts.sugar_mapping' in ' '.join(str(part) for part in command):
        engine(cwd, json.loads((cwd / 'model.json').read_text())['beads'])
    elif 'fit_topology.sh' in ' '.join(str(part) for part in command):
        (cwd / env['FINAL_ITP']).write_text(TOPOLOGY)
        (cwd / 'DDM_ff_inter.itp').write_text(TOPOLOGY)
        (cwd / 'bonded_fit.json').write_text(json.dumps({'temperature_k': 300.0}))
        # `refine_bonded` measures the AA reference's own interaction histograms while fitting, and leaves them beside
        # the topology; `save` records them with the revision and a consuming run stages them for the assessment.
        for name in ('B01_B11_bonds_distr.dat', 'B01_B02_B05_angles_distr.dat'):
            (cwd / name).write_text('0.005 0.0\n0.015 1.0\n')
    return None


@pytest.fixture
def fitted(dashboard):
    """One fit of the packaged DDM model against a resolved reference, in the app's own workspace."""
    candidate = ddm_mapping()
    record = fitting.start(candidate, engine='fast-forward', reference=RESOLVED, molecule_root=MOLECULES,
                           background=False, runner=runner)
    return dashboard, candidate, record


def test_the_job_is_not_a_run_and_its_work_is_not_a_run_directory(fitted):
    """D2: it makes no MD, so it is listed in the panel and has no line in Runs -- and its frames sit
    in the workspace's own parameterization directory rather than in a run's stage 2."""
    dashboard, candidate, record = fitted

    assert record['status'] == 'completed'
    assert dashboard.coordinator.database().all() == []
    assert list(dashboard.paths.runs.glob('*')) == [] if dashboard.paths.runs.is_dir() else True
    assert Path(record['work']).is_relative_to(dashboard.paths.workspace / 'parameterizations')
    assert (dashboard.paths.workspace / 'parameterizations' / 'jobs' / f"{record['id']}.json").is_file()
    assert parameterization.current(candidate)['engine'] == 'fast-forward'


def test_the_current_revision_is_what_a_run_consumes_and_a_second_fit_moves_it(fitted, tmp_path, monkeypatch):
    """The revision strip is the interface: a run reads whatever is current, and a fit appended later
    is what the next run reads. The panel's own list is the same fact, newest first."""
    from dashboard.analysis.runs import references as aa_references
    dashboard, candidate, first = fitted
    monkeypatch.setattr(aa_references, 'resolve', lambda *args, **kwargs: REFERENCE)
    monkeypatch.setattr(cg, 'tool_metadata', lambda: {})

    fitting.start(candidate, engine='fast-forward', reference=RESOLVED, molecule_root=MOLECULES,
                  background=False, runner=runner)
    run = tmp_path / 'run'
    run.mkdir()
    cg.prepare(run, molecule_snapshot=aa_molecules.selection(MOLECULES, 'DDM'),
               mapping_candidate=candidate, shared_reference=REFERENCE, molecule_root=MOLECULES)
    record = json.loads((run / 'manifest.json').read_text())['bonded']

    assert record['revision'] == 2
    assert [job['revision'] for job in fitting.jobs(candidate)] == [2, 1]
    assert parameterization.summary(candidate)['revision'] == 2
    assert (run / '3_initial_CG/parameterization.json').is_file()
    assert json.loads((run / '3_initial_CG/parameterization.json').read_text())['revision'] == 2


def test_the_coordinators_reader_and_the_run_agree_about_stage_three(fitted, tmp_path, monkeypatch):
    """`workflow.stage_definitions` is what the executor walks. It must resolve the same plan, and the
    same required outputs, from the manifest `prepare` wrote."""
    from dashboard.analysis.runs import references as aa_references
    _, candidate, _ = fitted
    monkeypatch.setattr(aa_references, 'resolve', lambda *args, **kwargs: REFERENCE)
    monkeypatch.setattr(cg, 'tool_metadata', lambda: {})
    run = tmp_path / 'run'
    run.mkdir()
    cg.prepare(run, molecule_snapshot=aa_molecules.selection(MOLECULES, 'DDM'),
               mapping_candidate=candidate, shared_reference=REFERENCE, molecule_root=MOLECULES)
    manifest = json.loads((run / 'manifest.json').read_text())

    plan, inputs, outputs = workflow.stage_definitions(manifest)
    stage = dict(plan)['CG parameterization']

    assert stage == '3_initial_CG/use_parameterization.sh'
    assert 'parameterization.json' in inputs['CG parameterization']
    assert outputs['CG parameterization'] == ('mapped.tpr', 'DDM.itp', 'parameterization_used.json')
    assert workflow.resumable_stages(run, manifest)[0] == plan[0][0], 'and it starts from a coherent prefix'


def test_the_checks_the_analysis_layer_declares_still_find_what_the_consuming_stage_writes(fitted, tmp_path, monkeypatch):
    """D6's other half: the two re-derivations run as analyses of an AA-CG run as well. Their declared
    sources are patterns over the run's stage directories, so they must match the files a stage that
    consumed its model's terms writes -- `*_parameterized.itp` and the mapped frames -- rather than the
    fit's own output names, which such a run does not have."""
    from dashboard.analysis.runs import references as aa_references
    _, candidate, _ = fitted
    monkeypatch.setattr(aa_references, 'resolve', lambda *args, **kwargs: REFERENCE)
    monkeypatch.setattr(cg, 'tool_metadata', lambda: {})
    run = tmp_path / 'run'
    run.mkdir()
    cg.prepare(run, molecule_snapshot=aa_molecules.selection(MOLECULES, 'DDM'),
               mapping_candidate=candidate, shared_reference=REFERENCE, molecule_root=MOLECULES)
    # What the run will hold once stage 2 and stage 3 have run: this is the state the analyses are
    # resolved against, written out for the patterns to be matched against. A stage directory here is
    # the run directory itself, because `prepare` was called on it rather than through the run type.
    # `DDM_ff_inter.itp` is `use_parameterization.py`'s other name for the model, and the only one the
    # analysis layer's declared sources select -- which is what makes the two checks read the model
    # rather than the coordinate seed beside it.
    run.joinpath('2_mapping/mapped.gro').write_text('x')
    run.joinpath('2_mapping/mapped.xtc').write_text('x')
    run.joinpath('3_initial_CG/DDM_ff_inter.itp').write_text(TOPOLOGY)
    written = {path.relative_to(run).as_posix() for path in run.rglob('*') if path.is_file()}

    for name in ('dihedral-fit', 'bonded-cross-check'):
        declared = kinds.TABLE[name].sources
        missing = [pattern for pattern in declared
                   if not any(Path(relative).match(pattern) or relative == pattern for relative in written)]
        assert missing == [], f'{name} is declared against files this run will not have: {missing}'
        assert name in kinds.default_for('aa_cg'), 'and an AA-CG run still gets both without being asked'
