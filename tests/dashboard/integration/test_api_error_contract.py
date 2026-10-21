"""Every failure under `/api` answers JSON; a page outside it keeps the browser's own answer.

Four codes were registered one at a time (400, 404, 409, 413), so a route that raised `abort(405)` -- by being
asked with the wrong method -- answered Werkzeug's HTML into a client that parses JSON. `POST /api/storage` is
that case on a real path, and it is what the audit found by calling it.
"""
import json


def test_a_wrong_method_on_a_real_api_path_answers_json(dashboard):
    response = dashboard.client.post('/api/storage')

    assert response.status_code == 405
    assert response.content_type.startswith('application/json')
    assert json.loads(response.data)['error'], 'the body says what was wrong, not a stack of HTML'


def test_an_unknown_api_path_answers_json(dashboard):
    response = dashboard.client.get('/api/nope')

    assert response.status_code == 404
    assert response.content_type.startswith('application/json')


def test_a_page_outside_the_api_keeps_the_servers_own_answer(dashboard):
    """The rule is about the client, not about the app: a browser asking for a page gets a page."""
    response = dashboard.client.get('/nope-not-a-page')

    assert response.status_code == 404
    assert b'<!doctype html>' in response.data.lower()
