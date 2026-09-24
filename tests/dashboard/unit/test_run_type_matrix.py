"""One owner for the run-type matrix: the rules, the stages, the readiness check.

What a run type may carry, which stages it runs, and whether it is ready are each
decided in one place. These tests pin the ownership rather than the rules: the
coordinator must not keep a private copy of the admission checks, stage dispatch
must go through the protocol, and the worker must not re-implement readiness.
"""
import inspect

from dashboard.execution import workflow
from dashboard.execution.coordination import coordinator


def test_create_job_defers_run_type_checks_to_admission():
    """The payload rules live in admission.py, which the queue routes also use."""
    source = inspect.getsource(coordinator.Coordinator.create_job)
    assert 'AA-only cannot use CG inputs' not in source
    assert 'CG composition runs require composition_id' not in source
    assert 'admission.validate_run_type' in source


def test_stage_dispatch_has_one_owner():
    """Stage tables come from the adapter for the run type, not from a local branch."""
    source = inspect.getsource(workflow.stage_definitions) + inspect.getsource(workflow.plan_for)
    assert 'adapter_for' in source
    assert "'aa_only'" not in source and "'cg_composition'" not in source
    assert 'from .adapters import' not in source


def test_worker_readiness_comes_from_the_adapter():
    """The worker asks the adapter for readiness instead of dispatching again."""
    source = inspect.getsource(coordinator.Coordinator.run_job)
    assert 'composition_readiness' not in source
    assert 'aa.readiness(' not in source and 'cg.readiness(' not in source
    assert 'adapter_for' in source
