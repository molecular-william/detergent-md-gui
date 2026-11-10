"""The published sugar reference as a read-only Bond Interactions model.

The model is a transcription of the reference entry, never a fit, so the route offers it only for the molecule the
entry is published *for* and where the candidate reproduces that entry's mapping facts. A layout match alone is not
enough: identification is stereochemistry-blind, and maltose's layout matches `LAC`, which is lactose. Glucose is the
exception the policy names: its layout identifies `GAL`, the two entries are one mapping under different published
lengths, and so the molecule's identity selects `GLC` and the model carries the sentence that says so.
"""
from dashboard.models import mappings
from dashboard.models.mappings import context as mapping_context


def sections(topology):
    """The topology's named sections, each as its rows of fields."""
    current, table = None, {}
    for line in topology.splitlines():
        clean = line.split(';', 1)[0].strip()
        if clean.startswith('['):
            current = clean.strip('[] ').lower()
            table.setdefault(current, [])
        elif clean and current:
            table[current].append(clean.split())
    return table


def test_sucrose_answers_the_published_sucr_model(dashboard):
    response = dashboard.client.get('/api/mappings/reference/Sucrose')
    assert response.status_code == 200, response.get_json()
    model = response.get_json()['model']

    assert model['read_only'] is True
    assert model['reference_entry'] == 'SUCR'
    assert model['file'] == 'reference:Sucrose'
    assert model['molecule_id'] == 'Sucrose'
    assert model['status'] == 'published-reference'
    assert len(model['beads']) == 8

    assert '[ constraints ]' in model['topology']
    assert '[ bonds ]' in model['topology']
    atoms = [row[4] for row in sections(model['topology'])['atoms']]
    assert atoms == [f'B{index:02d}' for index in range(1, 9)]

    assert model['reference']['paper_doi'] == '10.1021/acs.jctc.2c00757'
    assert model['reference']['path'] == 'references/martini_v3.0.0_sugars_v2.itp'
    assert model['limitations']


def test_maltose_is_refused_because_lac_is_lactose(dashboard):
    """Maltose and lactose share the identification fingerprint (two hexoses, an AB link), and the identifier is
    stereochemistry-blind: its layout matching `LAC` is not evidence that the published lactose model is maltose's
    model. The route refuses rather than showing another molecule's parameters under a matching layout."""
    response = dashboard.client.get('/api/mappings/reference/Maltose')
    assert response.status_code == 404
    error = response.get_json()['error']
    assert 'no published Martini 3 sugar entry' in error
    assert 'matching bead layout is not the same' in error


def test_lactose_answers_the_published_lac_model(dashboard):
    response = dashboard.client.get('/api/mappings/reference/Lactose')
    assert response.status_code == 200, response.get_json()
    model = response.get_json()['model']

    assert model['file'] == 'reference:Lactose'
    assert model['name'] == 'Martini 3 sugar reference · LAC'
    assert model['reference_entry'] == 'LAC'
    assert model['read_only'] is True
    assert len(model['beads']) == 8
    assert model['layout_note'] is None, 'the layout identified LAC itself, so no ambiguity is stated'


def test_glucose_answers_the_published_glc_model_and_states_the_gal_ambiguity(dashboard):
    """Every aldohexose has the same four-bead pattern, so the identifier names `GAL` for a glucose structure. The
    route uses the molecule's own `GLC` entry -- the two entries are one mapping with different published lengths --
    and says that only the identity chose, because the panel must not present it as a layout result."""
    response = dashboard.client.get('/api/mappings/reference/Glucose')
    assert response.status_code == 200, response.get_json()
    model = response.get_json()['model']

    assert model['file'] == 'reference:Glucose'
    assert model['name'] == 'Martini 3 sugar reference · GLC'
    assert model['reference_entry'] == 'GLC'
    assert len(model['beads']) == 4
    note = model['layout_note']
    assert 'GLC' in note and 'GAL' in note
    assert 'cannot distinguish' in note

    # The transcribed terms are glucose's, not galactose's: the published ring lengths differ.
    constraints = [row[3] for row in sections(model['topology'])['constraints']]
    assert constraints == ['0.38', '0.47', '0.396']


def test_a_layout_match_for_the_wrong_molecule_is_refused(dashboard):
    """The published-for map is the first gate; a molecule it does not name is not mapped to an entry by layout."""
    from dashboard.models.sugars import reference
    assert reference.PUBLISHED_FOR == {'Sucrose': 'SUCR', 'Trehalose': 'TREH',
                                       'Lactose': 'LAC', 'Glucose': 'GLC'}
    for molecule, entry in reference.PUBLISHED_FOR.items():
        response = dashboard.client.get(f'/api/mappings/reference/{molecule}')
        assert response.status_code == 200, response.get_json()
        assert response.get_json()['model']['reference_entry'] == entry


def test_trehalose_answers_the_published_treh_model(dashboard):
    """The published TREH atom 8 residue column is the file's anomaly; the reader takes a site's residue from its
    parents and the symmetric 1,1 linkage follows the entry's order, so the entry is offered."""
    response = dashboard.client.get('/api/mappings/reference/Trehalose')
    assert response.status_code == 200, response.get_json()
    model = response.get_json()['model']
    assert model['reference_entry'] == 'TREH'
    assert model['read_only'] is True
    assert [bead['type'] for bead in model['beads']] == ['SP1r', 'SP4r', 'SP1r', 'TC4',
                                                         'SN6', 'SP4r', 'SP1r', 'TC4']


def test_a_detergent_is_refused_because_it_has_no_published_entry(dashboard):
    """DDM is a detergent with two rings, not a published sugar model: the published-for map refuses it before any
    layout comparison, so no entry's numbers can be attached to it."""
    response = dashboard.client.get('/api/mappings/reference/DDM')
    assert response.status_code == 404
    assert 'no published Martini 3 sugar entry' in response.get_json()['error']


def test_an_unknown_molecule_answers_bad_request(dashboard):
    response = dashboard.client.get('/api/mappings/reference/NoSuchMolecule')
    assert response.status_code == 400
    assert response.get_json()['error']


def test_summary_rows_name_the_molecule_and_still_omit_beads(dashboard):
    client = dashboard.client
    context = client.get('/api/mappings/context?molecule_id=Maltose').get_json()['context']
    candidate = mappings.automatic_candidate(mapping_context.as_structure(context), 'Maltose')
    candidate['molecule_id'] = 'Maltose'
    candidate['molecule_snapshot'] = context['snapshot']
    saved = client.post('/api/mappings/drafts', json=candidate)
    assert saved.status_code == 201, saved.get_json()

    rows = client.get('/api/mappings?view=summary').get_json()['candidates']
    row = next(item for item in rows if item['file'] == saved.get_json()['file'])
    assert row['molecule_id'] == 'Maltose'
    assert 'beads' not in row
    assert set(row) == {'file', 'name', 'status', 'sha256', 'mapping_hash', 'mapping_content_hash',
                        'validation', 'molecule_id'}
