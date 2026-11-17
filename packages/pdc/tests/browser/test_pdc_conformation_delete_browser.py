"""Deleting a stored detergent-shape library from the New run panel.

A library is the workspace's own coordinates, so the row carries a Delete button beside its radio: the browser asks
before the server deletes anything, and the list comes back from the server afterwards rather than being edited in
place. The two paths that matter are pinned here -- cancelling sends nothing, and confirming sends `{confirm: true}`
to the row's own key. The button sits inside the row's label, so a click must not select the library first.
"""
import re
from urllib.parse import unquote

from playwright.sync_api import expect

from tests.harness import browser

CATALOG = {
    'templates': [{'id': 'DDM:DDM', 'name': 'DDM skeleton', 'molecule': 'DDM', 'residue': 'DDM',
                   'template': 'molecules/DDM/v1/micelle_template.json', 'registered_type': 'registered-template',
                   'files_present': True, 'missing_files': [],
                   'limitations': ['skeleton placeholder template, not a fitted detergent model']}],
    'proteins': [],
    'defaults': {'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900,
                 'nvt_ps': 500, 'npt_ps': 4500, 'pdc_seed': 20260101},
}
KEY = '3fa9c2e71b04d865'
OTHER = '0a1b2c3d4e5f6071'


def library(key, size):
    return {'key': key, 'residue': 'DDM', 'size': size, 'sha256': '5d0a' + 'ab' * 28 + 'c1e8',
            'sources': ['run-1'], 'path': f'workspace/dashboard/conformations/DDM/{key}/library.json'}


def serve(page):
    """The panel's reads, a mutable library list, and the DELETE the button sends."""
    state = {'libraries': [library(KEY, 2000), library(OTHER, 1800)], 'deleted': []}
    browser.serve_pdc_new_run(page, catalogue=CATALOG)
    browser.serve_files(
        page,
        (re.compile(r'/api/pdc/conformations/runs'), {'runs': []}),
        (re.compile(r'/api/setting-presets\?'), {'presets': [], 'default': None}),
    )

    def libraries(route):
        if route.request.method == 'DELETE':
            key = unquote(route.request.url.rsplit('/', 1)[-1])
            state['deleted'].append({'key': key, 'body': route.request.post_data_json})
            state['libraries'] = [item for item in state['libraries'] if item['key'] != key]
            route.fulfill(json={'deleted': key, 'residue': 'DDM',
                                'path': f'workspace/dashboard/conformations/DDM/{key}/library.json'})
            return
        route.fulfill(json={'libraries': state['libraries']})

    page.route(re.compile(r'/api/pdc/conformations/libraries'), libraries)
    return state


def open_stored(page, base_url):
    browser.open_pdc_new_run(page, base_url)
    page.locator('.new-pdc-shape .seg').filter(has_text='Stored library').click()
    page.wait_for_function("() => document.querySelectorAll('.new-pdc-shape .stored-library').length === 2",
                           timeout=30000)


def test_each_row_has_a_delete_button_that_does_not_select_the_library(dashboard, live_page):
    page, errors = live_page
    serve(page)
    open_stored(page, live_page.base_url)

    rows = page.locator('.new-pdc-shape .stored-library')
    assert rows.nth(1).locator('.stored-library-delete').count() == 1
    button = rows.nth(1).locator('.stored-library-delete')
    assert button.get_attribute('type') == 'button'
    assert OTHER in (button.get_attribute('aria-label') or ''), button.get_attribute('aria-label')
    # The first library is the selected one; the second is not. Clicking its Delete must not move the radio.
    expect(rows.nth(0).locator('input[type=radio]')).to_be_checked()
    assert not rows.nth(1).locator('input[type=radio]').is_checked()
    page.on('dialog', lambda dialog: dialog.accept())
    button.click()
    page.wait_for_function("() => document.querySelectorAll('.new-pdc-shape .stored-library').length === 1",
                           timeout=30000)
    # The second row's Delete removed the second row; the first row is still the one the reader had selected.
    expect(rows.first.locator('input[type=radio]')).to_be_checked()
    assert errors == [], errors


def test_cancelling_the_confirm_sends_nothing_and_keeps_the_row(dashboard, live_page):
    page, errors = live_page
    state = serve(page)
    open_stored(page, live_page.base_url)

    messages = []
    page.on('dialog', lambda dialog: (messages.append(dialog.message), dialog.dismiss()))
    page.locator('.new-pdc-shape .stored-library').nth(1).locator('.stored-library-delete').click()

    assert messages == [f'Delete the stored library {OTHER}? Its coordinates are removed from this workspace and '
                        'any run that selected it will no longer be able to use it.'], messages
    expect(page.locator('.new-pdc-shape .stored-library')).to_have_count(2)
    assert state['deleted'] == [], state
    assert errors == [], errors


def test_confirming_deletes_that_key_and_reloads_the_list(dashboard, live_page):
    page, errors = live_page
    state = serve(page)
    open_stored(page, live_page.base_url)

    messages = []
    page.on('dialog', lambda dialog: (messages.append(dialog.message), dialog.accept()))
    page.locator('.new-pdc-shape .stored-library').first.locator('.stored-library-delete').click()

    expect(page.locator('.new-pdc-shape .stored-library')).to_have_count(1)
    assert len(messages) == 1 and messages[0].startswith(f'Delete the stored library {KEY}?'), messages
    assert state['deleted'] == [{'key': KEY, 'body': {'confirm': True}}], state
    expect(page.locator('.new-pdc-shape .stored-library')).to_contain_text(OTHER)
    expect(page.locator('.new-pdc-shape .stored-library')).not_to_contain_text(KEY)
    # The deleted key was the selected one, so the first survivor is selected now.
    expect(page.locator('.new-pdc-shape .stored-library input[type=radio]')).to_be_checked()
    expect(page.locator('#notice')).to_contain_text(f'Stored library {KEY} deleted.')
    assert errors == [], errors
