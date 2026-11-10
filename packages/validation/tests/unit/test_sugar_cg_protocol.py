"""The sugar run type's protocol and payload contract: reachable, advertised, and refused where it should be."""
import pytest
from dashboard import features
from dashboard.execution import protocol
from dashboard.execution.coordination import admission
from detergent_validation.execution.adapters import sugar_cg


def test_the_reference_kind_is_reachable_through_the_cg_run_type():
    from dashboard.execution.adapters import cg_run

    features.ensure()

    assert 'cg' in protocol.RUN_TYPES and 'sugar_cg' not in protocol.RUN_TYPES
    assert protocol.adapter_for('cg') is cg_run.PROTOCOL
    reference = {'run_type': 'cg', 'molecule_id': 'Sucrose',
                 'parameterization': {'kind': 'reference', 'sugar_entry': 'SUCR'}}
    contract, _, _ = protocol.adapter_for('cg').stage_contract(reference)
    assert [name for name, _ in contract] == ['CG simulation']


def test_admission_accepts_one_sugar_and_one_published_entry():
    admission.validate_run_type({'run_type': 'cg', 'molecule_id': 'Sucrose',
                                 'parameterization': {'kind': 'reference', 'sugar_entry': 'SUCR'}})
    admission.validate_run_type({'run_type': 'cg', 'molecule_id': 'Trehalose',
                                 'parameterization': {'kind': 'reference', 'sugar_entry': 'TREH'}})


def test_admission_refuses_an_aa_input_or_a_missing_entry():
    with pytest.raises(ValueError, match='requires parameterization.sugar_entry'):
        admission.validate_run_type({'run_type': 'cg', 'molecule_id': 'Sucrose',
                                     'parameterization': {'kind': 'reference'}})
    with pytest.raises(ValueError, match='require parameterization'):
        admission.validate_run_type({'run_type': 'cg', 'molecule_id': 'Sucrose'})
    for key, value in (('reference_run_id', 'abc123'), ('mapping_candidate', 'saved.json'),
                       ('mapping_snapshot', {'beads': []})):
        with pytest.raises(ValueError, match=f'cannot include {key}'):
            admission.validate_run_type({'run_type': 'cg', 'molecule_id': 'Sucrose',
                                         'parameterization': {'kind': 'reference', 'sugar_entry': 'SUCR'},
                                         key: value})


def test_the_protocol_advertises_only_the_settings_it_reads():
    advertised = set(sugar_cg.PROTOCOL.settings_specs()) | set(sugar_cg.PROTOCOL.choice_specs())

    assert {'sugar_entry', 'cg_equil_ps', 'cg_production_ps', 'temperature_k', 'cg_seed',
            'output_interval_ps', 'mdrun_ntomp', 'mdrun_ranks', 'mdrun_cpt',
            'mdrun_nb', 'mdrun_pme'} <= advertised
    # The AA durations, pressure and box shape are deliberately not advertised: the reviewed CG profiles fix them
    # and a form field this run ignores would be a control that does nothing.
    assert not {'aa_nvt_ps', 'aa_npt_ps', 'aa_production_ps', 'pressure_bar', 'box_shape'} & advertised


def test_normalize_settings_is_the_protocol_s_own():
    values = sugar_cg.PROTOCOL.normalize_settings({'sugar_entry': 'SUCR'}, 'sugar-cg-v1')

    assert values['sugar_entry'] == 'SUCR'
    assert values['cg_production_ps'] == pytest.approx(10000.0)


def test_the_reference_kind_keeps_its_own_durations():
    from dashboard.execution.adapters import cg_run

    values = cg_run.normalize_settings({'sugar_entry': 'SUCR'}, 'draft-smoke-reference',
                                       parameterization={'kind': 'reference', 'sugar_entry': 'SUCR'})
    assert values['sugar_entry'] == 'SUCR'
    assert values['cg_production_ps'] == pytest.approx(10000.0)
    # The revision kind is still the default, and the run type keeps the CG profile its runs record.
    assert protocol.profile_for_run_type('cg') == 'draft-smoke-reference'
