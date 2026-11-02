"""Resume continues the stage that stopped from the checkpoint its declaration names.

The stage table is injected here rather than read from an adapter: the declarations a run type makes are Lane A's
contract, and these tests are about what the coordination layer does with a declaration -- which stage it names, which
checkpoint it finds, and what preparation leaves on disk.
"""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from dashboard import files
from dashboard.execution import devices, workflow
from dashboard.execution.adapters import aa
from dashboard.web import views


def stage(name, checkpoint=None, resumes_in_place=False):
    return SimpleNamespace(name=name, relative=f'{name}/run.sh', checkpoint=checkpoint,
                           resumes_in_place=resumes_in_place)


@pytest.fixture
def declarations(monkeypatch):
    """Install one stage table for both the read (plan_for) and the write (stage_definitions) paths."""
    def install(stages):
        pairs = tuple((item.name, item.relative) for item in stages)
        monkeypatch.setattr(workflow, 'plan_for', lambda metadata: tuple(stages))
        monkeypatch.setattr(workflow, 'stage_definitions', lambda metadata: (pairs, {}, {}))
    return install


def tree(root, stages, recorded, skipped=None):
    """A run tree with one directory and script per declared stage, and a manifest recording `recorded`."""
    for item in stages:
        for base in (root / 'inputs', root / 'stages'):
            directory = base / item.name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'run.sh').write_text(f'echo {item.name}\n')
    metadata = {'id': '123456abcdef', 'run_type': 'aa_only', 'layout_version': 2, 'status': 'failed',
                'stages': [{'name': name, 'status': status} for name, status in recorded]}
    if skipped:
        metadata['skipped_stages'] = skipped
    files.atomic_json(root / 'manifest.json', metadata)
    return metadata


def test_the_first_existing_checkpoint_the_declaration_names_is_the_one_continued(tmp_path, declarations):
    stages = [stage('first', 'run.cpt'), stage('second', ('prod/run.cpt', 'run.cpt'))]
    declarations(stages)
    tree(tmp_path, stages, [('first', 'completed'), ('second', 'failed')])
    (tmp_path / 'stages/second/run.cpt').write_text('checkpoint')

    plan = workflow.continue_plan(tmp_path)

    assert plan['name'] == 'second'
    assert plan['checkpoint_relative'] == 'run.cpt'
    assert plan['checkpoint'] == str((tmp_path / 'stages/second/run.cpt').absolute())
    # The declaration is ordered: the first existing name wins, not the first name.
    (tmp_path / 'stages/second/prod').mkdir()
    (tmp_path / 'stages/second/prod/run.cpt').write_text('production checkpoint')
    assert workflow.continue_plan(tmp_path)['checkpoint_relative'] == 'prod/run.cpt'


def test_a_stage_with_no_existing_checkpoint_is_not_offered(tmp_path, declarations):
    stages = [stage('first'), stage('second', ('prod/run.cpt', 'run.cpt'))]
    declarations(stages)
    tree(tmp_path, stages, [('first', 'completed'), ('second', 'failed')])

    assert workflow.continue_plan(tmp_path) is None


def test_a_stage_that_resumes_itself_is_continued_without_a_checkpoint(tmp_path, declarations):
    stages = [stage('first'), stage('series', resumes_in_place=True)]
    declarations(stages)
    tree(tmp_path, stages, [('first', 'completed'), ('series', 'failed')])

    plan = workflow.continue_plan(tmp_path)

    assert plan['name'] == 'series'
    assert plan['checkpoint'] is None and plan['checkpoint_relative'] is None
    assert plan['resumes_in_place'] is True


def test_a_run_with_no_unfinished_stage_has_nothing_to_continue(tmp_path, declarations):
    stages = [stage('first', 'run.cpt'), stage('second', 'run.cpt')]
    declarations(stages)
    tree(tmp_path, stages, [('first', 'completed'), ('second', 'skipped')])
    (tmp_path / 'stages/second/run.cpt').write_text('checkpoint')

    assert workflow.continue_plan(tmp_path) is None


def test_preparation_keeps_the_stage_files_and_truncates_the_manifest(tmp_path, declarations):
    stages = [stage('first', 'run.cpt'), stage('second', 'run.cpt'), stage('third', 'run.cpt')]
    declarations(stages)
    metadata = tree(tmp_path, stages, [('first', 'completed'), ('second', 'failed')])
    metadata['analyses'] = [{'id': 'old', 'kind': 'stability', 'status': 'completed'}]
    files.atomic_json(tmp_path / 'manifest.json', metadata)
    checkpoint = tmp_path / 'stages/second/run.cpt'
    checkpoint.write_text('checkpoint')
    (tmp_path / 'stages/second/prod').mkdir()
    (tmp_path / 'stages/second/prod/partial.xtc').write_text('previous trajectory')
    (tmp_path / 'stages/third/result.txt').write_text('stale downstream')

    prepared = workflow.prepare_continue_in_place(tmp_path)

    assert prepared['status'] == 'queued'
    assert prepared['resume_mode'] == 'continue'
    assert prepared['continue_stage'] == 'second'
    assert prepared['continue_checkpoint'] == 'run.cpt'
    assert prepared['resume_in_place'] is True
    assert prepared['resume_count'] == 1
    assert [entry['name'] for entry in prepared['stages']] == ['first']
    assert checkpoint.read_text() == 'checkpoint'
    assert (tmp_path / 'stages/second/prod/partial.xtc').read_text() == 'previous trajectory'
    assert (tmp_path / 'stages/third/result.txt').read_text() == 'stale downstream'
    assert prepared['analyses'][0]['status'] == 'superseded'
    assert not (tmp_path / 'resume_history').exists()
    assert not (tmp_path / 'resume_journal.json').exists()


def test_preparation_refuses_a_stage_without_a_checkpoint_naming_it(tmp_path, declarations):
    stages = [stage('first'), stage('second', 'run.cpt')]
    declarations(stages)
    tree(tmp_path, stages, [('first', 'completed'), ('second', 'failed')])

    with pytest.raises(ValueError, match='second.*no checkpoint'):
        workflow.prepare_continue_in_place(tmp_path)


def test_preparation_refuses_a_run_whose_stages_all_finished(tmp_path, declarations):
    stages = [stage('first', 'run.cpt'), stage('second', 'run.cpt')]
    declarations(stages)
    tree(tmp_path, stages, [('first', 'completed'), ('second', 'completed')])

    with pytest.raises(ValueError, match='no stage left'):
        workflow.prepare_continue_in_place(tmp_path)


def test_the_worker_hands_the_checkpoint_to_the_continued_stage_only(tmp_path, declarations, monkeypatch):
    stages = [stage('first', 'run.cpt'), stage('second', 'run.cpt'), stage('third', 'run.cpt')]
    declarations(stages)
    tree(tmp_path, stages, [('first', 'completed'), ('second', 'failed')])
    checkpoint = tmp_path / 'stages/second/run.cpt'
    checkpoint.write_text('checkpoint')
    (tmp_path / 'logs').mkdir()
    workflow.prepare_continue_in_place(tmp_path)
    monkeypatch.setattr(aa, 'gromacs_flavour', lambda *arguments, **keywords: 'mpi')
    monkeypatch.setattr(devices, 'detect', lambda *arguments, **keywords: [])
    monkeypatch.setattr(devices, 'in_use', lambda *arguments, **keywords: {})
    seen = {}

    def execute(command, **kwargs):
        seen[Path(kwargs['cwd']).name] = dict(kwargs['env'])
        return subprocess.CompletedProcess(command, 0)

    workflow.run(tmp_path, tmp_path / 'logs/console.log', execute=execute)

    assert seen['second']['MDRUN_CONTINUE'] == str(checkpoint.absolute())
    assert 'MDRUN_CONTINUE' not in seen['third']
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    continued = next(entry for entry in manifest['stages'] if entry['name'] == 'second')
    assert continued['environment']['MDRUN_CONTINUE'] == str(checkpoint.absolute())
    # Once the stage completes, the run owes nothing more from a checkpoint -- and a later stage could not inherit it.
    assert 'continue_stage' not in manifest and 'continue_checkpoint' not in manifest


def test_the_view_offers_continue_only_to_a_failed_run_that_has_a_checkpoint(tmp_path, declarations):
    stages = [stage('first', 'run.cpt'), stage('second', 'run.cpt')]
    declarations(stages)
    tree(tmp_path, stages, [('first', 'completed'), ('second', 'failed')])
    (tmp_path / 'stages/second/run.cpt').write_text('checkpoint')
    record = {'id': '123456abcdef', 'status': 'failed', 'run_type': 'aa_only', 'created': None}

    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    failed = views.run_view(record, run_dir=tmp_path, manifest=manifest)

    assert failed['can_continue'] is True
    assert failed['continue_stage'] == 'second'
    assert failed['resume_stages']
    completed = views.run_view({**record, 'status': 'completed'}, run_dir=tmp_path, manifest=manifest)
    assert completed['can_continue'] is False and completed['continue_stage'] is None
    running = views.run_view({**record, 'status': 'running'}, run_dir=tmp_path, manifest=manifest)
    assert running['can_continue'] is False
