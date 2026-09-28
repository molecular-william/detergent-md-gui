"""Choosing a force field: what the choice changes, and that a force field nobody can run is refused.

These drive `prepare_run` on a fixture molecule rather than inspecting the adapter, because the promises that
matter are in the files a run is actually prepared with: which tree is copied into `common/`, which water and ion
molecules the topology includes, what the mdp says about constraints, and what the context records.
"""
import json

import pytest

from dashboard.execution import forcefields
from dashboard.execution.adapters import aa
from dashboard.models.molecules import aa as aa_molecules
from tests.dashboard import support


@pytest.fixture
def molecule_root(tmp_path):
    """The molecule *root*: `write_aa_fixture` returns the folder it made, and `selection` wants the parent."""
    root = tmp_path / 'molecules'
    support.write_aa_fixture(root)
    return root


@pytest.fixture
def prepare(tmp_path, molecule_root, monkeypatch):
    """Prepare a run at the given settings. The manifest's GROMACS probe is stubbed: it is not the question."""
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {})

    def prepared(settings=None, name='run'):
        run = tmp_path / name
        run.mkdir()
        selected = aa_molecules.selection(molecule_root, 'Fixture', run_type='aa_only')
        aa.prepare_run(run, molecule_root, selected, settings)
        return run

    return prepared


def test_a_run_defaults_to_the_registrys_force_field(prepare):
    run = prepare()
    context = json.loads((run / 'stages/common/context.json').read_text())
    assert context['force_field'] == forcefields.DEFAULT
    assert context['force_field_directory'] == 'charmm36-feb2026_cgenff-4.6.ff'
    assert (run / 'stages/common' / context['force_field_directory'] / 'forcefield.itp').is_file()
    assert context['force_field_sha256'], 'the tree that ran must be hashed into the context'


def test_the_topology_includes_the_tree_that_was_chosen(prepare):
    run = prepare({'force_field': 'charmm36-jul2022'})
    top = (run / 'stages/01_solvation/system.top').read_text()
    assert '../common/charmm36-jul2022.ff/forcefield.itp' in top
    assert '../common/charmm36-jul2022.ff/tip3p.itp' in top
    assert '../common/charmm36-jul2022.ff/ions.itp' in top
    assert 'feb2026' not in top, 'the tree of the force field that was not chosen must not appear'


def test_the_two_entries_prepare_different_runs(prepare):
    first = (prepare({'force_field': 'charmm36-jul2022'}, 'a') / 'stages/01_solvation/system.top').read_text()
    second = (prepare({'force_field': 'charmm36-feb2026_cgenff-4.6'}, 'b') / 'stages/01_solvation/system.top').read_text()
    assert first != second


def test_the_temperature_default_belongs_to_the_force_field():
    assert aa.normalize_settings({'force_field': 'charmm36-feb2026_cgenff-4.6'})['temperature_k'] == 303.15


def test_a_caller_may_still_name_a_temperature():
    """The default follows the force field; a caller testing that assumption must be able to override it."""
    assert aa.normalize_settings({'temperature_k': 310})['temperature_k'] == 310


def test_a_force_field_the_registry_does_not_offer_is_refused():
    with pytest.raises(ValueError, match='force_field must be one of'):
        aa.normalize_settings({'force_field': 'gromos54a7'})


def test_the_mdp_restrains_every_bond_as_the_paper_does(prepare):
    """The paper's choice, not the manual's h-bonds -- and the manual's block is otherwise the one used."""
    run = prepare()
    text = (run / 'stages/04_nvt/run.mdp').read_text()
    assert 'constraints = all-bonds' in text
    assert 'h-bonds' not in text
    for line in ('cutoff-scheme = Verlet', 'vdwtype = Cut-off', 'vdw-modifier = Force-switch',
                 'rlist = 1.2', 'rvdw = 1.2', 'rvdw-switch = 1', 'coulombtype = PME', 'rcoulomb = 1.2',
                 'DispCorr = no'):
        assert line in text, f'{line!r} is missing from the mdp'


def test_the_mdp_fits_inside_the_protocols_small_box(prepare):
    """A box of 2.5 nm leaves no room for GROMACS's automatic Verlet buffer, which is added to rlist.

    Disabling the buffer is what makes the protocol's box usable at all. `nstlist` stays at 20: GROMACS documents
    it as a performance knob with no accuracy effect under the Verlet scheme, and prescribes at least 20 with GPUs.
    """
    text = (prepare() / 'stages/04_nvt/run.mdp').read_text()
    assert 'verlet-buffer-tolerance = -1' in text
    assert 'nstlist = 20' in text
    assert 'rlist = 1.2' in text


def test_the_box_shape_reaches_the_editconf_command(prepare):
    """The shape is a setting, so it must change the command rather than be recorded and ignored."""
    script = (prepare({'box_shape': 'dodecahedron'}) / 'stages/01_solvation/run.sh').read_text()
    assert '-bt dodecahedron -d 1.25' in script, 'the governing half-width must be asked for directly'
    cubic = (prepare({'box_shape': 'cubic'}, 'cube-run') / 'stages/01_solvation/run.sh').read_text()
    assert '-box 2.5 2.5 2.5' in cubic and 'dodecahedron' not in cubic


def test_a_solutes_caveats_travel_with_the_run_and_are_stated_in_readiness(molecule_root, prepare):
    """The SwissParam version caveat belongs to the solute, so it rides on the run rather than in a comment.

    It is not a blocker -- the pairing may well be sound -- but a reader deciding whether to trust a result needs
    it beside the verdict, and the manifest is the record that outlives the conversation.
    """
    metadata = json.loads((molecule_root / 'Fixture/metadata.json').read_text())
    metadata['parameterization_version'] = 'unrecorded'
    metadata['caveats'] = ['Parameterised by SwissParam, which does not record the CGenFF version it derives from.']
    (molecule_root / 'Fixture/metadata.json').write_text(json.dumps(metadata))

    run = prepare()
    context = json.loads((run / 'stages/common/context.json').read_text())
    assert context['caveats'] == metadata['caveats']
    assert json.loads((run / 'manifest.json').read_text())['caveats'] == metadata['caveats']

    report = aa.readiness(molecule_root, 'Fixture')
    detail = next(check['detail'] for check in report['checks'] if check['label'] == 'AA molecule')
    assert 'SwissParam' in detail
    assert report['blockers'] == [], 'a caveat is a caveat, not a blocker'


def test_the_ion_names_come_from_the_entry(tmp_path, molecule_root, monkeypatch):
    """A charged solute's counterions are named by the force field, not by a literal.

    The selection gate is exercised by its own tests; here the question is only what the generated script asks
    `genion` for, so it is stubbed out and the snapshot is made charged.
    """
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {})
    monkeypatch.setattr(aa_molecules, 'verify_selection', lambda *args: None)
    selected = aa_molecules.selection(molecule_root, 'Fixture', run_type='aa_only')
    metadata = selected['metadata']
    assert isinstance(metadata, dict)
    metadata['net_charge'] = 1
    run = tmp_path / 'charged'
    run.mkdir()
    aa.prepare_run(run, molecule_root, selected, {'force_field': 'charmm36-jul2022'})
    script = (run / 'stages/02_ions/run.sh').read_text()
    assert f"-pname {forcefields.entry('charmm36-jul2022').cation}" in script
    assert f"-nname {forcefields.entry('charmm36-jul2022').anion}" in script
    assert "printf 'SOL" in script
