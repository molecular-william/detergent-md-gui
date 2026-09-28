"""The catalogue endpoint the complex panel builds its setup from.

The endpoint's job is not to look impressive but to be honest: it lists what the repository actually holds,
including the state of the files a template names, because the shipped DDM template is a skeleton and the panel
must not offer it as a fitted detergent model.
"""


def test_the_catalogue_lists_the_shipped_template_and_says_what_it_is(dashboard):
    response = dashboard.client.get('/api/pdc/catalog')
    assert response.status_code == 200

    body = response.get_json()
    assert body['templates'], body
    ddm = next(entry for entry in body['templates'] if entry['molecule'] == 'DDM')
    assert ddm['residue'] == 'DDM'
    assert ddm['registered_type'] == 'registered-template'   # not a fitted model, and the panel says so
    assert ddm['limitations'], 'a template must carry its limitation rather than look ready'
    assert isinstance(ddm['files_present'], bool)
    assert ddm['missing_files'] == [] or ddm['files_present'] is False


def test_the_catalogue_carries_the_decided_defaults(dashboard):
    """The numbers the protocol was agreed with, in one place, so a panel field cannot invent its own."""
    defaults = dashboard.client.get('/api/pdc/catalog').get_json()['defaults']
    assert defaults['salt_molar'] == 0.15
    assert defaults['assessment_ns'] == 100 and defaults['extension_ns'] == 900
    assert defaults['selection_threshold_fraction'] == 0.10 and defaults['attempts_max'] == 3
    assert defaults['box_margin_nm'] == 2.0 and defaults['initial_z_nm'] == 6.0 and defaults['contact_nm'] == 0.6


def test_the_protein_list_is_what_the_repository_holds(dashboard):
    proteins = dashboard.client.get('/api/pdc/catalog').get_json()['proteins']
    assert isinstance(proteins, list)
    for entry in proteins:
        assert entry['path'].endswith('.pdb') and entry['name'] and entry['id']
