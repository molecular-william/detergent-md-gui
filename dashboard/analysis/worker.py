"""Isolated analysis subprocess: sources are copied, outputs never replace them.

What each kind *is* -- its name, the files it is handed, how it runs and how it reads -- lives in one row of
`kinds.TABLE`. This module reads the names, the sources and the dispatch from there, so the two shapes it names below
exist for callers rather than as a second declaration.
"""
import fnmatch
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .. import files
from ..execution import tools, workflow
from . import metadata as analysis_metadata
from .kinds import TABLE
from .runs import layout
from .runs import references as aa_references

KINDS = set(TABLE)
PATTERNS = {name: list(row.sources) for name, row in TABLE.items()}


def source_paths(root, kind):
    return list(source_entries(root,kind).values())


def source_entries(root,kind):
    patterns = list(PATTERNS[kind])
    run=root.parent if root.name=='stages' else root
    metadata=json.loads((run/'manifest.json').read_text()) if (run/'manifest.json').is_file() else {}
    shared=metadata.get('shared_reference');aa_source=None
    if TABLE[kind].reads_aa_reference:
        if shared:aa_source,_=aa_references.resolve(run.parent,shared['source_run_id'],shared['sha256'])
        elif metadata.get('run_type')=='aa_only':
            aa_references.verify(run);aa_source=root/'07_reference'
    if TABLE[kind].legacy_sources and not aa_source and not (root/'1_AA-reference/prod/lig.xtc').is_file():
        patterns = list(TABLE[kind].legacy_sources)
    entries={str(p.relative_to(root)):p for p in files.safe_files(root) if str(p.relative_to(root)).split('/')[0] not in ('analysis','analyses','analysis_plots','snapshots','inputs','logs') and any(fnmatch.fnmatch(str(p.relative_to(root)),pattern) for pattern in patterns)}
    if aa_source:entries.update({f'1_AA-reference/prod/{name}':aa_source/name for name in ('lig.gro','lig.xtc')})
    return entries

def execute(request_path):
    request_path = Path(request_path)
    request = json.loads(request_path.read_text())
    run = Path(request['run']); attempt = request_path.parent
    kind = request['kind']; root = workflow.execution_root(run)
    if kind not in KINDS: raise ValueError('Unknown analysis')
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
        for relative,path in source_entries(root,kind).items():
            target = work/relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            provenance=str(path.relative_to(run)) if path.is_relative_to(run) else 'shared/'+str(path.relative_to(run.parent))
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
            result = TABLE[kind].run(work, request.get('payload', {}))
        except layout.NoTrajectory as nothing_to_do:
            files.atomic_json(attempt/'skip.json', {'kind': kind, 'reason': str(nothing_to_do)})
            progress('Skipped: ' + str(nothing_to_do)[:200])
            print(f'Skipped: {nothing_to_do}', flush=True)
            sys.exit(workflow.SKIPPED_EXIT_CODE)
        files.atomic_json(work/'analysis-metadata.json', analysis_metadata.describe(kind, result))
        progress('Publishing immutable results')
        source_key = hashlib.sha256(json.dumps([sources,request.get('payload',{}),request.get('code_signature')],sort_keys=True).encode()).hexdigest()
        output = attempt/'output'/source_key; output.mkdir(parents=True)
        for path in files.safe_files(work):
            relative = str(path.relative_to(work))
            if relative in baseline:
                if files.sha256(path) != baseline[relative]: raise ValueError('Analysis modified its source copy: ' + relative)
                continue
            target = output/relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        files.atomic_json(attempt/'result.json', {'result': result, 'output_directory':str(output.relative_to(attempt)), 'sources_sha256': sources,
                          'outputs_sha256': files.hashes(output), 'tools':versions, 'wall_seconds': time.monotonic()-started})
        progress('Completed')


if __name__ == '__main__':
    execute(sys.argv[1])
