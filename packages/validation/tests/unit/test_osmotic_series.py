"""The osmotic series is the run type: one run owns N concentrations, one directory each.

The shape this file pins, and why it is the one that works here:

* **One run, N concentrations.** A series used to be N ``osmotic`` jobs queued together, which
  ``max_concurrent_runs: 1`` turns into a *one-condition* series -- the second ``create_job`` is refused
  ``CapacityFull`` and nothing starts a queued job. The run type owns the concentrations instead, so a series
  costs one worker slot, and its stage plan is the concentrations in the order the caller gave them.
* **One directory per concentration, each with its own checkpoint.** Each condition has its own ``solute/``,
  its own mdps, its own ``attempts.json`` and its own ``min/eq/md.{cpt,gro,tpr,xtc}``. That is what lets a
  condition that died mid-production continue from ``<stage>.cpt`` (the runner's ``gmx mdrun -cpi``) while the
  conditions that already finished are not run again.

Both are facts about the *build*, so they are asserted on what ``prepare`` writes rather than on the dataclass.

``molecules/Maltose`` and ``molecules/DDM`` are copied into a fixture root rather than read from the repository:
a test that reads the developer's tree reports nothing about the code when the tree moves.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from detergent_validation.execution.adapters import osmotic

from tests.harness.support import PROJECT_ROOT

MAPPING = {'beads': [{'name': 'S1A', 'type': 'SP1r', 'atoms': [1, 2, 3]},
                     {'name': 'S1B', 'type': 'SP4r', 'atoms': [4, 5, 6]},
                     {'name': 'S1C', 'type': 'SP1r', 'atoms': [7, 8, 9]},
                     {'name': 'VS1', 'type': 'TC4', 'atoms': []}]}

REPOSITORY = PROJECT_ROOT


def molecule_root(tmp_path, *names):
    """A fixture molecule root holding copies of the packaged sugars (and, by default, DDM as the non-sugar)."""
    root = tmp_path / 'molecules'
    root.mkdir(exist_ok=True)
    for name in names or ('Maltose', 'DDM'):
        shutil.copytree(REPOSITORY / 'molecules' / name, root / name)
    return root


def solute_root(tmp_path):
    root = tmp_path / 'solute'
    root.mkdir(exist_ok=True)
    for name in osmotic.SOLUTE_FILES:
        (root / name).write_text('placeholder\n')
    return root


def metadata(tmp_path, *, molalities=None, molecule_id='Maltose', **extra):
    settings = {}
    if molalities is not None:
        settings['molalities'] = molalities
    return dict({'molecule_id': molecule_id, 'solute_root': str(solute_root(tmp_path)),
                 'mapping_snapshot': MAPPING, 'molecule_root': molecule_root(tmp_path), 'settings': settings},
                **extra)


# --- the settings: N concentrations, each bounded where the box can place it -----------------------------------

def test_the_series_carries_its_concentrations_in_order_and_each_gets_its_own_directory():
    """The run type's own vocabulary: a list of molalities, and the directory each one is built in."""
    settings = osmotic.normalize_settings({'molalities': [0.5, 1.0, 2.5]})

    assert settings['molalities'] == [0.5, 1.0, 2.5]
    assert [condition['directory'] for condition in osmotic.conditions_of(settings)] == \
           ['00_0.5molal', '01_1molal', '02_2.5molal']
    assert [condition['molality'] for condition in osmotic.conditions_of(settings)] == [0.5, 1.0, 2.5]


def test_a_lone_molality_in_the_series_list_is_a_one_condition_series():
    """A series of one is still a series: ONE run that owns the one concentration, not a special case."""
    assert osmotic.normalize_settings({'molalities': [0.5]})['molalities'] == [0.5]


def test_the_run_type_publishes_no_single_molality_setting():
    """The old shape's own field is gone, which is what makes the reader's marker one-sided.

    `osmotic_molality` is the setting every sibling job of the old series carried. It is no longer part of this run
    type's vocabulary at all, so a record that carries it cannot have been built by this run type -- and a record
    this run type builds always carries `molalities` instead.
    """
    assert 'osmotic_molality' not in osmotic.SETTING_SPECS
    assert 'osmotic_molality' not in osmotic.DEFAULTS
    assert 'osmotic_molality' not in osmotic.stage_defaults()['values']


def test_a_payload_that_names_no_concentrations_is_refused_with_the_new_shape():
    """The one thing this run type accepts: one run owning N concentrations.

    Every payload below is the shape the hand-queued one-condition runs had -- a single molality, no series -- and
    each is refused with a reason that names what to send instead. There is no default: completing a single
    concentration here is exactly what made a condition look like a series.
    """
    for settings in ({}, {'osmotic_molality': 0.5}, {'molalities': []}, {'molalities': ''}):
        with pytest.raises(ValueError) as refused:
            osmotic.normalize_settings(settings)
        assert 'molalities' in str(refused.value), settings
        assert 'one run owning' in str(refused.value), settings


def test_the_refusal_names_both_shapes_so_a_caller_knows_what_to_send():
    """A refusal that names only the old shape is a no; this one says what to send instead."""
    reason = osmotic.series_shape_reason()

    assert 'molalities' in reason and 'one run owning' in reason
    assert 'sibling' in reason, 'the old shape is named too'
    assert osmotic.refuse_legacy_shape({'molalities': [0.5]}) is None
    assert osmotic.refuse_legacy_shape({}) is not None


def test_a_reader_tells_an_old_record_from_a_series_by_its_settings():
    """The marker, one-sided: only a series carries `molalities`, and only an old record carries the scalar.

    `series_of` is the reader -- the concentrations for a series, `None` for a record that predates the shape -- so
    the two shapes are not left looking identical in the store.
    """
    new = osmotic.normalize_settings({'molalities': [0.5, 1.0]})
    old = {'osmotic_molality': 0.5, 'series_id': '108c31827410'}

    assert 'molalities' not in old and 'osmotic_molality' not in new
    assert [condition['molality'] for condition in osmotic.series_of(new)] == [0.5, 1.0]
    assert osmotic.series_of(old) is None


def test_the_shared_admission_refuses_an_osmotic_payload_that_names_no_series():
    """The coordinator's front door holds the same rule, so a payload that skips the series route is refused too."""
    from dashboard.execution.coordination import admission

    with pytest.raises(ValueError, match='molalities'):
        admission.validate_run_type({'run_type': 'osmotic', 'settings': {'solute_root': '/tmp/solute'}})
    with pytest.raises(ValueError, match='molalities'):
        admission.validate_run_type({'run_type': 'osmotic', 'solute_root': '/tmp/solute', 'osmotic_molality': 1.0})
    # The new shape is admitted, and the run type's other rule -- the solute it is built from -- still holds.
    admission.validate_run_type({'run_type': 'osmotic',
                                 'settings': {'solute_root': '/tmp/solute', 'molalities': [0.5, 1.0]}})


def test_a_molality_the_box_cannot_place_is_refused_and_the_bound_is_named():
    """`osmic_box.MOLALITY_RANGE` is the bound, and the refusal names the value that broke it."""
    with pytest.raises(ValueError, match='between 0.0 and 2.5'):
        osmotic.normalize_settings({'molalities': [0.5, 9.0]})
    with pytest.raises(ValueError, match='between 0.0 and 2.5'):
        osmotic.normalize_settings({'molalities': [-0.5]})


def test_a_repeated_molality_is_refused_because_it_would_be_one_directory_twice():
    """Two conditions at one molality would be one directory and one measurement reported twice."""
    with pytest.raises(ValueError, match='twice'):
        osmotic.normalize_settings({'molalities': [1.0, 1.0]})
    with pytest.raises(ValueError, match='must be numeric'):
        osmotic.normalize_settings({'molalities': ['a lot']})


# --- the sugar gate -------------------------------------------------------------------------------------------

def test_a_sugar_is_accepted_and_a_detergent_with_a_sugar_head_group_is_not(tmp_path):
    """The gate is the repository's own two facts: the registry's names, and the recogniser on the structure.

    DDM is the case that makes the first half insufficient and a naive ring test wrong: it *has* two
    hexopyranose rings -- it is a glucoside -- so "has a recognised ring" admits it. What it is not is a sugar:
    twelve heavy atoms of alkyl chain sit outside those rings.
    """
    root = molecule_root(tmp_path, 'Maltose', 'DDM')

    assert osmotic.refuse_non_sugar('Maltose', molecule_root=root) is None

    refused = osmotic.refuse_non_sugar('DDM', molecule_root=root)
    assert refused and 'not a carbohydrate' in refused
    assert '12' in refused and 'outside' in refused, refused


def test_a_name_the_repository_does_not_carry_is_refused_with_the_two_places_that_were_checked(tmp_path):
    """Refuse with a reason rather than a bare no: the reason says what was looked at and what was missing."""
    refused = osmotic.refuse_non_sugar('Glucosex', molecule_root=molecule_root(tmp_path, 'Maltose'))

    assert refused and 'not a carbohydrate' in refused
    assert 'molecules/' in refused and 'targets-v1.json' in refused, refused


def test_a_carbohydrate_the_registry_names_is_a_sugar_even_with_no_molecule_folder(tmp_path):
    """Glucose has a measured target and no folder. It is a sugar the catalogue cannot *build* -- a different
    answer from "not a sugar", and one this gate must not collapse into the other."""
    context = osmotic.carbohydrate_names()
    assert 'Glucose' in context and 'Maltose' in context

    assert osmotic.refuse_non_sugar('Glucose', molecule_root=molecule_root(tmp_path, 'Maltose')) is None


def test_readiness_names_a_non_sugar_as_the_blocker(tmp_path):
    """The gate reaches the coordinator's own path, where a payload can arrive without the route."""
    blocked = osmotic.readiness({'molecule_id': 'DDM', 'solute_root': str(solute_root(tmp_path)),
                                 'molecule_root': molecule_root(tmp_path, 'Maltose', 'DDM'),
                                 'settings': {'molalities': [1.0]}})

    assert blocked['ready'] is False
    assert any('not a carbohydrate' in blocker for blocker in blocked['blockers']), blocked['blockers']


def test_prepare_refuses_a_non_sugar_rather_than_building_it(tmp_path):
    with pytest.raises(ValueError, match='not a carbohydrate'):
        osmotic.prepare(tmp_path, metadata(tmp_path, molalities=[1.0], molecule_id='DDM'))


# --- the build: one directory per concentration ---------------------------------------------------------------

@pytest.mark.slow
def test_prepare_writes_one_directory_per_concentration_each_able_to_carry_its_own_checkpoint(tmp_path):
    """The substance of "checkpoints for each concentration": every condition owns its own files on disk.

    A condition that dies in production has ``md.cpt`` beside it, in its own directory, and its own
    ``attempts.json`` -- so the next entry into the series continues *it* and leaves the finished ones alone.
    """
    record = osmotic.prepare(tmp_path, metadata(tmp_path, molalities=[0.5, 1.5]))

    assert [condition['molality_achieved'] for condition in record['conditions']] == \
           pytest.approx([0.5, 1.5], rel=0.01)

    stage = tmp_path / 'stages' / '01_simulate'
    for directory in ('00_0.5molal', '01_1.5molal'):
        condition = stage / 'conditions' / directory
        for name in ('minimization.mdp', 'eq.mdp', 'md.mdp', 'reference.itp', 'osmotic_condition.json'):
            assert (condition / name).is_file(), name
        # The molecule is referenced, never copied into the run: its absolute path is in the condition's own record,
        # and there is no `solute/` directory or force-field copy beside it for the runner to read instead.
        assert not (condition / 'solute').exists()
        assert not (condition / 'martini_v3.0.0.itp').exists()
        written = json.loads((condition / 'osmotic_condition.json').read_text())
        assert written['molality_requested'] == pytest.approx({'00_0.5molal': 0.5, '01_1.5molal': 1.5}[directory])
        # Each referenced file's absolute path is written down, so the driver reads what the manifest hashed.
        for name in osmotic.SOLUTE_FILES:
            assert Path(written['paths'][name]).is_absolute()
            assert Path(written['paths'][name]).is_file(), name
        assert Path(written['paths']['force_field']).is_file()
        # And the run's generated data lives in `inputs/`, where the manifest record is written from.
        for name in osmotic.CONDITION_FILES:
            assert (tmp_path / 'inputs' / 'conditions' / directory / name).is_file(), name

    manifest = json.loads((stage / 'conditions.json').read_text())
    assert [condition['directory'] for condition in manifest['conditions']] == ['00_0.5molal', '01_1.5molal']
    assert manifest['attempts_max'] == osmotic.DEFAULTS['osmotic_attempts_max']
    assert manifest['series_on_failure'] == 'carry_on'
    assert manifest['molecule_id'] == 'Maltose'
    # The executor checks the stage's declared inputs before it runs the stage, and every one of them is a glob
    # over the conditions the build wrote. Nothing else would catch a declaration that names one directory.
    for declared in osmotic.STAGE_DEFS[0].inputs:
        assert list(stage.glob(declared)), declared


def test_the_stage_declares_the_outputs_the_runner_writes_per_condition(tmp_path):
    """An output pattern that names one condition would read a complete series as an incomplete stage."""
    outputs = osmotic.STAGE_DEFS[0].outputs

    assert set(outputs) == {'conditions/*/built.json', 'conditions/*/system.top',
                            'conditions/*/prod/md_whole.xtc'}
    assert [name for name, _ in osmotic.STAGES] == ['Osmotic series']


def test_the_checkpoint_ceiling_travels_in_the_series_record_not_a_stamped_script(tmp_path):
    """The runner is a repository script now, so a per-run ceiling travels as data, not as a rewritten file."""
    osmotic.prepare(tmp_path, metadata(tmp_path, molalities=[1.0],
                                       settings={'molalities': [1.0], 'osmotic_attempts_max': 5}))

    stage = tmp_path / 'stages' / '01_simulate'
    series = json.loads((stage / 'conditions.json').read_text())
    assert series['attempts_max'] == 5
    assert not (stage / 'run.sh').exists(), 'the driver is the repository script, not a copy in the run'
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    assert manifest['stage_scripts']['Osmotic series']['path'] == osmotic.OSMOTIC_SCRIPT


def test_the_series_policy_travels_into_the_run_the_runner_reads(tmp_path):
    """The two choices have to reach the process that can enforce them: one driver loop, one policy file."""
    osmotic.prepare(tmp_path, metadata(tmp_path, molalities=[0.5, 1.0],
                                       settings={'molalities': [0.5, 1.0], 'series_on_failure': 'stop'}))

    manifest = json.loads((tmp_path / 'stages' / '01_simulate' / 'conditions.json').read_text())
    assert manifest['series_on_failure'] == 'stop'
    # The runner reads the policy from that file by name, so the name is part of the contract.
    assert osmotic.CONDITIONS_MANIFEST == 'conditions.json'


# --- the declaration: what the driver is GIVEN, not what it works in ------------------------------------------

def test_the_stage_declares_the_given_files_as_inputs_and_the_conditions_as_outputs():
    """A stage's inputs are what it must be given, not what it happens to look at.

    The conditions are the driver's own OUTPUT -- it works in them, and their trajectories are written where it
    stands. So the declaration names the pristine `../inputs/` copies as inputs -- the series manifest, the mdps,
    the reference bead and the solute files, kilobytes in all -- and the conditions as outputs. Nothing under the
    stage's own `conditions/` directory is declared as an input, which is what keeps the declared set the settings,
    the solute files and the mdps rather than the trajectories they produce.

    **The executor's half is proved below.** The declaration is only half the invariant: the executor used to record
    a stage's inputs by hashing the stage *directory* (`workflow.py`: `entry['inputs_sha256'] = files.hashes(...)`),
    so an in-place resume re-hashed whatever the conditions held, declared here or not. It records the declared inputs
    now, and `test_entering_and_resuming_a_series_reads_its_declaration_and_not_its_own_output` pins that half.
    """
    inputs = osmotic.STAGE_DEFS[0].inputs
    outputs = osmotic.STAGE_DEFS[0].outputs

    assert inputs and all(pattern.startswith('../../inputs/') for pattern in inputs), inputs
    assert not [pattern for pattern in inputs if pattern.startswith('conditions/')], inputs
    assert outputs and all(pattern.startswith('conditions/') for pattern in outputs), outputs
    assert 'conditions/*/prod/md_whole.xtc' in outputs, 'the trajectory is the producer\'s output, not its input'


def test_a_zero_molality_condition_is_still_the_control(tmp_path):
    """The control is a row in the series and is stated as one, exactly as it was when it was its own run."""
    osmotic.prepare(tmp_path, metadata(tmp_path, molalities=[0.0, 1.0]))

    control = tmp_path / 'inputs' / 'conditions' / '00_0molal' / 'control.json'
    assert 'zero by construction' in control.read_text()


# --- the resume, at the coordinator's own seam ------------------------------------------------------------------

def test_resuming_the_run_keeps_every_conditions_checkpoint_on_disk(tmp_path):
    """What a series resume has to preserve, asserted where the coordinator would destroy it.

    A run whose stage ended failed is resumed through `workflow.prepare_resume_in_place`: it drops the failed
    stage from the manifest and re-enters it **in the same directory**. Everything that makes that a resume
    rather than a restart is therefore in that directory -- each condition's `md.cpt` and its own terminal record
    -- and a resume preparation that cleared or moved the stage would silently turn the run back into one that
    repeats five conditions' work.
    """
    from dashboard.execution import workflow

    osmotic.prepare(tmp_path, metadata(tmp_path, molalities=[0.5, 1.0]))
    condition = tmp_path / 'stages' / '01_simulate' / 'conditions' / '00_0.5molal'
    # What a condition that died mid-production leaves behind.
    (condition / 'md.cpt').write_text('the checkpoint the failure wrote')
    (condition / 'condition.json').write_text(json.dumps({'directory': '00_0.5molal', 'status': 'failed'}))
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    manifest.update(status='failed', stages=[{'name': 'Osmotic series', 'status': 'failed',
                                              'error': 'gmx mdrun failed'}])
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))

    assert workflow.resumable_stages(tmp_path) == ['Osmotic series']
    resumed = workflow.prepare_resume_in_place(tmp_path, 'Osmotic series')

    assert resumed['status'] == 'queued' and resumed['resume_in_place'] is True
    assert resumed['stages'] == [], 'the failed stage is entered again, not skipped'
    assert (condition / 'md.cpt').read_text() == 'the checkpoint the failure wrote'
    assert json.loads((condition / 'condition.json').read_text())['status'] == 'failed'
    assert (tmp_path / 'stages' / '01_simulate' / 'conditions' / '01_1molal').is_dir(), 'the series is untouched'


# --- the executor's half: the record follows the declaration, not the stage directory ----------------------------

CONDITIONS = ('00_0.5molal', '01_1.0molal')
#: What one condition's own trajectory holds. The project's own series measured 57 files / 1,830.6 MB against a
#: declared 19 files / ~14 KB; the *shape* is the finding, so a few megabytes stand in for the gigabytes and the
#: assertion is on the ratio -- kilobytes read against megabytes present -- rather than on the absolute total.
CONDITION_BYTES = 4 * 1024 * 1024


def series_run(root):
    """A one-stage series laid out the way `prepare` writes one: the generated data in `inputs/`, the work in the stage.

    The stage stands at `stages/01_simulate`, so a declared `../../inputs/...` pattern resolves to the run's `inputs/`
    tree. Everything one condition *produces* (its trajectory, its built system) is written inside the stage
    directory, which is exactly why its contents are the wrong thing to hash. The driver is a repository script named
    in the manifest's `stage_scripts`, so the run holds no launcher of its own.
    """
    from dashboard import files
    from dashboard.execution import run_scripts

    inputs, stage = root / 'inputs', root / 'stages' / '01_simulate'
    (root / 'logs').mkdir(parents=True, exist_ok=True)
    stage.mkdir(parents=True)
    script = run_scripts.code_path(osmotic.OSMOTIC_SCRIPT, root=REPOSITORY)
    (root / 'manifest.json').write_text(json.dumps({
        'run_type': 'osmotic', 'layout_version': 3, 'stages': [],
        'stage_scripts': {'Osmotic series': {'path': osmotic.OSMOTIC_SCRIPT,
                                             'sha256': files.sha256(script)}}}))
    (inputs / 'conditions').mkdir(parents=True)
    (inputs / 'conditions.json').write_text('{}')
    for condition in CONDITIONS:
        given = inputs / 'conditions' / condition
        given.mkdir()
        for name in osmotic.CONDITION_FILES:
            (given / name).write_text('kilobytes\n')
        work = stage / 'conditions' / condition
        (work / 'prod').mkdir(parents=True)
        (work / 'prod' / 'md_whole.xtc').write_bytes(b'x' * CONDITION_BYTES)
        (work / 'built.json').write_text('{}')
        (work / 'system.top').write_text('{}')
        (work / 'martini_v3.0.0.itp').write_bytes(b'x' * CONDITION_BYTES)
    return stage


@pytest.mark.slow
def test_entering_and_resuming_a_series_reads_the_run_record_and_not_its_own_output(tmp_path, monkeypatch):
    """The executor's half of the invariant: the entry records what the stage is *given*.

    The stage directory is where the series works, so it holds each condition's trajectory and its built system.
    Recording the entry by hashing that directory -- which an in-place resume re-enters and does again every time --
    reads the run's own output back to write its own provenance. The declared inputs are the run's `inputs/` record,
    one level above `stages/`, and the executor records only stage-root-relative files (the pdc convention), so the
    stage's entry carries no generated output: what the stage was given is the manifest's `inputs` record.
    """
    from dashboard import files
    from dashboard.execution import workflow

    stage = series_run(tmp_path)
    monkeypatch.setattr(
        workflow, 'stage_definitions',
        lambda metadata: (osmotic.STAGES, osmotic.REQUIRED_INPUTS, osmotic.REQUIRED_OUTPUTS))

    def execute(command, **kwargs): return subprocess.CompletedProcess(command, 0)

    workflow.run(tmp_path, tmp_path / 'logs' / 'console.log', execute=execute)
    # Enter it again the way an in-place resume does: the stage is dropped from the manifest and re-entered in place.
    workflow.prepare_resume_in_place(tmp_path, 'Osmotic series')

    counted, read, at_command = {'bytes': 0}, [], {}
    real_sha256 = files.sha256

    def counting_sha256(path):
        counted['bytes'] += Path(path).stat().st_size
        read.append(Path(path))
        return real_sha256(path)

    def measure(command, **kwargs):
        # Everything the entry read, by the time the stage's own command is about to run -- and nothing the run does
        # afterwards, which is where the declared outputs are hashed.
        at_command.update(bytes=counted['bytes'], paths=list(read))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(files, 'sha256', counting_sha256)
    workflow.run(tmp_path, tmp_path / 'logs' / 'console.log', execute=measure)

    entry = json.loads((tmp_path / 'manifest.json').read_text())['stages'][0]
    assert entry['status'] == 'completed'
    assert entry['inputs'] == list(osmotic.STAGE_DEFS[0].inputs), 'the entry names the declaration it was given'
    # Nothing under the stage is a declared input, so the entry records no staged bytes at all. The run's own
    # provenance is the manifest's `inputs` record, written from `inputs/` at prepare time.
    assert entry['inputs_sha256'] == {}
    present = sum(path.stat().st_size for path in stage.rglob('*') if path.is_file())
    assert present > 8 * 1024 * 1024, 'the fixture stands in for a stage directory holding gigabytes'
    # The repository script is what the executor verified and ran; it is the only thing it reads. A 256 KB ceiling
    # still catches the multi-megabyte output this fixture writes while leaving room for the driver's own digest.
    assert at_command['bytes'] < 256 * 1024, (
        f'the entry read {at_command["bytes"]} bytes of the stage directory\'s {present}: a resume re-hashes its own output')
    assert not [path for path in at_command['paths'] if path.suffix == '.xtc'], \
        'the entry re-hashed the condition trajectories'
    assert not [path for path in at_command['paths'] if path.name == 'martini_v3.0.0.itp'], \
        'the entry re-hashed the per-condition force-field copies'
