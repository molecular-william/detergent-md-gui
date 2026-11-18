"""Isolated analysis subprocess: sources are linked, outputs never replace them.

What each kind *is* -- its name, the files it is handed, how it runs and how it reads -- lives in one row of
`kinds.TABLE`. This module reads the names, the sources and the dispatch from there, so the two shapes it names below
exist for callers rather than as a second declaration.
"""
import fnmatch
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

#: The run-relative directory holding one durable copy of each source an analysis read from outside the run. Each
#: is named as `sources.json` records it (`sources/shared/<path from the workspace>`), so a run directory copied
#: to another machine still holds every input its analyses read and `source_path` answers it from the run alone.
#: An attempt stages no copy of its own: a second attempt of a kind finds the run's copy and stages nothing.
COPIES = 'sources'


def _stage_alias(relative):
    """A stage-relative path with its stage directory replaced by the stage's own registered key.

    The kinds declare a source by one spelling (`4_extension/prod/whole.xtc`, `1_system/*.itp`), while a current
    run writes the numbered directory (`08_extension/…`, `02_system/…`). Normalising both the declared pattern and
    the file's path to the stage key lets one declaration match either layout, without a second list of patterns.
    """
    parts = str(relative).split('/')
    stage = layout.stage_key(parts[0]) if parts else None
    return '/'.join([stage, *parts[1:]]) if stage else str(relative)


def _copy_roots(run, kind):
    """Where this run keeps copies of outside sources: its own first, then an older attempt's, newest first.

    An attempt directory is `analyses/<kind>/<NNNN-date>/` in a current run and `<signature>/<attempt>/` in one
    written before the sequence was named, so the old copies are searched rather than spelled. The run's own copy is
    the one current attempts read; the attempts' copies are the previous lane's, kept so an attempt it published
    still answers.
    """
    yield Path(run)/COPIES
    directory = Path(run)/'analyses'/kind
    if directory.is_dir():
        found = [path for path in directory.glob(f'**/{COPIES}') if path.is_dir()]
        yield from sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)


def _staged_reference(run, kind, source_run_id):
    """This run's copy of the shared AA reference's two files, or `None` when it holds none.

    Both files are staged together, so their copies share a directory; a run whose copies are incomplete (or were
    published by two different attempts) answers `None` rather than half a reference.
    """
    tail = Path('shared')/str(source_run_id)/'stages'/'07_reference'
    for root in _copy_roots(run, kind):
        directory = root/tail
        if all((directory/name).is_file() for name in ('lig.gro', 'lig.xtc')):
            return directory
    return None


def source_entries(root,kind,payload=None):
    patterns = list(TABLE[kind].sources)
    run=root.parent if root.name=='stages' else root
    metadata=json.loads((run/'manifest.json').read_text()) if (run/'manifest.json').is_file() else {}
    shared=metadata.get('shared_reference');aa_source=None
    if TABLE[kind].reads_aa_reference:
        if shared:
            if not shared.get('edition'):
                raise ValueError('A shared AA reference must be pinned by its edition')
            if (run.parent/str(shared.get('source_run_id') or '')).is_dir():
                aa_source,_=aa_references.resolve(run.parent,shared['source_run_id'],shared['edition'])
            else:
                # This run has been copied to a machine without the reference run it was fitted against. The run
                # kept one copy of the two files its analyses read, so the consumer still answers from this run; a
                # run that holds neither that copy nor an earlier attempt's gets the resolver's own refusal instead
                # of a silently empty pair.
                aa_source=_staged_reference(run,kind,str(shared.get('source_run_id') or ''))
                if aa_source is None:
                    raise ValueError(f'the shared AA reference run {shared["source_run_id"]!r} is not under '
                                     f'{run.parent} and this run holds no copy of its lig.gro/lig.xtc')
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

def _copy_name(run, path):
    """The recorded name of an attempt copy published by the previous lane, or `None`.

    That copy sits at `analyses/<kind>/<attempt>/sources/<name>`. An attempt that reads one -- a run directory
    moved to a machine without the store or reference run it came from -- records the name the first attempt
    recorded rather than the path the copy now occupies, and the run then keeps its own copy under that name so
    every later attempt reads the same file.
    """
    try:
        parts = Path(path).relative_to(run).parts
    except ValueError:
        return None
    if not parts or parts[0] != 'analyses':
        return None
    try:
        index = parts.index(COPIES, 2)
    except ValueError:
        return None
    tail = parts[index + 1:]
    return Path(*tail).as_posix() if tail else None


def _source_provenance(run, path):
    """The name `sources.json` records for a source: run-relative, or `sources/<shared name>` when it is outside.

    A source hook may stage a file from the parameterization store, which is beside `runs/`, not under it. The worker
    used to assume every source was under the run or its parent and died on the first store file; the shared name is
    taken from the workspace root when the file is there, so the recorded name list stays readable. The `sources/`
    prefix is what makes an outside source run-relative: the run keeps one copy under it (see `_stage_source_copy`),
    and a previous lane's attempt copy is promoted under the name the first attempt recorded.
    """
    path = Path(path)
    copied = _copy_name(run, path)
    if copied:
        return f'{COPIES}/{copied}'
    if path.is_relative_to(run):
        return str(path.relative_to(run))
    for base in (run.parent, run.parent.parent):
        if path.is_relative_to(base):
            return f'{COPIES}/shared/{path.relative_to(base)}'
    return f'{COPIES}/shared/{path.name}'


def _stage_source_copy(run, path, name):
    """Copy an outside source into the run once, under the name its record carries.

    `name` is `sources/<shared name>` for a file from outside the run and for a previous lane's attempt copy. The
    copy is skipped when the run already holds the same bytes, so a second attempt of a kind stages nothing; the
    named-and-renamed write means a reader never sees a partial file.
    """
    if not name.startswith(COPIES + '/'):
        return
    source, target = Path(path), Path(run)/name
    if target == source:
        return
    if target.is_file() and target.stat().st_size == source.stat().st_size \
            and files.sha256(target) == files.sha256(source):
        return
    files.atomic_copy(source, target)


def source_copy_bytes(run, entries):
    """The bytes a queue request would add under the run's own `sources/`, for the capacity check.

    An outside source already copied at its recorded name with the same size adds nothing, so a second attempt is
    not charged for the copy the first made. A cheap size test rather than a digest: the worker refuses to replace
    an identical file, and a same-sized replacement cannot grow the run past this estimate.
    """
    run, total = Path(run), 0
    for path in entries.values():
        source = Path(path)
        name = _source_provenance(run, source)
        if not name.startswith(COPIES + '/'):
            continue
        try:
            size = source.stat().st_size
        except OSError:
            continue
        target = run/name
        if target.is_file() and target.stat().st_size == size:
            continue
        total += size
    return total


def source_path(run, attempt, name):
    """The file a recorded source name stands for, or `None` when this machine holds none of its copies.

    `name` is one entry of an attempt's `sources.json`: a run-relative path, or `shared/<path from the workspace>`
    for an attempt the previous lane published. The run's own `sources/` copy answers first, so a run directory
    copied to another machine reads what it kept; the original outside path answers when it is still on this
    machine, and an attempt's own `sources/<name>` is the last answer for an older record. `None` rather than a
    missing path, so a caller can name what is gone.
    """
    run, attempt = Path(run), Path(attempt)
    relative = Path(str(name))
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError(f'A recorded analysis source must be a relative name, not {name!r}')
    if relative.parts and relative.parts[0] == 'shared':
        tail = Path(*relative.parts[1:])
        for base in (run.parent, run.parent.parent):
            candidate = base / tail
            if candidate.is_file():
                return candidate
    elif relative.parts:
        candidate = run / relative
        if candidate.is_file():
            return candidate
    for base in (run/COPIES, attempt/COPIES):
        candidate = base / relative
        if candidate.is_file():
            return candidate
    return None


def execute(request_path):
    request_path = Path(request_path)
    request = json.loads(request_path.read_text())
    run = Path(request['run']); attempt = request_path.parent
    features.ensure()
    kind = request['kind']; root = layout.stage_root(run)
    if kind not in TABLE: raise ValueError('Unknown analysis')
    def progress(phase):
        files.atomic_json(attempt/'progress.json', {'phase': phase})
    progress('Staging sources')
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
        work = Path(temporary); sources = []; staged = {}
        for relative,path in source_entries(root,kind,request.get('payload', {})).items():
            target = work/relative; target.parent.mkdir(parents=True, exist_ok=True)
            name = _source_provenance(run, path)
            sources.append(name)
            # A source from outside the run -- the paired AA reference's trajectory, the parameterization store's
            # histograms -- is copied into the run itself, once, under the name `sources.json` records. An attempt
            # keeps no copy of its own, so a second attempt of a kind finds the run's copy and stages nothing; the
            # run directory alone then holds every input its analyses read, and is the link target below.
            link = Path(path)
            if name.startswith(COPIES+'/'):
                _stage_source_copy(run, path, name)
                link = Path(run)/name
            # A run's files are immutable and an analysis only reads them, so every source is staged as a link to
            # the file itself: the attempt writes no second copy of a multi-gigabyte trajectory. `safe_files` skips
            # links, so produced-output enumeration is unchanged, and the stat guard below watches the targets, so
            # a producer that opens one of its inputs for writing is still refused.
            os.symlink(str(link.absolute()), target)
            staged[relative] = Path(path)
        # Refinement depends on the latest completed diagnostic reports, with legacy fallback.
        if TABLE[kind].takes_dependencies:
            for name in ('numerical_stability.json', 'experimental_targets.json'):
                path = request.get('dependencies', {}).get(name)
                path = run/path if path else root/'analysis'/name
                if path.is_file():
                    if path.is_symlink() or not path.resolve().is_relative_to(run.resolve()): raise ValueError('Invalid analysis dependency')
                    target = work/'analysis'/name; target.parent.mkdir(exist_ok=True)
                    # A small report read against the file it names is copied: the producer may edit its own copy,
                    # and the guard re-hashes only a copy whose stat moved, against this source.
                    shutil.copy2(path, target); sources.append(str(path.relative_to(run)))
                    staged[str(target.relative_to(work))] = path
        # The run's own manifest comes along, for the one thing no source path can state: the *name* of the file the
        # run simulated. A fitted run leaves six `.itp` files under `3_initial_CG/`, and `FINAL_ITP` in this manifest
        # is what says which one the simulation ran with -- a producer that must draw the model's own bonds has no
        # other way to find it. Staged before the baseline, so it is an input rather than something an analysis
        # published.
        manifest = run / 'manifest.json'
        if manifest.is_file():
            shutil.copy2(manifest, work / manifest.name)
            sources.append('manifest.json')
            staged[manifest.name] = manifest
        # What an attempt read is recorded by name, never by digest: the identities the queue compares are names
        # and a code version. The stat snapshot below is the producer's own guard -- it must publish new files, not
        # edit the inputs it was handed -- and is never written down or compared across attempts.
        baseline = files.stat_snapshot(work)
        files.atomic_json(attempt/'sources.json', sorted(set(sources)))
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
        # The producer must publish new files, not edit the ones it was handed. Re-statting the snapshot is one walk;
        # a digest is paid only for an entry whose stat moved, against the file it was staged from -- a real copy (a
        # dependency, the run's manifest) or an outside source's original -- so a producer that only touched one is
        # not accused of editing it. An in-run source's link target *is* that file, so there is nothing to compare
        # with: the moved stat is the evidence, and the run's immutable file has been written through.
        after = files.stat_snapshot(work)
        for relative, before in baseline.items():
            if after.get(relative) == before:
                continue
            path, source = work/relative, staged.get(relative)
            try:
                intact = path.is_file() and source is not None \
                    and os.path.realpath(source) != os.path.realpath(path) \
                    and files.sha256(path) == files.sha256(source)
            except OSError:
                intact = False
            if intact:
                continue
            raise ValueError('Analysis modified its source copy: ' + relative)
        produced = []
        for path in files.safe_files(work):
            relative = str(path.relative_to(work))
            if relative in baseline:
                continue
            produced.append((path, relative))
        if stable:
            # One series per run: the coordinator names this attempt after the kind's stable directory, so the
            # producer's files replace the previous build's in place. The JSON record goes last, so a reader that
            # finds it has the pair it describes.
            for path, relative in sorted(produced, key=lambda item: (item[1].endswith('.json'), item[1])):
                files.atomic_copy(path, attempt/relative)
            output_directory = '.'
            outputs_sha256 = {relative: files.sha256(attempt/relative) for _, relative in produced}
        else:
            # The attempt's own directory is already unique, so its published files land in one "output" rather than
            # under a digest of the sources: the record's "output_directory" is what a reader finds them by.
            output = attempt/'output'; output.mkdir(parents=True)
            for path, relative in produced:
                target = output/relative; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            output_directory = str(output.relative_to(attempt))
            outputs_sha256 = files.hashes(output)
        files.atomic_json(attempt/'result.json', {'result': result, 'output_directory':output_directory,
                          'outputs_sha256': outputs_sha256, 'tools':versions, 'wall_seconds': time.monotonic()-started})
        progress('Completed')


if __name__ == '__main__':
    execute(sys.argv[1])
