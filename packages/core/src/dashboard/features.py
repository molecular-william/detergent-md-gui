"""The dashboard's selectable halves: an installed feature registers itself with the engine.

The engine (`dashboard`) owns the run lifecycle, persistence, the molecule and mapping models and the shell. Two
features sit on top -- detergent validation and protein-detergent simulations -- and each is its own distribution.
A feature is present when its package is importable: `find_spec` is the install check, because there is no plugin
registry to keep in sync with pip and an installed distribution that cannot be imported is not a usable feature.

Core never imports a feature. This module is the only place that names them, and the record each one exports is the
whole contract: the blueprints to register, the run types and their protocol builders, the analysis kinds it owns, and
the workspace it contributes to the shell. Everything is added to registries that already exist and are imported by
their consumers as dicts/objects, so registering *mutates* them rather than rebinding a name a route has already
captured.
"""
from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

#: The feature distributions this repository builds. Deliberately closed: a feature is a package shipped from here,
#: not an extension point for a third party, and a name list is easier to reason about than metadata discovery.
KNOWN = ('detergent_validation', 'detergent_pdc')


@dataclass(frozen=True)
class Feature:
    """What one installed feature contributes to the engine.

    Every field is optional because the features differ in shape: validation owns analyses and most panels, pdc owns
    a run type, a table of stages and one workspace. A feature supplies only what it has.
    """

    name: str
    #: Flask blueprints to register after the engine's own.
    blueprints: tuple = ()
    #: `{run type: builder}` added to `execution.protocol`; the builder returns the feature's `Protocol`.
    protocols: Mapping[str, Callable] = field(default_factory=dict)
    #: `kinds.Kind` rows the feature owns.
    kinds: tuple = ()
    #: `(name, record)` added to `web.sections.SECTIONS`: the workspace this feature contributes.
    section: tuple | None = None
    #: `(slug, (label, glyph))` and `(slug, blurb)` and `(slug, DOM id)` for the panels in that workspace.
    panels: tuple = ()
    blurbs: tuple = ()
    tab_ids: tuple = ()
    #: `(recorded path prefix, distribution, prefix in that package)` for code the feature took over, so a prepared
    #: run's recorded `dashboard/...` path still resolves to the file's new home.
    code_prefixes: tuple = ()
    #: `{run type: (payload) -> None}` admission rules a feature's run types need; raise ValueError to refuse.
    admission: Mapping[str, Callable] = field(default_factory=dict)
    #: `(label, package directory)` trees whose content decides an analysis result, so a feature edit mints a new
    #: attempt instead of reusing a completed one (`analysis_coordinator.code_fingerprint_files`).
    code_roots: tuple = ()
    #: `{run type: (job, root) -> metadata}` the arguments its adapter's `prepare` is called with.
    prepare: Mapping[str, Callable] = field(default_factory=dict)
    #: `{run type: (settings, job) -> settings}` the run type's own sanitisation after generic normalisation.
    create_settings: Mapping[str, Callable] = field(default_factory=dict)
    #: `{run type: (data, root) -> readiness answer}` for a run type whose adapter asks its own question.
    readiness: Mapping[str, Callable] = field(default_factory=dict)
    #: `(coordinator, job) -> object` called when a run ends failed: the series stop, a cleanup the run type owns.
    on_run_failed: Callable | None = None
    #: `() -> None` callbacks that add the feature's run layout (stage directories, roles, review order, topology).
    layout: tuple = ()
    #: `(job, manifest) -> {stage name: reason}` for the stages a queued run of this type will not run.
    planned_skips: Callable | None = None


_features: list[Feature] | None = None


def installed() -> list[Feature]:
    """The features whose distributions are importable, in registration order.

    An import failure is not swallowed: a feature that is installed and broken must say so at start-up rather than
    disappear from the dashboard silently.
    """
    found = []
    for module in KNOWN:
        if importlib.util.find_spec(module) is None:
            continue
        found.append(importlib.import_module(f'{module}.feature').FEATURE)
    return found


def ensure() -> list[Feature]:
    """Load the installed features once and let them register with the shared registries."""
    global _features
    if _features is None:
        from .analysis import kinds
        from .execution import protocol, run_scripts
        from .web import sections
        _features = installed()
        for feature in _features:
            protocol.register(feature.protocols)
            kinds.register(feature.kinds)
            run_scripts.register_prefixes(feature.code_prefixes)
            for register_layout in feature.layout:
                register_layout()
            if feature.section:
                sections.register(feature.section, panels=feature.panels, blurbs=feature.blurbs,
                                  tab_ids=feature.tab_ids)
    return _features


def admission_for(run_type):
    """The admission rule a feature registered for this run type, or None.

    Called before the engine's own rule chain: a feature that owns a run type owns its payload contract too, and the
    engine has no branch that could second-guess it.
    """
    for feature in ensure():
        if run_type in feature.admission:
            return feature.admission[run_type]
    return None


def code_fingerprint_files():
    """`(name, path)` for every feature file that decides an analysis result.

    The engine walks its own `analysis/` and `models/`; a feature's code lives outside those, so without this an
    edit to a feature's metric would change no signature and the panel would keep serving the old numbers.
    """
    entries = []
    for feature in ensure():
        for label, directory in feature.code_roots:
            directory = Path(directory)
            for path in sorted(directory.rglob('*.py')):
                entries.append((f'{label}/{path.relative_to(directory).as_posix()}', path))
    return entries


def _hook(table, run_type):
    """The callable a feature registered in one of its per-run-type tables, or None."""
    for feature in ensure():
        if run_type in table(feature):
            return table(feature)[run_type]
    return None


def prepare_for(run_type):
    """The prepare-argument builder a feature registered for this run type, or None."""
    return _hook(lambda feature: feature.prepare, run_type)


def create_settings_for(run_type):
    """The settings tweak a feature registered for this run type, or None."""
    return _hook(lambda feature: feature.create_settings, run_type)


def readiness_for(run_type):
    """The readiness question a feature registered for this run type, or None."""
    return _hook(lambda feature: feature.readiness, run_type)


def planned_skips(job, manifest=None):
    """The stages the run type itself says will not run, or {} when no feature owns this run's type."""
    for feature in ensure():
        if feature.planned_skips is not None:
            answer = feature.planned_skips(job, manifest)
            if answer:
                return answer
    return {}


def run_failed(coordinator, jid):
    """Tell every feature a run ended failed, so a run type can close what it opened (an osmotic series)."""
    job = coordinator.lookup(jid)
    for feature in ensure():
        if feature.on_run_failed is not None:
            feature.on_run_failed(coordinator, job)


def register(app):
    """Register each installed feature's blueprints on this application."""
    for feature in ensure():
        for blueprint in feature.blueprints:
            app.register_blueprint(blueprint)
