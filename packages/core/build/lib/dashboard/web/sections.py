"""Which panels each workspace of the dashboard owns.

The dashboard has two workspaces -- detergent validation and protein-detergent simulations -- and this module is the
single record of what goes where. It is deliberately not in the template: the template renders a section, and a test
can assert the split without reading HTML.

Nothing here knows about layout. Whether the two workspaces are entered from an overview or shown side by side, and
whether they are two pages or one, this record is the same -- which is why it is the first thing the refactor builds.
"""

#: The two workspaces. `slug` is the URL segment and the `data-tab` prefix; `label` is the human name. The two are
#: not derived from each other on purpose: the label "protein-detergent simulations" is longer than its slug
#: `protein-detergent`, and `new-run` is a better URL than a panel called `new`.
SECTIONS = {
}

#: The human label and glyph for each sub-panel, in one place so a section cannot render a panel whose label nobody
#: defined. The keys are the slugs used in `SECTIONS['tabs']`.
PANELS = {
    'runs': ('Runs', '☰'),
    'run-view': ('Run view', '⬓'),
    'new-run': ('New run', '▶'),
    'initial-state': ('Initial state', '⬢'),
}

#: What each workspace is for, one line per sub-panel, for the overview to list. Kept beside the panels rather than
#: in the template so the overview cannot describe a panel that does not exist -- and so the description of a panel
#: is written where the panel is registered.
PANEL_BLURBS = {
    'runs': 'every run in this workspace, with what it draws on and what uses it',
    'run-view': 'one run, its structures, its frames and its figures',
    'new-run': 'a run, with a snapshot of the box before it starts',
    'initial-state': 'the micelle builder',
}

#: Panels that are named but not built. The overview lists them as planned rather than hiding them, so the section's
#: shape accounts for work that is coming.
PLANNED = {
    'initial-state': 'the micelle builder is paused, and is not a validated model',
    'detergent-design': 'not built yet; named so the shape accounts for it',
}


#: The DOM id each panel's section already carries. A slug is what a URL says; this is what the template and the
#: panel JavaScript have always called it, and the two are kept deliberately separate.
#:
#: The reason is risk, not tidiness. `tabs.js` resolves a panel with `$('#' + tab.dataset.tab)`, so an id that no
#: longer matches is a JavaScript failure -- and no Python test sees JavaScript at all. Renaming seven ids across
#: three thousand lines of panel code to make the DOM match the URLs would trade a URL nobody reads twice for a class
#: of failure nothing in the suite could catch. The URLs are the slugs; the DOM keeps its names.
TAB_IDS = {
    'runs': 'runs',
    'run-view': 'runview',
    'new-run': 'new',
    'initial-state': 'initial-state',
}


def register(section, *, panels=(), blurbs=(), tab_ids=()) -> None:
    """Add one feature's workspace and panels to the registry.

    The four dicts below are the objects routes and the template read, and `routes/runs.py` imported them by name, so
    a feature is added by **mutating** them: rebinding a name would leave every earlier importer looking at the old
    registry. A duplicate name raises, because two features claiming one workspace is a registry error, not a merge.
    """
    name, record = section
    if name in SECTIONS:
        raise ValueError(f'workspace {name!r} is already registered')
    SECTIONS[name] = record
    PANELS.update(panels)
    PANEL_BLURBS.update(blurbs)
    TAB_IDS.update(tab_ids)


def home():
    """The workspace the front door renders: the first registered one.

    Registration order is the answer: the engine contributes the shell, then features register in `features.KNOWN`
    order, so a full install opens on validation and a minimal one opens on its only workspace. Naming a workspace
    here would keep one feature's name in the engine.
    """
    return next(iter(SECTIONS.values()))


def visible(section):
    """The section with `DASHBOARD_TABS` honoured: the panels this instance shows, in the registry's order.

    A deployment may be narrower than the distribution it installed: the validation-only dashboard shows six of the
    eight panels its feature owns. The filter is an environment setting rather than a copy of the registry, so the
    installed feature still describes every panel it can render and a missing name is a start-up error, not a page
    that silently lost a tab. An unset variable, or an empty one, means every panel.
    """
    import os
    wanted = [slug for slug in (os.environ.get('DASHBOARD_TABS') or '').split(',') if slug.strip()]
    if not wanted:
        return section
    unknown = [slug for slug in wanted if slug not in section['tabs']]
    if unknown:
        raise ValueError(f'DASHBOARD_TABS names panels {unknown} that {section["label"]} does not have')
    return {**section, 'tabs': tuple(slug for slug in section['tabs'] if slug in wanted)}


def section_for(name):
    """The section `name`, or `None`.

    A route turns `None` into a 404 rather than choosing a section for the caller: the whole point of naming a
    workspace in a URL is that the name is checked, and a silent default is how a wrong guess becomes a wrong page.
    """
    return SECTIONS.get(name)


def section_by_slug(slug):
    """The section whose URL segment is `slug`, or `None`.

    The lookup by slug is separate from the lookup by name because they are different vocabularies: the overview
    links with slugs, the registry is keyed by short names, and only this function knows the mapping between them.
    """
    for name, section in SECTIONS.items():
        if section['slug'] == slug:
            return section
    return None


def tabs_for(name):
    """The sub-panels a section renders, in the order it renders them."""
    section = SECTIONS.get(name)
    return tuple(section['tabs']) if section else ()


def panel_label(slug, section=None):
    """A sub-panel's display name in one workspace, or its rail label when no workspace is named.

    Without `section` this is the rail's own word for the panel: short, and the same in both workspaces -- both
    call this panel "New run". With a workspace's **slug** it is the heading the panel carries *there*, which is
    where a workspace says what it actually runs: "Single Molecule Simulations" under validation against
    "Protein-Detergent Simulations" under simulations. Headings are registered per workspace because the registry
    was keyed by panel slug alone, so `simulations.new-run` had no way to differ from `validation.new-run`.

    Raises rather than defaulting: a panel with no label is a registry error, and returning the slug would ship a
    page showing `new-run` where a person expects "New run". A workspace this registry does not have also raises,
    for the same reason a route 404s on an unknown slug -- a heading resolved from an unknown workspace would be a
    guess.
    """
    if slug not in PANELS:
        raise KeyError(f'no label registered for panel {slug!r}')
    if section is None:
        return PANELS[slug][0]
    for name, record in SECTIONS.items():
        if section in (name, record['slug']):
            return record.get('panel_labels', {}).get(slug) or PANELS[slug][0]
    raise KeyError(f'no workspace has the slug or name {section!r}')


def panel_glyph(slug):
    """A sub-panel's rail glyph, or an empty string for a panel registered without one."""
    return PANELS.get(slug, ('', ''))[1]


def tab_id(slug):
    """The DOM id a panel's section carries, for the template to write and the JavaScript to resolve.

    Raises rather than defaulting, for the same reason `panel_label` does: a panel whose id is guessed renders a tab
    that toggles nothing at all, and nothing would report it.
    """
    if slug not in TAB_IDS:
        raise KeyError(f'no DOM id registered for panel {slug!r}')
    return TAB_IDS[slug]


def run_types_for(section):
    """The run types a workspace's Run view offers, in the order the panel lists them.

    The panel asks `/api/jobs` for each of these by name, so this is what decides which runs a reader can reach
    from a workspace -- and why it is registered per workspace rather than written in the panel's JavaScript: a
    second copy of the list is a second place for a run type to go missing. A workspace this registry does not have
    raises, for the same reason a route 404s on an unknown slug: a scope resolved from an unknown workspace would
    be a guess. A workspace registered without a scope answers `()`, which the panel renders as "no run type in
    this workspace" rather than as every run of every kind.
    """
    for name, record in SECTIONS.items():
        if section in (name, record['slug']):
            return tuple(record.get('run_types', ()))
    raise KeyError(f'no workspace has the slug or name {section!r}')


def legacy_tab_targets():
    """Where an old `/#tab` fragment should land now: `{old DOM id: '/workspace/panel'}`.

    The dashboard used to name its panels in a fragment, so every bookmark and every browser test pointed at one page
    plus `#bonded` -- and those are real links that someone made. They are answered rather than broken, by the shell,
    because a fragment is never sent to a server and only the browser can see it.

    Where an id belongs to both workspaces -- `runs` and `new-run` do -- **validation wins**. That is where the old
    page did most of its work, and a fragment-only link gives no other clue about which one was meant.
    """
    targets = {}
    for section in SECTIONS.values():
        for slug in section['tabs']:
            targets.setdefault(TAB_IDS[slug], f"/{section['slug']}/{slug}")
    return targets
