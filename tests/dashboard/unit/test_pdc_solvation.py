"""Solvent and ions by construction: the options decide the composition, so they are asserted as options.

The count of water and ions a run records comes from these commands and nothing else, which is why the interesting
assertions are about `-radius`, `-neutral` and `-conc` rather than about a file that would need GROMACS to produce.
"""
import pytest

from dashboard.execution.adapters import pdc_solvation


def test_the_commands_solvate_then_neutralise_then_add_salt():
    solvate, grompp, genion = pdc_solvation.solvation_commands('system.top', 'system.gro', 'ions.tpr')

    assert solvate[:2] == ['gmx', 'solvate'] and '-radius' in solvate
    assert solvate[solvate.index('-radius') + 1] == '0.21', 'Martini water is placed at a bead radius'
    assert genion[:2] == ['gmx', 'genion']
    assert '-neutral' in genion, 'neutralisation must happen before the concentration is applied'
    assert genion[genion.index('-conc') + 1] == '0.15', 'the concentration is molar, as genion defines it'
    assert genion[genion.index('-pname') + 1] == 'NA' and genion[genion.index('-nname') + 1] == 'CL'
    assert grompp[:2] == ['gmx', 'grompp'] and 'ions.tpr' in grompp


def test_the_ion_group_is_piped_because_genion_asks_for_it():
    """An unanswered prompt is a hung stage rather than a failed one, so the stdin is part of the contract."""
    assert pdc_solvation.ion_group_selection() == 'W\n'


def test_a_negative_concentration_is_refused_rather_than_subtracted():
    with pytest.raises(ValueError, match='cannot be negative'):
        pdc_solvation.solvation_commands('system.top', 'system.gro', 'ions.tpr', salt_molar=-0.1)
    with pytest.raises(ValueError, match='radius must be positive'):
        pdc_solvation.solvation_commands('system.top', 'system.gro', 'ions.tpr', radius_nm=0)


def test_the_agreed_default_is_the_concentration_the_protocol_asks_for():
    _, _, genion = pdc_solvation.solvation_commands('system.top', 'system.gro', 'ions.tpr')
    assert genion[genion.index('-conc') + 1] == '0.15'   # 0.15 M NaCl, the protocol's number
