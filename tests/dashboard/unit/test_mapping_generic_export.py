from dashboard.models import mappings
from dashboard.models.mappings.context import build_context

from tests.dashboard.support import write_aa_fixture


def test_export_uses_selected_molecule_and_keeps_snapshot(tmp_path):
    write_aa_fixture(tmp_path, 'Fixture')
    context = build_context(tmp_path, 'Fixture')
    candidate = mappings.new_draft(context, 'Complete fixture')
    candidate['beads'] = [{'name': 'B1', 'size': 'R', 'type': 'C1', 'atoms': [1, 2, 3, 4]}]
    files = mappings.export_files(candidate, context=context)
    assert 'LIG1 Fixture' in files['mapping.map']
    assert 'molecule_snapshot' in files['model.json']
    assert 'DDM' not in files['README.txt']
