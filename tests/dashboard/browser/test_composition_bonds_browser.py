"""The Molecule Combination panel draws the model's bonds, not the viewer's guess.

The geometry writer puts the candidate's own bonded terms into the PDB as `CONECT` records, which is what makes the
picture the model rather than a fresh guess -- and the panel draws a colourless bond-only representation so the
bonds crossing between bead types survive the per-type colouring. But NGL invents bonds from interatomic distances
as well unless it is told otherwise (`inferBonds` defaults to `'all'`), and every bead is a radius stand-in
element, so the panel can draw the model's bonds *plus* a set the model does not have. A reader cannot then tell
which sticks are the linkage and which are the viewer's arithmetic.

The rule the Complexes panel already carries applies here unchanged: switch the guess off when, and only when, the
file states its own bonds. A file without `CONECT` records keeps NGL's bonds rather than being drawn as unconnected
dots, which is why the guard tests the text rather than switching inference off unconditionally.

Two files are held here, because the guarantee should not rest on a layout accident:

* the preview's own file, unmodified -- its layout spaces beads 3.5 A apart, outside NGL's cut-off, so it already
  draws the model's 6 bonds; this is the state the guard must not regress;
* the same file through `bond_fixtures.regrouped`, which keeps every serial, name and `CONECT` record and changes
  only the residue column (so NGL groups the beads into more than one residue) and the spacing -- the shape a real
  coarse-grained file has, and the only shape in which the guess runs. Without the guard this draws more bonds than
  the model has.

The expectation comes from the very PDB the viewer was handed (the preview response is intercepted), so the file and
the structure cannot be two different things, and the drawn bonds are read off the loaded structure through the
panel's own seam (`compositionStages`).
"""
import json

from tests.dashboard.bond_fixtures import atom_count, model_pairs, regrouped

HOST = '#compositions'

#: The drawn bonds as the viewer holds them, by 1-based structure index, through the same `bondStore` seam the
#: Complexes and overlay tests read.
BONDS = """(el, key) => {
  const structure = el.compositionStages?.[key]?.compList?.[0]?.structure;
  if (!structure || !structure.bondStore) return null;
  const store = structure.bondStore, pairs = [];
  for (let index = 0; index < store.count; index += 1) {
    const first = store.atomIndex1[index] + 1;
    const second = store.atomIndex2[index] + 1;
    pairs.push(first < second ? [first, second] : [second, first]);
  }
  return {atoms: structure.atomCount, count: store.count, pairs: pairs};
}"""


def _preview(page):
    from playwright.sync_api import expect

    page.locator('#composition-preview').click()
    expect(page.locator('#composition-panel-status')).to_contain_text('Preview ready', timeout=30000)


def _mounted(page):
    """Every panel's stage has loaded a structure, which is asynchronous in NGL."""
    page.wait_for_function(
        """selector => {
             const stages = document.querySelector(selector)?.compositionStages;
             return !!stages && Object.values(stages).length === 3
               && Object.values(stages).every(stage => stage.compList.length > 0
                    && stage.compList[0].structure && stage.compList[0].structure.bondStore);
           }""",
        arg=HOST, timeout=30000)


def _drawn(page, key, tries=24, pause_ms=250):
    for _ in range(tries):
        value = page.locator(HOST).evaluate(BONDS, key)
        if value:
            return value
        page.wait_for_timeout(pause_ms)
    raise AssertionError('the viewer never held the joined structure to read bonds from')


def _open_with_transform(page, live_page, transform):
    """Mount the panel on a file transformed by `transform`, and hold the drawn bonds to the file's own `CONECT`."""
    served = {}

    def capture(route):
        response = route.fetch()
        body = response.json()
        served[atom_count(body['pdb'])] = model_pairs(body['pdb'])
        route.fulfill(status=200, content_type='application/json',
                      body=json.dumps(dict(body, pdb=transform(body['pdb']))))

    page.route('**/api/compositions/preview', capture)
    page.goto(f'{live_page.base_url}/detergent-validation/combinations')
    _preview(page)
    _mounted(page)

    measured = _drawn(page, 'joined')
    assert measured['atoms'] in served, \
        f'the drawn structure holds {measured["atoms"]} atoms, which is not a file this view was served: {sorted(served)}'
    model = served[measured['atoms']]
    assert model, 'this composition carries no bonds, so the view has none to be held to'
    drawn = {tuple(pair) for pair in measured['pairs']}

    assert measured['count'] == len(model), (
        f'the panel drew {measured["count"]} bonds where the model has {len(model)}: '
        f'{len(drawn - model)} of them are not the model\'s')
    assert drawn == model, f'the drawn bonds are not the model\'s: {sorted(drawn ^ model)}'


def test_the_join_draws_the_models_bonds_rather_than_guessing_them(dashboard, live_page):
    page, errors = live_page
    # Same arrangement, brought inside NGL's cut-off: the bonds are the file's own, the spacing is the fixture.
    _open_with_transform(page, live_page, lambda pdb: regrouped(pdb, scale=0.2))
    assert errors == []


def test_the_join_draws_the_models_bonds_on_the_real_file_too(dashboard, live_page):
    page, errors = live_page
    _open_with_transform(page, live_page, lambda pdb: pdb)
    assert errors == []
