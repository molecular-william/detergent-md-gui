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
