"""Re-score a finished run's CG assessment against its model's current references, with no new MD.

Stage 5 (`CG assessment (ff_assess)`) is written once, at run time, and its two figures are the run's *record* of that
one comparison: a score matrix drawn from one `<resid>_<a>_<resid>_<b>_distances_distr.dat` per bead pair, and the
distance distributions beside it. When the run was scored against a parameterization revision that carried no pairwise
family, that record is an all-zero matrix for a comparison that never happened -- and nothing about the run can be
re-run to fix it. The panel's Recompute button re-queues *analyses*, which are derived from the run's outputs; the
matrix is not an analysis, it is the stage's own output.

So this module stages a second attempt instead of rewriting the first:

* `prepare` resolves the run's mapping to its **current** parameterization revision, stages that revision's
  histograms into `<run>/stages/5_assessment@<n>/references/` (through `cg.stage_distributions`, so the copy rule and
  the digest check are the run-prepare rule, not a second one), names the repository `assess.sh` it will run, and
  writes `attempt.json` naming what it read.
* `run` executes that repository script with `cwd` in the attempt directory, `INITIAL_DIR` pointing at the run's own
  `3_initial_CG` and `REFERENCES` at the staged references, and appends the attempt to the manifest under
  `assessment_attempts`. A non-zero exit is recorded as a failed attempt, never raised: the run stays `completed`,
  because a second attempt at its assessment is not a new run.

`stages` is never touched by any of this. The first assessment's directory stays byte-for-byte what it was, its record
stays where it is, and the attempt directories sit beside it -- which is what makes "the run scored 0.00" and "the
run's model carried no pairwise references" two facts a reader can hold at once.

Nothing here writes outside `<run>/stages/5_assessment@<n>/` and the manifest's one new key.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from .. import files
from ..analysis.runs import layout
from ..models.bonded import parameterization
from . import environment
from .adapters import cg
from .coordination import errors

#: The stage this module re-scores, by the name a run records it under. A run type that has no stage by this name has
#: no such assessment to re-score, and says so rather than re-scoring something else.
STAGE = 'CG assessment (ff_assess)'

#: One re-score's directory is `5_assessment@<n>` beside the first attempt's `5_assessment`. `@` rather than a
#: numbered prefix so the first attempt keeps the name every reader and the stage contract already use.
ATTEMPT_PREFIX = '5_assessment@'

#: The repository code the attempt runs, recorded by path and digest: the shared stage script and the two helpers it
#: calls as repository modules. Nothing is copied into the attempt directory.
SCRIPTS = ('dashboard/execution/scripts/assess.sh',
           'dashboard/execution/scripts/validate_run.py',
           'dashboard/execution/scripts/distance_diagnostics.py')

#: The script this module executes, named once.
ASSESS_SCRIPT = 'dashboard/execution/scripts/assess.sh'

#: The runs with an attempt in flight in this process. One attempt per run at a time -- two at once would both stage
#: references and both append to the same list -- and this is process-local for the same reason the analysis workers
#: are: a second dashboard process is answered by the lease on the run directory, not by a shared file.
_CLAIMS = set()
_CLAIMS_LOCK = threading.Lock()

#: The manifest is read-modify-written under this, so two attempts finishing together cannot lose one another's entry.
_MANIFEST_LOCK = threading.Lock()


class RescoreRefused(errors.RunConflict):
    """The run cannot be re-scored, in a sentence a reader can act on.

    A `RunConflict` because every one of these is a fact about the run's recorded state rather than a malformed
    request: the route answers it 409 with this message, which is the same answer a conflicting resume gets.
    """


def in_flight(jid) -> bool:
    """Whether this process holds a re-score slot for `jid`."""
    with _CLAIMS_LOCK:
        return jid in _CLAIMS


def claim(jid):
    """Take the run's one re-score slot, or refuse because an attempt is already running."""
    with _CLAIMS_LOCK:
        if jid in _CLAIMS:
            raise errors.RunBusy('This run is already being re-scored; wait for that attempt to finish')
        _CLAIMS.add(jid)


def release(jid):
    """Give the slot back. Safe on a run that holds none, so a failed prepare can release unconditionally."""
    with _CLAIMS_LOCK:
        _CLAIMS.discard(jid)


def next_attempt(manifest, stages_root) -> int:
    """The number this attempt gets: one past every attempt already recorded, or already on disk.

    The rule is the recorded count, `1 + len(assessment_attempts)` -- so the first re-score of a run is
    `5_assessment@1` -- with the directories on disk taken into account as well. A process that died between creating
    its directory and recording the attempt leaves one behind, and re-using its number would mean staging references
    over a half-written attempt. Numbers may then skip; an attempt is named, never counted, by the manifest.
    """
    recorded = [entry['attempt'] for entry in manifest.get('assessment_attempts') or []
                if isinstance(entry, dict) and isinstance(entry.get('attempt'), int)]
    on_disk = [int(path.name[len(ATTEMPT_PREFIX):]) for path in Path(stages_root).glob(f'{ATTEMPT_PREFIX}*')
               if path.is_dir() and path.name[len(ATTEMPT_PREFIX):].isdigit()]
    return max([*recorded, *on_disk], default=0) + 1


def prepare(coordinator, jid):
    """Stage one re-score attempt and return what it will run against. Raises `RescoreRefused` or `RunBusy`.

    The attempt is staged here rather than in the worker because the answers the caller gets back -- how many
    references it will score with, and which revision they came from -- are the refusal's own facts: a caller told 202
    can already see the attempt directory and its reference count.
    """
    claim(jid)
    try:
        return _prepare(coordinator, jid)
    except BaseException:
        release(jid)
        raise


def _prepare(coordinator, jid):
    job = coordinator.lookup(jid)
    run_dir = Path(coordinator.run_path(job))
    manifest = _manifest(run_dir)
    stages_root = layout.stage_root(run_dir)

    _require_assessment_stage(jid, manifest)
    _require_completed(jid, manifest, job)
    trajectory = _require_trajectory(jid, stages_root)
    mapping = _require_mapping(jid, manifest)
    revision = _require_current_revision(jid, mapping)

    number = next_attempt(manifest, stages_root)
    directory = stages_root / f'{ATTEMPT_PREFIX}{number}'
    # `mkdir` without `parents` and without `exist_ok`, so a directory this function did not just create is an error
    # rather than something to stage over. `next_attempt` makes that unreachable; the call is what keeps it so.
    try:
        directory.mkdir()
    except FileExistsError:
        raise RescoreRefused(f'{jid}: {directory.name} already exists, so attempt {number} cannot be staged beside '
                             'it') from None
    references = directory / 'references'
    references.mkdir()
    names = _cg_names(manifest)
    try:
        inventory = cg.stage_distributions(references, mapping, beads=len(mapping['beads']))
    except (OSError, ValueError) as exc:
        # A recorded histogram whose digest no longer matches is a store changed under the model, and it is a refusal
        # rather than a stage failure: nothing about this run's second attempt can be measured against it either.
        _discard(directory)
        raise RescoreRefused(f'{jid}: {exc}') from None
    if not (inventory.get('pairs') or {}).get('files'):
        # The one refusal the fix this module exists for produced: a revision that records histograms but none of the
        # pairwise family. Its reason is `cg.stage_distributions`'s own sentence, which names the count it holds and
        # the count it needs, so an operator reads why the run is unscorable rather than that it was refused.
        _discard(directory)
        raise RescoreRefused(inventory.get('reason') or
                             f'{jid}: this model records no pairwise distance histograms, so there is nothing to score '
                             'this run against')

    aa_reference = _shared_reference_path(manifest, run_dir)
    staged = Path(references).resolve()
    attempt = {
        'attempt': number,
        'run': jid,
        'directory': str(directory),
        # Run-relative as well, because that is how every other record in this tree names a run's own files, and how
        # the route answers a caller who is going to quote it.
        'relative': str(directory.relative_to(run_dir)),
        'references_directory': str(staged),
        'created_at': files.now_iso(),
        'stage': STAGE,
        'mapping': parameterization.identities(mapping) | {'name': mapping.get('name')},
        'revision': {'revision': revision.get('revision'),
                     'sha256': parameterization.revision_sha256(revision),
                     'engine': revision.get('engine')},
        'trajectory': trajectory,
        'initial': {'directory': str(stages_root / '3_initial_CG'),
                    'itp': names['initial_itp']},
        'aa_reference': str(aa_reference) if aa_reference else None,
        'references': {'files': len(inventory.get('files') or []),
                       'pairs': inventory.get('pairs'),
                       'interactions': inventory.get('interactions'),
                       'inventory': inventory.get('files') or [],
                       'source': (f"revision {revision.get('revision')} of this run's mapping parameterization")},
        # The repository code the attempt runs, named by path and digest instead of copied into the attempt
        # directory: the executor's own rule, applied to a stage that is re-entered rather than prepared.
        'scripts': {relative: files.sha256(environment.ROOT / relative) for relative in SCRIPTS},
    }
    files.atomic_json(directory / 'attempt.json', attempt)
    return attempt


def run(coordinator, jid, attempt):
    """Execute one prepared attempt, append it to the manifest, and give the slot back.

    Runs in the caller's background thread, which is why the application context is pushed here: the coordinator's
    database, its run paths and `paths.current()` are application state, and a worker thread starts with none of it.

    A stage that exits non-zero is recorded, not raised. The run finished before this was asked for and stays
    `completed`; what failed is this attempt, and the exit code and its log are the record of that.
    """
    try:
        with coordinator.app.app_context():
            _execute(coordinator, jid, attempt)
    finally:
        release(jid)


def _execute(coordinator, jid, attempt):
    job = coordinator.lookup(jid)
    run_dir = Path(coordinator.run_path(job))
    directory = Path(attempt['directory'])
    log = directory / 'console.log'
    manifest = _manifest(run_dir)
    started = files.now_iso()
    exit_code, error = _execute_script(directory, log, _environment(manifest, run_dir, attempt))
    entry = {'attempt': attempt['attempt'],
             'directory': _relative(directory, run_dir),
             'started_at': started,
             'ended_at': files.now_iso(),
             'exit_code': exit_code,
             'status': _status(exit_code),
             'references': attempt['references']['files'],
             'revision': attempt['revision']['revision'],
             'mapping_hash': attempt['mapping']['mapping_hash'],
             'log': _relative(log, run_dir)}
    if error:
        entry['error'] = error
    _append(run_dir, entry)
    # The figures this attempt wrote are new artifacts on a run whose index was frozen the moment it completed, so the
    # index is re-read here: without it the panel would keep offering the first assessment's pictures until a restart.
    try:
        coordinator.artifact_index(coordinator.lookup(jid), refresh=True)
    except (OSError, ValueError):
        pass


def _execute_script(directory, log, env):
    """`(exit_code, error)`: the stage script's exit status, and why it could not be started when it could not."""
    command = ['bash', '-e', '-o', 'pipefail', str(environment.ROOT / ASSESS_SCRIPT)]
    with Path(log).open('a') as output:
        output.write(f'$ {shlex.join(command)}\n')
        output.write(json.dumps({'environment': {key: env.get(key) for key in
                                                 ('INITIAL_DIR', 'REFERENCES', 'INITIAL_ITP', 'MOLECULE_TYPE',
                                                  'AA_REFERENCE_DIR', 'PYTHON', 'PYTHONPATH')}}, indent=2) + '\n')
        output.flush()
        try:
            result = subprocess.run(command, cwd=str(directory), env=env, stdout=output, stderr=subprocess.STDOUT)
        except OSError as exc:
            return None, str(exc)
    return result.returncode, None


def _status(exit_code):
    """How a reader should read the attempt's exit code, in the vocabulary every stage already uses."""
    if exit_code == 0:
        return 'completed'
    return 'skipped' if exit_code == 4 else 'failed'


def _environment(manifest, run_dir, attempt):
    """What the repository script is given: the two directories it reads, and the run's own naming context.

    `INITIAL_DIR` is the run's own stage 3, so the ITP the score is measured with is the one this run simulated;
    `REFERENCES` is the attempt's staged revision. The rest is the environment every stage runs in, plus the
    variables the workflow hands a stage from the run's recorded `cg_names` -- `assess.sh` reads `$INITIAL_ITP` under
    `set -u`, and `validate_run.py` and `distance_diagnostics.py` read the molecule type -- and the run's shared AA
    reference, which `validate_run.py` re-reads to check the mapping it is scoring. `PYTHON`/`PYTHONPATH` are the
    executor's own two variables: the script's helpers are repository modules, not files beside it.
    """
    names = _cg_names(manifest)
    env = environment.environment()
    env.update(INITIAL_DIR=str(attempt['initial']['directory']),
               REFERENCES=str(attempt['references_directory']),
               INITIAL_ITP=names['initial_itp'],
               MOLECULE_TYPE=names['residue_name'],
               PYTHON=sys.executable,
               PYTHONPATH=str(environment.ROOT))
    reference = attempt.get('aa_reference') or _shared_reference_path(manifest, run_dir)
    if reference:
        env['AA_REFERENCE_DIR'] = str(reference)
    return env


def _cg_names(manifest):
    """The run's own molecule names, as every stage is handed them, with this run type's defaults behind them."""
    recorded = manifest.get('cg_names') if isinstance(manifest.get('cg_names'), dict) else {}
    return {'residue_name': recorded.get('residue_name') or 'DDM',
            'initial_itp': recorded.get('initial_itp') or 'DDM_initial.itp'}


def _shared_reference_path(manifest, run_dir):
    """The published AA reference this run was scored against, or `None` when it has none to resolve."""
    shared = manifest.get('shared_reference')
    if not isinstance(shared, dict) or not shared.get('source_run_id'):
        return None
    from ..analysis.runs import references as aa_references

    try:
        path, _ = aa_references.resolve(Path(run_dir).parent, shared['source_run_id'], shared.get('sha256'))
    except (OSError, ValueError, KeyError):
        return None
    return Path(path)


def _require_assessment_stage(jid, manifest):
    """A run whose stages name no `CG assessment (ff_assess)` has no assessment to re-score."""
    names = [entry.get('name') for entry in manifest.get('stages') or [] if isinstance(entry, dict)]
    plan = [entry[0] for entry in manifest.get('stage_plan') or []
            if isinstance(entry, (list, tuple)) and entry]
    if STAGE not in names + plan:
        run_type = manifest.get('run_type') or 'unknown'
        raise RescoreRefused(f'Run {jid} ({run_type}) records no `{STAGE}` stage, so it has no assessment to re-score')


def _require_completed(jid, manifest, job):
    """Only a finished run is re-scored: its CG trajectory is final, and its first assessment is history."""
    status = manifest.get('status') or job.get('status')
    if status != 'completed':
        raise RescoreRefused(f'Only a completed run can be re-scored: run {jid} is {status}')


def _require_trajectory(jid, stages_root):
    """What stage 5 scores, named with its digest: the run's coarse-grained production trajectory."""
    production = Path(stages_root) / '4_CG_sim/prod'
    trajectory, structure = production / 'lig_CG.xtc', production / 'lig_CG.gro'
    missing = [path.name for path in (trajectory, structure) if not path.is_file()]
    if missing:
        raise RescoreRefused(f'Run {jid} has no CG trajectory to score: {", ".join(missing)} is not in '
                             f'{production.relative_to(Path(stages_root).parent)}')
    return {'path': str(trajectory.relative_to(Path(stages_root).parent)),
            'sha256': files.sha256(trajectory),
            'structure': str(structure.relative_to(Path(stages_root).parent)),
            'structure_sha256': files.sha256(structure)}


def _require_mapping(jid, manifest):
    """The mapping the run was built from: the record `cg.prepare` staged, in either of the two spellings."""
    mapping = manifest.get('mapping_candidate') or manifest.get('mapping_snapshot')
    if not isinstance(mapping, dict):
        raise RescoreRefused(f'Run {jid} records no mapping, so there is no parameterization to read its references '
                             'from')
    return mapping


def _require_current_revision(jid, mapping):
    """The revision a re-score reads: the model's current one, which is the one a new run would consume."""
    revision = parameterization.current(mapping)
    if revision is None:
        raise RescoreRefused(f"Run {jid}'s mapping ({mapping.get('name') or 'unnamed'}) carries no current "
                             'parameterization revision, so there are no references to re-score it against')
    return revision


def _manifest(run_dir):
    """The run's manifest as it is on disk, read rather than taken from the cache: what is appended must not be."""
    try:
        data = json.loads((Path(run_dir) / 'manifest.json').read_text())
    except (OSError, ValueError) as exc:
        raise RescoreRefused(f'{Path(run_dir).name}: the run manifest cannot be read ({exc})') from None
    if not isinstance(data, dict):
        raise RescoreRefused(f'{Path(run_dir).name}: the run manifest is not an object')
    return data


def _append(run_dir, entry):
    """Append one attempt to the manifest's `assessment_attempts`, leaving every other key exactly as it was."""
    path = Path(run_dir) / 'manifest.json'
    with _MANIFEST_LOCK:
        data = json.loads(path.read_text())
        attempts = data.get('assessment_attempts')
        attempts = list(attempts) if isinstance(attempts, list) else []
        data['assessment_attempts'] = attempts + [entry]
        files.atomic_json(path, data)


def _relative(path, run_dir):
    """A path as the manifest spells it: relative to the run, so the record survives the workspace being moved."""
    try:
        return str(Path(path).relative_to(Path(run_dir)))
    except ValueError:
        return str(path)


def _discard(directory):
    """Remove an attempt directory this function created and has just refused to fill."""
    shutil.rmtree(directory, ignore_errors=True)
