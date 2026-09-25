"""One request-body parser for every route.

The routes each parsed their own body: `request.get_json() or {}` in five places, a silent
parse plus an isinstance check in three, and a double parse in the bonded delete. An empty
or non-object body therefore failed differently per route -- a 415 from one, a 500 from
another -- while `common.json_object` already existed for the ones that abort.

Every route goes through it now. `optional=True` is the routes that used to tolerate a bad
body: they get an empty object, which is what `or {}` did, instead of an abort or a 500.
"""


def test_a_route_that_tolerates_a_body_gets_an_empty_object(dashboard):
    """No body, no content type: the route's own validation answers, not the parser."""
    response = dashboard.client.post('/api/migration/inventory')
    assert response.status_code == 400
    assert response.json['error'] == 'root is required'


def test_a_non_object_body_is_not_a_server_error(dashboard):
    """A list body is not an object: each route answers with its own failure, not a 500."""
    for path, allowed in (('/api/migration/inventory', {400}),
                          ('/api/migration/delete-obsolete', {400, 409})):
        response = dashboard.client.post(path, json=[])
        assert response.status_code in allowed, (path, response.status_code)
        assert response.json['error']


def test_the_bonded_delete_still_requires_confirmation(dashboard):
    """400 with or without a body, and the confirmation is read once instead of twice."""
    empty = dashboard.client.delete('/api/bonded-states/whatever')
    assert empty.status_code == 400
    assert empty.json['error'] == 'Deletion requires confirmation'
    without_confirm = dashboard.client.delete('/api/bonded-states/whatever', json={'other': True})
    assert without_confirm.status_code == 400


def test_the_micelle_route_rejects_a_non_object_body(dashboard):
    response = dashboard.client.post('/api/micelle/build', json=[])
    assert response.status_code == 400
    assert response.json['error'] == 'Expected an object'
