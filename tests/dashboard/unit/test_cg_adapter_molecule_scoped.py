"""Molecule-scoped CG runs must consume a shared AA reference."""
import pytest

from dashboard.execution import cg_adapter


def test_molecule_scoped_cg_requires_shared_reference(tmp_path):
    snapshot = {'id': 'Maltose', 'metadata': {'molecule_type': 'MAL', 'cg_molecule_type': 'MAL'}}
    run = tmp_path / 'run'; run.mkdir()
    with pytest.raises(ValueError, match='shared AA reference'):
        cg_adapter.prepare(run, molecule_snapshot=snapshot, profile='draft-smoke')


def test_molecule_scoped_cg_rejects_invalid_reference_id(tmp_path):
    snapshot = {'id': 'Maltose', 'metadata': {'molecule_type': 'MAL', 'cg_molecule_type': 'MAL'}}
    run = tmp_path / 'run'; run.mkdir()
    with pytest.raises(ValueError, match='Invalid AA source run ID'):
        cg_adapter.prepare(
            run, molecule_snapshot=snapshot, profile='draft-smoke',
            shared_reference={'source_run_id': 'not-a-run-id', 'sha256': {}},
        )