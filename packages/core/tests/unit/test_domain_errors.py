"""The lifecycle raises domain errors; the web layer decides status codes.

A guard that resolves imports and calls rather than matching text: the point is that
these modules cannot name an HTTP status code at all, so a failure has to be described
in the vocabulary of the run lifecycle and mapped once, in the web layer.
"""
import ast

import pytest
from dashboard.execution.coordination import errors
from dashboard.web.routes import common

from tests.harness.support import PACKAGE

LIFECYCLE = PACKAGE / 'execution/coordination'
MODULES = ('coordinator.py', 'worker.py', 'analysis_coordinator.py', 'admission.py')


def imported_names(path):
    """Top-level module names this file imports, absolute and relative alike."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split('.')[0])
        elif isinstance(node, ast.ImportFrom) and node.level and node.names:
            names.update(alias.name.split('.')[0] for alias in node.names)
    return names


def called_names(path):
    """Names called as plain functions in this file."""
    return {node.func.id for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


@pytest.mark.parametrize('name', MODULES)
def test_the_lifecycle_does_not_import_flask(name):
    assert 'flask' not in imported_names(LIFECYCLE / name)


@pytest.mark.parametrize('name', MODULES)
def test_the_lifecycle_does_not_abort_a_request(name):
    assert 'abort' not in called_names(LIFECYCLE / name), name


def test_the_status_map_covers_every_domain_error():
    for error in errors.ALL:
        assert error in common.STATUS_CODES, error.__name__
        assert isinstance(common.STATUS_CODES[error], int)


def test_the_status_codes_are_the_ones_the_surface_returned_before():
    """Domain errors must not renumber anything: the browser's stale-source branch and
    the API tests read these codes."""
    assert common.STATUS_CODES == {
        errors.InvalidRequest: 400, errors.InvalidRunId: 404, errors.RunNotFound: 404,
        errors.RunBusy: 409, errors.RunConflict: 409, errors.CapacityFull: 409,
        errors.DependencyRetained: 409, errors.SourceUnavailable: 409,
    }


def test_a_domain_error_is_not_a_value_error():
    """Otherwise the app's ValueError handler would answer 400 for every conflict."""
    assert not issubclass(errors.RunBusy, ValueError)
    assert issubclass(errors.RunBusy, errors.RunError)
    assert issubclass(errors.RunError, Exception)


def test_the_app_maps_every_domain_error(dashboard):
    """The application under test is the one the test built, not one bound to the live workspace."""
    # {blueprint: {code-or-None: {exception class: handler}}}; None is the app itself.
    handlers = dashboard.app.error_handler_spec[None][None] or {}
    for error in errors.ALL:
        assert error in handlers, error.__name__
