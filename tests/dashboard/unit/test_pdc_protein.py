"""The CG protein step: the elastic network is the one the protocol asked for, not a default.

The distinction that matters is `-eu` against `-el`: the tool's own help says `-el` is the lower bound, below which
the force is constant, and `-eu` is the upper cutoff beyond which it is zero. "Within 10 A" is the upper cutoff, and
getting it wrong would have produced a network that looked plausible and restrained the wrong pairs.
"""
import pytest

from dashboard.execution.adapters import pdc_protein


def test_the_elastic_network_is_the_requested_one(tmp_path):
    (tmp_path / 'protein.pdb').write_text('ATOM\n')
    command = pdc_protein.martinize_command(tmp_path / 'protein.pdb', tmp_path)

    assert command[0] == 'martinize2'
    assert '-elastic' in command
    assert command[command.index('-ef') + 1] == '1000'     # kJ/mol/nm^2, the force constant asked for
    assert command[command.index('-eu') + 1] == '1.0'      # 10 A, in the nanometres the tool documents
    assert '-el' not in command, 'the lower bound is not the cutoff the request names'


def test_the_command_names_its_inputs_and_outputs(tmp_path):
    (tmp_path / 'protein.pdb').write_text('ATOM\n')
    command = pdc_protein.martinize_command(tmp_path / 'protein.pdb', tmp_path, force_field='martini3001')

    assert command[command.index('-f') + 1].endswith('protein.pdb')
    assert command[command.index('-ff') + 1] == 'martini3001'
    assert command[command.index('-x') + 1].endswith('protein_cg.pdb')
    assert command[command.index('-o') + 1].endswith('protein.top')


def test_a_missing_structure_is_an_error_rather_than_a_command(tmp_path):
    """A command built against a file that is not there fails inside a stage, where it costs a run."""
    with pytest.raises(ValueError, match='not found'):
        pdc_protein.martinize_command(tmp_path / 'absent.pdb', tmp_path)
