"""Molecule-scoped CG runs must consume a shared AA reference."""
import copy
import json
from pathlib import Path
import pytest

from dashboard.execution.adapters import cg
from dashboard.execution.adapters.cg_names import CGNames
from dashboard.models import draft_model, mappings
from dashboard.models.mappings.context import as_structure, build_context


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_long_molecule_id_uses_short_source_residue_name_for_gro():
    names = CGNames.for_snapshot({'id': 'Maltose', 'metadata': {'molecule_type': 'LIG1'}})
    assert names.residue_name == 'LIG1'
    assert names.initial_itp == 'LIG1_initial.itp'


def test_molecule_scoped_cg_requires_shared_reference(tmp_path):
    snapshot = {'id': 'Maltose', 'metadata': {'molecule_type': 'MAL', 'cg_molecule_type': 'MAL'}}
    run = tmp_path / 'run'; run.mkdir()
    with pytest.raises(ValueError, match='shared AA reference'):
        cg.prepare(run, molecule_snapshot=snapshot, profile='draft-smoke')


def test_molecule_scoped_cg_rejects_invalid_reference_id(tmp_path):
    snapshot = {'id': 'Maltose', 'metadata': {'molecule_type': 'MAL', 'cg_molecule_type': 'MAL'}}
    run = tmp_path / 'run'; run.mkdir()
    with pytest.raises(ValueError, match='Invalid AA source run ID'):
        cg.prepare(
            run, molecule_snapshot=snapshot, profile='draft-smoke',
            shared_reference={'source_run_id': 'not-a-run-id', 'sha256': {}},
        )


def test_maltose_mapping_validation_uses_its_bound_molecule():
    context = build_context(PROJECT_ROOT / 'molecules', 'Maltose')
    mapping = mappings.automatic_candidate(as_structure(context), 'Maltose')
    mapping.update(schema_version=3, molecule_id='Maltose',
                  molecule_snapshot=copy.deepcopy(context['snapshot']))

    loaded = draft_model.load(mapping)
    metadata = json.loads((PROJECT_ROOT / 'molecules/Maltose/metadata.json').read_text())
    names = CGNames.for_snapshot({'id': 'Maltose', 'metadata': metadata})
    topology = draft_model.initial_topology(loaded, residue_name=names.residue_name)

    assert len(loaded['beads']) == 8
    assert '[ moleculetype ]' in topology
    assert topology.count('\n[ atoms ]') == 1
    assert '\nLIG1 1\n' in topology
    assert ' 1 LIG1 B01 ' in topology
    assert ' DDM ' not in topology


def test_maltose_mapping_without_virtual_sites_allows_advisory_size_warnings():
    context = build_context(PROJECT_ROOT / 'molecules', 'Maltose')
    mapping = mappings.automatic_candidate(as_structure(context), 'Maltose')
    mapping['beads'] = [bead for bead in mapping['beads'] if not bead.get('virtual_site')]
    mapping['rings'] = []
    physical = {bead['name'] for bead in mapping['beads']}
    mapping['connections'] = [pair for pair in mapping['connections'] if set(pair) <= physical]
    mapping.update(schema_version=3, molecule_id='Maltose', molecule_snapshot=copy.deepcopy(context['snapshot']), name='Maltose-0-noVS')

    loaded = draft_model.load(mapping, molecule_root=PROJECT_ROOT / 'molecules')
    exported = mappings.export_files(loaded, context=context)

    assert loaded['name'] == 'Maltose-0-noVS'
    assert {'mapping.map', 'mapping.ndx', 'mapped.gro', 'model.json'} <= exported.keys()
    validation = mappings.validate(loaded, context=context)
    assert validation['issues']
    assert validation['can_export'] and validation['can_reuse']
    assert not validation['can_approve']
