"""Browser proof that the mapping editor's 3D overlay draws the molecule and its beads where they are.

The bead editor draws each bead as a sphere at the mean of the atoms it maps, in the same three dimensions as the
molecule. That is the whole point of the view: a sphere that sat somewhere other than its atoms' centre would say
something false about the mapping. So the assertions here are about geometry rather than about mounting: the
sphere's position is compared with the mean of the atoms the mapping gives that bead, read from the structure the
viewer is actually holding.

Reads go through `_drawn`, not a bare `evaluate`. `update()` clears the viewer's components before it rebuilds them,
so a read that lands in that window finds an empty list -- which is exactly how this file failed once, under load,
with `Cannot read properties of undefined`. The read retries until the state it needs exists, and still fails loudly
if the view never draws: a widened timeout would only decide how long the failure takes.

The candidate is created through the panel's own route into the fixture's workspace, so nothing here touches a
developer's data and the fixture runs the current code.
"""
from playwright.sync_api import expect

OVERLAY = '#mapping-editor-overlay3d'
MOLECULE = 'Maltose'

# The viewer's stage, the molecule it holds, and the beads it holds -- read from the seam the panel publishes.
STAGE = """(el) => {
  const stage = el.overlayStage;
  if (!stage) return null;
  return {components: stage.compList.length,
          atoms: stage.compList.map(component => component.structure ? component.structure.atomCount : 0),
          beadReps: (stage.compList[1] ? (stage.compList[1].reprList || []) : []).map(repr => ({
            sele: (repr.parameters ?? {}).sele, radiusScale: (repr.parameters ?? {}).radiusScale,
            opacity: (repr.parameters ?? {}).opacity }))};
}"""

# Each bead atom's position beside the mean of the molecule atoms that bead maps: the claim under test. Guarded,
# because a component list that has just been cleared is a state this read can meet.
CENTRES = """(el) => {
  const stage = el.overlayStage;
  const molecule = stage?.compList?.[0]?.structure, beads = stage?.compList?.[1]?.structure;
  if (!molecule || !beads) return null;
  const out = [];
  for (let index = 0; index < beads.atomCount; index += 1) {
    const bead = beads.getAtomProxy(index);
    out.push({position: [bead.x, bead.y, bead.z].map(v => Math.round(v * 100) / 100),
              resname: bead.resname});
  }
  return out;
}"""

# A canvas point where the picker finds the bead component, so a click there is a click on a sphere.
BEAD_POINT = """(el) => {
  const stage = el.overlayStage, canvas = stage.viewer.renderer.domElement;
  const rect = canvas.getBoundingClientRect();
  for (let iy = 2; iy < 30; iy += 1) {
    for (let ix = 2; ix < 30; ix += 1) {
      const x = rect.width * ix / 30, y = rect.height * iy / 30;
      const pick = stage.pickingControls.pick(x, y);
      if (pick && pick.atom && ['R', 'S', 'T'].includes(String(pick.atom.resname || '').trim())) {
        return {x: rect.left + x, y: rect.top + y};
      }
    }
  }
  return null;
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


# What the click actually sees, so a failure names the reason instead of only the timeout.
CLICK_EVIDENCE = """(el) => {
  const stage = el.overlayStage, canvas = stage.viewer.renderer.domElement;
  const rect = canvas.getBoundingClientRect();
  el.__events = [];
  for (const type of ['mousedown', 'mouseup', 'click']) {
    el.addEventListener(type, event => el.__events.push(type + '@' + Math.round(event.clientX - rect.left)
      + ',' + Math.round(event.clientY - rect.top)), true);
  }
  for (let iy = 2; iy < 30; iy += 1) {
    for (let ix = 2; ix < 30; ix += 1) {
      const x = rect.width * ix / 30, y = rect.height * iy / 30;
      const pick = stage.pickingControls.pick(x, y);
      if (pick && pick.atom && ['R', 'S', 'T'].includes(String(pick.atom.resname || '').trim())) {
        return {point: [rect.left + x, rect.top + y], resname: pick.atom.resname, atomIndex: pick.atomIndex,
                isBeadComponent: pick.component === stage.compList[1], components: stage.compList.length};
      }
    }
  }
  return null;
}"""


def _drawn(page, expression, ready=lambda value: bool(value), tries=24, pause_ms=250):
    """Read the viewer once it is holding what the read needs.

    `update()` rebuilds the components on every assignment change: it clears them first, so a read inside that window
    meets an empty list. Retrying the read is the remedy, and it is bounded -- if the view never draws, this raises
    with the expression that timed out rather than letting a later assertion fail for an unrelated reason.
    """
    for _ in range(tries):
        value = page.locator(OVERLAY).evaluate(expression)
        if ready(value):
            return value
        page.wait_for_timeout(pause_ms)
    raise AssertionError(f'the viewer never held what this read needs: {expression.strip()[:70]}')


def _open_editor(page, live_page):
    page.goto(f'{live_page.base_url}/detergent-validation/bead-assignment')
    # The mapping tab carries aria-label="CG mappings", so its accessible name is not the text on the button. The
    # id is the one handle that does not depend on how it is labelled.
    page.locator('#tab-mappings').click()
    page.wait_for_function("() => document.querySelector('#mapping-molecule')?.options.length > 0", timeout=30000)
    page.locator('#mapping-molecule').select_option(MOLECULE)
    page.wait_for_function(f"() => document.querySelector('{OVERLAY}')?.overlayStage"
                           " && document.querySelector('" + OVERLAY + "').overlayStage.compList.length >= 2",
                           timeout=60000)


def test_the_overlay_draws_the_molecule_and_one_sphere_per_bead(dashboard, live_page):
    page, errors = live_page
    context, candidate = _seed_candidate(dashboard)
    _open_editor(page, live_page)

    expect(page.locator(OVERLAY).locator('canvas')).to_be_visible()
    state = _drawn(page, STAGE, lambda value: value and value['components'] >= 2 and all(value['atoms']))
    heavy = [atom for atom in context['atoms'] if atom['heavy']]
    with_atoms = [bead for bead in candidate['beads'] if bead.get('atoms')]
    assert state['atoms'] == [len(heavy), len(with_atoms)], state
    assert errors == []


def test_every_sphere_sits_at_the_centre_of_the_atoms_its_bead_maps(dashboard, live_page):
    """The claim the view makes, checked against the coordinates the viewer holds rather than the ones it sent."""
    page, errors = live_page
    context, candidate = _seed_candidate(dashboard)
    _open_editor(page, live_page)

    drawn = _drawn(page, CENTRES)
    positions = {atom['id']: [value * 10 for value in atom['xyz']] for atom in context['atoms']}
    expected = []
    for bead in candidate['beads']:
        mapped = [positions[atom_id] for atom_id in bead.get('atoms') or [] if atom_id in positions]
        if not mapped:
            continue
        expected.append([round(sum(point[axis] for point in mapped) / len(mapped), 2) for axis in range(3)])

    assert len(drawn) == len(expected), (drawn, expected)
    for sphere, centre in zip(drawn, expected):
        # Agreement to a hundredth of an angstrom is the coordinates agreeing: the server rounds its centres to four
        # decimals while this recomputes them from coordinates ten times larger, and 0.01 A is a fiftieth of a
        # carbon-carbon bond.
        assert all(abs(got - wanted) <= 0.02 for got, wanted in zip(sphere['position'], centre)), (sphere, centre)
    assert errors == []


def test_the_spheres_are_drawn_translucent_and_sized_by_their_class(dashboard, live_page):
    """Opacity and per-class colour are why the beads are a file and representations rather than shapes."""
    page, errors = live_page
    _seed_candidate(dashboard)
    _open_editor(page, live_page)

    reps = _drawn(page, STAGE, lambda value: value and value['beadReps'])['beadReps']
    assert reps, reps
    for rep in reps:
        assert rep['sele'] in ('R', 'S', 'T'), rep
        assert 0 < rep['opacity'] < 1, rep
        assert 0.8 < rep['radiusScale'] < 2.0, rep
    assert errors == []


#: The radius each sphere is drawn at, read off the representation rather than recomputed from the file. A sphere
#: is drawn at the atom radius the one helper wrote on the structure (`ngl-beads.js`, `radiusType: 'explicit'`),
#: times the representation's own scale.
RADII = """(el) => {
  const stage = el.overlayStage;
  const beads = stage?.compList?.[1]?.structure;
  if (!beads) return null;
  const radii = {};
  for (const element of (stage.compList[1].reprList || [])) {
    const repr = element.repr;
    if (!repr || repr.type !== 'spacefill' || !repr.getAtomRadius) continue;
    for (let index = 0; index < beads.atomCount; index += 1) {
      const atom = beads.getAtomProxy(index);
      const drawn = Math.round(repr.getAtomRadius(atom) * 1000) / 1000;
      if (drawn > 0) (radii[String(atom.resname).trim()] ??= []).push(drawn);
    }
  }
  return radii;
}
"""


def test_the_spheres_are_drawn_at_the_radius_their_own_size_class_has(dashboard, live_page):
    """T6: the overlay's spheres come out of `ngl-beads.js`, and the migration left this picture where it was.

    This panel drew the model's own radius through a table of its own -- a `spacefill` at `class radius / carbon's
    van der Waals radius`, with element `C` on every bead. It now reads the shared table and the shared call and is
    told to use what that wrote (`radiusType: 'explicit'`), so the sphere is the class radius and not an element's:
    measured on this vendored build, a `spacefill` left to its own default sizes a bead by that element, which ranks
    the classes and gets their proportions wrong (1.70 against 1.55 where the model's R/S is 1.15).
    """
    page, errors = live_page
    _seed_candidate(dashboard)
    _open_editor(page, live_page)

    radii = _drawn(page, RADII, lambda value: value and any(value.values()))
    assert radii, 'the viewer reported no sphere radii'
    table = {'R': 2.64, 'S': 2.30, 'T': 1.91}
    for size, values in radii.items():
        assert size in table, f'the viewer drew a sphere for {size!r}, which is not a size class'
        for value in values:
            assert abs(value - table[size]) < 0.005, (size, table[size], value)
    # Every bead in this file carries `C` in its element column, whose van der Waals radius is 1.70 A. A sphere
    # drawn at that would be an element's radius rather than the class's, and the two would then be 1.10 apart
    # where the model's R and S are 1.15 apart -- which is the defect this migration is here to not reintroduce.
    assert any(abs(value - 1.70) > 0.01 for values in radii.values() for value in values), radii
    assert errors == []


def test_clicking_a_sphere_selects_the_atoms_that_bead_maps(dashboard, live_page):
    page, errors = live_page
    _seed_candidate(dashboard)
    _open_editor(page, live_page)

    assert '0 heavy atoms selected' in page.locator('#mapping-selection-count').text_content()
    # Scrolled into view first: this point is in viewport coordinates, and an element far down the page would
    # otherwise be clicked about a thousand pixels away from where the sphere is.
    page.locator(OVERLAY).scroll_into_view_if_needed()
    evidence = _drawn(page, CLICK_EVIDENCE)
    assert evidence, 'no sphere was found to click'
    page.mouse.click(evidence['point'][0], evidence['point'][1])
    try:
        page.wait_for_function("() => !/^0 /.test(document.querySelector('#mapping-selection-count').textContent)",
                               timeout=8000)
    except Exception:
        events = page.locator(OVERLAY).evaluate('(el) => el.__events')
        raise AssertionError(f'click did not select: {evidence} events={events} '
                             f'status={page.locator("#mapping-editor-status").text_content()!r}')
    assert errors == []
