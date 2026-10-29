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


def fitted(candidate, revision=None,
           files=('B01_B11_bonds_distr.dat', 'B01_B02_B05_angles_distr.dat', '1_B01_1_B02_distances_distr.dat')):
    """Save a revision the way a real fit does: with the AA reference's histograms in its working directory.

    `ff_inter -dists -dist-matrix` measures them while fitting, and `parameterization.save` copies and hashes them
    beside the revision. They are the baseline `ff_assess` scores a CG run against, so a run that consumes this revision
    stages them.
    """
    work = parameterization.work_root() / f'{parameterization.content_identity(candidate)}-{REFERENCE["source_run_id"]}'
    stage = work / '3_initial_CG'
    stage.mkdir(parents=True, exist_ok=True)
    for name in files:
        (stage / name).write_text('0.005 0.0\n0.015 1.0\n')
    return parameterization.save(candidate, revision or REVISION, work=work)


def bead_pairs(candidate):
    """One reference file name per bead pair, in the tool's own convention.

    `ff_assess` scores every unordered pair of a molecule's atoms and asks for
    `f'{resid1}_{name1}_{resid2}_{name2}_distances_distr.dat'` (`fast_forward/score.py`), so a scorable revision holds
    `n(n-1)/2` of them. The names are spelled here rather than derived from the module under test, so a fixture that
    drifted from the tool's rule fails these tests instead of agreeing with itself; `test_cg_reference_distributions.py`
    pins what the tool actually writes.
    """
    names = [bead['name'] for bead in candidate['beads']]
    return [f'1_{first}_1_{second}_distances_distr.dat'
            for index, first in enumerate(names) for second in names[index + 1:]]


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
    """D5's first honest state. Stage 3 runs a different repository script, and the stage it replaces is not there
    for a reader to mistake for what ran -- not even as a copy inside the run."""
    candidate = ddm_mapping()
    fitted(candidate)
    run = prepared(tmp_path, monkeypatch, mapping_candidate=candidate)

    assert not (run / '3_initial_CG/use_parameterization.sh').exists()
    assert not (run / '3_initial_CG/fit_topology.sh').exists(), 'a stage named for fitting must not sit there'
    scripts = {stage.name: stage.script for stage in cg.stage_definitions(parameterized=True)}
    assert scripts['CG parameterization'] == 'dashboard/execution/scripts/use_parameterization.sh'
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
    assert 'fitted nothing' in limitations
    assert 'carries 1 pairwise distance histograms' in limitations, \
        'the run says how much of a baseline came with the model rather than claiming it has none'
    assert 'revision 1' in limitations


def test_a_model_with_no_parameterization_is_fitted_by_the_run_and_the_run_records_that(tmp_path, monkeypatch):
    """D5's second honest state: the whole old behaviour, and a manifest that says it happened."""
    run = prepared(tmp_path, monkeypatch, mapping_candidate=another_mapping())
    record = manifest(run)['bonded']

    assert not (run / '3_initial_CG/fit_topology.sh').exists()
    assert not (run / '3_initial_CG/use_parameterization.sh').exists()
    assert not (run / '3_initial_CG/parameterization.json').exists()
    assert {stage.name: stage.script for stage in cg.stage_definitions()}['CG parameterization'] == \
        'dashboard/execution/scripts/fit_topology.sh'
    assert record['consumes_parameterization'] is False and record['fitted'] is True
    assert record['revision'] is None and record['engine'] is None
    assert record['reference_pairs'] is None, 'nothing was staged: stage 3 measures the reference while it fits'
    assert record['source'] == 'fitted by this run, in stage 3, from the AA reference it consumes'
    # The fit's temperature is the run's own setting, handed to the repository script as environment: nothing is
    # stamped into a copy, and the same file fits every run.
    script = (PROJECT_ROOT / 'dashboard/execution/scripts/fit_topology.sh').read_text()
    assert 'RUN_SETTING_TEMPERATURE_K:-300' in script
    assert '-temperature "$FIT_TEMPERATURE"' in script


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

    assert '"$PYTHON" -m dashboard.execution.scripts.use_parameterization' in executable
    assert '"$PYTHON" -m dashboard.execution.scripts.prepare_ring_constraints' in executable
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
    assert [entry['name'] for entry in recorded['files']] == ['1_B01_1_B02_distances_distr.dat',
                                                              'B01_B02_B05_angles_distr.dat',
                                                              'B01_B11_bonds_distr.dat'], \
        'the distance histograms too: `ff_assess` skips a pair with no baseline and scores it 0.00, which reads perfect'
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


def test_the_consuming_run_names_the_baseline_in_place_and_the_assessment_reads_it(tmp_path, monkeypatch):
    """`ff_assess` reads `<group>_<type>_distr.dat` from its `-d` directory and never computes them.

    The run no longer copies the revision's histograms into stage 3 or links them into stage 5: the store's revision
    directory is immutable and already hashed, so the run names each file there by absolute path and digest and writes
    that directory into `5_assessment/references.txt` -- the data `assess.sh` reads when nothing hands it `REFERENCES`.
    Nothing of the baseline is staged, so a reader sees the store's own files rather than a second copy that could
    drift from it.
    """
    candidate = ddm_mapping()
    fitted(candidate)
    run = prepared(tmp_path, monkeypatch, mapping_candidate=candidate)

    staged = run / '3_initial_CG'
    inventory = json.loads((staged / 'distributions.json').read_text())
    names = [Path(entry['name']).name for entry in inventory['files']]
    assert names == ['1_B01_1_B02_distances_distr.dat',
                     'B01_B02_B05_angles_distr.dat',
                     'B01_B11_bonds_distr.dat']
    for entry in inventory['files']:
        path = Path(entry['name'])
        assert path.is_absolute() and path.is_file(), 'the inventory names the store file, not a copy'
        assert parameterizations_digest(path) == entry['sha256']
    assert not list(staged.glob('*_distr.dat')), 'no histogram is copied into stage 3'
    assert manifest(run)['bonded']['reference_distributions'] == names
    assert manifest(run)['bonded']['assessment'] == {'scored': True, 'reason': None}

    # Stage 5 is pointed at those files by `references.txt` and runs the repository's own script.
    stage = run / '5_assessment'
    declared = Path((stage / 'references.txt').read_text().strip())
    assert declared.resolve() == Path(inventory['files'][0]['name']).parent.resolve()
    done = run_stage(stage)
    assert done.returncode != 4, 'a run with the pair family is not a run with nothing to score'
    assert not (stage / 'skip.json').exists()
    assert not (stage / 'references').exists(), 'nothing is linked into the run: the store is read where it lives'


def test_the_run_records_how_many_pair_histograms_it_can_score_with(tmp_path, monkeypatch):
    """The score matrix is built from one `<resid>_<a>_<resid>_<b>_distances_distr.dat` per bead pair, so the run
    counts that family rather than listing 68 names and hoping: a reader can see 55 of 55 before the simulation runs."""
    candidate = ddm_mapping()
    pairs = bead_pairs(candidate)
    bonded = ('B01_B11_bonds_distr.dat', 'B01_B02_B05_angles_distr.dat')
    assert len(pairs) == 55, 'eleven beads make fifty-five pairs, which is what `ff_assess` scores'
    fitted(candidate, files=(*bonded, *pairs))
    run = prepared(tmp_path, monkeypatch, mapping_candidate=candidate)

    staged = run / '3_initial_CG'
    inventory = json.loads((staged / 'distributions.json').read_text())
    assert inventory['pairs'] == {'files': 55, 'expected': 55}
    assert inventory['interactions'] == {'files': 2}
    assert inventory['reason'] is None
    named = {Path(entry['name']).name for entry in inventory['files']}
    assert set(pairs) <= named, 'every pair histogram is named by the inventory, where `-d` is handed them'
    assert all(Path(entry['name']).is_file() for entry in inventory['files'])
    assert not list(staged.glob('*_distr.dat')), 'and none of them is a copy inside the run'
    record = manifest(run)['bonded']
    assert record['reference_pairs'] == {'files': 55, 'expected': 55}
    assert record['assessment'] == {'scored': True, 'reason': None}


def test_a_revision_without_the_pair_histograms_is_not_scored_and_says_why(tmp_path, monkeypatch):
    """The quiet half of the defect: a revision holding bonds and angles but no pairwise family.

    `ff_assess` skips every pair whose reference file is missing and leaves the cell at 0.00, so such a run printed an
    all-zero matrix under `Overall Score : 0.0` -- a perfect score for a comparison that never happened (run
    `ce1318485197`, whose revision predates the pair family being recorded). It is now not scored at all, and the run's
    own stage 5 records `skipped` with the reason rather than a number it did not measure.
    """
    candidate = ddm_mapping()
    fitted(candidate, files=('B01_B11_bonds_distr.dat', 'B01_B02_B05_angles_distr.dat'))
    run = prepared(tmp_path, monkeypatch, mapping_candidate=candidate)

    inventory = json.loads((run / '3_initial_CG/distributions.json').read_text())
    assert inventory['pairs'] == {'files': 0, 'expected': 55}
    assert 'none of the pairwise distance histograms' in inventory['reason']
    assert '0.00' in inventory['reason'] and 'identical' in inventory['reason'], \
        'it names the failure it prevents: an unbaselined cell scores 0.00, which reads identical'
    record = manifest(run)['bonded']
    assert record['assessment'] == {'scored': False, 'reason': inventory['reason']}
    assert 'no pairwise distance histograms' in ' '.join(manifest(run)['limitations'])

    # The prepared run's own stage 5, in the layout the run has: `skipped`, with the inventory's sentence.
    stage = run / '5_assessment'
    done = run_stage(stage)
    assert done.returncode == 4, done.stdout + done.stderr
    assert json.loads((stage / 'skip.json').read_text()) == {'reason': inventory['reason']}
    assert not (stage / 'report_distances.out').exists(), 'no matrix was printed at all'


def test_the_prepared_stage_five_goes_on_when_the_revision_brought_the_pair_histograms(tmp_path, monkeypatch):
    """The other half: with the family staged, the guard does not fire and `ff_assess` is what runs."""
    candidate = ddm_mapping()
    fitted(candidate, files=(*bead_pairs(candidate), 'B01_B11_bonds_distr.dat'))
    run = prepared(tmp_path, monkeypatch, mapping_candidate=candidate)

    stage = run / '5_assessment'
    done = run_stage(stage)

    assert done.returncode != 4 and not (stage / 'skip.json').exists()


def test_a_bartender_model_runs_and_its_assessment_records_that_it_had_nothing_to_score(tmp_path, monkeypatch):
    """D6a: BARTENDER's analysis is its own and is unbuilt, which postpones scoring -- not the run.

    Refusing the run would throw away a simulation that still has evidence in it. So prepare stages what the model
    brought (nothing), writes the reason into the inventory, and stage 5 records `skipped` with those words: a stage that
    had nothing to do, said so, and was not confused with one that scored nothing.
    """
    candidate = ddm_mapping()
    bartender = {**REVISION, 'engine': 'bartender'}
    parameterization.save(candidate, bartender)
    run = prepared(tmp_path, monkeypatch, mapping_candidate=candidate)

    inventory = json.loads((run / '3_initial_CG/distributions.json').read_text())
    assert inventory['files'] == []
    assert 'BARTENDER measured no reference histograms' in inventory['reason']
    assert 'D6a' in inventory['reason'] and 'nothing to score' in inventory['reason']
    record = manifest(run)['bonded']
    assert record['consumes_parameterization'] is True and record['engine'] == 'bartender'
    assert record['reference_distributions'] == []
    assert record['reference_pairs'] == {'files': 0, 'expected': 55}, 'nothing staged, and the count says so'
    assert record['assessment'] == {'scored': False, 'reason': inventory['reason']}
    # The consuming stage still records what it consumed, and that it consumed no baseline.
    assert not (run / '3_initial_CG/DDM_ff_inter.itp').exists(), 'nothing is fitted or staged by prepare itself'


def test_a_revision_that_predates_recorded_baselines_also_runs_and_says_so(tmp_path, monkeypatch):
    """The other way to have no baseline: a fast-forward revision from before they were recorded. Same answer -- the
    run happens, the assessment records why it could not score, and the reason names the remedy."""
    candidate = ddm_mapping()
    parameterization.save(candidate, REVISION)
    run = prepared(tmp_path, monkeypatch, mapping_candidate=candidate)

    inventory = json.loads((run / '3_initial_CG/distributions.json').read_text())
    assert inventory['files'] == []
    assert 'predates them being recorded' in inventory['reason']
    assert 're-fit' in inventory['reason']
    assert manifest(run)['bonded']['assessment']['scored'] is False


def assessment_stage(tmp_path, inventory=None, histograms=()):
    """Stage 5 as `prepare` lays it out: the reference data in `3_initial_CG/`, and `references.txt` naming it.

    The layout is the point. The reference histograms live in stage 3 -- the directory `ff_assess -d` is handed -- and
    so does the inventory that lists them; `references.txt` is the data file the run writes so the shared script can be
    the same file for a run that fits and one that consumes a model. A test that put the inventory beside the script
    would pass while a real run never found it, which is how the skip path this stage documents was unreachable.
    """
    stage = tmp_path / '5_assessment'
    stage.mkdir(parents=True)
    (stage / 'references.txt').write_text('../3_initial_CG\n')
    reference = stage.parent / '3_initial_CG'
    reference.mkdir(exist_ok=True)
    for name in histograms:
        (reference / name).write_text('0.005 0.0\n')
    if inventory is not None:
        (reference / 'distributions.json').write_text(json.dumps(inventory))
    return stage


def run_stage(stage):
    """Run the stage the way the executor does: the repository script, in the stage directory, with its own modules.

    There is no run-local script to pick: `assess.sh` is the repository file recorded in the manifest, and its helpers
    are package modules reached through `PYTHONPATH`.
    """
    return subprocess.run(['bash', str(PROJECT_ROOT / 'dashboard/execution/scripts/assess.sh')],
                          cwd=stage, capture_output=True, text=True,
                          env={'PATH': f'{Path(sys.executable).parent}:/usr/bin:/bin',
                               'PYTHON': sys.executable, 'PYTHONPATH': str(PROJECT_ROOT)})


def test_the_assessment_stage_skips_and_says_why_when_the_inventory_is_empty(tmp_path):
    """The stage's own half of the contract: exit 4 with `skip.json` beside it, so the run records `skipped`."""
    stage = assessment_stage(tmp_path, {'directory': '.', 'files': [], 'pairs': {'files': 0, 'expected': 55},
                                        'reason': 'BARTENDER measured no reference histograms'})

    done = run_stage(stage)

    assert done.returncode == 4, done.stdout + done.stderr
    assert json.loads((stage / 'skip.json').read_text()) == {
        'reason': 'BARTENDER measured no reference histograms'}
    assert not (stage / 'report_interactions.out').exists(), 'it did not score anything'


def test_the_assessment_stage_does_not_skip_a_run_that_brought_no_inventory(tmp_path):
    """A run that fits has no inventory and does not need one: its own fit left the histograms in stage 3. So a missing
    inventory is not an empty one, and the stage goes on to the tool rather than claiming it had nothing to do."""
    stage = assessment_stage(tmp_path, histograms=('1_B01_1_B02_distances_distr.dat',))

    done = run_stage(stage)

    assert done.returncode != 4, 'a stage with no inventory is not a stage with nothing to do'
    assert not (stage / 'skip.json').exists()


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
    (stage / 'distributions.json').write_text(json.dumps({**record, 'pairs': {'files': 1, 'expected': 55}}))

    subprocess.run([sys.executable, str(script)], cwd=stage, check=True,
                   env={'PATH': '/usr/bin', 'FINAL_ITP': 'DDM.itp'})
    written = json.loads((stage / 'parameterization_used.json').read_text())
    assert written['reference_distributions'] == record['files']
    assert written['reference_pairs'] == {'files': 1, 'expected': 55}

    (stage / 'B01_B11_bonds_distr.dat').write_text('0.005 9.9\n')
    result = subprocess.run([sys.executable, str(script)], cwd=stage, env={'PATH': '/usr/bin', 'FINAL_ITP': 'DDM.itp'},
                            capture_output=True, text=True)
    assert result.returncode != 0 and 'does not match the digest' in result.stderr

