"""Browser proof that CG Bond Interactions produces a parameterization and draws the model it belongs to.

The parameterization itself -- the model card, the fit job, the result, the `source` column and the revision
strip -- is proved in `test_bonded_parameterization_browser.py`, where every route it drives is stubbed. What is
left here is the rest of the panel: that the mapping selector reaches the model it names, that a mapping's
revisions replace the flat bonded-state list (D1), that the terms no engine fits -- a ring constraint, a virtual
site and its parents -- are shown and stay read-only (`:108-110`), and that the torsion switch still writes the
mapping's own options.
"""
import re

from playwright.sync_api import expect

from dashboard.models import mappings
from dashboard.models.bonded import parameterization
from dashboard.models.bonded import states as bonded_states

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


def test_the_revision_strip_replaces_the_flat_bonded_state_list(dashboard, live_page):
    """D1, as the page: no state select, and a table that reads a revision rather than a state.

    The states still exist in the store, and one is created here on purpose -- what this asserts is that a
    mapping's parameterization is what the panel shows, so a state record that is not a revision appears nowhere.
    """
    saved = mappings.save_draft(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    bonded_states.create(saved, 'A state that is not a revision', topology='[ moleculetype ]\n[ atoms ]',
                         status='complete')

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    expect(page.locator('.bonded-mapping-select')).to_have_value(saved['file'])
    page.wait_for_selector('.bonded-plot .plotly', timeout=30000)

    expect(page.locator('.bonded-state-select')).to_have_count(0)
    # One way a parameterization is produced, and the one place its revisions are read: the reference-free draft
    # and its button were removed, so a second entry point must not come back.
    expect(page.get_by_role('button', name='Fit this model')).to_have_count(1)
    expect(page.get_by_role('button', name='Generate reference-informed draft')).to_have_count(0)
    expect(page.locator('#bonded-revisions')).to_be_visible()

    # This mapping has no revision, so the rows are its own draft and every one of them says so.
    page.wait_for_selector('.bonded-interaction-table tbody tr', timeout=30000)
    expect(page.locator('.bonded-interaction-table thead th').last).to_have_text('Source')
    sources = page.locator('.bonded-interaction-table tbody tr td:last-child').all_inner_texts()
    assert sources and set(sources) == {'mapping'}, sources
    assert errors == []


def test_constraints_and_virtual_site_parents_are_shown_and_stay_read_only(dashboard, live_page):
    """Spec `:108-110`: the read-only constraints and virtual-site parents stay as they were.

    These are the two kinds no engine fits -- a constraint's length is the mapping's own ring target and a virtual
    site's parents are the mapping's beads -- so the table states both, marks the cell read-only, and offers no
    control over either. The source column is compared against the store's own `term_sources` rather than restated
    here, so a row's source cannot drift from the term it belongs to.
    """
    saved = mappings.save_draft(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    mapping = mappings.get(saved['file'])
    save_revision(mapping)
    stored = parameterization.get(mapping, 1)
    expected = {(row['kind'], ' · '.join(row['beads'])): row['source'] for row in stored['sources']}

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    page.locator('.bonded-mapping-select').select_option(saved['file'])
    page.wait_for_selector('.bonded-interaction-table tbody tr', timeout=30000)

    rows = page.locator('.bonded-interaction-table tbody tr')
    expect(rows).to_have_count(len(expected))
    read = {}
    for index in range(rows.count()):
        cells = rows.nth(index).locator('td')
        read[(cells.nth(0).inner_text(), cells.nth(1).inner_text())] = cells.nth(4).inner_text()
    assert read == expected, read

    # The constraint: its own length, in nanometres, and a rigid constraint rather than a potential.
    constraint = rows.nth(0).locator('td')
    expect(constraint.nth(0)).to_have_text('constraints')
    expect(constraint.nth(2)).to_have_text('1 — rigid constraint, no potential')
    expect(constraint.nth(3)).to_have_text('0.315 nm')
    expect(constraint.nth(3)).to_have_class(re.compile('bonded-readonly-parameter'))
    # The virtual site: its parents, by bead name.
    site = rows.nth(1).locator('td')
    expect(site.nth(0)).to_have_text('virtual_sitesn')
    expect(site.nth(2)).to_contain_text('virtual site')
    expect(site.nth(3)).to_have_text('parents B02 · B03')
    expect(site.nth(3)).to_have_class(re.compile('bonded-readonly-parameter'))
    # And nothing in the table is a control: neither kind is a draft anyone can edit.
    expect(page.locator('.bonded-interaction-table input, .bonded-interaction-table select')).to_have_count(0)
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

    saved = mappings.save_draft(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    page.locator('.bonded-mapping-select').select_option(saved['file'])

    model = page.locator('.bonded-torsion-model')
    scale = page.locator('.bonded-torsion-scale')
    save = page.get_by_role('button', name='Save to mapping')
    # A mapping that states no options is the model's own default, and nothing is offered to save.
    expect(model).to_have_value('legacy')
    expect(scale).to_be_disabled()
    expect(save).to_be_disabled()
    expect(page.locator('.bonded-torsion-status')).to_contain_text('keeps the periodic torsions')

    # What the control says it does: the terms of the CG topology, and whose property it is.
    wording = page.locator('.bonded-torsion').inner_text()
    assert 'CG topology' in wording, wording
    assert 'property of this mapping' in wording, wording
    assert 'New run panel' in wording, wording

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
    page.locator('.bonded-mapping-select').select_option(saved['file'])
    expect(page.locator('.bonded-torsion-model')).to_have_value('circular-harmonic')
    expect(page.locator('.bonded-torsion-scale')).to_have_value('0.5')
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
    page.locator('.bonded-mapping-select').select_option(saved['file'])
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
