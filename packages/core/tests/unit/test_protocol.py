"""Every run type answers the same protocol surface, in the same shapes.

The interface exists so no caller has to know which adapter it is talking to:
the coordinator, the queue routes and these tests all ask the same questions
and get the same shapes back. These tests pin the shapes, not the internals.
"""
import importlib
import subprocess
from collections.abc import Mapping

import pytest
from dashboard.execution import protocol, tools

RUN_TYPES = ('aa_only', 'aa_cg', 'cg_composition')
"""The run types whose contract is molecule-scoped, which is what the shape assertions below can be stated over.

Deliberately narrower than `protocol.RUN_TYPES`: a pdc build is prepared from a protein and a template and is
*allowed* to run with no protein at all (the empty micelle is a design decision, reported as a check rather than a
blocker), so `readiness({})` answering "ready" is right for it and wrong for the three below.
"""


def published_vocabulary(adapter):
    """Everything a run type says it accepts: its numeric settings and its choice-typed ones together."""
    return set(adapter.settings_specs()) | set(adapter.choice_specs())


@pytest.mark.parametrize('run_type', protocol.RUN_TYPES)
def test_every_published_setting_declares_what_a_value_may_be(run_type):
    """A form renders one control per published key, so each has to say what a valid value looks like.

    Two shapes and each has its own meaning. A bounded setting declares `(label, lo, hi)` and the range has to be
    one. A choice declares `(label, options)`, and an *empty* options tuple is a declaration rather than a gap: it
    says the value is free text, which is how `osmotic` declares its series id and solute root -- strings with no
    enumerable domain. Its normalizer reads it that way (`if allowed and text not in allowed`), so a run type may
    publish a key it places no enumeration on.

    The alternative -- reading a value back out of `normalize_settings` to prove the key is accepted -- does not
    work: a raise means either "I do not know this key" or "I know it and this value breaks a rule about it", and
    the adapters disagree about which of those they raise. That direction is asserted where it has a user-facing
    observable, which is a job posted through the queue keeping the keys the form offered.
    """
    adapter = protocol.adapter_for(run_type)
    for key, spec in {**adapter.settings_specs(), **adapter.choice_specs()}.items():
        if len(spec) == 2:
            assert isinstance(spec[1], tuple), f'{run_type}: {key} declares options that are not a tuple'
        else:
            label, lo, hi = spec
            assert lo < hi, f'{run_type}: {key} declares an empty range {lo}..{hi}'
            assert isinstance(lo, (int, float)) and isinstance(hi, (int, float)), f'{run_type}: {key} bounds'
        assert isinstance(spec[0], str) and spec[0], f'{run_type}: {key} has no label to render'


def test_the_queue_routes_vocabulary_is_the_run_types_own():
    """The route used to merge dialects itself; one run type was answered wrongly by that merge.

    It computed `cg.SETTING_SPECS | aa.SETTING_SPECS | aa.CHOICE_SPECS` for everything that was not `aa_only` or
    `pdc`. For the three run types that reaches, that happens to equal the run type's own vocabulary -- and for
    `osmotic` it does not: the molality, which is the one setting that makes a series a series, is in neither half.
    It is not in the run type's tables either, and that is deliberate: the concentrations are a *list*, the route
    that queues a series reads its own body, and no form control could carry it. The old single-molality setting is
    gone entirely, which is what leaves the two shapes tellable apart.
    """
    from dashboard.execution.adapters import aa, cg
    merged = set(cg.SETTING_SPECS) | set(aa.SETTING_SPECS) | set(aa.CHOICE_SPECS)
    osmotic = published_vocabulary(protocol.adapter_for('osmotic'))
    assert 'osmotic_production_ps' in osmotic, "the series' own settings are part of its own vocabulary"
    assert 'osmotic_production_ps' not in merged, 'and they were not in the union the route computed for it'
    assert 'molalities' not in osmotic, 'the series list is deliberately in neither published table'
    assert 'osmotic_molality' not in osmotic, "the old shape's single molality is not a setting any more"


def test_an_aa_cg_run_publishes_both_halves_it_accepts():
    """The regression the queue route was working around.

    An AA-to-CG run's `normalize_settings` takes a key from the AA half and from the CG half, so it has to publish
    both. It published only the CG dialect while the route merged the two by hand -- and a caller who read the
    published vocabulary and posted it back would have had their AA settings dropped on the floor.
    """
    from dashboard.execution.adapters import aa, cg
    published = published_vocabulary(protocol.adapter_for('aa_cg'))
    for half, specs in (('AA', aa.SETTING_SPECS), ('CG', cg.SETTING_SPECS), ('AA choices', aa.CHOICE_SPECS)):
        missing = set(specs) - published
        assert not missing, f'{half} settings an aa_cg run accepts but does not publish: {sorted(missing)}'


def test_the_published_run_types_are_the_registrys_own():
    """`RUN_TYPES` is what a caller iterates to reach every run type, so it cannot be a list someone maintains.

    It once omitted `osmotic` while `_BUILDERS` carried it: every run type was reachable by name and invisible to
    anything that walked the published tuple, which is the same shape of bug as a registry nobody can enumerate.
    """
    assert set(protocol.RUN_TYPES) == {'aa_only', 'aa_cg', 'cg_composition', 'pdc', 'osmotic'}
    for run_type in protocol.RUN_TYPES:
        assert protocol.adapter_for(run_type).name == run_type



def test_adapter_for_rejects_an_unknown_run_type():
    with pytest.raises(ValueError):
        protocol.adapter_for('cg_no_such_thing')


@pytest.mark.parametrize('run_type', RUN_TYPES)
def test_adapter_for_returns_the_adapter_named_by_the_run_type(run_type):
    assert protocol.adapter_for(run_type).name == run_type


@pytest.mark.parametrize('run_type', RUN_TYPES)
def test_every_adapter_exposes_the_same_surface(run_type):
    adapter = protocol.adapter_for(run_type)
    plan, required_inputs, required_outputs = adapter.stage_contract({})
    assert plan, 'the stage contract must declare at least one stage'
    assert required_inputs is not None and required_outputs is not None
    assert adapter.stages({}), 'the adapter must resolve its own stage declarations'
    specs = adapter.settings_specs()
    assert all(isinstance(bounds, tuple) and len(bounds) in (2, 3) for bounds in specs.values())
    assert set(adapter.readiness({})) >= {'ready', 'checks', 'blockers'}
    assert callable(adapter.tool_report)
    assert isinstance(adapter.stage_defaults(), dict)
    assert callable(adapter.normalize_settings) and callable(adapter.prepare)


@pytest.mark.slow
@pytest.mark.parametrize('run_type', RUN_TYPES)
def test_tool_report_returns_a_mapping_or_fails_loudly(run_type):
    """A tool that cannot be reported must fail the report, not be left out of it.

    Preparation records this mapping in the run manifest, so a partial answer
    would let a run start on tools nobody verified. What is under test is that a
    gap is loud rather than silent: `aa_cg` either returns a full mapping or
    raises while naming the tool it could not report, whichever this machine's
    environment supports.
    """
    adapter = protocol.adapter_for(run_type)
    try:
        report = adapter.tool_report()
    except (OSError, subprocess.CalledProcessError) as exc:
        assert str(exc), 'the failure must name what could not be reported'
    else:
        assert isinstance(report, Mapping)
        if run_type == 'aa_cg' and tools.declared('fast_forward_source'):
            # A version output says nothing about which source produced the tool.
            provenance = report['fast_forward_source']
            assert provenance['path'] and provenance['declared_commit'], provenance


@pytest.mark.parametrize('run_type', RUN_TYPES)
def test_readiness_without_metadata_reports_a_blocker_instead_of_raising(run_type):
    """A caller that does not know what a run type needs still gets an answer."""
    report = protocol.adapter_for(run_type).readiness({})
    assert report['ready'] is False
    assert report['blockers'], 'a missing input must appear as a blocker'


@pytest.mark.parametrize('run_type, adapter_name', [('aa_only', 'aa'), ('aa_cg', 'cg'), ('cg_composition', 'composition')])
def test_adapter_for_returns_the_adapters_own_protocol(run_type, adapter_name):
    """The interface lives with the adapter that implements it."""
    adapter = importlib.import_module(f'dashboard.execution.adapters.{adapter_name}')
    assert protocol.adapter_for(run_type) is adapter.PROTOCOL


def test_settings_specs_share_one_shape():
    """Every adapter declares the same shape, so callers stop translating dialects."""
    for run_type in RUN_TYPES:
        specs = protocol.adapter_for(run_type).settings_specs()
        assert all(len(bounds) == 3 and isinstance(bounds[0], str) for bounds in specs.values()), run_type


def test_aa_cg_settings_have_one_owner():
    """An AA-to-CG run's settings are composed once, by the adapter that runs it."""
    adapter = protocol.adapter_for('aa_cg')
    settings = adapter.normalize_settings({'aa_nvt_ps': 20, 'aa_npt_ps': 30, 'cg_production_ps': 200}, 'standard')
    assert settings['aa_equil_ps'] == 50, 'the equilibrium duration is the AA halves added, not an input of its own'
    assert settings['aa_nvt_ps'] == 20 and settings['aa_production_ps'] > 0, 'the AA half survives the composition'
    assert settings['cg_production_ps'] == 200 and settings['cg_seed'], 'the CG half keeps its values and defaults'
    with pytest.raises(ValueError, match='Unknown run settings'):
        adapter.normalize_settings({'not_a_setting': 1}, 'standard')


def test_shared_settings_take_the_tighter_bound():
    """A key both halves bound is bounded once: AA's output_interval_ps floor, not CG's."""
    adapter = protocol.adapter_for('aa_cg')
    with pytest.raises(ValueError):
        adapter.normalize_settings({'output_interval_ps': 0.0015}, 'standard')
    assert adapter.normalize_settings({'output_interval_ps': 5}, 'standard')['output_interval_ps'] == 5
