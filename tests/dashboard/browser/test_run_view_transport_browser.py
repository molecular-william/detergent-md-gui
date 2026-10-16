"""The transport row: two play buttons and one frame slider, on one line under the canvas.

The row is only honest if both its frames and its playback come from the viewer, so every assertion here reads the
renderer's own state back -- `trajectory.currentFrame`, `player.isRunning`, `player.parameters.direction` -- and
never the parameters this panel handed it. Two of the four traps the plan measured live here:

3. **A multi-model PDB loaded without `component.addTrajectory()` draws every model's atoms at once and has no
   trajectory at all**, so a row built on the assumption that the trajectory is there renders a plausible picture
   with a dead slider. `loadFile` does not attach one; the panel calls `addTrajectory()` and the row is driven from
   `trajList[0].trajectory`.
4. **Playback is `requestAnimationFrame`-driven, so a page that is not being rendered advances ZERO frames** -- a
   panel that keeps claiming to play while it is off screen returns the reader to a stale frame. Two things are
   measured here: that the playhead moves only while animation frames are being served, and that the row pauses
   when its panel stops being the open one.
"""
from playwright.sync_api import expect

from tests.dashboard.browser.test_run_view_browser import AA_RUN, FRAMES_RUN, MEASURE, open_panel, seed, wait_for_component

#: The renderer's own state, read back rather than inferred from what the panel asked for.
PLAYHEAD = """
() => {
  const host = document.querySelector('#run-view-viewer-A');
  const transport = host.runViewTransport;
  const trajectory = transport.trajectory;
  const player = transport.player;
  return {
    frames: transport.frames,
    frame: trajectory ? trajectory.currentFrame : null,
    moving: !!(player && player.isRunning),
    direction: player ? player.parameters.direction : null,
    mode: player ? player.parameters.mode : null,
    timeout: player ? player.parameters.timeout : null,
    start: player ? player.parameters.start : null,
    end: player ? player.parameters.end : null,
    slider: Number(document.querySelector('#run-view-frame-A').value),
    minimum: Number(document.querySelector('#run-view-frame-A').min),
    maximum: Number(document.querySelector('#run-view-frame-A').max),
    readout: document.querySelector('#run-view-frame-readout-A').textContent,
    rate: document.querySelector('#run-view-transport-note-A').textContent,
    forward: document.querySelector('#run-view-forward-A').getAttribute('aria-pressed'),
    reverse: document.querySelector('#run-view-reverse-A').getAttribute('aria-pressed'),
    disabled: ['#run-view-reverse-A', '#run-view-forward-A', '#run-view-frame-A']
      .map(selector => document.querySelector(selector).disabled),
    titles: ['#run-view-reverse-A', '#run-view-forward-A', '#run-view-frame-A']
      .map(selector => document.querySelector(selector).title),
  };
}
"""

#: The row's geometry, and what is drawn above it, at whatever width the window is.
GEOMETRY = """
() => {
  const box = (selector) => {
    const rectangle = document.querySelector(selector).getBoundingClientRect();
    return {x: Math.round(rectangle.x), y: Math.round(rectangle.y), width: Math.round(rectangle.width),
            height: Math.round(rectangle.height), top: rectangle.top, bottom: rectangle.bottom,
            right: rectangle.right, centre: rectangle.top + rectangle.height / 2};
  };
  const controls = ['#run-view-reverse-A', '#run-view-forward-A', '#run-view-frame-A'].map(box);
  return {
    controls: controls,
    tops: controls.map(control => control.y),
    centres: controls.map(control => control.centre),
    tallest: Math.max(...controls.map(control => control.height)),
    row: box('#run-view-transport-A'),
    panel: box('#runview'),
    canvas: box('#run-view-viewer-A'),
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
}
"""


def move_slider(page, value):
    page.evaluate("""(value) => {
      const slider = document.querySelector('#run-view-frame-A');
      slider.value = String(value);
      slider.dispatchEvent(new Event('input', {bubbles: true}));
    }""", value)


def test_the_row_is_drawn_and_disabled_with_its_reason_where_the_file_holds_one_frame(dashboard, live_page):
    """D17: a drawn-but-disabled row says more than a hidden one, and this is every run without a frame series."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=AA_RUN)
    wait_for_component(page, atoms=5)

    measured = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    expect(page.locator('#run-view-transport-A')).to_be_visible()
    assert measured['disabled'] == [True, True, True], 'all three controls are disabled'
    assert all(title.strip() for title in measured['titles']), 'and each says why in its own title'
    assert 'holds one frame' in measured['titles'][0]
    assert '100 ms a frame' in measured['rate'], 'the fixed rate is printed rather than offered as a control'
    assert 'lig.xtc' in measured['rate'], 'and the trajectory no route serves a frame of is named'
    assert measured['readout'] == 'frame 0 of 0'
    assert errors == []


def test_the_published_frame_series_gives_the_row_a_real_trajectory(dashboard, live_page):
    """Trap 3's positive half: one request for the whole series, a trajectory, and the slider bound to its count."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    measured = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert measured['frames'] == 5, 'the multi-model PDB is a trajectory, not five models in one picture'
    assert measured['disabled'] == [False, False, False]
    assert (measured['minimum'], measured['maximum']) == (0, 4), 'the slider is the frame index, 0 to frameCount - 1'
    assert measured['readout'] == 'frame 0 of 4'
    # The rate is fixed (D13), the ends stop (D12), and the range starts at 0 so every frame stays reachable in
    # reverse (D14).
    assert measured['timeout'] == 100 and measured['mode'] == 'once' and measured['start'] == 0
    assert measured['end'] == 4
    assert 'stride of 7' in measured['rate'], 'the stride the frames were sampled at is said in words'
    assert errors == []


def test_playing_forward_advances_the_renderers_own_playhead_and_stops_at_the_last_frame(dashboard, live_page):
    """D12/D14: forward from a frame runs on and stops on the last one, and the slider is never the driver."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    move_slider(page, 1)
    assert page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)['frame'] == 1

    page.locator('#run-view-forward-A').click()
    page.wait_for_timeout(200)
    moving = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert moving['moving'] and moving['direction'] == 'forward', moving
    assert moving['frame'] > 1, 'the playhead moved'
    assert moving['forward'] == 'true' and moving['reverse'] == 'false', 'the running direction is the pressed one'

    page.wait_for_timeout(1500)
    stopped = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert stopped['frame'] == 4, f'the playhead stops on the last frame: {stopped}'
    assert not stopped['moving'], 'and stops rather than wrapping (D12)'
    assert stopped['forward'] == 'false', 'and the pressed state goes with it'
    assert stopped['slider'] == 4 and stopped['readout'] == 'frame 4 of 4'
    assert errors == []


def test_playing_in_reverse_runs_the_other_way_and_stops_at_the_first_frame(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    move_slider(page, 4)
    page.locator('#run-view-reverse-A').click()
    page.wait_for_timeout(200)
    moving = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert moving['moving'] and moving['direction'] == 'backward', moving
    assert moving['frame'] < 4, 'the playhead moved backwards'
    assert moving['reverse'] == 'true' and moving['forward'] == 'false'

    page.wait_for_timeout(1500)
    stopped = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert stopped['frame'] == 0, f'the playhead stops on the first frame: {stopped}'
    assert not stopped['moving']
    assert errors == []


def test_the_slider_is_the_frame_shown_and_the_frame_playback_starts_from(dashboard, live_page):
    """D14: moving the slider moves the drawn atoms and pauses; replaying starts where the slider is."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    before = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    move_slider(page, 3)
    after = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert after['frame'] == 3 and after['slider'] == 3
    assert after['readout'] == 'frame 3 of 4'
    assert before['readout'] != after['readout'], 'the readout follows the playhead'
    # The playhead is the trajectory's, so the drawn atoms are the frame's own rather than the previous one's.
    structure = page.locator('#run-view-viewer-A').evaluate(MEASURE)
    assert structure['atoms'] == 8

    page.locator('#run-view-forward-A').click()
    page.wait_for_timeout(400)
    played = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert played['frame'] > 3, 'playback starts from the frame the slider left it on'
    assert errors == []


def test_the_strip_sets_the_frame_and_follows_the_playhead_it_never_drives(dashboard, live_page):
    """D16: a strip button sets the frame and stops; the pressed state moves only on an exact match."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    buttons = page.locator('#run-view-frames-A button')
    expect(buttons).to_have_count(3)
    labels = buttons.all_inner_texts()
    assert labels == ['first', 'middle', 'last'], labels

    buttons.nth(2).click()
    moved = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert moved['frame'] == 4 and not moved['moving'], 'a strip button sets the frame and stops there'
    expect(buttons.nth(2)).to_have_attribute('aria-pressed', 'true')
    expect(buttons.nth(0)).to_have_attribute('aria-pressed', 'false')

    buttons.nth(1).click()
    back = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert back['frame'] == 2 and not back['moving']
    expect(buttons.nth(1)).to_have_attribute('aria-pressed', 'true')
    expect(buttons.nth(2)).to_have_attribute('aria-pressed', 'false')
    assert errors == []


def test_the_three_controls_share_one_line_inside_the_panel_below_the_canvas(dashboard, live_page):
    """The ask's geometry, and the two widths the plan measured it at.

    A row that folded into two lines, or that sat above the canvas, or that overflowed its panel, would still look
    plausible in a screenshot -- only the boxes say otherwise.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    for width in (1600, 1100, 390):
        page.set_viewport_size({'width': width, 'height': 900})
        page.wait_for_timeout(100)
        measured = page.evaluate(GEOMETRY)
        spread = max(measured['centres']) - min(measured['centres'])
        assert spread <= measured['tallest'] / 2, (
            f'at {width} px the three controls are not one row: centres {measured["centres"]} '
            f'spread {spread:.1f} against a tallest control of {measured["tallest"]}')
        assert measured['row']['right'] <= measured['panel']['right'] + 1, \
            f'at {width} px the row overflows its panel: {measured["row"]} against {measured["panel"]}'
        assert measured['row']['x'] >= measured['panel']['x'] - 1
        assert measured['row']['bottom'] <= measured['panel']['bottom'] + 1
        assert measured['canvas']['bottom'] <= measured['row']['top'] + 1, \
            f'at {width} px the canvas is not above the row: {measured["canvas"]} {measured["row"]}'
        assert measured['overflow'] == 0, f'at {width} px the page scrolls sideways by {measured["overflow"]} px'
    assert errors == []


def test_playback_is_driven_by_animation_frames_and_nothing_else_moves_the_playhead(dashboard, live_page):
    """Trap 4, measured: with no animation frames served, not one frame advances.

    The plan's own measurement was a background tab -- `requestAnimationFrame` ticked zero times in a second while
    the page was hidden, and 61 a second when it was brought back. This harness cannot hide a page from Chromium
    (measured: a page in a second context, and a page CDP-frozen, both kept serving ~50 ticks a second, and
    `document.visibilityState` stayed `visible`), so the dependency is measured at its cause instead: take the
    animation frames away and the playhead goes nowhere, put them back and it runs. That is the same statement, and
    it is the one that decides whether a frozen row may claim to be playing.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    move_slider(page, 0)
    page.evaluate("""() => {
      window.__asked = 0;
      window.__realRaf = window.requestAnimationFrame.bind(window);
      window.requestAnimationFrame = () => { window.__asked += 1; return 0; };
    }""")
    page.locator('#run-view-forward-A').click()
    page.wait_for_timeout(600)
    assert page.evaluate('window.__asked') > 0, 'the player asks the renderer for frames'
    frozen = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert frozen['frame'] == 0, f'with no animation frames served, nothing advances: {frozen}'
    assert frozen['slider'] == 0 and frozen['readout'] == 'frame 0 of 4'

    page.evaluate('() => { window.requestAnimationFrame = window.__realRaf; }')
    page.locator('#run-view-forward-A').click()   # the running direction's own button pauses
    page.locator('#run-view-forward-A').click()   # and pressing it again plays
    page.wait_for_timeout(400)
    resumed = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert resumed['frame'] > 0, 'and the row plays again once frames are being served'
    assert errors == []


def test_the_row_stops_playing_when_its_panel_is_no_longer_the_open_one(dashboard, live_page):
    """Trap 4's answer: a panel that is not on screen pauses rather than returning a stale frame.

    The plan's measured consequence -- a row that plays while unselected shows its last frame and nothing else --
    is what this panel refuses to do: the playhead stops where the reader left it, and the readout says so.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    move_slider(page, 0)
    page.locator('#run-view-forward-A').click()
    page.wait_for_timeout(300)
    assert page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)['moving']

    page.locator('#tab-runs').click()
    expect(page.locator('#runview')).to_be_hidden()
    left = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert not left['moving'], 'the row pauses when its panel stops being the open one'
    page.wait_for_timeout(700)
    later = page.locator('#run-view-viewer-A').evaluate(PLAYHEAD)
    assert not later['moving'], 'and it does not keep playing unobserved'
    assert later['frame'] == left['frame'], 'the frame it stopped on is the frame the reader left'
    assert errors == []
