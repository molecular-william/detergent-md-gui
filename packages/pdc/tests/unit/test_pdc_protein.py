"""The CG protein step: the elastic network is the one the protocol asked for, not a default.

The distinction that matters is `-eu` against `-el`: the tool's own help says `-el` is the lower bound, below which
the force is constant, and `-eu` is the upper cutoff beyond which it is zero. "Within 10 A" is the upper cutoff, and
getting it wrong would have produced a network that looked plausible and restrained the wrong pairs.
"""
import pytest
from detergent_pdc.execution.adapters import pdc_protein


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



def test_the_position_restraint_flag_is_asked_for_on_every_build(tmp_path):
    """The tool's `-p backbone` writes the POSRES block; the slack of the window is the mdp's, not the command's."""
    (tmp_path / 'protein.pdb').write_text('ATOM')
    command = pdc_protein.martinize_command(tmp_path / 'protein.pdb', tmp_path)

    assert command[command.index('-p') + 1] == 'backbone'
    assert '-pf' not in command, 'the tool default force constant is the one the block uses'


def test_the_restraint_file_lands_in_the_recorded_stage_inputs(tmp_path):
    """(d) A stub martinize2 writes the file its own flag names, and the legs' declared tree records it.

    This vermouth (0.15.0) writes the `#ifdef POSRES` block inside `molecule_N.itp` rather than a separate
    `posre.itp`; the recording claim is the same for either shape because every leg declares the whole `cg/` tree
    as an input, so whatever the tool writes beside the topology is inside it.
    """
    import subprocess
    import sys

    from dashboard.execution import workflow

    out = tmp_path / 'cg'
    out.mkdir()
    stub = tmp_path / 'martinize2'
    stub.write_text(f'#!{sys.executable}\nimport pathlib\npathlib.Path("posre.itp").write_text("[ position_restraints ]\\n")\n')
    stub.chmod(0o755)
    (tmp_path / 'protein.pdb').write_text('ATOM\n')
    command = pdc_protein.martinize_command(tmp_path / 'protein.pdb', out, executable=str(stub))
    assert command[command.index('-p') + 1] == 'backbone'
    subprocess.run(command, check=True, cwd=out)

    assert (out / 'posre.itp').is_file(), 'the stub wrote the file the flag names'
    # The executor reads each leg's declared inputs through this function and hashes every file it yields, so the
    # file the build wrote is on the record beside the topology it was written with.
    stages = tmp_path / 'run' / 'stages'
    leg = stages / '03_minimisation'
    leg.mkdir(parents=True)
    probe = stages / '02_system' / 'cg'
    probe.mkdir(parents=True)
    (probe / 'posre.itp').write_text('[ position_restraints ]\n')
    from detergent_pdc.execution.adapters import pdc

    declared = pdc.stage_by_name('Energy minimisation').inputs
    assert f'../02_system/{pdc.PROTEIN_TOPOLOGY_DIRECTORY}/' in declared
    recorded = {path.resolve() for path in workflow._declared_paths(leg, '../02_system/cg/')}
    assert (probe / 'posre.itp').resolve() in recorded, 'the restraint file is inside the recorded cg/ tree'
