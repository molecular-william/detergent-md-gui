import json
import numpy as np
import pytest
from dashboard.models import mappings
from dashboard.execution import workflow
from dashboard.models import draft_model
from dashboard.models import bonded
from dashboard.models import mapping_store


def test_circular_fit_handles_seam_and_gromacs_harmonic_minimum():
    phase, k = bonded.circular_harmonic([178, 179, -179, -178], 300)
    assert abs(abs(phase)-180) < 1e-9
    assert k > 100
    phase, k = bonded.circular_harmonic([-110, -100, -90], 300)
    assert phase == pytest.approx(-100)
    residual = np.angle(np.exp(1j*np.radians(np.array([-100, 0])-phase)))
    assert (0.5*k*residual**2)[0] == pytest.approx(0)
    assert (0.5*k*residual**2)[1] > 10


def test_options_export_and_saved_draft_survive(monkeypatch, tmp_path):
    monkeypatch.setattr(mapping_store, 'storage_root', lambda: tmp_path)
    c = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    c['bonded_options'] = {'torsion_model': 'circular-harmonic', 'torsion_scale': 0.5}
    c['bonded_overrides'] = [{'section': 'bonds', 'beads': ['S1B', 'S2A'], 'function': 1, 'parameters': [0.33, 1900]}]
    saved = mappings.save_draft(c)
    model = json.loads(mappings.export_files(saved)['model.json'])
    assert model['bonded_options'] == c['bonded_options']
    assert model['bonded_overrides'] == c['bonded_overrides']


def test_manual_parameters_survive_fitting_and_protect_constraints(tmp_path):
    c = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    seed = draft_model.initial_topology(c)
    c['bonded_options'] = {'torsion_model': 'circular-harmonic', 'torsion_scale': 1}
    c['bonded_overrides'] = [{'section': 'bonds', 'beads': ['S1B','S2A'], 'function': 1, 'parameters': [.33, 1900]}]
    np.savetxt(tmp_path/'B01_B02_B05_B06_dihedrals.dat', [-110,-100,-90])
    result, report = bonded.refine(seed, c, tmp_path, 300)
    assert '2 5 1 0.33 1900' in result
    assert '1 2 5 6 2 -100' in result
    assert report['torsions'][0]['phase_deg'] == pytest.approx(-100)
    assert seed.split('[ constraints ]')[1].split('[ bonds ]')[0] == result.split('[ constraints ]')[1].split('[ bonds ]')[0]
    c['bonded_overrides'][0]['beads'] = ['S1A','S1B']
    with pytest.raises(ValueError, match='constraint'):
        mappings.check_schema(c)


@pytest.mark.parametrize('options', [{'torsion_scale': float('nan')}, {'torsion_model':'unknown'}, {'distance_weight':2}])
def test_invalid_fitting_options_rejected(options):
    c = mappings.automatic_candidate(mappings.molecule(), 'DDM'); c['bonded_options'] = options
    with pytest.raises(ValueError): mappings.check_schema(c)


def test_manual_connectivity_must_stay_connected():
    c = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    c['connections'].append(['S1C','TAIL3'])
    assert mappings.validate(c)['checks_passed']
    c['connections'] = [p for p in c['connections'] if 'TAIL1' not in p]
    assert any(x['code']=='connections' for x in mappings.validate(c)['issues'])
    c['connections'] = []
    assert any(x['code']=='connections' for x in mappings.validate(c)['issues'])


def test_seed_is_validated():
    assert workflow.normalize_settings({'cg_seed': 123})['cg_seed'] == 123
    with pytest.raises(ValueError): workflow.normalize_settings({'cg_seed': 1.5})
