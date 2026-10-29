"""Port one completed run between workspaces: the run directory and its job row travel together.

A run is two things -- `runs/<id>/` and the job record that lists it -- and a workspace that receives only one of them
shows either a row with nothing behind it or a directory nobody can reach. This moves both, keeps the id (mappings
pin an AA source by `aa_reference.run_id`), and re-verifies the copied run against the receiving workspace before it
is committed to.

Dry run by default: it reports what would move, refuses a collision by name, and verifies the source record.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from .. import paths
from ..execution import run_inputs
from ..store import Store


def _paths(workspace):
    return paths.Paths(workspace=Path(workspace))


def plan(source, target, run_id):
    """What an import would move, refusing a missing run or a collision on either side."""
    source, target = _paths(source), _paths(target)
    job = Store(source.database).get(run_id)
    if job is None:
        raise ValueError(f'no run {run_id} in {source.workspace}')
    directory = source.runs / run_id
    if not (directory / 'manifest.json').is_file():
        raise ValueError(f'run {run_id} has no manifest beside it: {directory}')
    if (target.runs / run_id).exists() or Store(target.database).get(run_id) is not None:
        raise ValueError(f'run {run_id} is already in {target.workspace}')
    return source, target, job, directory


def import_run(source, target, run_id, *, apply=False):
    """Copy one run into another workspace, or return the plan that says it would."""
    source, target, job, directory = plan(source, target, run_id)
    manifest = json.loads((directory / 'manifest.json').read_text())
    with paths.use(source):
        run_inputs.verify_manifest(directory, manifest)
    report = {'run': run_id, 'from': str(source.workspace), 'to': str(target.workspace),
              'status': job.get('status'), 'run_type': manifest.get('run_type'), 'applied': False}
    if not apply:
        return report
    destination = target.runs / run_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(directory, destination)
    try:
        # The receiving workspace must be able to prove the copy before it is listed: `repo`-rooted inputs resolve
        # here, and an entry only the source workspace could satisfy is refused by name rather than left dangling.
        with paths.use(target):
            run_inputs.verify_manifest(destination, manifest)
        Store(target.database).insert(job)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    report['applied'] = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog='detergent-import-run')
    parser.add_argument('--run', required=True, help='the 12-character run id')
    parser.add_argument('--from-workspace', required=True)
    parser.add_argument('--to-workspace', required=True)
    parser.add_argument('--apply', action='store_true', help='copy; without it, report what would move')
    arguments = parser.parse_args(argv)
    report = import_run(arguments.from_workspace, arguments.to_workspace, arguments.run, apply=arguments.apply)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
