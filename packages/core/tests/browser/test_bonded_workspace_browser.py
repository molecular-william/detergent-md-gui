"""Browser proof that CG Bond Interactions shows two independent model panes and draws the model each belongs to.

The constructor changed on 2026-11-12: the panel is one Jinja macro rendered twice (pane A keeps the bare ids, pane B
carries `-B`), the model facts and actions live in each pane, and the fit controls are one merged "Model and fit" card
above both. What is left here is the rest of the panel: the display selector reaches the model it names, the terms no
engine fits -- a ring constraint, a virtual site and its parents -- are shown and stay read-only where the server says
so, the torsion switch still writes the mapping's own options through the fit card, and the second pane is a whole
workspace of its own (own molecule, own typed edits, minimisable, remembered in `ddm.bonded.state`).

The parameterization record's own card, the fit job and the result are proved in
`test_bonded_parameterization_browser.py`, where every route they drive is stubbed. The Lead's pane-B id contract is
`test_bonded_two_panes_browser.py`.
"""
import json
import re

from dashboard.models import mappings
from dashboard.models.bonded import parameterization
from dashboard.models.mappings import context as mapping_context
from playwright.sync_api import expect

PANE_A = '.bonded-column[data-side="A"]'
PANE_B = '.bonded-column[data-side="B"]'
#: The server's own sentence for a published reference. The panel quotes it rather than stating a local rule.
REFERENCE_SENTENCE = 'published Martini 3 reference is read-only; a CG run consumes it directly'

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
    """One saved candidate built the way the editor builds it: scoped to a molecule and its snapshot."""
    context = dashboard.client.get(f'/api/mappings/context?molecule_id={molecule}').get_json()['context']
    candidate = mappings.automatic_candidate(mapping_context.as_structure(context), molecule)
    candidate['molecule_id'] = molecule
    candidate['molecule_snapshot'] = context['snapshot']
    if name:
        candidate['name'] = name
    return mappings.save_draft(candidate)


def pane(page, side='A'):
    return page.locator(f'.bonded-column[data-side="{side}"]')


def pane_id(page, name, side='A'):
    """A pane's id: the bare id in pane A, the same with `-B` in pane B."""
    return pane(page, side).locator(f'#{name}{"" if side == "A" else "-B"}')


def choose_mapping(page, file, molecule=None, side='A'):
    """Pick a mapping the way a reader does in one pane: its molecule first, then the option carrying the mapping."""
    suffix = '' if side == 'A' else '-B'
    pane(page, side).wait_for()
    page.wait_for_function(
        f"() => document.querySelectorAll('{PANE_A if side == 'A' else PANE_B} "
        f"#bonded-molecule-select{suffix} option').length > 0", timeout=30000)
    if molecule:
        pane_id(page, 'bonded-molecule-select', side).select_option(molecule)
    page.wait_for_function(
        """([side, file]) => Array.from(
            document.querySelectorAll(`.bonded-column[data-side="${side}"] `
              + `#bonded-parameterization-display${side === 'A' ? '' : '-B'} option`))
          .some(option => option.value.startsWith(`revision:${file}:`) || option.value === `draft:${file}`)""",
        arg=[side, file], timeout=30000)
    value = page.evaluate("""([side, file]) => {
      const options = Array.from(document.querySelectorAll(`.bonded-column[data-side="${side}"] `
        + `#bonded-parameterization-display${side === 'A' ? '' : '-B'} option`));
      const current = options.find(option => option.value.startsWith(`revision:${file}:`)
        && option.textContent.includes('current'));
      const draft = options.find(option => option.value === `draft:${file}`);
      return (current || draft || {}).value || '';
    }""", [side, file])
    if pane_id(page, 'bonded-parameterization-display', side).input_value() != value:
        pane_id(page, 'bonded-parameterization-display', side).select_option(value)
    return value


def choose_fit_target(page, file, molecule=None):
    """Point the merged fit card at one mapping: its own molecule select, then its own mapping select."""
    page.wait_for_function(
        "() => document.querySelectorAll('#bonded-fit-molecule option').length > 0", timeout=30000)
    if molecule:
        page.locator('#bonded-fit-molecule').select_option(molecule)
    page.wait_for_function(
        """(file) => Array.from(document.querySelectorAll('#bonded-fit-mapping option'))
          .some(option => option.value === file)""", arg=file, timeout=30000)
    if page.locator('#bonded-fit-mapping').input_value() != file:
        page.locator('#bonded-fit-mapping').select_option(file)


def test_the_display_selector_is_the_only_history(dashboard, live_page):
    """D1, as the page: no state select, no revision strip, and a table that reads a revision rather than a state.

    The flat bonded-state store and the revision strip are gone from the codebase, not merely unshown: the display
    selector is the history, and nothing else lists revisions.
    """
    saved = save_mapping(dashboard)

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    # One display selector per pane, showing this mapping's draft because it has no revision yet. The hidden bridge
    # is present but is not a second choice, and it addresses pane A only.
    expect(pane_id(page, 'bonded-parameterization-display')).to_have_value(f'draft:{saved["file"]}')
    expect(page.locator('#bonded-mapping-select')).to_be_hidden()
    pane(page, 'A').locator('.bonded-plot .plotly').wait_for(timeout=30000)

    expect(page.locator('.bonded-state-select')).to_have_count(0)
    # One way a parameterization is produced, and the one place its revisions are read: the reference-free draft
    # and its button were removed, so a second entry point must not come back.
    expect(page.get_by_role('button', name='Fit this model')).to_have_count(1)
    expect(page.get_by_role('button', name='Generate reference-informed draft')).to_have_count(0)
    expect(page.locator('#bonded-revisions')).to_have_count(0)

    # This mapping has no revision, so the rows are its own draft and every one of them says so.
    table = pane(page, 'A').locator('.bonded-interaction-table')
    table.locator('tbody tr').first.wait_for(timeout=30000)
    expect(table.locator('thead th').last).to_have_text('Source')
    sources = table.locator('tbody tr td:last-child').all_inner_texts()
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
    rows = pane(page, 'A').locator('.bonded-interaction-table tbody tr')
    rows.first.wait_for(timeout=30000)

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
    expect(rows.nth(0).locator('input')).to_have_count(1), 'the constraint length is editable'
    expect(rows.nth(1).locator('input')).to_have_count(0)
    expect(rows.nth(2).locator('input')).to_have_count(2), 'the bond is editable too'
    expect(pane(page, 'A').locator('.bonded-interaction-table select')).to_have_count(0)
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
    choose_fit_target(page, saved['file'], saved['molecule_id'])
    expect(page.locator('#bonded-torsion-status')).to_contain_text('keeps the periodic torsions', timeout=30000)

    model = page.locator('#bonded-torsion-model')
    scale = page.locator('#bonded-torsion-scale')
    save = page.get_by_role('button', name='Save to mapping')
    # A mapping that states no options is the model's own default, and nothing is offered to save.
    expect(model).to_have_value('legacy')
    expect(scale).to_be_disabled()
    expect(save).to_be_disabled()

    # The scale belongs to the circular-harmonic model and to nothing else.
    model.select_option('circular-harmonic')
    expect(scale).to_be_enabled()
    expect(save).to_be_enabled()
    expect(page.locator('#bonded-torsion-status')).to_contain_text('fits every torsion')
    scale.fill('0.5')
    save.click()
    expect(page.locator('.bonded-panel-message')).to_contain_text('Torsion model saved')

    # Read back: the options are in the mapping the runs are queued from, and reopening the panel shows them.
    assert mappings.get(saved['file'])['bonded_options'] == {'torsion_model': 'circular-harmonic',
                                                             'torsion_scale': 0.5}
    expect(save).to_be_disabled()
    page.reload()
    choose_fit_target(page, saved['file'], saved['molecule_id'])
    expect(page.locator('#bonded-torsion-model')).to_have_value('circular-harmonic')
    expect(page.locator('#bonded-torsion-scale')).to_have_value('0.5')
    assert errors == [], errors


def test_the_torsion_explainer_is_an_info_control_that_opens_and_closes(dashboard, live_page):
    """The torsion copy is one (i) control, not a fieldset: it opens on a click, and Escape or an outside click closes.

    The copy is the approved explainer (what it is for, how it works, what a run needs, and the caveat). Its
    visibility on hover and focus is the sheet's; what this asserts is the script's own state -- `.is-open` and
    `aria-expanded` -- because that is the part touch and keyboard readers depend on.
    """
    saved = save_mapping(dashboard)
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    choose_fit_target(page, saved['file'], saved['molecule_id'])

    info = page.locator('#bonded-torsion-info')
    tip = page.locator('#bonded-torsion-tip')
    expect(page.locator('fieldset.bonded-torsion')).to_have_count(0)
    expect(info).to_have_attribute('aria-expanded', 'false')
    expect(tip).to_be_hidden()

    # The approved copy, once, in the tip: the three questions and the caveat.
    wording = tip.text_content()
    for expected in ('What it is for', 'How it works', 'What a run needs', 'property of this mapping',
                     'k = kT / variance', 'at least three sampled angles per torsion', 'scientific validation',
                     'no independent check'):
        assert expected in wording, (expected, wording)

    info.click()
    expect(info).to_have_attribute('aria-expanded', 'true')
    expect(tip).to_have_class(re.compile('is-open'))
    page.keyboard.press('Escape')
    expect(info).to_have_attribute('aria-expanded', 'false')
    expect(tip).not_to_have_class(re.compile('is-open'))

    # An outside click closes it too, and the control toggles back open.
    info.click()
    page.locator('#bonded-fit-title').click()
    expect(tip).not_to_have_class(re.compile('is-open'))
    assert errors == [], errors


def test_the_diagram_draws_the_candidates_own_molecule_and_not_the_packaged_one(dashboard, live_page):
    """A non-DDM candidate is drawn on its own molecule's atoms, never on the packaged DDM ones.

    The panel read its atoms once, from the workspace default, and used that reading for every candidate: a mapping of
    Sucrose's atoms was drawn on DDM's 81. The assertion is against the molecule's own geometry, computed here from
    the context the panel is given, so it holds for any molecule instead of pinning one molecule's numbers.
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
    plot = pane(page, 'A').locator('.bonded-plot')
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
    """One pane's molecule select is the catalogue's first question: its mappings, then its published reference.

    The reference is a read-only transcription of an upstream ITP rather than a saved candidate: a CG run consumes
    it directly, so its rows are readings, both terms buttons are inert, and the status quotes the server's own
    sentence -- the seed path (Save as new from a reference) is gone. Leaving it for a saved mapping restores the
    pane's normal state.
    """
    ddm = save_mapping(dashboard, 'DDM')
    sucrose = save_mapping(dashboard, 'Sucrose')
    detail = dashboard.client.get(f'/api/mappings/{sucrose["file"]}').get_json()

    # The reference route's model, built from the same beads and connections the saved mapping states, so the scene
    # has a geometry to draw and the table has the ITP's own rows.
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
    term_posts = []
    record_reads = []
    page.on('request', lambda request: record_reads.append(request.url)
            if '/api/bonded-parameterizations?' in request.url else None)
    page.route(re.compile(r'/api/bonded-parameterizations/[a-f0-9]{64}/terms$'),
               lambda route: (term_posts.append((route.request.method, route.request.url,
                                                 json.loads(route.request.post_data))),
                              route.fulfill(json={'revision': 1}))[-1])
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')

    page.wait_for_function(
        f"() => document.querySelectorAll('{PANE_A} #bonded-molecule-select option').length > 0", timeout=30000)
    offered = pane_id(page, 'bonded-molecule-select').locator('option').evaluate_all(
        "options => options.map(option => option.value)")
    assert 'C12E4' not in offered, offered  # a cg detergent is not an AA source for the pane
    assert {'DDM', 'Sucrose'} <= set(offered), offered
    # The fit target offers AA molecules only: a CG composition cannot be fitted.
    fit_molecules = page.locator('#bonded-fit-molecule option').evaluate_all(
        "options => options.map(option => option.value)")
    assert 'C12E4' not in fit_molecules, fit_molecules

    pane_id(page, 'bonded-molecule-select').select_option('DDM')
    page.wait_for_function(
        """(file) => Array.from(document.querySelectorAll(
            '.bonded-column[data-side="A"] #bonded-parameterization-display option'))
          .some(option => option.value === `draft:${file}`)""", arg=ddm['file'], timeout=30000)
    ddm_options = pane_id(page, 'bonded-parameterization-display').locator('option').evaluate_all(
        "options => options.map(option => option.value)")
    assert f'draft:{ddm["file"]}' in ddm_options, ddm_options
    assert not any(sucrose['file'] in value for value in ddm_options), ddm_options

    pane_id(page, 'bonded-molecule-select').select_option('Sucrose')
    page.wait_for_function(
        """() => Array.from(document.querySelectorAll(
            '.bonded-column[data-side="A"] #bonded-parameterization-display option'))
          .some(option => option.value === 'draft:reference:Sucrose')""", timeout=30000)
    sucrose_options = pane_id(page, 'bonded-parameterization-display').locator('option').evaluate_all(
        "options => options.map(option => option.value)")
    assert sucrose_options == [f'draft:{sucrose["file"]}', 'draft:reference:Sucrose'], sucrose_options
    expect(pane_id(page, 'bonded-parameterization-display').locator('option').nth(1)).to_have_text(
        'Martini 3 reference · SUCR (read-only)')
    # Wait for the saved mapping's own record to land before switching: its read is in flight until the pane is idle.
    expect(pane(page, 'A')).to_have_attribute('aria-busy', 'false', timeout=30000)

    term_posts.clear()
    record_reads.clear()
    pane_id(page, 'bonded-parameterization-display').select_option('draft:reference:Sucrose')
    rows = pane(page, 'A').locator('.bonded-interaction-table tbody tr')
    rows.first.wait_for(timeout=30000)
    expect(rows).to_have_count(2)
    first_row = rows.nth(0).locator('td')
    expect(first_row.nth(0)).to_have_text('bonds')
    # Read-only: the values are a reading, not an input, and the source names the transcription.
    expect(first_row.nth(3).locator('input')).to_have_count(0)
    expect(first_row.nth(3)).to_contain_text('0.32 nm')
    expect(first_row.nth(4)).to_have_text('martini-reference')
    angle_row = rows.nth(1).locator('td')
    expect(angle_row.nth(0)).to_have_text('angles')
    expect(angle_row.nth(3).locator('input')).to_have_count(0)
    expect(angle_row.nth(3)).to_contain_text('141.6')
    expect(angle_row.nth(4)).to_have_text('martini-reference')
    expect(pane(page, 'A').locator('.bonded-plot .plotly')).to_be_visible(timeout=30000)
    # The terms are drawn, which is what says the ITP's `B01..` names found the mapping's own beads.
    page.wait_for_function(
        """() => (document.querySelector('.bonded-column[data-side="A"] .bonded-plot').data || [])"""
        """.filter(trace => trace.meta === 'term').length >= 2""", timeout=30000)
    drawn = pane(page, 'A').locator('.bonded-plot').evaluate(
        "(el) => el.data.filter(trace => trace.meta === 'term')"
        ".map(trace => trace.name.split(' · ')[0])")
    assert set(drawn) == {'bonds', 'angles'}, drawn

    # The pane says what this is, and both save buttons quote the reference's own sentence.
    expect(pane_id(page, 'bonded-model-summary')).to_contain_text('published Martini 3 reference')
    expect(pane_id(page, 'bonded-model-badge')).to_have_text('published reference')
    expect(page.locator('#bonded-revisions')).to_have_count(0)
    expect(pane_id(page, 'bonded-save-terms-inplace')).to_be_disabled()
    expect(pane_id(page, 'bonded-save-terms-new')).to_be_disabled()
    for button in ('bonded-save-terms-inplace', 'bonded-save-terms-new'):
        expect(pane_id(page, button)).to_have_attribute('title', re.compile(REFERENCE_SENTENCE))
    expect(pane_id(page, 'bonded-terms-status')).to_contain_text(REFERENCE_SENTENCE)
    expect(pane_id(page, 'bonded-delete-parameterization')).to_be_disabled()
    # A published reference cannot become what a run consumes: Make current is inert here too.
    expect(pane_id(page, 'bonded-make-current')).to_be_disabled()
    expect(pane_id(page, 'bonded-make-current')).to_have_attribute(
        'title', 'The published reference is read-only: it cannot be made current.')
    # The fit card is not this pane's subject: a reference in a pane leaves the panel's own fit controls alone.
    expect(page.locator('#bonded-result')).to_be_hidden()
    page.wait_for_timeout(400)
    assert term_posts == [], term_posts
    # No parameterization record is read for a reference: the published model states its own ITP and has no revision.
    assert not [url for url in record_reads if detail['mapping_content_hash'] in url], record_reads

    # Leaving the reference for the saved mapping restores the pane; a draft still has no stored revision to save.
    pane_id(page, 'bonded-parameterization-display').select_option(f'draft:{sucrose["file"]}')
    expect(pane_id(page, 'bonded-model-badge')).to_have_text('no parameterization', timeout=30000)
    expect(pane_id(page, 'bonded-save-terms-new')).to_be_disabled()
    expect(pane_id(page, 'bonded-save-terms-new')).to_have_attribute(
        'title', 'This model has no stored revision to clone.')
    assert errors == [], errors


def test_a_context_that_cannot_be_read_draws_nothing_rather_than_another_molecule(dashboard, live_page):
    """The packaged molecule is not a fallback: a context that fails means no drawing, and the pane says why."""
    saved = save_mapping(dashboard)
    save_revision(mappings.get(saved['file']))

    page, errors = live_page
    page.route(re.compile(r'/api/mappings/context\?'),
               lambda route: route.fulfill(status=500, json={'error': 'the molecule could not be read'}))
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    choose_mapping(page, saved['file'], saved['molecule_id'])
    expect(pane(page, 'A')).to_have_attribute('aria-busy', 'false', timeout=30000)

    # The reason names the molecule and the failed read, and the scene is empty: no packaged atoms stand in.
    message = page.locator('.bonded-panel-message')
    expect(message).to_contain_text('The diagram is not drawn')
    expect(message).to_contain_text('the coordinates of DDM could not be read')
    expect(pane(page, 'A').locator('.bonded-selection-status')).to_contain_text('could not be read')
    pane(page, 'A').locator('.bonded-plot .plotly').wait_for(timeout=30000)
    drawn = pane(page, 'A').locator('.bonded-plot').evaluate(
        "(el) => (el.data || []).filter(trace => trace.meta === 'bead' || trace.meta === 'term').length")
    assert drawn == 0, f'the scene drew {drawn} traces without the named molecule'
    assert errors == [], errors


def test_a_reference_without_a_saved_mapping_is_read_only_and_offers_no_seed(dashboard, live_page):
    """The published reference is display-only: both save buttons are inert with the server's reason.

    The seed path is gone with it: a CG run consumes the published reference directly, so there is no "Save as new
    from the reference" and no mapping for it to target.
    """
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
        f"() => document.querySelectorAll('{PANE_A} #bonded-parameterization-display option').length === 1",
        timeout=30000)
    expect(pane_id(page, 'bonded-parameterization-display').locator('option')).to_have_value(
        'draft:reference:Glucose')

    expect(pane_id(page, 'bonded-save-terms-inplace')).to_be_disabled()
    expect(pane_id(page, 'bonded-save-terms-new')).to_be_disabled()
    for button in ('bonded-save-terms-inplace', 'bonded-save-terms-new'):
        expect(pane_id(page, button)).to_have_attribute('title', re.compile(REFERENCE_SENTENCE))
    expect(pane_id(page, 'bonded-terms-status')).to_contain_text(REFERENCE_SENTENCE)
    # The fit card has no mapping to fit: its own status says so rather than offering a disabled mystery.
    expect(page.locator('#bonded-fit')).to_be_disabled()
    expect(page.locator('#bonded-fit-status')).to_contain_text('Choose a mapping first')
    assert errors == [], errors


# ----------------------------------------------------------------------------------- two independent panes


def test_two_panes_hold_different_molecules_and_their_own_facts(dashboard, live_page):
    """Each pane is a whole workspace: its own molecule, its own selector, its own facts and its own scene."""
    ddm = save_mapping(dashboard, 'DDM')
    sucrose = save_mapping(dashboard, 'Sucrose')

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    choose_mapping(page, ddm['file'], 'DDM', side='A')
    choose_mapping(page, sucrose['file'], 'Sucrose', side='B')

    expect(pane_id(page, 'bonded-molecule-select', 'A')).to_have_value('DDM')
    expect(pane_id(page, 'bonded-molecule-select', 'B')).to_have_value('Sucrose')
    expect(pane_id(page, 'bonded-parameterization-display', 'A')).to_have_value(f'draft:{ddm["file"]}')
    expect(pane_id(page, 'bonded-parameterization-display', 'B')).to_have_value(f'draft:{sucrose["file"]}')
    # The model facts live in each pane, and the two molecules do not state the same bead count.
    facts_a = pane_id(page, 'bonded-mapping-facts', 'A').inner_text()
    facts_b = pane_id(page, 'bonded-mapping-facts', 'B').inner_text()
    assert 'beads' in facts_a and 'beads' in facts_b, (facts_a, facts_b)
    assert facts_a != facts_b, (facts_a, facts_b)
    # Each pane's table and scene are its own.
    expect(pane(page, 'A').locator('.bonded-interaction-table tbody tr').first).to_be_visible()
    expect(pane(page, 'B').locator('.bonded-interaction-table tbody tr').first).to_be_visible()
    expect(pane(page, 'B').locator('.bonded-plot .plotly')).to_be_visible(timeout=30000)
    assert errors == [], errors


def test_the_second_pane_minimises_expands_and_keeps_its_typed_edit(dashboard, live_page):
    """Pane B collapses to its header and comes back with its state: a typed parameter survives, and the choice is
    remembered in `ddm.bonded.state`."""
    saved = save_mapping(dashboard)
    save_revision(mappings.get(saved['file']))

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    choose_mapping(page, saved['file'], saved['molecule_id'], side='B')
    rows = pane(page, 'B').locator('.bonded-interaction-table tbody tr')
    rows.first.wait_for(timeout=30000)
    # Row order is the topology's: constraints, virtual site, then the bond this test edits.
    bond = rows.nth(2).locator('input').nth(0)
    bond.fill('0.33')
    expect(rows.nth(2).locator('input').nth(0)).to_have_value('0.33')

    minimize = page.locator('#bonded-minimize-B')
    minimize.click()
    expect(pane(page, 'B')).to_have_attribute('data-minimized', 'true')
    expect(page.locator('.bonded-columns')).to_have_class(re.compile('one-column'))
    expect(minimize).to_have_text('Expand')
    expect(minimize).to_have_attribute('aria-expanded', 'false')
    # The choice is remembered under the panel's own key.
    remembered = page.evaluate("() => JSON.parse(localStorage.getItem('ddm.bonded.state') || '{}')")
    assert remembered.get('minimized', {}).get('B') is True, remembered
    # Pane A never collapses.
    expect(pane(page, 'A')).not_to_have_attribute('data-minimized', 'true')

    minimize.click()
    expect(pane(page, 'B')).to_have_attribute('data-minimized', 'false')
    expect(page.locator('.bonded-columns')).not_to_have_class(re.compile('one-column'))
    expect(minimize).to_have_text('Minimize')
    expect(minimize).to_have_attribute('aria-expanded', 'true')
    # The typed value was never dropped: minimising is CSS, not a remount.
    expect(rows.nth(2).locator('input').nth(0)).to_have_value('0.33')
    expect(pane(page, 'B').locator('.bonded-plot .plotly')).to_be_visible(timeout=30000)
    assert errors == [], errors


def test_a_save_in_one_pane_leaves_the_other_panes_typed_edits_alone(dashboard, live_page):
    """Panes are independent: saving A reloads only the panes showing A's mapping.

    The server's edit gate is what a fresh fit revision says: inputs are editable, Save in place is inert with the
    server's reason, and Save as new carries the edit as a hand-edited revision. B's unsaved value must survive A's
    save, because B shows a different mapping.
    """
    ddm = save_mapping(dashboard, 'DDM')
    sucrose = save_mapping(dashboard, 'Sucrose')
    save_revision(mappings.get(ddm['file']))
    save_revision(mappings.get(sucrose['file']))

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    choose_mapping(page, ddm['file'], 'DDM', side='A')
    choose_mapping(page, sucrose['file'], 'Sucrose', side='B')
    rows_a = pane(page, 'A').locator('.bonded-interaction-table tbody tr')
    rows_b = pane(page, 'B').locator('.bonded-interaction-table tbody tr')
    rows_a.first.wait_for(timeout=30000)
    rows_b.first.wait_for(timeout=30000)

    # A fresh fit's first edit is Save as new: the store's reason is quoted, and the inputs are still editable.
    expect(pane_id(page, 'bonded-save-terms-inplace', 'A')).to_be_disabled()
    expect(pane_id(page, 'bonded-save-terms-inplace', 'A')).to_have_attribute(
        'title', re.compile('fitted by fast-forward; Save as new to edit it'))
    expect(pane_id(page, 'bonded-terms-status', 'A')).to_contain_text(
        'fitted by fast-forward; Save as new to edit it')
    expect(pane_id(page, 'bonded-save-terms-new', 'A')).to_be_enabled()

    rows_a.nth(2).locator('input').nth(0).fill('0.33')
    rows_b.nth(2).locator('input').nth(0).fill('0.4')

    pane_id(page, 'bonded-save-terms-new', 'A').click()
    # The save appends revision 2 and makes it current; the pane reloads it.
    page.wait_for_function(
        """([file]) => document.querySelector('.bonded-column[data-side="A"] #bonded-parameterization-display')
          ?.value === `revision:${file}:2`""", arg=[ddm['file']], timeout=30000)

    # A's edited value is stored, and its source column says the term is a hand edit.
    expect(rows_a.nth(2).locator('input').nth(0)).to_have_value('0.33')
    expect(rows_a.nth(2).locator('td').last).to_have_text('manual')
    # B's typed value and shown revision are untouched by A's save.
    expect(rows_b.nth(2).locator('input').nth(0)).to_have_value('0.4')
    expect(pane_id(page, 'bonded-parameterization-display', 'B')).to_have_value(
        f'revision:{sucrose["file"]}:1')
    assert errors == [], errors


def test_the_new_run_door_preselects_pane_a(dashboard, live_page):
    """The hidden bridge `new-run.js` drives addresses pane A only; pane B keeps whatever it is showing."""
    ddm = save_mapping(dashboard, 'DDM')
    sucrose = save_mapping(dashboard, 'Sucrose')

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    page.wait_for_function(
        f"() => document.querySelectorAll('{PANE_A} #bonded-molecule-select option').length > 0", timeout=30000)
    # Which molecule the panels default to is the catalogue's order, not this test's subject: read it, then hand the
    # door a mapping of the *other* molecule so A's move is visible against B's unchanged state.
    default_molecule = pane_id(page, 'bonded-molecule-select', 'A').input_value()
    other = 'Sucrose' if default_molecule == 'DDM' else 'DDM'
    target = sucrose if other == 'Sucrose' else ddm
    page.wait_for_function(
        """() => document.querySelectorAll('#bonded-parameterization-display-B option').length > 0""",
        timeout=30000)

    # The door's own address (`?mapping_candidate=`) is what `new-run.js` applies on a cold load.
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions'
              f'?mapping_candidate={target["file"]}')
    page.wait_for_function(
        """(file) => document.querySelector(
            '.bonded-column[data-side="A"] #bonded-parameterization-display')?.value?.includes(file)""",
        arg=target['file'], timeout=30000)
    assert target['file'] in pane_id(page, 'bonded-parameterization-display', 'A').input_value()
    # Pane B is untouched: still the default molecule's mapping, not the door's target.
    assert target['file'] not in pane_id(page, 'bonded-parameterization-display', 'B').input_value()
    expect(pane_id(page, 'bonded-molecule-select', 'B')).to_have_value(default_molecule)
    assert errors == [], errors
