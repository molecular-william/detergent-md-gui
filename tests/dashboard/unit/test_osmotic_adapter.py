"""One osmotic condition's build: what it writes, and the numbers the analysis will divide with.

The reference bead is the piece worth testing hardest, because a reference that interacts or that can move would
change the measured force without changing anything a run log says.
"""
import json

import pytest

from dashboard.execution.adapters import osmotic

RADII = [0.264, 0.23, 0.23, 0.23, 0.23, 0.23, 0.23, 0.191]


def test_the_build_writes_the_mdps_the_reference_the_index_and_the_manifest(tmp_path):
    record = osmotic.plan_and_build(tmp_path, molality=1.0, temperature=308.15, bead_radii_nm=RADII,
                                    solute_beads_per_molecule=8,
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
    record = osmotic.plan_and_build(tmp_path, molality=0.5, temperature=308.15, solute_atoms=[1, 2],
                                    reference_atom=9)

    assert record['dividing_area_nm2'] == pytest.approx(5.04156 ** 2)
    assert 'must not recompute' in record['note']
    manifest = json.loads((tmp_path / osmotic.MANIFEST).read_text())
    assert manifest['dividing_area_nm2'] == record['dividing_area_nm2']
    assert manifest['box_nm'] == record['box_nm']


def test_the_reference_bead_cannot_interact(tmp_path):
    """Zero sigma and zero epsilon is no van der Waals; zero charge is no Coulomb. A reference that interacted would
    perturb the very slab it is measuring, and nothing in a run log would say so."""
    osmotic.plan_and_build(tmp_path, molality=1.0, temperature=308.15, solute_atoms=[1], reference_atom=2)
    itp = (tmp_path / 'reference.itp').read_text()

    assert 'REF' in itp
    # The atomtype line, not the moleculetype line that also begins with these letters.
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


def test_the_index_file_names_both_pull_groups_in_order(tmp_path):
    """`grompp` refuses a direction geometry with one group, and the groups are read by name."""
    osmotic.plan_and_build(tmp_path, molality=1.0, temperature=308.15, solute_atoms=[5, 6, 7],
                           reference_atom=42, solvent_atoms=[8, 9])
    index = (tmp_path / 'index.ndx').read_text()

    assert '[ SOLUTE ]' in index and '[ REFERENCE ]' in index and '[ SOLVENT ]' in index
    blocks = {name: [] for name in ('System', 'SOLUTE', 'REFERENCE', 'SOLVENT')}
    current = None
    for line in index.splitlines():
        if line.startswith('['):
            current = line.strip('[] ')
        elif line.strip() and current:
            blocks[current] += line.split()
    # `System` covers every atom up to the highest index given, because that is what `tc-grps = System` must be:
    # passing `-n` replaces GROMACS's own groups, and an index without it leaves every water bead out of the
    # thermostat -- "1537 atoms are not part of any of the T-Coupling groups", at the first dynamics step.
    assert blocks['System'] == [str(n) for n in range(1, 43)]
    assert blocks['SOLUTE'] == ['5', '6', '7']
    assert blocks['REFERENCE'] == ['42']
    assert blocks['SOLVENT'] == ['8', '9']


def test_an_empty_solute_group_is_refused_before_anything_is_written():
    with pytest.raises(ValueError, match='solute group is empty'):
        osmotic.index_groups(solute_atoms=[], reference_atom=1)


def test_a_reference_that_is_not_its_own_atom_is_refused():
    """The reference sharing an atom with the solute would make the pull coordinate zero by construction, which
    reads as a perfectly confined solute."""
    with pytest.raises(ValueError, match='also in the solute or solvent'):
        osmotic.index_groups(solute_atoms=[1, 2, 3], reference_atom=2)
    with pytest.raises(ValueError, match='both the solute and the solvent'):
        osmotic.index_groups(solute_atoms=[1, 2], reference_atom=9, solvent_atoms=[2, 3])


def test_a_non_positive_reference_index_is_refused():
    with pytest.raises(ValueError, match='not 1-based'):
        osmotic.index_groups(solute_atoms=[1], reference_atom=0)


def test_the_mdps_written_are_the_ones_that_were_tested(tmp_path):
    """One source of truth: the adapter must not keep its own copy of the method."""
    from dashboard.execution.adapters import osmotic_mdp

    osmotic.plan_and_build(tmp_path, molality=1.0, temperature=308.15, solute_atoms=[1], reference_atom=2,
                           production_ps=500000.0)
    expected = osmotic_mdp.osmotic_mdps(temperature=308.15, production_ps=500000.0)

    assert (tmp_path / 'md.mdp').read_text() == expected['production']
    assert (tmp_path / 'eq.mdp').read_text() == expected['equilibration']
    assert (tmp_path / 'minimization.mdp').read_text() == expected['minimization']


def test_a_run_with_no_indices_yet_writes_no_index_file(tmp_path):
    """The runner places the molecules and *then* writes the index, because the pull's groups are atom indices. A
    placeholder with invented indices would be read by grompp and would confine and measure the wrong atoms."""
    placed = osmotic.plan_and_build(tmp_path, molality=1.0, temperature=308.15, solute_atoms=[1], reference_atom=2)
    assert (tmp_path / 'index.ndx').is_file()
    assert placed['restraint']['reference_atom'] == 2

    elsewhere = tmp_path / 'unplaced'
    unplaced = osmotic.plan_and_build(elsewhere, molality=1.0, temperature=308.15)
    assert not (elsewhere / 'index.ndx').exists()
    assert (elsewhere / 'md.mdp').is_file()
    assert unplaced['restraint']['reference_atom'] is None


def test_the_record_and_the_plan_agree_about_the_counts(tmp_path):
    """A build that wrote one set of counts and recorded another would be undetectable downstream."""
    from dashboard.execution.adapters import osmotic_box

    plan = osmotic_box.plan_condition(2.0, bead_radii_nm=RADII, solute_beads_per_molecule=8)
    record = osmotic.build(tmp_path, plan=plan, temperature=308.15, solute_atoms=[1], reference_atom=2)

    for key in ('water_beads', 'solute_molecules', 'dividing_area_nm2', 'box_volume_nm3'):
        assert record[key] == plan[key], key
    assert record['confinement_nm'] == pytest.approx(osmotic_box.CONFINEMENT_NM)
    assert record['restraint']['reference_type'] == osmotic.REFERENCE_TYPE
    assert record['restraint']['mechanism'].startswith('pull, flat-bottom')
