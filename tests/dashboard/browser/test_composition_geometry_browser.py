"""Browser proof that the Molecule Combination panel mounts the CG geometry in NGL.

The panel used to draw three plotly scenes, whose one interactive advantage -- clicking a bead to choose the
linkage endpoint -- the two endpoint comboboxes now cover, so the picker and the renderer both went. It mounts
NGL stages instead: one structure per panel, separated by the residue the writer gives each fragment. These
tests read what the viewer actually loaded, not what the panel intended to load.

NGL stages live in the panel's closure, so the panel publishes them on the workspace element as its test seam
(`compositionStages`). The claims are the ones the plotly tests made: each fragment panel shows its own beads,
the linkage bead is highlighted in every view, and no virtual site is drawn as an atom. The bond count is not
re-proved here -- what a viewer draws bonds from is the CONECT records, and that is pinned in the unit test on
the writer, where the file is produced.
"""
from playwright.sync_api import expect

HEAD = '#composition-plot-head'
TAIL = '#composition-plot-tail'
JOINED = '#composition-plot-joined'
# The panel publishes its NGL stages on the workspace element, so this is where the seam is read.
HOST = '#compositions'

# One entry per bead, from the structure NGL is actually holding.
ATOMS = """(el, key) => {
  const structure = el.compositionStages?.[key]?.compList?.[0]?.structure;
  if (!structure) return null;
  const atoms = [];
  for (let index = 0; index < structure.atomCount; index += 1) {
    const atom = structure.getAtomProxy(index);
    atoms.push({name: atom.atomname, residue: atom.resname});
  }
  return atoms;
}"""

# Every representation the panel asked for, with the selection and the colour it carries -- and, the part that
# matters, the bead names the viewer actually matched for that selection. Reading the request alone is what let
# three blank panels pass these tests: the selections named beads in a syntax this NGL build does not resolve, so
# every representation drew nothing while every assertion about the requested text held.
REPS = """(el, key) => {
  const component = el.compositionStages?.[key]?.compList?.[0];
  const structure = component?.structure;
  return (component?.reprList ?? []).map(repr => {
    const parameters = repr.parameters ?? repr.params ?? {};
    const indices = (typeof parameters.sele === 'string' && structure?.getAtomIndices && window.NGL?.Selection)
      ? Array.from(structure.getAtomIndices(new window.NGL.Selection(parameters.sele))) : [];
    return {sele: parameters.sele, colour: parameters.color,
            names: indices.map(index => structure.getAtomProxy(index).atomname)};
  }).filter(repr => typeof repr.sele === 'string');
}"""

# Where the camera sits, and how far in it is zoomed. NGL opens at (0, 0, -10) with zoom 1, which is also where
# an autoView resolves to when the selection it was handed matched nothing -- so this pair is the difference
# between a framed structure and an empty rectangle.
CAMERA = """(el, key) => {
  const camera = el.compositionStages?.[key]?.viewer?.camera;
  if (!camera) return null;
  return {position: camera.position.toArray().map(value => Math.round(value * 100) / 100),
          zoom: Math.round(camera.zoom * 1000) / 1000};
}"""

# The colour the panel gives the linkage beads, which is what marks those representations out.
LINKAGE_COLOUR = 0xDF203D
# The bond-only representation is colourless: it carries connectivity rather than identity, so it is excluded
# wherever the question is which beads a panel draws in their type colours.
BOND_COLOUR = 0x555555


# The drawn ball radius, as NGL computes it: atomRadius x radiusScale x aspectRatio.
DRAWN_RADII = """(el, key) => {
  const component = el.compositionStages?.[key]?.compList?.[0];
  const structure = component?.structure;
  const params = component?.reprList?.[0]?.parameters ?? {};
  if (!structure || !params.radiusScale) return null;
  const radii = {};
  for (let index = 0; index < structure.atomCount; index += 1) {
    const atom = structure.getAtomProxy(index);
    const residue = String(atom.resname).slice(0, 3).trim();
    (radii[residue] ??= []).push(atom.vdw * params.radiusScale * params.aspectRatio);
  }
  return radii;
}"""


def _preview(page):
    page.locator('#composition-preview').click()
    expect(page.locator('#composition-panel-status')).to_contain_text('Preview ready', timeout=30000)


def _mounted(page):
    """Every panel's stage has loaded a structure, which is asynchronous in NGL."""
    page.wait_for_function(
        """selector => {
             const stages = document.querySelector(selector)?.compositionStages;
             return !!stages && Object.values(stages).length === 3
               && Object.values(stages).every(stage => stage.compList.length > 0
                    && stage.compList.every(comp => comp.reprList.length >= 2));
           }""",
        arg='#compositions', timeout=30000)


def _beads(page, selector, key):
    beads = page.locator(HOST).evaluate(ATOMS, key)
    assert beads, f'{selector} mounted no structure'
    return beads


def _reps(page, key):
    return page.locator(HOST).evaluate(REPS, key)


def _names(sele):
    return [name for name in sele.split(' or ')]


def test_preview_waits_for_the_catalogue_instead_of_posting_an_empty_fragment(dashboard, live_page):
    """The panel's first click used to build a fragment id with nothing after the colon.

    The Preview button is rendered with the tab, but its inputs are only real once the catalogue has arrived. In
    that window `sugar.value` is empty, the payload asks the server for the fragment named '', and the server
    answers about fragment ids -- so a click that arrived a moment too early looks exactly like a panel that does
    not render. The catalogue is held open here to make that window deterministic rather than a race.
    """
    page, errors = live_page
    posted = []
    page.route('**/api/compositions/preview',
               lambda route: (posted.append(route.request.post_data_json), route.continue_())[1])
    catalog = dashboard.client.get('/api/compositions/catalog').get_json()
    released = {'value': False}
    # Returning without fulfilling leaves the request pending: this is the window under test.
    page.route('**/api/compositions/catalog',
               lambda route: route.fulfill(json=catalog) if released['value'] else None)

    page.goto(f'{live_page.base_url}/#compositions')
    page.get_by_role('tab', name='Combinations', exact=True).click()
    page.wait_for_selector('#composition-preview', timeout=30000)
    page.wait_for_timeout(700)
    assert page.locator('#composition-preview').is_disabled(), 'the button must not be live before its inputs are'
    assert posted == [], 'a click this early must not reach the server at all'

    # Release the catalogue. The button becomes live, and what it posts names a real fragment.
    released['value'] = True
    page.reload()
    page.get_by_role('tab', name='Combinations', exact=True).click()
    page.wait_for_function("() => !document.querySelector('#composition-preview').disabled", timeout=30000)
    _preview(page)
    _mounted(page)
    assert posted, 'the released click should have reached the server'
    fragment = posted[-1]['head_fragment_id']
    assert not fragment.endswith(':'), f'the fragment id has no residue: {fragment!r}'
    assert errors == []


def _drawn(page, key):
    """The beads the panel draws in their own type colour."""
    ignore = (LINKAGE_COLOUR, BOND_COLOUR)
    return [name for rep in _reps(page, key) if rep['colour'] not in ignore for name in rep['names']]


def _highlight(page, key):
    """The beads the panel draws in the linkage colour. The join asks for both at once, as one selection."""
    return [name for rep in _reps(page, key) if rep['colour'] == LINKAGE_COLOUR for name in rep['names']]


def _colours(page, keys):
    """Bead name -> the colours it is drawn in, ignoring the linkage highlight."""
    colours = {}
    for key in keys:
        for rep in _reps(page, key):
            if rep['colour'] in (LINKAGE_COLOUR, BOND_COLOUR): continue
            for name in rep['names']:
                colours.setdefault(name, set()).add(rep['colour'])
    return colours


def test_every_representation_matches_beads_and_the_view_is_framed(dashboard, live_page):
    """Blank panels with every part apparently in place: the selections matched nothing, and autoView framed it.

    This build parses a bare word as a residue name, so selections built from bead names (`A or B`, `C01`)
    resolved to no atoms. Each representation therefore drew nothing, and autoView(selection) asked for the centre
    and zoom of a selection that had no atoms -- which is the camera's own starting place, so the view never moved
    off the origin. Nothing threw and nothing logged, and the tests above passed throughout, because they asserted
    the selections the panel asked for rather than the beads the viewer matched. Both, plus the camera, are the
    regression.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#compositions')
    _preview(page)
    _mounted(page)

    for key in ('head', 'tail', 'joined'):
        reps = _reps(page, key)
        assert reps, f'{key} asked for no representations'
        for rep in reps:
            assert rep['names'], f"{key} representation {rep['sele']!r} matches no bead"
        camera = page.locator(HOST).evaluate(CAMERA, key)
        assert camera and (camera['position'] != [0, 0, -10] or camera['zoom'] != 1), \
            f'{key} is still at the camera NGL opens with: {camera}'
    assert errors == []


def test_the_panel_mounts_both_fragments_and_the_join_with_the_linkage_beads_highlighted(dashboard, live_page):
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#compositions')
    _preview(page)
    _mounted(page)

    for selector in (HEAD, TAIL, JOINED):
        expect(page.locator(selector).locator('canvas')).to_be_visible()

    head = _beads(page, HEAD, 'head')
    tail = _beads(page, TAIL, 'tail')
    joined = _beads(page, JOINED, 'joined')

    # One structure per panel, holding every bead: what separates the views is which beads each panel is told
    # it owns, so the fragment split is asserted on what it draws rather than on an atom count.
    assert (len(head), len(tail), len(joined)) == (6, 6, 6), (head, tail, joined)
    residues = {atom['name']: atom['residue'] for atom in joined}
    assert sorted(residues.values()) == ['SUG', 'SUG', 'SUG', 'TAI', 'TAI', 'TAI'], residues
    assert 'VS' not in residues
    assert sorted(_drawn(page, 'head')) == sorted(atom['name'] for atom in head if atom['residue'] == 'SUG')
    assert sorted(_drawn(page, 'tail')) == sorted(atom['name'] for atom in tail if atom['residue'] == 'TAI')
    assert sorted(_drawn(page, 'joined')) == sorted(atom['name'] for atom in joined)
    # One colour per bead type: a bead shown in more than one panel keeps a single colour.
    colours = _colours(page, ('head', 'tail', 'joined'))
    assert colours and all(len(values) == 1 for values in colours.values()), colours

    # Each fragment highlights exactly the endpoint the linkage currently attaches to, and the join both.
    head_endpoint = page.locator('#composition-head-endpoint').input_value()
    tail_endpoint = page.locator('#composition-tail-endpoint').input_value()
    assert _highlight(page, 'head') == [head_endpoint]
    assert _highlight(page, 'tail') == [tail_endpoint]
    assert sorted(_highlight(page, 'joined')) == sorted([head_endpoint, tail_endpoint])

    caption = page.locator('#composition-geometry-basis').text_content()
    assert 'layout' in caption and 'minimised' in caption and 'CG' in caption
    assert errors == []


def test_choosing_another_endpoint_moves_the_highlight_in_every_view(dashboard, live_page):
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#compositions')
    _preview(page)
    _mounted(page)

    first = page.locator('#composition-head-endpoint').input_value()
    second = [atom['name'] for atom in _beads(page, HEAD, 'head') if atom['name'] != first][0]

    page.locator('#composition-head-endpoint').select_option(second)
    _preview(page)
    _mounted(page)

    assert _highlight(page, 'head') == [second]
    assert second in _highlight(page, 'joined')
    assert errors == []


def test_a_response_without_the_structure_file_says_so_instead_of_showing_nothing(dashboard, live_page):
    """A dashboard process older than the viewer returns geometry but no structure file.

    Not hypothetical: it is exactly what a process started before that field existed answers with, and the panel
    used to reply with three empty canvases and no explanation -- which is what made the report "nothing is
    rendered" cost a debugging session. The message has to name the cause and the remedy.
    """
    import json

    page, errors = live_page

    def without_pdb(route):
        body = route.fetch().json()
        body.pop('pdb', None)
        route.fulfill(status=200, content_type='application/json', body=json.dumps(body))

    page.route('**/api/compositions/preview', without_pdb)
    page.goto(f'{live_page.base_url}/#compositions')
    _preview(page)

    expect(page.locator('#composition-geometry-basis')).to_contain_text('Restart the dashboard')
    # The stages exist but hold nothing, which is what the message is explaining.
    assert page.locator(HOST).evaluate(
        '(el) => Object.values(el.compositionStages ?? {}).every(stage => stage.compList.length === 0)') is True
    assert errors == []


def test_the_drawn_bead_radii_match_what_the_size_classes_mean(dashboard, live_page):
    """The plan for this panel said to measure the drawn radii rather than assume them.

    NGL draws a ball at atomRadius x radiusScale x aspectRatio, and the first scale shipped here was a guess that
    ignored aspectRatio, which drew every bead twice its intended size. This reads the product back out of the
    viewer, so a drifting default or a changed scale fails here. Only R and S appear in the default composition;
    the T class needs another tail recipe.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#compositions')
    _preview(page)
    _mounted(page)

    radii = page.locator(HOST).evaluate(DRAWN_RADII, 'joined')
    assert radii, 'the viewer reported no radii'
    # Martini's molecular-volume classes are 2.64 / 2.30 / 1.91 A for R / S / T, which the writer maps to C / N.
    # The panel draws them larger than life -- at the physical size the beads are hard to tell apart at panel scale
    # -- and the multiplier is asserted here rather than absorbed into the target, so that neither the classes nor
    # the display size can drift without this test saying so.
    DISPLAY_SCALE = 5
    for residue, class_radius in (('SUG', 2.30), ('TAI', 2.64)):
        target = class_radius * DISPLAY_SCALE
        drawn = radii.get(residue)
        assert drawn, (residue, radii)
        for value in drawn:
            assert abs(value - target) / target < 0.15, (residue, target, value)
    assert errors == []


def test_every_panel_draws_the_bonds_that_cross_between_bead_types(dashboard, live_page):
    """NGL draws a stick only between two atoms inside one representation.

    The panel gives each bead type its own representation so that a bead keeps its colour in every view. That split
    also cut every bond crossing between types: the sugar ring's A and B share a colour and were drawn bonded, while
    C -- alone in its colour -- kept both of its ring bonds in the PDB and appeared as an orphan. The file was
    always right; the connectivity was a rendering artefact, which is why "not all particles are connected" could
    not be fixed in the writer. One bond-only representation over every bead a panel owns is the fix, and the
    property to hold is that each panel has a representation covering all of the beads it claims.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#compositions')
    _preview(page)
    _mounted(page)

    for key, selector, residue in (('head', HEAD, 'SUG'), ('tail', TAIL, 'TAI'), ('joined', JOINED, None)):
        fatoms = _beads(page, selector, key)
        beads = {atom['name'] for atom in fatoms if residue is None or atom['residue'] == residue}
        assert beads, (key, fatoms)
        covered = [set(rep['names']) for rep in _reps(page, key)]
        assert covered, f'{key} asked for no representations'
        assert any(beads <= names for names in covered), \
            f'{key} draws its beads only in separate representations, so the bonds between them are cut: {covered}'
    assert errors == []
