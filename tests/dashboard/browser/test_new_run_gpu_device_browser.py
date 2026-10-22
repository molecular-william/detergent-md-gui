"""The GPU device control on the New run panel: the host's options, and the note about a busy device.

Two claims, and both are about what the panel does with an answer it did not compute:

* **The options are the host's.** `#run-gpu-device` is filled from `GET /api/run/devices` -- stubbed here, because
  no test may need a GPU -- one option per device as `index - name - memory MiB`, and device 0 is what an untouched
  form selects.
* **A busy device is reported, never refused.** When `in_use` reports compute processes on the chosen device the
  panel says so, and when several ranks will share one device it says that too. Start stays enabled: a busy device
  is a fact to see, not a reason to stop a run, which is the project's record-and-warn rule.

The device travels as the ordinary setting `mdrun_gpu`, so the third test reads it out of the POST body rather than
above the form.
"""
import json

from playwright.sync_api import expect

DEVICES = [{'index': 0, 'name': 'NVIDIA GeForce RTX 4090', 'memory_mib': 24564, 'uuid': 'GPU-aaaa'},
           {'index': 1, 'name': 'NVIDIA A100-SXM4-40GB', 'memory_mib': 40960, 'uuid': 'GPU-bbbb'}]
SHARING = 'Device 1 is already running 2 compute processes; mdrun will share it.'


def stub(page, in_use=None):
    page.route('**/api/run/devices',
               lambda route: route.fulfill(json={'devices': DEVICES, 'in_use': in_use or {}}))


def open_panel(page, base_url, in_use=None):
    """The validation workspace's New run panel, with the device list already answered."""
    stub(page, in_use)
    page.goto(f'{base_url}/detergent-validation/new-run')
    page.wait_for_function(
        "() => document.querySelectorAll('#run-gpu-device option').length === 2", timeout=30000)
    return page


def test_the_panel_offers_the_devices_the_host_reports(dashboard, live_page):
    page, errors = live_page
    open_panel(page, live_page.base_url)
    options = page.evaluate(
        "Array.from(document.querySelectorAll('#run-gpu-device option')).map(o => [o.value, o.textContent])")
    assert options == [['0', '0 - NVIDIA GeForce RTX 4090 - 24564 MiB'],
                       ['1', '1 - NVIDIA A100-SXM4-40GB - 40960 MiB']]
    expect(page.locator('#run-gpu-device')).to_have_value('0')
    expect(page.locator('#run-gpu-note')).to_have_text('')
    assert errors == []


def test_a_busy_device_is_reported_and_never_refused(dashboard, live_page):
    page, errors = live_page
    dashboard.coordinator.database().replace([])
    page.route('**/api/defaults?*', lambda route: route.fulfill(
        json={'values': {'mdrun_ntomp': 8, 'mdrun_ranks': 1}, 'sources': {'AA': 'test'}, 'profile': 'standard'}))
    page.route('**/api/readiness?*', lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_only',molecule_id:'DDM'}))")
    open_panel(page, live_page.base_url, in_use={'1': 2})
    page.locator('#run-gpu-device').select_option('1')
    expect(page.locator('#run-gpu-note')).to_have_text(SHARING)
    # A readiness note, not a gate: the run can still be started.
    expect(page.locator('#start-run')).to_be_enabled()
    # Several ranks share the one device, and the panel says so beside the measurement above.
    page.locator('[name=mdrun_ranks]').fill('2')
    expect(page.locator('#run-gpu-note')).to_contain_text(SHARING)
    expect(page.locator('#run-gpu-note')).to_contain_text('One device is shared by all 2 ranks.')
    page.locator('#run-gpu-device').select_option('0')
    expect(page.locator('#run-gpu-note')).to_have_text('One device is shared by all 2 ranks.')
    assert errors == []


def test_the_posted_settings_carry_the_chosen_device(dashboard, live_page):
    """The device is an ordinary setting: the form posts it as `mdrun_gpu`, under the key the adapter publishes."""
    page, errors = live_page
    dashboard.coordinator.database().replace([])
    url = f'{live_page.base_url}/'
    submissions = []
    page.route('**/api/defaults?*', lambda route: route.fulfill(
        json={'values': {'mdrun_ntomp': 8, 'mdrun_ranks': 1}, 'sources': {'AA': 'test'}, 'profile': 'standard'}))
    page.route('**/api/readiness?*', lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_only',molecule_id:'DDM'}))")
    open_panel(page, live_page.base_url)

    def submit(route):
        submissions.append(route.request.post_data_json)
        route.fulfill(status=201, json={'id': '222222222222'})

    page.route(url, submit)
    page.locator('#run-gpu-device').select_option('1')
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    assert submissions and submissions[0]['mdrun_gpu'] == '1'
    # The saved form remembers the choice, so a reload does not silently move the run back to device 0.
    assert json.loads(page.evaluate("localStorage.getItem('ddm.form')"))['mdrun_gpu'] == '1'
    assert errors == []
