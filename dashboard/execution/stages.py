"""Declarative workflow stage tables shared by execution adapters.

Each Stage declares the executable path relative to a run's stages/ directory
plus the input and output patterns that must exist for the stage to run or be
considered complete. Adapters assemble a Stage tuple and publish the legacy
(plan, inputs, outputs) mapping that workflow.run and its callers consume.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    name: str
    relative: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()

    def resolve(self, context: Mapping[str, str] | None = None) -> "Stage":
        """Return this declaration with run-specific placeholders resolved."""
        values = context or {}
        return Stage(
            name=self.name.format_map(values),
            relative=self.relative.format_map(values),
            inputs=tuple(value.format_map(values) for value in self.inputs),
            outputs=tuple(value.format_map(values) for value in self.outputs),
        )


def stage_tables(
    stages: tuple[Stage, ...],
    context: Mapping[str, str] | None = None,
) -> tuple[tuple[tuple[str, str], ...], dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Adapt a Stage tuple to the (plan, inputs, outputs) contract.

    plan:    tuple of (name, relative) in execution order
    inputs:  {name: required input patterns relative to the stage directory}
    outputs: {name: required output patterns relative to the stage directory}
    """
    resolved = tuple(stage.resolve(context) for stage in stages)
    plan = tuple((s.name, s.relative) for s in resolved)
    inputs = {s.name: s.inputs for s in resolved}
    outputs = {s.name: s.outputs for s in resolved}
    return plan, inputs, outputs
