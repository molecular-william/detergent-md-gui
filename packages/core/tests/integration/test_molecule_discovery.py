"""Discovery, generated metadata and immutable run-local PDB conversion."""
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from dashboard import files
from dashboard.execution import forcefields, run_inputs
from dashboard.execution.adapters import aa
from dashboard.models.molecules import aa as aa_molecules

from tests.harness.support import PROJECT_ROOT


@pytest.fixture
def source(tmp_path):
    """One version folder, as an import writes it: the files sit under `molecules/<id>/v1/`."""
    folder = tmp_path/'molecules/Example/v1'
    shutil.copytree(PROJECT_ROOT/'molecules/DDM/v1', folder)
    (folder/'metadata.json').unlink(missing_ok=True)
    return folder


def test_nested_pdb_generates_metadata_once_and_preserves_sources(source):
    before = files.hashes(source)
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda _: aa_molecules.inspect(source.parent.parent, source.parent.name, version='v1'), range(8)))
    assert all(r['valid'] and r['capabilities']['aa_only']['executable'] for r in records)
    assert len({r['sha256']['metadata.json'] for r in records}) == 1
    record = records[0]
    assert record['atom_count'] == 81
    assert record['inputs']['coordinates'] == 'results/MMFF/lig1.pdb'
    assert record['metadata']['generated'] is True
    assert record['metadata']['net_charge'] == 0
    assert files.hashes(source) == before | {'metadata.json': record['sha256']['metadata.json']}
    metadata = source/'metadata.json'
    custom = record['metadata'] | {'name': 'My molecule'}
    metadata.write_text(json.dumps(custom))
    assert aa_molecules.inspect(source.parent.parent, source.parent.name, version='v1')['metadata'] == custom


def test_gro_is_preferred_and_ambiguous_pairs_block_launch(source):
    pdb = source/'results/MMFF/lig1.pdb'
    pdb.with_suffix('.gro').write_text(aa_molecules.pdb_gro(pdb.read_text()))
    record = aa_molecules.inspect(source.parent.parent, source.parent.name, version='v1')
    assert record['inputs']['coordinate_format'] == 'gro'
    shutil.copytree(pdb.parent, source/'duplicate')
    record = aa_molecules.inspect(source.parent.parent, source.parent.name, version='v1')
    assert not record['valid'] and 'Multiple' in ' '.join(record['issues'])


def test_unknown_force_field_is_not_silently_admitted(source):
    itp = source/'results/MMFF/lig1.itp'
    itp.write_text(itp.read_text().replace('by user SwissParam', 'by user Unknown'))
    record = aa_molecules.inspect(source.parent.parent, source.parent.name, version='v1')
    assert record['valid']
    assert record['metadata']['force_field'] == 'unknown'
    assert not record['capabilities']['aa_only']['executable']


@pytest.mark.parametrize('bad', ['alternate', 'multiple', 'nan', 'order', 'symlink'])
def test_unsafe_or_inconsistent_pdb_rejected_without_metadata(source, bad):
    pdb = source/'results/MMFF/lig1.pdb'
    lines = pdb.read_text().splitlines()
    index = next(i for i,l in enumerate(lines) if l.startswith(('ATOM  ', 'HETATM')))
    if bad == 'alternate':
        lines[index] = lines[index][:16] + 'A' + lines[index][17:]
    elif bad == 'multiple':
        lines += ['MODEL        1', 'ENDMDL', 'MODEL        2', 'ENDMDL']
    elif bad == 'nan':
        lines[index] = lines[index][:30] + '     nan' + lines[index][38:]
    elif bad == 'order':
        lines[index], lines[index+1] = lines[index+1], lines[index]
    if bad == 'symlink':
        pdb.unlink(); pdb.symlink_to(PROJECT_ROOT/'molecules/DDM/v1/results/MMFF/lig1.pdb')
    else:
        pdb.write_text('\n'.join(lines))
    record = aa_molecules.inspect(source.parent.parent, source.parent.name, version='v1')
    assert not record['valid']
    assert not (source/'metadata.json').exists()


def test_pdb_preparation_names_source_and_conversion_without_mutating_source(source, tmp_path, monkeypatch):
    selected = aa_molecules.selection(source.parent.parent, source.parent.name, run_type='aa_only', version='v1')
    before = files.hashes(source)
    run = tmp_path/'run'; run.mkdir()
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {})
    monkeypatch.setattr(aa, 'gromacs_flavour', lambda *arguments, **keywords: 'mpi')
    aa.prepare_run(run, source.parent.parent, selected, {'box_nm': 4.0})
    prepared = run/'inputs/common/molecule'
    assert files.hashes(source) == before
    assert not (source/'molecule.gro').exists()
    assert (prepared/'molecule.gro').read_text() == aa_molecules.pdb_gro((source/'results/MMFF/lig1.pdb').read_text())
    assert (prepared/'molecule.itp').read_text() == f'#include "{(source/"results/MMFF/lig1.itp").resolve()}"\n'
    assert 'sha256' not in selected and 'reference_sha256' not in selected, \
        'a selection names its version, not one digest per file'
    manifest = json.loads((run/'manifest.json').read_text())
    assert manifest['input_preparation']['coordinate_conversion']['method'] == 'aa_molecules.pdb_gro'
    assert manifest['layout_version'] == 4
    # The store is named, not copied: no published file is in `inputs/`, and nothing of the tree is in `stages/`.
    assert not (prepared/'results').exists()
    assert not (run/'stages/common'/forcefields.entry().directory).exists()
    inputs = selected['inputs']
    included = [*aa_molecules.topology_tree(source, inputs['topology'])[1], inputs['coordinates'], 'metadata.json']
    molecule_entries = [entry for entry in manifest['inputs'] if entry['role'] == 'molecule']
    assert {entry['path'] for entry in molecule_entries} == {
        f'molecules/Example/v1/{relative}' for relative in included}
    assert {entry['label'] for entry in molecule_entries} == {
        f'Example/v1/{relative}' for relative in included}
    for entry in molecule_entries:
        run_inputs.verify_entry(entry, repo_root=tmp_path)
    (source/'results/MMFF/lig1.pdb').write_text('changed after queue')
    with pytest.raises(ValueError):
        aa_molecules.verify_selection(source.parent.parent, selected)


# --- Local molecule imports (item 5) ------------------------------------------------------------------------------

#: The checked-in small molecules these tests import. They are the test's own files, so no test reads the developer's
#: `molecules/` tree: `aa_example` is a two-atom SwissParam-labelled pair and `cg_og` a three-bead Martini 3 detergent.
FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'


def fixture_text(name, filename):
    return (FIXTURES / name / filename).read_text()


def submission(molecule_id, kind, topology, coordinates, metadata=None):
    """The import route's body: names and texts, exactly what a client posts."""
    body = {'id': molecule_id, 'kind': kind,
            'topology': {'name': topology[0], 'text': topology[1]},
            'coordinates': {'name': coordinates[0], 'text': coordinates[1]}}
    if metadata is not None:
        body['metadata'] = metadata
    return body


@pytest.fixture
def import_service(dashboard, tmp_path, monkeypatch):
    """An application whose project root is the test's, so an import writes under `tmp_path/molecules`."""
    root = tmp_path / 'project'
    (root / 'molecules').mkdir(parents=True)
    monkeypatch.setattr(dashboard.coordinator, 'ROOT', root)
    return dashboard.client, root


def versioned_copy(source, target):
    """A molecule id folder holding `v1/`, as an import writes it, from a fixture that states no version."""
    target.mkdir(parents=True)
    shutil.copytree(source, target / 'v1')
    metadata = target / 'v1' / 'metadata.json'
    metadata.write_text(json.dumps({**json.loads(metadata.read_text()), 'version': 'v1'}))
    return target / 'v1'


def test_a_cg_folder_is_classified_as_cg_and_selected_as_one(tmp_path):
    root = tmp_path / 'molecules'
    versioned_copy(FIXTURES / 'cg_og', root / 'OG')
    record = aa_molecules.inspect(root, 'OG')

    assert record['kind'] == 'cg' and record['valid']
    assert record['atom_count'] == 3
    assert record['executable'] is False, 'a CG molecule is not an all-atom source'
    assert record['capabilities']['cg']['executable'] is True
    for run_type in ('aa_only', 'aa_cg'):
        assert record['capabilities'][run_type]['executable'] is False
        assert 'cg' in ' '.join(record['capabilities'][run_type]['blockers'])

    snapshot = aa_molecules.selection(root, 'OG', 'cg')
    assert snapshot['kind'] == 'cg' and snapshot['cg_residue_name'] == 'OG'
    aa_molecules.verify_selection(root, snapshot)
    for run_type in ('aa_only', 'aa_cg'):
        with pytest.raises(ValueError, match='coarse-grained'):
            aa_molecules.selection(root, 'OG', run_type)


def test_a_cg_import_writes_the_cg_layout_and_records_its_sources(import_service):
    client, root = import_service
    itp = fixture_text('cg_og', 'molecule.itp')
    gro = fixture_text('cg_og', 'molecule.gro')

    response = client.post('/api/molecules/import',
                           json=submission('OG', 'cg', ('OG.itp', itp), ('OG.gro', gro)))

    assert response.status_code == 201, response.get_json()
    record = response.get_json()['molecule']
    assert record['kind'] == 'cg' and record['valid'] and record['capabilities']['cg']['executable']
    assert (record['version'], record['path']) == ('v1', 'molecules/OG/v1')
    folder = root / 'molecules' / 'OG' / 'v1'
    assert {path.name for path in folder.iterdir()} == {'molecule.itp', 'molecule.gro', 'metadata.json'}
    metadata = json.loads((folder / 'metadata.json').read_text())
    assert metadata['kind'] == 'cg' and metadata['version'] == 'v1'
    assert metadata['sources'] == {'topology': {'name': 'OG.itp'}, 'coordinates': {'name': 'OG.gro'}}, \
        'the submitted names are recorded; the version directory is the identity'
    assert metadata['imported_at'], 'the import records when the submission arrived'
    listed = {entry['id']: entry for entry in client.get('/api/molecules').get_json()['molecules']}
    assert listed['OG']['kind'] == 'cg', 'the bead editor filters on the kind the catalogue exposes'
    assert listed['OG']['path'] == 'molecules/OG/v1'
    assert not [path for path in (root / 'molecules').iterdir() if path.name.startswith('.')], \
        'the temporary validation folder is gone'


def test_an_aa_import_writes_a_validated_molecule_folder(import_service):
    client, root = import_service
    body = submission('Example', 'aa', ('lig1.itp', fixture_text('aa_example', 'lig1.itp')),
                      ('lig1.pdb', fixture_text('aa_example', 'lig1.pdb')))

    response = client.post('/api/molecules/import', json=body)

    assert response.status_code == 201, response.get_json()
    record = response.get_json()['molecule']
    assert record['kind'] == 'aa' and record['valid']
    assert record['capabilities']['aa_only']['executable'], 'the fixture states a supported force field'
    folder = root / 'molecules' / 'Example' / 'v1'
    assert {path.name for path in folder.iterdir()} == {'lig1.itp', 'lig1.pdb', 'metadata.json'}
    metadata = json.loads((folder / 'metadata.json').read_text())
    assert metadata['generated'] is True, 'the catalogue generated the force-field record'
    assert metadata['version'] == 'v1'
    assert metadata['sources'] == {'topology': {'name': 'lig1.itp'}, 'coordinates': {'name': 'lig1.pdb'}}
    assert metadata['imported_at']
    assert client.get('/api/molecules').get_json()['molecules'][0]['kind'] == 'aa'


def test_an_import_refuses_a_filename_that_is_a_path(import_service):
    client, root = import_service
    body = submission('Traversal', 'cg', ('../OG.itp', fixture_text('cg_og', 'molecule.itp')),
                      ('OG.gro', fixture_text('cg_og', 'molecule.gro')))

    response = client.post('/api/molecules/import', json=body)

    assert response.status_code == 400
    assert 'plain file name' in response.get_json()['error']
    assert not (root / 'molecules' / 'Traversal').exists()


def test_an_import_writes_a_new_version_and_never_replaces_one(import_service):
    """A submission beside an existing molecule is a new version: the legacy folder and its files stay untouched."""
    client, root = import_service
    folder = root / 'molecules' / 'OG'
    folder.mkdir()
    sentinel = folder / 'keep.txt'
    sentinel.write_text("the user's molecule")
    body = submission('OG', 'cg', ('OG.itp', fixture_text('cg_og', 'molecule.itp')),
                      ('OG.gro', fixture_text('cg_og', 'molecule.gro')))

    first = client.post('/api/molecules/import', json=body)
    assert first.status_code == 201, first.get_json()
    assert first.get_json()['molecule']['path'] == 'molecules/OG/v1'
    assert sentinel.read_text() == "the user's molecule"
    written = (folder / 'v1' / 'molecule.itp').read_bytes()

    second = client.post('/api/molecules/import', json=body)
    assert second.status_code == 201, second.get_json()
    assert second.get_json()['molecule']['version'] == 'v2'
    assert {path.name for path in folder.iterdir()} == {'keep.txt', 'v1', 'v2'}
    assert (folder / 'v1' / 'molecule.itp').read_bytes() == written, 'an earlier version was rewritten'
    assert (folder / 'v2' / 'molecule.itp').read_bytes() == written
    assert aa_molecules.versions(root / 'molecules', 'OG') == ['v1', 'v2']


def test_an_import_refuses_a_symlinked_target(import_service, tmp_path):
    client, root = import_service
    (root / 'molecules' / 'OG').symlink_to(tmp_path / 'elsewhere')

    response = client.post('/api/molecules/import', json=submission(
        'OG', 'cg', ('OG.itp', fixture_text('cg_og', 'molecule.itp')),
        ('OG.gro', fixture_text('cg_og', 'molecule.gro'))))

    assert response.status_code == 409
    assert (root / 'molecules' / 'OG').is_symlink()


@pytest.mark.parametrize('failure', ['count', 'charge', 'kind'])
def test_an_import_refuses_files_that_do_not_agree(import_service, failure):
    client, root = import_service
    itp = fixture_text('cg_og', 'molecule.itp')
    gro = fixture_text('cg_og', 'molecule.gro')
    metadata = None
    if failure == 'count':
        gro = gro.replace('3\n', '2\n', 1).splitlines()
        gro = '\n'.join(gro[:4] + gro[-1:]) + '\n'
    elif failure == 'charge':
        metadata = {'net_charge': 1.0}
    else:
        metadata = {'kind': 'aa'}

    response = client.post('/api/molecules/import', json=submission(
        'OG', 'cg', ('OG.itp', itp), ('OG.gro', gro), metadata))

    assert response.status_code == 400, response.get_json()
    assert not (root / 'molecules' / 'OG').exists(), 'a refused import leaves the tree unchanged'


def test_an_import_refuses_a_file_over_the_eight_mebibyte_limit(import_service):
    client, root = import_service
    oversized = 'x' * (8 * 1024 * 1024 + 1)

    response = client.post('/api/molecules/import', json=submission(
        'Huge', 'cg', ('OG.itp', oversized), ('OG.gro', fixture_text('cg_og', 'molecule.gro'))))

    assert response.status_code == 400
    assert '8 MiB' in response.get_json()['error']
    assert not (root / 'molecules' / 'Huge').exists()


def test_a_cg_molecule_is_not_offered_to_the_aa_run_types(import_service):
    client, root = import_service
    versioned_copy(FIXTURES / 'cg_og', root / 'molecules' / 'OG')

    readiness = client.get('/api/readiness?run_type=cg&molecule_id=OG').get_json()
    assert readiness['ready'] is False
    assert any('coarse-grained' in blocker for blocker in readiness['blockers'])
    queued = client.post('/', json={'run_type': 'aa_only', 'molecule_id': 'OG', 'detergent': 'OG'})
    assert queued.status_code == 409
    assert 'coarse-grained' in queued.get_json()['error']
# --- Versions (named identity, phase 4) -----------------------------------------------------------------------------

def versioned_molecule(root, versions=('v1', 'v2')):
    """A molecule folder whose sources sit in version directories, as an import writes them."""
    for version in versions:
        folder = root / 'MOL' / version
        shutil.copytree(PROJECT_ROOT / 'molecules/DDM/v1', folder)
        metadata = json.loads((folder / 'metadata.json').read_text())
        metadata['version'] = version
        (folder / 'metadata.json').write_text(json.dumps(metadata))
    return root


def test_a_versioned_molecule_reads_its_newest_version_unless_one_is_named(tmp_path):
    root = versioned_molecule(tmp_path / 'molecules')

    assert aa_molecules.versions(root, 'MOL') == ['v1', 'v2']
    newest = aa_molecules.inspect(root, 'MOL')
    assert (newest['version'], newest['path']) == ('v2', 'molecules/MOL/v2')
    assert aa_molecules.inspect(root, 'MOL', version='v1')['path'] == 'molecules/MOL/v1'
    assert aa_molecules.selection(root, 'MOL', 'aa_only', version='v1')['version'] == 'v1'
    with pytest.raises(ValueError, match='not an installed version'):
        aa_molecules.inspect(root, 'MOL', version='v9')
    with pytest.raises(ValueError, match='folder name'):
        aa_molecules.inspect(root, 'MOL', version='../../etc')


def test_a_selection_pinned_to_an_older_version_keeps_verifying(tmp_path):
    """A queued run names the version it read, so a newer import cannot move it; an edit inside it still refuses."""
    root = versioned_molecule(tmp_path / 'molecules')
    pinned = aa_molecules.selection(root, 'MOL', 'aa_only', version='v1')
    versioned_molecule(root, ('v3',))
    assert aa_molecules.inspect(root, 'MOL')['version'] == 'v3'

    aa_molecules.verify_selection(root, pinned)

    metadata = root / 'MOL' / 'v1' / 'metadata.json'
    metadata.write_text(json.dumps({**json.loads(metadata.read_text()), 'name': 'edited'}))
    with pytest.raises(ValueError, match='changed'):
        aa_molecules.verify_selection(root, pinned)


def test_a_mapping_snapshot_names_the_version(tmp_path):
    from dashboard.models.mappings import context as mapping_context

    root = versioned_molecule(tmp_path / 'molecules')
    context = mapping_context.build_context(root, 'MOL', 'v1')

    assert dict(context['snapshot']) == {'molecule_id': 'MOL', 'version': 'v1'}
    assert context['path'] == 'molecules/MOL/v1'
    assert mapping_context.snapshot_matches({'molecule_id': 'MOL', 'version': 'v1'}, context)
    assert not mapping_context.snapshot_matches({'molecule_id': 'MOL', 'version': 'v2'}, context)
    # A digest-era snapshot names no version this folder states, so it is refused as a changed molecule.
    assert not mapping_context.snapshot_matches({'molecule_id': 'MOL', 'snapshot_sha256': 'stale'}, context)
def test_a_versioned_selection_prepares_from_its_own_version_folder(tmp_path, monkeypatch):
    root = versioned_molecule(tmp_path / 'molecules', ('v1',))
    selected = aa_molecules.selection(root, 'MOL', run_type='aa_only', version='v1')
    run = tmp_path / 'run'; run.mkdir()
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {})
    monkeypatch.setattr(aa, 'gromacs_flavour', lambda *arguments, **keywords: 'mpi')

    aa.prepare_run(run, root, selected, {'box_nm': 4.0})

    manifest = json.loads((run / 'manifest.json').read_text())
    recorded = {entry['path'] for entry in manifest['inputs'] if entry['role'] == 'molecule'}
    assert recorded and all(path.startswith('molecules/MOL/v1/') for path in recorded), recorded
    context = json.loads((run / 'stages/common/context.json').read_text())
    assert Path(context['molecule_directory']) == (root / 'MOL' / 'v1').resolve()
    assert context['molecule_snapshot']['version'] == 'v1'
    assert (run / 'inputs/common/molecule/molecule.itp').read_text() == \
        f'#include "{(root / "MOL" / "v1" / "results/MMFF/lig1.itp").resolve()}"\n'
def test_a_folder_without_a_version_is_refused_with_the_migration(tmp_path):
    """The legacy shape is retired: a plain folder is not read as its own version (phase 4's contract step)."""
    root = tmp_path / 'molecules'
    shutil.copytree(PROJECT_ROOT / 'molecules/DDM/v1', root / 'MOL')

    with pytest.raises(ValueError, match='migrate_molecule_versions'):
        aa_molecules.selection(root, 'MOL', run_type='aa_only')
    listed = aa_molecules.catalogue(root)
    assert [entry['id'] for entry in listed] == ['MOL']
    assert not listed[0]['valid'] and 'migrate_molecule_versions' in ' '.join(listed[0]['issues'])
