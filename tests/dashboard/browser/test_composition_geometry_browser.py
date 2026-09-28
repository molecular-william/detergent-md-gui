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

# Every representation the panel asked for, with the selection and the colour it carries.
REPS = """(el, key) => (el.compositionStages?.[key]?.compList?.[0]?.reprList ?? []).map(repr => {
  const parameters = repr.parameters ?? repr.params ?? {};
  return {sele: parameters.sele, colour: parameters.color};
}).filter(repr => typeof repr.sele === 'string')"""

# The colour the panel gives the linkage beads, which is what marks those representations out.
LINKAGE_COLOUR = 0xDF203D


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


def _drawn(page, key):
    """The beads the panel draws in their own type colour."""
    return [name for rep in _reps(page, key) if rep['colour'] != LINKAGE_COLOUR for name in _names(rep['sele'])]


def _highlight(page, key):
    """The beads the panel draws in the linkage colour. The join asks for both at once, as one selection."""
    return [name for rep in _reps(page, key) if rep['colour'] == LINKAGE_COLOUR for name in _names(rep['sele'])]


def _colours(page, keys):
    """Bead name -> the colours it is drawn in, ignoring the linkage highlight."""
    colours = {}
    for key in keys:
        for rep in _reps(page, key):
            if rep['colour'] == LINKAGE_COLOUR: continue
            for name in _names(rep['sele']):
                colours.setdefault(name, set()).add(rep['colour'])
    return colours


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
    for residue, target in (('SUG', 2.30), ('TAI', 2.64)):
        drawn = radii.get(residue)
        assert drawn, (residue, radii)
        for value in drawn:
            assert abs(value - target) / target < 0.15, (residue, target, value)
    assert errors == []
