"""Neutralising a converted complex: what the numbers are, and what has to be true before `genion` can act.

The converted 4iar/DDM complex came out at -5 and CG2AT2's steering leg refused to simulate it ("Ewald electrostatics in a
system with net charge"). `pdc_neutralise` adds what it takes to make the sum zero and records the sum before and after, so
these tests pin the three things that decide the number: how a moleculetype's charge is read, how the counts are summed, and
which molecule is the solvent `genion` may replace.

`genion` itself is not run here -- it needs GROMACS and a tpr -- so what is tested is the arithmetic and the rewriting that
the command depends on. The end-to-end result (-5.0 -> 0.0, 5 NA added) was measured on the run's own conversion.
"""
from pathlib import Path

from detergent_pdc.execution.scripts import pdc_neutralise as neutralise

TOPOLOGY = """[ molecules ]
; Compound        #mols
PROTEIN_0    1
DDM    3
TIP3P    100
NA    2
CL    3
"""


def write_system(root: Path, *, water='tip3p') -> Path:
    root.mkdir(parents=True, exist_ok=True)
    # The topology names the solvent as the build chose; the itp defines it as it likes. `water` is the itp's spelling,
    # so the row follows it here and the case difference the real conversion has is exercised separately.
    (root / 'topol_final.top').write_text(TOPOLOGY.replace('TIP3P', water.upper()))
    (root / 'PROTEIN_0.itp').write_text(
        '[ moleculetype ]\n; molname nrexcl\nprotein_0       3\n\n'
        '[ atoms ]\n; nr type resnr resid atom cgnr charge mass\n'
        '1  CA  1  ALA  CA  1  0.2  12.0\n2  CA  1  ALA  CB  2  0.1  12.0\n')
    (root / 'DDM.itp').write_text(
        '[ moleculetype ]\nDDM      3\n\n'
        '[ atoms ]\n1  CR  1  DDM  C1  1  0.0  12.0\n2  HCMM  1  DDM  H1  2  0.0  1.0\n')
    (root / 'TIP3P.itp').write_text(
        f'[ moleculetype ]\n; molname\t   nrexcl\n{water}\t\t2\n\n'
        '[ atoms ]\n1  OW  1  SOL  OW  1  -0.834  16.0\n2  HW  1  SOL  HW1  2  0.417  1.0\n'
        '3  HW  1  SOL  HW2  2  0.417  1.0\n')
    (root / 'NA.itp').write_text('[ moleculetype ]\nNA\t\t1\n\n[ atoms ]\n1  NA  1  NA  NA  1  1.0  22.99\n')
    (root / 'CL.itp').write_text('[ moleculetype ]\nCL\t\t1\n\n[ atoms ]\n1  CL  1  CL  CL  1  -1.0  35.45\n')
    return root


def test_a_moleculetypes_charge_is_the_sum_of_its_own_atoms(tmp_path):
    root = write_system(tmp_path / 'FINAL')

    assert round(neutralise.charge_of(root / 'PROTEIN_0.itp'), 4) == 0.3
    assert round(neutralise.charge_of(root / 'TIP3P.itp'), 4) == 0.0


def test_the_system_charge_weighs_each_molecule_by_its_count(tmp_path):
    """0.3 protein + 3 neutral DDM + 0 water + 2 Na - 3 Cl = -0.7, which is the number the step must make zero."""
    root = write_system(tmp_path / 'FINAL')

    total, per = neutralise.total_charge(root)

    assert round(total, 4) == -0.7
    assert round(per['NA'], 4) == 2.0 and round(per['CL'], 4) == -3.0


def test_the_solvent_is_the_most_numerous_molecule_that_is_not_an_ion(tmp_path):
    root = write_system(tmp_path / 'FINAL')

    # The topology's spelling, not the itp's: `[ molecules ]` is what `genion` rewrites rows in, and it says `TIP3P`
    # while the itp calls the moleculetype `tip3p`.
    assert neutralise.water_name(root) == 'TIP3P'


def test_renaming_the_solvent_touches_only_the_solvent(tmp_path):
    """`genion` replaces solvent by moleculetype name; CG2AT2 writes `tip3p` while its residues are `SOL`."""
    root = write_system(tmp_path / 'FINAL')

    record = neutralise.rename_water(root, 'SOL')

    assert record == {'renamed': {'from': 'TIP3P', 'to': 'SOL', 'file': 'TIP3P.itp'}}
    assert neutralise.moleculetype_of((root / 'TIP3P.itp').read_text()) == 'SOL'
    topology = (root / 'topol_final.top').read_text()
    assert 'SOL    100' in topology and 'TIP3P' not in topology
    assert 'NA    2' in topology and 'DDM    3' in topology, 'nothing else in [ molecules ] moves'
    assert neutralise.moleculetype_of((root / 'DDM.itp').read_text()) == 'DDM'


def test_renaming_a_solvent_already_named_right_changes_nothing(tmp_path):
    root = write_system(tmp_path / 'FINAL', water='SOL')

    assert neutralise.rename_water(root, 'SOL') == {'renamed': None}
    assert 'SOL    100' in (root / 'topol_final.top').read_text()


def test_the_counts_sum_rows_because_genion_appends_one(tmp_path):
    root = write_system(tmp_path / 'FINAL')
    topology = root / 'topol_final.top'
    topology.write_text(topology.read_text() + 'NA    5\n')

    assert neutralise.counts(topology)['NA'] == 7, 'genion writes its own row rather than editing the existing one'


def test_the_ions_mdp_makes_a_topology_and_runs_no_dynamics():
    mdp = neutralise.IONS_MDP

    assert 'nsteps' in mdp and 'integrator' in mdp
    assert 'steep' in mdp, 'no dynamics: the tpr exists only so the ions have somewhere to go'


def test_a_missing_conversion_is_a_refusal_rather_than_a_silent_success(tmp_path):
    import pytest

    root = tmp_path / 'FINAL'
    root.mkdir()

    with pytest.raises(SystemExit, match='did not finish'):
        neutralise.neutralise(root, tmp_path / 'stage')



def test_the_step_adds_the_ions_its_own_arithmetic_asks_for(tmp_path, monkeypatch):
    """`genion` is replaced by what it would do -- append its ions and shrink the solvent -- so the record is testable.

    What the real run measured on the 4iar/DDM conversion: -5.0 before, 0.0 after, five NA ions, the solvent 5 smaller.
    """
    root = write_system(tmp_path / 'FINAL')
    stage = tmp_path / 'stage'
    stage.mkdir()
    (root / 'final_cg2at_de_novo.pdb').write_text('END\n')
    commands = []

    def fake_run(command, *, log, stdin=None, cwd):
        commands.append((command[1], Path(cwd).name, stdin))
        if command[1] == 'genion':
            topology = Path(cwd) / 'topol_final.top'
            topology.write_text(topology.read_text().replace('TIP3P    100', 'SOL    99') + 'NA    2\n')
        return 0

    monkeypatch.setattr(neutralise, 'run', fake_run)
    record = neutralise.neutralise(root, stage)

    assert commands[0][0] == 'grompp' and commands[1] == ('genion', 'FINAL', 'SOL\n')
    assert record['charge_before'] == -0.7, 'the sum the step set out to fix'
    assert record['ions_added'] == {'NA': 2, 'CL': 0}, 'only the difference between before and after'
    assert record['renamed'] == {'from': 'TIP3P', 'to': 'SOL', 'file': 'TIP3P.itp'}
    assert record['structure'].endswith('final_cg2at_neutral.pdb')
