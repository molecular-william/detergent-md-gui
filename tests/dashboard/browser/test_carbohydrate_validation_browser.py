from playwright.sync_api import expect


def test_mapping_tab_shows_carbohydrate_validation_controls(live_page):
    page = live_page.page
    page.goto(f'{live_page.base_url}/#mappings')
    page.get_by_role('tab', name='CG mappings', exact=True).click()
    expect(page.locator('#validation-representation')).to_have_count(1)
    expect(page.locator('#validation-tier')).to_have_count(1)
    expect(page.locator('#launch-carbohydrate-validation')).to_be_disabled()
