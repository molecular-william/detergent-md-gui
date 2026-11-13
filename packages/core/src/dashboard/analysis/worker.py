"""Isolated analysis subprocess: sources are copied, outputs never replace them.

What each kind *is* -- its name, the files it is handed, how it runs and how it reads -- lives in one row of
`kinds.TABLE`. This module reads the names, the sources and the dispatch from there, so the two shapes it names below
exist for callers rather than as a second declaration.
"""
import fnmatch
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .. import features, files
from ..execution import tools, workflow
from . import metadata as analysis_metadata
from . import progress as analysis_progress
from .kinds import TABLE
from .runs import layout
from .runs import references as aa_references


def _stage_alias(relative):
    """A stage-relative path with its stage directory replaced by the stage's own registered key.

    The kinds declare a source by one spelling (`4_extension/prod/whole.xtc`, `1_system/*.itp`), while a current
    run writes the numbered directory (`08_extension/…`, `02_system/…`). Normalising both the declared pattern and
    the file's path to the stage key lets one declaration match either layout, without a second list of patterns.
    """
    parts = str(relative).split('/')
    stage = layout.stage_key(parts[0]) if parts else None
    return '/'.join([stage, *parts[1:]]) if stage else str(relative)


def source_entries(root,kind,payload=None):
    patterns = list(TABLE[kind].sources)
    run=root.parent if root.name=='stages' else root
    metadata=json.loads((run/'manifest.json').read_text()) if (run/'manifest.json').is_file() else {}
    shared=metadata.get('shared_reference');aa_source=None
    if TABLE[kind].reads_aa_reference:
        if shared:aa_source,_=aa_references.resolve(run.parent,shared['source_run_id'],shared['sha256'])
        elif metadata.get('run_type')=='aa_only':
            aa_references.verify(run);aa_source=root/'07_reference'
    def matches(relative):
        if any(fnmatch.fnmatch(relative, pattern) for pattern in patterns):
            return True
        # Both layouts name the same stage: the numbered directories and the legacy spellings are aliases of one
        # pattern, so a current run's sources are staged exactly as a legacy run's are. `_stage_alias` is the
        # identity for any directory `layout.stage_key` does not know, so this cannot widen a non-stage pattern.
        return any(fnmatch.fnmatch(_stage_alias(relative), _stage_alias(pattern)) for pattern in patterns)
    entries={str(p.relative_to(root)):p for p in files.safe_files(root) if str(p.relative_to(root)).split('/')[0] not in ('analysis','analyses','analysis_plots','snapshots','inputs','logs') and matches(str(p.relative_to(root)))}
    if aa_source:entries.update({f'1_AA-reference/prod/{name}':aa_source/name for name in ('lig.gro','lig.xtc')})
    # A kind whose sources are decided by its request rather than by a pattern list: the hook validates the payload and
    # resolves the files against the run root, which is also where the queue fingerprints them.
    if TABLE[kind].source_hook is not None:
        entries.update(TABLE[kind].source_hook(run, payload or {}))
    return entries

def _source_provenance(run, path):
    """The run-relative name of a source, or a stable shared name when it lives outside the run.

    A source hook may stage a file from the parameterization store, which is beside `runs/`, not under it. The worker
    used to assume every source was under the run or its parent and died on the first store file; the shared name is
    taken from the workspace root when the file is there, so the digest list stays readable.
    """
    if path.is_relative_to(run):
        return str(path.relative_to(run))
    for base in (run.parent, run.parent.parent):
        if path.is_relative_to(base):
            return 'shared/' + str(path.relative_to(base))
    return 'shared/' + path.name


def execute(request_path):
    request_path = Path(request_path)
    request = json.loads(request_path.read_text())
    run = Path(request['run']); attempt = request_path.parent
    features.ensure()
    kind = request['kind']; root = layout.stage_root(run)
    if kind not in TABLE: raise ValueError('Unknown analysis')
    def progress(phase):
        files.atomic_json(attempt/'progress.json', {'phase': phase})
    progress('Copying and hashing sources')
    versions = {'python':sys.version,'executable':sys.executable}
    for package in ('MDAnalysis','numpy','matplotlib','plotly','scikit-image','scipy'):
        try: versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: pass
    gmx = tools.tool_path('gmx')
    if gmx and TABLE[kind].records_gmx_version:
        info = subprocess.run([gmx,'--version'],capture_output=True,text=True,timeout=30,check=True)
        versions['gmx'] = {'path':gmx,'version_output':info.stdout}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='.work-', dir=attempt) as temporary:
        work = Path(temporary); sources = {}
        for relative,path in source_entries(root,kind,request.get('payload', {})).items():
            target = work/relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            provenance=_source_provenance(run, path)
            sources[provenance] = files.sha256(target)
        # Refinement depends on the latest completed diagnostic reports, with legacy fallback.
        if TABLE[kind].takes_dependencies:
            for name in ('numerical_stability.json', 'experimental_targets.json'):
                path = request.get('dependencies', {}).get(name)
                path = run/path if path else root/'analysis'/name
                if path.is_file():
                    if path.is_symlink() or not path.resolve().is_relative_to(run.resolve()): raise ValueError('Invalid analysis dependency')
                    target = work/'analysis'/name; target.parent.mkdir(exist_ok=True)
                    shutil.copy2(path, target); sources[str(path.relative_to(run))] = files.sha256(target)
        # The run's own manifest comes along, for the one thing no source path can state: the *name* of the file the
        # run simulated. A fitted run leaves six `.itp` files under `3_initial_CG/`, and `FINAL_ITP` in this manifest
        # is what says which one the simulation ran with -- a producer that must draw the model's own bonds has no
        # other way to find it. Staged before the baseline, so it is an input rather than something an analysis
        # published.
        manifest = run / 'manifest.json'
        if manifest.is_file():
            shutil.copy2(manifest, work / manifest.name)
            sources.setdefault('manifest.json', files.sha256(work / manifest.name))
        baseline = files.hashes(work)
        files.atomic_json(attempt/'sources.json', sources)
        progress('Calculating ' + kind)
        # One call for every kind: the row holds the dispatch, and the analyses that read only the sources they were
        # handed are adapted to this shape where they are declared rather than by a branch here.
        #
        # A kind whose producer finds nothing to work on is not a failure. `layout.NoTrajectory` is the one such
        # refusal: a run with no trajectory has nothing to sample, and saying so is the honest outcome rather than
        # an error. It is recorded as the workflow contract's skip -- exit 4, with the producer's own reason in
        # `skip.json` beside the request -- so the coordinator records `skipped` and the run is left alone.
        try:
            # The producer is a separate function in this process; naming its progress file here lets it report a
            # phase from any thread it starts, without the `Kind` signature growing a parameter every kind ignores.
            previous = os.environ.get(analysis_progress.ENV)
            os.environ[analysis_progress.ENV] = str(attempt/'progress.json')
            try:
                result = TABLE[kind].run(work, request.get('payload', {}))
            except layout.NoTrajectory as nothing_to_do:
                files.atomic_json(attempt/'skip.json', {'kind': kind, 'reason': str(nothing_to_do)})
                progress('Skipped: ' + str(nothing_to_do)[:200])
                print(f'Skipped: {nothing_to_do}', flush=True)
                sys.exit(workflow.SKIPPED_EXIT_CODE)
        finally:
            if previous is None:
                os.environ.pop(analysis_progress.ENV, None)
            else:
                os.environ[analysis_progress.ENV] = previous
        files.atomic_json(work/'analysis-metadata.json', analysis_metadata.describe(kind, result))
        stable = TABLE[kind].stable_directory
        progress('Publishing results' if stable else 'Publishing immutable results')
        produced = []
        for path in files.safe_files(work):
            relative = str(path.relative_to(work))
            if relative in baseline:
                if files.sha256(path) != baseline[relative]: raise ValueError('Analysis modified its source copy: ' + relative)
                continue
            produced.append((path, relative))
        if stable:
            # One series per run: the coordinator names this attempt after the kind's stable directory, so the
            # producer's files replace the previous build's in place instead of landing under a content hash. The
            # JSON record goes last, so a reader that finds it has the pair it describes.
            for path, relative in sorted(produced, key=lambda item: (item[1].endswith('.json'), item[1])):
                files.atomic_copy(path, attempt/relative)
            output_directory = '.'
            outputs_sha256 = {relative: files.sha256(attempt/relative) for _, relative in produced}
        else:
            source_key = hashlib.sha256(json.dumps([sources,request.get('payload',{}),request.get('code_signature')],sort_keys=True).encode()).hexdigest()
            output = attempt/'output'/source_key; output.mkdir(parents=True)
            for path, relative in produced:
                target = output/relative; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            output_directory = str(output.relative_to(attempt))
            outputs_sha256 = files.hashes(output)
        files.atomic_json(attempt/'result.json', {'result': result, 'output_directory':output_directory, 'sources_sha256': sources,
                          'outputs_sha256': outputs_sha256, 'tools':versions, 'wall_seconds': time.monotonic()-started})
        progress('Completed')


if __name__ == '__main__':
    execute(sys.argv[1])
