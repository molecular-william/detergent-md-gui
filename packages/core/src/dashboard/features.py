"""The dashboard's selectable halves: an installed distribution registers a feature with the engine.

The engine (`dashboard`) owns the run lifecycle, persistence, the molecule and mapping models and the shell. A feature
is its own distribution and advertises itself with an entry point in the `detergent_md.features` group; installing the
wheel is the whole act of adding one to a dashboard. The entry point resolves to a module exporting `FEATURE`, or to
the `Feature` object itself. Nothing outside the installed metadata names the features, so a checkout can carry one,
two or none, and a third party can ship another without editing this repository.

`KNOWN` is a compatibility fallback, not the registry: a checkout whose editable install predates the entry point (or
whose metadata is stale) still finds the two distributions this repository ships by import. A distribution that
advertises the entry point always wins; the two paths are merged by `Feature.name`.

Core never imports a feature. The record a distribution exports is the whole contract: the blueprints to register, the
run types and their protocol builders, the analysis kinds it owns, and the workspace it contributes to the shell.
Everything is added to registries that already exist and are imported by their consumers as dicts/objects, so
registering *mutates* them rather than rebinding a name a route has already captured.

An installed feature that fails to import is a start-up error, not a silent absence: a dashboard missing a panel is
worse than one that says why.
"""
from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

#: The entry-point group a feature distribution advertises:
#:     [project.entry-points."detergent_md.features"]
#:     validation = "detergent_validation.feature"
#: The name on the left is the distribution's own label; the record's `Feature.name` is what the engine registers.
ENTRY_POINT_GROUP = 'detergent_md.features'

#: Compatibility fallback, not the registry: modules looked up by import when their metadata advertises no entry point
#: (an editable checkout older than this seam). A feature is otherwise discovered from installed metadata alone.
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
    #: `(run_dir) -> [moleculetype dict]` the structure writer needs for a feature's own protein build.
    protein_topologies: Callable | None = None
    #: `{kind: (coordinator, body) -> payload}` for a kind whose queue route validates and derives its body.
    kind_payload: Mapping[str, Callable] = field(default_factory=dict)
    #: Registration order: the shell opens on the first workspace registered, so lower runs first; ties break by name.
    priority: int = 100
    #: The feature's browser assets. `templates` joins the Jinja search path (so `panels/<id>.html` can live here),
    #: `static` is served at `/feature-assets/<name>/...` (`url_for('feature_asset', ...)`), and `styles` are the sheets the shell links before its own
    #: panel sheets. A feature with no browser code leaves all three empty.
    templates: Path | None = None
    static: Path | None = None
    styles: tuple = ()
    #: `{panel DOM id: (path under static, factory export)}` -- the panels the shell mounts from this feature's own ES
    #: modules. The shell emits the map to the browser and the boot code imports exactly what is installed.
    panel_modules: Mapping[str, tuple[str, str]] = field(default_factory=dict)


_features: list[Feature] | None = None


def _entry_points():
    """The feature entry points installed in this interpreter.

    One indirection, so a test can hand the seam a fabricated distribution without installing one, and so the
    compatibility fallback in `installed` can share the same view of what metadata says.
    """
    from importlib import metadata
    return list(metadata.entry_points(group=ENTRY_POINT_GROUP))


def _feature_of(entry):
    """Load one entry point into a `Feature`, naming the entry point in every failure."""
    try:
        loaded = entry.load()
    except Exception as error:
        raise RuntimeError(f'feature {entry.name!r} is installed but could not be loaded: {error}') from error
    feature = getattr(loaded, 'FEATURE', loaded)
    if not isinstance(feature, Feature):
        raise TypeError(f'entry point {ENTRY_POINT_GROUP}.{entry.name} must resolve to a Feature or a module '
                        f'exporting FEATURE, not {type(feature).__name__}')
    return feature


def installed() -> list[Feature]:
    """The installed features, in registration order: metadata first, then the compatibility fallback.

    Two distributions claiming one `Feature.name` is a registry error, not a merge, because the name decides the
    workspace, the run types and the analysis kinds; the message names the collision rather than letting the second
    silently replace the first.
    """
    found: dict[str, Feature] = {}
    for entry in _entry_points():
        feature = _feature_of(entry)
        if feature.name in found:
            raise ValueError(f'two installed features are named {feature.name!r}; give one a different name')
        found[feature.name] = feature
    for module in KNOWN:
        if importlib.util.find_spec(module) is None:
            continue
        feature = importlib.import_module(f'{module}.feature').FEATURE
        found.setdefault(feature.name, feature)
    return sorted(found.values(), key=lambda feature: (feature.priority, feature.name))


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


def template_dirs():
    """The installed features' template directories, in registration order."""
    return [feature.templates for feature in ensure() if feature.templates is not None]


def static_dirs():
    """The installed features' browser-asset directories, by feature name."""
    return {feature.name: feature.static for feature in ensure() if feature.static is not None}


def browser_panels():
    """`{panel DOM id: (feature name, path under its static, factory export)}` for every installed panel module."""
    found = {}
    for feature in ensure():
        for panel, (path, factory) in feature.panel_modules.items():
            found[panel] = (feature.name, path, factory)
    return found


def browser_styles():
    """`[(feature name, stylesheet under its static)]` the shell links, in registration order."""
    return [(feature.name, name) for feature in ensure() for name in feature.styles]


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


def kind_payload_for(kind):
    """The body contract a feature registered for one analysis kind, or None."""
    for feature in ensure():
        if kind in feature.kind_payload:
            return feature.kind_payload[kind]
    return None


def protein_topologies(run_dir):
    """The protein moleculetypes a feature's run type writes, or [] when none owns this run."""
    for feature in ensure():
        if feature.protein_topologies is not None:
            topologies = feature.protein_topologies(run_dir)
            if topologies:
                return topologies
    return []


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
