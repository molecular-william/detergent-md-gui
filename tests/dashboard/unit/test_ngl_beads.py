"""`ngl-beads.js` carries the model's radii, not a second opinion about them.

The panel draws a bead at the radius its size class has in Martini 3, and the one table of those radii is
`models/sugars/recognition.py`'s `RADII_NM`. A JavaScript copy of the numbers is unavoidable -- the viewer cannot
import Python -- so the copy is held here: if either table moves, this test fails rather than the picture quietly
drawing a size the model does not state. The element stand-ins are checked against the writer that uses them
(`models/compositions/topology.py`), because the panel reads a file that carries the class in that column.
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.models.compositions.topology import render_pdb  # noqa: E402
from dashboard.models.sugars import RADII_NM  # noqa: E402

from tests.harness.support import PACKAGE

SOURCE = PACKAGE / 'web/static/js/ngl-beads.js'
#: The mock of the new-run panel's preview, which draws the same beads and bonds without importing this module (a
#: standalone page carries no ES modules), so its copy of these numbers is held here like the table above.
DRAFT = PROJECT_ROOT / 'docs/superpowers/drafts/2026-10-13-pdc-system-preview-draft.html'
#: The complex panel and the shared New Run panel's pdc half ship with the pdc feature, not the engine.
PDC_JS = PROJECT_ROOT / 'packages/pdc/src/detergent_pdc/static/js'


def _constants(text, names):
    """`NAME = <number>` or `NAME = <number> / <other name>` out of a file, resolved in the order given."""
    values = {}
    for name in names:
        match = re.search(rf'{name}\s*=\s*([^;]+);', text)
        assert match, f'{name} is not in this file'
        values[name] = _resolve(match.group(1), values)
    return values


def _resolve(expression, values):
    """A one-term expression: a literal, a name already read, or a literal over one."""
    expression = expression.strip()
    if expression in values:
        return values[expression]
    if re.fullmatch(r'[0-9.]+', expression):
        return float(expression)
    match = re.fullmatch(r'([0-9.]+)\s*/\s*([A-Za-z_][A-Za-z0-9_]*)', expression)
    assert match and match.group(2) in values, f'cannot resolve {expression!r}'
    return float(match.group(1)) / values[match.group(2)]


def _table_body(text, name):
    """One `{...}` table's own body, out of the file's text, so two copies can be compared as written.

    Whitespace is dropped rather than preserved: one copy may wrap a long table over two lines, and a comparison
    that failed on a line break would be comparing the layout rather than the numbers.
    """
    match = re.search(rf'{name}\s*=\s*\{{([^}}]*)\}}', text)
    assert match, f'{name} is not in this file'
    return re.sub(r'\s+', '', match.group(1))


def _drawn_parameters(text):
    """The `radiusScale`/`aspectRatio` a file draws a bead view with, resolved from its own constants.

    Read from the *given* text rather than from `SOURCE`: a helper that silently reads one file while being handed
    another is how a comparison between two copies passes without comparing anything.
    """
    values = _constants(text, ('BEAD_ASPECT_RATIO', 'BEAD_STICK_FRACTION'))
    body = _table_body(text, 'BEAD_RADIUS_PARAMETERS')
    drawn = {}
    for key in ('radiusScale', 'aspectRatio'):
        match = re.search(rf'\b{key}\s*:\s*([^,}}]+)', body)
        assert match, f'{key} is not in BEAD_RADIUS_PARAMETERS'
        drawn[key] = _resolve(match.group(1), values)
    return values['BEAD_ASPECT_RATIO'], values['BEAD_STICK_FRACTION'], drawn


def test_the_ball_keeps_the_models_radius_and_the_stick_is_a_quarter_of_it():
    """The two knobs are independent, and the numbers say which is which: `radiusScale x aspectRatio` is 1.

    `ball+stick` draws the ball at `atomRadius x radiusScale x aspectRatio` and the stick at
    `atomRadius x radiusScale`, so the product being 1 is what keeps the drawn ball at the radius the model states
    while the radius scale -- and with it every bond -- thins. Both numbers are pinned: 1/4 is half of the 1/2 these
    views drew at before 2026-10-14, and the aspect ratio's own reciprocal is what makes the product 1.
    """
    aspect, fraction, drawn = _drawn_parameters(SOURCE.read_text())
    assert (aspect, fraction) == (4, 0.25), f'the drawn stick is not a quarter of the bead: 1/{aspect}'
    assert drawn == {'radiusScale': fraction, 'aspectRatio': aspect}, drawn
    assert drawn['radiusScale'] * drawn['aspectRatio'] == 1, 'the ball would not be drawn at the model\'s radius'


def test_the_run_view_and_the_preview_draw_a_bead_at_the_same_scale():
    """Two panels, one reader: the run view reads a bead at exactly the scale the New Run preview does.

    The value itself is pinned beside the call that uses it; this holds the two panels together, so the same mapped
    sugar cannot be drawn one size in the preview the reader approves and another in the run they then inspect.
    """
    panel = re.search(r'const BEAD_SCALE\s*=\s*([0-9.]+);', (SOURCE.parent / 'run-view-monitor.js').read_text())
    assert panel, 'the run view states no BEAD_SCALE'
    preview = re.search(r'PREVIEW_BEAD_SCALE\s*=\s*([0-9.]+);', (PDC_JS / 'new-run-pdc.js').read_text())
    assert preview, 'the New Run panel states no PREVIEW_BEAD_SCALE'
    assert float(preview.group(1)) == float(panel.group(1)), \
        f'the run view draws at {panel.group(1)} and the preview at {preview.group(1)}: one bead, two sizes'


def test_the_mock_draws_the_same_bead_and_bond_as_the_module():
    """The mock's copy of these numbers is the module's, because the preview and the run view draw one bead.

    A standalone page cannot import the module, so the numbers are repeated -- and a second copy is a second model
    unless something holds the two together. This is that hold: the radii table, the element stand-ins, the family
    table with its five colours and labels, the scale the preview reads at and the two representation parameters all
    have to be the module's.
    """
    module = SOURCE.read_text()
    draft = DRAFT.read_text()
    assert _table_body(draft, 'BEAD_RADII_NM') == _table_body(module, 'BEAD_RADII_NM')
    assert _table_body(draft, 'SIZE_ELEMENTS') == _table_body(module, 'SIZE_ELEMENTS')
    # The colour table too: a mock that decoded a bead with a different palette would be a second colouring.
    assert _table_body(draft, 'BEAD_FAMILY_COLOURS') == _table_body(module, 'BEAD_FAMILY_COLOURS')
    assert _table_body(draft, 'BEAD_FAMILY_LABELS') == _table_body(module, 'BEAD_FAMILY_LABELS')
    for text, name in ((module, 'ngl-beads.js'), (draft, 'the mock')):
        assert re.search(r"BEAD_FAMILY_ORDER\s*=\s*\[\s*'unstated',\s*'C',\s*'N',\s*'P',\s*'Q'\s*\]", text), \
            f'{name} states no family order'
    # The module's own scale is `1` -- a bead is drawn at the model's radius -- and the preview reads it at a scale
    # of its own: the panel's beads were drawn twice as large, the user's first report had them halved and the
    # second put them at 0.3, so the mock carries the number the reader approved.
    assert re.search(r'BEAD_RADIUS_SCALE\s*=\s*1\s*;', module)
    preview = re.search(r'PREVIEW_BEAD_SCALE\s*=\s*([0-9.]+);', draft)
    assert preview, 'the mock states no PREVIEW_BEAD_SCALE'
    assert float(preview.group(1)) == 0.3, 'the mock draws the beads at the scale the user asked for'
    # And the panel now draws it too: the mock's own preview scale is the panel's, so the picture the reader approved
    # and the picture the app builds cannot differ by the one number the preview adds for reading.
    panel = re.search(r'PREVIEW_BEAD_SCALE\s*=\s*([0-9.]+);', (PDC_JS / 'new-run-pdc.js').read_text())
    assert panel, 'the New Run panel states no PREVIEW_BEAD_SCALE'
    assert float(panel.group(1)) == float(preview.group(1)), 'the mock and the panel draw the preview at two scales'
    assert _drawn_parameters(draft) == _drawn_parameters(module)



def _table(name):
    match = re.search(rf'{name}\s*=\s*\{{([^}}]*)\}}', SOURCE.read_text())
    assert match, f'{name} is not in {SOURCE.name}'
    return match.group(1)


def _numbers(name):
    """One `{KEY: number}` table out of the module's text."""
    return {key.strip(): float(value) for key, value in re.findall(r'([A-Za-z]+)\s*:\s*([0-9.]+)', _table(name))}


def _strings(name):
    """One `{KEY: 'string'}` table out of the module's text."""
    return {key.strip(): value for key, value in re.findall(r"([A-Za-z]+)\s*:\s*'([A-Za-z]+)'", _table(name))}


def composition_pdb():
    """A composition PDB carrying one bead of every size class, written by its own renderer."""
    tail = {'beads': [{'name': 'T1', 'type': 'C1', 'mass': 54.0}], 'coordinates': [[0.0, 0.0, 0.0]]}
    mapping = {'beads': [{'name': 'R1', 'type': 'P1', 'size': 'R'},
                         {'name': 'S1', 'type': 'SP1', 'size': 'S'},
                         {'name': 'T2', 'type': 'TC4', 'size': 'T'},
                         {'name': 'T1', 'type': 'C1', 'size': 'R'}]}
    return render_pdb({'tail': tail, 'mapping': mapping,
                       'topology': {'bonds': [{'a': 'R1', 'b': 'S1', 'function': 1}]}})


def test_the_radii_table_is_the_models_own():
    """`BEAD_RADII_NM` and `recognition.RADII_NM` are the same three numbers, in the same unit (nanometres)."""
    assert _numbers('BEAD_RADII_NM') == {size: float(radius) for size, radius in RADII_NM.items()}


def test_the_element_stand_ins_are_the_ones_the_composition_writer_uses():
    """Each class' element in the file maps back to that class, as the composition writer writes them."""
    elements = {line[12:16].strip(): (line[17:20].strip(), line[76:78].strip()) for line
                in composition_pdb().splitlines() if line.startswith('HETATM')}
    stand_ins = _strings('SIZE_ELEMENTS')
    for name, (residue, element) in elements.items():
        if residue == 'SUG':                      # a head bead carries the mapping's own size class
            assert stand_ins[element] in RADII_NM, f'{name}: element {element} is not a class stand-in'
    assert len({stand_ins[element] for _, element in elements.values()}) == 3, elements


def test_the_element_stand_ins_are_the_ones_the_system_writer_writes():
    """The writer's element column is this module's table the other way round, so the panel reads back the class.

    `pdc_view.system_pdb` -- the writer the run's snapshot, the Complexes route and the preview all go through --
    resolves each bead's class and writes the stand-in element that class has; `sizeClassOf` turns that element back
    into the class. Two tables, one meaning: if either side moves, a bead is drawn at a size the model does not state.
    """
    from dashboard.analysis.runs import structures as pdc_view
    assert {element: size for size, element in pdc_view.SIZE_ELEMENTS.items()} == _strings('SIZE_ELEMENTS')
    # The composition writer's own choice is the same three stand-ins, which is the convention both readers describe.
    written = {line[76:78].strip() for line in composition_pdb().splitlines() if line.startswith('HETATM')}
    assert written == set(pdc_view.SIZE_ELEMENTS.values()), written
    # A bead whose class the model does not state is written as the R stand-in rather than a guessed smaller class.
    assert pdc_view.BEAD_ELEMENT == pdc_view.SIZE_ELEMENTS['R']
    assert pdc_view.size_class('') == 'R' and pdc_view.size_class(None) == 'R'


def test_the_size_class_a_bead_type_names_is_martini_3s_own():
    """The class comes from the moleculetype's type column, spelled the way this repository already reads it.

    Martini 3 prefixes a small bead's type with `S` and a tiny one's with `T`; a regular bead's type carries no
    prefix. `models/molecules/draft.py` reconciles a mapping's stated size with its bead type by that same letter,
    and the saved DDM mapping's types (`SP1r`, `SN6`, `TC4`, `C1`) read back as the sizes it states for them.
    """
    from dashboard.analysis.runs import structures as pdc_view
    classes = {bead_type: pdc_view.size_class(bead_type)
               for bead_type in ('SP1r', 'SN6', 'SP4r', 'TC4', 'C1', 'C2', 'TN2', '')}
    assert classes == {'SP1r': 'S', 'SN6': 'S', 'SP4r': 'S', 'TC4': 'T', 'C1': 'R', 'C2': 'R', 'TN2': 'T', '': 'R'}


def test_the_family_a_bead_type_names_is_martini_3s_polarity_family():
    """The family comes out of the same type column the class does: the first of `Q`/`P`/`N`/`C` after the prefix.

    The writer puts the code in the file and a panel turns it back into one of five colours, so both ends have to
    read the column the same way. A size-class prefix hides the family's own letter (`TC4` is tiny *and* apolar,
    `SN6` small *and* nonpolar), and a type whose letter is none of the four -- a water bead, a bead no mapping
    names, an empty column -- states no family rather than being guessed into one.
    """
    from dashboard.analysis.runs import structures as pdc_view
    families = {bead_type: pdc_view.bead_family(bead_type)
                for bead_type in ('SP1r', 'SN6', 'SP4r', 'TC4', 'C1', 'C4', 'P1', 'N1', 'Q5', 'TN2', 'WF1', '', None)}
    assert families == {'SP1r': 'P', 'SN6': 'N', 'SP4r': 'P', 'TC4': 'C', 'C1': 'C', 'C4': 'C', 'P1': 'P',
                        'N1': 'N', 'Q5': 'Q', 'TN2': 'N', 'WF1': 'unstated', '': 'unstated', None: 'unstated'}


def test_the_family_codes_are_the_order_the_modules_own_table_states():
    """The code the file carries is an index into `ngl-beads.js`'s `BEAD_FAMILY_ORDER`, so one list decides it.

    The writer numbers the families and the representation's colour scale is handed the same five in the same order,
    which is what makes code *k* the *k*-th colour rather than one the panel picked.
    """
    from dashboard.analysis.runs import structures as pdc_view
    assert list(pdc_view.BEAD_FAMILIES) == ['unstated', 'C', 'N', 'P', 'Q']
    assert [pdc_view.bead_family_code(bead_type)
            for bead_type in ('C1', 'N1', 'P1', 'Q5', '', 'TC4')] == [1, 2, 3, 4, 0, 1]
    order = re.search(r'BEAD_FAMILY_ORDER\s*=\s*\[([^\]]*)\]', SOURCE.read_text())
    assert order, 'ngl-beads.js states no BEAD_FAMILY_ORDER'
    assert re.findall(r"'([A-Za-z]+)'", order.group(1)) == list(pdc_view.BEAD_FAMILIES)
    # And the palette has one colour per code, so the scale a representation is handed is five long and not four.
    assert list(_colours('BEAD_FAMILY_COLOURS')) == list(pdc_view.BEAD_FAMILIES)
    assert re.findall(r'([A-Za-z]+)\s*:', _table('BEAD_FAMILY_LABELS')) == list(pdc_view.BEAD_FAMILIES)


def _colours(name):
    """One `{KEY: '#hex'}` table out of the module's text, as written."""
    return {key.strip(): value for key, value in re.findall(r"([A-Za-z]+)\s*:\s*'(#[0-9a-fA-F]{6})'", _table(name))}


def test_the_colour_table_covers_the_families_and_no_two_share_a_colour():
    """Five distinct colours, one per code, and the legend's labels name the same five keys."""
    colours = _colours('BEAD_FAMILY_COLOURS')
    assert list(colours) == ['unstated', 'C', 'N', 'P', 'Q'], colours
    assert len(set(colours.values())) == 5, f'two families would be drawn the same colour: {colours}'


def test_the_mocks_frames_carry_the_writers_own_family_codes():
    """The mock's embedded frames are the writer's output, so its pictures colour by the same column the app reads.

    The mock carries no Python and cannot re-derive a frame in the page, so its five frames are held here instead:
    every HETATM's b-factor column is a family code, a detergent bead states one of the four families and a protein
    bead -- which no moleculetype names -- is written `unstated`, and each frame spans more than one family (the
    polar sugar heads and the apolar tails), which is what makes the picture a colouring rather than one flat fill.
    """
    from dashboard.analysis.runs import structures as pdc_view
    frames = re.findall(r'<script type="text/plain" data-frame="(\w)"[^>]*>\n(.*?)\n</script>',
                        DRAFT.read_text(), re.DOTALL)
    assert len(frames) == 5, [key for key, _ in frames]
    for key, body in frames:
        detergent = set()
        for line in body.splitlines():
            if not line.startswith('HETATM'):
                continue
            code = int(round(float(line[60:66])))
            assert code in range(len(pdc_view.BEAD_FAMILIES)), f'frame {key}: {line!r}'
            if line[17:20].strip() == 'PRO':
                assert code == 0, f'frame {key}: a protein bead states a family: {line!r}'
            else:
                assert code != 0, f'frame {key}: a detergent bead states no family: {line!r}'
                detergent.add(code)
        assert len(detergent) >= 2, f'frame {key} is drawn in one family: {sorted(detergent)}'
        # And the element column is the size class the writer chooses per bead, not one stand-in for every bead:
        # each frame holds all three classes (R, S and the ring's T virtual sites).
        elements = {line[76:78].strip() for line in body.splitlines() if line.startswith('HETATM')}
        assert elements == set(pdc_view.SIZE_ELEMENTS.values()), f'frame {key} elements: {sorted(elements)}'


def test_the_scale_knob_defaults_to_the_models_own_radius():
    """`1` draws what the table states; a bigger number is a reading aid and never a new model."""
    assert re.search(r'BEAD_RADIUS_SCALE\s*=\s*1\s*;', SOURCE.read_text())


#: The four engine views that draw a bead, plus the protein-detergent preview card that is the fifth. Each used to
#: hold its own numbers -- a table, an element's van der Waals radius to divide by, or a scale of its own -- which is
#: one model in four places. `ngl-beads.js` is now the one table and the one call for all of them, and this is what
#: holds that: a fifth copy of either would be a fifth answer. `new-run-pdc.js` is the pdc feature's New Run panel's
#: system preview, which reads the same beads as the run's own viewer, at the one scale the reader asked both for
#: (0.3).
JS_DIR = SOURCE.parent
BEAD_VIEWS = (JS_DIR / 'compositions.js', JS_DIR / 'mapping-ngl.js', JS_DIR / 'run-view-monitor.js',
              JS_DIR / 'bonded-plot.js', PDC_JS / 'new-run-pdc.js')


def test_every_bead_view_reads_the_one_table_and_keeps_no_copy_of_it():
    for path in BEAD_VIEWS:
        text = path.read_text()
        assert re.search(r"from '(?:/static/js/|\./)ngl-beads\.js'", text), f'{path.name} does not read the one module'
        assert not re.search(r'(BEAD_RADII_NM|SIZE_RADII)\s*=\s*\{', text), f'{path.name} keeps a radii table of its own'
        assert not re.search(r'(BEAD_ASPECT_RATIO|VDW_CARBON)\s*=', text), f'{path.name} keeps a scale of its own'
        assert not re.search(r'\b0\.264\b', text), f'{path.name} spells a radius the model table already states'


def test_each_panel_states_its_own_scale_at_the_call():
    """The module's default is the model's own radius, and a panel that reads a bead differently says so where it draws.

    Every one of these views passes its scale rather than inheriting it, so the panel's answer is in the panel: `1`
    is the mapping overlay's, the composition preview reads the model's beads larger than life, and the run view and
    the New Run preview read them at 0.3 so a bonded pair reads as two beads rather than one lump.
    """
    compositions = (JS_DIR / 'compositions.js').read_text()
    assert 'applyBeadRadii(item.structure, {scale: BEAD_RADIUS_SCALE})' in compositions
    assert re.search(r'BEAD_RADIUS_SCALE\s*=\s*3\.75\s*;', compositions), \
        'the composition preview draws its beads larger than life, and that multiplier is its own'
    assert 'applyBeadRadii(beadStructure, {scale: 1})' in (JS_DIR / 'mapping-ngl.js').read_text()
    view = (JS_DIR / 'run-view-monitor.js').read_text()
    assert 'applyBeadRadii(component.structure, {scale: BEAD_SCALE,' in view, \
        'the run view does not pass its own scale to the one call that writes radii'
    assert re.search(r'const BEAD_SCALE\s*=\s*0\.3\s*;', view), \
        'the run view draws at the scale the reader asked for, and that multiplier is the panel\'s own'
    # The system preview reads its beads at a scale of its own since 2026-10-14, when the user reported the beads
    # too big, halved them and then asked for 0.3: the number is still the panel's own -- stated here, and held to
    # the mock's.
    new_run = (PDC_JS / 'new-run-pdc.js').read_text()
    assert 'applyBeadRadii(component.structure, {scale: PREVIEW_BEAD_SCALE})' in new_run
    assert re.search(r'PREVIEW_BEAD_SCALE\s*=\s*0\.3\s*;', new_run), \
        'the preview draws at the scale the user asked for, and that multiplier is the panel\'s own'
    bonded = (JS_DIR / 'bonded-plot.js').read_text()
    assert 'beadRadiusNm(bead.size' in bonded, \
        'the 3D bead diagram is Plotly, so it reads the table through `beadRadiusNm` rather than `applyBeadRadii`'
    assert 'MARKER_PIXELS_PER_NM = 72' in bonded, 'the diagram states its own pixels-per-nanometre factor'


#: The four bead views that draw the pdc system files -- the mock, the preview card, the Complexes panel and the run
#: view -- and where each adds the module's colour parameters to its representation. One table, one set of parameters,
#: so the same bead type is one colour in all four.
#: The Complexes panel's module now lives in the pdc feature; the other two are the engine's.
FAMILY_VIEWS = {PDC_JS / 'pdc.js': ['BEAD_FAMILY_PARAMETERS', 'renderBeadLegend'],
                PDC_JS / 'new-run-pdc.js': ['BEAD_FAMILY_PARAMETERS', 'renderBeadLegend'],
                JS_DIR / 'run-view-monitor.js': ['BEAD_FAMILY_PARAMETERS', 'renderBeadLegend']}


def test_every_bead_view_colours_from_the_one_family_table():
    """Each draw site adds the module's family parameters and fills its legend from the same module.

    The parameters name the scheme, the five-colour scale and the fixed domain, and the legend lists the same five
    families -- both out of `ngl-beads.js`, so neither the panel nor the mock can hold a palette of its own.
    """
    module = SOURCE.read_text()
    assert 'export const BEAD_FAMILY_PARAMETERS' in module
    assert 'export function renderBeadLegend' in module
    for path, markers in FAMILY_VIEWS.items():
        text = path.read_text()
        assert re.search(r"from '(?:/static/js/|\./)ngl-beads\.js'", text), f'{path.name} does not read the one module'
        for marker in markers:
            assert marker in text, f'{path.name} does not use {marker}'
        assert '...BEAD_FAMILY_PARAMETERS' in text, f'{path.name} draws beads without the family colour parameters'
        assert not re.search(r'BEAD_FAMILY_COLOURS\s*=\s*\{', text), f'{path.name} keeps a family palette of its own'
    draft = DRAFT.read_text()
    assert '...BEAD_FAMILY_PARAMETERS' in draft and 'renderLegend()' in draft
