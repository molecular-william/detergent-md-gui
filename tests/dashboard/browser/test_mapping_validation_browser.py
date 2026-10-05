"""What the Mapping Validation panel renders, over a comparison the test built itself.

The panel is a reader: it shows the record the analysis published and nothing else. A fixture is therefore
enough to hold its rendering in place — the run selector, card 1's pairs, card 2's terms, card 3's per-bead
chart — without needing a coarse-grained run, which is what the earlier phase's tests were missing when the
panel turned out to be reading an endpoint that answered nothing.
"""
import json

from playwright.sync_api import expect

COMPARISON = {
    'schema_version': 1, 'comparison': 'AA vs CG', 'molecule': 'Sucrose', 'entry': 'SUCR',
    'sections': {'pairs': 'AA vs CG', 'terms': 'AA-mapped vs CG-simulated',
                 'displacement': 'AA vs CG, rigid-body fitted on the beads that own atoms'},
    'pairs': {'counts': {'pairs': 2, 'compared': 2, 'cg_outside_aa_range': 0}, 'rows': [
        {'pair': [[1, 'A'], [1, 'B']], 'compared': True, 'unconstrained': False,
         'aa': {'mean': 0.3155, 'std': 0.0063, 'stderr': 0.0002, 'count': 20001, 'min': 0.29, 'max': 0.34},
         'cg': {'mean': 0.3155, 'std': 0.0004, 'stderr': 0.0, 'count': 20001, 'min': 0.315, 'max': 0.316},
         'delta_pct': 0.0, 'inside_range': True, 'inside_spread': True,
         'reference_nm': 0.3050, 'delta_vs_reference_pct': 3.44},
        {'pair': [[2, 'A'], [2, 'B']], 'compared': True, 'unconstrained': False,
         'aa': {'mean': 0.3160, 'std': 0.0035, 'stderr': 0.0000, 'count': 20001, 'min': 0.30, 'max': 0.33},
         'cg': {'mean': 0.3160, 'std': 0.0004, 'stderr': 0.0, 'count': 20001, 'min': 0.315, 'max': 0.317},
         'delta_pct': 0.0, 'inside_range': True, 'inside_spread': True,
         'reference_nm': 0.3760, 'delta_vs_reference_pct': -15.96}]},
    'terms': [
        {'section': 'bonds', 'atoms': [0, 4], 'beads': '(1,A) - (2,A)', 'compared': True,
         'aa': {'mean': 0.30, 'std': 0.01, 'stderr': 0.0, 'count': 20001, 'min': 0.28, 'max': 0.32},
         'cg': {'mean': 0.30, 'std': 0.01, 'stderr': 0.0, 'count': 20001, 'min': 0.29, 'max': 0.31},
         'delta': -0.0, 'wasserstein': 0.002, 'overlap': 0.886, 'overlap_range': [0.2298, 0.3803]},
        {'section': 'angles', 'atoms': [0, 4, 5], 'beads': '(1,A) - (2,A) - (2,B)', 'compared': True,
         'aa': {'mean': 126.93, 'std': 5.09, 'stderr': 0.1, 'count': 20001, 'min': 100.0, 'max': 146.0},
         'cg': {'mean': 124.30, 'std': 10.46, 'stderr': 0.3, 'count': 20001, 'min': 92.0, 'max': 152.0},
         'delta': -2.63, 'wasserstein': 5.19, 'overlap': 0.622, 'overlap_range': [95.6513, 150.5906]}],
    'displacement': {'comparison': 'AA vs CG, rigid-body fitted on the beads that own atoms',
                     'rmsd_nm': 0.00431, 'max_nm': 0.00723, 'aa_frames': 20001, 'cg_frames': 20001,
                     'fit_beads': [[1, 'A'], [1, 'B']],
                     'per_bead': [{'bead': [1, 'A'], 'displacement_nm': 0.004},
                                  {'bead': [1, 'B'], 'displacement_nm': 0.019},
                                  {'bead': [1, 'VS'], 'displacement_nm': 0.001}]},
    'diagnostic_only': True, 'scientifically_validated': False,
    'interpretation': 'This compares our model with our own atomistic reference.',
}


def publish(dashboard, jid, comparison=None, analyses=None):
    """Leave behind what `analysis.worker` leaves behind for a completed comparison."""
    runs = dashboard.coordinator.RUNS; runs.mkdir(parents=True, exist_ok=True)
    record = {'id': jid, 'label': 'Sucrose CG consumer', 'detergent': 'Sucrose', 'method': 'fast_forward',
              'run_type': 'aa_cg', 'profile': 'draft-smoke-reference', 'reference_run_id': '03875cf39790',
              'molecule_id': 'Sucrose', 'status': 'completed', 'stage': 'complete',
              'created': dashboard.coordinator.now()}
    # Only when a test wants one: a record with no `analyses` is what most of these fixtures have always been, and
    # the panel reads absence and an empty list the same way.
    if analyses is not None:
        record['analyses'] = analyses
    dashboard.coordinator.database().replace([record])
    attempt = runs / jid / 'analyses/mapping-consistency/hash/attempt1'
    output = attempt / 'output/abc123/analysis'
    output.mkdir(parents=True)
    (output / 'mapping_consistency.json').write_text(json.dumps(comparison or COMPARISON))
    (attempt / 'result.json').write_text(json.dumps(
        {'result': {'artifact': 'analysis/mapping_consistency.json', 'comparison': 'AA vs CG'},
         'output_directory': 'output/abc123', 'wall_seconds': 13.3}))
    return attempt


SURFACES = {
    'probe_nm': 0.191, 'rendering': 'SAS mesh, GROMACS Connolly dots retained separately',
    'scientifically_validated': False, 'comparison_html': 'analysis/surfaces/surface-comparison.html',
    'statistics': {'AA': {'frames': 20001, 'start_ps': 0.0, 'end_ps': 200000.0,
                          'mean_nm2': 5.8157, 'std_nm2': 0.077},
                   'Simulated CG': {'frames': 20001, 'start_ps': 0.0, 'end_ps': 200000.0,
                                    'mean_nm2': 5.599, 'std_nm2': 0.174}},
}


def publish_surfaces(dashboard, jid):
    """Leave behind what `analysis.worker` leaves behind for a completed surfaces analysis."""
    attempt = dashboard.coordinator.RUNS / jid / 'analyses/surfaces/hash/attempt1'
    output = attempt / 'output/abc123/analysis/surfaces'
    output.mkdir(parents=True)
    (output / 'metadata.json').write_text(json.dumps(SURFACES))
    (output / 'surface-comparison.html').write_text('<html><body>envelopes</body></html>')
    (attempt / 'result.json').write_text(json.dumps(
        {'result': SURFACES, 'output_directory': 'output/abc123', 'wall_seconds': 121.0}))
    return attempt


def test_the_panel_shows_the_published_comparison_including_the_shape_card(dashboard, live_page):
    publish(dashboard, 'aa11bb22cc33')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#validation')

    expect(page.locator('#validation-run option')).to_have_count(1)
    page.wait_for_function("() => document.querySelectorAll('#validation-pair-rows tr').length === 2", timeout=30000)
    # Two different statements side by side, and the panel keeps them apart: the pair sits inside our own
    # observed range, and is 16% away from the published entry, which is carried as context and not as a verdict.
    row = page.evaluate("() => [...document.querySelectorAll('#validation-pair-rows tr')][1].textContent")
    assert 'inside the AA range' in row, row
    assert '(-16.0% context)' in row, row
    assert page.evaluate("() => document.querySelectorAll('#validation-term-rows tr').length") == 2
    assert page.evaluate("() => document.querySelector('#validation-pairs-badge').textContent") == \
        '0 of 2 pairs outside the AA observed range'

    # Card 3: the per-bead chart, in picometres, with the fitted beads distinguished from the rest.
    page.wait_for_function("() => { const host = document.querySelector('#validation-shape-plot');"
                           " return host && host.data && host.data.length === 1; }", timeout=30000)
    chart = page.evaluate("""() => { const host = document.querySelector('#validation-shape-plot');
      return {y: host.data[0].y, x: host.data[0].x, colors: host.data[0].marker.color}; }""")
    assert chart['x'] == ['(1,A)', '(1,B)', '(1,VS)']
    assert [round(value, 2) for value in chart['y']] == [4.0, 19.0, 1.0], 'nanometres shown as picometres'
    assert chart['colors'][0] == '#2455b0' and chart['colors'][1] == '#2455b0', 'the fitted beads are filled'
    assert chart['colors'][2] == '#b9c6d8', 'a bead the fit did not use is shown, and shown differently'
    assert 'rmsd 0.0043 nm' in page.locator('#validation-shape-detail').text_content()
    assert errors == []


def test_a_completed_coarse_grained_run_offers_the_panel_from_its_card(dashboard, live_page):
    """The run card's line: it opens the panel with that run already selected."""
    publish(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    page.goto(live_page.base_url)
    page.wait_for_function("() => document.querySelectorAll('.job').length === 1", timeout=30000)

    page.locator('.job-validate').click()

    expect(page.locator('#tab-validation')).to_have_attribute('aria-selected', 'true')
    expect(page.locator('#validation-run')).to_have_value('bb22cc33dd44')
    page.wait_for_function("() => document.querySelectorAll('#validation-pair-rows tr').length === 2", timeout=30000)
    assert errors == []


def test_an_atomistic_only_run_does_not_offer_it(dashboard, live_page):
    publish(dashboard, 'cc33dd44ee55')
    database = dashboard.coordinator.database()
    database.replace([{**database.all()[0], 'run_type': 'aa_only'}])
    page, errors = live_page
    page.goto(live_page.base_url)
    page.wait_for_function("() => document.querySelectorAll('.job').length === 1", timeout=30000)

    assert page.locator('.job-validate').is_hidden(), 'there is no comparison to read from an atomistic-only run'
    assert errors == []


def test_a_run_with_no_published_comparison_says_so_in_the_panel(dashboard, live_page):
    publish(dashboard, 'dd44ee55ff66')
    (dashboard.coordinator.RUNS / 'dd44ee55ff66/analyses/mapping-consistency/hash/attempt1/result.json').unlink()
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#validation')

    expect(page.locator('#validation-message')).to_be_visible(timeout=30000)
    expect(page.locator('#validation-message')).to_contain_text('No AA vs CG comparison')
    assert page.evaluate("() => document.querySelector('#validation-shape-plot').data === undefined")
    assert errors == []


def publish_molecule(dashboard, jid, molecule, beads, pair, mean, terms=(), other_ring=()):
    """A completed CG run of one molecule with a published comparison, for the cross-molecule card.

    Two of these are needed for a spread, and the card finds them through the job's own `analyses` list, so the
    record carries it -- that is what the panel reads to decide which runs have something to compare. `terms` are
    the linkage rows, and `other_ring` puts beads in residue 2 so those rows have types to resolve against.
    """
    run = dashboard.coordinator.RUNS / jid
    attempt = run / 'analyses/mapping-consistency/hash/attempt1'
    mapped = [{'letter': letter, 'residue': 1, 'name': f'S1{letter}', 'type': bead_type}
              for letter, bead_type in beads]
    mapped += [{'letter': letter, 'residue': 2, 'name': f'S2{letter}', 'type': bead_type}
               for letter, bead_type in other_ring]
    (attempt / 'output/abc123/analysis').mkdir(parents=True)
    (run / 'manifest.json').write_text(json.dumps(
        {'mapping_candidate': {'name': f'{molecule} mapping', 'molecule_id': molecule, 'beads': mapped}}))
    (attempt / 'output/abc123/analysis/mapping_consistency.json').write_text(json.dumps(
        {**COMPARISON, 'molecule': molecule,
         'pairs': {'counts': {'pairs': 1, 'compared': 1, 'cg_outside_aa_range': 0},
                   'rows': [{'pair': pair, 'aa': {'mean': mean}, 'cg': {'mean': mean}}]},
         'terms': [{'section': section, 'beads': ' - '.join(f'({r},{b})' for r, b in atoms),
                    'aa': {'mean': aa}, 'cg': {'mean': cg}} for section, atoms, aa, cg in terms]}))
    (attempt / 'result.json').write_text(json.dumps(
        {'result': {'artifact': 'analysis/mapping_consistency.json', 'comparison': 'AA vs CG'},
         'output_directory': 'output/abc123', 'wall_seconds': 3.0}))
    dashboard.coordinator.database().insert(
        {'id': jid, 'label': f'{molecule} CG consumer', 'detergent': molecule, 'molecule_id': molecule,
         'method': 'fast_forward', 'run_type': 'aa_cg', 'profile': 'draft-smoke-reference',
         'status': 'completed', 'stage': 'complete', 'created': dashboard.coordinator.now(),
         'analyses': [{'kind': 'mapping-consistency', 'status': 'completed', 'id': 'attempt1'}]})
    return attempt


def test_the_across_molecules_card_puts_the_same_bead_types_side_by_side(dashboard, live_page):
    """The spread is the number this card exists for, and the card names the runs that produced it."""
    publish_molecule(dashboard, 'aa11bb22cc33', 'Sucrose', [('A', 'SN6'), ('C', 'SP1r')], [[1, 'A'], [1, 'C']], 0.4230)
    publish_molecule(dashboard, 'bb22cc33dd44', 'Trehalose', [('A', 'SN6'), ('C', 'SP1r')], [[1, 'A'], [1, 'C']], 0.4226)
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#validation')

    # The placeholder row is one row too, so the wait is for the card's own content rather than a row count.
    page.wait_for_function(
        "() => document.querySelector('#validation-across-head').textContent.includes('Trehalose')", timeout=30000)
    row = page.evaluate("() => document.querySelector('#validation-across-rows tr').textContent")
    head = page.evaluate("() => document.querySelector('#validation-across-head').textContent")
    sources = page.evaluate("() => document.querySelector('#validation-across-sources').textContent")

    assert 'Sucrose' in head and 'Trehalose' in head, head
    assert 'SN6 – SP1r' in row, row
    assert '0.4230' in row and '0.4226' in row, row
    assert 'same edges' in row, row
    assert '0.09%' in row, row
    assert 'aa11bb22cc33' in sources and 'bb22cc33dd44' in sources, sources
    assert errors == []


def test_the_across_molecules_card_refuses_to_call_different_edges_a_spread(dashboard, live_page):
    """`SP1r`|`SP1r` is one molecule's B-C edge and another's A-C edge; the card has to say so."""
    publish_molecule(dashboard, 'aa11bb22cc33', 'Maltose', [('B', 'SP1r'), ('C', 'SP1r')], [[1, 'B'], [1, 'C']], 0.3130)
    publish_molecule(dashboard, 'bb22cc33dd44', 'Sucrose', [('A', 'SP1r'), ('C', 'SP1r')], [[1, 'A'], [1, 'C']], 0.4019)
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#validation')

    page.wait_for_function(
        "() => document.querySelector('#validation-across-head').textContent.includes('Sucrose')", timeout=30000)
    row = page.evaluate("() => document.querySelector('#validation-across-rows tr').textContent")

    assert 'different edges' in row, row
    assert '1B–1C' in row and '1A–1C' in row, 'the edges each molecule named are part of the reading'


def test_the_linkage_is_shown_where_the_pairs_table_cannot_reach_it(dashboard, live_page):
    """The bond joining the two rings. Every `pairs` row is a constrained distance inside one ring, so the
    interaction that differs most between disaccharides appears in no row of that table and in this one."""
    publish_molecule(dashboard, 'aa11bb22cc33', 'Maltose', [('B', 'SP1r'), ('A', 'SP4r')], [[1, 'A'], [1, 'B']], 0.34,
                     terms=[('bonds', [(1, 'B'), (2, 'A')], 0.310, 0.304)], other_ring=[('A', 'SN6')])
    publish_molecule(dashboard, 'bb22cc33dd44', 'Trehalose', [('B', 'SP1r'), ('A', 'SP4r')], [[1, 'A'], [1, 'B']], 0.34,
                     terms=[('bonds', [(1, 'B'), (2, 'A')], 0.363, 0.363)], other_ring=[('A', 'SN6')])
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#validation')

    page.wait_for_function(
        "() => document.querySelector('#validation-linkage-head').textContent.includes('Trehalose')", timeout=30000)
    head = page.evaluate("() => document.querySelector('#validation-linkage-head').textContent")
    row = page.evaluate("() => document.querySelector('#validation-linkage-rows tr').textContent")

    assert 'Term' in head and 'Types' in head and 'Spread' in head, head
    assert 'bonds' in row and 'SN6 – SP1r' in row, row
    assert '0.3100 nm' in row and '0.3630 nm' in row, row
    assert '1B-2A' in row, 'the beads the term was measured over'
    assert '15.75%' in row, row
    assert errors == []


def test_a_wrapped_dihedral_shows_its_means_and_withholds_the_percentage(dashboard, live_page):
    """A dihedral mean near the wrap: -97 and +5 are not far apart, and a percentage would say they were."""
    publish_molecule(dashboard, 'aa11bb22cc33', 'Maltose',
                     [('B', 'SP1r'), ('A', 'SP4r')], [[1, 'A'], [1, 'B']], 0.34,
                     terms=[('dihedrals', [(1, 'A'), (1, 'B'), (2, 'A'), (2, 'B')], -97.21, -101.09)],
                     other_ring=[('A', 'SN6'), ('B', 'SP4r')])
    publish_molecule(dashboard, 'bb22cc33dd44', 'Sucrose',
                     [('B', 'SP1r'), ('A', 'SP4r')], [[1, 'A'], [1, 'B']], 0.34,
                     terms=[('dihedrals', [(1, 'A'), (1, 'B'), (2, 'A'), (2, 'B')], 5.42, -0.05)],
                     other_ring=[('A', 'SN6'), ('B', 'SP4r')])
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#validation')

    page.wait_for_function(
        "() => document.querySelector('#validation-linkage-head').textContent.includes('Sucrose')", timeout=30000)
    row = page.evaluate("() => document.querySelector('#validation-linkage-rows tr').textContent")

    assert 'dihedrals' in row and '-97.2°' in row and '5.4°' in row, row
    assert 'wrapped angle: no spread' in row, row
    assert '%' not in row, 'a wrapped mean must not be turned into a percentage'
    assert errors == []


def test_the_envelope_analysis_is_drawn_with_its_statistics_and_its_own_figure(dashboard, live_page):
    """Card 3's second half. The surfaces analysis publishes numbers and a figure; the card frames both.

    The figure is served through the artifact route and framed rather than redrawn, so the assertion is on the
    URL the card built -- from the path the route returned, never from a filesystem path.
    """
    publish(dashboard, 'bb22cc33dd44')
    publish_surfaces(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#validation')

    page.wait_for_function(
        "() => document.querySelectorAll('#validation-surface-rows tr').length === 2", timeout=30000)
    rows = page.evaluate("() => [...document.querySelectorAll('#validation-surface-rows tr')].map(r => r.textContent)")
    frame = page.evaluate("() => { const f = document.querySelector('#validation-surface-figure iframe');"
                          " return f ? f.getAttribute('src') : null; }")
    note = page.evaluate("() => document.querySelector('#validation-surface-note').textContent")

    assert 'AA' in rows[0] and '5.816' in rows[0] and '200.0 ns' in rows[0], rows
    assert 'Simulated CG' in rows[1] and '5.599' in rows[1], rows
    assert frame and frame.startswith('/api/jobs/bb22cc33dd44/artifacts/analyses/surfaces/'), frame
    assert frame.endswith('surface-comparison.html?inline=1'), frame
    assert 'SAS mesh' in note and 'Not scientifically validated' in note, note
    assert errors == []


def test_a_run_with_no_envelope_analysis_says_so_and_frames_nothing(dashboard, live_page):
    """Never queued is a state the card states, rather than an empty frame a reader reads as broken."""
    publish(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    page.goto(f'{live_page.base_url}/#validation')

    page.wait_for_function(
        "() => document.querySelector('#validation-surface-note').textContent.includes('surfaces')", timeout=30000)
    note = page.evaluate("() => document.querySelector('#validation-surface-note').textContent")
    body = page.evaluate("() => document.querySelector('#validation-surface-rows').textContent")

    assert 'queued by hand' in note, note
    assert 'no envelope analysis has been published' in body.lower(), body
    assert page.evaluate("() => document.querySelectorAll('#validation-surface-figure iframe').length") == 0
    assert errors == []


# D1's other half. The card used to offer a bare button; it now states what the run's comparison found, and the
# numbers come from the summary the analysis published into the job record -- the same ones card 1 badges, carried
# by `/api/jobs`, so the card states them without a request of its own.


def test_the_run_card_states_the_numbers_its_comparison_published(dashboard, live_page):
    publish(dashboard, 'bb22cc33dd44', analyses=[
        {'kind': 'mapping-consistency', 'status': 'completed', 'id': 'attempt1',
         'result': {'comparison': 'AA vs CG', 'artifact': 'analysis/mapping_consistency.json',
                    'pairs': {'pairs': 6, 'compared': 6, 'cg_outside_aa_range': 1}}}])
    page, errors = live_page
    page.goto(live_page.base_url)
    page.wait_for_function("() => document.querySelectorAll('.job').length === 1", timeout=30000)

    line = page.locator('.job-validate')
    expect(line).to_be_visible()
    expect(line).to_contain_text('Consistency: CG 5 of 6 ring distances inside the AA observed range')

    # D1's placement, measured rather than assumed: one line under the timeline.
    timeline = page.locator('.job .workflow-timeline').bounding_box()
    box = line.bounding_box()
    assert box['y'] >= timeline['y'] + timeline['height'] - 2, 'the line sits under the timeline, not beside it'

    # The numbers are the door, not a label beside it: clicking the line preselects the run on the panel.
    line.click()
    expect(page.locator('#tab-validation')).to_have_attribute('aria-selected', 'true')
    expect(page.locator('#validation-run')).to_have_value('bb22cc33dd44')
    assert errors == []


def test_a_card_with_no_published_comparison_offers_the_door_without_numbers(dashboard, live_page):
    """Nothing to state, so it offers the panel rather than inventing a count of zero."""
    publish(dashboard, 'bb22cc33dd44')
    page, errors = live_page
    page.goto(live_page.base_url)
    page.wait_for_function("() => document.querySelectorAll('.job').length === 1", timeout=30000)

    expect(page.locator('.job-validate')).to_have_text('Mapping validation')
    assert errors == []
