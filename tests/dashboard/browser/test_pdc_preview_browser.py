"""The New Run panel's system preview: the card, the ask, the refusal, and the stale frame.

Four claims, and each is the plan's:

* **the card is at the head of the right column and changes nothing about the layout** -- the two halves still sit
  side by side with equal widths at different x, and the paired rows still share a y;
* **the picture is asked for** -- `Derive the preview` sends one request, and a change to the protein, the subunit
  ticks or the mapping does *not* send another: it marks the frame as no longer this form's. The count, the style,
  the seed and the box margins do re-derive, because the coarse-grained protein is cached server-side;
* **a refusal is the builder's sentence and no picture** -- never a blank block, and never a drawing of a system the
  build would refuse;
* **the beads are drawn at twice the model's radius and the bond guess is off** -- the radii read off the loaded
  structure are the module's own table doubled, and the drawn bonds are the file's `CONECT` records or none at all.

The route is served as a fixture, so nothing here reads the developer's workspace, and the frames are written by
`pdc_view.system_pdb` -- the same writer a run's own snapshot goes through -- rather than being typed out by hand.
"""
import re

from playwright.sync_api import expect

from dashboard.execution.adapters import pdc_view
from tests.dashboard.support import DDM_BEADS, DDM_BONDS, DDM_CONSTRAINTS, DDM_PLACEMENT, ddm_moleculetype

PROTEIN = {'id': 'molecules/1qj8/1qj8.pdb', 'name': '1qj8', 'path': 'molecules/1qj8/1qj8.pdb',
           'source': 'packaged', 'half_thickness_nm': 1.35, 'chains': ['A', 'B']}
CATALOG = {'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                          'template': 'molecules/DDM/micelle_template.json',
                          'registered_type': 'registered-template', 'files_present': True, 'missing_files': [],
                          'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
           'proteins': [PROTEIN],
           'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15,
                        'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
                        'selection_threshold_fraction': 0.1, 'snapshot_interval_ns': 20.0, 'snapshot_cap': 20}}
MAPPING_FILE = 'mapping_candidate_fixture.json'
MAPPINGS = {'candidates': [{'name': 'DDM draft', 'file': MAPPING_FILE}]}

MOLECULES = 2
#: The refusal the clearance gate writes, in its own words (`pdc_placement.place_detergents`).
REFUSAL = 'detergent too close to the protein: 0.174 nm < 0.5 nm'
STALE = 'The protein, the subunits or the mapping have changed since this frame was derived — derive it again.'
DERIVED = 'Derived for the inputs on this form.'


def placement_pdb(molecules=MOLECULES):
    """A placement frame written by the writer a run's own snapshot goes through.

    Two protein beads and `molecules` DDM molecules, three nanometres apart so no two beads of different molecules are
    near enough for a viewer's distance-based guess to join them -- which is what makes the drawn bond count a
    statement about the model. It carries the moleculetype's own bonds as `CONECT` records, exactly as a run's
    snapshot does.
    """
    atoms = [{'residue_id': 1, 'residue': 'PRO', 'name': 'BB', 'position': [0.0, 0.0, 0.0]},
             {'residue_id': 2, 'residue': 'PRO', 'name': 'SC1', 'position': [0.5, 0.0, 0.0]}]
    for molecule in range(molecules):
        for name, xyz in zip(DDM_BEADS, DDM_PLACEMENT):
            atoms.append({'residue_id': 3 + molecule, 'residue': 'DDM', 'name': name,
                          'position': [xyz[0] + molecule * 3.0, xyz[1], xyz[2]]})
    model = pdc_view.read_moleculetype_text(ddm_moleculetype(), source='detergent_CG.itp')
    return pdc_view.system_pdb(atoms, detergent_residue='DDM', topology=model,
                               title='placement preview (DDM, AN=2, mode=lattice, seed=20261013)')


def centres_pdb(molecules=3):
    """The other build: no mapping, so one centre per molecule and no topology -- and no bonds to draw at all."""
    atoms = [{'residue_id': index + 1, 'residue': 'DDM', 'name': f'DD{index + 1:03d}',
              'position': [1.0 * index, 0.0, 0.0]} for index in range(molecules)]
    return pdc_view.system_pdb(atoms, detergent_residue='DDM', topology=None,
                               title='placement preview (DDM, AN=3, mode=lattice, seed=20261013)')


def answer(pdb=None, *, valid=True, reasons=(), protein_beads=542, beads=1024, clearance: float | None = 0.5436,
           placement_shape='belt-band', band: float | None = 3.6408, representation='the mapping\u2019s beads',
           cost=None, protein: str | None = '1qj8', chains=('A', 'B'), mode='lattice', aggregation=150,
           seed=20261013):
    """A response shaped as the route answers, with the fields the card renders."""
    return {
        'valid': valid, 'reasons': list(reasons), 'pdb': pdb if valid else None,
        'basis': {'protein': protein, 'chains': list(chains), 'template': 'micelle_template.json',
                  'detergent': 'DDM', 'residue': 'DDM', 'mapping': MAPPING_FILE,
                  'aggregation_number': aggregation, 'placement_mode': mode, 'seed': seed,
                  'beads': beads, 'protein_beads': protein_beads,
                  'box_nm': [8.3517, 6.7817, 11.0804] if valid else None,
                  'clearance_nm': clearance,
                  'placement_shape': placement_shape,
                  'band_radius_nm': band, 'detergent_representation': representation},
        'cost': cost or {'cg_cached': True, 'coarse_graining_seconds': 0.001, 'detergent_seconds': 0.074,
                         'placement_seconds': 0.005, 'seconds': 0.1017, 'cg_bytes': 50768,
                         'cg_key': '0423f94ce62e7698'},
    }


def serve(page, body, requests=None):
    """Every read the panel makes before it can ask, and the route under test."""
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=CATALOG))
    page.route(re.compile(r'/api/mappings\?'), lambda route: route.fulfill(json=MAPPINGS))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))

    def route_preview(route):
        if requests is not None:
            requests.append(route.request.url)
        route.fulfill(json=body(route.request.url) if callable(body) else body)

    page.route(re.compile(r'/api/pdc/preview/placement'), route_preview)


def open_panel(page, base_url, *, protein=PROTEIN['id']):
    page.goto(f'{base_url}/protein-detergent/new-run')
    page.get_by_role('tab', name='New run', exact=True).click()
    page.wait_for_function("() => document.querySelectorAll('#new-detergent option').length > 1", timeout=30000)
    if protein:
        page.wait_for_function("() => document.querySelectorAll('#new-protein option').length > 1", timeout=30000)
        page.locator('#new-protein').select_option(protein)


def derive(page):
    """Press the button: the picture is asked for, never streamed."""
    page.locator('.new-pdc-preview-derive').click()


def loaded_atoms(page, count):
    """Wait for the stage to hold `count` beads, and answer with how many it did hold."""
    page.wait_for_function("() => document.querySelector('.new-pdc-preview-viewer').previewStage"
                           f"?.compList[0]?.structure?.atomCount === {count}", timeout=30000)
    return page.evaluate("() => document.querySelector('.new-pdc-preview-viewer').previewStage"
                         ".compList[0].structure.atomCount")


#: The loaded structure's radii and drawn bonds, read off the component and the representation -- the same seam the
#: other bead tests read (`el.previewStage.compList[0]`), so what is measured is what is drawn.
MEASURE = """
(el) => {
  const component = el.previewStage.compList[0];
  const structure = component.structure;
  const radii = [];
  for (let index = 0; index < structure.atomCount; index += 1) radii.push(structure.getAtomProxy(index).radius);
  return {atoms: structure.atomCount, radii: radii, bonds: structure.bondStore.count,
          parameters: component.reprList[0].parameters};
}
"""


def test_the_card_is_first_in_the_right_column_and_the_layout_is_unchanged(dashboard, live_page):
    """The plan's geometry: the card at the head of the right column, and the two halves still side by side."""
    page, errors = live_page
    serve(page, lambda url: answer(placement_pdb()))
    open_panel(page, live_page.base_url)

    first = page.locator('.new-run-settings .card').first
    expect(first).to_contain_text('What these inputs would build')
    expect(first.locator('.new-pdc-preview-viewer')).to_be_visible()
    expect(first.locator('.new-pdc-preview-derive')).to_be_visible()
    expect(first.locator('.new-pdc-preview-state')).to_have_text('Nothing derived yet: press Derive the preview.')

    form = page.locator('#run-form').bounding_box()
    inputs = page.locator('.new-run-inputs').bounding_box()
    settings = page.locator('.new-run-settings').bounding_box()
    assert settings['x'] >= inputs['x'] + inputs['width'] - 1, 'the halves overlap: they are not side by side'
    assert abs(inputs['width'] - form['width'] / 2) <= 20 and abs(settings['width'] - form['width'] / 2) <= 20

    # The pairing the panel already had is untouched: the first paired row still shares a y to the pixel.
    cells = [page.locator('.new-pdc-detergent-pair > *').nth(index).bounding_box() for index in range(2)]
    assert cells[0]['y'] == cells[1]['y'], cells
    assert cells[0]['x'] < cells[1]['x'], cells
    assert errors == [], errors


def test_deriving_the_preview_draws_the_frame_the_route_answered_with(dashboard, live_page):
    """One request, the server's own record on screen, and the stage holding the frame that was sent."""
    page, errors = live_page
    requests = []
    serve(page, answer(placement_pdb()), requests)
    open_panel(page, live_page.base_url)

    assert requests == [], 'the card asked for a picture nobody asked for'
    derive(page)

    assert loaded_atoms(page, 2 + MOLECULES * len(DDM_BEADS)) == 2 + MOLECULES * len(DDM_BEADS)
    assert len(requests) == 1, requests
    expect(page.locator('.new-pdc-preview-state')).to_have_text(DERIVED)
    expect(page.locator('.new-pdc-preview-basis')).to_contain_text('1qj8 chains A+B')
    expect(page.locator('.new-pdc-preview-basis')).to_contain_text('box 8.35 × 6.78 × 11.08 nm')
    expect(page.locator('.new-pdc-preview-basis')).to_contain_text('clearance from the protein 0.544 nm')
    expect(page.locator('.new-pdc-preview-basis')).to_contain_text('no solvent')
    expect(page.locator('.new-pdc-preview-from')).to_have_text(
        '1qj8 chains A+B · pre-assembled micelle · 150 detergents · seed 20261013')
    expect(page.locator('.new-pdc-preview-beads')).to_contain_text('1,024 beads')
    expect(page.locator('.new-pdc-preview-box')).to_contain_text('the box the build writes')
    expect(page.locator('.new-pdc-preview-box')).to_contain_text('band of radius 3.64 nm')
    expect(page.locator('.new-pdc-preview-cost')).to_contain_text('already cached')
    expect(page.locator('.new-pdc-preview-kept')).to_contain_text('preview/cg/0423f94ce62e7698')
    expect(page.locator('.new-pdc-preview-refusal')).to_be_hidden()
    assert errors == [], errors


def test_a_refusal_shows_the_builders_reason_and_no_picture(dashboard, live_page):
    """`valid: false` is an answer: the builder's own sentence, no canvas, and no number that could read as one."""
    page, errors = live_page
    serve(page, answer(valid=False, reasons=[REFUSAL], placement_shape='sphere', band=None, clearance=0.174,
                       cost={'cg_cached': False, 'coarse_graining_seconds': 6.7, 'detergent_seconds': 0.02,
                             'placement_seconds': 0.014, 'seconds': 6.9, 'cg_bytes': 50768,
                             'cg_key': '0423f94ce62e7698'}))
    open_panel(page, live_page.base_url)
    derive(page)

    refusal = page.locator('.new-pdc-preview-refusal')
    expect(refusal).to_be_visible()
    expect(refusal).to_contain_text(REFUSAL)
    expect(refusal).to_contain_text('the builder refuses these inputs')
    # The scope the plan asked for: a refusal from the sphere is not a verdict on the protein.
    expect(refusal).to_contain_text('the shape a build takes when the protein’s file states no membrane')
    expect(page.locator('.new-pdc-preview-viewer')).to_be_hidden()
    assert page.locator('.new-pdc-preview-viewer canvas').count() == 0, 'a refusal drew a picture'
    expect(page.locator('.new-pdc-preview-beads')).to_have_text('—')
    expect(page.locator('.new-pdc-preview-box')).to_have_text('—')
    # What it paid is still a measurement, and the state line says what the card is showing.
    expect(page.locator('.new-pdc-preview-cost')).to_contain_text('martinize2 6.7 s')
    expect(page.locator('.new-pdc-preview-state')).to_have_text(
        'The build refuses these inputs; the sentence above is its own.')
    assert errors == [], errors


def test_the_expensive_inputs_mark_the_frame_stale_and_the_cheap_ones_re_derive(dashboard, live_page):
    """Decision 4, measured in requests: a subunit tick is a different question, a count is the same one re-asked."""
    page, errors = live_page
    requests = []
    serve(page, answer(placement_pdb()), requests)
    open_panel(page, live_page.base_url)
    derive(page)
    loaded_atoms(page, 2 + MOLECULES * len(DDM_BEADS))
    assert len(requests) == 1

    # A subunit tick: what would be coarse-grained has changed, so the frame is stale and the card says so -- and no
    # second request goes out, because the picture on screen is still the one that was paid for.
    page.locator('.new-pdc-chain').last.locator('input').uncheck()
    expect(page.locator('.new-pdc-preview-state')).to_have_text(STALE)
    page.wait_for_timeout(600)
    assert len(requests) == 1, requests
    assert page.locator('.new-pdc-preview-viewer canvas').count() == 1, 'a stale frame is not a missing one'

    # The count, though, needs no new coarse-graining: the card re-derives on its own, and the frame it comes back
    # with answers the form as it stands (the tick included), which is why the staleness clears.
    page.locator('#new-count').fill('220')
    page.wait_for_function("() => document.querySelector('.new-pdc-preview-state').textContent"
                           f" === {DERIVED!r}", timeout=30000)
    assert len(requests) == 2, requests
    assert 'aggregation_number=220' in requests[1], requests[1]
    assert errors == [], errors


def test_the_empty_micelle_derives_with_no_coarse_graining_at_all(dashboard, live_page):
    """The first-class case: no protein, no CG step, one centre per molecule, and no guessed bond on a coarse file."""
    page, errors = live_page
    serve(page, answer(centres_pdb(), protein=None, chains=(), protein_beads=0, beads=3, clearance=None,
                       placement_shape='sphere', band=None, representation='one centre per molecule',
                       cost={'cg_cached': False, 'coarse_graining_seconds': 0.0, 'detergent_seconds': 0.0,
                             'placement_seconds': 0.001, 'seconds': 0.0005, 'cg_bytes': 0, 'cg_key': None}))
    open_panel(page, live_page.base_url, protein=None)
    derive(page)

    assert loaded_atoms(page, 3) == 3
    expect(page.locator('.new-pdc-preview-from')).to_contain_text('no protein (empty micelle)')
    expect(page.locator('.new-pdc-preview-cost')).to_contain_text('no coarse-graining')
    expect(page.locator('.new-pdc-preview-kept')).to_contain_text('nothing')
    expect(page.locator('.new-pdc-preview-beads')).to_contain_text('one centre per detergent')
    # The file carries no bond records at all, and a coarse file draws no guessed ones: three beads, no bonds.
    measured = page.locator('.new-pdc-preview-viewer').evaluate(MEASURE)
    assert measured['bonds'] == 0, f"{measured['bonds']} bonds drawn on a file that declares none"
    assert errors == [], errors


def test_the_beads_are_drawn_at_twice_the_models_radius_with_the_bond_guess_off(dashboard, live_page):
    """Measured off the loaded structure: the module's table doubled, and the file's own bonds and no others.

    The element every bead is written with is a neutral stand-in, so NGL's distance-based guess -- `inferBonds`, on by
    default -- draws head beads onto tail beads. The card switches it off, so the drawn bonds are the `CONECT` records
    `pdc_view.system_pdb` wrote, replicated per molecule, and nothing else.
    """
    page, errors = live_page
    serve(page, answer(placement_pdb()))
    open_panel(page, live_page.base_url)
    derive(page)
    loaded_atoms(page, 2 + MOLECULES * len(DDM_BEADS))
    measured = page.locator('.new-pdc-preview-viewer').evaluate(MEASURE)

    model_r_nm = 0.264
    # Every bead is written with the neutral `C` stand-in, so every bead is the model's R, doubled for the preview.
    assert set(round(value / 10.0, 4) for value in measured['radii']) == {round(2 * model_r_nm, 4)}, measured['radii']
    assert measured['parameters']['radiusScale'] * measured['parameters']['aspectRatio'] == 1, measured['parameters']
    expected = MOLECULES * len(DDM_BONDS + DDM_CONSTRAINTS)
    assert measured['bonds'] == expected, (
        f"{measured['bonds']} bonds drawn where the model bonds {expected}: the distance guess is back in")
    assert errors == [], errors
