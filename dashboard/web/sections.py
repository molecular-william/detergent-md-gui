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
    'validation': {
        'slug': 'detergent-validation',
        'label': 'Detergent validation',
        'blurb': "Build and check a detergent's coarse-grained model: assign beads, fit its bonded terms, combine "
                 "molecules, and compare each against its reference and against measured data.",
        # The sub-panels, in the order they appear. Each is also its URL segment:
        # `/detergent-validation/new-run`. `osmotic-pressure` is the maltose concentration series.
        'tabs': ('runs', 'new-run', 'bead-assignment', 'bond-interactions', 'combinations',
                 'mapping-validation', 'osmotic-pressure'),
    },
    'simulations': {
        'slug': 'protein-detergent',
        'label': 'Protein-detergent simulations',
        'blurb': 'Set up and run a protein with its detergent, and read the results.',
        'tabs': ('runs', 'new-run', 'complexes', 'initial-state'),
    },
}

#: The human label and glyph for each sub-panel, in one place so a section cannot render a panel whose label nobody
#: defined. The keys are the slugs used in `SECTIONS['tabs']`.
PANELS = {
    'runs': ('Runs', '☰'),
    'new-run': ('New run', '▶'),
    'bead-assignment': ('Bead Assignment', '◎'),
    'bond-interactions': ('Bond Interactions', '⇄'),
    'combinations': ('Combinations', '⧉'),
    'mapping-validation': ('Mapping Validation', '✓'),
    'osmotic-pressure': ('Osmotic Pressure', '△'),
    'complexes': ('Complexes', '⬡'),
    'initial-state': ('Initial state', '⬢'),
}

#: What each workspace is for, one line per sub-panel, for the overview to list. Kept beside the panels rather than
#: in the template so the overview cannot describe a panel that does not exist -- and so the description of a panel
#: is written where the panel is registered.
PANEL_BLURBS = {
    'runs': 'every run in this workspace, with what it draws on and what uses it',
    'new-run': 'a run, with a snapshot of the box before it starts',
    'bead-assignment': 'the CG mapping editor',
    'bond-interactions': 'fitted terms, and the cross-check against the reference',
    'combinations': 'building a system from several molecules',
    'mapping-validation': 'a mapping against its reference, and across molecules',
    'osmotic-pressure': 'the maltose concentration series against the measured values',
    'complexes': 'build and inspect a system',
    'initial-state': 'the micelle builder',
}

#: Panels that are named but not built. The overview lists them as planned rather than hiding them, so the section's
#: shape accounts for work that is coming.
PLANNED = {
    'osmotic-pressure': 'not built yet; the reader exists and is tested',
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
    'new-run': 'new',
    'bead-assignment': 'mappings',
    'bond-interactions': 'bonded',
    'combinations': 'compositions',
    'mapping-validation': 'validation',
    'osmotic-pressure': 'osmotic-pressure',
    'complexes': 'pdc',
    'initial-state': 'initial-state',
}


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


def panel_label(slug):
    """A sub-panel's display name.

    Raises rather than defaulting: a panel with no label is a registry error, and returning the slug would ship a
    page showing `new-run` where a person expects "New run".
    """
    if slug not in PANELS:
        raise KeyError(f'no label registered for panel {slug!r}')
    return PANELS[slug][0]


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


def legacy_tab_targets():
    """Where an old `/#tab` fragment should land now: `{old DOM id: '/workspace/panel'}`.

    The dashboard used to name its panels in a fragment, so every bookmark and every browser test pointed at one page
    plus `#bonded` -- and those are real links that someone made. They are answered rather than broken, by the shell,
    because a fragment is never sent to a server and only the browser can see it.

    Where an id belongs to both workspaces -- `runs` and `new-run` do -- **validation wins**. That is where the old
    page did most of its work, and a fragment-only link gives no other clue about which one was meant.
    """
    targets = {}
    for name in ('validation', 'simulations'):
        section = SECTIONS[name]
        for slug in section['tabs']:
            targets.setdefault(TAB_IDS[slug], f"/{section['slug']}/{slug}")
    return targets
