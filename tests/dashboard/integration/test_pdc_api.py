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


# The head of a real OPM download (1qj8, OmpX), and a fetch that counts itself, so a test can assert the network was
# touched once or not at all.
STRUCTURE = ('REMARK      1/2 of bilayer thickness:   11.8                                    \n'
             'ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00  0.00           N\n')


def _counted_fetcher(monkeypatch, dashboard, payload=STRUCTURE.encode()):
    calls = []

    def fetch(url):
        calls.append(url)
        return payload

    monkeypatch.setitem(dashboard.app.config, 'PDC_FETCHER', fetch)
    return calls


def test_importing_a_structure_puts_it_in_the_catalogue_with_what_the_file_states(dashboard, monkeypatch):
    """The point of the import: the panel can then name this protein the way it names a packaged one."""
    calls = _counted_fetcher(monkeypatch, dashboard)

    response = dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': '1qj8'})

    assert response.status_code == 201
    record = response.get_json()
    assert record['pdbid'] == '1qj8' and record['half_thickness_nm'] == 1.18
    assert calls == ['https://biomembhub.org/shared/opm-assets/pdb/1qj8.pdb']
    assert (dashboard.paths.proteins / '1qj8.pdb').read_bytes() == STRUCTURE.encode()

    catalogue = dashboard.client.get('/api/pdc/catalog').get_json()['proteins']
    entry = next(item for item in catalogue if item['name'] == '1qj8')
    assert entry['source'] == 'imported' and entry['half_thickness_nm'] == 1.18


def test_an_id_that_is_already_here_answers_without_fetching_again(dashboard, monkeypatch):
    """A second import is a question about a file, not a reason to reach the network."""
    calls = _counted_fetcher(monkeypatch, dashboard)

    first = dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': '1qj8'})
    second = dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': '1qj8'})

    assert (first.status_code, second.status_code) == (201, 200)
    assert len(calls) == 1
    assert second.get_json()['already_present'] is True


def test_an_id_that_is_not_a_pdb_id_is_refused_before_anything_is_fetched(dashboard, monkeypatch):
    """The id becomes a file name, so this is the trust boundary -- and a refusal must not reach the network.

    What is refused is the *form*: `nope` is four letters and therefore a well-formed id, and whether a well-formed
    id names a structure is the fetch's question to answer, not this gate's.
    """
    calls = _counted_fetcher(monkeypatch, dashboard)

    for bad in ('../../etc/passwd', '1qj8.pdb', '1qj', '1qj88', '1q;8', ''):
        assert dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': bad}).status_code == 400, bad

    assert calls == []
    assert not dashboard.paths.proteins.exists() or list(dashboard.paths.proteins.iterdir()) == []


def test_a_body_with_no_id_at_all_is_refused_rather_than_fetching_anything(dashboard, monkeypatch):
    calls = _counted_fetcher(monkeypatch, dashboard)

    assert dashboard.client.post('/api/pdc/proteins/import', json={}).status_code == 400
    assert calls == []


def test_a_fetch_that_failed_is_reported_and_leaves_the_catalogue_as_it_was(dashboard, monkeypatch):
    """A failure upstream is not the caller's bad request, and it must not leave a half-made import behind."""
    def broken(url):
        raise OSError('connection reset by peer')

    monkeypatch.setitem(dashboard.app.config, 'PDC_FETCHER', broken)

    response = dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': '1qj8'})

    assert response.status_code == 502
    assert '1qj8' in response.get_json()['error']
    catalogue = dashboard.client.get('/api/pdc/catalog').get_json()['proteins']
    assert '1qj8' not in [item['name'] for item in catalogue]
