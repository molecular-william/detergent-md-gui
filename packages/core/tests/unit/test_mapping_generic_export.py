from dashboard.models import mappings
from dashboard.models.mappings.context import build_context

from tests.harness.support import write_aa_fixture


def new_draft(context, name):
    """An empty molecule-bound editor document, the shape the route hands the editor."""
    return {'schema_version': 3, 'molecule_id': context['molecule_id'],
            'molecule_snapshot': context['snapshot'], 'name': name,
            'beads': [], 'rings': [], 'connections': [],
            'provenance': {'origin': 'manual', 'algorithm': None, 'references': []},
            'status': 'candidate-unvalidated', 'martini_version': '3'}


def test_export_uses_selected_molecule_and_keeps_snapshot(tmp_path):
    write_aa_fixture(tmp_path, 'Fixture')
    context = build_context(tmp_path, 'Fixture')
    candidate = new_draft(context, 'Complete fixture')
    candidate['beads'] = [{'name': 'B1', 'size': 'R', 'type': 'C1', 'atoms': [1, 2, 3, 4]}]
    files = mappings.export_files(candidate, context=context)
    assert 'LIG1 Fixture' in files['mapping.map']
    assert 'molecule_snapshot' in files['model.json']
    assert 'DDM' not in files['README.txt']
