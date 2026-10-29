"""The DOM id contract, read in both directions.

Phase 4 of the audit's plan, and the highest-risk phase here: nine modules resolve 212 id lookups against a template
that carries 162 ids, and a missed one throws on the module's first line and kills every later statement in it. Four
of the five audit defects live in this contract. So does D1, in its second direction -- a panel registered in a
section and mounted nowhere is a tab that resolves to no element, which hides every panel and leaves a blank
workspace.

The channels that count as *addressing* an id are enumerated rather than assumed, because a scan that counts only
`$('#id')` calls reads every labelled heading and every styled container as dead:

- a JavaScript lookup, or a selector built by concatenating a rendered prefix (`$('#composition-plot-' + key)`);
- a CSS selector, which is how a container gets its layout;
- a browser test's selector, which is how a control is exercised;
- an attribute whose value *is* an id: `aria-labelledby`, `aria-controls`, `for`, `data-tab`, `href="#..."`;
- the panel registry, which names each panel's section.

Reading the *selector* rather than a bare `'#id'` is load-bearing and was wrong here once: the first version of this
scan matched only `'#subtabs'`, so it read `'#subtabs .subtab[aria-selected=true]'` -- the selector this tier's own
navigation test uses -- as naming nothing, and an id a test depends on was deleted on the strength of it. Every
selector string is scanned for `#`-tokens now.

What this deliberately does not do is rewrite the 212 lookups. They resolve, and rewriting them buys naming tidiness
at the cost of the exact churn the plan exists to avoid; these tests are what make leaving them alone safe.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

from dashboard.web import sections

from tests.dashboard.support import PACKAGE

REPO = Path(__file__).resolve().parents[3]
WEB = PACKAGE / 'web'
STATIC = WEB / 'static'
BROWSER_TESTS = REPO / 'tests/dashboard/browser'

#: A JavaScript call whose argument is a selector, and a `getElementById` whose argument *is* an id.
LOOKUP_CALLS = (re.compile(r"""[$]\s*\(\s*['"]([^'"]*)['"]"""),
                re.compile(r"""querySelector(?:All)?\s*\(\s*['"]([^'"]*)['"]"""))
BY_ID_CALLS = re.compile(r"""getElementById\s*\(\s*['"]([A-Za-z0-9_-]+)['"]""")
#: Any quoted string, which is where a test keeps its selector.
QUOTED = re.compile(r"""['"]([^'"]*)['"]""")
#: The ids inside a selector, wherever they sit in it.
ID_TOKEN = re.compile(r"""#([A-Za-z][A-Za-z0-9_-]*)""")
#: A selector whose id is built: `'#prefix-' + key` or `` `#prefix-${key}` ``. The literal is a prefix of ids the
#: template renders, which is what makes it resolvable rather than missing.
BUILT_SELECTOR = re.compile(r"""['"`]#([A-Za-z0-9_-]+-)['"`]?\s*[+]|#([A-Za-z0-9_-]+-)\$\{""")
ID_ATTRIBUTES = ('aria-labelledby', 'aria-describedby', 'aria-controls', 'aria-owns', 'aria-activedescendant',
                 'for', 'form', 'headers', 'list')


def ids_in(selector):
    return set(ID_TOKEN.findall(selector))


class Dom(HTMLParser):
    """Every element the rendered page carries, by id, and which of them are panels."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.panels = set()
        self.references = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        name = attributes.get('id')
        if name:
            self.ids.add(name)
            if 'panel' in (attributes.get('class') or '').split():
                self.panels.add(name)
        for attribute in ID_ATTRIBUTES:
            value = attributes.get(attribute)
            if value:
                self.references.update(value.split())
        href = attributes.get('href') or ''
        if href.startswith('#') and len(href) > 1:
            self.references.add(href[1:])


def rendered(dashboard):
    """The page as the server renders it -- not the template as it is written, so a conditional is accounted for."""
    with dashboard.client as client:
        page = Dom()
        page.feed(client.get('/').get_data(as_text=True))
    return page


def module_lookups():
    """Every id a module names in a selector, and every prefix it builds one from."""
    named, prefixes = set(), set()
    for path in sorted(STATIC.rglob('*.js')):
        text = path.read_text()
        for pattern in LOOKUP_CALLS:
            for selector in pattern.findall(text):
                named.update(ids_in(selector))
        named.update(BY_ID_CALLS.findall(text))
        for literal, interpolated in BUILT_SELECTOR.findall(text):
            prefixes.add(literal or interpolated)
    return named, prefixes


def browser_selectors():
    """The ids the browser tier selects, read out of every quoted string in it."""
    selected = set()
    for path in sorted(BROWSER_TESTS.rglob('*.py')):
        selected.update(ids_in(path.read_text()))
    return selected


def test_every_id_a_module_looks_up_is_rendered(dashboard):
    """A lookup with no element throws where it stands, so this is the direction that breaks a page outright."""
    page = rendered(dashboard)
    named, prefixes = module_lookups()
    missing = sorted(name for name in named
                     if name not in page.ids and not any(other.startswith(name) for other in page.ids | prefixes))
    assert not missing, f'looked up and rendered nowhere: {missing}'


def test_every_rendered_id_is_addressed_by_something(dashboard):
    """The other direction: an id nothing reads is decoration, and this is what says so by name."""
    page = rendered(dashboard)
    named, _ = module_lookups()
    styled = {name for path in STATIC.rglob('*.css')
              for name in re.findall(r"""#([A-Za-z][A-Za-z0-9_-]*)""", path.read_text())}
    addressed = named | styled | browser_selectors() | page.references | set(sections.TAB_IDS.values())
    unaddressed = sorted(page.ids - addressed)
    assert not unaddressed, (
        'rendered and read by nothing -- remove the id, or address it: ' + ', '.join(unaddressed))


def test_every_registered_panel_has_a_section_and_every_section_a_panel(dashboard):
    """D1's class, from the registry's side: a tab whose panel is not in the page blanks the workspace.

    A slug reaches the page through `TAB_IDS`, which names the DOM id its section already carries -- deliberately not
    the slug itself, because seven section ids predate the URL scheme. So the two must be compared through that map,
    and both ways: a tab whose section is absent, and a section no tab can reach.
    """
    page = rendered(dashboard)
    from_tabs = {sections.TAB_IDS[slug] for section in sections.SECTIONS.values() for slug in section['tabs']}
    assert from_tabs <= page.panels, f'tabs whose panel is not rendered: {sorted(from_tabs - page.panels)}'
    assert page.panels <= from_tabs, f'rendered panels no section offers: {sorted(page.panels - from_tabs)}'


def test_a_slug_that_is_not_built_has_no_tab(dashboard):
    """The other half of D1: a panel that is planned is *labelled* and must not be tabbed.

    `PLANNED` is how a slug is registered before its section exists -- it can carry a label and a DOM id so the shape
    accounts for it, and it must not appear in a section's tabs, because that is the line between "registered" and
    "a live tab pointing at nothing".
    """
    tabbed = {slug for section in sections.SECTIONS.values() for slug in section['tabs']}
    for slug, reason in sections.PLANNED.items():
        assert slug not in tabbed, f'{slug} is planned ({reason}) and must not be a live tab'
    assert set(sections.PANELS) <= tabbed | set(sections.PLANNED), 'a labelled panel is neither built nor planned'
    assert set(sections.TAB_IDS) <= tabbed | set(sections.PLANNED), 'an id is named for no panel at all'
