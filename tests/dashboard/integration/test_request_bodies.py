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


def test_the_parameterization_delete_still_requires_confirmation(dashboard):
    """400 with or without a body, and the confirmation is read once instead of twice.

    The route this pins used to be the bonded-state store's; that store is gone, and the confirmation is still the
    contract on the delete that removes history -- a parameterization's revisions are recoverable only by fitting again.
    """
    content_hash = 'ab' * 32
    empty = dashboard.client.delete(f'/api/bonded-parameterizations/{content_hash}')
    assert empty.status_code == 400
    assert empty.json['error'] == 'Deleting a parameterization requires confirmation'
    without_confirm = dashboard.client.delete(f'/api/bonded-parameterizations/{content_hash}', json={'other': True})
    assert without_confirm.status_code == 400


def test_the_flat_bonded_state_surface_is_gone(dashboard):
    """The store, its seven routes, and the importer that called a method no coordinator implements.

    A 404 for each, not a 405 or a 400: the paths are not routes at all any more, which is what "deleted" has to mean
    for a surface nobody could reach to be worth deleting. `POST /api/bonded-states/import-legacy` was worse than dead —
    it called `coordinator.import_legacy_bonded_states`, which does not exist, so the one route meant to rescue an old
    workspace would have answered with a stack trace.
    """
    for method, path in (('get', '/api/bonded-states'), ('get', '/api/bonded-states/whatever'),
                         ('post', '/api/bonded-states/automatic'), ('post', '/api/bonded-states/import-legacy')):
        response = getattr(dashboard.client, method)(path)
        assert response.status_code == 404, (method, path, response.status_code)
        assert 'error' in response.json, (method, path)

    # Two-segment paths are shadowed by the page route `/<section>/<panel>`, which is GET-only, so a write to one
    # answers 405 rather than 404 -- measured on `/api/definitely-nope` as well, so it is the router and not this
    # deletion. What matters here is that no write reaches a bonded-state handler, and none exists to reach.
    for method, path in (('post', '/api/bonded-states'), ('patch', '/api/bonded-states/whatever'),
                         ('delete', '/api/bonded-states/whatever')):
        assert getattr(dashboard.client, method)(path).status_code in (404, 405), (method, path)


def test_the_micelle_route_rejects_a_non_object_body(dashboard):
    response = dashboard.client.post('/api/micelle/build', json=[])
    assert response.status_code == 400
    assert response.json['error'] == 'Expected an object'
