"""The detergent list the protein-detergent panel offers, and the heading each workspace renders.

The panel's list is the molecule catalogue filtered by the registry, so the endpoint is where a non-detergent is
refused rather than offered: `molecules/` ships DDM beside three sugars, and a belt built from a sugar's beads is a
run that cannot be built. The repository's own files answer this (the register and the molecule directories are
checked in, like `resources/`), not the workspace -- only the *writable* stores are the test's to build.
"""
from dashboard.models.molecules import aa as aa_molecules
from dashboard.models.molecules import detergent_registry

SUGARS = ('Maltose', 'Sucrose', 'Trehalose')


def test_the_detergent_list_is_the_registry_against_the_molecules_on_disk(dashboard):
    """DDM is offered and a sugar is not, and every entry says which registry name it was filed under."""
    with dashboard.client as c:
        payload = c.get('/api/detergents').get_json()
    offering = {item['id']: item for item in payload['detergents']}
    assert 'DDM' in offering, f'the registry names DDM and molecules/DDM exists: {sorted(offering)}'
    for sugar in SUGARS:
        assert sugar not in offering, f'{sugar} is not in detergents.json and cannot be built into a belt'
    assert offering['DDM']['registry_name'] == 'n-Dodecyl-β-D-maltoside (DDM)'


def test_the_endpoint_asks_the_same_registry_the_module_does(dashboard):
    """The list is not a copy: the route answers with what the module resolved for this project root."""
    with dashboard.client as c:
        payload = c.get('/api/detergents').get_json()
    records = aa_molecules.catalogue(dashboard.coordinator.ROOT / 'molecules')
    assert [item['id'] for item in payload['detergents']] == \
        [record['id'] for record in detergent_registry.select(records, dashboard.coordinator.ROOT)]


def test_each_workspace_renders_its_own_panel_heading(dashboard):
    """The registry's per-workspace label is what the page shows, in both workspaces."""
    with dashboard.client as c:
        validation = c.get('/detergent-validation/new-run').get_data(as_text=True)
        simulations = c.get('/protein-detergent/new-run').get_data(as_text=True)
    assert '<h2>Single Molecule Simulations</h2>' in validation
    assert '<h2>Protein-Detergent Simulations</h2>' in simulations
    assert 'Protein-Detergent Simulations' not in validation.split('<form id="run-form"')[0]


def test_a_panels_heading_does_not_follow_whichever_panel_is_open(dashboard):
    """The page renders once, for one panel, and every panel's section is in it.

    So a heading read from the *open* panel is right only until someone opens another one: asking for
    `/detergent-validation/runs` rendered the New run section with the Runs panel's heading. Each section names the
    panel it is, and the registry keys the label by that.
    """
    with dashboard.client as c:
        runs = c.get('/detergent-validation/runs').get_data(as_text=True)
        complexes = c.get('/protein-detergent/complexes').get_data(as_text=True)
    assert '<h2>Single Molecule Simulations</h2>' in runs
    assert '<h2>Protein-Detergent Simulations</h2>' in complexes


def test_the_readiness_route_answers_for_the_panel_the_pdc_payload_names(dashboard):
    """The panel's readiness line is that run type's own answer, not a second opinion held in the page.

    A template that exists is checked by its own reader, so the check the panel shows is the pipeline's -- and the
    blockers are the ones the panel repeats verbatim.
    """
    with dashboard.client as c:
        answer = c.get('/api/readiness', query_string={'run_type': 'pdc', 'molecule_id': 'DDM',
                                                       'template': 'molecules/DDM/micelle_template.json'})
    assert answer.status_code == 200
    body = answer.get_json()
    assert set(body) >= {'ready', 'checks', 'blockers'}
    labels = [check['label'] for check in body['checks']]
    assert 'Detergent template' in labels and 'Template files' in labels, labels
    # A protein was not named, so the panel is told it is an absence by choice rather than a missing input.
    protein = next(check for check in body['checks'] if check['label'] == 'Protein')
    assert protein['ready'] is True and 'empty micelle' in protein['path']
