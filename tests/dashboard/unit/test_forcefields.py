"""The force-field registry: what each entry claims, checked against the trees that are actually on disk.

A registry that drifts from the files it names would be worse than the hard-coded strings it replaces, so these
tests read the vendored trees rather than trusting the entry: the water moleculetype, the ion names and the
existence of every file an entry promises are all asserted against the filesystem.
"""
from pathlib import Path

import pytest
from dashboard.execution import forcefields


def moleculetypes(path):
    """Every moleculetype name in a GROMACS include, in file order."""
    out, want = [], False
    for line in Path(path).read_text(errors='ignore').splitlines():
        stripped = line.strip()
        if stripped.startswith('[') and 'moleculetype' in stripped:
            want = True
            continue
        if want:
            if stripped.startswith(';') or not stripped:
                continue
            out.append(stripped.split()[0])
            want = False
    return out


def test_the_default_is_an_entry_and_is_the_newer_port():
    assert forcefields.DEFAULT in forcefields.ENTRIES
    assert forcefields.entry() is forcefields.ENTRIES[forcefields.DEFAULT]
    assert forcefields.entry().directory == 'charmm36-feb2026_cgenff-4.6.ff'


def test_naming_no_force_field_and_naming_the_default_agree():
    assert forcefields.entry(None) == forcefields.entry(forcefields.DEFAULT)


def test_an_unknown_force_field_is_an_error_rather_than_a_fallback():
    with pytest.raises(ValueError, match='unknown force field'):
        forcefields.entry('gromos54a7')


@pytest.mark.parametrize('name', forcefields.names())
def test_every_entry_names_files_that_exist(name):
    ff = forcefields.entry(name)
    tree = ff.tree()
    assert (tree / 'forcefield.itp').is_file(), f'{name}: no forcefield.itp in {tree}'
    assert (tree / ff.water_file).is_file(), f'{name}: no {ff.water_file}'
    assert (tree / 'ions.itp').is_file(), f'{name}: no ions.itp'
    assert tree.name == ff.directory


@pytest.mark.parametrize('name', forcefields.names())
def test_the_water_and_ion_names_are_the_ones_the_trees_provide(name):
    """The promise that matters: a topology is written with these names, so they must resolve."""
    ff = forcefields.entry(name)
    assert ff.water_molecule in moleculetypes(ff.tree() / ff.water_file)
    ions = moleculetypes(ff.tree() / 'ions.itp')
    assert ff.cation in ions, f'{name}: {ff.cation} is not an ion moleculetype'
    assert ff.anion in ions, f'{name}: {ff.anion} is not an ion moleculetype'


@pytest.mark.parametrize('name', forcefields.names())
def test_the_mdp_carries_the_manuals_block_and_the_papers_constraint_choice(name):
    ff = forcefields.entry(name)
    assert ff.mdp == forcefields.MANUAL_CHARMM36
    assert ff.mdp == {'cutoff-scheme': 'Verlet', 'vdwtype': 'Cut-off', 'vdw-modifier': 'Force-switch',
                      'rlist': 1.2, 'rvdw': 1.2, 'rvdw-switch': 1.0, 'coulombtype': 'PME', 'rcoulomb': 1.2,
                      'DispCorr': 'no'}
    # The paper restrains all bonds; the manual's h-bonds is recorded beside it rather than lost.
    assert ff.constraints == 'all-bonds'
    assert ff.manual_constraints == 'h-bonds'
    assert 'constraints' not in ff.mdp


@pytest.mark.parametrize('name', forcefields.names())
def test_the_temperature_is_the_one_the_parameterisation_assumes(name):
    assert forcefields.entry(name).temperature_k == 303.15


def test_every_entry_carries_a_label_a_temperature_and_a_water_model():
    """The panel renders these, so an entry without them would appear as a nameless or nonsensical option."""
    for name in forcefields.names():
        ff = forcefields.entry(name)
        assert ff.label.strip(), f'{name} has no label for the panel to show'
        assert isinstance(ff.temperature_k, float)
        assert ff.water_file.endswith('.itp')


def test_the_defaults_endpoint_offers_what_the_registry_holds():
    """The panel's options come from the endpoint, so the endpoint must agree with the registry exactly."""
    from dashboard.web.routes.molecules import _with_force_fields
    offered = _with_force_fields({})['force_fields']
    assert [entry['name'] for entry in offered] == list(forcefields.names())
    for entry in offered:
        registered = forcefields.entry(entry['name'])
        assert entry['label'] == registered.label
        assert entry['temperature_k'] == registered.temperature_k
        assert entry['water'] == registered.water_file[: -len('.itp')]


def test_the_newer_port_records_where_it_came_from():
    ff = forcefields.entry('charmm36-feb2026_cgenff-4.6')
    assert ff.source.startswith('http://mackerell.umaryland.edu/')
    assert len(ff.archive_sha256 or '') == 64
    assert ff.parameterizations == ('cgenff-4.6',)


def test_entries_are_immutable_so_a_run_cannot_edit_the_rules_it_ran_under():
    ff = forcefields.entry()
    with pytest.raises(Exception):
        setattr(ff, 'temperature_k', 1.0)
