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
import re

import pytest
from playwright.sync_api import expect

DEVICES = [{'index': 0, 'name': 'NVIDIA GeForce RTX 4090', 'memory_mib': 24564, 'uuid': 'GPU-aaaa'},
           {'index': 1, 'name': 'NVIDIA A100-SXM4-40GB', 'memory_mib': 40960, 'uuid': 'GPU-bbbb'}]
SHARING = 'Device 1 is already running 2 compute processes; mdrun will share it.'


def stub(page, in_use=None):
    page.route('**/api/run/devices',
               lambda route: route.fulfill(json={'devices': DEVICES, 'in_use': in_use or {}}))


def open_panel(page, base_url, in_use=None):
    """The validation workspace's New run panel, with the device list already answered.

    The execution controls sit in the collapsed Other run options, so opening that fold is part of opening the panel.
    """
    stub(page, in_use)
    page.goto(f'{base_url}/detergent-validation/new-run')
    page.wait_for_function(
        "() => document.querySelectorAll('#run-gpu-device option').length === 2", timeout=30000)
    page.locator('#new-advanced > summary').click()
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


def test_a_read_that_fails_keeps_device_0_and_does_not_claim_the_host_has_none(dashboard, live_page):
    """An unreachable route is not a host without a GPU, and the panel must not say it is.

    This is the shape of a server started before `/api/run/devices` existed: the route answers 404, `api()` throws,
    and an earlier version filled an empty select labelled "No GPU detected" -- a claim about the host made by a
    request that never reached it -- while the note underneath said the read had failed. Two sentences contradicting
    each other, and the select also disabled itself, so `mdrun_gpu` left the form and the run recorded no device at
    all. Now the option says what happened and keeps 0, which is the device the command carries regardless.
    """
    page, errors = live_page
    page.route('**/api/run/devices', lambda route: route.fulfill(status=500, json={'error': 'probe failed'}))
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.wait_for_function(
        "() => document.querySelectorAll('#run-gpu-device option').length === 1", timeout=30000)
    option = page.evaluate(
        "(() => { const o = document.querySelector('#run-gpu-device option'); return [o.value, o.textContent]; })()")
    assert option == ['0', 'Device 0 (devices could not be read)']
    expect(page.locator('#run-gpu-device')).to_be_enabled()
    expect(page.locator('#run-gpu-note')).to_have_text(
        'The GPU devices could not be read; the command keeps device 0.')


def test_a_host_with_no_gpu_offers_no_device_control_and_posts_none(dashboard, live_page):
    """A host that reports no devices has no device to choose: the control is gone, and the form posts no device.

    "No GPU" is an answer the panel received, so it is not the failed-read case below: there is no select to leave
    disabled and no note claiming the command keeps device 0. The offload scheme loses its `gpu` option too, and
    the run's payload names no `mdrun_gpu` for the route to drop.
    """
    page, errors = live_page
    dashboard.coordinator.database().replace([])
    url = f'{live_page.base_url}/'
    submissions = []
    page.route('**/api/defaults?*', lambda route: route.fulfill(
        json={'values': {'mdrun_ntomp': 8, 'mdrun_ranks': 1}, 'sources': {'AA': 'test'}, 'profile': 'standard'}))
    page.route('**/api/readiness?*', lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.route('**/api/run/devices', lambda route: route.fulfill(json={'devices': [], 'in_use': {}}))
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_only',molecule_id:'DDM'}))")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.wait_for_function(
        "() => document.querySelector('#run-gpu-device').closest('label').hidden === true", timeout=30000)

    expect(page.locator('#run-gpu-device')).to_be_hidden()
    expect(page.locator('#run-gpu-note')).to_have_text('')
    schemes = page.evaluate(
        "Array.from(document.querySelectorAll('[name=mdrun_nb] option, [name=mdrun_pme] option')).map(o => o.value)")
    assert 'gpu' not in schemes, schemes

    def submit(route):
        submissions.append(route.request.post_data_json)
        route.fulfill(status=201, json={'id': '333333333333'})

    page.route(url, submit)
    expect(page.locator('#start-run')).to_be_enabled()
    page.locator('#start-run').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    assert submissions and 'mdrun_gpu' not in submissions[0], submissions
    assert errors == []


def test_a_cg_run_is_offered_no_pme_scheme(dashboard, live_page):
    """A CG leg is reaction-field, so the PME scheme, its FFT and its load tuning are not offered to it.

    The controls are the AA half's: a CG run that named `mdrun_pme: gpu` produced a flag GROMACS refuses (run
    `6ed68979edf0`), and the form must not invite the choice the engine now retires.
    """
    page, errors = live_page
    page.route('**/api/defaults?*', lambda route: route.fulfill(
        json={'values': {'mdrun_ntomp': 8, 'mdrun_ranks': 1}, 'sources': {'AA': 'test'}, 'profile': 'standard'}))
    page.route('**/api/readiness?*', lambda route: route.fulfill(json={'ready': True, 'checks': [], 'blockers': []}))
    page.add_init_script("localStorage.setItem('ddm.form', JSON.stringify({run_type:'cg',molecule_id:'DDM'}))")
    page.goto(f'{live_page.base_url}/detergent-validation/new-run')
    page.locator('#new-advanced > summary').click()

    expect(page.locator('[name=mdrun_nb]')).to_be_visible()
    for control in ('mdrun_pme', 'mdrun_pmefft', 'mdrun_tunepme'):
        expect(page.locator(f'[name={control}]')).to_be_hidden()

    page.locator('#run-type').select_option('aa_only')
    for control in ('mdrun_pme', 'mdrun_pmefft', 'mdrun_tunepme'):
        expect(page.locator(f'[name={control}]')).to_be_visible()
    assert errors == [], errors


# --- Queue or share the device ------------------------------------------------------------------------------------
#
# The two launch buttons are the same words for AA and CG runs. Queue needs only readiness; Share also needs a run
# already on the chosen device, which is what `GET /api/run/devices` `active` reports. The payload's own
# `gpu_sharing` is asserted from the POST body -- the form's contribution to the coordinator's choice.

def stub_launch_answers(page, ready=True):
    page.route('**/api/defaults?*', lambda route: route.fulfill(
        json={'values': {'mdrun_ntomp': 8, 'mdrun_ranks': 1}, 'sources': {'AA': 'test'}, 'profile': 'standard'}))
    page.route('**/api/readiness?*', lambda route: route.fulfill(json={
        'ready': ready, 'checks': [], 'blockers': [] if ready else ['Select an available molecule directory.']}))
    page.add_init_script(
        "localStorage.setItem('ddm.form', JSON.stringify({run_type:'aa_only',molecule_id:'DDM'}))")


def open_launch_form(page, base_url):
    page.goto(f'{base_url}/detergent-validation/new-run')
    page.wait_for_function(
        "() => document.querySelectorAll('#run-gpu-device option').length === 2", timeout=30000)
    page.locator('#new-advanced > summary').click()
    return page


def test_share_is_disabled_until_the_chosen_device_reports_an_active_run(dashboard, live_page):
    page, errors = live_page
    dashboard.coordinator.database().replace([])
    stub_launch_answers(page)
    answer = {'active': {}}
    page.route('**/api/run/devices', lambda route: route.fulfill(
        json={'devices': DEVICES, 'in_use': {}, **answer}))
    open_launch_form(page, live_page.base_url)

    # A free device: Queue can create the run now, Share has nothing to share with.
    expect(page.locator('#start-run')).to_be_enabled()
    expect(page.locator('#start-run-share')).to_be_disabled()

    # The selection's own device reports a run: Share may start alongside it. Device 0 has none.
    answer['active'] = {'1': ['run-already-on-one']}
    page.locator('#run-gpu-device').select_option('1')
    expect(page.locator('#start-run-share')).to_be_enabled()
    page.locator('#run-gpu-device').select_option('0')
    expect(page.locator('#start-run-share')).to_be_disabled()
    assert errors == []


@pytest.mark.parametrize('button, sharing', [('start-run', 'queue'), ('start-run-share', 'share')])
def test_each_launch_button_posts_its_own_gpu_sharing(dashboard, live_page, button, sharing):
    page, errors = live_page
    dashboard.coordinator.database().replace([])
    stub_launch_answers(page)
    page.route('**/api/run/devices', lambda route: route.fulfill(
        json={'devices': DEVICES, 'in_use': {}, 'active': {'0': ['run-already-on-zero']}}))
    submissions = []

    def submit(route):
        submissions.append(route.request.post_data_json)
        route.fulfill(status=201, json={'id': '444444444444'})

    page.route(re.compile(r'^http://127\.0\.0\.1:\d+/$'), submit)
    open_launch_form(page, live_page.base_url)

    expect(page.locator(f'#{button}')).to_be_enabled()
    page.locator(f'#{button}').click()
    expect(page.locator('#notice')).to_have_text('Run queued.')
    assert submissions and submissions[0]['gpu_sharing'] == sharing, submissions
    assert errors == []


def test_readiness_not_ready_disables_both_launch_buttons(dashboard, live_page):
    page, errors = live_page
    stub_launch_answers(page, ready=False)
    page.route('**/api/run/devices', lambda route: route.fulfill(
        json={'devices': DEVICES, 'in_use': {}, 'active': {'0': ['run-already-on-zero']}}))
    open_launch_form(page, live_page.base_url)

    expect(page.locator('#review-status')).to_have_text('Action required')
    expect(page.locator('#start-run')).to_be_disabled()
    expect(page.locator('#start-run-share')).to_be_disabled()
    assert errors == []


def test_an_older_device_payload_without_active_leaves_share_disabled(dashboard, live_page):
    """A server from before `active` existed must not enable Share on a guess: unknown is not "a run is there"."""
    page, errors = live_page
    dashboard.coordinator.database().replace([])
    stub_launch_answers(page)
    page.route('**/api/run/devices',
               lambda route: route.fulfill(json={'devices': DEVICES, 'in_use': {'0': 1}}))
    open_launch_form(page, live_page.base_url)

    expect(page.locator('#start-run')).to_be_enabled()
    expect(page.locator('#start-run-share')).to_be_disabled()
    assert errors == []
