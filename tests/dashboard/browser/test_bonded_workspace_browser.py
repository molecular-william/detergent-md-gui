"""Browser proof that CG Bond Interactions produces a parameterization and draws the model it belongs to.

The parameterization itself -- the model card, the fit job, the result, the `source` column and the revision
strip -- is proved in `test_bonded_parameterization_browser.py`, where every route it drives is stubbed. What is
left here is the rest of the panel: that the mapping selector reaches the model it names, that the flat
bonded-state workflow is gone (D1), and that the torsion switch still writes the mapping's own options.
"""
from playwright.sync_api import expect

from dashboard.models import mappings
from dashboard.models.bonded import states as bonded_states


def test_the_flat_bonded_state_workflow_is_gone_and_the_table_reads_a_revisions_terms(dashboard, live_page):
    """D1, as the page: no state select, no state buttons, and a table nothing in it can edit.

    The states still exist in the store, and one is created here on purpose -- what this asserts is that a
    mapping's parameterization is what the panel shows, so a state record that is not a revision appears nowhere.
    Saving, deleting and creating a state were the old panel's three ways of writing one; a model's revisions are
    written by a fit now, and this slice has no route that writes a hand-edited revision, so keeping those
    controls would have left three buttons that cannot act.
    """
    saved = mappings.save_draft(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    bonded_states.create(saved, 'A state that is not a revision', topology='[ moleculetype ]\n[ atoms ]',
                         status='complete')

    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/bond-interactions')
    expect(page.locator('.bonded-mapping-select')).to_have_value(saved['file'])
    page.wait_for_selector('.bonded-plot .plotly', timeout=30000)

    expect(page.locator('.bonded-state-select')).to_have_count(0)
    for name in ('Save as new state', 'Delete state', 'Create interaction', 'Run short CG validation',
                 'Generate automatic bonded state'):
        expect(page.get_by_role('button', name=name)).to_have_count(0)
    # The two ways a parameterization is produced, and the one place its revisions are read.
    expect(page.get_by_role('button', name='Fit this model')).to_have_count(1)
    expect(page.get_by_role('button', name='Generate reference-informed draft')).to_have_count(1)
    expect(page.locator('#bonded-revisions')).to_be_visible()

    # The table is a reading, not an editor: a revision is what a fit stored, and nothing here can rewrite it.
    page.wait_for_selector('.bonded-interaction-table tbody tr', timeout=30000)
    expect(page.locator('.bonded-interaction-table thead th').last).to_have_text('Source')
    expect(page.locator('.bonded-interaction-table input, .bonded-interaction-table select')).to_have_count(0)
    # This mapping has no revision, so the rows are its own draft and every one of them says so.
    sources = page.locator('.bonded-interaction-table tbody tr td:last-child').all_inner_texts()
    assert sources and set(sources) == {'mapping'}, sources
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
    expect(plot.locator('.plotly')).to_be_visible()

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
