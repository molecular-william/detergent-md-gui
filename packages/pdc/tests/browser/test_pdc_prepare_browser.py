"""The panel's statement of the plan's step 1, and the workflow card -- neither of which asks anything any more.

The user met this step as a refusal: their 4iar download has 20 of 928 coarse-grained beads with no position, and the
preview card said so in the placement gate's own words with no way to act on it. The step answers it, so it stopped being
a choice: pdb2pqr rebuilds and protonates the protein before martinize2 reads it, and the stage records `skipped` when the
tool is not resolvable -- a default no machine is obliged to satisfy must not block runs. So the claims here are that the
control is **gone**, that the sentence replacing it is the honest one (always on, skipped when absent), that the derive
still *states* the choice rather than omitting it, and that a refusal from the step is rendered as the tool's own sentence
with no picture.

The workflow card is the other half: it is a closed `<details>` holding one inline SVG of the chain, so the shape of the
run is available without pushing the form down the page.

The routes are served as fixtures, exactly as the preview card's own browser tests do, so nothing here reads the
developer's workspace and no tool runs.
"""
import re

from playwright.sync_api import expect

from tests.harness import browser

PROTEIN = {'id': 'workspace/dashboard/proteins/4iar.pdb', 'name': '4iar',
           'path': 'workspace/dashboard/proteins/4iar.pdb', 'source': 'imported',
           'half_thickness_nm': 1.68, 'chains': ['A']}
CATALOG = {'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                          'template': 'molecules/DDM/micelle_template.json',
                          'registered_type': 'registered-template', 'files_present': True, 'missing_files': [],
                          'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
           'proteins': [PROTEIN],
           'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15,
                        'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
                        'selection_threshold_fraction': 0.1,
                        'prepare_protein': True}}
#: One model, as `/api/pdc/models` answers: a saved mapping and what it carries. The server has already joined the
#: parameterization and written the label, so a stub without a label offers nothing to choose.
MODELS = {'molecule': 'DDM', 'models': [{'file': 'mapping_candidate_fixture.json', 'name': 'DDM draft', 'beads': 11,
                                         'content_hash': 'ab' * 32, 'fitted': None,
                                         'label': 'DDM draft · 11 beads · derived terms'}]}

#: The refusal the user actually met, in the placement gate's own words, and the sentence the preparation step
#: answers when it cannot run at all.
POSITIONLESS = ('the protein has 20 coarse-grained bead(s) without a position, of 928, so no detergent can be '
                'placed clear of it')
NO_TOOL = 'pdb2pqr is not resolvable on this machine, and it is the tool this step rebuilds a structure\'s missing ' \
          'atoms and protonates it with'


def answer(*, valid=True, step=None, reasons=(), pdb='', prepare_seconds=0.0, heavy_atoms=0,
           prepare_protein=True):
    """A response shaped as the route answers, with the fields this statement and card render."""
    return {
        'valid': valid, 'step': step, 'reasons': list(reasons), 'pdb': pdb if valid else None,
        'basis': {'protein': '4iar', 'chains': ['A'], 'template': 'micelle_template.json', 'detergent': 'DDM',
                  'residue': 'DDM', 'mapping': None, 'aggregation_number': 150, 'placement_mode': 'lattice',
                  'seed': 20261014, 'beads': 1028 if valid else None, 'protein_beads': 928,
                  'box_nm': [10.0, 9.0, 12.0] if valid else None, 'clearance_nm': 0.5436 if valid else None,
                  'placement_shape': 'belt-torus' if valid else None, 'band_radius_nm': 2.1431,
                  'detergent_representation': "the mapping's beads",
                  'prepare_protein': prepare_protein,
                  'prepare': ({'tool': 'pdb2pqr', 'tool_version': '3.7.1', 'heavy_atoms_added': heavy_atoms,
                               'residues_rebuilt': 25, 'seconds': prepare_seconds} if prepare_seconds else None)},
        'cost': {'cg_cached': False, 'coarse_graining_seconds': 11.7, 'detergent_seconds': 0.0,
                 'placement_seconds': 0.002, 'seconds': 13.2, 'cg_bytes': 86788, 'cg_key': '26f6e8f875ed858f',
                 'prepare_seconds': prepare_seconds},
    }


PLACEMENT_PDB = ('REMARK 950 PLACEMENT PREVIEW\n'
                 'HETATM    1  B01 PRO A   1       0.000   0.000   0.000  1.00  0.00           C\n'
                 'END\n')


def serve(page, body, requests=None):
    """Every read the panel makes before it can ask, and the route under test."""
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=CATALOG))
    page.route(re.compile(r'/api/pdc/models\?'), lambda route: route.fulfill(json=MODELS))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))

    def route_preview(route):
        if requests is not None:
            requests.append(route.request.url)
        route.fulfill(json=body(route.request.url) if callable(body) else body)

    page.route(re.compile(r'/api/pdc/preview/placement'), route_preview)


def open_panel(page, base_url, *, protein=PROTEIN['id']):
    return browser.open_pdc_new_run(page, base_url, protein=protein, chains=True)


def test_the_step_is_stated_rather_than_offered(dashboard, live_page):
    """No control, one sentence, one review row -- and the sentence says the step always runs."""
    page, errors = live_page
    serve(page, answer(pdb=PLACEMENT_PDB))
    open_panel(page, live_page.base_url)

    assert page.locator('[name=prepare_protein]').count() == 0, 'the step is not a choice any more'
    note = page.locator('.new-pdc-prepare-note')
    expect(note).to_contain_text('Prepare the protein (PDB2PQR): always on')
    expect(note).to_contain_text('104 heavy atoms across 25 residues')
    expect(note).to_contain_text('skipped')
    expect(page.locator('[data-new-summary=prepare]')).to_contain_text('PDB2PQR: always on')
    assert errors == [], errors


def test_the_derive_always_asks_for_the_preparation_and_the_cost_row_reports_it(dashboard, live_page):
    """The request states the choice rather than omitting it: a prepared protein is a different bead set."""
    page, errors = live_page
    requests = []
    serve(page, answer(pdb=PLACEMENT_PDB, prepare_seconds=1.5, heavy_atoms=104), requests=requests)
    open_panel(page, live_page.base_url)

    page.locator('.new-pdc-preview-derive').click()
    page.wait_for_function("() => document.querySelector('.new-pdc-preview-cost').textContent.includes('PDB2PQR')",
                           timeout=30000)

    assert requests and 'prepare_protein=true' in requests[-1], requests[-1]
    expect(page.locator('.new-pdc-preview-cost')).to_contain_text('PDB2PQR 1.5 s')
    expect(page.locator('.new-pdc-preview-cost')).to_contain_text('104 heavy atoms')
    assert errors == [], errors


def test_a_refusal_from_the_preparation_is_the_tools_own_sentence_and_no_picture(dashboard, live_page):
    """The step is where a structure with no hydrogens to offer is refused, and the card says which step refused."""
    page, errors = live_page
    serve(page, answer(valid=False, step='protein preparation', reasons=[NO_TOOL]))
    open_panel(page, live_page.base_url)

    page.locator('.new-pdc-preview-derive').click()
    page.wait_for_function("() => !document.querySelector('.new-pdc-preview-refusal').hidden", timeout=30000)

    refusal = page.locator('.new-pdc-preview-refusal')
    expect(refusal).to_contain_text('the protein preparation step refuses')
    expect(refusal).to_contain_text(NO_TOOL)
    expect(page.locator('.new-pdc-preview-viewer')).to_be_hidden()
    assert errors == [], errors


def test_the_workflow_card_is_closed_and_draws_the_chain_when_opened(dashboard, live_page):
    """Minimised by default, and what it holds is a diagram of the chain rather than a paragraph per step."""
    page, errors = live_page
    serve(page, answer(pdb=PLACEMENT_PDB))
    open_panel(page, live_page.base_url)

    details = page.locator('details.new-pdc-diagram')
    expect(details).to_be_visible()
    assert not details.evaluate('element => element.open'), 'minimised by default'
    expect(details.locator('summary')).to_contain_text('CG-MD chain as a diagram')

    details.locator('summary').click()
    svg = details.locator('svg.new-pdc-workflow-svg')
    expect(svg).to_be_visible()
    # The chain, not a decoration: every stage the run can take is drawn, and the back-map is marked apart from it.
    titles = [text.strip() for text in svg.locator('text:not(.sub)').all_text_contents()]
    assert len(titles) == 10, titles
    assert titles[0].startswith('1 · Prepare') and titles[-1].startswith('10 · Result')
    assert svg.locator('.new-pdc-backmap-node').count() == 1
    assert errors == [], errors


def test_the_other_workspace_is_untouched(dashboard, live_page):
    """The step is this pipeline's: the single-molecule panel renders no such statement, and no such row."""
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')

    assert page.locator('[name=prepare_protein]').count() == 0
    assert page.locator('.new-pdc-prepare-note').count() == 0
    assert page.locator('details.new-pdc-diagram').count() == 0
