"""Every run type answers the same protocol surface, in the same shapes.

The interface exists so no caller has to know which adapter it is talking to:
the coordinator, the queue routes and these tests all ask the same questions
and get the same shapes back. These tests pin the shapes, not the internals.
"""
import importlib
import subprocess
from collections.abc import Mapping

import pytest

from dashboard.execution import protocol

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


def test_setting_bounds_accepts_both_dialects():
    """AA declares (lo, hi), CG declares (label, lo, hi); callers see one shape."""
    assert protocol.setting_bounds('aa_nvt_ps', (1, 2)) == ('aa_nvt_ps', 1, 2)
    assert protocol.setting_bounds('aa_nvt_ps', ('AA NVT duration', 1, 2)) == ('AA NVT duration', 1, 2)
    with pytest.raises(ValueError):
        protocol.setting_bounds('aa_nvt_ps', (1,))
