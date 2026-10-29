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
        from .execution import protocol
        from .web import sections
        _features = installed()
        for feature in _features:
            protocol.register(feature.protocols)
            kinds.register(feature.kinds)
            if feature.section:
                sections.register(feature.section, panels=feature.panels, blurbs=feature.blurbs,
                                  tab_ids=feature.tab_ids)
    return _features


def register(app):
    """Register each installed feature's blueprints on this application."""
    for feature in ensure():
        for blueprint in feature.blueprints:
            app.register_blueprint(blueprint)
