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
"""
import pytest

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

METADATA = {'molecule_id': 'DDM', 'method': 'fast_forward', 'profile': 'standard',
            'mapping_candidate': None, 'composition_id': None}


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
