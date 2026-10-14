"""The Complexes panel draws each bead at the radius its own size class has in the model.

A bead is not an atom: it has no element and no van der Waals radius, which is why every bead in these files is
written with a neutral stand-in element. A viewer left with the stand-in draws a ranking of sizes, not the model's
-- carbon and nitrogen are nearly the same size, while Martini 3's classes are R 0.264 / S 0.230 / T 0.191 nm. So
the panel sets each bead's own radius on the loaded structure (`ngl-beads.js`, the one table and the one call), and
this test reads those radii back off the loaded component and holds them to the table.

The second half is the precondition, and it is not optional: NGL infers bonds from the radii the file's elements
give, so a panel that grows its beads while still guessing would *invent more* bonds -- the defect that was fixed
twice already. The panel stops the guess when the file carries `CONECT` records, and the same measurement that
reads the radii here reads the drawn bonds, so a regression that let the guess back in fails in this file too.
(`tests/dashboard/browser/test_pdc_bonds_browser.py` holds the same assertion over the writer the run itself uses.)

The frame is a fixture rather than a run: the eleven beads of one DDM molecule are the coordinates the run's
`1_system/system.gro` held, repeated `MOLECULES` times, three nanometres apart so no two beads in different
molecules are near enough for a distance-based guess. It is written by `pdc_view.system_pdb` -- the writer the route
serves a run's own snapshot through -- so the element column this test resolves the classes from is the writer's own
output and not a second copy of its convention. No test reads the developer's workspace.
"""
import re
from pathlib import Path

from dashboard.execution.adapters import pdc_view
from tests.dashboard.support import DDM_BEADS, DDM_BONDS, DDM_CLASSES, DDM_CONSTRAINTS, DDM_PLACEMENT, ddm_moleculetype

MOLECULES = 6
SPACING_NM = 3.0

#: Martini 3's molecular-volume classes in nanometres, from `models/sugars/recognition.py`'s `RADII_NM`. Written out
#: here so the test fails if the panel's table and the model's ever disagree.
RADII_NM = {'R': 0.264, 'S': 0.230, 'T': 0.191}
NANOMETRE_TO_ANGSTROM = 10.0

INDEX = {
    'job_id': 'pdcbeads',
    'snapshots': [
        {'name': 'placement', 'time_ps': None, 'pdb': 'snapshots/placement.pdb', 'stage': '1_system',
         'atoms': len(DDM_PLACEMENT) * MOLECULES, 'verdict': None},
    ],
}

#: What the panel's viewer holds after the picture is loaded: every atom's resolved radius in angstroms, and the
#: drawn bond count with its pairs, read off the loaded structure (`compList[0].structure`, the seam this repo's
#: other viewer tests read a structure through).
MEASURE = """
(el) => {
  const structure = el.pdcStage.compList[0].structure;
  const radii = [];
  for (let index = 0; index < structure.atomCount; index += 1) {
    radii.push(structure.getAtomProxy(index).radius);
  }
  const store = structure.bondStore;
  const pairs = [];
  for (let index = 0; index < store.count; index += 1) {
    const first = store.atomIndex1[index] + 1;
    const second = store.atomIndex2[index] + 1;
    pairs.push(first < second ? [first, second] : [second, first]);
  }
  return {atoms: structure.atomCount, radii: radii, count: store.count, pairs: pairs};
}
"""


def placement_pdb():
    """The placement frame as the panel loads it: written by the writer a run's own snapshot goes through.

    `pdc_view.system_pdb` puts the moleculetype's own bonds on the frame as `CONECT` records, gives every detergent
    molecule its own residue, and writes each bead's size class in the element column -- the column NGL is handed and
    the one a class is resolved from. Six molecules three nanometres apart, so no two beads of different molecules
    are near enough for a viewer's distance-based guess to join them.
    """
    atoms = [{'residue_id': 2 + molecule, 'residue': 'DDM', 'name': name,
              'position': [xyz[0] + molecule * SPACING_NM, xyz[1], xyz[2]]}
             for molecule in range(MOLECULES) for name, xyz in zip(DDM_BEADS, DDM_PLACEMENT)]
    model = pdc_view.read_moleculetype_text(ddm_moleculetype(), source='detergent_CG.itp')
    return pdc_view.system_pdb(atoms, detergent_residue='DDM', topology=model,
                               title=f'placement frame ({MOLECULES} DDM molecules)')


def model_bonds():
    """The model's own bonds over the frame, by the bead serial the fixture gives each bead."""
    pairs = set()
    for molecule in range(MOLECULES):
        offset = molecule * len(DDM_BEADS)
        for first, second in (*DDM_BONDS, *DDM_CONSTRAINTS):
            pairs.add((min(offset + first, offset + second), max(offset + first, offset + second)))
    return pairs


def beads_in_order():
    """The bead name of every atom the fixture writes, in file order."""
    return [name for _ in range(MOLECULES) for name in DDM_BEADS]


def open_panel(page, live_page):
    """Drive the panel to the placement frame the way a reader does, and measure the loaded structure."""
    page.route('**/api/pdc/*/snapshots', lambda route: route.fulfill(json=INDEX))
    page.route('**/api/pdc/*/snapshots/**',
               lambda route: route.fulfill(body=placement_pdb(), content_type='text/plain'))
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')
    page.get_by_role('tab', name='Complexes', exact=True).click()
    page.evaluate("window.pdcSetRun('pdcbeads')")
    button = page.locator('#pdc-snapshots button').first
    button.wait_for(timeout=30000)
    button.click()
    page.wait_for_function(
        "() => document.querySelector('#pdc-viewer').pdcStage?.compList[0]?.structure?.atomCount === "
        f'{len(DDM_PLACEMENT) * MOLECULES}', timeout=30000)
    return page.locator('#pdc-viewer').evaluate(MEASURE)


def measured_radii_nm(measured):
    """Every bead's radius back off the loaded structure, in nanometres, in the order the fixture writes them.

    `None` is NGL's answer for an atom the file gave no radius and nothing set one on -- the state this test exists
    to distinguish from a bead drawn at its own size class.
    """
    return [None if value is None else round(value / NANOMETRE_TO_ANGSTROM, 4) for value in measured['radii']]


#: The two buffers the `ball+stick` representation draws from, read off the representation itself. NGL keeps the
#: balls in a sphere buffer and the sticks in a cylinder buffer, and the cylinder one is the one that carries its
#: two ends (`position1`/`position2`); each buffer's own `radius` attribute is the radius its impostor shader draws
#: with -- in Angstroms, times the view matrix, which is 1 -- so this measures what is drawn rather than what was
#: asked for. The two are told apart by that attribute and not by index, because an index is a fact about NGL's
#: internals while the two ends are a fact about a bond.
MEASURE_DRAWN = """
(el) => {
  const buffers = el.pdcStage.compList[0].reprList[0].repr.bufferList;
  const radii = (buffer) => {
    const attribute = buffer.geometry.attributes.radius;
    return attribute && attribute.array ? Array.from(attribute.array) : null;
  };
  const stick = buffers.find(buffer => buffer.geometry.attributes.position1);
  const ball = buffers.find(buffer => buffer !== stick);
  return {buffers: buffers.length, ball: radii(ball), stick: radii(stick),
          radiusParameters: el.pdcStage.compList[0].reprList[0].parameters};
}
"""
#: The module's own two numbers, read from the file rather than restated: this test holds what is *drawn* to what
#: `ngl-beads.js` says the app draws, and `test_ngl_beads.py` holds that file's numbers to their reasons.
MODULE = Path(__file__).resolve().parents[3] / 'dashboard/web/static/js/ngl-beads.js'
ASPECT = re.search(r'BEAD_ASPECT_RATIO\s*=\s*([0-9.]+)', MODULE.read_text())
assert ASPECT, 'ngl-beads.js states no BEAD_ASPECT_RATIO'
ASPECT_RATIO = float(ASPECT.group(1))
STICK_FRACTION = 1 / ASPECT_RATIO


def distinct(values):
    """The drawn radii that are actually there, to four decimals, with how many vertices carry each."""
    counts = {}
    for value in values:
        key = round(value, 4)
        counts[key] = counts.get(key, 0) + 1
    return counts


def measure_drawn(page):
    """The drawn ball and stick radii, once both buffers exist (a representation builds them asynchronously)."""
    page.wait_for_function("""() => {
      const component = document.querySelector('#pdc-viewer').pdcStage.compList[0];
      const representation = component && component.reprList[0] && component.reprList[0].repr;
      if (!representation || !representation.bufferList) return false;
      const withRadii = representation.bufferList.filter(buffer => buffer.geometry.attributes.radius);
      return withRadii.length === 2;
    }""", timeout=30000)
    return page.locator('#pdc-viewer').evaluate(MEASURE_DRAWN)


def test_the_sticks_are_thinner_and_the_balls_are_not_shrunk(dashboard, live_page):
    """Measured on the drawn buffers: the balls keep the model's own radius, the sticks are a quarter of it.

    This is the user's ask of 2026-10-14 -- "maybe the bonds can look a bit thinner" -- measured where a picture is
    actually decided, the radii the impostor shaders are handed. Before the change the same measurement was ball
    2.64 A / stick 1.32 A for the tail beads (and 2.30 / 1.15 for the sugar ones); the sticks are half of that now
    and the balls are unchanged, because `radiusScale` thins the stick while `aspectRatio` buys the ball back.
    """
    page, errors = live_page
    open_panel(page, live_page)
    drawn = measure_drawn(page)

    assert drawn['buffers'] == 2, 'ball+stick draws from two buffers: one for the balls, one for the sticks'
    ball_radii = sorted(distinct(drawn['ball']))
    stick_radii = sorted(distinct(drawn['stick']))
    model = sorted(round(radius * NANOMETRE_TO_ANGSTROM, 2) for radius in RADII_NM.values())  # T 1.91, S 2.30, R 2.64

    # The balls are the model's own radii -- nothing was shrunk to thin the sticks -- and there is one per class.
    assert ball_radii == model, f'the drawn balls are not the model radii: {ball_radii} against {model}'
    # The sticks are the module's fraction of exactly those radii: every drawn stick radius, divided by the
    # module's own fraction, is a radius the file states a bead class has.
    assert sorted(set(round(value / STICK_FRACTION, 4) for value in stick_radii)) == [2.30, 2.64], (
        f'the drawn sticks are not the module\'s fraction of the beads: {stick_radii} at 1/{ASPECT_RATIO}')
    # And the amount is pinned, not just the relationship: 1.32 A and 1.15 A were the drawn stick radii before.
    assert stick_radii == [0.575, 0.66], f'the drawn sticks are not half of what they were: {stick_radii}'
    assert drawn['radiusParameters']['radiusScale'] == STICK_FRACTION
    assert drawn['radiusParameters']['aspectRatio'] == ASPECT_RATIO
    assert errors == []


def test_the_panel_draws_each_bead_at_its_own_size_class_radius(dashboard, live_page):
    """The radii on the loaded structure are the model's, class by class: 2.64 / 2.30 / 1.91 A on an R-S-T frame.

    This is the acceptance, measured off the loaded structure rather than argued: the three classes are the model's
    three radii in the model's own proportion (R/S is 1.148), read from a frame whose beads span all three. Before the
    writer chose its stand-in element from each bead's class, the file a run is served wrote `C` for every bead, so
    `ngl-beads.js` resolved every bead to the model's R and this measurement was 2.64 A eleven times over for one
    molecule -- the sugar ring's small beads drawn at a tail bead's size. The fixture here used to write its element
    column by hand, which is how the panel's own measurement stayed green while the route's file was uniform; it is
    the writer's output now, so the two cannot part again.
    """
    page, errors = live_page
    measured = open_panel(page, live_page)

    assert measured['atoms'] == len(DDM_PLACEMENT) * MOLECULES
    drawn = measured_radii_nm(measured)
    expected = [RADII_NM[DDM_CLASSES[name]] for name in beads_in_order()]
    assert drawn == expected, (
        'the beads are not drawn at their own size classes: '
        f'{[value for value in drawn[:len(DDM_BEADS)]]} against {expected[:len(DDM_BEADS)]}')

    # The ratio, read off the structure rather than restated: one radius per class, and the three of them are the
    # model's R 0.264 / S 0.230 / T 0.191 -- not a stand-in element's, where carbon and nitrogen are nearly equal.
    by_class = {}
    for index, name in enumerate(beads_in_order()):
        by_class.setdefault(DDM_CLASSES[name], set()).add(drawn[index])
    assert {size: sorted(values) for size, values in by_class.items()} == {
        size: [radius] for size, radius in RADII_NM.items()}, f'the drawn radii are not the model\'s: {by_class}'
    assert len(set(drawn)) == 3, 'every bead class should be drawn at its own radius'
    # And the numbers themselves, in the unit a structure file carries: the model's radii in Angstroms, and the
    # R to S proportion the three of them state.
    assert {size: round(sorted(values)[0] * NANOMETRE_TO_ANGSTROM, 2)
            for size, values in by_class.items()} == {'R': 2.64, 'S': 2.30, 'T': 1.91}, by_class
    assert round(sorted(by_class['R'])[0] / sorted(by_class['S'])[0], 3) == 1.148, by_class
    assert errors == []


def test_the_true_radii_do_not_let_the_bond_guess_back_in(dashboard, live_page):
    """Bigger beads must not buy bigger bonds: the drawn bonds are still the model's, not a distance guess.

    NGL's `inferBonds` defaults to `'all'`, and a bead written with a stand-in element puts head beads within a
    generous guess of tail beads -- measured at 90 bonds on a frame the model bonds 60 ways, `S1A-TAIL1` among
    them. The panel switches the guess off when the file carries `CONECT` records, and this measurement is the same
    one that reads the radii, so a change that grew the beads while re-enabling the guess fails here.
    """
    page, errors = live_page
    measured = open_panel(page, live_page)

    drawn = {tuple(pair) for pair in measured['pairs']}
    model = model_bonds()
    assert measured['count'] == len(model), (
        f'the panel drew {measured["count"]} bonds where the model has {len(model)}: '
        f'{len(drawn - model)} of them are not the model\'s')
    assert drawn == model, f'the drawn bonds are not the model\'s: {sorted(drawn ^ model)}'
    assert (1, 9) not in drawn and (1, 10) not in drawn, 'S1A-TAIL1/S1A-TAIL2 are the guess this test exists for'
    assert errors == []
