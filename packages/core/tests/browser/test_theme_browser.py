"""The theme control: the dashboard boots dark, the header button flips it, and the choice survives a reload.

The assertion is the attribute the sheets key on *and* the colour that follows from it: a page can carry
`data-theme="dark"` and still paint light through a sheet that restated a colour, which is exactly the failure this
file is here to catch in reverse.
"""
from playwright.sync_api import expect


def page_theme(page):
    return page.evaluate("""() => { const cs = getComputedStyle(document.body);
      return {theme: document.documentElement.dataset.theme,
              background: cs.backgroundColor, color: cs.color}; }""")


def test_the_dashboard_boots_dark_and_the_button_returns_it_to_light(dashboard, live_page):
    page, errors = live_page
    page.goto(live_page.base_url)
    toggle = page.locator('#theme-toggle')
    expect(toggle).to_be_visible()

    # Dark is the default, stated on the root and painted by the body.
    expect(toggle).to_have_attribute('aria-pressed', 'true')
    assert page_theme(page) == {'theme': 'dark', 'background': 'rgb(13, 19, 27)',
                                'color': 'rgb(219, 227, 238)'}, page_theme(page)

    toggle.click()
    expect(toggle).to_have_attribute('aria-pressed', 'false')
    assert page_theme(page) == {'theme': 'light', 'background': 'rgb(243, 246, 250)',
                                'color': 'rgb(28, 41, 64)'}, page_theme(page)

    # The choice is the reader's: a reload keeps it, and the button flips back.
    page.reload()
    expect(page.locator('#theme-toggle')).to_have_attribute('aria-pressed', 'false')
    assert page_theme(page)['theme'] == 'light'
    page.locator('#theme-toggle').click()
    assert page_theme(page)['theme'] == 'dark'
    assert errors == []
