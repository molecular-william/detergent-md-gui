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
from pathlib import Path

import pytest

from dashboard.execution.adapters import osmotic

MAPPING = {'beads': [{'name': 'S1A', 'type': 'SP1r', 'atoms': [1, 2, 3]},
                     {'name': 'S1B', 'type': 'SP4r', 'atoms': [4, 5, 6]},
                     {'name': 'S1C', 'type': 'SP1r', 'atoms': [7, 8, 9]},
                     {'name': 'VS1', 'type': 'TC4', 'atoms': []}]}

REPOSITORY = Path(osmotic.__file__).resolve().parents[3]


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


def test_a_lone_molality_is_a_one_condition_series():
    """`osmotic_molality` stays what it always was -- the molality of a run that names no series."""
    assert osmotic.normalize_settings({'osmotic_molality': 0.5})['molalities'] == [0.5]
    assert osmotic.normalize_settings({})['molalities'] == [osmotic.DEFAULTS['osmotic_molality']]


def test_a_molality_the_box_cannot_place_is_refused_and_the_bound_is_named():
    """`osmic_box.MOLALITY_RANGE` is the bound, and the refusal names the value that broke it."""
    with pytest.raises(ValueError, match='between 0.0 and 2.5'):
        osmotic.normalize_settings({'molalities': [0.5, 9.0]})
    with pytest.raises(ValueError, match='between 0.0 and 2.5'):
        osmotic.normalize_settings({'molalities': [-0.5]})


def test_an_empty_series_and_a_repeated_molality_are_both_refused():
    """Two conditions at one molality would be one directory and one measurement reported twice."""
    with pytest.raises(ValueError, match='at least one molality'):
        osmotic.normalize_settings({'molalities': []})
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

def test_prepare_writes_one_directory_per_concentration_each_able_to_carry_its_own_checkpoint(tmp_path):
    """The substance of "checkpoints for each concentration": every condition owns its own files on disk.

    A condition that dies in production has ``md.cpt`` beside it, in its own directory, and its own
    ``attempts.json`` -- so the next entry into the series continues *it* and leaves the finished ones alone.
    """
    record = osmotic.prepare(tmp_path, metadata(tmp_path, molalities=[0.5, 1.5]))

    assert [condition['molality_achieved'] for condition in record['conditions']] == \
           pytest.approx([0.5, 1.5], rel=0.01)

    for directory in ('00_0.5molal', '01_1.5molal'):
        condition = tmp_path / '01_simulate' / 'conditions' / directory
        for name in ('minimization.mdp', 'eq.mdp', 'md.mdp', 'reference.itp', 'osmotic_condition.json'):
            assert (condition / name).is_file(), name
        # The runner reads all four of these from the condition directory it is working in.
        for name in osmotic.SOLUTE_FILES:
            assert (condition / 'solute' / name).is_file(), name
        assert (condition / 'martini_v3.0.0.itp').is_file()
        # And the manifest the analysis divides with is this condition's own: its molality, not the series'.
        written = json.loads((condition / 'osmotic_condition.json').read_text())
        assert written['molality_requested'] == pytest.approx({'00_0.5molal': 0.5, '01_1.5molal': 1.5}[directory])

    manifest = json.loads((tmp_path / '01_simulate' / 'conditions.json').read_text())
    assert [condition['directory'] for condition in manifest['conditions']] == ['00_0.5molal', '01_1.5molal']
    assert manifest['attempts_max'] == osmotic.DEFAULTS['osmotic_attempts_max']
    assert manifest['series_on_failure'] == 'carry_on'
    assert manifest['molecule_id'] == 'Maltose'
    # The executor checks the stage's declared inputs before it runs the stage, and every one of them is a glob
    # over the conditions the build wrote. Nothing else would catch a declaration that names one directory.
    for declared in osmotic.STAGE_DEFS[0].inputs:
        assert list((tmp_path / '01_simulate').glob(declared)), declared


def test_the_stage_declares_the_outputs_the_runner_writes_per_condition(tmp_path):
    """An output pattern that names one condition would read a complete series as an incomplete stage."""
    outputs = osmotic.STAGE_DEFS[0].outputs

    assert set(outputs) == {'conditions/*/built.json', 'conditions/*/system.top',
                            'conditions/*/prod/md_whole.xtc'}
    assert [name for name, _ in osmotic.STAGES] == ['Osmotic series']


def test_the_checkpoint_ceiling_is_written_into_the_runner_and_not_left_at_its_default(tmp_path):
    """The runner is a file read at prepare time, so a per-run ceiling is written into it there."""
    osmotic.prepare(tmp_path, metadata(tmp_path, molalities=[1.0],
                                       settings={'molalities': [1.0], 'osmotic_attempts_max': 5}))

    runner = (tmp_path / '01_simulate' / 'run.sh').read_text()
    assert 'OSMOTIC_ATTEMPTS_MAX="5"' in runner
    assert 'OSMOTIC_ATTEMPTS_MAX="${OSMOTIC_ATTEMPTS_MAX:-3}"' not in runner


def test_the_series_policy_travels_into_the_run_the_runner_reads(tmp_path):
    """The two choices have to reach the process that can enforce them: one driver loop, one policy file."""
    osmotic.prepare(tmp_path, metadata(tmp_path, molalities=[0.5, 1.0],
                                       settings={'molalities': [0.5, 1.0], 'series_on_failure': 'stop'}))

    manifest = json.loads((tmp_path / '01_simulate' / 'conditions.json').read_text())
    assert manifest['series_on_failure'] == 'stop'
    # The runner reads the policy from that file by name, so the name is part of the contract.
    assert osmotic.CONDITIONS_MANIFEST == 'conditions.json'


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
    condition = tmp_path / '01_simulate' / 'conditions' / '00_0.5molal'
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
    assert (tmp_path / '01_simulate' / 'conditions' / '01_1molal').is_dir(), 'the series is untouched'
