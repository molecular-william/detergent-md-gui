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
  stages need both an AA and a CG view composes them itself (``cg`` does),
  rather than making its caller merge two dialects. What it accepts and what it
  publishes are the same vocabulary, which its own test asserts.
- ``readiness(metadata)`` -> a mapping that always carries ``ready``, ``checks``
  and ``blockers``. Incomplete metadata is a blocker, never an exception: a
  caller that does not know what a run type needs must still get an answer.
- ``prepare(run_dir, metadata)`` -> writes the run directory.
- ``label(molecule, settings, *, protein=None)`` -> the name an unnamed run of this type is given, when the type
  names one. A type that names none keeps the engine's ``[molecule]-[AA|CG]-...`` label.

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


def _provenance(document, entries):
    """What a prepared run can say about the code, the inputs and the reference it was built from.

    It is written beside the manifest and read by nobody: provenance is a record for a person, not a gate. A
    reference's edition is recorded when the run names one; a run that names none records nulls rather than
    pretending to have checked something.
    """
    code = {key: {stage: {'name': entry.get('name'), 'version': entry.get('version')}
                  for stage, entry in (document.get(key) or {}).items()}
            for key in ('stage_scripts', 'python_modules')}
    inputs = [{'role': entry.get('role'), 'root': entry.get('root'), 'path': entry.get('path')}
              for entry in (entries or ())]
    reference = {'run_id': None, 'edition': None}
    candidates = [document.get('shared_reference'), document.get('aa_reference')]
    for key in ('parameterization', 'bonded'):
        block = document.get(key)
        if isinstance(block, dict):
            candidates.append(block.get('aa_reference'))
    for value in candidates:
        if not isinstance(value, dict):
            continue
        run_id = value.get('source_run_id') or value.get('run_id')
        edition = value.get('edition')
        if run_id is not None or edition is not None:
            reference = {'run_id': run_id, 'edition': edition}
            break
    return {'code': code, 'inputs': inputs, 'reference': reference}


def write_prepared_manifest(run_dir, metadata, *, tools, plan, environment=None, references=(),
                            scripts=None, skipped=None, modules=None):
    """Write the manifest every prepared run carries, so all run types agree.

    `metadata` carries what is specific to the run; this adds what every prepared run records. `references` names
    each shared input in place: layout 4 records `role/label/kind/root/path` and no input snapshot, so nothing starts
    or refuses on a digest.

    `inputs/` must exist before the call, because the record is written there.

    The environment recorded beside it also carries `devices`: every GPU this host reported at prepare,
    so a report written later can still say what the host had. A caller that records no environment still
    records none -- that rule is the oldest one here and a run type that records none is saying so.
    """
    run_dir = Path(run_dir)
    document = dict(metadata)
    entries = run_inputs.write(run_dir, references or ())
    document.update(layout_version=run_inputs.LAYOUT, stage_plan=list(plan), stages=[], tools=tools,
                    inputs=entries, prepared_at=datetime.now(timezone.utc).isoformat())
    if modules is not None:
        # The Python modules a stage executes: the same name+version record as a script, kept apart because these are
        # imported into an interpreter rather than executed as a file.
        from .environment import ROOT
        document['python_modules'] = run_scripts.record(modules, root=ROOT)
    if skipped is not None:
        # Stages the run's own prepare decided will not run. They get no directory and no script; the executor records
        # them skipped with the reason this mapping states.
        document['skipped_stages'] = dict(skipped)
    if scripts is not None:
        # One record of the code this run executes: a name and version per stage, checked before it runs.
        from .environment import ROOT
        document['stage_scripts'] = run_scripts.record(scripts, root=ROOT)
    if environment is not None:
        document['environment'] = devices.environment_record(environment)
    files.atomic_json(run_dir / 'manifest.json', document)
    files.atomic_json(run_dir / 'provenance.json', _provenance(document, entries))
    return document


#: The run types this registry no longer answers. A record that still names one is a record written before the
#: migration, and the refusal says how to move it rather than reading as a typo.
RETIRED_RUN_TYPES: tuple[str, ...] = ('aa_cg', 'sugar_cg', 'cg_composition')

RETIRED_RUN_TYPE_MESSAGE = (
    'run type {name!r} is retired; migrate the run records with '
    '`python -m dashboard.cli.migrate_run_types --apply`')


def run_type_of(metadata) -> str:
    """The run type a metadata document names; absent means the run the migration rewrote to ``cg``.

    An absent type is the historical combined AA-to-CG job, which `aa_cg` was the name of. `dashboard.cli.
    migrate_run_types` rewrites those records to ``cg`` with ``cg_model_kind: revision``, exactly as it rewrites a
    record naming ``aa_cg`` explicitly, so this default agrees with the record the migration leaves behind. Partial
    metadata that a caller holds rather than reads from a manifest (a stage list, a filter) therefore resolves to
    the one run type whose stage vocabulary and settings are the CG pipeline's.
    """
    return (metadata.get('run_type') if isinstance(metadata, dict) else None) or 'cg'


def profile_for_run_type(run_type: str) -> str:
    """The execution profile a run type runs under when its caller names none.

    One answer, read by the queue route and by the defaults route, so the durations a panel shows are the durations
    the run will use. They were decided in both places before: `/api/defaults` fell back to `standard` while the queue
    stamped `draft-smoke-reference` for an `aa_cg` run, and the panel papered over the gap by naming the profile on
    every request. A form filled from the first answer and posted back as explicit settings would then have queued a
    100 ns CG production where the record said 10 ns (measured: `cg_equil_ps` 5000 / `cg_production_ps` 100000 against
    10 / 10000).

    The CG half's own constant is the literal, resolved through the adapter registry so this module adds none of its
    own; `sugar_cg` has its own duration preset for the same reason; every other type starts from `standard`, which
    is what `create_job` has always defaulted to.
    """
    if run_type not in RUN_TYPES:
        raise ValueError(f'Unknown run type: {run_type}')
    if run_type == 'cg':
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
                        discard=('manifest.json',), references=(), scripts=None, skipped=None, modules=None):
    """Turn a filled stage directory into a prepared run: `inputs/` beside it, and the manifest at the root.

    The choreography every run type performs and only one of them used to own: a type fills `stages/`, and this copies
    that tree to `inputs/` -- the immutable record the resume path verifies -- and writes the manifest that names the
    plan, the tools and the inputs by path. Doing it in one place is what lets `prepare` mean the same thing whichever
    run type is behind it.

    `discard` names the files a type leaves in `stages/` as its own channel rather than as stage input. The CG
    adapter writes its record there, and a stale copy in `inputs/` would be a second manifest nothing updates.
    """
    run_dir, stages = Path(run_dir), Path(stages)
    for name in discard:
        (stages / name).unlink(missing_ok=True)
    shutil.copytree(stages, run_dir / 'inputs')
    return write_prepared_manifest(run_dir, metadata, tools=tools, plan=plan, environment=environment,
                                   references=references, scripts=scripts, skipped=skipped, modules=modules)


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
    # The settings whose value is one of a list -- the nonbonded scheme, a series id. Kept apart from
    # `settings_specs` because they are bounded differently and a caller rendering a form needs each in its own
    # control. Everything that has none takes the shared default instead of repeating an empty mapping.
    choice_specs: Callable[[], Mapping] = dict
    #: An unnamed run's label in this type's own vocabulary. `None` keeps the engine's generated label, so the
    #: shell states no feature's naming rule and a feature that has one declares it beside its other answers.
    label: Callable[..., str] | None = None


def blocked(*reasons: str) -> dict:
    """The readiness answer for a run that cannot start, in the shared shape."""
    return {'ready': False, 'checks': [], 'blockers': [reason for reason in reasons if reason]}


def _aa_protocol() -> Protocol:
    from .adapters import aa
    return aa.PROTOCOL


def _cg_run_protocol() -> Protocol:
    from .adapters import cg_run
    return cg_run.PROTOCOL


_BUILDERS: dict[str, Callable[[], Protocol]] = {
    'aa_only': _aa_protocol,
    'cg': _cg_run_protocol,
}

RUN_TYPES: tuple[str, ...] = tuple(_BUILDERS)
"""Every run type, derived from the registry rather than listed beside it.

It was a hand-written tuple that omitted `osmotic` -- reachable by name, invisible to anything that walked the
published tuple. A list that has to agree with a dict is a second source of truth, and this one was already wrong.
"""

RUN_TYPE_LABELS: Mapping[str, str] = {
    'aa_only': 'AA simulation',
    'cg': 'CG simulation',
}
"""What the engine's own run types are called where a person reads them.

Presentation only: the vocabulary is `RUN_TYPES`, and a name with no label reads as its own slug. A feature labels
its own types (`Feature.run_type_labels`) so that `pdc` or `osmotic` never has to be spelled out in the engine --
the shell must not learn a feature's vocabulary by being edited.
"""


def register(builders: Mapping[str, Callable[[], Protocol]]) -> None:
    """Add the run types one feature owns, and republish the tuple that lists them.

    `RUN_TYPES` is read through this module (`protocol.RUN_TYPES`), so rebinding it here is enough for the callers;
    a feature never writes to `_BUILDERS` directly.
    """
    global RUN_TYPES
    retired = sorted(set(builders) & set(RETIRED_RUN_TYPES))
    if retired:
        raise ValueError('a retired run type cannot be registered: ' + ', '.join(retired))
    _BUILDERS.update(builders)
    RUN_TYPES = tuple(_BUILDERS)


def adapter_for(run_type: str) -> Protocol:
    """Return the protocol for a run type, or raise ValueError for an unknown or retired one.

    Discovery is forced here because not every caller builds an application: a unit test, a CLI command and the
    analysis subprocess all reach a run type without `create_app`, and a feature run type missing from the table
    would otherwise read as an unknown name.
    """
    from .. import features
    features.ensure()
    try:
        return _BUILDERS[run_type]()
    except KeyError as exc:
        if run_type in RETIRED_RUN_TYPES:
            raise ValueError(RETIRED_RUN_TYPE_MESSAGE.format(name=run_type)) from exc
        raise ValueError(f'Unknown run type: {run_type}') from exc
