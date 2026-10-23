"""The panel's control for the plan's step 1: what it says, what it sends, and what a refusal from it looks like.

The user met this step as a refusal: their 4iar download has 20 of 928 coarse-grained beads with no position, and the
preview card said so in the placement gate's own words with no way to act on it. So the claims here are about the
control that answers it -- it is offered in the protein card, its off state says what it costs the build, its on state
states what it does, what it needs and what it costs, the derive request carries the choice (the prepared structure is
a different coarse-grained protein, so a preview that did not say which one it asked for would be ambiguous), and a
refusal from the step is rendered as the tool's own sentence with no picture.

The routes are served as fixtures, exactly as the preview card's own browser tests do, so nothing here reads the
developer's workspace and no tool runs.
"""
import re

from playwright.sync_api import expect

from . import panels

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
                        'selection_threshold_fraction': 0.1, 'snapshot_interval_ns': 20.0, 'snapshot_cap': 20,
                        'prepare_protein': False}}
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
           prepare_protein=False):
    """A response shaped as the route answers, with the fields this control and card render."""
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
    return panels.open_pdc_new_run(page, base_url, protein=protein, chains=True)


def test_the_panel_offers_the_step_with_its_on_state_and_the_workflow_says_so(dashboard, live_page):
    """The control, its own sentence, the review row and the strip: four places, one choice -- and the default is *on*,
    because a structure whose side chains are incomplete coarse-grains into beads with no position."""
    page, errors = live_page
    serve(page, answer(pdb=PLACEMENT_PDB))
    open_panel(page, live_page.base_url)

    box = page.locator('[name=prepare_protein]')
    expect(box).to_be_visible()
    expect(box).to_be_checked()
    expect(page.locator('.new-pdc-prepare-note')).to_contain_text('rebuilds the residues')
    expect(page.locator('.new-pdc-prepare-note')).to_contain_text('104 heavy atoms across 25 residues')
    expect(page.locator('[data-new-summary=prepare]')).to_contain_text('PDB2PQR')

    step = page.locator('.new-pdc-prepare-step')
    expect(step).to_contain_text('1 · Prepare (PDB2PQR)')
    expect(step).to_contain_text('rebuilds the deposited file')


def test_switching_it_on_states_what_it_does_needs_and_costs(dashboard, live_page):
    """The honest voice the preview card uses: the tool it needs, what it builds, and its measured wall time."""
    page, errors = live_page
    serve(page, answer(pdb=PLACEMENT_PDB))
    open_panel(page, live_page.base_url)

    page.locator('[name=prepare_protein]').check()

    note = page.locator('.new-pdc-prepare-note')
    expect(note).to_contain_text('pdb2pqr rebuilds the residues')
    expect(note).to_contain_text('needs pdb2pqr on this machine')
    expect(note).to_contain_text('104 heavy atoms across 25 residues in 1.5 s')
    expect(page.locator('[data-new-summary=prepare]')).to_contain_text('PDB2PQR')
    expect(page.locator('.new-pdc-prepare-step')).to_contain_text('1 · Prepare (PDB2PQR)')
    expect(page.locator('.new-pdc-prepare-step')).to_contain_text('Energy minimisation leg in step 4')


def test_the_derive_carries_the_choice_and_the_cost_row_reports_the_step(dashboard, live_page):
    """A prepared protein is a different coarse-grained protein, so the request says which one it asked for."""
    page, errors = live_page
    requests = []
    serve(page, lambda url: answer(pdb=PLACEMENT_PDB, prepare_seconds=1.5, heavy_atoms=104,
                                   prepare_protein='prepare_protein=true' in url), requests=requests)
    open_panel(page, live_page.base_url)

    page.locator('[name=prepare_protein]').check()
    page.locator('.new-pdc-preview-derive').click()
    page.wait_for_function("() => document.querySelector('.new-pdc-preview-cost').textContent.includes('PDB2PQR')",
                           timeout=30000)

    assert 'prepare_protein=true' in requests[-1], requests[-1]
    expect(page.locator('.new-pdc-preview-cost')).to_contain_text('PDB2PQR 1.5 s')
    expect(page.locator('.new-pdc-preview-cost')).to_contain_text('104 heavy atoms')

    # And switched back off, the next derive says so rather than leaving the reader to assume the last choice stood.
    #
    # The wait is on this derive's *request*, not on the cost row: the row already holds the previous derive's answer,
    # so waiting for "the text is not empty" returns at once and the assertion reads whichever request happened to be
    # last -- the race this test was rewritten for, measured intermittent under a loaded parallel browser tier.
    page.locator('[name=prepare_protein]').uncheck()
    with page.expect_request(lambda request: 'prepare_protein=false' in request.url) as derived:
        page.locator('.new-pdc-preview-derive').click()
    assert 'prepare_protein=false' in derived.value.url, derived.value.url
    assert '/api/pdc/preview/placement?' in derived.value.url, derived.value.url


def test_a_refusal_from_the_preparation_is_the_tools_own_sentence_and_no_picture(dashboard, live_page):
    """The step is where a structure with no hydrogens to offer is refused, and the card says which step refused."""
    page, errors = live_page
    serve(page, answer(valid=False, step='protein preparation', reasons=[NO_TOOL]))
    open_panel(page, live_page.base_url)

    page.locator('[name=prepare_protein]').check()
    page.locator('.new-pdc-preview-derive').click()
    page.wait_for_function("() => !document.querySelector('.new-pdc-preview-refusal').hidden", timeout=30000)

    refusal = page.locator('.new-pdc-preview-refusal')
    expect(refusal).to_contain_text('the protein preparation step refuses')
    expect(refusal).to_contain_text(NO_TOOL)
    expect(page.locator('.new-pdc-preview-viewer')).to_be_hidden()


def test_the_other_workspace_is_untouched(dashboard, live_page):
    """The step is this pipeline's: the single-molecule panel renders no such control, and no such row."""
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')

    assert page.locator('[name=prepare_protein]').count() == 0
    assert page.locator('.new-pdc-prepare-note').count() == 0
