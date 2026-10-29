"""The bead-assignment 3D overlay draws the model's bonds, not the viewer's guess.

`overlay3d.pdb_text` writes the molecule's own bonds as `CONECT` records -- that is what makes the picture the
mapping's molecule rather than a fresh guess -- but NGL invents bonds from interatomic distances as well unless it
is told otherwise: `inferBonds` defaults to `'all'`, and every atom here is a plain C/O/N stand-in, so the guess is
generous. When it fires, the panel draws the model's bonds *plus* a set the model does not have, and the reader has
no way to tell which sticks are chemistry and which are the viewer's arithmetic.

The rule the Complexes panel already carries applies here unchanged: switch the guess off when, and only when, the
file states its own bonds. A file without `CONECT` records keeps NGL's bonds rather than being drawn as unconnected
dots -- which is why the guard tests the text rather than switching inference off unconditionally.

The file under test is the panel's own, with one documented fixture change (`tests/dashboard/bond_fixtures.py`):
`regrouped` keeps every serial, coordinate and `CONECT` record and changes only the residue column, so NGL groups
the atoms into more than one residue -- the shape a real coarse-grained file has, and the only shape in which its
guess runs. Read off the real overlay file, the drawn count already equals the model's 24 (one `MOL` residue keeps
the guess out); this test holds the guarantee by rule rather than by that accident, and fails at the over-drawn
number without the guard.

The drawn bonds are read from the loaded structure through `compList[0].structure`, the seam this repository's other
viewer tests use.
"""
import json

from tests.harness.bond_fixtures import atom_count, model_pairs, regrouped

OVERLAY = '#mapping-editor-overlay3d'
MOLECULE = 'Maltose'

#: The drawn bonds as the viewer holds them: the count and the pairs, by 1-based structure index. `bondStore` is
#: where NGL keeps every bond a representation draws (`atomIndex1`/`atomIndex2` are 0-based structure indices).
BONDS = """(el) => {
  const structure = el.overlayStage?.compList?.[0]?.structure;
  if (!structure || !structure.bondStore) return null;
  const store = structure.bondStore, pairs = [];
  for (let index = 0; index < store.count; index += 1) {
    const first = store.atomIndex1[index] + 1;
    const second = store.atomIndex2[index] + 1;
    pairs.push(first < second ? [first, second] : [second, first]);
  }
  return {atoms: structure.atomCount, count: store.count, pairs: pairs};
}"""


def _seed_candidate(dashboard):
    """A scoped candidate in the fixture's workspace, saved the way the panel saves one."""
    from dashboard.models import mappings
    from dashboard.models.mappings import context as mapping_context

    context = dashboard.client.get(f'/api/mappings/context?molecule_id={MOLECULE}').get_json()['context']
    candidate = mappings.automatic_candidate(mapping_context.as_structure(context), MOLECULE)
    candidate['molecule_id'] = MOLECULE
    candidate['molecule_snapshot'] = context['snapshot']
    response = dashboard.client.post('/api/mappings/drafts', json=candidate)
    assert response.status_code == 201, response.get_json()
    return context, response.get_json()


def _open_editor(page, live_page):
    page.goto(f'{live_page.base_url}/detergent-validation/bead-assignment')
    page.locator('#tab-mappings').click()
    page.wait_for_function("() => document.querySelector('#mapping-molecule')?.options.length > 0", timeout=30000)
    page.locator('#mapping-molecule').select_option(MOLECULE)
    page.wait_for_function(f"() => document.querySelector('{OVERLAY}')?.overlayStage"
                           " && document.querySelector('" + OVERLAY + "').overlayStage.compList.length >= 2"
                           f" && document.querySelector('{OVERLAY}').overlayStage.compList[0]?.structure?.bondStore",
                           timeout=60000)


def _drawn(page, expression, ready=lambda value: bool(value), tries=24, pause_ms=250):
    """Read the viewer once it is holding what the read needs.

    `update()` clears the components before it rebuilds them, so a read that lands in that window meets an empty
    list. Retrying is the remedy, and it is bounded: if the view never draws, this raises with the expression that
    timed out rather than letting a later assertion fail for an unrelated reason.
    """
    for _ in range(tries):
        value = page.locator(OVERLAY).evaluate(expression)
        if ready(value):
            return value
        page.wait_for_timeout(pause_ms)
    raise AssertionError(f'the viewer never held what this read needs: {expression.strip()[:70]}')


def _drawn_holding_the_model_to_the_view(page, live_page, transform):
    """Open the editor on a file transformed by `transform`, and hold the drawn bonds to the file's own `CONECT`.

    The panel asks for more than one molecule while it mounts (the list's first and then the chosen one), so the
    files are keyed by how many atoms they write -- the drawn structure is matched to the file it was served, not to
    whichever request happened to arrive last.
    """
    served = {}

    def capture(route):
        response = route.fetch()
        body = response.json()
        served[atom_count(body['pdb'])] = model_pairs(body['pdb'])
        route.fulfill(status=200, content_type='application/json',
                      body=json.dumps(dict(body, pdb=transform(body['pdb']))))

    page.route('**/api/mappings/overlay3d', capture)
    _open_editor(page, live_page)

    measured = _drawn(page, BONDS)
    assert measured['atoms'] in served, \
        f'the drawn structure holds {measured["atoms"]} atoms, which is not a file this view was served: {sorted(served)}'
    model = served[measured['atoms']]
    assert model, 'this fixture molecule carries no bonds, so the view has none to be held to'
    drawn = {tuple(pair) for pair in measured['pairs']}

    assert measured['count'] == len(model), (
        f'the overlay drew {measured["count"]} bonds where the model has {len(model)}: '
        f'{len(drawn - model)} of them are not the model\'s')
    assert drawn == model, f'the drawn bonds are not the model\'s: {sorted(drawn ^ model)}'


def test_the_overlay_draws_the_models_bonds_rather_than_guessing_them(dashboard, live_page):
    page, errors = live_page
    _seed_candidate(dashboard)
    _drawn_holding_the_model_to_the_view(page, live_page, regrouped)
    assert errors == []


def test_the_overlay_draws_the_models_bonds_on_the_real_file_too(dashboard, live_page):
    """The unmodified overlay file: this is the state the guard must not regress."""
    page, errors = live_page
    _seed_candidate(dashboard)
    _drawn_holding_the_model_to_the_view(page, live_page, lambda pdb: pdb)
    assert errors == []
