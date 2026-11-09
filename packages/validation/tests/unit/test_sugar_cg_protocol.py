"""The sugar run type's protocol and payload contract: reachable, advertised, and refused where it should be."""
import pytest
from dashboard import features
from dashboard.execution import protocol
from dashboard.execution.coordination import admission
from detergent_validation.execution.adapters import sugar_cg


def test_the_feature_registers_the_run_type():
    features.ensure()

    assert 'sugar_cg' in protocol.RUN_TYPES
    assert protocol.adapter_for('sugar_cg') is sugar_cg.PROTOCOL


def test_admission_accepts_one_sugar_and_one_published_entry():
    admission.validate_run_type({'run_type': 'sugar_cg', 'molecule_id': 'Sucrose', 'sugar_entry': 'SUCR'})
    admission.validate_run_type({'run_type': 'sugar_cg', 'molecule_id': 'Trehalose', 'sugar_entry': 'TREH'})


def test_admission_refuses_an_aa_input_or_a_missing_entry():
    with pytest.raises(ValueError, match='require sugar_entry'):
        admission.validate_run_type({'run_type': 'sugar_cg', 'molecule_id': 'Sucrose'})
    with pytest.raises(ValueError, match='require molecule_id'):
        admission.validate_run_type({'run_type': 'sugar_cg', 'sugar_entry': 'SUCR'})
    for key, value in (('method', 'fast_forward'), ('reference_run_id', 'abc123'),
                       ('mapping_candidate', 'saved.json'), ('mapping_snapshot', {'beads': []}),
                       ('aa_production_ps', 100), ('sasa_probe_nm', 0.191)):
        with pytest.raises(ValueError, match=f'cannot include {key}'):
            admission.validate_run_type({'run_type': 'sugar_cg', 'molecule_id': 'Sucrose',
                                         'sugar_entry': 'SUCR', key: value})


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


def test_the_profile_is_the_run_type_s_own():
    assert protocol.profile_for_run_type('sugar_cg') == 'sugar-cg-v1'
