"""The legacy run migration archives before it moves, never rewrites a manifest, and refuses rather than guesses.

Every run is synthetic: a pdc run with stage directories at its root, an `aa_cg` run with a byte copy of its prepared
tree in `inputs/` and copied helpers inside `stages/`. The properties that matter are that a dry run writes nothing,
that an apply moves or deletes exactly the described paths while the manifest stays byte-identical, that the archive
reads back as the tree it replaced, and that a second apply changes nothing.
"""
import json
import os
import tarfile

from dashboard import files
from dashboard.cli import migrate_run_layout as migration

PDC_RUN = 'pdc0000000001'
AA_RUN = 'aa00000000001'


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def snapshot(root):
    """Every path below `root` with the bytes behind it, so a dry run can be shown to have changed nothing."""
    state = {}
    for path in sorted(root.rglob('*')):
        key = path.relative_to(root).as_posix()
        if path.is_symlink():
            state[key] = ('link', os.readlink(path))
        elif path.is_file():
            state[key] = ('file', files.sha256(path))
        else:
            state[key] = ('dir',)
    return state


def content(state):
    """The snapshot's files and links, without the directory entries a tar extract recreates."""
    return {key: value for key, value in state.items() if value[0] != 'dir'}


def extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:gz') as opened:
        opened.extractall(destination, filter='data')
    return destination


def pdc_run(workspace, run_id=PDC_RUN):
    run = workspace / 'runs' / run_id
    write(run / '0_prepare' / 'pdc_prepare.py', 'print("prepare")\n')
    write(run / '0_prepare' / 'pdc_prepare.sh', '#!/bin/sh\n')
    write(run / '1_system' / 'system.top', '[system]\n')
    write(run / '1_system' / 'protein.pdb', 'ATOM\n')
    write(run / 'logs' / 'console.log', 'prepared\n')
    write(run / 'manifest.json', json.dumps({'id': run_id, 'run_type': 'pdc'}, indent=2) + '\n')
    return run


def aa_run(workspace, run_id=AA_RUN):
    run = workspace / 'runs' / run_id
    for relative, body in (('common/files.py', 'x = 1\n'), ('common/context.json', '{}\n'),
                           ('01_solvation/run.sh', '#!/bin/sh\n'), ('01_solvation/run.mdp', 'nsteps = 1\n'),
                           ('01_solvation/system.top', '[system]\n')):
        write(run / 'stages' / relative, body)
        write(run / 'inputs' / relative, body)
    write(run / 'logs' / 'console.log', 'prepared\n')
    write(run / 'manifest.json', json.dumps({'id': run_id, 'run_type': 'aa_cg', 'layout_version': 2,
                                             'input_snapshot_sha256': {'01_solvation/run.sh': 'ab' * 32}}, indent=2) + '\n')
    return run


def both(tmp_path):
    workspace = tmp_path / 'workspace'
    return workspace, pdc_run(workspace), aa_run(workspace)


def record(run):
    return json.loads((run / migration.RECORD).read_text())


def test_a_dry_run_changes_nothing_but_says_what_would_happen(tmp_path):
    workspace, pdc, aa = both(tmp_path)
    before = snapshot(workspace)

    entries = migration.plan(workspace)

    assert {entry['id']: entry['status'] for entry in entries} == {PDC_RUN: 'moved', AA_RUN: 'trimmed'}
    assert snapshot(workspace) == before
    assert not (pdc / migration.RECORD).exists() and not (aa / migration.RECORD).exists()


def test_the_pdc_move_puts_the_stage_directories_under_stages_and_keeps_everything_else(tmp_path):
    workspace, pdc, _ = both(tmp_path)
    manifest = (pdc / 'manifest.json').read_bytes()
    before = snapshot(pdc)

    migration.apply(migration.plan(workspace, [PDC_RUN]))

    assert sorted(path.name for path in (pdc / 'stages').iterdir()) == ['0_prepare', '1_system']
    assert not (pdc / '0_prepare').exists() and not (pdc / '1_system').exists()
    assert (pdc / 'manifest.json').read_bytes() == manifest
    assert (pdc / 'logs' / 'console.log').exists()
    moved = record(pdc)
    assert moved['tool'] == migration.TOOL and moved['version'] == migration.VERSION
    assert moved['action'] == 'moved' and moved['deleted'] == []
    assert moved['moved'] == ['0_prepare', '1_system']
    assert moved['moved_to'] == ['stages/0_prepare', 'stages/1_system']
    assert moved['archive'] == f'legacy_evidence/run-tree-{moved["date"][:10]}.tar.gz'
    assert moved['archive_sha256'] == files.sha256(pdc / moved['archive'])
    assert 'input_snapshot_sha256' in moved['note']
    assert content(snapshot(pdc))['manifest.json'] == before['manifest.json']


def test_the_pdc_archive_restores_the_stage_tree(tmp_path):
    workspace, pdc, _ = both(tmp_path)
    before = snapshot(pdc)

    migration.apply(migration.plan(workspace, [PDC_RUN]))

    restored = content(snapshot(extract(pdc / record(pdc)['archive'], tmp_path / 'restored')))
    archived = content({key: value for key, value in before.items() if key.split('/')[0] in ('0_prepare', '1_system')})
    assert restored == archived


def test_the_aa_trim_deletes_the_copy_and_the_helpers_and_keeps_the_stage_outputs(tmp_path):
    workspace, _, aa = both(tmp_path)
    manifest = (aa / 'manifest.json').read_bytes()
    before = snapshot(aa)

    migration.apply(migration.plan(workspace, [AA_RUN]))

    assert not (aa / 'inputs').exists()
    left = sorted(path.relative_to(aa / 'stages').as_posix() for path in (aa / 'stages').rglob('*') if path.is_file())
    assert left == ['01_solvation/run.mdp', '01_solvation/system.top', 'common/context.json']
    assert (aa / 'manifest.json').read_bytes() == manifest
    assert (aa / 'logs' / 'console.log').exists()
    trimmed = record(aa)
    assert trimmed['action'] == 'trimmed' and trimmed['moved'] == [] and trimmed['moved_to'] == []
    assert trimmed['deleted'] == ['inputs', 'stages/01_solvation/run.sh', 'stages/common/files.py']
    assert trimmed['archive'] == 'legacy_evidence.tar.gz'
    assert trimmed['archive_sha256'] == files.sha256(aa / 'legacy_evidence.tar.gz')
    assert 'input_snapshot_sha256' in trimmed['note']
    assert before['manifest.json'] == content(snapshot(aa))['manifest.json']


def test_the_aa_archive_restores_what_was_deleted(tmp_path):
    workspace, _, aa = both(tmp_path)
    before = snapshot(aa)

    migration.apply(migration.plan(workspace, [AA_RUN]))

    restored = content(snapshot(extract(aa / 'legacy_evidence.tar.gz', tmp_path / 'restored')))
    archived = content({key: value for key, value in before.items()
                        if key == 'inputs' or key.startswith('inputs/') or key.endswith(('.py', '.sh'))})
    assert restored == archived


def test_a_second_apply_is_a_no_op(tmp_path):
    workspace, _, _ = both(tmp_path)
    migration.apply(migration.plan(workspace))
    after_first = snapshot(workspace)

    entries = migration.plan(workspace)

    assert {entry['status'] for entry in entries} == {'skipped'}
    assert migration.apply(entries) == []
    assert snapshot(workspace) == after_first


def test_a_run_on_the_current_layout_is_skipped(tmp_path):
    workspace = tmp_path / 'workspace'
    run = aa_run(workspace)
    write(run / 'inputs' / 'inputs.json', '[]\n')

    entries = migration.plan(workspace)

    assert [entry['status'] for entry in entries] == ['skipped']
    assert not (run / migration.RECORD).exists()


def test_a_symlinked_run_directory_is_refused(tmp_path):
    workspace = tmp_path / 'workspace'
    real = tmp_path / 'elsewhere' / 'realrun'
    write(real / '0_prepare' / 'pdc_prepare.sh', '#!/bin/sh\n')
    write(real / 'manifest.json', '{}\n')
    (workspace / 'runs').mkdir(parents=True)
    (workspace / 'runs' / PDC_RUN).symlink_to(real, target_is_directory=True)
    before = snapshot(real)

    entries = migration.plan(workspace)

    assert [entry['status'] for entry in entries] == ['refused']
    assert migration.apply(entries) == []
    assert snapshot(real) == before
    assert not (real / migration.RECORD).exists()


def test_a_symlinked_legacy_stage_directory_is_refused(tmp_path):
    workspace = tmp_path / 'workspace'
    run = pdc_run(workspace)
    elsewhere = tmp_path / 'elsewhere'
    write(elsewhere / 'pdc_prepare.sh', '#!/bin/sh\n')
    (run / '1_system').rename(tmp_path / 'moved_aside')
    (run / '1_system').symlink_to(elsewhere, target_is_directory=True)
    before = snapshot(run)

    entries = migration.plan(workspace)

    assert [entry['status'] for entry in entries] == ['refused']
    assert '1_system' in entries[0]['why']
    assert migration.apply(entries) == []
    assert snapshot(run) == before


def test_a_symlink_inside_the_inputs_tree_being_deleted_is_refused(tmp_path):
    workspace = tmp_path / 'workspace'
    run = aa_run(workspace)
    (run / 'inputs' / 'link').symlink_to(tmp_path / 'elsewhere', target_is_directory=True)
    before = snapshot(run)

    entries = migration.plan(workspace)

    assert [entry['status'] for entry in entries] == ['refused']
    assert migration.apply(entries) == []
    assert snapshot(run) == before


def test_a_symlink_nested_in_a_moved_stage_directory_travels_with_it(tmp_path):
    """The real back-map tree holds 100 of these, pointing into the tool checkout; the move must not break them."""
    workspace = tmp_path / 'workspace'
    run = pdc_run(workspace)
    database = tmp_path / 'tool-database'
    write(database / 'atoms.itp', 'atoms\n')
    (run / '1_system' / 'assets').symlink_to(database, target_is_directory=True)

    migration.apply(migration.plan(workspace, [PDC_RUN]))

    moved = run / 'stages' / '1_system' / 'assets'
    assert moved.is_symlink() and os.readlink(moved) == str(database)
    with tarfile.open(run / record(run)['archive'], 'r:gz') as opened:
        link = opened.getmember('1_system/assets')
    assert link.issym() and link.linkname == str(database)


def test_a_pdc_run_that_already_has_stages_is_refused(tmp_path):
    workspace = tmp_path / 'workspace'
    run = pdc_run(workspace)
    (run / 'stages').mkdir()
    before = snapshot(run)

    entries = migration.plan(workspace)

    assert [entry['status'] for entry in entries] == ['refused']
    assert migration.apply(entries) == []
    assert snapshot(run) == before


def test_an_unknown_shape_is_reported_not_guessed(tmp_path):
    workspace = tmp_path / 'workspace'
    run = workspace / 'runs' / 'none00000000'
    write(run / 'manifest.json', '{}\n')
    write(run / 'logs' / 'console.log', 'log\n')
    before = snapshot(run)

    entries = migration.plan(workspace)

    assert [entry['status'] for entry in entries] == ['unknown']
    assert migration.apply(entries) == []
    assert snapshot(run) == before
    assert not (run / migration.RECORD).exists()


def test_the_cli_reports_one_line_per_run_and_writes_nothing_without_apply(tmp_path, capsys):
    workspace, pdc, aa = both(tmp_path)

    code = migration.main(['--workspace', str(workspace)])

    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert len(lines) == 2
    assert any('would move' in line for line in lines)
    assert any('would trim' in line for line in lines)
    assert not (pdc / migration.RECORD).exists() and not (aa / migration.RECORD).exists()


def test_the_cli_selects_the_named_run_and_applies_it(tmp_path, capsys):
    workspace, pdc, aa = both(tmp_path)

    code = migration.main(['--workspace', str(workspace), '--run', PDC_RUN, '--apply'])

    lines = capsys.readouterr().out.splitlines()
    assert code == 0 and len(lines) == 1 and 'moved' in lines[0]
    assert (pdc / 'stages' / '1_system').is_dir()
    assert (aa / 'inputs').is_dir() and not (aa / migration.RECORD).exists()


def test_an_unmigratable_run_makes_the_cli_exit_nonzero(tmp_path, capsys):
    workspace = tmp_path / 'workspace'
    run = workspace / 'runs' / 'none00000000'
    write(run / 'manifest.json', '{}\n')

    code = migration.main(['--workspace', str(workspace)])

    assert code == 1
    assert 'unknown' in capsys.readouterr().out
