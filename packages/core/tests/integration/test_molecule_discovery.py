"""Discovery, generated metadata and immutable run-local PDB conversion."""
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from dashboard import files
from dashboard.analysis.runs import references as aa_references
from dashboard.execution import forcefields, run_inputs
from dashboard.execution.adapters import aa
from dashboard.models.molecules import aa as aa_molecules

from tests.harness.support import PROJECT_ROOT


@pytest.fixture
def source(tmp_path):
    folder = tmp_path/'molecules/Example'
    shutil.copytree(PROJECT_ROOT/'molecules/DDM', folder)
    (folder/'metadata.json').unlink(missing_ok=True)
    return folder


def test_nested_pdb_generates_metadata_once_and_preserves_sources(source):
    before = files.hashes(source)
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda _: aa_molecules.inspect(source.parent, source.name), range(8)))
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
    assert aa_molecules.inspect(source.parent, source.name)['metadata'] == custom


def test_gro_is_preferred_and_ambiguous_pairs_block_launch(source):
    pdb = source/'results/MMFF/lig1.pdb'
    pdb.with_suffix('.gro').write_text(aa_molecules.pdb_gro(pdb.read_text()))
    record = aa_molecules.inspect(source.parent, source.name)
    assert record['inputs']['coordinate_format'] == 'gro'
    shutil.copytree(pdb.parent, source/'duplicate')
    record = aa_molecules.inspect(source.parent, source.name)
    assert not record['valid'] and 'Multiple' in ' '.join(record['issues'])


def test_unknown_force_field_is_not_silently_admitted(source):
    itp = source/'results/MMFF/lig1.itp'
    itp.write_text(itp.read_text().replace('by user SwissParam', 'by user Unknown'))
    record = aa_molecules.inspect(source.parent, source.name)
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
        pdb.unlink(); pdb.symlink_to(PROJECT_ROOT/'molecules/DDM/results/MMFF/lig1.pdb')
    else:
        pdb.write_text('\n'.join(lines))
    record = aa_molecules.inspect(source.parent, source.name)
    assert not record['valid']
    assert not (source/'metadata.json').exists()


def test_pdb_preparation_hashes_source_and_conversion_without_mutating_source(source, tmp_path, monkeypatch):
    selected = aa_molecules.selection(source.parent, source.name, run_type='aa_only')
    before = files.hashes(source)
    run = tmp_path/'run'; run.mkdir()
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {})
    monkeypatch.setattr(aa, 'gromacs_flavour', lambda *arguments, **keywords: 'mpi')
    aa.prepare_run(run, source.parent, selected, {'box_nm': 4.0})
    prepared = run/'inputs/common/molecule'
    assert files.hashes(source) == before
    assert not (source/'molecule.gro').exists()
    assert (prepared/'molecule.gro').read_text() == aa_molecules.pdb_gro((source/'results/MMFF/lig1.pdb').read_text())
    assert (prepared/'molecule.itp').read_text() == f'#include "{(source/"results/MMFF/lig1.itp").resolve()}"\n'
    files.verify(source, selected['sha256'])
    manifest = json.loads((run/'manifest.json').read_text())
    assert manifest['input_preparation']['coordinate_conversion']['method'] == 'aa_molecules.pdb_gro'
    assert manifest['layout_version'] == 3
    # The store is named, not copied: no published file is in `inputs/`, and nothing of the tree is in `stages/`.
    assert not (prepared/'results').exists()
    assert not (run/'stages/common'/forcefields.entry().directory).exists()
    molecule_entries = [entry for entry in manifest['inputs'] if entry['role'] == 'molecule']
    assert {entry['path'] for entry in molecule_entries} == {
        f'molecules/Example/{relative}' for relative in selected['sha256']}
    for entry in molecule_entries:
        run_inputs.verify_entry(entry, repo_root=tmp_path)
    legacy = dict(selected, sha256={'molecule.itp': files.sha256(source/'results/MMFF/lig1.itp'),
                                  'molecule.gro': files.sha256(prepared/'molecule.gro')})
    legacy.pop('reference_sha256')
    assert aa_references.identity(selected) == aa_references.identity(legacy)
    (source/'results/MMFF/lig1.pdb').write_text('changed after queue')
    with pytest.raises(ValueError):
        aa_molecules.verify_selection(source.parent, selected)


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


def test_a_cg_folder_is_classified_as_cg_and_selected_as_one(tmp_path):
    root = tmp_path / 'molecules'
    shutil.copytree(FIXTURES / 'cg_og', root / 'OG')
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
    import hashlib
    client, root = import_service
    itp = fixture_text('cg_og', 'molecule.itp')
    gro = fixture_text('cg_og', 'molecule.gro')

    response = client.post('/api/molecules/import',
                           json=submission('OG', 'cg', ('OG.itp', itp), ('OG.gro', gro)))

    assert response.status_code == 201, response.get_json()
    record = response.get_json()['molecule']
    assert record['kind'] == 'cg' and record['valid'] and record['capabilities']['cg']['executable']
    folder = root / 'molecules' / 'OG'
    assert {path.name for path in folder.iterdir()} == {'molecule.itp', 'molecule.gro', 'metadata.json'}
    metadata = json.loads((folder / 'metadata.json').read_text())
    assert metadata['kind'] == 'cg'
    assert metadata['sources']['topology'] == {'name': 'OG.itp',
                                                'sha256': hashlib.sha256(itp.encode()).hexdigest()}
    assert metadata['sources']['coordinates']['name'] == 'OG.gro'
    listed = {entry['id']: entry for entry in client.get('/api/molecules').get_json()['molecules']}
    assert listed['OG']['kind'] == 'cg', 'the bead editor filters on the kind the catalogue exposes'
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
    folder = root / 'molecules' / 'Example'
    assert {path.name for path in folder.iterdir()} == {'lig1.itp', 'lig1.pdb', 'metadata.json'}
    assert json.loads((folder / 'metadata.json').read_text())['generated'] is True
    assert client.get('/api/molecules').get_json()['molecules'][0]['kind'] == 'aa'


def test_an_import_refuses_a_filename_that_is_a_path(import_service):
    client, root = import_service
    body = submission('Traversal', 'cg', ('../OG.itp', fixture_text('cg_og', 'molecule.itp')),
                      ('OG.gro', fixture_text('cg_og', 'molecule.gro')))

    response = client.post('/api/molecules/import', json=body)

    assert response.status_code == 400
    assert 'plain file name' in response.get_json()['error']
    assert not (root / 'molecules' / 'Traversal').exists()


def test_an_import_never_replaces_an_existing_folder(import_service):
    client, root = import_service
    folder = root / 'molecules' / 'OG'
    folder.mkdir()
    sentinel = folder / 'keep.txt'
    sentinel.write_text("the user's molecule")

    response = client.post('/api/molecules/import', json=submission(
        'OG', 'cg', ('OG.itp', fixture_text('cg_og', 'molecule.itp')),
        ('OG.gro', fixture_text('cg_og', 'molecule.gro'))))

    assert response.status_code == 409
    assert 'already exists' in response.get_json()['error']
    assert sentinel.read_text() == "the user's molecule"
    assert {path.name for path in folder.iterdir()} == {'keep.txt'}


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
    shutil.copytree(FIXTURES / 'cg_og', root / 'molecules' / 'OG')

    readiness = client.get('/api/readiness?run_type=aa_cg&molecule_id=OG').get_json()
    assert readiness['ready'] is False
    assert any('coarse-grained' in blocker for blocker in readiness['blockers'])
    queued = client.post('/', json={'run_type': 'aa_only', 'molecule_id': 'OG', 'detergent': 'OG'})
    assert queued.status_code == 409
    assert 'coarse-grained' in queued.get_json()['error']
