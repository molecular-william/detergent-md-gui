"""One osmotic condition's build: what it writes, and the numbers the analysis will divide with.

The reference bead is the piece worth testing hardest, because a reference that interacts or that can move would
change the measured force without changing anything a run log says.

**The atom indices are only given where the index file is the subject.** `build` writes the index from the counts its
plan holds -- one group per molecule -- so a caller that hands it two atoms while the plan says seventy molecules is
passing inconsistent inputs, which is what the first version of these tests did. The runner writes the real index
anyway, after placement, where the counts come from the system rather than from a plan.
"""
import json

import pytest
from detergent_validation.execution.adapters import osmotic, osmotic_box

RADII = [0.264, 0.23, 0.23, 0.23, 0.23, 0.23, 0.23, 0.191]
BEADS = 8


def a_plan(molality=0.5):
    return osmotic_box.plan_condition(molality, bead_radii_nm=RADII, solute_beads_per_molecule=BEADS)


def test_the_build_writes_the_mdps_the_reference_the_index_and_the_manifest(tmp_path):
    record = osmotic.plan_and_build(tmp_path, molality=1.0, temperature=308.15, bead_radii_nm=RADII,
                                    solute_beads_per_molecule=BEADS,
                                    solute_atoms=range(1, 977), reference_atom=4001,
                                    solvent_atoms=range(977, 4001))

    for name in ('minimization.mdp', 'eq.mdp', 'md.mdp', 'reference.itp', 'index.ndx', osmotic.MANIFEST):
        assert (tmp_path / name).is_file(), name
    assert record['molality_requested'] == 1.0
    assert record['molality_achieved'] == pytest.approx(1.0, rel=0.01)
    assert record['dividing_area_nm2'] == pytest.approx(25.4173, rel=1e-4)
    assert record['temperature'] == pytest.approx(308.15)
    assert record['groups'] == {'solute': 976, 'solvent': 3024}


def test_the_manifest_carries_the_area_so_the_analysis_never_recomputes_it(tmp_path):
    """Dividing a force by an area the build never agreed to is how a series ends up internally consistent and
    wrong. The record says so in its own words, and the analysis reads it rather than deriving it."""
    record = osmotic.plan_and_build(tmp_path, molality=0.5, temperature=308.15)

    assert record['dividing_area_nm2'] == pytest.approx(5.04156 ** 2)
    assert 'must not recompute' in record['note']
    manifest = json.loads((tmp_path / osmotic.MANIFEST).read_text())
    assert manifest['dividing_area_nm2'] == record['dividing_area_nm2']
    assert manifest['box_nm'] == record['box_nm']


def test_the_reference_bead_cannot_interact(tmp_path):
    """Zero sigma and zero epsilon is no van der Waals; zero charge is no Coulomb. A reference that interacted would
    perturb the very slab it is measuring, and nothing in a run log would say so."""
    osmotic.plan_and_build(tmp_path, molality=1.0, temperature=308.15)
    itp = (tmp_path / 'reference.itp').read_text()

    # The atomtype block comes before the moleculetype that uses it: GROMACS resolves a type as it reads the
    # molecule, so the other order is "Atomtype REF not found" with the type visible in the same file.
    assert itp.index('[ atomtypes ]') < itp.index('[ moleculetype ]')
    atomtypes = [line for line in itp.splitlines() if line.startswith(osmotic.REFERENCE_TYPE + ' ')]
    assert len(atomtypes) == 1, itp
    fields = atomtypes[0].split()
    # name, mass, charge, ptype, sigma, epsilon
    assert float(fields[1]) == pytest.approx(osmotic.REFERENCE_MASS)
    assert float(fields[2]) == 0.0
    assert float(fields[4]) == 0.0 and float(fields[5]) == 0.0
    # And the atom carries no charge either.
    atom = [line for line in itp.splitlines() if line.strip().startswith('1 ') and 'REF' in line][0]
    assert float(atom.split()[6]) == 0.0


def test_the_index_names_a_group_per_molecule_a_solute_a_reference_and_the_system(tmp_path):
    """`grompp` refuses a direction geometry with one group, and the groups are read by name. The per-molecule groups
    are what the confinement coordinates address -- `MOL<i>` for the i-th molecule's own beads, in order."""
    plan = a_plan()
    molecules = plan['solute_molecules']
    solute_atoms = list(range(1, BEADS * molecules + 1))
    reference_atom = BEADS * molecules + 1
    solvent = list(range(reference_atom + 1, reference_atom + 4))

    osmotic.build(tmp_path, plan=plan, temperature=308.15, solute_atoms=solute_atoms,
                  reference_atom=reference_atom, solvent_atoms=solvent)
    index = (tmp_path / 'index.ndx').read_text()

    assert '[ SOLUTE ]' in index and '[ REFERENCE ]' in index and '[ SOLVENT ]' in index
    blocks, current = {}, None
    for line in index.splitlines():
        if line.startswith('['):
            current = line.strip('[] ')
            blocks[current] = []
        elif line.strip() and current:
            blocks[current] += line.split()
    # `System` covers every atom up to the highest index given, because that is what `tc-grps = System` must be:
    # passing `-n` replaces GROMACS's own groups, and an index without it leaves every water bead out of the
    # thermostat -- "1537 atoms are not part of any of the T-Coupling groups", at the first dynamics step.
    assert blocks['System'] == [str(n) for n in range(1, reference_atom + 4)]
    assert blocks['MOL1'] == [str(n) for n in range(1, BEADS + 1)]
    assert blocks[f'MOL{molecules}'] == [str(n) for n in range(BEADS * molecules - BEADS + 1, BEADS * molecules + 1)]
    assert blocks['SOLUTE'] == [str(n) for n in solute_atoms]
    assert blocks['REFERENCE'] == [str(reference_atom)]
    assert blocks['SOLVENT'] == [str(n) for n in solvent]


def test_solute_atoms_that_do_not_divide_into_the_molecules_are_refused():
    """A group per molecule needs each molecule's beads to be a whole number of them: a wrong split would confine
    groups that are not molecules, which is worse than refusing."""
    with pytest.raises(ValueError, match='do not divide'):
        osmotic.index_groups(solute_atoms=[1, 2, 3], reference_atom=9, solute_molecules=2)


def test_an_empty_solute_group_is_refused_before_anything_is_written():
    with pytest.raises(ValueError, match='solute group is empty'):
        osmotic.index_groups(solute_atoms=[], reference_atom=1, solute_molecules=1)


def test_a_reference_that_is_not_its_own_atom_is_refused():
    """The reference sharing an atom with the solute would make the pull coordinate zero by construction, which
    reads as a perfectly confined solute."""
    with pytest.raises(ValueError, match='also in the solute or solvent'):
        osmotic.index_groups(solute_atoms=[1, 2, 3], reference_atom=2, solute_molecules=1)
    with pytest.raises(ValueError, match='both the solute and the solvent'):
        osmotic.index_groups(solute_atoms=[1, 2], reference_atom=9, solute_molecules=1, solvent_atoms=[2, 3])


def test_a_non_positive_reference_index_is_refused():
    with pytest.raises(ValueError, match='not 1-based'):
        osmotic.index_groups(solute_atoms=[1], reference_atom=0, solute_molecules=1)


def test_the_mdps_written_are_the_ones_that_were_tested(tmp_path):
    """One source of truth: the adapter must not keep its own copy of the method."""
    from detergent_validation.execution.adapters import osmotic_mdp

    record = osmotic.plan_and_build(tmp_path, molality=1.0, temperature=308.15, production_ps=500000.0)
    expected = osmotic_mdp.osmotic_mdps(temperature=308.15, solute_molecules=record['solute_molecules'],
                                        production_ps=500000.0)

    assert (tmp_path / 'md.mdp').read_text() == expected['production']
    assert (tmp_path / 'eq.mdp').read_text() == expected['equilibration']
    assert (tmp_path / 'minimization.mdp').read_text() == expected['minimization']


def test_a_run_with_no_indices_yet_writes_no_index_file(tmp_path):
    """The runner places the molecules and *then* writes the index, because the pull's groups are atom indices -- and
    `build` can only write one from counts it was told, which an unplaced run does not have."""
    plan = a_plan()
    placed = osmotic.build(tmp_path, plan=plan, temperature=308.15,
                           solute_atoms=list(range(1, BEADS * plan['solute_molecules'] + 1)),
                           reference_atom=BEADS * plan['solute_molecules'] + 1)
    assert (tmp_path / 'index.ndx').is_file()
    assert placed['restraint']['reference_atom'] == BEADS * plan['solute_molecules'] + 1

    elsewhere = tmp_path / 'unplaced'
    unplaced = osmotic.build(elsewhere, plan=plan, temperature=308.15)
    assert not (elsewhere / 'index.ndx').exists()
    assert (elsewhere / 'md.mdp').is_file()
    assert unplaced['restraint']['reference_atom'] is None


def test_the_record_and_the_plan_agree_about_the_counts(tmp_path):
    """A build that wrote one set of counts and recorded another would be undetectable downstream."""
    plan = a_plan(2.0)
    record = osmotic.build(tmp_path, plan=plan, temperature=308.15)

    for key in ('water_beads', 'solute_molecules', 'dividing_area_nm2', 'box_volume_nm3'):
        assert record[key] == plan[key], key
    assert record['confinement_nm'] == pytest.approx(osmotic_box.CONFINEMENT_NM)
    assert record['restraint']['reference_type'] == osmotic.REFERENCE_TYPE
    # The mechanism the record names is the one the mdp and the runner actually use. This assertion is why the
    # record's own account of *how* the solute is confined is not allowed to drift.
    assert record['restraint']['mechanism'].startswith('plumed, flat-bottom')
