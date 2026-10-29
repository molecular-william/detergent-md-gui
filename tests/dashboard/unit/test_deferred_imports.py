"""Every deferred import in `dashboard.analysis` resolves, and every name it asks for exists.

These modules import MDAnalysis, matplotlib and the sugar model inside function bodies, which keeps the
dashboard's start-up cheap but means an import is only exercised on the code path that reaches it. A test that
takes another path says nothing about it: `consistency.aa_bead_means` carried
`from ..models.sugars import coordinates` — one dot short — for as long as it existed, and it raised
`ModuleNotFoundError: No module named 'dashboard.analysis.models'` the first time the published comparison
called it, after a real run had been queued against it. Resolving every deferred import is cheap and catches
the whole class: a wrong module, a wrong level, or a name the target module does not export.
"""
import ast
import importlib
import importlib.util

import pytest

from tests.dashboard.support import PACKAGE as PACKAGE_ROOT

PACKAGE = 'dashboard.analysis'
ROOT = PACKAGE_ROOT / 'analysis'


def package_name(path):
    """The package a module's relative imports resolve against: its own directory.

    `importlib.util.resolve_name` takes a *package*, not a module: a module's `.` is its package, `..` is that
    package's parent. Handing it the module's own name shifts every level by one and reports working imports as
    broken.
    """
    relative = path.relative_to(ROOT).with_suffix('')
    parts = [part for part in relative.parts[:-1] if part != '__init__']
    return '.'.join([PACKAGE, *parts])


def deferred_imports(path):
    """`(module to import, names to find, line)` for every relative import in one file."""
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        target = importlib.util.resolve_name('.' * node.level + (node.module or ''), package_name(path))
        names = [alias.name for alias in node.names if alias.name != '*']
        found.append((target, names, node.lineno))
    return found


FILES = sorted(path for path in ROOT.rglob('*.py') if '__pycache__' not in path.parts)


def test_the_analysis_package_has_deferred_imports_to_check():
    assert len(FILES) > 5, 'this test is only meaningful over the package it walks'
    assert sum(len(deferred_imports(path)) for path in FILES) > 0


@pytest.mark.parametrize('path', FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_every_relative_import_in_the_module_resolves(path):
    for target, names, line in deferred_imports(path):
        try:
            module = importlib.import_module(target)
        except ModuleNotFoundError as error:
            raise AssertionError(f'{path.name}:{line} imports {target!r}, which does not exist: {error}') from error
        for name in names:
            if hasattr(module, name):
                continue
            # `from package import name` reaches a submodule when the package has no such attribute, which
            # is what Python itself does; the name still has to exist one way or the other.
            try:
                importlib.import_module(f'{target}.{name}')
            except ModuleNotFoundError as error:
                raise AssertionError(f'{path.name}:{line} imports {name!r} from {target!r}, which has '
                                     f'neither an attribute nor a submodule by that name: {error}') from error
