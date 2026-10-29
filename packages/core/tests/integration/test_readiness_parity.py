"""The readiness route and the run-type protocol must answer the same question the same way.

Phase 2 of the audit's plan. `/api/readiness` reached into the adapters directly -- `pdc.readiness(...)`,
`composition.readiness(...)`, `aa.readiness(...)`, `cg.readiness(...)` -- and for `aa_cg` it collected two answers by
hand and merged them. The protocol already publishes a `readiness` for every run type, so the route had a surface to
ask and reached past it instead.

What that costs is not a wrong answer today but a second place to keep right: an `aa_cg` run needs everything the
coarse-grained half needs *and* everything the atomistic half needs, and that rule lived in a web route. These tests
pin the two answers together so the merge can move to the adapter without changing what a caller is told.

The assertions compare `ready` and the *set* of blockers, not the whole payload: the route decorates its answer with
the molecule it inspected, which is a view concern the protocol has no reason to know about.

Nothing here is a question about this machine's tools, and each case asks two readiness paths, so the probe is
injected: a real probe is a subprocess importing a whole scientific stack (~4.9 s cold for the three a CG readiness
asks about). The real environment end to end is asked once, in
`packages/core/tests/integration/test_readiness_aa_cg_profile.py::test_the_readiness_route_asks_about_the_profile_the_run_type_runs_under`.
"""
import pytest
from dashboard.execution import environment
from dashboard.execution.adapters import aa, cg
from dashboard.execution.protocol import adapter_for

# Each case is a run type and the query the readiness panel sends. The first two send no molecule at all, because
# with a molecule the route inspects it first and answers from *that* -- a page-level concern the protocol has no
# business knowing -- so only the blocked path is comparable, and comparing it is what pins the two wordings together.
CASES = (
    ('aa_only', 'run_type=aa_only'),
    ('aa_cg', 'run_type=aa_cg'),
    ('pdc', 'run_type=pdc'),
    ('cg_composition', 'run_type=cg_composition'),
)

METADATA = {'molecule_id': 'DDM', 'method': 'fast_forward', 'mapping_candidate': None, 'composition_id': None}
"""The metadata the route builds for a query that names no profile.

No `profile` key on purpose: the route passes no profile when the query names none, and each run type answers with
its own default (`cg.AA_CG_PROFILE` for an AA-to-CG run). Putting `'standard'` here would be the page's old
fallback written into the comparison, which is exactly the drift this file exists to catch.
"""


@pytest.fixture(autouse=True)
def injected_probe(monkeypatch):
    """One probe answer, at every name a readiness path in this file reads.

    `cg` and `aa` bound the name at import, so each has its own attribute; `pdc.readiness` imports
    it inside the function, so it reads the one on the environment module. All three are patched,
    because a case here compares two paths over the same run types and a subprocess on only one of
    them would be both slow and a difference the comparison would have to explain.
    """

    def answer(executable):
        return True, 'injected: this file compares two answers about the same tools'

    monkeypatch.setattr(cg, 'probe_tool', answer)
    monkeypatch.setattr(aa, 'probe_tool', answer)
    monkeypatch.setattr(environment, 'probe_tool', answer)


def essentials(answer):
    return answer.get('ready'), sorted(str(blocker) for blocker in answer.get('blockers') or [])


@pytest.mark.parametrize('run_type,query', CASES)
def test_the_route_and_the_protocol_agree_for_a_run_that_cannot_start(dashboard, run_type, query):
    with dashboard.client as client:
        route = client.get(f'/api/readiness?{query}').get_json()
    coordinator = dashboard.coordinator
    metadata = dict(METADATA, molecule_root=coordinator.ROOT / 'molecules', runs_root=coordinator.RUNS,
                    protein=None, template=None, project_root=coordinator.ROOT)
    via_protocol = adapter_for(run_type).readiness(metadata)
    assert essentials(route) == essentials(via_protocol), (
        f'{run_type}: the route says {essentials(route)} where the protocol says {essentials(via_protocol)}')


def test_an_aa_cg_run_needs_both_halves(dashboard):
    """The rule the route was carrying: a coarse-grained run of an atomistic molecule needs the molecule too.

    Stated as a test of the *adapter* rather than of the route, because that is where it is moving: an `aa_cg` plan
    cannot prepare its reference without a molecule, so a missing one is a blocker for the run type and not a detail
    of one page that asks about it.
    """
    answer = adapter_for('aa_cg').readiness({'molecule_id': 'NOT-A-MOLECULE', 'method': 'fast_forward',
                                            'profile': 'standard',
                                            'molecule_root': dashboard.coordinator.ROOT / 'molecules'})
    assert answer['ready'] is False
    assert answer['blockers'], 'a molecule that does not exist is a blocker for an aa_cg run'
