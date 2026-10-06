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
- ``normalize_settings(settings, profile)`` -> the settings the run will use,
  range-checked and completed with that run type's defaults. A run type whose
  stages need both an AA and a CG view composes them itself (``aa_cg`` does),
  rather than making its caller merge two dialects.
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

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .. import files

RUN_TYPES = ('aa_only', 'aa_cg', 'cg_composition', 'pdc')


def write_prepared_manifest(run_dir, metadata, *, tools, plan, environment=None):
    """Write the manifest every prepared run carries, so all three run types agree.

    Four modules used to emit this document and they disagreed: the AA adapter and the CG
    path wrote an input snapshot, the composition adapter wrote none, and only the AA
    adapter recorded the environment. The keys here are the ones the resume path verifies
    against -- `input_snapshot_sha256` above all -- so a run type that omits them is a run
    type the resume path cannot check.

    `metadata` carries what is specific to the run; this adds what every prepared run
    records. `inputs/` must exist before the call, because this hashes it.
    """
    document = dict(metadata)
    document.update(layout_version=2, stage_plan=list(plan), stages=[], tools=tools,
                    input_snapshot_sha256=files.hashes(Path(run_dir) / 'inputs'),
                    prepared_at=datetime.now(timezone.utc).isoformat())
    if environment is not None:
        document['environment'] = environment
    files.atomic_json(Path(run_dir) / 'manifest.json', document)
    return document


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
    prepare: Callable[..., None]
    tool_report: Callable[[], Mapping]


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


def _pdc_protocol() -> Protocol:
    from .adapters import pdc
    return pdc.PROTOCOL


def _osmotic_protocol() -> Protocol:
    from .adapters import osmotic
    return osmotic.PROTOCOL


_BUILDERS: dict[str, Callable[[], Protocol]] = {
    'aa_only': _aa_protocol,
    'aa_cg': _cg_protocol,
    'cg_composition': _composition_protocol,
    'pdc': _pdc_protocol,
    'osmotic': _osmotic_protocol,
}


def adapter_for(run_type: str) -> Protocol:
    """Return the protocol for a run type, or raise ValueError for an unknown one."""
    try:
        return _BUILDERS[run_type]()
    except KeyError as exc:
        raise ValueError(f'Unknown run type: {run_type}') from exc
