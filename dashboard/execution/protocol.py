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
- ``settings_specs()`` -> ``{key: (lo, hi)}`` or ``{key: (label, lo, hi)}``.
  ``setting_bounds`` reads either; Task 2.6 makes them one shape.
- ``readiness(metadata)`` -> a mapping that always carries ``ready``, ``checks``
  and ``blockers``. Incomplete metadata is a blocker, never an exception: a
  caller that does not know what a run type needs must still get an answer.
- ``prepare(run_dir, metadata)`` -> writes the run directory.
- ``tool_report()`` -> the recorded tool versions, or an empty mapping for a run
  type that uses no external tool.

The per-type wrappers live here for now and move into their adapters as each
adapter is wrapped (Tasks 2.2-2.4): `aa_only` is wrapped already, and
``adapter_for`` returns the adapter's own ``Protocol`` instance for it. The
builders import their adapter inside the function so that an adapter may import
this module to declare its Protocol without creating a cycle.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable

RUN_TYPES = ('aa_only', 'aa_cg', 'cg_composition')


@dataclass(frozen=True)
class Protocol:
    """What every run type can be asked, in shapes that do not vary."""

    name: str
    stage_contract: Callable[[Mapping], tuple]
    settings_specs: Callable[[], Mapping]
    stage_defaults: Callable[[], Mapping]
    normalize_settings: Callable[[Mapping | None], Mapping]
    readiness: Callable[[Mapping], Mapping]
    prepare: Callable[..., None]
    tool_report: Callable[[], Mapping]


def setting_bounds(key: str, bounds) -> tuple[str, float, float]:
    """Read either settings dialect as ``(label, lo, hi)``.

    AA declares ``(lo, hi)`` and CG declares ``(label, lo, hi)``; callers that
    render or compare bounds should not care which adapter they came from.
    """
    if not isinstance(bounds, tuple) or len(bounds) not in (2, 3):
        raise ValueError(f'{key}: settings bounds must be (lo, hi) or (label, lo, hi)')
    return (key, bounds[0], bounds[1]) if len(bounds) == 2 else (bounds[0], bounds[1], bounds[2])


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


_BUILDERS: dict[str, Callable[[], Protocol]] = {
    'aa_only': _aa_protocol,
    'aa_cg': _cg_protocol,
    'cg_composition': _composition_protocol,
}


def adapter_for(run_type: str) -> Protocol:
    """Return the protocol for a run type, or raise ValueError for an unknown one."""
    try:
        return _BUILDERS[run_type]()
    except KeyError as exc:
        raise ValueError(f'Unknown run type: {run_type}') from exc
