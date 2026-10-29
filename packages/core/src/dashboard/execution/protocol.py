"""The run-type protocol: one surface every execution adapter answers.

A caller -- the coordinator, a queue route, a readiness panel, a test -- asks
the same questions of any run type: which stages exist, which settings are
legal, can this run, how is it prepared, which tools were used. The adapters
disagree about the answers' shapes (argument order, settings dialects, whether
they can name a tool at all); absorbing that disagreement here is the point of
this module, so it stops leaking into every caller.

Shapes, as of this module:

- ``stage_contract(metadata)`` -> ``(plan, required_inputs, required_outputs)``
  as ``stages.stage_tables`` defines them.
- ``stages(metadata)`` -> the resolved stage declarations, with any
  molecule-specific script names substituted.
- ``settings_specs()`` -> ``{key: (label, lo, hi)}``. One shape, so a caller that
  renders or compares bounds never asks which adapter it came from.
- ``choice_specs()`` -> ``{key: (label, options)}``, the settings whose value is
  one of a list. Kept apart from the bounded ones because a form renders each in
  its own control, and empty for a run type that has none.
- ``normalize_settings(settings, profile)`` -> the settings the run will use,
  range-checked and completed with that run type's defaults. A run type whose
  stages need both an AA and a CG view composes them itself (``aa_cg`` does),
  rather than making its caller merge two dialects. What it accepts and what it
  publishes are the same vocabulary, which its own test asserts.
- ``readiness(metadata)`` -> a mapping that always carries ``ready``, ``checks``
  and ``blockers``. Incomplete metadata is a blocker, never an exception: a
  caller that does not know what a run type needs must still get an answer.
- ``prepare(run_dir, metadata)`` -> writes the run directory.
- ``tool_report()`` -> the recorded tool versions, or an empty mapping for a run
  type that uses no external tool.

Every run type's wrapper lives in its own adapter: ``adapter_for`` returns the
adapter's own ``Protocol`` instance. The builders import their adapter inside the
function so that an adapter may import this module to declare its Protocol
without creating a cycle.
"""
from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .. import files
from . import devices, run_inputs, run_scripts
from .stages import Stage


def write_prepared_manifest(run_dir, metadata, *, tools, plan, environment=None, references=None,
                            scripts=None, skipped=None, modules=None):
    """Write the manifest every prepared run carries, so all three run types agree.

    Four modules used to emit this document and they disagreed: the AA adapter and the CG
    path wrote an input snapshot, the composition adapter wrote none, and only the AA
    adapter recorded the environment. The keys here are the ones the resume path verifies
    against -- `input_snapshot_sha256` above all -- so a run type that omits them is a run
    type the resume path cannot check.

    `metadata` carries what is specific to the run; this adds what every prepared run
    records. `inputs/` must exist before the call, because this hashes it.

    The environment recorded beside it also carries `devices`: every GPU this host reported at prepare,
    so a report written later can still say what the host had. A caller that records no environment still
    records none -- that rule is the oldest one here and a run type that records none is saying so.
    """
    document = dict(metadata)
    if references is None:
        # A run type that still mirrors its whole stage tree into `inputs/`: layout 2, the old directory digest.
        document.update(layout_version=2, stage_plan=list(plan), stages=[], tools=tools,
                        input_snapshot_sha256=files.hashes(Path(run_dir) / 'inputs'),
                        prepared_at=datetime.now(timezone.utc).isoformat())
    else:
        # The new record: shared inputs named by path and digest, generated data in `inputs/`, one digest over it.
        entries = run_inputs.write(run_dir, references)
        document.update(layout_version=3, stage_plan=list(plan), stages=[], tools=tools, inputs=entries,
                        input_snapshot_sha256=run_inputs.digest(entries),
                        prepared_at=datetime.now(timezone.utc).isoformat())
    if modules is not None:
        # The Python modules a stage executes: the same path+digest record as a script, kept apart because these are
        # imported into an interpreter rather than executed as a file.
        from .environment import ROOT
        document['python_modules'] = run_scripts.record(modules, root=ROOT)
    if skipped is not None:
        # Stages the run's own prepare decided will not run. They get no directory and no script; the executor records
        # them skipped with the reason this mapping states.
        document['skipped_stages'] = dict(skipped)
    if scripts is not None:
        # One record of the code this run executes: a repository path and a digest per stage, checked before it runs.
        from .environment import ROOT
        document['stage_scripts'] = run_scripts.record(scripts, root=ROOT)
    if environment is not None:
        document['environment'] = devices.environment_record(environment)
    files.atomic_json(Path(run_dir) / 'manifest.json', document)
    return document


def run_type_of(metadata) -> str:
    """The run type a metadata document names; absent means the historical combined AA-to-CG job."""
    return metadata.get('run_type') or 'aa_cg'


def profile_for_run_type(run_type: str) -> str:
    """The execution profile a run type runs under when its caller names none.

    One answer, read by the queue route and by the defaults route, so the durations a panel shows are the durations
    the run will use. They were decided in both places before: `/api/defaults` fell back to `standard` while the queue
    stamped `draft-smoke-reference` for an `aa_cg` run, and the panel papered over the gap by naming the profile on
    every request. A form filled from the first answer and posted back as explicit settings would then have queued a
    100 ns CG production where the record said 10 ns (measured: `cg_equil_ps` 5000 / `cg_production_ps` 100000 against
    10 / 10000).

    The CG half's own constant is the literal, resolved through the adapter registry so this module adds none of its
    own; every other type starts from `standard`, which is what `create_job` has always defaulted to.
    """
    if run_type not in RUN_TYPES:
        raise ValueError(f'Unknown run type: {run_type}')
    if run_type == 'aa_cg':
        from .adapters import cg
        return cg.AA_CG_PROFILE
    return 'standard'


def plan_pairs(metadata) -> list[list[str]]:
    """A run's stage plan as `(name, relative)` pairs, whatever shape its adapter declares its stages in.

    Three shapes exist and one of them is a legacy: the AA and CG adapters declare `(name, relative)` pairs, the pdc
    adapter declares `Stage` records, and manifests written before 2026-10-10 by the CG adapter record *names only*.

    A bare name is resolved through the stage contract rather than guessed, and an entry of no known shape raises.
    The previous fallback indexed whatever it was handed, so a name list produced `[['A', 'A'], ['t', 'r']]` -- two
    characters per name -- and returned it as a plan. A silent wrong answer is worse than a refusal, because a caller
    cannot tell it from a right one.

    It lives here rather than in `workflow` because every path that prepares a run needs it, including the CG
    adapter's own prepare, and an adapter importing the orchestrator would be a cycle.
    """
    adapter = adapter_for(run_type_of(metadata))
    by_name = dict(adapter.stage_contract(metadata)[0])
    pairs = []
    for entry in metadata.get('stage_plan') or adapter.stages(metadata):
        if isinstance(entry, Stage):
            pairs.append([entry.name, entry.relative])
        elif isinstance(entry, str):
            if entry not in by_name:
                raise ValueError(f'stage plan names {entry!r}, which is not a stage of this run')
            pairs.append([entry, by_name[entry]])
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            pairs.append([entry[0], entry[1]])
        else:
            raise TypeError(f'cannot read a stage plan entry of type {type(entry).__name__}: {entry!r}')
    return pairs


def finish_prepared_run(run_dir, stages, *, metadata, tools, plan, environment=None,
                        discard=('manifest.json',), references=None, scripts=None, skipped=None, modules=None):
    """Turn a filled stage directory into a prepared run: `inputs/` beside it, and the manifest at the root.

    The choreography every run type performs and only one of them used to own: a type fills `stages/`, and this copies
    that tree to `inputs/` -- the immutable record the resume path verifies -- and writes the manifest that names the
    plan, the tools and the input snapshot's hash. Doing it in one place is what lets `prepare` mean the same thing
    whichever run type is behind it.

    `discard` names the files a type leaves in `stages/` as its own channel rather than as stage input. The CG
    adapter writes its record there, and a stale copy in `inputs/` would be a second manifest nothing updates.
    """
    run_dir, stages = Path(run_dir), Path(stages)
    for name in discard:
        (stages / name).unlink(missing_ok=True)
    shutil.copytree(stages, run_dir / 'inputs')
    return write_prepared_manifest(run_dir, metadata, tools=tools, plan=plan, environment=environment,
                                   references=references, scripts=scripts, skipped=skipped, modules=modules)


def no_choice_specs() -> Mapping:
    """The empty vocabulary a run type with no choice-typed settings publishes.

    Named rather than written as a lambda so the dataclass field below has one shared default, and so a caller that
    asks a run type with no choices gets a declared empty answer instead of an absence.
    """
    return {}


@dataclass(frozen=True)
class Protocol:
    """What every run type can be asked, in shapes that do not vary."""

    name: str
    stage_contract: Callable[[Mapping], tuple]
    stages: Callable[[Mapping], tuple]
    settings_specs: Callable[[], Mapping]
    stage_defaults: Callable[[], Mapping]
    normalize_settings: Callable[..., Mapping]
    readiness: Callable[[Mapping], Mapping]
    # `object`, not `None`: an adapter may return the record it wrote (osmotic returns its condition, the CG adapter
    # returns the run's manifest). Callers that only want the side effect are free to ignore it.
    prepare: Callable[..., object]
    tool_report: Callable[[], Mapping]
    # The settings whose value is one of a list -- the nonbonded scheme, a series id. Kept apart from
    # `settings_specs` because they are bounded differently and a caller rendering a form needs each in its own
    # control. Everything that has none takes the shared default instead of repeating an empty mapping.
    choice_specs: Callable[[], Mapping] = no_choice_specs


def blocked(*reasons: str) -> dict:
    """The readiness answer for a run that cannot start, in the shared shape."""
    return {'ready': False, 'checks': [], 'blockers': [reason for reason in reasons if reason]}


def _aa_protocol() -> Protocol:
    from .adapters import aa
    return aa.PROTOCOL


def _cg_protocol() -> Protocol:
    from .adapters import cg
    return cg.PROTOCOL


def _composition_protocol() -> Protocol:
    from .adapters import composition
    return composition.PROTOCOL


def _osmotic_protocol() -> Protocol:
    from .adapters import osmotic
    return osmotic.PROTOCOL


_BUILDERS: dict[str, Callable[[], Protocol]] = {
    'aa_only': _aa_protocol,
    'aa_cg': _cg_protocol,
    'cg_composition': _composition_protocol,
    'osmotic': _osmotic_protocol,
}

RUN_TYPES: tuple[str, ...] = tuple(_BUILDERS)
"""Every run type, derived from the registry rather than listed beside it.

It was a hand-written tuple that omitted `osmotic` -- reachable by name, invisible to anything that walked the
published tuple. A list that has to agree with a dict is a second source of truth, and this one was already wrong.
"""


def register(builders: Mapping[str, Callable[[], Protocol]]) -> None:
    """Add the run types one feature owns, and republish the tuple that lists them.

    `RUN_TYPES` is read through this module (`protocol.RUN_TYPES`), so rebinding it here is enough for the callers;
    a feature never writes to `_BUILDERS` directly.
    """
    global RUN_TYPES
    _BUILDERS.update(builders)
    RUN_TYPES = tuple(_BUILDERS)


def adapter_for(run_type: str) -> Protocol:
    """Return the protocol for a run type, or raise ValueError for an unknown one.

    Discovery is forced here because not every caller builds an application: a unit test, a CLI command and the
    analysis subprocess all reach a run type without `create_app`, and a feature run type missing from the table
    would otherwise read as an unknown name.
    """
    from .. import features
    features.ensure()
    try:
        return _BUILDERS[run_type]()
    except KeyError as exc:
        raise ValueError(f'Unknown run type: {run_type}') from exc
