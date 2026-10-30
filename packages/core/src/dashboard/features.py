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

An installed feature that cannot load is skipped and recorded, not fatal: `DASHBOARD_FEATURES` (or the launcher's
`--features`) narrows what is loaded, a feature outside that list is never imported, and one inside it that fails is
logged with its reason and left out. A requested name that matches nothing is an error -- a typo must not read as a
feature that is simply not installed.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
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

#: What the last `installed()` call skipped, as `[(name, message)]`: a feature that is installed but could not load is
#: absent from the dashboard, and this is what lets the reason be reported instead of the absence being silent.
_failures: list[tuple[str, str]] = []

_log = logging.getLogger(__name__)


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
    #: ES modules under `static` the shell imports for their side effects: they register extensions onto a shared
    #: engine panel (New run, Run view) by importing that module and calling its `register...Extension`. Imported after
    #: the engine modules and before any panel mounts, and only when this distribution is installed.
    extension_modules: tuple = ()
    #: `{section id: (title, what it must show, units)}` for the evidence sections a feature's report is required to
    #: carry. A section is report vocabulary, not an analysis kind; the engine merges the installed features' tables.
    evidence_sections: Mapping[str, tuple] = field(default_factory=dict)
    #: `{profile name: tuple of section ids}` for a molecule evidence profile the feature owns. Core keeps the AA/CG
    #: profiles it always had; a feature adds the ones only its molecules use.
    molecule_profiles: Mapping[str, tuple] = field(default_factory=dict)
    #: `{run type: tuple of legacy stage directory names}` a feature's runs may hold at the run root. The run-layout
    #: migration reads this to recognise a pre-numbering tree; the engine does not keep a list of a feature's stages.
    legacy_stages: Mapping[str, tuple] = field(default_factory=dict)


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


def selected() -> list[str]:
    """The feature names `DASHBOARD_FEATURES` asks for; an empty list means every installed one."""
    return [name.strip() for name in (os.environ.get('DASHBOARD_FEATURES') or '').split(',') if name.strip()]


def failures() -> list[tuple[str, str]]:
    """The features the last discovery skipped, and why."""
    return list(_failures)


def _skip(name, error) -> None:
    _failures.append((name, str(error)))
    _log.warning('feature %r is installed but could not be loaded: %s', name, error)


def installed() -> list[Feature]:
    """The installed features, in registration order: metadata first, then the compatibility fallback.

    `DASHBOARD_FEATURES` narrows the list by entry-point name (which the shipped features keep equal to
    `Feature.name`); a feature outside it is not imported at all. One that fails to load is skipped and recorded by
    `failures()` rather than stopping the dashboard. Two distributions claiming one `Feature.name` is still a registry
    error, not a merge, because the name decides the workspace, the run types and the analysis kinds.
    """
    wanted = selected()
    _failures.clear()
    found: dict[str, Feature] = {}
    for entry in _entry_points():
        if wanted and entry.name not in wanted:
            continue
        try:
            feature = _feature_of(entry)
        except Exception as error:  # noqa: BLE001 - every load failure is a skipped feature, not a dead dashboard
            _skip(entry.name, error)
            continue
        if feature.name in found:
            raise ValueError(f'two installed features are named {feature.name!r}; give one a different name')
        found[feature.name] = feature
    # The fallback is for a checkout whose editable metadata predates the entry point. It is tried only when a
    # requested name is still missing: an unselected module is never imported, and its failure cannot fail this one.
    if not wanted or not set(wanted) <= set(found):
        for module in KNOWN:
            if importlib.util.find_spec(module) is None:
                continue
            try:
                feature = importlib.import_module(f'{module}.feature').FEATURE
            except Exception as error:  # noqa: BLE001 - same rule as an entry point
                _skip(module, error)
                continue
            found.setdefault(feature.name, feature)
    unknown = [name for name in wanted if name not in found]
    if unknown:
        raise ValueError(f'DASHBOARD_FEATURES names {unknown}, which no installed feature provides; '
                         f'the installed features are {sorted(found)}')
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
                                  tab_ids=feature.tab_ids, owner=feature.name)
    return _features


def template_dirs():
    """The installed features' template directories, in registration order."""
    return [feature.templates for feature in ensure() if feature.templates is not None]


def static_dirs():
    """The installed features' browser-asset directories, by feature name."""
    return {feature.name: feature.static for feature in ensure() if feature.static is not None}


def legacy_stages(run_type=None):
    """The legacy stage directory names a feature registered for a run type (or all, merged)."""
    merged = {}
    for feature in ensure():
        for name, stages in feature.legacy_stages.items():
            if name in merged:
                raise ValueError(f'legacy stage table {name!r} is claimed by two features')
            merged[name] = tuple(stages)
    return merged if run_type is None else merged.get(run_type, ())


def browser_extensions():
    """`[(feature name, module under its static)]` the shell imports for their side effects, in registration order."""
    return [(feature.name, module) for feature in ensure() for module in feature.extension_modules]


def evidence_sections():
    """The evidence-section vocabulary, merged across the installed features; a duplicate title is an error."""
    merged = {}
    for feature in ensure():
        for name, text in feature.evidence_sections.items():
            if name in merged:
                raise ValueError(f'evidence section {name!r} is claimed by two features')
            merged[name] = text
    return merged


def molecule_profiles():
    """The molecule evidence profiles the installed features add, merged; a duplicate name is an error."""
    merged = {}
    for feature in ensure():
        for name, profile in feature.molecule_profiles.items():
            if name in merged:
                raise ValueError(f'molecule profile {name!r} is claimed by two features')
            merged[name] = profile
    return merged


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
