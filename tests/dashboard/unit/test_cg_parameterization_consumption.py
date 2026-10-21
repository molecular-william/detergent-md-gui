"""What a run does with a model that already carries a parameterization, and what it says it did.

D5 of `docs/design/2026-10-16-parameterization-and-new-run.md`: the choice of fit-or-reuse is a
property of the model and not of the run, so the run panel has nothing to choose and the manifest
records which happened. These tests read the *prepared run directory* and the manifest rather than the
branch that decided it, and they read the stage contract back out of the manifest the run wrote, which
is the claim that matters: every later reader -- the coordinator, a resume, a test -- resolves the
same plan from the same recorded fact.

They also exercise the stage that does the consuming: `use_parameterization.py` writes the model's
terms and its own record of not having fitted, and deliberately does not write `bonded_fit.json`.
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dashboard.execution.adapters import cg
from dashboard.execution.adapters.cg_names import CGNames
from dashboard.models import mappings
from dashboard.models.bonded import parameterization
from dashboard.models.mappings.context import as_structure, build_context
from dashboard.models.molecules import aa as aa_molecules

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MOLECULES = PROJECT_ROOT / 'molecules'
REFERENCE = {'source_run_id': '1' * 12, 'sha256': {}}
REVISION = {'engine': 'fast-forward', 'topology': '[ moleculetype ]\nDDM 1\n\n[ atoms ]\n',
            'options': {'constraints_threshold': 10000.0, 'temperature_k': 300.0,
                        'torsion_model': 'circular-harmonic', 'torsion_scale': 1.0},
            'ensemble': {'frames': 20001, 'trajectory': '2_mapping/mapped.xtc',
                         'source': 'the mapped AA frames'},
            'aa_reference': {'run_id': 'a54ac8f64710', 'reference_sha256': 'ab' * 32,
                             'molecule_identity': 'cd' * 32, 'temperature_k': 300.0,
                             'production_ns': 10.0}}


def ddm_mapping():
    context = build_context(MOLECULES, 'DDM')
    candidate = mappings.automatic_candidate(as_structure(context), 'DDM')
    candidate.update(schema_version=3, molecule_id='DDM',
                     molecule_snapshot=copy.deepcopy(context['snapshot']))
    return candidate


def another_mapping():
    """The same molecule and beads, a different model.

    A ring's dilation is part of the mapping's identity and not part of its name, so changing one
    gives a mapping that is still valid, still DDM, and carries no parameterization of its own --
    which is the only way to ask `prepare` to fit. Renaming a bead instead would break the virtual
    site that names it.
    """
    candidate = ddm_mapping()
    candidate['rings'][0]['scale'] = 1.2
    return candidate


def parameterizations_digest(path):
    """The digest a recorded histogram is named by. Spelled out here so a drifted rule fails these tests."""
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fitted(candidate, revision=None, files=('B01_B11_bonds_distr.dat', 'B01_B02_B05_angles_distr.dat')):
    """Save a revision the way a real fit does: with the AA reference's histograms in its working directory.

    `refine_bonded` measures them while fitting, and `parameterization.save` copies and hashes them beside the revision.
    They are the baseline `ff_assess` scores a CG run against, so a run that consumes this revision stages them.
    """
    work = parameterization.work_root() / f'{parameterization.content_identity(candidate)}-{REFERENCE["source_run_id"]}'
    stage = work / '3_initial_CG'
    stage.mkdir(parents=True, exist_ok=True)
    for name in files:
        (stage / name).write_text('0.005 0.0\n0.015 1.0\n')
    return parameterization.save(candidate, revision or REVISION, work=work)


def prepared(tmp_path, monkeypatch, **arguments):
    """One real `prepare()` into a scratch run directory, with the outside world's two seams stubbed."""
    from dashboard.analysis.runs import references as aa_references
    monkeypatch.setattr(aa_references, 'resolve', lambda *args, **kwargs: REFERENCE)
    monkeypatch.setattr(cg, 'tool_metadata', lambda: {'gmx': {'path': '/usr/bin/gmx'}})
    run = tmp_path / 'run'
    run.mkdir(parents=True)
    cg.prepare(run, molecule_snapshot=aa_molecules.selection(MOLECULES, 'DDM'),
               mapping_candidate=arguments.pop('mapping_candidate', ddm_mapping()),
               shared_reference=REFERENCE, molecule_root=MOLECULES, **arguments)
    return run


def manifest(run):
    return json.loads((run / 'manifest.json').read_text())


def test_a_model_with_a_parameterization_is_consumed_and_the_run_says_it_did_not_fit(tmp_path, monkeypatch):
    """D5's first honest state. Stage 3 is a different script, and the stage it replaces is not there
    for a reader to mistake for what ran."""
    candidate = ddm_mapping()
    fitted(candidate)
    run = prepared(tmp_path, monkeypatch, mapping_candidate=candidate)

    assert (run / '3_initial_CG/use_parameterization.sh').is_file()
    assert not (run / '3_initial_CG/fit_topology.sh').exists(), 'a stage named for fitting must not sit there'
    staged = json.loads((run / '3_initial_CG/parameterization.json').read_text())
    record = manifest(run)['bonded']

    assert staged['revision'] == 1 and staged['topology'] == REVISION['topology']
    assert record['consumes_parameterization'] is True and record['fitted'] is False
    assert record['revision'] == 1 and record['engine'] == 'fast-forward'
    assert record['torsion_model'] == 'circular-harmonic'
    assert record['revision_sha256'] == parameterization.revision_sha256(parameterization.current(candidate))
    assert record['aa_reference']['run_id'] == 'a54ac8f64710'


def test_the_run_resolves_the_same_stage_plan_from_what_it_recorded(tmp_path, monkeypatch):
    """The contract is a function of the run's own manifest, so a reader two frames later cannot
    disagree with the run about which script stage 3 ran -- or about what it had to produce."""
    from dashboard.execution import protocol  # the coordinator's own reader

    candidate = ddm_mapping()
    fitted(candidate)
    consuming = prepared(tmp_path / 'consuming', monkeypatch, mapping_candidate=candidate)
    # A *different model* is what makes a run fit: the key is the mapping's content identity, so a
    # second prepared run of the same beads would consume the revision the first one left.
    fitting = prepared(tmp_path / 'fitting', monkeypatch, mapping_candidate=another_mapping())

    plan, _, outputs = protocol.adapter_for('aa_cg').stage_contract(manifest(consuming))
    assert dict(plan)['CG parameterization'] == '3_initial_CG/use_parameterization.sh'
    assert outputs['CG parameterization'] == ('mapped.tpr', 'DDM.itp', 'parameterization_used.json')
    assert manifest(consuming)['stage_plan'] == [[name, relative] for name, relative in plan]

    plan, inputs, outputs = protocol.adapter_for('aa_cg').stage_contract(manifest(fitting))
    assert dict(plan)['CG parameterization'] == '3_initial_CG/fit_topology.sh'
    assert outputs['CG parameterization'][0] == 'mapped.tpr'
    assert '_distr.dat' in ' '.join(outputs['CG parameterization'])


def test_the_assessment_stage_is_the_shape_of_the_fit_that_did_not_happen(tmp_path, monkeypatch):
    """An atomistic reference distribution is a fit's output, so a run that did not fit has none and
    its assessment stage is declared without them -- and the run's own limitations say so."""
    candidate = ddm_mapping()
    fitted(candidate)
    run = prepared(tmp_path, monkeypatch, mapping_candidate=candidate)

    _, inputs, _ = cg.stage_contract(CGNames.ddm_defaults(), parameterized=True)
    assert inputs['CG assessment (ff_assess)'] == (
        '../4_CG_sim/prod/lig_CG.xtc', '../4_CG_sim/prod/lig_CG.tpr',
        '../4_CG_sim/prod/lig_CG.gro', '../3_initial_CG/DDM_initial.itp')
    limitations = ' '.join(manifest(run)['limitations'])
    assert 'wrote no `*_distr.dat`' in limitations
    assert 'revision 1' in limitations


def test_a_model_with_no_parameterization_is_fitted_by_the_run_and_the_run_records_that(tmp_path, monkeypatch):
    """D5's second honest state: the whole old behaviour, and a manifest that says it happened."""
    run = prepared(tmp_path, monkeypatch, mapping_candidate=another_mapping())
    record = manifest(run)['bonded']

    assert (run / '3_initial_CG/fit_topology.sh').is_file()
    assert not (run / '3_initial_CG/use_parameterization.sh').exists()
    assert not (run / '3_initial_CG/parameterization.json').exists()
    assert record['consumes_parameterization'] is False and record['fitted'] is True
    assert record['revision'] is None and record['engine'] is None
    assert record['source'] == 'fitted by this run, in stage 3, from the AA reference it consumes'
    # The fit script is stamped with the run's own temperature, as it always was (303.15 K rounds to
    # 303 for `ff_inter`, which declares `-temperature` an int).
    assert '-temperature 303' in (run / '3_initial_CG/fit_topology.sh').read_text()


def test_a_fit_against_another_reference_is_named_in_the_runs_own_limitations(tmp_path, monkeypatch):
    """D4: the model's reference is the run's default, and a run that consumes a different one says so
    rather than presenting a fit of one ensemble beside a simulation of another."""
    candidate = ddm_mapping()
    fitted(candidate)
    run = prepared(tmp_path, monkeypatch, mapping_candidate=candidate)
    limitations = ' '.join(manifest(run)['limitations'])
    assert 'do not share a reference' in limitations, 'the revision was fitted against a54ac8f64710'

    other = ddm_mapping()
    other['beads'] = copy.deepcopy(other['beads'])
    fitted(other, {**REVISION, 'aa_reference': {**REVISION['aa_reference'],
                                                'run_id': REFERENCE['source_run_id']}})
    renamed = prepared(tmp_path / 'same', monkeypatch, mapping_candidate=other)
    assert 'do not share a reference' not in ' '.join(manifest(renamed)['limitations'])


def test_the_run_type_publishes_which_of_the_two_things_will_happen(tmp_path, monkeypatch):
    """The panel renders this sentence rather than composing it, so the promise a run makes about
    fitting is stated next to the code that keeps it."""
    plain = cg._parameterization_state({'mapping_candidate': ddm_mapping()})
    candidate = ddm_mapping()
    fitted(candidate)
    state = cg._parameterization_state({'mapping_candidate': candidate})

    assert plain['parameterized'] is False and plain['terms'] is None
    assert plain['statement'] == ('this model carries no parameterization -- the run will fit it in '
                                  'stage 3 and record that it did')
    assert state['parameterized'] is True and state['revision'] == 1
    assert state['engine_label'] == 'Fast-Forward fit (ff_inter)'
    assert 'a54ac8f64710' in state['statement'] and 'does not re-fit' in state['statement']
    assert 'No mapping is selected' in cg._parameterization_state({})['statement']


def test_the_readiness_answer_carries_that_state_beside_its_checks(tmp_path, monkeypatch):
    """A top-level key and not a `checks` entry: both states are ready, so it is not a prerequisite."""
    from dashboard.analysis.runs import references as aa_references
    monkeypatch.setattr(aa_references, 'resolve', lambda *args, **kwargs: REFERENCE)
    monkeypatch.setattr(cg, 'readiness', lambda *args, **kwargs: {'ready': True, 'checks': [], 'blockers': []})
    answer = cg._protocol_readiness({'molecule_id': 'DDM', 'mapping_candidate': ddm_mapping(),
                                     'molecule_root': str(MOLECULES)})

    assert answer['ready'] is True
    assert answer['parameterization']['parameterized'] is False
    assert 'stage 3' in answer['parameterization']['statement']


def test_a_record_the_run_cannot_read_is_a_blocker_and_not_a_promise_to_fit(tmp_path, monkeypatch):
    """`prepare` refuses a corrupt record, so readiness must not answer "the run will fit it in
    stage 3": that is a promise the run cannot keep. The error is named instead."""
    candidate = ddm_mapping()
    fitted(candidate)
    path = parameterization.records_root() / f'{parameterization.content_identity(candidate)}.json'
    path.write_text('{not json')
    state = cg._parameterization_state({'mapping_candidate': candidate})

    assert 'cannot be read' in state['statement'] and state['error']
    assert 'Unreadable parameterization record' in state['error']
    assert 'stage 3' not in state['statement'], 'no promise to fit over a fit that was made and lost'


def test_the_consuming_stage_writes_the_model_terms_and_the_record_that_it_did_not_fit(tmp_path):
    """The stage's own artefact, run for real: the model's terms under both names the run's readers
    use, and a record that says fitted `false`. `bonded_fit.json` -- what a fitting stage writes -- is
    deliberately absent, because a stage that skips its fit must not look like one that fitted."""
    stage = tmp_path / '3_initial_CG'
    stage.mkdir()
    (stage / 'parameterization.json').write_text(json.dumps({**REVISION, 'revision': 3,
                                                             'created_at': '2026-01-01T00:00:00+00:00',
                                                             'checks': {'dihedral-fit': {'rows': []}}}))
    script = PROJECT_ROOT / 'dashboard/execution/scripts/use_parameterization.py'

    subprocess.run([sys.executable, str(script)], cwd=stage, check=True,
                   env={'PATH': '/usr/bin', 'FINAL_ITP': 'DDM.itp'})

    assert (stage / 'DDM.itp').read_text() == REVISION['topology']
    assert (stage / 'DDM_ff_inter.itp').read_text() == REVISION['topology'], \
        'the name the run\'s checks and the analysis layer\'s sources read'
    assert not (stage / 'bonded_fit.json').exists()
    record = json.loads((stage / 'parameterization_used.json').read_text())
    assert record['fitted'] is False and record['revision'] == 3
    assert record['engine'] == 'fast-forward' and record['torsion_model'] == 'circular-harmonic'
    assert record['constraints_threshold'] == 10000.0 and record['temperature_k'] == 300.0
    assert record['aa_reference']['run_id'] == 'a54ac8f64710'
    assert record['checks_published_with_the_revision'] == ['dihedral-fit']
    # The same digest the store computes, spelled out here so a script that drifted from the store's
    # rule fails this test rather than agreeing with itself.
    stored = {**REVISION, 'revision': 3, 'checks': {'dihedral-fit': {'rows': []}}}
    assert record['revision_sha256'] == mappings.canonical_sha256(stored)
    assert 'did not fit' in record['statement']


def test_the_stage_refuses_to_run_when_it_was_staged_without_a_parameterization(tmp_path):
    stage = tmp_path / '3_initial_CG'
    stage.mkdir()
    script = PROJECT_ROOT / 'dashboard/execution/scripts/use_parameterization.py'
    result = subprocess.run([sys.executable, str(script)], cwd=stage, env={'PATH': '/usr/bin'},
                            capture_output=True, text=True)

    assert result.returncode != 0 and 'staged without one' in result.stderr


def test_the_consuming_script_still_locks_the_rings_and_builds_the_same_tpr():
    """The ring pass belongs to the mapping and not to the fit, so it survives; and `mapped.tpr` is
    built from the same seeded topology the fit path builds it from, because the model's own terms are
    not in that tpr in either case."""
    executable = [line for line in (cg.SCRIPTS / 'use_parameterization.sh').read_text().splitlines()
                  if not line.lstrip().startswith('#')]

    assert 'python use_parameterization.py' in executable
    assert 'python prepare_ring_constraints.py' in executable
    assert any(line.startswith('gmx grompp') and '-c ../2_mapping/mapped.gro' in line for line in executable)
    assert not [line for line in executable if 'ff_inter' in line], 'nothing here fits anything'


def test_the_fits_reference_histograms_are_recorded_with_the_revision(tmp_path):
    """The baseline belongs to the model, not to a working directory: `save` copies it beside the revision, hashed.

    A working directory is scratch -- deleting the mapping deletes it, and a re-fit overwrites it -- so a baseline left
    there would let a run's score depend on a folder that can change underneath it.
    """
    candidate = ddm_mapping()
    item = fitted(candidate)

    recorded = parameterization.distributions(candidate)
    assert item['distributions']['files'] and recorded['revision'] == 1
    assert [entry['name'] for entry in recorded['files']] == ['B01_B02_B05_angles_distr.dat',
                                                              'B01_B11_bonds_distr.dat']
    for entry in recorded['files']:
        path = recorded['directory'] / entry['name']
        assert path.is_file()
        assert parameterizations_digest(path) == entry['sha256']
    # A revision fitted without a working directory records none, and says so by answering None rather than [].
    plain = ddm_mapping()
    plain['rings'][0]['scale'] = 1.2
    parameterization.save(plain, {**REVISION, 'engine': 'bartender'})
    assert parameterization.distributions(plain) is None


def test_deleting_the_mapping_takes_the_recorded_histograms_and_reports_them(tmp_path):
    candidate = ddm_mapping()
    fitted(candidate)
    content = parameterization.content_identity(candidate)
    assert parameterization.revisions_root(content).is_dir()

    removed = parameterization.delete(content)

    assert removed['distributions'] == f'{content}.revisions'
    assert not parameterization.revisions_root(content).exists()


def test_the_consuming_run_stages_the_baseline_into_the_stage_the_assessment_reads(tmp_path, monkeypatch):
    """`ff_assess` reads `<group>_<type>_distr.dat` from its `-d` directory and never computes them.

    Stage 5 passes `-d ../3_initial_CG`, so that is where a consuming run's copy has to land -- and the run records
    which files it staged, so a reader can see what its numbers were measured against.
    """
    candidate = ddm_mapping()
    fitted(candidate)
    run = prepared(tmp_path, monkeypatch, mapping_candidate=candidate)

    staged = run / '3_initial_CG'
    inventory = json.loads((staged / 'distributions.json').read_text())
    assert [entry['name'] for entry in inventory['files']] == ['B01_B02_B05_angles_distr.dat',
                                                               'B01_B11_bonds_distr.dat']
    for entry in inventory['files']:
        assert (staged / entry['name']).is_file()
        assert parameterizations_digest(staged / entry['name']) == entry['sha256']
    assert manifest(run)['bonded']['reference_distributions'] == ['B01_B02_B05_angles_distr.dat',
                                                                 'B01_B11_bonds_distr.dat']


def test_a_model_with_no_recorded_baseline_is_refused_before_it_simulates(tmp_path, monkeypatch):
    """The cheap place to fail. A run with no baseline simulates for an hour and then reports `Overall Score : nan`,
    because stage 5 averages zero comparable interactions -- so `prepare` names the missing evidence instead."""
    candidate = ddm_mapping()
    parameterization.save(candidate, REVISION)

    with pytest.raises(ValueError) as error:
        prepared(tmp_path, monkeypatch, mapping_candidate=candidate)

    message = str(error.value)
    assert 'records no AA reference distributions' in message
    assert 'could not score a run of it' in message and 'Re-fit' in message

    # An engine that measures none gets its own sentence: re-fitting with the same one would change nothing.
    bartender = ddm_mapping()
    bartender['rings'][0]['scale'] = 1.2
    parameterization.save(bartender, {**REVISION, 'engine': 'bartender'})
    with pytest.raises(ValueError) as engine_error:
        prepared(tmp_path / 'bartender', monkeypatch, mapping_candidate=bartender)
    assert 'fitted by bartender' in str(engine_error.value)
    assert 'Fit with fast-forward' in str(engine_error.value)


def test_the_consuming_stage_records_the_baseline_and_refuses_a_changed_one(tmp_path):
    """The stage verifies what prepare staged, and names the file when it disagrees.

    Defence in depth, and the place a reader looks for what the run's numbers will be measured against: the record the
    stage writes is `parameterization_used.json`, so the baseline is named there beside the terms.
    """
    script = PROJECT_ROOT / 'dashboard/execution/scripts/use_parameterization.py'
    stage = tmp_path / '3_initial_CG'
    stage.mkdir()
    (stage / 'parameterization.json').write_text(json.dumps({**REVISION, 'revision': 1}))
    (stage / 'B01_B11_bonds_distr.dat').write_text('0.005 0.0\n')
    record = {'directory': '.', 'files': [{'name': 'B01_B11_bonds_distr.dat',
                                           'sha256': parameterizations_digest(stage / 'B01_B11_bonds_distr.dat')}]}
    (stage / 'distributions.json').write_text(json.dumps(record))

    subprocess.run([sys.executable, str(script)], cwd=stage, check=True,
                   env={'PATH': '/usr/bin', 'FINAL_ITP': 'DDM.itp'})
    written = json.loads((stage / 'parameterization_used.json').read_text())
    assert written['reference_distributions'] == record['files']

    (stage / 'B01_B11_bonds_distr.dat').write_text('0.005 9.9\n')
    result = subprocess.run([sys.executable, str(script)], cwd=stage, env={'PATH': '/usr/bin', 'FINAL_ITP': 'DDM.itp'},
                            capture_output=True, text=True)
    assert result.returncode != 0 and 'does not match the digest' in result.stderr

