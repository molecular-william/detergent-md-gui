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
molecules are near enough for a distance-based guess. It carries the model's own bonds as `CONECT` records and each
bead's size class as its stand-in element -- the convention `models/compositions/topology.py` writes and the
documented meaning of the element column these files carry. No test reads the developer's workspace.
"""
from tests.dashboard.support import DDM_BEADS, DDM_BONDS, DDM_CONSTRAINTS, DDM_PLACEMENT

MOLECULES = 6
SPACING_NM = 3.0

#: One DDM molecule's beads by size class, as the DDM mapping states them in its beads' `size` fields: the sugar
#: ring beads are small (S), the two ring virtual sites are tiny (T), and the three tail beads are regular (R).
CLASSES = {'S1A': 'S', 'S1B': 'S', 'S1C': 'S', 'S1VS': 'T', 'S2A': 'S', 'S2B': 'S', 'S2C': 'S', 'S2VS': 'T',
           'TAIL1': 'R', 'TAIL2': 'R', 'TAIL3': 'R'}
#: The stand-in element each class is written with in the element column.
ELEMENTS = {'R': 'C', 'S': 'N', 'T': 'H'}
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
    """The placement frame as the panel loads it: the model's bonds as CONECT, each bead's class as its element.

    The record layout is the one `pdc_view.system_pdb` writes, column for column, so the element column lands where
    NGL reads it (77-78) and the residue reads as `DET`.
    """
    lines = ['REMARK 950 TEST PLACEMENT: 6 DDM MOLECULES, ONE RESIDUE EACH',
             'REMARK 950 ELEMENTS ARE THE SIZE CLASS STAND-IN, NOT CHEMISTRY']
    records, serials = [], [[] for _ in range(MOLECULES)]
    for molecule in range(MOLECULES):
        for name, xyz in zip(DDM_BEADS, DDM_PLACEMENT):
            serial = len(records) + 1
            x, y, z = (round((xyz[0] + molecule * SPACING_NM) * NANOMETRE_TO_ANGSTROM, 3),
                       round(xyz[1] * NANOMETRE_TO_ANGSTROM, 3), round(xyz[2] * NANOMETRE_TO_ANGSTROM, 3))
            records.append(f'HETATM{serial:5d} {name[:4]:<4s} DET A{molecule + 1:4d}    '
                           f'{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {ELEMENTS[CLASSES[name]]:>2s}')
            serials[molecule].append(serial)
    conect = [f'CONECT{serials[molecule][first - 1]:5d}{serials[molecule][second - 1]:5d}'
              for molecule in range(MOLECULES) for first, second in (*DDM_BONDS, *DDM_CONSTRAINTS)]
    return '\n'.join(lines + records + conect + ['END']) + '\n'


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


def test_the_panel_draws_each_bead_at_its_own_size_class_radius(dashboard, live_page):
    """The radii on the loaded structure are the model's, class by class, and the ratio between them is its own."""
    page, errors = live_page
    measured = open_panel(page, live_page)

    assert measured['atoms'] == len(DDM_PLACEMENT) * MOLECULES
    drawn = measured_radii_nm(measured)
    expected = [RADII_NM[CLASSES[name]] for name in beads_in_order()]
    assert drawn == expected, (
        'the beads are not drawn at their own size classes: '
        f'{[value for value in drawn[:len(DDM_BEADS)]]} against {expected[:len(DDM_BEADS)]}')

    # The ratio, read off the structure rather than restated: one radius per class, and the three of them are the
    # model's R 0.264 / S 0.230 / T 0.191 -- not a stand-in element's, where carbon and nitrogen are nearly equal.
    by_class = {}
    for index, name in enumerate(beads_in_order()):
        by_class.setdefault(CLASSES[name], set()).add(drawn[index])
    assert {size: sorted(values) for size, values in by_class.items()} == {
        size: [radius] for size, radius in RADII_NM.items()}, f'the drawn radii are not the model\'s: {by_class}'
    assert len(set(drawn)) == 3, 'every bead class should be drawn at its own radius'
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
