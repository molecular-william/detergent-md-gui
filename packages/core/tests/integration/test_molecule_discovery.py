"""Discovery, generated metadata and immutable run-local PDB conversion."""
import json
import shutil
from concurrent.futures import ThreadPoolExecutor

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
