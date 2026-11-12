"""Browser proof that CG Bond Interactions produces a parameterization and draws the model it belongs to.

The parameterization itself -- the model card, the fit job, the result, the `source` column and the revision
strip -- is proved in `test_bonded_parameterization_browser.py`, where every route it drives is stubbed. What is
left here is the rest of the panel: that the mapping selector reaches the model it names, that a mapping's
revisions replace the flat bonded-state list (D1), that the terms no engine fits -- a ring constraint, a virtual
site and its parents -- are shown and stay read-only (`:108-110`), and that the torsion switch still writes the
mapping's own options.
"""
import json
import re

from dashboard.models import mappings
from dashboard.models.bonded import parameterization
from dashboard.models.mappings import context as mapping_context
from playwright.sync_api import expect

#: A revision's topology with the two kinds the panel must never offer an editor for: a constraint, whose length is
#: the mapping's, and a `virtual_sitesn`, whose parents are bead names rather than atoms.
TOPOLOGY = """[ moleculetype ]
LIG1 1

[ atoms ]
1 SP1r 1 LIG1 B01 1 0 54
2 SP1r 1 LIG1 B02 2 0 54
3 SP1r 1 LIG1 B03 3 0 54

[ constraints ]
2 3 1 0.315

[ virtual_sitesn ]
1 2 2 3

[ bonds ]
1 2 1 0.32 5000
"""


def save_revision(mapping):
    """One real revision in the store, so the table is read from what a run would stage rather than from a stub."""
    return parameterization.save(mapping, {
        'engine': 'fast-forward', 'topology': TOPOLOGY,
        'options': {'constraints_threshold': 10000, 'temperature_k': 300, 'torsion_model': 'legacy'},
        'ensemble': {'frames': 20001}, 'checks': {}, 'aa_reference': None, 'diagnostics': []})


def save_mapping(dashboard, molecule='DDM', name=None):
    """One saved candidate built the way the editor builds it: scoped to a molecule and its snapshot.

    The catalogue route now lists one molecule's mappings, and it filters on both the molecule id and the snapshot the
    candidate was built from. A fixture that omits either is a mapping no molecule query can find, so the test saves
    the same construction the route's real caller does rather than a looser one.
    """
    context = dashboard.client.get(f'/api/mappings/context?molecule_id={molecule}').get_json()['context']
    candidate = mappings.automatic_candidate(mapping_context.as_structure(context), molecule)
    candidate['molecule_id'] = molecule
    candidate['molecule_snapshot'] = context['snapshot']
    if name:
        candidate['name'] = name
    return mappings.save_draft(candidate)


def choose_mapping(page, file, molecule=None):
    """Pick a mapping the way a reader does: its molecule first, then the option carrying that mapping's revision."""
    page.wait_for_function(
        "() => document.querySelectorAll('#bonded-molecule-select option').length > 0", timeout=30000)
    if molecule:
        page.locator('#bonded-molecule-select').select_option(molecule)
    page.wait_for_function(
        """(file) => Array.from(document.querySelectorAll('#bonded-parameterization-display option'))
          .some(option => option.value.startsWith(`revision:${file}:`) || option.value === `draft:${file}`)""",
        arg=file, timeout=30000)
    value = page.evaluate("""(file) => {
      const options = Array.from(document.querySelectorAll('#bonded-parameterization-display option'));
      const current = options.find(option => option.value.startsWith(`revision:${file}:`)
        && option.textContent.includes('current'));
      const draft = options.find(option => option.value === `draft:${file}`);
      return (current || draft || {}).value || '';
    }""", file)
    if page.locator('#bonded-parameterization-display').input_value() != value:
        page.locator('#bonded-parameterization-display').select_option(value)


def test_the_display_selector_is_the_only_history(dashboard, live_page):
    """D1, as the page: no state select, no revision strip, and a table that reads a revision rather than a state.

    The flat bonded-state store and the revision strip are gone from the codebase, not merely unshown: the display
    selector is the history, and nothing else lists revisions.
    """
    saved = save_mapping(dashboard)

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    # One display selector, showing this mapping's draft because it has no revision yet. The Mapping select is gone
    # from the viewing path; the element the New run door drives is present but hidden and is not a second choice.
    expect(page.locator('#bonded-parameterization-display')).to_have_value(f'draft:{saved["file"]}')
    expect(page.locator('#bonded-mapping-select')).to_be_hidden()
    page.wait_for_selector('.bonded-plot .plotly', timeout=30000)

    expect(page.locator('.bonded-state-select')).to_have_count(0)
    # One way a parameterization is produced, and the one place its revisions are read: the reference-free draft
    # and its button were removed, so a second entry point must not come back.
    expect(page.get_by_role('button', name='Fit this model')).to_have_count(1)
    expect(page.get_by_role('button', name='Generate reference-informed draft')).to_have_count(0)
    expect(page.locator('#bonded-revisions')).to_have_count(0)

    # This mapping has no revision, so the rows are its own draft and every one of them says so.
    page.wait_for_selector('.bonded-interaction-table tbody tr', timeout=30000)
    expect(page.locator('.bonded-interaction-table thead th').last).to_have_text('Source')
    sources = page.locator('.bonded-interaction-table tbody tr td:last-child').all_inner_texts()
    assert sources and set(sources) == {'mapping'}, sources
    assert errors == []


def test_a_constraint_is_editable_and_virtual_site_parents_are_read_only(dashboard, live_page):
    """A constraint's length is an input; a virtual site's parents are a reading.

    The constraint starts at the mapping's own ring target and can be overridden by a revision -- the source column
    then reads `manual`. A virtual site's parents are the mapping's beads, not a parameter, so the cell stays a
    reading. The source column is compared against the store's own `term_sources` rather than restated here, so a
    row's source cannot drift from the term it belongs to.
    """
    saved = save_mapping(dashboard)
    mapping = mappings.get(saved['file'])
    save_revision(mapping)
    stored = parameterization.get(mapping, 1)
    expected = {(row['kind'], ' · '.join(row['beads'])): row['source'] for row in stored['sources']}

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    choose_mapping(page, saved['file'], saved['molecule_id'])
    page.wait_for_selector('.bonded-interaction-table tbody tr', timeout=30000)

    rows = page.locator('.bonded-interaction-table tbody tr')
    expect(rows).to_have_count(len(expected))
    read = {}
    for index in range(rows.count()):
        cells = rows.nth(index).locator('td')
        read[(cells.nth(0).inner_text(), cells.nth(1).inner_text())] = cells.nth(4).inner_text()
    assert read == expected, read

    # The constraint: its own length, in nanometres, as an editable input; a rigid constraint rather than a potential.
    constraint = rows.nth(0).locator('td')
    expect(constraint.nth(0)).to_have_text('constraints')
    expect(constraint.nth(2)).to_have_text('1 — rigid constraint, no potential')
    length = constraint.nth(3).locator('input')
    expect(length).to_have_count(1)
    expect(length).to_have_value('0.315')
    expect(length).to_be_editable()
    # The virtual site: its parents, by bead name, still a reading.
    site = rows.nth(1).locator('td')
    expect(site.nth(0)).to_have_text('virtual_sitesn')
    expect(site.nth(2)).to_contain_text('virtual site')
    expect(site.nth(3)).to_have_text('parents B02 · B03')
    expect(site.nth(3)).to_have_class(re.compile('bonded-readonly-parameter'))
    table_rows = page.locator('.bonded-interaction-table tbody tr')
    expect(table_rows.nth(0).locator('input')).to_have_count(1), 'the constraint length is editable'
    expect(table_rows.nth(1).locator('input')).to_have_count(0)
    expect(table_rows.nth(2).locator('input')).to_have_count(2), 'the bond is editable too'
    expect(page.locator('.bonded-interaction-table select')).to_have_count(0)
    assert errors == []


def test_the_torsion_switch_belongs_to_the_mapping_and_saves_to_it(dashboard, live_page):
    """Stage 3's refinement has one switch, and it is the mapping's rather than a run's.

    `bonded.refine` reads `bonded_options` out of the mapping's own `model.json` -- staged from the candidate a run
    recorded when it was queued -- so this control is the only route by which a chosen torsion model reaches a run's
    topology. That is why it lives in this workspace and not on the New run panel, why its own text has to name both
    the terms it changes and the mapping it belongs to, and why the scale is out of reach unless the model that uses
    it is chosen: `models/bonded.validate` accepts exactly those two keys and refuses a scale without the model.

    The last claim is the one a rendered control alone cannot make, so it is read back off disk: the saved candidate
    carries the options, and reopening the panel reads them into the controls.
    """
    from dashboard.models import mappings

    saved = save_mapping(dashboard)
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    choose_mapping(page, saved['file'], saved['molecule_id'])

    model = page.locator('.bonded-torsion-model')
    scale = page.locator('.bonded-torsion-scale')
    save = page.get_by_role('button', name='Save to mapping')
    # A mapping that states no options is the model's own default, and nothing is offered to save.
    expect(model).to_have_value('legacy')
    expect(scale).to_be_disabled()
    expect(save).to_be_disabled()
    expect(page.locator('.bonded-torsion-status')).to_contain_text('keeps the periodic torsions')

    # What the fieldset says it does: the question it answers, and whose property it is. The mechanism now lives in
    # a closed disclosure (drawing B of the 2026-11-09 explainer draft), so only the visible reason is read here.
    # `text_content`, because the block headings are uppercased by the sheet and `inner_text` reads the render.
    wording = page.locator('.bonded-torsion').text_content()
    assert 'What it is for' in wording, wording
    assert 'property of this mapping' in wording, wording
    expect(page.locator('.torsion-caveat')).to_contain_text('scientific validation')

    # The scale belongs to the circular-harmonic model and to nothing else.
    model.select_option('circular-harmonic')
    expect(scale).to_be_enabled()
    expect(save).to_be_enabled()
    expect(page.locator('.bonded-torsion-status')).to_contain_text('fits every torsion')
    scale.fill('0.5')
    save.click()
    expect(page.locator('.bonded-panel-message')).to_contain_text('Torsion model saved')

    # Read back: the options are in the mapping the runs are queued from, and reopening the panel shows them.
    assert mappings.get(saved['file'])['bonded_options'] == {'torsion_model': 'circular-harmonic',
                                                             'torsion_scale': 0.5}
    expect(save).to_be_disabled()
    page.reload()
    choose_mapping(page, saved['file'], saved['molecule_id'])
    expect(page.locator('.bonded-torsion-model')).to_have_value('circular-harmonic')
    expect(page.locator('.bonded-torsion-scale')).to_have_value('0.5')
    assert errors == [], errors


def test_the_torsion_refinement_explains_why_how_and_what_a_run_needs(dashboard, live_page):
    """Drawing B of the explainer draft: the reason and the caveat visible, the mechanism behind one disclosure.

    The fieldset shares its row with seven fields, so the two blocks that answer "how does it work" and "what does a
    run need" sit in one native `<details>` that starts closed; a reader who wants them clicks once. What stays on
    screen is the part that changes a decision: what a torsion is for, and how far a stiffness should be trusted.
    Both torsion options, the save control and the scale's tie to the circular model are unchanged.
    """
    saved = save_mapping(dashboard)
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    choose_mapping(page, saved['file'], saved['molecule_id'])

    fieldset = page.locator('fieldset.bonded-torsion')
    expect(fieldset).to_be_visible()

    # The three questions, by the draft's own copy table.
    questions = fieldset.locator('dt')
    expect(questions).to_have_count(3)
    assert [questions.nth(index).text_content() for index in range(3)] == [
        'What it is for', 'How it works', 'What a run needs'], questions.all_inner_texts()

    # The caveat is a block of its own, and it is visible: a caveat inside a closed disclosure is one nobody reads.
    caveat = fieldset.locator('.torsion-caveat')
    expect(caveat).to_be_visible()
    expect(caveat).to_contain_text('Caveat')
    expect(caveat).to_contain_text('scientific validation')
    # The caveat must not promise a check the analysis cannot make: `dihedral-fit` skips funct 2, which is the
    # circular model's spelling (see DDM_CALIBRATION.md's baseline and refine's own output).
    expect(caveat).to_contain_text('no independent check')

    # The mechanism starts closed and a click opens it; the disclosure is native, so no script is involved.
    more = fieldset.locator('details.torsion-more')
    expect(more).to_have_count(1)
    assert more.evaluate('el => el.open') is False
    expect(more.locator('summary')).to_have_text('How it works, and what a run needs')
    expect(more.locator('dd').nth(0)).to_be_hidden()
    more.locator('summary').click()
    assert more.evaluate('el => el.open') is True
    expect(more.locator('dd').nth(0)).to_be_visible()
    # The corrected facts the copy keeps: the fit measures the angles and the refinement reads them, one preferred
    # angle and one stiffness at k = kT / variance, never a count of harmonic lines.
    expect(more).to_contain_text('the refinement reads those angles')
    expect(more).to_contain_text('one preferred angle and one stiffness')
    expect(more).to_contain_text('k = kT / variance')
    expect(more).to_contain_text('at least three sampled angles per torsion')

    # Both options and the save control survive the copy change.
    options = page.locator('.bonded-torsion-model option')
    expect(options).to_have_count(2)
    assert [options.nth(index).get_attribute('value') for index in range(2)] == ['legacy', 'circular-harmonic']
    expect(page.get_by_role('button', name='Save to mapping')).to_have_count(1)
    expect(fieldset.locator('#bonded-torsion-status')).to_be_visible()

    # The scale stays out of reach until the model that uses it is chosen.
    scale = page.locator('.bonded-torsion-scale')
    expect(scale).to_be_disabled()
    page.locator('.bonded-torsion-model').select_option('circular-harmonic')
    expect(scale).to_be_enabled()
    assert errors == [], errors


def test_the_diagram_draws_the_candidates_own_molecule_and_not_the_packaged_one(dashboard, live_page):
    """A non-DDM candidate was drawn on the packaged DDM atoms, so its geometry was another molecule's.

    The panel read its atoms once, from the workspace default -- the packaged DDM reference -- and used that reading
    for every candidate. A candidate mapping Sucrose's atoms was therefore drawn on DDM's 81: the same atom id is a
    different atom in a different molecule, so the bead cloud came out 4.4x too long on one axis and 0.4x too short
    on another. That reads as a scaling error and is not one -- and it is why sucrose, trehalose and maltose all drew
    as the identical cloud.

    The assertion is against the molecule's own geometry, computed here from the context the panel is given, so it
    holds for any molecule instead of pinning one molecule's numbers.
    """
    from dashboard.models.mappings import context as mapping_context

    context = dashboard.client.get('/api/mappings/context?molecule_id=Sucrose').get_json()['context']
    candidate = mappings.automatic_candidate(mapping_context.as_structure(context), 'Sucrose')
    candidate['molecule_id'] = 'Sucrose'
    candidate['molecule_snapshot'] = context['snapshot']
    saved = mappings.save_draft(candidate)

    # Every physical bead at the mean of the atoms it maps, in this molecule's own coordinates: what the diagram
    # would draw if it were drawing the molecule the candidate names.
    atoms = {atom['id']: atom['xyz'] for atom in context['atoms']}
    centres = []
    for bead in saved['beads']:
        if bead.get('virtual_site'):
            continue
        points = [atoms[atom_id] for atom_id in (bead.get('atoms') or []) if atom_id in atoms]
        if points:
            centres.append([sum(point[axis] for point in points) / len(points) for axis in range(3)])
    assert centres, 'the candidate maps no physical bead, so there is no geometry to check'
    expected = [round(max(centre[axis] for centre in centres) - min(centre[axis] for centre in centres), 3)
                for axis in range(3)]

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    choose_mapping(page, saved['file'], saved['molecule_id'])
    plot = page.locator('.bonded-plot')
    # The bundle is several megabytes and the scene is WebGL: 5 s is enough alone and not enough with two
    # dozen workers loading it at once, which is what a bare `to_be_visible` answers here.
    expect(plot.locator('.plotly')).to_be_visible(timeout=20000)

    drawn = plot.evaluate("""(el) => {
      const beads = el.data.filter(trace => trace.meta === 'bead');
      const span = axis => {
        const values = beads.flatMap(trace => trace[axis] || []);
        return Math.round((Math.max(...values) - Math.min(...values)) * 1000) / 1000;
      };
      return [span('x'), span('y'), span('z')];
    }""")
    for axis, want in enumerate(expected):
        assert abs(drawn[axis] - want) < 0.05, (
            f'axis {axis}: the diagram draws {drawn[axis]} nm where Sucrose itself spans {want} nm '
            f'(drawn {drawn}, the molecule its own {expected})')
    assert errors == []


def test_a_molecule_scopes_its_mappings_and_offers_its_published_reference(dashboard, live_page):
    """The molecule select is the catalogue's first question: its mappings, then its published reference.

    A molecule's list is the route's answer for that molecule -- not a filter applied here -- and the reference is a
    read-only transcription of an upstream ITP rather than a saved candidate. The panel must draw its own terms
    (kind, parameters, `martini-reference`) in the table and the scene, offer no fit and no delete, and read no
    parameterization route for it. Leaving the reference for the saved mapping restores the normal card.
    """
    ddm = save_mapping(dashboard, 'DDM')
    sucrose = save_mapping(dashboard, 'Sucrose')
    detail = dashboard.client.get(f'/api/mappings/{sucrose["file"]}').get_json()

    # The reference route's model, built from the same beads and connections the saved mapping states, so the scene
    # has a geometry to draw and the table has the ITP's own rows. Its atoms are named the way an exported topology
    # names them (`B01` is the first bead), so the scene proves the same alias join a revision uses.
    topology = '\n'.join([
        '[ moleculetype ]', 'SUCR 1', '',
        '[ atoms ]',
        *[f'{index} SP1r 1 SUCR B{index:02d} 1 0 54'
          for index in range(1, len(detail['beads']) + 1)],
        '',
        '[ bonds ]',
        '1 2 1 0.32 5000',
        '',
        '[ angles ]',
        '1 2 3 10 141.6 26.8',
    ]) + '\n'
    model = {
        'file': 'reference:Sucrose', 'name': 'Martini 3 sugar reference · SUCR',
        'molecule_id': 'Sucrose', 'read_only': True, 'reference_entry': 'SUCR',
        'beads': detail['beads'], 'rings': detail.get('rings', []),
        'connections': detail.get('connections', []), 'topology': topology,
        'reference': {'path': 'references/SUCR.itp', 'sha256': 'f' * 64, 'commit': 'abc1234',
                      'paper_doi': '10.1000/example', 'martini_version': '3.0.0'},
        'limitations': [], 'status': 'published-reference',
    }

    def molecules(route):
        route.fulfill(json={'molecules': [
            {'id': 'DDM', 'name': 'DDM', 'kind': 'aa'},
            {'id': 'Sucrose', 'name': 'Sucrose', 'kind': 'aa'},
            {'id': 'C12E4', 'name': 'C12E4', 'kind': 'cg'},
        ]})

    def reference(route):
        if route.request.url.endswith('/Sucrose'):
            route.fulfill(json={'model': model})
        else:
            route.fulfill(status=404, json={'error': 'no published reference for this molecule'})

    page, errors = live_page
    page.route(re.compile(r'/api/molecules$'), molecules)
    page.route(re.compile(r'/api/mappings/reference/[^/]+$'), reference)
    # Every engine left needs an AA run, and this workspace has none: a mapping-only engine makes Fit's enabled state
    # a statement about the mapping, which is what the test is reading.
    page.route(re.compile(r'/api/bonded-parameterizations/engines$'),
               lambda route: route.fulfill(json={'engines': [
                   {'value': 'mapping-only', 'label': 'Mapping only', 'needs_reference': False}]}))
    term_posts = []
    page.route(re.compile(r'/api/bonded-parameterizations/[a-f0-9]{64}/terms$'),
               lambda route: (term_posts.append((route.request.method, route.request.url,
                                                 json.loads(route.request.post_data))),
                              route.fulfill(json={'revision': 1}))[-1])
    asks = []
    page.on('request', lambda request: asks.append((request.method, request.url))
            if '/api/bonded-parameterizations' in request.url else None)
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')

    page.wait_for_function(
        "() => document.querySelectorAll('#bonded-molecule-select option').length > 0", timeout=30000)
    offered = page.locator('#bonded-molecule-select option').evaluate_all(
        "options => options.map(option => option.value)")
    assert 'C12E4' not in offered, offered  # a cg detergent is not an AA source for the mapping editor
    assert {'DDM', 'Sucrose'} <= set(offered), offered

    page.locator('#bonded-molecule-select').select_option('DDM')
    page.wait_for_function(
        """(file) => Array.from(document.querySelectorAll('#bonded-parameterization-display option'))
          .some(option => option.value === `draft:${file}`)""", arg=ddm['file'], timeout=30000)
    ddm_options = page.locator('#bonded-parameterization-display option').evaluate_all(
        "options => options.map(option => option.value)")
    assert f'draft:{ddm["file"]}' in ddm_options, ddm_options
    assert not any(sucrose['file'] in value for value in ddm_options), ddm_options
    assert 'draft:reference:Sucrose' not in ddm_options, ddm_options

    page.locator('#bonded-molecule-select').select_option('Sucrose')
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('#bonded-parameterization-display option'))"
        ".some(option => option.value === 'draft:reference:Sucrose')", timeout=30000)
    sucrose_options = page.locator('#bonded-parameterization-display option').evaluate_all(
        "options => options.map(option => option.value)")
    assert sucrose_options == [f'draft:{sucrose["file"]}', 'draft:reference:Sucrose'], sucrose_options
    expect(page.locator('#bonded-parameterization-display option').nth(1)).to_have_text(
        'Martini 3 reference · SUCR (read-only)')
    # Wait for the saved mapping's own record to land before clearing the list: its read is in flight until the card
    # reports the switch finished.
    expect(page.locator('.bonded-model')).to_have_attribute('aria-busy', 'false', timeout=30000)

    asks.clear()
    page.locator('#bonded-parameterization-display').select_option('draft:reference:Sucrose')
    page.wait_for_selector('.bonded-interaction-table tbody tr', timeout=30000)
    rows = page.locator('.bonded-interaction-table tbody tr')
    expect(rows).to_have_count(2)
    first_row = rows.nth(0).locator('td')
    expect(first_row.nth(0)).to_have_text('bonds')
    expect(first_row.nth(3).locator('input').nth(0)).to_have_value('0.32')
    expect(first_row.nth(4)).to_have_text('martini-reference')
    angle_row = rows.nth(1).locator('td')
    expect(angle_row.nth(0)).to_have_text('angles')
    expect(angle_row.nth(3).locator('input').nth(0)).to_have_value('141.6')
    expect(angle_row.nth(4)).to_have_text('martini-reference')
    expect(page.locator('.bonded-plot .plotly')).to_be_visible(timeout=30000)
    # The terms are drawn, which is what says the ITP's `B01..` names found the mapping's own beads: a term whose
    # names do not resolve is skipped, not drawn somewhere invented.
    page.wait_for_function(
        "() => (document.querySelector('.bonded-plot').data || [])"
        ".filter(trace => trace.meta === 'term').length >= 2", timeout=30000)
    drawn = page.locator('.bonded-plot').evaluate(
        "(el) => el.data.filter(trace => trace.meta === 'term')"
        ".map(trace => trace.name.split(' · ')[0])")
    assert set(drawn) == {'bonds', 'angles'}, drawn

    # The panel says what this is, and every control a fit would use is disabled rather than hidden.
    expect(page.locator('#bonded-model-summary')).to_contain_text('published Martini 3 sugar reference')
    expect(page.locator('#bonded-model-badge')).to_have_text('published reference')
    expect(page.locator('#bonded-revisions')).to_have_count(0)
    # Both terms buttons are offered, and the reason for the disabled one is visible in the status panel.
    expect(page.locator('#bonded-save-terms-inplace')).to_be_disabled()
    expect(page.locator('#bonded-save-terms-inplace')).to_have_attribute(
        'title', re.compile('published Martini 3 reference'))
    expect(page.locator('#bonded-save-terms-new')).to_be_enabled()
    expect(page.locator('#bonded-terms-status')).to_contain_text('only Save as new can store them')
    expect(page.locator('#bonded-fit')).to_be_disabled()
    expect(page.locator('#bonded-delete-parameterization')).to_be_disabled()
    # A published reference cannot become what a run consumes: it is not a fit of this molecule, and Make current is
    # the one control that changes that, so it is inert here too.
    expect(page.locator('#bonded-make-current')).to_be_disabled()
    expect(page.locator('#bonded-make-current')).to_have_attribute(
        'title', 'The published reference is read-only: it cannot be made current.')
    for control in ('#bonded-aa-reference', '#bonded-engine', '#bonded-constraints-threshold',
                    '#bonded-temperature', '#bonded-torsion-model', '#bonded-save-torsion'):
        expect(page.locator(control)).to_be_disabled()
    expect(page.locator('#bonded-job')).to_be_hidden()
    expect(page.locator('#bonded-result')).to_be_hidden()

    # No parameterization route is read for a reference, and none is written until the reader saves one.
    page.wait_for_timeout(400)
    assert asks == [], asks

    # Save as new is the one live terms control: it posts the edits to the saved mapping, with `from_reference`.
    reference_bond = page.locator('.bonded-interaction-table tbody tr').nth(0).locator('input')
    expect(reference_bond).to_have_count(2)
    reference_bond.nth(0).fill('0.34')
    page.locator('#bonded-save-terms-new').click()
    page.wait_for_timeout(600)
    assert len(term_posts) == 1, term_posts
    method, url, body = term_posts[0]
    assert method == 'POST' and url.endswith('/terms'), (method, url)
    assert sucrose['mapping_content_hash'] in url, (url, sucrose['mapping_content_hash'])
    assert body == {'mode': 'new', 'from_reference': True, 'expected_revision': 0,
                    'terms': [{'id': 'bonds:1', 'parameters': [0.34, 5000]}]}, body

    # Leaving the reference for the saved mapping restores the card and hands every control back.
    page.locator('#bonded-parameterization-display').select_option(f'draft:{sucrose["file"]}')
    expect(page.locator('#bonded-fit')).to_be_enabled(timeout=30000)
    expect(page.locator('#bonded-model-badge')).to_have_text('no parameterization')
    expect(page.locator('#bonded-aa-reference')).to_be_enabled()
    expect(page.locator('#bonded-constraints-threshold')).to_be_enabled()
    expect(page.locator('#bonded-temperature')).to_be_enabled()
    assert errors == [], errors


def test_a_context_that_cannot_be_read_draws_nothing_rather_than_another_molecule(dashboard, live_page):
    """The packaged molecule is not a fallback: a context that fails means no drawing, and the panel says why.

    The old `resolveStructure` answered the workspace's packaged DDM structure whenever the molecule's own context
    failed, so a candidate mapped a different molecule's atoms while the card named this one. The bead aliases and the
    bond table are the model's, but their positions must come from the molecule the model names -- or not be drawn.
    """
    saved = save_mapping(dashboard)
    save_revision(mappings.get(saved['file']))

    page, errors = live_page
    page.route(re.compile(r'/api/mappings/context\?'),
               lambda route: route.fulfill(status=500, json={'error': 'the molecule could not be read'}))
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    choose_mapping(page, saved['file'], saved['molecule_id'])
    expect(page.locator('.bonded-model')).to_have_attribute('aria-busy', 'false', timeout=30000)

    # The reason names the molecule and the failed read, and the scene is empty: no packaged atoms stand in.
    message = page.locator('.bonded-panel-message')
    expect(message).to_contain_text('The diagram is not drawn')
    expect(message).to_contain_text('the coordinates of DDM could not be read')
    expect(page.locator('.bonded-selection-status')).to_contain_text('could not be read')
    page.wait_for_selector('.bonded-plot .plotly', timeout=30000)
    drawn = page.locator('.bonded-plot').evaluate(
        "(el) => (el.data || []).filter(trace => trace.meta === 'bead' || trace.meta === 'term').length")
    assert drawn == 0, f'the scene drew {drawn} traces without the named molecule'
    assert errors == [], errors


def test_a_reference_without_a_saved_mapping_disables_save_as_new_with_its_reason(dashboard, live_page):
    """Save as new needs a saved mapping to seed; with none, the button is inert and the status says why."""
    topology = '\n'.join([
        '[ moleculetype ]', 'GLC 1', '',
        '[ atoms ]',
        *[f'{index} SP1r 1 GLC B{index:02d} 1 0 54' for index in range(1, 5)],
        '', '[ bonds ]', '1 2 1 0.32 5000']) + '\n'
    model = {'file': 'reference:Glucose', 'name': 'Martini 3 sugar reference · GLC',
             'molecule_id': 'Glucose', 'read_only': True, 'reference_entry': 'GLC',
             'beads': [{'name': f'B{index:02d}', 'atoms': [index]} for index in range(1, 5)],
             'rings': [], 'connections': [], 'topology': topology,
             'reference': {'path': 'references/GLC.itp', 'sha256': 'f' * 64},
             'limitations': [], 'status': 'published-reference'}
    page, errors = live_page
    page.route(re.compile(r'/api/molecules$'),
               lambda route: route.fulfill(json={'molecules': [{'id': 'Glucose', 'name': 'Glucose',
                                                               'kind': 'aa'}]}))
    page.route(re.compile(r'/api/mappings\?view=summary&molecule_id=Glucose$'),
               lambda route: route.fulfill(json={'candidates': []}))
    page.route(re.compile(r'/api/mappings/reference/Glucose$'), lambda route: route.fulfill(json={'model': model}))
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    page.wait_for_function(
        "() => document.querySelectorAll('#bonded-parameterization-display option').length === 1",
        timeout=30000)
    expect(page.locator('#bonded-parameterization-display option')).to_have_value('draft:reference:Glucose')

    expect(page.locator('#bonded-save-terms-inplace')).to_be_disabled()
    expect(page.locator('#bonded-save-terms-inplace')).to_have_attribute(
        'title', re.compile('published Martini 3 reference'))
    expect(page.locator('#bonded-save-terms-new')).to_be_disabled()
    expect(page.locator('#bonded-save-terms-new')).to_have_attribute('title', re.compile('needs a saved mapping'))
    expect(page.locator('#bonded-terms-status')).to_contain_text('needs a saved mapping of Glucose to seed')
    assert errors == [], errors
