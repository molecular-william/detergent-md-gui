"""What an AA run names and what it writes: shared inputs by reference, synthesized data by value.

A prepared run used to hold a copy of the force-field tree and of every molecule file. The input model names those
by path and digest instead, and only what `prepare` synthesizes -- the converted `molecule.gro`, the topology shim,
the context, the index, the system topology, the MDPs and the scripts -- is written into `stages/` and mirrored into
`inputs/`. These tests drive `prepare_run` against a throwaway checkout, so a "published" file can be changed after
prepare without touching the real repository.
"""
import json
import shutil
from pathlib import Path

import pytest
from dashboard import files, paths
from dashboard.analysis.runs import references
from dashboard.execution import environment, forcefields, run_inputs
from dashboard.execution.adapters import aa
from dashboard.models.molecules import aa as aa_molecules

from tests.harness import support


def _molecule_root(repo):
    return repo / 'molecules'


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A throwaway checkout: one force-field tree and one molecule, and no network of packages behind them."""
    root = tmp_path / 'repo'
    real_tree = forcefields.entry().tree()
    tree = root / 'resources/aa' / real_tree.name
    tree.parent.mkdir(parents=True)
    shutil.copytree(real_tree, tree)
    support.write_aa_fixture(root / 'molecules')
    monkeypatch.setattr(environment, 'AA_TEMPLATE', tree.parent)
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {})
    monkeypatch.setattr(aa, 'gromacs_flavour', lambda *arguments, **keywords: 'mpi')
    with paths.use(paths.Paths(project_root=root, workspace=tmp_path / 'workspace')):
        yield root


@pytest.fixture
def prepared(repo, tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    selected = aa_molecules.selection(_molecule_root(repo), 'Fixture', run_type='aa_only')
    aa.prepare_run(run, _molecule_root(repo), selected,
                   {'aa_production_ps': 2, 'output_interval_ps': 1, 'box_nm': 4.0})
    return run


def manifest_of(run):
    return json.loads((run / 'manifest.json').read_text())


def test_a_prepared_run_names_shared_inputs_and_writes_only_generated_data(repo, prepared):
    manifest = manifest_of(prepared)
    assert manifest['layout_version'] == 3 and manifest['inputs']
    by_role = {}
    for entry in manifest['inputs']:
        by_role.setdefault(entry['role'], []).append(entry)
    assert by_role['force_field'][0]['files'] == len(files.hashes(repo / by_role['force_field'][0]['path']))
    assert {entry['path'] for entry in by_role['molecule']} == {
        f'molecules/Fixture/{relative}' for relative in ('molecule.itp', 'molecule.gro', 'metadata.json')}

    context = json.loads((prepared / 'stages/common/context.json').read_text())
    assert Path(context['force_field_path']) == (repo / by_role['force_field'][0]['path']).resolve()
    assert not (prepared / 'stages/common' / context['force_field_directory']).exists(), 'the tree is never copied'
    assert not (prepared / 'inputs/common' / context['force_field_directory']).exists()
    assert not (prepared / 'stages/common/molecule/results').exists(), 'stored molecule files are never copied'
    assert not (prepared / 'inputs/common/molecule/metadata.json').exists()
    assert sorted(path.name for path in (prepared / 'inputs/common/molecule').iterdir()) == \
        ['molecule.gro', 'molecule.itp']
    assert (prepared / 'stages/common/molecule/molecule.gro').read_text() == \
        (prepared / 'inputs/common/molecule/molecule.gro').read_text()

    assert run_inputs.verify_manifest(prepared, manifest) == manifest['inputs']


def test_a_force_field_file_changed_after_prepare_refuses_the_run(repo, prepared):
    manifest = manifest_of(prepared)
    entry = next(item for item in manifest['inputs'] if item['role'] == 'force_field')
    next((repo / entry['path']).rglob('*.itp')).write_text('changed after prepare\n')

    with pytest.raises(ValueError, match='force_field changed since this run was prepared'):
        run_inputs.verify_manifest(prepared, manifest)


def test_a_molecule_file_changed_after_prepare_refuses_the_run(repo, prepared):
    manifest = manifest_of(prepared)
    entry = next(item for item in manifest['inputs'] if item['role'] == 'molecule'
                 and item['path'].endswith('molecule.itp'))
    (repo / entry['path']).write_text('changed after prepare\n')

    with pytest.raises(ValueError, match='molecule changed since this run was prepared'):
        run_inputs.verify_manifest(prepared, manifest)


def test_the_system_topology_includes_the_referenced_tree_by_absolute_path(repo, prepared):
    top = (prepared / 'stages/01_solvation/system.top').read_text()
    tree = (repo / 'resources/aa' / forcefields.entry().directory).resolve()
    for name in ('forcefield.itp', forcefields.entry().water_file, 'ions.itp'):
        assert f'#include "{tree / name}"' in top, f'{name} is not referenced by absolute path'
    assert '../common/charmm36' not in top


def test_the_molecule_topology_is_a_generated_shim_to_the_store(repo, prepared):
    stored = (repo / 'molecules/Fixture/molecule.itp').resolve()
    shim = (prepared / 'inputs/common/molecule/molecule.itp').read_text()
    assert shim == f'#include "{stored}"\n'
    context = json.loads((prepared / 'stages/common/context.json').read_text())
    assert context['input_preparation']['topology_include'] == str(stored)


def test_the_reference_publishes_and_rehashes_the_referenced_sources(repo, prepared):
    """The publication has no in-run copy to hash, so it names the store, and `verify` re-hashes it."""
    import MDAnalysis as mda

    manifest = manifest_of(prepared)
    manifest['status'] = 'completed'
    files.atomic_json(prepared / 'manifest.json', manifest)
    stages = prepared / 'stages'
    output = stages / '07_reference'
    # The publication checks the solute's atom order and two increasing frames; everything else is provenance.
    (output / 'lig.gro').write_text((stages / 'common/molecule/molecule.gro').read_text())
    universe = mda.Universe.empty(5, trajectory=True)
    universe.atoms.positions = [[0.1 * index, 0, 0] for index in range(5)]
    with mda.Writer(str(output / 'lig.xtc'), n_atoms=5) as writer:
        for step in range(2):
            universe.trajectory.ts.time = float(step)
            writer.write(universe)
    (output / 'lig.tpr').write_bytes(b'tpr')
    (output / 'diagnostics.xvg').write_text(
        '@ s0 legend "Temperature"\n@ s1 legend "Density"\n0 300 1000\n1 301 1001\n')
    (stages / '02_ions/composition.json').write_text(json.dumps({'molecule_counts': {'LIG': 1}}))
    for name in ('run.gro', 'run.tpr', 'run.xtc', 'run.cpt', 'run.edr', 'run.log', 'system.top', 'run.mdp'):
        (stages / '06_production' / name).write_text(name)

    data = references.publish(stages)

    assert {entry['role'] for entry in data['referenced_sources']} == {'force_field', 'molecule'}
    assert not any('charmm36' in key for key in data['sha256']), 'the tree is not a run-relative artifact'
    assert references.verify(prepared)['sha256']
    # A published source changed later must be refused by the verifier, not silently re-hashed.
    stored = repo / 'molecules/Fixture/molecule.itp'
    original = stored.read_text()
    stored.write_text('changed after publication\n')
    with pytest.raises(ValueError, match='molecule source changed since publication'):
        references.verify(prepared)
    stored.write_text(original)
    tree = Path(next(entry['path'] for entry in data['referenced_sources'] if entry['role'] == 'force_field'))
    next(tree.rglob('*.itp')).write_text('changed after publication\n')
    with pytest.raises(ValueError, match='force_field source changed since publication'):
        references.verify(prepared)


def test_every_prepared_mdp_is_its_recorded_profile_at_the_run_numbers(repo, prepared):
    """Phase 3: `prepare_run` renders the reviewed profiles, and the manifest names each one it used.

    The value the run supplies is the profile's `None` entry, so the file must be exactly `render(profile, values)`
    for the settings the manifest records -- and the mirrored `inputs/` copy is the same text.
    """
    from dashboard.execution.mdp import render

    manifest = manifest_of(prepared)
    assert manifest['mdp_profiles'] == {
        '01_solvation/run.mdp': 'aa-ions-v1', '02_ions/run.mdp': 'aa-ions-v1',
        '03_minimization/run.mdp': 'aa-em-v1', '04_nvt/run.mdp': 'aa-nvt-v1',
        '05_npt/run.mdp': 'aa-npt-v1', '06_production/run.mdp': 'aa-production-v1'}
    for relative, profile in manifest['mdp_profiles'].items():
        expected = render(profile, aa.mdp_values(manifest['settings'], profile))
        assert (prepared / 'stages' / relative).read_text() == expected, relative
        assert (prepared / 'inputs' / relative).read_text() == expected, relative
