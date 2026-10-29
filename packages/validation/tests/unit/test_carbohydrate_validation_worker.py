from detergent_validation.analysis.validation.report import run


def test_validation_report_keeps_three_evidence_sections_and_provenance(tmp_path):
    result = run(tmp_path, {
        'mapping_snapshot': {'name': 'Maltose-0', 'beads': [], 'rings': []},
        'representation_mode': 'physical_only_ring_constrained',
        'tier': 'setup',
        'target_dataset': {'id': 'maltose-pilot-v1', 'citation': 'doi:test', 'targets': []},
    })
    assert set(result) >= {'status', 'representation', 'mapped_geometry', 'transfer_free_energy', 'osmotic_pressure'}
    assert result['status'] in {'diagnostic_only', 'insufficient_data'}
    assert result['representation']['mode'] == 'physical_only_ring_constrained'
