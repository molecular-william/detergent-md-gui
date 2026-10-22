"""One owner for the run-type matrix: the rules, the stages, the readiness check.

What a run type may carry, which stages it runs, and whether it is ready are each
decided in one place. These tests pin the ownership rather than the rules: the
coordinator must not keep a private copy of the admission checks, stage dispatch
must go through the protocol, and the worker must not re-implement readiness.
"""
import inspect

import pytest

from dashboard.execution import workflow
from dashboard.execution.coordination import admission, coordinator


def test_create_job_defers_run_type_checks_to_admission():
    """The payload rules live in admission.py, which the queue routes also use."""
    source = inspect.getsource(coordinator.Coordinator.create_job)
    assert 'AA-only cannot use CG inputs' not in source
    assert 'CG composition runs require composition_id' not in source
    # The method allow-list sat here and applied to every run type, so a protein-detergent build -- which takes its
    # topology from a mapping and has no parameterizer to name -- was refused with "Unsupported method" while its own
    # adapter was ready. The rule belongs with the rest of the payload rules, where it can ask which types have a
    # choice at all.
    assert 'Unsupported method' not in source
    assert 'ALLOWED_METHODS' not in source
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


def test_the_run_contract_carries_no_bonded_intent_or_state():
    """D1: fitting is the run type's own, so nothing queues a run to fit differently.

    The two controls the panel used to offer -- a bonded state to reuse, a bonded workflow to follow -- are gone
    from the queue and from the worker: `create_job` accepts neither, `run_job` neither hands them to the run
    type's preparation nor records a state after the fit, and nothing stops a run after stage 3. `models/bonded`
    keeps the states themselves; this is about what a run may be told, not about the workspace that fits them.
    """
    parameters = inspect.signature(coordinator.Coordinator.create_job).parameters
    for retired in ('bonded_state_id', 'bonded_intent'):
        assert retired not in parameters, 'the run type fits its own parameters; no caller picks them (D1)'
    source = inspect.getsource(coordinator.Coordinator.run_job)
    assert 'bonded_state' not in source and 'bonded_intent' not in source
    assert 'stop_after' not in source, 'an AA-to-CG run no longer stops itself after stage 3'


def test_only_a_run_that_names_a_parameterizer_is_asked_for_one():
    """A run type whose topology comes from a mapping has no method to choose.

    `aa_cg` (and a payload that states no run type, which is one) must name the parameterizer that maps its atoms; a
    protein-detergent build, a composition and an osmotic series do not, because each takes its topology from a mapping
    and its stages from its own adapter. The allow-list used to apply to all of them, which is why queueing a pdc run
    answered 400 "Unsupported method" from a form that had no method field to fill.
    """
    admission.validate_run_type({'run_type': 'pdc', 'molecule_id': 'DDM'})
    admission.validate_run_type({'run_type': 'cg_composition', 'composition_id': 'composition_ddm_belt'})
    with pytest.raises(ValueError, match='Unsupported method'):
        admission.validate_run_type({'run_type': 'aa_cg'})
    with pytest.raises(ValueError, match='Unsupported method'):
        admission.validate_run_type({})
    with pytest.raises(ValueError, match='Unsupported method'):
        admission.validate_run_type({'run_type': 'aa_cg', 'method': 'gromacs'})
    admission.validate_run_type({'run_type': 'aa_cg', 'method': 'fast_forward'})
    admission.validate_run_type({'run_type': 'aa_cg', 'method': 'bartender'})
