"""The AA-CG run type's readiness asks about the profile it actually runs under.

`readiness()` gates its mapping check on the profile string (`if profile in ('draft-smoke','draft-smoke-reference')`)
and defaults to `'standard'` when a caller names none. The panel no longer offers an AA-CG run a profile choice and
sends none (D2 of `docs/design/2026-10-16-new-run-panel-refactor.md`), so that fallback both skipped the mapping
check and put a *standard*-parameterization blocker in front of a run type that has never run under that profile:

    standard              blockers ['A reviewed CG model is required for standard parameterization. Choose candidate …']
                          mapping checks []
    draft-smoke-reference blockers ['CG mapping: Select a saved CG mapping before launching candidate screening']
                          mapping checks [('CG mapping', False, 'Select a saved CG mapping …')]

`cg._protocol_readiness` now falls back to `AA_CG_PROFILE`, which is also `prepare()`'s own default -- the same rule
in both places, which is what the second test here pins, because a fallback that drifts from the builder's default
would put the panel's answer and the run's behaviour apart again.

None of that is a question about this machine's installed tools, so every test here but one injects the probe
(`injected_probe`): a real probe is a subprocess that imports a whole scientific stack, measured at 4.9 s cold for
the three a readiness asks about, and those three tests were the fast tier's slowest. The one that keeps asking the
real environment end to end is
`test_the_readiness_route_asks_about_the_profile_the_run_type_runs_under`: a seam added for testability still needs
one test that runs its defaults, or the defaults are only ever exercised by the user.
"""
import inspect

import pytest

from dashboard.execution.adapters import aa, cg


@pytest.fixture
def injected_probe(monkeypatch):
    """A probe answer that costs nothing, at the name each caller actually reads.

    `cg` and `aa` both wrote `from ..environment import probe_tool`, so each module has its own
    attribute and patching one is invisible to the other. The list the fixture returns is the
    executables the readiness path asked about, which is how a test can say the path did probe
    rather than assume it.
    """
    asked = []

    def answer(executable):
        asked.append(executable)
        return True, 'injected: this test is about the profile, not about the installed tools'

    monkeypatch.setattr(cg, 'probe_tool', answer)
    monkeypatch.setattr(aa, 'probe_tool', answer)
    return asked


def test_readiness_under_the_run_types_own_profile_checks_the_mapping(injected_probe):
    answer = cg.readiness('Maltose', 'fast_forward', cg.AA_CG_PROFILE, None, 'molecules')
    mapping = [check for check in answer['checks'] if check['label'] == 'CG mapping']
    assert mapping, 'the AA-CG profile must be the one whose mapping check runs'
    assert mapping[0]['ready'] is False
    assert 'Select a saved CG mapping' in mapping[0]['detail']
    assert any('Select a saved CG mapping' in blocker for blocker in answer['blockers'])
    assert injected_probe, 'the tool checks come from the injected probe, not from a subprocess'


def test_the_three_tool_checks_keep_their_order_and_a_missing_tool_is_named(monkeypatch):
    """Measuring the three at the same time may not reorder what the panel reads.

    `gmx`, `ff_inter` and `ff_assess` are written in the order a stage calls them, and the panel
    prints the list as it arrives. Concurrency is about the wait -- 5.09 s one after another,
    1.93 s together, measured 2026-10-20 -- not about the answer, so the order is pinned here and
    the timing is not: a suite that asserts a duration is a suite that fails on a busy machine.
    """
    monkeypatch.setattr(cg, 'probe_tool', lambda executable: (True, f'injected: {executable}'))
    monkeypatch.setattr(cg.tools, 'tool_path',
                        lambda name: None if name == 'ff_assess' else f'/injected/{name}')
    answer = cg.readiness('Maltose', 'fast_forward', cg.AA_CG_PROFILE, None, 'molecules')
    tools_checks = [check for check in answer['checks']
                    if check['label'] in cg.READINESS_TOOLS]
    assert [check['label'] for check in tools_checks] == list(cg.READINESS_TOOLS)
    assert [check['path'] for check in tools_checks] == ['/injected/gmx', '/injected/ff_inter', 'ff_assess']
    missing = tools_checks[-1]
    assert missing['ready'] is False
    assert missing['detail'] == 'Executable not found'
    assert 'ff_assess: Executable not found' in answer['blockers']


def test_the_readiness_fallback_is_the_builders_own_default():
    """One string, two places: a caller naming no profile gets the same one from both."""
    assert inspect.signature(cg.prepare).parameters['profile'].default == cg.AA_CG_PROFILE
    source = inspect.getsource(cg._protocol_readiness)
    assert "metadata.get('profile') or AA_CG_PROFILE" in source


def test_the_readiness_route_asks_about_the_profile_the_run_type_runs_under(dashboard):
    """The adapter's fallback only reaches an answer the route does not overwrite.

    `/api/readiness` used to build its metadata with `request.args.get('profile', 'standard')`, so an AA-CG request
    that named no profile -- which is every request the panel makes, since D2 removed the choice -- was judged
    under `standard`. That put `A reviewed CG model is required for standard parameterization` in front of a run
    type that has never run under that profile, and skipped the mapping check the same string gates.

    This is the one test here that asks the real environment end to end: no probe is injected, so the route, the
    protocol, `cg.readiness`, its three concurrent probes and `aa.readiness` all run their own defaults against
    whatever tools this machine has. It is the test that would notice if the seam stopped being wired.
    """
    with dashboard.client as client:
        answer = client.get('/api/readiness?run_type=aa_cg').get_json()

    assert answer['profile'] == cg.AA_CG_PROFILE
    assert not [blocker for blocker in answer['blockers'] if 'standard parameterization' in blocker]
    assert any(check['label'] == 'CG mapping' for check in answer['checks'])
    probed = [check for check in answer['checks'] if check['label'] in cg.READINESS_TOOLS]
    assert [check['label'] for check in probed] == list(cg.READINESS_TOOLS)
    assert all(check['detail'] for check in probed), 'a real probe says something about the tool it measured'


def test_a_typo_in_the_profile_is_still_reported_rather_than_silently_standard(dashboard, injected_probe):
    """The route's own default went away; its refusal of a name no run type has did not."""
    with dashboard.client as client:
        assert client.get('/api/readiness?run_type=aa_cg&profile=standrd').status_code == 400
        named = client.get('/api/readiness?run_type=aa_cg&profile=standard').get_json()

    assert named['profile'] == 'standard'
    assert any('standard parameterization' in blocker for blocker in named['blockers']), \
        'a caller that names standard still gets the standard answer'
