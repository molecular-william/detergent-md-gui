"""One writer per rendered host, and the window handles are test hooks.

Phase 5 of the audit's plan. The audit found the run card's `.analysis-tasks` written by two modules that do not know
about each other: `runs.js` fills it with one row per analysis task, and `runs-diagnostics.js` -- which `runs.js`
itself calls, on the same refresh -- replaces its children with the distance-diagnostics guidance box. Whichever
writes second erases the other, and which one that is depends on whether the diagnostics have been fetched yet, so a
card's contents are not a function of its run.

The scanner below is the durable half of the fix: it reports every selector mutated by more than one module, so the
next two-writer host is a failing test rather than a panel that empties itself when a fetch lands. It is validated
against a synthetic pair *inside* the test, because a scanner that reports nothing and a codebase with nothing to
report look identical from the outside -- and the first version of this file is expected to fail on the case the
audit named.
"""
import re
from collections import defaultdict

from tests.harness.support import PACKAGE, PROJECT_ROOT

REPO = PROJECT_ROOT
STATIC = PACKAGE / 'web/static/js'

#: `const host = $('.x', card)` / `$$('#x')` -- the selector text is what identifies the host.
BIND = re.compile(r"""(?:const|let|var)\s+(\w+)\s*=\s*\$\$?\(\s*(['"`][^'"`]+['"`])""")
#: A call that replaces or appends a host's children.
CHILD_CALL = re.compile(r"""(\w+)\s*\.\s*(replaceChildren|append|appendChild|insertAdjacentHTML|prepend)\s*\(""")
#: An assignment that replaces a host's content.
CONTENT_SET = re.compile(r"""(\w+)\s*\.\s*(innerHTML|textContent)\s*=\s*[^=]""")
#: A write straight off a fresh selector, with no binding to follow.
INLINE_WRITE = re.compile(
    r"""\$\$?\(\s*(['"`][^'"`]+['"`])\s*\)\s*\.\s*(?:replaceChildren|append|appendChild|innerHTML|textContent|insertAdjacentHTML)""")


def writers_of(sources):
    """`{selector: {module}}` for every selector a module mutates, over `{module: source}`."""
    writers = defaultdict(set)
    for module, text in sources.items():
        bound = dict(BIND.findall(text))
        for line in text.splitlines():
            for selector in INLINE_WRITE.findall(line):
                writers[selector].add(module)
            for name, _ in CONTENT_SET.findall(line):
                if name in bound:
                    writers[bound[name]].add(module)
            for name, _ in CHILD_CALL.findall(line):
                if name in bound:
                    writers[bound[name]].add(module)
    return writers


def _static_roots():
    """The engine's browser modules and the installed features' own: the one-writer invariant spans both trees."""
    from dashboard import features

    roots = [STATIC]
    for directory in features.static_dirs().values():
        scripts = directory / 'js'
        if scripts.is_dir():
            roots.append(scripts)
    return roots


def module_sources():
    return {path.relative_to(REPO).as_posix(): path.read_text()
            for root in _static_roots() for path in sorted(root.rglob('*.js'))}


def test_the_scanner_reports_a_host_two_modules_write():
    """The instrument check, in the test rather than in a comment: a scanner that cannot see the known case would
    report an empty result and be believed.

    The scan keys on the selector *text*, so two writers spelling the host the same way is what it catches. A host
    named by a class in one module and an id in another is two keys here rather than one -- a limitation, not a
    claim, and the second assertion pins it so nobody reads this as broader than it is.
    """
    seen = writers_of({'a.js': "const host = $('.shared-host'); host.replaceChildren();",
                       'b.js': "const other = $('.shared-host', card); other.append(row);"})
    assert seen.get("'.shared-host'", set()) == {'a.js', 'b.js'}, seen
    spelled_differently = writers_of({'a.js': "const host = $('.shared-host'); host.replaceChildren();",
                                      'b.js': "const other = $('#shared-host'); other.append(row);"})
    assert len(spelled_differently) == 2, 'the two spellings are two hosts to this scan, deliberately'


def test_no_host_is_written_by_two_modules():
    """Every host in a rendered card has one owner. The owner is named where it is bound.

    Two shapes this does not model, stated rather than implied: a host handed to a class which then writes it
    (`.analysis-plots` is passed to `new RunFigureViewer(...)`, and the viewer owns its contents), and a host whose
    two writers spell the selector differently. Both are single-writer by inspection; neither is caught here.
    """
    writers = writers_of(module_sources())
    shared = {selector: sorted(modules) for selector, modules in writers.items() if len(modules) > 1}
    assert not shared, 'written by more than one module: ' + '; '.join(
        f'{selector} <- {modules}' for selector, modules in sorted(shared.items()))


def test_the_window_handles_are_read_by_no_module():
    """A handle published for tests must not become load-bearing for the application.

    `main.js` puts five handles on `window` so the browser tier and a person at a console can reach them. None of them
    is read back by any module -- the panels import what they need -- and that is the property to keep: a module that
    starts reading `window.refreshJobs` has quietly made a test hook part of the application, and the hook can no
    longer be moved without breaking the page.
    """
    published = re.search(r"""const hooks = \{(.*?)\n  \};""", (STATIC / 'main.js').read_text(), re.S)
    assert published, 'the window handles are no longer published as one object; update this test'
    names = re.findall(r"""(?:^|,)\s*(\w+)\s*:""", published.group(1))
    assert names, 'no handles parsed out of main.js'
    readers = set()
    for module, text in module_sources().items():
        if module.endswith('main.js'):
            continue
        readers.update(re.findall(r"""window\.(\w+)""", text))
    assert not (set(names) & readers), (
        'a module reads a handle that exists for tests: ' + ', '.join(sorted(set(names) & readers)))
