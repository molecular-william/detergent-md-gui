"""The New Run panel's system preview: the card, the ask, the refusal, and the stale frame.

Four claims, and each is the plan's:

* **the card is at the head of the right column and changes nothing about the layout** -- the two halves still sit
  side by side with equal widths at different x, and the paired rows still share a y;
* **the picture is asked for** -- `Derive the preview` sends one request, and a change to the protein, the subunit
  ticks or the mapping does *not* send another: it marks the frame as no longer this form's. The count, the style,
  the seed and the box margins do re-derive, because the coarse-grained protein is cached server-side;
* **a refusal is the builder's sentence and no picture** -- never a blank block, and never a drawing of a system the
  build would refuse;
* **the beads are drawn at three tenths of the model's radius, class by class, and coloured by their type family** --
  the radii read off the loaded structure are the module's own table times this card's own `PREVIEW_BEAD_SCALE`, each
  bead at the radius its own size class has and a bead the model does not size at the R stand-in, and each bead's
  colour is the Martini 3 polarity family the file's b-factor column carries; the drawn bonds are the file's `CONECT`
  records or none at all.
* **the empty micelle is derived from the detergent's own mapping** -- the panel hands the derive the mapping the
  detergent has saved, so the frame carries that mapping's beads and their types. A derive that carries none is a
  centres-only build -- one point per detergent, no moleculetype, hence no types -- and every bead's family code is
  the unstated zero, which is the defect the last test in this file pins from the request the card sends; and
* **the card shows what the placement measured** -- the shell the sites were placed on (and which number sized it),
  the detergent's own body as the clearance gate read it, and, when the requested count does not fit, the count the
  shape would hold offered as a control that writes it into the count field; and
* **the protein's backbone is coloured by its secondary structure, and its bonds can be made visible** -- the
  assignment the server keyed by this frame's residue numbers, one representation per class, with the three swatches
  beside the family legend and the assignment's own counts on the card; the Bonds control switches the protein's
  representations to licorice and leaves the detergent's alone, changing nothing the build derives.

The route is served as a fixture, so nothing here reads the developer's workspace, and the frames are written by
`pdc_view.system_pdb` -- the same writer a run's own snapshot goes through -- rather than being typed out by hand.
"""
import json
import re

from dashboard.execution.adapters import pdc_view
from playwright.sync_api import expect

from . import panels
from tests.dashboard.support import DDM_BEADS, DDM_BONDS, DDM_CLASSES, DDM_CONSTRAINTS, DDM_PLACEMENT, ddm_moleculetype

#: Martini 3's classes in nanometres, from `models/sugars/recognition.py`'s `RADII_NM`, written out so the preview's
#: measurement and the model's table cannot drift.
RADII_NM = {'R': 0.264, 'S': 0.230, 'T': 0.191}
NANOMETRE_TO_ANGSTROM = 10.0
#: The card's own reading scale -- the module's `BEAD_RADIUS_SCALE` at the value this preview wants, 0.3 since
#: 2026-10-14, when the user reported the beads too big twice and asked for 0.3. A bead is drawn at its own class'
#: radius times this, which is 0.792 / 0.690 / 0.573 A for R, S and T.
PREVIEW_BEAD_SCALE = 0.3

PROTEIN = {'id': 'molecules/1qj8/1qj8.pdb', 'name': '1qj8', 'path': 'molecules/1qj8/1qj8.pdb',
           'source': 'packaged', 'half_thickness_nm': 1.35, 'chains': ['A', 'B']}
CATALOG = {'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                          'template': 'molecules/DDM/micelle_template.json',
                          'registered_type': 'registered-template', 'files_present': True, 'missing_files': [],
                          'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
           'proteins': [PROTEIN],
           'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900, 'salt_molar': 0.15,
                        'box_margin_nm': 2.0, 'initial_z_nm': 6.0, 'contact_nm': 0.6,
                        'selection_threshold_fraction': 0.1}}
MAPPING_FILE = 'mapping_candidate_fixture.json'
#: The model the panel's picker is served, in the shape `/api/pdc/models` answers with: a saved mapping, the fit it
#: carries, and the sentence the picker shows. `fitted` is what a run consumes; the label is the server's, so this
#: fixture never decides fitted from derived.
MODEL = {'file': MAPPING_FILE, 'name': 'DDM draft', 'beads': len(DDM_BEADS), 'content_hash': 'ab' * 32,
         'fitted': {'revision': 2, 'terms': 26, 'term_kinds': {'bonds': 20, 'angles': 6},
                    'engine': 'fast-forward', 'created_at': '2026-10-22T06:35:10.928624+00:00',
                    'scientifically_validated': False},
         'label': (f'DDM draft · revision 2 · {len(DDM_BEADS)} beads · 26 terms · fitted 2026-10-22')}
MODELS = {'molecule': 'DDM', 'models': [MODEL]}

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


def empty_micelle_pdb(molecules=3):
    """An empty-micelle frame with the mapping's beads: no protein at all, one residue per detergent.

    The frame the preview draws when the form carries the detergent's mapping, written by the same writer a run's
    own snapshot goes through -- so the bead names, the element column and the family code column are the writer's
    rather than typed here.
    """
    atoms = []
    for molecule in range(molecules):
        for name, xyz in zip(DDM_BEADS, DDM_PLACEMENT):
            atoms.append({'residue_id': 1 + molecule, 'residue': 'DDM', 'name': name,
                          'position': [xyz[0] + molecule * 3.0, xyz[1], xyz[2]]})
    model = pdc_view.read_moleculetype_text(ddm_moleculetype(), source='detergent_CG.itp')
    return pdc_view.system_pdb(atoms, detergent_residue='DDM', topology=model,
                               title='placement preview (DDM, AN=3, mode=lattice, seed=20261013)')


def answer(pdb=None, *, valid=True, reasons=(), protein_beads=542, beads=1024, clearance: float | None = 0.5436,
           placement_shape='belt-torus', band: float | None = 3.1408, representation='the mapping\u2019s beads',
           cost=None, protein: str | None = '1qj8', chains=('A', 'B'), mode='lattice', aggregation=150,
           seed=20261013, shell: float | None = None, radius_source: str | None = None,
           body_profile: dict | None = None, body_profile_reason: str | None = None,
           bead_clearance: float | None = None, density: float | None = None,
           capacity: dict | None = None, secondary: dict | None = None,
           structure: dict | None = None):
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
                  'band_radius_nm': band, 'detergent_representation': representation,
                  # What the placement measured: the shell it placed on and which number decided its radius, the
                  # detergent's own body as the clearance gate read it, and -- when the requested count fails the
                  # gate -- the count the shape would hold.
                  'shell_radius_nm': shell, 'radius_source': radius_source,
                  'body_profile': body_profile, 'body_profile_reason': body_profile_reason,
                  'bead_clearance_nm': bead_clearance, 'estimated_density_per_nm3': density,
                  'capacity_aggregation': capacity,
                  # The assignment martinize2 coarse-grained the protein with, keyed by the frame's residue numbers:
                  # `None` for a build with no protein or an answer that carries no assignment, exactly as the
                  # service writes it.
                  'secondary_structure': secondary,
                  # The all-atom structure the beads were coarse-grained from -- a cache key and the URL that serves
                  # it, exactly as `pdc_preview.protein_structure_basis` writes one -- or `None` for a build with no
                  # protein, exactly as the service writes that.
                  'protein_structure': structure},
        'cost': cost or {'cg_cached': True, 'coarse_graining_seconds': 0.001, 'detergent_seconds': 0.074,
                         'placement_seconds': 0.005, 'seconds': 0.1017, 'cg_bytes': 50768,
                         'cg_key': '0423f94ce62e7698'},
    }


def serve(page, body, requests=None, structure=None):
    """Every read the panel makes before it can ask, and the route under test.

    `structure` is the all-atom PDB the preview's protein route answers with when the card asks for it. It is not
    routed at all when it is `None`, because a card whose basis names no structure must not ask -- and a test that
    routes a file nobody should fetch would hide exactly that.
    """
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=CATALOG))
    page.route(re.compile(r'/api/pdc/models\?'), lambda route: route.fulfill(json=MODELS))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))

    def route_preview(route):
        if requests is not None:
            requests.append(route.request.url)
        route.fulfill(json=body(route.request.url) if callable(body) else body)

    page.route(re.compile(r'/api/pdc/preview/placement'), route_preview)

    def route_structure(route):
        if requests is not None:
            requests.append(route.request.url)
        route.fulfill(status=200, content_type='text/plain', body=structure)

    if structure is not None:
        page.route(re.compile(r'/api/pdc/preview/protein'), route_structure)


def serve_raw(page, body):
    """Every read the panel makes before it can ask, with the preview route answering `body` as raw text.

    `serve`'s `route.fulfill(json=...)` serialises through JavaScript, where a float `nan` becomes `null` and the
    defect this file's last two tests are about cannot be reproduced at all: the body has to be the bytes Python's
    own JSON writer produced, bare `NaN` token and all.
    """
    page.route(re.compile(r'/api/pdc/catalog'), lambda route: route.fulfill(json=CATALOG))
    page.route(re.compile(r'/api/pdc/models\?'), lambda route: route.fulfill(json=MODELS))
    page.route(re.compile(r'/api/readiness\?'),
               lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.route(re.compile(r'/api/pdc/preview/placement'),
               lambda route: route.fulfill(status=200, content_type='application/json', body=body))


def open_panel(page, base_url, *, protein=PROTEIN['id']):
    return panels.open_pdc_new_run(page, base_url, protein=protein)


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
    panels.assert_side_by_side(page, '.new-run-inputs', '.new-run-settings')
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
    expect(page.locator('.new-pdc-preview-box')).to_contain_text('band of radius 3.14 nm')
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


def test_an_answer_a_browser_cannot_parse_is_not_read_as_a_refusal(dashboard, live_page):
    """The user's report, end to end: the server's answer carried a `nan`, and that must not be called a refusal.

    The server answered 4iar with a frame -- `valid: true` -- whose `clearance_nm` was `nan`, because 20 of its 928
    coarse-grained beads carry no position and a distance to a bead with no position is not a number. Python's
    `json.dumps` writes a `nan` as the bare token `NaN`, which a browser's `JSON.parse` refuses. The card's
    `response.json().catch(() => ({}))` swallowed that, and an empty object is an object with no `valid` and no
    `reasons`: the card then said "the builder refuses these inputs. Its own reason is: the build gave no reason" --
    two sentences the server never sent, about a picture the server had actually drawn. What happened is that the
    answer could not be read, and that is what the card says now.
    """
    page, errors = live_page
    body = json.dumps(answer(placement_pdb(), clearance=float('nan')))
    assert 'NaN' in body, 'the server writes the token this test is about'

    serve_raw(page, body)
    open_panel(page, live_page.base_url)
    derive(page)

    refusal = page.locator('.new-pdc-preview-refusal')
    expect(refusal).to_be_visible()
    expect(refusal).to_contain_text('No picture: the answer could not be read.')
    expect(refusal).to_contain_text('is not JSON this panel can parse')
    assert 'the builder refuses these inputs' not in refusal.inner_text(), refusal.inner_text()
    expect(page.locator('.new-pdc-preview-state')).to_have_text(
        'No answer came back to read; the sentence above says so.')
    assert page.locator('.new-pdc-preview-viewer canvas').count() == 0, 'an unreadable answer drew a picture'
    assert errors == [], errors


def test_a_refusal_with_no_sentence_of_its_own_names_the_step_that_refused(dashboard, live_page):
    """A refusal whose sentence is empty must still say what refused: the step, not "the build gave no reason".

    The service sends the step beside the sentences (`step: 'placement'`, from `pdc_preview._refusal`), so the card
    can name the gate even when the gate said nothing of its own. The bare phrase it used to fall back on named
    neither a step nor a cause.
    """
    page, errors = live_page
    serve(page, {**answer(valid=False, reasons=[], placement_shape='sphere', band=None, clearance=0.174),
                 'step': 'placement'})
    open_panel(page, live_page.base_url)
    derive(page)

    refusal = page.locator('.new-pdc-preview-refusal')
    expect(refusal).to_contain_text('No picture: the placement step refuses these inputs.')
    expect(refusal).to_contain_text('the placement step refused these inputs and named no reason of its own')
    assert 'the build gave no reason' not in refusal.inner_text(), refusal.inner_text()
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
    """The centres-only branch, chosen rather than inherited: no protein, no CG step, one centre per molecule.

    A build with no mapping writes one point per detergent and no topology, and this is what it looks like -- so the
    reader selects *no mapping* here instead of leaving the form on the detergent's own mapping, which is the panel's
    default (a centres-only frame is what that default used to be, and it is the frame every bead came back
    `family not stated` on; the last test in this file is the measurement of it).
    """
    page, errors = live_page
    serve(page, answer(centres_pdb(), protein=None, chains=(), protein_beads=0, beads=3, clearance=None,
                       placement_shape='sphere', band=None, representation='one centre per molecule',
                       cost={'cg_cached': False, 'coarse_graining_seconds': 0.0, 'detergent_seconds': 0.0,
                             'placement_seconds': 0.001, 'seconds': 0.0005, 'cg_bytes': 0, 'cg_key': None}))
    open_panel(page, live_page.base_url, protein=None)
    page.locator('#new-mapping').select_option('')
    derive(page)

    assert loaded_atoms(page, 3) == 3
    expect(page.locator('.new-pdc-preview-from')).to_contain_text('no protein (empty micelle)')
    expect(page.locator('.new-pdc-preview-cost')).to_contain_text('no coarse-graining')
    expect(page.locator('.new-pdc-preview-kept')).to_contain_text('nothing')
    expect(page.locator('.new-pdc-preview-beads')).to_contain_text('one centre per detergent')
    # The file carries no bond records at all, and a coarse file draws no guessed ones: three beads, no bonds.
    measured = page.locator('.new-pdc-preview-viewer').evaluate(MEASURE)
    assert measured['bonds'] == 0, f"{measured['bonds']} bonds drawn on a file that declares none"

    # And the choice is remembered per detergent, so the next mount does not put the form back onto a mapping:
    # choosing the centres-only build is a decision, not an untouched form.
    open_panel(page, live_page.base_url, protein=None)
    page.wait_for_function("() => document.querySelectorAll('#new-mapping option').length > 1", timeout=30000)
    assert page.locator('#new-mapping').input_value() == '', 'the reader\'s own choice was defaulted over'
    assert errors == [], errors


def test_the_preview_shows_the_shell_it_measured_and_the_count_that_fits(dashboard, live_page):
    """The measured shell and the capacity control, on one answer -- and the control queues nothing.

    Three facts the placement now records reached no card before: `shell_radius_nm` with the `radius_source` that
    decided it, the detergent's own `body_profile` as the clearance gate read it, and -- when the requested count
    fails the gate -- `capacity_aggregation`, the count the shape would hold. A reader asking for 150 molecules that
    do not fit is told what does fit, and the button writes that number into the count field rather than into a
    request of its own: the field's own `input` listener is what re-derives, so no POST is issued and nothing is
    queued. The request list is this file's own, and the POSTs are counted on the page's own event stream.
    """
    page, errors = live_page
    requests, posts = [], []
    page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
    serve(page, answer(placement_pdb(), placement_shape='sphere', band=None, shell=4.87, radius_source='measured',
                       body_profile={'bead_count': 11, 'length_nm': 2.1431, 'radial_nm': 0.4021, 'reach_nm': 2.2103,
                                     'head_source': 'polar-atoms', 'source': 'coordinates'},
                       bead_clearance=0.4123, density=0.3512,
                       capacity={'count': 24, 'seeds': [1, 2, 3], 'requested': 150}), requests)
    open_panel(page, live_page.base_url)
    derive(page)
    loaded_atoms(page, 2 + MOLECULES * len(DDM_BEADS))

    # The shell's sentence: the radius, which number decided it, the body the gate measured the clearance over, the
    # number itself, and the crowding -- joined, with nothing printed for a fact the answer did not carry.
    expect(page.locator('.new-pdc-preview-shell')).to_be_visible()
    expect(page.locator('.new-pdc-preview-shell')).to_have_text(
        'the shell is 4.87 nm - measured from the protein this selection includes - clearance measured against all '
        '11 beads of the detergent - closest bead to the protein 0.41 nm - 0.35 detergents per nm3')
    # The capacity: what fits, and over how many seeds the placer measured it.
    expect(page.locator('.new-pdc-preview-capacity')).to_be_visible()
    expect(page.locator('.new-pdc-preview-capacity')).to_have_text(
        'The placement measured what fits: about 24 detergents, over 3 seeds, at the 0.25 nm overlap gate.')
    button = page.locator('.new-pdc-preview-use-capacity')
    expect(button).to_be_visible()
    expect(button).to_have_text('Use 24')

    button.click()
    expect(page.locator('#new-count')).to_have_value('24')
    page.wait_for_timeout(600)
    assert posts == [], f'the control issued a request of its own: {posts}'
    # The re-derive is the count field's own: the frame is asked about the number the button wrote.
    assert any('aggregation_number=24' in url for url in requests), requests
    assert errors == [], errors


def test_the_beads_are_drawn_at_three_tenths_of_the_models_radius_with_the_bond_guess_off(dashboard, live_page):
    """Measured off the loaded structure: each bead at three tenths its own class' radius, and the file's own bonds.

    The card drew these beads twice the model's size until 2026-10-14, when the user asked for half; the same day's
    second report put them at 0.3, so the preview now reads the module's one table at its own `PREVIEW_BEAD_SCALE`
    (0.3) and a bead is drawn at three tenths the radius its class states -- 0.792 / 0.690 / 0.573 A for R, S and T.
    The frame is the writer's own output, so the classes are the ones
    `pdc_view.system_pdb` wrote: the detergent's sugar beads are the model's S (2.30 A), their ring virtual sites its
    T (1.91 A) and their tails its R (2.64 A) -- while the two protein beads are beads the detergent's moleculetype
    does not size, so they keep the stand-in, the model's R.

    The element a bead is written with is a neutral stand-in, so NGL's distance-based guess -- `inferBonds`, on by
    default -- draws head beads onto tail beads. The card switches it off, so the drawn bonds are the `CONECT` records
    `pdc_view.system_pdb` wrote, replicated per molecule, and nothing else.
    """
    page, errors = live_page
    serve(page, answer(placement_pdb()))
    open_panel(page, live_page.base_url)
    derive(page)
    loaded_atoms(page, 2 + MOLECULES * len(DDM_BEADS))
    measured = page.locator('.new-pdc-preview-viewer').evaluate(MEASURE)

    # The frame's beads in file order: the two protein beads first, then each detergent's eleven.
    beads = ['BB', 'SC1'] + [name for _ in range(MOLECULES) for name in DDM_BEADS]
    expected = [RADII_NM[DDM_CLASSES.get(name, 'R')] * PREVIEW_BEAD_SCALE for name in beads]
    drawn = [None if value is None else round(value / NANOMETRE_TO_ANGSTROM, 4) for value in measured['radii']]
    assert drawn == expected, f"not three tenths of the model's own radii: {drawn} against {expected}"
    # The acceptance, in the unit the structure carries: the model's three classes at the card's own scale, and the
    # R to S proportion, which no multiplier of the card's can change.
    radii_nm = {value for value in drawn if value is not None}
    assert sorted({round(value * NANOMETRE_TO_ANGSTROM, 2) for value in radii_nm}) == \
        sorted(round(radius * NANOMETRE_TO_ANGSTROM * PREVIEW_BEAD_SCALE, 2) for radius in RADII_NM.values()), drawn
    assert round(RADII_NM['R'] / RADII_NM['S'], 3) == 1.148
    assert measured['parameters']['radiusScale'] * measured['parameters']['aspectRatio'] == 1, measured['parameters']
    expected_bonds = MOLECULES * len(DDM_BONDS + DDM_CONSTRAINTS)
    assert measured['bonds'] == expected_bonds, (
        f"{measured['bonds']} bonds drawn where the model bonds {expected_bonds}: the distance guess is back in")
    assert errors == [], errors


#: Martini 3's polarity families as `ngl-beads.js` colours them, written out so this test is not the module's own
#: answer read back to itself.
FAMILY_COLOURS = {'unstated': '#cccccc', 'C': '#7048e8', 'N': '#e8590c', 'P': '#2f9e44', 'Q': '#2b6cb0'}
#: Each DDM bead's family, from the type the fixture's moleculetype gives it: the sugar beads are polar (`SP1r`),
#: the ring's virtual sites and the tails apolar (`TC4`, `C1`). A protein bead is named by no moleculetype, so its
#: family is not stated -- and neither is a bead an all-atom file writes.
DDM_FAMILIES = {'S1A': 'P', 'S1B': 'P', 'S1C': 'P', 'S1VS': 'C', 'S2A': 'P', 'S2B': 'P', 'S2C': 'P', 'S2VS': 'C',
                'TAIL1': 'C', 'TAIL2': 'C', 'TAIL3': 'C'}

#: What the picture's own colours and the legend under it are, read back off the loaded component and the DOM: the
#: representation's resolved per-atom colour (through the same registry the drawing uses), the colour parameters the
#: panel handed it, and every legend entry with its swatch's rendered background.
MEASURE_COLOURS = """
async (el) => {
  const structure = el.previewStage.compList[0].structure;
  const parameters = el.previewStage.compList[0].reprList[0].repr.getColorParams();
  const scheme = NGL.ColormakerRegistry.getScheme(parameters);
  const colours = [];
  for (let index = 0; index < structure.atomCount; index += 1) {
    colours.push(scheme.atomColor(structure.getAtomProxy(index)).toString(16).padStart(6, '0'));
  }
  const entries = [...document.querySelectorAll('.new-pdc-preview [data-bead-legend] .bead-legend-item')].map(item => ({
    family: item.dataset.family,
    label: item.querySelector('.bead-legend-label').textContent,
    declared: item.querySelector('.bead-legend-swatch').dataset.colour,
    swatch: getComputedStyle(item.querySelector('.bead-legend-swatch')).backgroundColor,
  }));
  const module = await import('/static/js/ngl-beads.js');
  return {scheme: parameters.scheme, scale: parameters.scale, domain: parameters.domain, colours: colours,
          entries: entries,
          module: {order: module.BEAD_FAMILY_ORDER, colours: module.BEAD_FAMILY_COLOURS,
                   families: [module.beadFamily('SP1r'), module.beadFamily('SN6'), module.beadFamily('SP4r'),
                              module.beadFamily('TC4'), module.beadFamily('C1'), module.beadFamily('BB')]}};
}
"""


def rgb(hex_code):
    """A `#rrggbb` as the string `getComputedStyle` reports it."""
    value = hex_code.lstrip('#')
    return f'rgb({int(value[0:2], 16)}, {int(value[2:4], 16)}, {int(value[4:6], 16)})'


def test_the_beads_are_coloured_by_type_family_and_the_legend_says_which(dashboard, live_page):
    """Measured off the loaded frame and the DOM: every bead's colour is its type family's, and the legend names them.

    A bead's size class is one axis and its Martini 3 polarity family the other, so the family is what colour carries:
    `pdc_view.system_pdb` writes a code per bead in the file's b-factor column, and `BEAD_FAMILY_PARAMETERS` colours
    the representation from it. The frame spans two families (the sugar heads polar, the tails apolar), and its two
    protein beads -- beads no moleculetype names -- are drawn the neutral family-not-stated colour rather than being
    guessed into one. The legend under the canvas is read back from its own DOM: five entries, each named, each
    swatch the colour the module states for that family *and* the colour a bead of it resolves to on the canvas.
    """
    page, errors = live_page
    serve(page, answer(placement_pdb()))
    open_panel(page, live_page.base_url)
    derive(page)
    loaded_atoms(page, 2 + MOLECULES * len(DDM_BEADS))
    measured = page.locator('.new-pdc-preview-viewer').evaluate(MEASURE_COLOURS)

    # The panel asked for the family scheme, with the module's five-colour scale over its fixed domain -- never the
    # structure's own spread of codes, which would repaint a bead when a frame held different families.
    assert measured['scheme'] == 'bfactor', measured['scheme']
    assert measured['scale'] == [FAMILY_COLOURS[family] for family in measured['module']['order']], measured['scale']
    assert measured['domain'] == [0, 4], measured['domain']
    # The module's own rule, run in the page: the saved DDM mapping's types, and a name that names no family.
    assert measured['module']['families'] == ['P', 'N', 'P', 'C', 'C', 'unstated'], measured['module']['families']

    beads = ['BB', 'SC1'] + [name for _ in range(MOLECULES) for name in DDM_BEADS]
    expected = [FAMILY_COLOURS[DDM_FAMILIES.get(name, 'unstated')] for name in beads]
    drawn = ['#' + colour for colour in measured['colours']]
    assert drawn == expected, f"the beads are not drawn in their families' colours: {drawn} against {expected}"
    # The frame spans two *stated* families -- the polar heads and the apolar tails -- beside the two protein beads
    # no moleculetype names, which is what makes this a measurement of the colouring rather than of one family.
    stated = {colour for colour in drawn} - {FAMILY_COLOURS['unstated']}
    assert stated == {FAMILY_COLOURS['P'], FAMILY_COLOURS['C']}, f'not two families on the frame: {sorted(drawn)}'

    # The legend, read off the page: one entry per family, named, and its swatch is the colour the beads resolved.
    assert [entry['family'] for entry in measured['entries']] == measured['module']['order']
    for entry in measured['entries']:
        assert entry['declared'] == FAMILY_COLOURS[entry['family']], entry
        assert entry['swatch'] == rgb(FAMILY_COLOURS[entry['family']]), entry
    labels = {entry['family']: entry['label'] for entry in measured['entries']}
    assert labels == panels.BEAD_FAMILY_LABELS, labels
    assert errors == [], errors


def test_the_model_picker_shows_the_fit_and_still_sends_the_mappings_file(dashboard, live_page):
    """A reader chooses a detergent and then a model, by revision and terms rather than by a file name.

    The second control used to list mapping files. It lists the models `/api/pdc/models` answers with -- this
    detergent's saved mappings joined to their parameterization -- and the sentence beside the chosen one says what it
    carries: here revision 2 and its 26 terms, which is what makes a fitted model recognisable at the moment of
    choosing. The option's *value* is still the mapping file, because that file is the model's identity to the form,
    the preview and the run; the request the card sends is where that is checked, since a picker that showed the
    label and submitted the label would queue nothing.
    """
    page, errors = live_page
    requests = []
    serve(page, answer(empty_micelle_pdb()), requests)
    open_panel(page, live_page.base_url, protein=None)

    select = page.locator('#new-mapping')
    expect(select).to_have_value(MAPPING_FILE)
    shown = select.locator('option:checked')
    expect(shown).to_contain_text('revision 2')
    expect(shown).to_contain_text('26 terms')
    assert MAPPING_FILE not in shown.inner_text(), 'the picker still shows the mapping file'
    values = page.evaluate("Array.from(document.querySelectorAll('#new-mapping option')).map(o => o.value)")
    assert values == ['', MAPPING_FILE], values

    derive(page)

    assert len(requests) == 1, requests
    assert f'mapping_candidate={MAPPING_FILE}' in requests[0], requests[0]
    assert errors == [], errors


def test_the_empty_micelle_preview_is_the_detergents_own_mapping_and_carries_its_families(dashboard, live_page):
    """The defect, measured from the request the card sends: a derive with no mapping is a centres-only build.

    The panel opens on the detergent's own mapping, so the derive for an empty micelle carries `mapping_candidate`
    and the server writes that mapping's beads -- eleven per detergent, each with its own size class and its own
    Martini 3 polarity family -- instead of one point per molecule with no moleculetype behind it, which is the frame
    whose every bead read *family not stated*.

    The route is served per URL: a request carrying a mapping is answered with the writer's own empty-micelle frame
    and one that carries none with its centres-only frame, so what the card draws is decided by what it asked for
    rather than by a body the fixture picked.
    """
    page, errors = live_page
    requests = []

    def frame_for(url):
        mapped = 'mapping_candidate=' in url
        return answer(empty_micelle_pdb() if mapped else centres_pdb(),
                      protein=None, chains=(), protein_beads=0,
                      beads=3 * len(DDM_BEADS) if mapped else 3, clearance=None,
                      placement_shape='sphere', band=None,
                      representation="the mapping\u2019s beads" if mapped else 'one centre per molecule')

    serve(page, frame_for, requests)
    open_panel(page, live_page.base_url, protein=None)

    # What the form hands the derive: the mapping the store lists for this detergent, not the "no mapping" option a
    # centres-only frame is chosen with.
    assert page.locator('#new-mapping').input_value() == MAPPING_FILE
    derive(page)

    assert len(requests) == 1, requests
    assert f'mapping_candidate={MAPPING_FILE}' in requests[0], requests[0]
    assert loaded_atoms(page, 3 * len(DDM_BEADS)) == 3 * len(DDM_BEADS)
    measured = page.locator('.new-pdc-preview-viewer').evaluate(MEASURE_COLOURS)

    # Two stated families on DDM -- its sugar heads polar and its tails apolar, `#2f9e44` and `#7048e8` -- and every
    # bead in its own family's colour rather than in the neutral one a centres-only frame gives all of them.
    beads = [name for _ in range(3) for name in DDM_BEADS]
    drawn = ['#' + colour for colour in measured['colours']]
    expected = [FAMILY_COLOURS[DDM_FAMILIES[name]] for name in beads]
    assert drawn == expected, f'the empty micelle is not drawn in its beads\u2019 families: {drawn} against {expected}'
    stated = {colour for colour in drawn} - {FAMILY_COLOURS['unstated']}
    assert stated == {FAMILY_COLOURS['P'], FAMILY_COLOURS['C']} == {'#2f9e44', '#7048e8'}, sorted(drawn)

    # And the legend under it is the key to those colours: the polar and apolar swatches are the two the beads
    # resolved to, which is the picture the user asked for -- and the two families the frame holds are the two it
    # names, not one flat fill of the neutral colour.
    legend = {entry['family']: entry['swatch'] for entry in measured['entries']}
    assert legend['P'] == rgb(FAMILY_COLOURS['P']) and legend['C'] == rgb(FAMILY_COLOURS['C']), legend
    labels = {entry['family']: entry['label'] for entry in measured['entries']}
    assert labels == panels.BEAD_FAMILY_LABELS, labels
    assert errors == [], errors


# --- the protein's secondary structure, and its bonds ------------------------------------------------------------
#
# The assignment was computed and then dropped: `pdc_preview.preview` now puts it in `basis.secondary_structure`,
# keyed by the residue number this frame gives each protein residue, and the card colours the protein's backbone beads
# by their residue's class -- one representation per class, over NGL's own selections. What these two tests measure is
# that picture and that control, off the loaded frame rather than off the code that drew it: the colours the
# representations resolve to, the legend under them, and the shapes the Bonds control switches.

#: Four residues as martinize2 writes them, then the detergents. The writer renames every protein bead `PRO` whatever
#: amino acid it stands for and numbers the residues 1..4, which is what the assignment above is keyed by.
PROTEIN_RESIDUES = ['ALA', 'GLY', 'SER', 'THR']
#: The letters planted for them: two helices, one strand, one coil -- three classes in one frame.
PROTEIN_LETTERS = 'HHEC'
#: `ngl-beads.js`'s three class colours, written out so this file is not the module's answer read back to itself.
SECONDARY_COLOURS = {'helix': '#e03131', 'sheet': '#f59f00', 'coil': '#495057'}


def protein_frame(molecules=MOLECULES, *, residues=PROTEIN_RESIDUES):
    """A placement frame with a four-residue protein -- a backbone bead and one side chain each -- and the belt."""
    atoms = []
    for index, name in enumerate(residues, 1):
        atoms.append({'residue_id': index, 'residue': name, 'name': 'BB',
                      'position': [-0.6 + 0.4 * index, 0.0, 0.0]})
        atoms.append({'residue_id': index, 'residue': name, 'name': 'SC1',
                      'position': [-0.6 + 0.4 * index, 0.4, 0.0]})
    for molecule in range(molecules):
        for name, xyz in zip(DDM_BEADS, DDM_PLACEMENT):
            atoms.append({'residue_id': len(residues) + 1 + molecule, 'residue': 'DDM', 'name': name,
                          'position': [xyz[0] + molecule * 4.0, xyz[1], xyz[2]]})
    model = pdc_view.read_moleculetype_text(ddm_moleculetype(), source='detergent_CG.itp')
    return pdc_view.system_pdb(atoms, detergent_residue='DDM', topology=model,
                               title='placement preview (DDM, AN=2, mode=lattice, seed=20261013)')


FRAME_ATOMS = len(PROTEIN_RESIDUES) * 2 + MOLECULES * len(DDM_BEADS)


def secondary_basis(letters=PROTEIN_LETTERS):
    """The assignment the service puts in `basis.secondary_structure`, written the way it writes one."""
    table = {'H': 'helix', 'G': 'helix', 'I': 'helix', 'E': 'sheet', 'B': 'sheet'}
    classes = {str(number): table.get(letter, 'coil') for number, letter in enumerate(letters, 1)}
    summary = {name: 0 for name in SECONDARY_COLOURS}
    for name in classes.values():
        summary[name] += 1
    return {'source': 'mdtraj.compute_dssp', 'route': '-dssp', 'residues': len(letters),
            'letters': {str(number): letter for number, letter in enumerate(letters, 1)},
            'protein_residues': len(letters), 'classes': classes, 'summary': summary, 'detail': None}


#: Every representation's own selection, its resolved colours and the atoms it covers, read off the loaded component
#: -- the same seam the bead tests use (`el.previewStage.compList[0]`), so what is measured is what is drawn.
MEASURE_REPRESENTATIONS = """
(el) => {
  const component = el.previewStage.compList[0];
  const structure = component.structure;
  const atoms = [];
  for (let index = 0; index < structure.atomCount; index += 1) {
    const atom = structure.getAtomProxy(index);
    atoms.push({resname: atom.resname.trim(), atomname: atom.atomname.trim(), resno: atom.resno});
  }
  const reps = component.reprList.map(rep => {
    const parameters = rep.repr.getColorParams();
    // The selection string a representation was drawn with: this build keeps it on `getParameters()`, which is where
    // NGL itself reads it back from (`repr.parameters` does not carry it).
    const requested = rep.repr.getParameters();
    const sele = requested.sele || '*';
    // A selection object's `test` is a method only when the string parsed; a parse failure leaves a boolean, which is
    // what makes a mistyped selection fail a test here rather than quietly covering every atom.
    const selection = new NGL.Selection(sele);
    const test = selection.atomOnlyTest || selection.test;
    if (typeof test !== 'function') throw new Error(`the selection ${JSON.stringify(sele)} does not parse`);
    const scheme = NGL.ColormakerRegistry.getScheme(parameters);
    const covered = [], colours = [];
    for (let index = 0; index < structure.atomCount; index += 1) {
      const atom = structure.getAtomProxy(index);
      if (!test(atom)) continue;
      covered.push(index);
      colours.push(scheme.atomColor(atom).toString(16).padStart(6, '0'));
    }
    return {type: rep.repr.type, scheme: parameters.scheme, value: parameters.value || null, sele: sele,
            atoms: covered, colours: colours};
  });
  return {atoms: atoms, count: structure.atomCount, bonds: structure.bondStore.count, reps: reps};
}
"""


def drawn_colours(measured):
    """The colour each atom is drawn in, from the representations that cover it."""
    colours = {}
    for rep in measured['reps']:
        for index, colour in zip(rep['atoms'], rep['colours']):
            colours[index] = '#' + colour
    return colours


def test_the_protein_backbone_is_drawn_in_its_residues_class_colour_and_the_legend_names_the_three(
        dashboard, live_page):
    """Measured off the loaded frame: each backbone bead its residue's class, each side chain its family, one legend.

    Two residues are helix, one is a strand and one is coil, so a colouring that read one class for the whole protein
    would show one colour here. Every atom is covered exactly once -- the class representations and the complement
    below them are built from the same residue numbers -- and the detergents keep their polarity families, which is
    the other table the same module carries.
    """
    page, errors = live_page
    serve(page, answer(protein_frame(), secondary=secondary_basis(), protein_beads=len(PROTEIN_RESIDUES) * 2,
                       beads=FRAME_ATOMS, clearance=0.51))
    open_panel(page, live_page.base_url)
    derive(page)
    assert loaded_atoms(page, FRAME_ATOMS) == FRAME_ATOMS
    measured = page.locator('.new-pdc-preview-viewer').evaluate(MEASURE_REPRESENTATIONS)

    # The frame the writer wrote, read back: `PRO` for every protein bead, `BB` for its backbone, `DET` for the belt.
    assert measured['atoms'][0] == {'resname': 'PRO', 'atomname': 'BB', 'resno': 1}, measured['atoms'][0]
    residues = measured['atoms']
    backbone = [index for index, atom in enumerate(residues) if atom['resname'] == 'PRO' and atom['atomname'] == 'BB']
    sidechains = [index for index, atom in enumerate(residues)
                  if atom['resname'] == 'PRO' and atom['atomname'] == 'SC1']
    detergents = [index for index, atom in enumerate(residues) if atom['resname'] == 'DET']
    assert len(backbone) == 4 and len(sidechains) == 4 and len(detergents) == MOLECULES * len(DDM_BEADS)

    # No bead is drawn twice and none is dropped: the complement is the selections above it, not a second rule.
    covered = sorted(index for rep in measured['reps'] for index in rep['atoms'])
    assert covered == list(range(measured['count'])), covered

    colours = drawn_colours(measured)
    assert [colours[index] for index in backbone] == [SECONDARY_COLOURS['helix'], SECONDARY_COLOURS['helix'],
                                                      SECONDARY_COLOURS['sheet'], SECONDARY_COLOURS['coil']]
    # The protein's side chains have no secondary structure of their own, so they stay `family not stated`.
    assert {colours[index] for index in sidechains} == {FAMILY_COLOURS['unstated']}
    # And the belt is untouched by any of it: its beads are still their own polarity families' colours.
    names = [name for _ in range(MOLECULES) for name in DDM_BEADS]
    assert [colours[index] for index in detergents] == [FAMILY_COLOURS[DDM_FAMILIES[name]] for name in names]

    # The legend beside the picture is the key to those three colours, and it is the module's table that draws it.
    legend = page.locator('.new-pdc-preview .new-pdc-preview-secondary-legend')
    expect(legend).to_be_visible()
    entries = legend.locator('.bead-legend-item')
    assert entries.count() == 3
    names = [entries.nth(index).get_attribute('data-secondary-class') for index in range(3)]
    assert names == ['helix', 'sheet', 'coil'], names
    for index, name in enumerate(names):
        item = entries.nth(index)
        assert item.locator('.bead-legend-label').inner_text() == name
        assert item.locator('.bead-legend-swatch').get_attribute('data-colour') == SECONDARY_COLOURS[name]
        assert item.locator('.bead-legend-swatch').evaluate(
            "el => getComputedStyle(el).backgroundColor") == rgb(SECONDARY_COLOURS[name])

    # The counts are the server's own, printed beside the legend: a record of the assignment, not a measurement here.
    expect(page.locator('.new-pdc-preview-secondary')).to_contain_text('1qj8: 2 helix, 1 sheet, 1 coil')
    assert errors == [], errors


def test_the_bonds_control_switches_the_protein_to_licorice_and_leaves_the_detergent_alone(dashboard, live_page):
    """The control is a view of this frame: the protein's representations change shape, the belt's does not.

    The frame carries the model's own bonds as `CONECT` records, drawn at a quarter of a bead's radius -- which the
    beads at this card's 0.3 scale hide. `Bonds` redraws the protein's own representations as licorice, leaves the
    detergent's `ball+stick` where it was, asks the server for nothing and leaves the state line saying the frame on
    screen is the one this form asked for.
    """
    page, errors = live_page
    requests = []
    serve(page, answer(protein_frame(), secondary=secondary_basis(), protein_beads=len(PROTEIN_RESIDUES) * 2,
                       beads=FRAME_ATOMS, clearance=0.51), requests)
    open_panel(page, live_page.base_url)
    derive(page)
    assert loaded_atoms(page, FRAME_ATOMS) == FRAME_ATOMS

    def shapes():
        measured = page.locator('.new-pdc-preview-viewer').evaluate(MEASURE_REPRESENTATIONS)
        detergent, protein = [], []
        for rep in measured['reps']:
            names = {measured['atoms'][index]['resname'] for index in rep['atoms']}
            (detergent if 'DET' in names else protein).append(rep['type'])
        return {'detergent': detergent, 'protein': protein, 'bonds': measured['bonds']}

    before = shapes()
    assert before['protein'] and set(before['protein']) == {'ball+stick'}, before
    assert set(before['detergent']) == {'ball+stick'}, before
    assert before['bonds'] > 0, 'the frame carries no bond for the control to make readable'
    assert len(requests) == 1

    toggle = page.locator('.new-pdc-preview-bonds input')
    toggle.check()
    after = shapes()
    assert set(after['protein']) == {'licorice'}, after
    assert after['detergent'] == ['ball+stick'], f'the detergent was switched with the protein: {after}'
    assert after['bonds'] == before['bonds'], 'the control changed which bonds are drawn'
    # Nothing was asked of the server, and the frame is still the one the form asked for: this is a view, not a
    # different placement.
    assert len(requests) == 1, requests
    expect(page.locator('.new-pdc-preview-state')).to_have_text(DERIVED)

    toggle.uncheck()
    assert set(shapes()['protein']) == {'ball+stick'}
    assert errors == [], errors


def test_a_frame_with_no_assignment_says_so_and_colours_nothing_by_structure(dashboard, live_page):
    """martinize2's no-assignment case on the card: the reason it gave, no legend, and the beads in their families.

    A protein whose structure neither DSSP source could assign is a real build (it is what `-maxwarn 1` is for), so
    the card must neither invent a class nor leave a legend keyed to colours nothing resolved to. The frame is drawn
    as one representation, exactly as it was before there was an assignment to carry.
    """
    page, errors = live_page
    no_assignment = {'source': None, 'route': None, 'residues': 0, 'protein_residues': len(PROTEIN_RESIDUES),
                     'letters': {}, 'classes': {}, 'summary': None,
                     'detail': 'mdtraj is not importable: no module named mdtraj'}
    serve(page, answer(protein_frame(), secondary=no_assignment, protein_beads=len(PROTEIN_RESIDUES) * 2,
                       beads=FRAME_ATOMS, clearance=0.51))
    open_panel(page, live_page.base_url)
    derive(page)
    assert loaded_atoms(page, FRAME_ATOMS) == FRAME_ATOMS

    expect(page.locator('.new-pdc-preview-secondary')).to_contain_text(
        'No secondary structure is drawn: mdtraj is not importable: no module named mdtraj')
    expect(page.locator('.new-pdc-preview .new-pdc-preview-secondary-legend')).to_be_hidden()

    measured = page.locator('.new-pdc-preview-viewer').evaluate(MEASURE_REPRESENTATIONS)
    assert len(measured['reps']) == 1, 'an answer with no assignment drew more than one representation'
    colours = drawn_colours(measured)
    protein = [index for index, atom in enumerate(measured['atoms']) if atom['resname'] == 'PRO']
    assert protein and {colours[index] for index in protein} == {FAMILY_COLOURS['unstated']}, colours
    assert errors == [], errors


# --- the ribbon, under the beads --------------------------------------------------------------------------------
#
# The beads are a coarse-graining of a structure, and the picture now shows both: the server names the all-atom file
# martinize2 was handed in `basis.protein_structure`, the card asks that URL for it, and it is drawn as a ribbon in
# one neutral colour under the beads. What these tests measure on the loaded stage is which layer is which: two
# components, the ribbon's first (NGL draws its components in the order they were added) carrying one ribbon
# representation at less than full opacity and writing no depth, the frame's second carrying the bead representations
# and nothing else; the Ribbon control removing and adding the ribbon and touching no bead; and a protein-free answer
# producing one component and asking for no structure at all.

#: The cache key the stubbed basis names, and the URL that serves it -- the card is handed both and must build
#: neither, so this is what the request for the ribbon is asserted against.
ENTRY_KEY = '0123456789abcdef'
STRUCTURE = {'key': ENTRY_KEY, 'url': f'/api/pdc/preview/protein?key={ENTRY_KEY}'}


def peptide(residues=4, *, chain='A'):
    """An all-atom peptide in the columns NGL's own trace reads: `N`, `CA`, `C` and `O` per residue.

    Real peptide geometry -- 1.45 A `N`-`CA`, 1.45 A `CA`-`C`, 1.33 A `C`-`N` to the next residue -- because the
    viewer splits a polymer where its backbone stops being bonded, and a chain of residues spaced far apart arrives
    as separate pieces that `cartoon` draws nothing for. `HELIX`/`SHEET` records are not written: the ribbon is one
    neutral colour either way, and the classes in this picture are the *beads'* (`secondary_basis`), which is the
    other half of the claim.
    """
    lines, serial = [], 0
    for index in range(residues):
        base = 4.23 * index
        for name, xyz, element in (('N', (base, 0.0, 0.0), 'N'), ('CA', (base + 1.45, 0.2, 0.0), 'C'),
                                   ('C', (base + 2.90, 0.0, 0.0), 'C'), ('O', (base + 3.40, 1.10, 0.0), 'O')):
            serial += 1
            lines.append(f'ATOM  {serial:5d} {name:^4s} ALA {chain}{index + 1:4d}    '
                         f'{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00  0.00           {element}')
    return '\n'.join(lines) + '\nEND\n'


PEPTIDE = peptide()
PEPTIDE_ATOMS = 4 * 4


#: Every component on the stage, in the order NGL draws them, with the representation types and the two parameter
#: these tests are about -- and each structure's own atom names, which is how a layer is identified as the all-atom
#: protein or as the beads rather than by the order it happens to have been added in.
MEASURE_LAYERS = """
(el) => {
  return el.previewStage.compList.map(component => {
    const atomnames = new Set(), resnames = new Set();
    for (let index = 0; index < component.structure.atomCount; index += 1) {
      const atom = component.structure.getAtomProxy(index);
      atomnames.add(atom.atomname.trim());
      resnames.add(atom.resname.trim());
    }
    return {
      atoms: component.structure.atomCount,
      atomnames: [...atomnames], resnames: [...resnames], visible: component.visible,
      reps: component.reprList.map(rep => {
        const parameters = rep.repr.getParameters();
        return {type: rep.repr.type, sele: parameters.sele || '*',
                opacity: parameters.opacity, depthWrite: parameters.depthWrite};
      }),
    };
  });
}
"""


def layers(page, count, atoms):
    """Wait for `count` components on the stage, the last of them the `atoms`-bead frame, and read them off."""
    page.wait_for_function(
        """([count, atoms]) => {
          const stage = document.querySelector('.new-pdc-preview-viewer').previewStage;
          return !!stage && stage.compList.length === count
            && stage.compList[stage.compList.length - 1].structure.atomCount === atoms;
        }""", arg=[count, atoms], timeout=30000)
    return page.locator('.new-pdc-preview-viewer').evaluate(MEASURE_LAYERS)


def test_the_protein_is_a_ribbon_of_its_all_atom_structure_under_the_beads(dashboard, live_page):
    """Two components: the all-atom ribbon first and translucent, the frame's beads second and untouched.

    The ribbon is identified by its atoms, not by its position: it is the one whose backbone is `N`/`CA`/`C`/`O`, and
    the frame is the one whose atoms are the writer's beads (`BB`, `SC1`, ...). Two claims beyond "there are two" are
    what keep the beads readable on top of it -- the ribbon is at less than full opacity and writes no depth, so it
    cannot paint over a bead, and it is the component added first, which is the order NGL draws in. The legend stays
    one legend: the ribbon has no colour key of its own.
    """
    page, errors = live_page
    requests = []
    serve(page, answer(protein_frame(), secondary=secondary_basis(), protein_beads=len(PROTEIN_RESIDUES) * 2,
                       beads=FRAME_ATOMS, clearance=0.51, structure=STRUCTURE), requests, structure=PEPTIDE)
    open_panel(page, live_page.base_url)
    derive(page)

    measured = layers(page, 2, FRAME_ATOMS)
    ribbon, frame = measured

    assert ribbon['atoms'] == PEPTIDE_ATOMS, ribbon
    assert {'N', 'CA', 'C', 'O'} <= set(ribbon['atomnames']), ribbon['atomnames']
    assert 'ALA' in ribbon['resnames'] and 'DET' not in ribbon['resnames'], ribbon['resnames']
    assert len(ribbon['reps']) == 1, ribbon['reps']
    assert ribbon['reps'][0]['type'] == 'cartoon', ribbon['reps']
    assert ribbon['reps'][0]['opacity'] is not None and 0 < ribbon['reps'][0]['opacity'] < 1, ribbon['reps']
    assert ribbon['reps'][0]['depthWrite'] is False, 'a translucent ribbon that writes depth cuts the beads behind it'
    assert ribbon['reps'][0]['sele'] == '*', ribbon['reps']

    assert frame['atoms'] == FRAME_ATOMS, frame
    assert {'BB', 'SC1'} <= set(frame['atomnames']) and 'CA' not in frame['atomnames'], frame['atomnames']
    assert set(rep['type'] for rep in frame['reps']) == {'ball+stick'}, frame['reps']
    # The ribbon runs through the very atoms these beads were coarse-grained from, so the protein's bead
    # representations are translucent (and write no depth) while the detergent's stay solid: with both at full
    # opacity the cartoon is invisible under the beads it belongs to.
    detergent_reps = [rep for rep in frame['reps'] if str(rep['sele']).startswith('not (')]
    protein_reps = [rep for rep in frame['reps'] if not str(rep['sele']).startswith('not (')]
    assert detergent_reps and protein_reps, frame['reps']
    for rep in protein_reps:
        assert rep['opacity'] is not None and 0 < rep['opacity'] < 1, rep
        assert rep['depthWrite'] is False, rep
    for rep in detergent_reps:
        assert rep['opacity'] in (None, 1), 'the micelle is not under the ribbon and is not drawn as if it were'
    # The bead representations are the frame's, and the ribbon's representation is not among them: the two layers are
    # separate components, so the Bonds and Ribbon controls cannot redraw each other's.
    assert abs(sum(1 for rep in frame['reps'] if rep['type'] == 'cartoon')) == 0

    # The legend is still one key per question and no third for the ribbon: the family colours and the three classes.
    assert page.locator('.new-pdc-preview .bead-legend').count() == 2
    assert page.locator('.new-pdc-preview .bead-legend:not([hidden])').count() == 2

    # One request each: the card asked the URL the server named, and built no URL of its own.
    protein_requests = [url for url in requests if '/preview/protein' in url]
    assert len(protein_requests) == 1 and protein_requests[0].endswith(STRUCTURE['url']), requests
    assert len([url for url in requests if '/preview/placement' in url]) == 1, requests
    expect(page.locator('.new-pdc-preview-ribbon-note')).to_be_hidden()
    assert errors == [], errors


def test_the_ribbon_control_removes_and_adds_only_the_ribbon(dashboard, live_page):
    """The Ribbon switch beside Bonds is a view of this frame: one representation goes, the beads do not move.

    Unchecked, the ribbon component carries no representation at all and every bead representation is exactly what it
    was; checked again, one ribbon comes back. Nothing is asked of the server and the state line still says the frame
    on screen is the one this form asked for -- it is a way of looking at the frame, not a different frame.
    """
    page, errors = live_page
    requests = []
    serve(page, answer(protein_frame(), secondary=secondary_basis(), protein_beads=len(PROTEIN_RESIDUES) * 2,
                       beads=FRAME_ATOMS, clearance=0.51, structure=STRUCTURE), requests, structure=PEPTIDE)
    open_panel(page, live_page.base_url)
    derive(page)
    drawn = layers(page, 2, FRAME_ATOMS)
    assert len(requests) == 2, requests

    ribbon, frame = drawn
    assert [rep['type'] for rep in ribbon['reps']] == ['cartoon']
    bead_reps = frame['reps']
    assert bead_reps, 'the frame drew no bead'

    toggle = page.locator('.new-pdc-preview-ribbon input')
    assert toggle.is_checked(), 'the ribbon is drawn by default'

    toggle.uncheck()
    hidden = layers(page, 2, FRAME_ATOMS)
    assert hidden[0]['reps'] == [], hidden[0]
    # The same beads, the same selections -- now opaque, because the ribbon they were drawn translucent over is gone.
    assert [(rep['type'], rep['sele']) for rep in hidden[1]['reps']] == \
           [(rep['type'], rep['sele']) for rep in bead_reps], 'the control changed which beads are drawn'
    for rep in hidden[1]['reps']:
        assert rep['opacity'] in (None, 1), rep
    assert hidden[1]['atoms'] == frame['atoms']

    toggle.check()
    shown = layers(page, 2, FRAME_ATOMS)
    assert [rep['type'] for rep in shown[0]['reps']] == ['cartoon'], shown[0]
    assert [(rep['type'], rep['sele']) for rep in shown[1]['reps']] == \
           [(rep['type'], rep['sele']) for rep in bead_reps]
    protein_reps = [rep for rep in shown[1]['reps'] if not str(rep['sele']).startswith('not (')]
    assert protein_reps and all(rep['opacity'] is not None and 0 < rep['opacity'] < 1 for rep in protein_reps)

    # A view, not a derive: one request each, and the state line has not moved.
    assert len(requests) == 2, requests
    expect(page.locator('.new-pdc-preview-state')).to_have_text(DERIVED)
    assert errors == [], errors


def test_a_protein_free_frame_asks_for_no_structure_and_draws_one_component(dashboard, live_page):
    """An empty micelle coarse-grains nothing, so the basis names no structure -- and no ribbon is drawn or asked for.

    The negative half of the claim above: a card that fetched a ribbon anyway (or invented a URL for one) would put a
    layer on screen for a structure this build never had.
    """
    page, errors = live_page
    requests = []
    serve(page, answer(empty_micelle_pdb(), protein=None, chains=(), protein_beads=0,
                       beads=len(DDM_BEADS) * 3, clearance=None, placement_shape='sphere', band=None,
                       representation='the mapping\u2019s beads'), requests, structure=PEPTIDE)
    open_panel(page, live_page.base_url, protein=PROTEIN['id'])
    derive(page)

    measured = layers(page, 1, len(DDM_BEADS) * 3)
    assert len(measured) == 1, measured
    assert not any('/preview/protein' in url for url in requests), requests
    expect(page.locator('.new-pdc-preview-ribbon-note')).to_be_hidden()
    assert page.locator('.new-pdc-preview-ribbon input').is_checked(), 'the control is present and on by default'
    assert errors == [], errors
