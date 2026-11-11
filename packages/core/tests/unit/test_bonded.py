import json

import numpy as np
import pytest
from dashboard.execution.adapters import cg
from dashboard.models import bonded, mappings
from dashboard.models.mappings import store as mapping_store
from dashboard.models.molecules import draft as draft_model


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
    assert cg.normalize_settings({'cg_seed': 123})['cg_seed'] == 123
    with pytest.raises(ValueError): cg.normalize_settings({'cg_seed': 1.5})


# --- the refinement's unit of work is one interaction, not one line -------------------------------------------

def _fitted_torsion_lines():
    """One torsion as Fast-Forward writes it: eight `funct 9` lines, one cosine harmonic each."""
    return ''.join(f'1 2 5 6 9 {0.1 * i:.2f} {-0.5 * i:.2f} {i}\n' for i in range(1, 9))


def test_a_fitted_torsion_is_rewritten_once_not_once_per_harmonic(tmp_path):
    """Fast-Forward writes one torsion as eight `funct 9` lines; the circular fit replaces the interaction, not each line.

    The defect this pins: rewriting every line produced eight identical `funct 2` terms, so the stiffness a run
    simulated was eight times the fitted one and `bonded_fit.json` counted eight torsions for one (found 2026-11-09).
    """
    seed = '[ dihedrals ]\n' + _fitted_torsion_lines() + '1 2 5 7 9 10.00 2.00 1\n'
    candidate = {'beads': [{'name': f'B0{i}'} for i in range(1, 7)],
                 'bonded_options': {'torsion_model': 'circular-harmonic', 'torsion_scale': 2}}
    np.savetxt(tmp_path / 'B01_B02_B05_B06_dihedrals.dat', [-110, -100, -90])
    np.savetxt(tmp_path / 'B01_B02_B05_B07_dihedrals.dat', [10, 20, 30])

    result, report = bonded.refine(seed, candidate, tmp_path, 300)

    dihedrals = [line for line in result.split('[ dihedrals ]')[1].splitlines() if line.strip()]
    assert len(dihedrals) == 2, dihedrals
    assert dihedrals[0].startswith('1 2 5 6 2 '), dihedrals[0]
    assert dihedrals[1].startswith('1 2 5 7 2 '), dihedrals[1]
    assert all(' 9 ' not in line for line in dihedrals), 'a fitted harmonic line survived the refinement'
    assert [torsion['beads'] for torsion in report['torsions']] == [[1, 2, 5, 6], [1, 2, 5, 7]]
    phase, k = bonded.circular_harmonic([-110, -100, -90], 300)
    assert report['torsions'][0]['phase_deg'] == pytest.approx(phase)
    assert report['torsions'][0]['k_kj_mol_rad2'] == pytest.approx(k * 2), \
        'the stiffness scale multiplies the fitted stiffness once'


def test_legacy_keeps_every_fitted_harmonic_line(tmp_path):
    """The legacy model is not a fit of its own: the run simulates the periodic series Fast-Forward wrote."""
    seed = '[ dihedrals ]\n' + _fitted_torsion_lines()
    candidate = {'beads': [{'name': f'B0{i}'} for i in range(1, 7)],
                 'bonded_options': {'torsion_model': 'legacy'}}

    result, report = bonded.refine(seed, candidate, tmp_path, 300)

    assert result == seed, 'legacy must write the fitted lines unchanged'
    assert report['torsions'] == []


def test_two_molecule_blocks_keep_their_own_torsions(tmp_path):
    """The same four atom indices in two `[ dihedrals ]` blocks are two terms, not one interaction's harmonics."""
    one = '[ dihedrals ]\n1 2 5 6 9 1.0 2.0 1\n1 2 5 6 9 3.0 4.0 2\n'
    candidate = {'beads': [{'name': f'B0{i}'} for i in range(1, 7)],
                 'bonded_options': {'torsion_model': 'circular-harmonic'}}
    np.savetxt(tmp_path / 'B01_B02_B05_B06_dihedrals.dat', [-110, -100, -90])

    result, report = bonded.refine(one + one, candidate, tmp_path, 300)

    assert len([torsion for torsion in report['torsions']]) == 2, 'one rewrite per block'
    assert len([line for line in result.splitlines() if line.strip().startswith('1 2 5 6 2')]) == 2


# --- editable terms: one range table, one writer --------------------------------------------------------------

#: Four named beads, the flexible sections, and a constraint that must never be offered as an edit.
EDITABLE_TOPOLOGY = """[ moleculetype ]
MOL 1

[ atoms ]
1 C1 1 MOL B01 1 0 72
2 C1 1 MOL B02 2 0 72
3 C1 1 MOL B03 3 0 72
4 C1 1 MOL B04 4 0 72

[ constraints ]
1 2 1 0.31

[ bonds ]
2 3 1 0.30 5000 ; keep this comment
3 4 1 0.31 5000

[ angles ]
1 2 3 10 141.6 26.8

[ dihedrals ]
1 2 3 4 1 -102.273 36.636 2
"""


def test_parameter_ranges_are_json_safe_and_name_their_fields():
    """Lane D publishes this table to the browser; it must survive json.dumps and carry the unit labels."""
    import json
    encoded = json.dumps(bonded.PARAMETER_RANGES)
    assert set(bonded.PARAMETER_RANGES) == {'bonds', 'angles', 'dihedrals'}
    for kind, functions in bonded.PARAMETER_RANGES.items():
        for function, bounds in functions.items():
            assert len(bounds) == bonded.FUNCTIONS[kind][function]
            for bound in bounds:
                assert set(bound) == {'min', 'max', 'integer', 'label'}
                assert bound['min'] < bound['max']
    dihedral = bonded.PARAMETER_RANGES['dihedrals'][1]
    assert dihedral[2] == {'min': 1, 'max': 6, 'integer': True, 'label': 'multiplicity'}
    assert 'multiplicity' in encoded


@pytest.mark.parametrize('kind, function, parameters', [
    ('bonds', 1, [0.01, 0]),
    ('bonds', 1, [2, 100000]),
    ('angles', 10, [0, 100000]),
    ('dihedrals', 1, [-180, 0, 1]),
    ('dihedrals', 9, [180, 100000, 6]),
    ('dihedrals', 2, [0, 25]),
])
def test_validate_term_accepts_the_edges_of_its_ranges(kind, function, parameters):
    assert bonded.validate_term(kind, function, parameters) == parameters


@pytest.mark.parametrize('kind, function, parameters, message', [
    ('bonds', 1, [0.001, 5000], 'length'),
    ('bonds', 1, [0.3], 'takes 2 parameters'),
    ('bonds', 1, ['0.3', 5000], 'finite number'),
    ('angles', 1, [181, 25], 'angle'),
    ('dihedrals', 1, [0, 10, 1.5], 'integer'),
    ('dihedrals', 1, [0, 100001, 1], 'force'),
    ('dihedrals', 9, [0, 10, 7], 'between 1 and 6'),
    ('dihedrals', 99, [0, 10, 1], 'Unsupported bonded function'),
])
def test_validate_term_refuses_values_the_store_cannot_run(kind, function, parameters, message):
    with pytest.raises(ValueError, match=message):
        bonded.validate_term(kind, function, parameters)


def test_rewrite_interactions_changes_only_the_edited_line():
    rewritten = bonded.rewrite_interactions(EDITABLE_TOPOLOGY, {'bonds:1': [0.32, 6000]})

    assert '2 3 1 0.32 6000 ; keep this comment' in rewritten
    assert '3 4 1 0.31 5000' in rewritten
    assert '1 2 3 10 141.6 26.8' in rewritten
    assert '1 2 3 4 1 -102.273 36.636 2' in rewritten
    assert [row['id'] for row in bonded.parse_interactions(rewritten)] == [
        row['id'] for row in bonded.parse_interactions(EDITABLE_TOPOLOGY)]
    assert bonded.rewrite_interactions(EDITABLE_TOPOLOGY, {}) == EDITABLE_TOPOLOGY


def test_rewrite_interactions_numbers_funct_nine_lines_independently():
    """One Fast-Forward torsion is eight harmonic lines; each line is its own editable row."""
    topology = '[ dihedrals ]\n' + ''.join(
        f'1 2 3 4 9 {index * 10:.1f} {index * 2:.1f} {index}\n' for index in range(1, 9))
    rewritten = bonded.rewrite_interactions(topology, {'dihedrals:5': [77.0, 9.0, 3]})

    lines = [line for line in rewritten.splitlines() if line.strip()]
    assert lines[0] == '[ dihedrals ]'
    assert lines[5] == '1 2 3 4 9 77 9 3'
    assert lines[1] == '1 2 3 4 9 10.0 2.0 1', 'an earlier harmonic moved'


def test_rewrite_interactions_refuses_constraints_and_unknown_ids():
    with pytest.raises(ValueError, match='No editable term constraints:1'):
        bonded.rewrite_interactions(EDITABLE_TOPOLOGY, {'constraints:1': [0.3]})
    with pytest.raises(ValueError, match='No editable term bonds:9'):
        bonded.rewrite_interactions(EDITABLE_TOPOLOGY, {'bonds:9': [0.3, 5000]})
