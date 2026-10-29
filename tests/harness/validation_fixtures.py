"""What a completed comparison analysis leaves on disk, for the panels that read it.

`publish` and `publish_cross_check`, with the comparison and cross-check records they write, lived in the browser
test that first needed them and `test_plotly_lazy_browser.py` imported them from there. The construction is shared;
what each panel asserts about it stays in its own file.
"""
import json

COMPARISON = {
    'schema_version': 1, 'comparison': 'AA vs CG', 'molecule': 'Sucrose', 'entry': 'SUCR',
    'sections': {'pairs': 'AA vs CG', 'terms': 'AA-mapped vs CG-simulated',
                 'displacement': 'AA vs CG, rigid-body fitted on the beads that own atoms'},
    'pairs': {'counts': {'pairs': 2, 'compared': 2, 'cg_outside_aa_range': 0}, 'rows': [
        {'pair': [[1, 'A'], [1, 'B']], 'compared': True, 'unconstrained': False,
         'aa': {'mean': 0.3155, 'std': 0.0063, 'stderr': 0.0002, 'count': 20001, 'min': 0.29, 'max': 0.34},
         'cg': {'mean': 0.3155, 'std': 0.0004, 'stderr': 0.0, 'count': 20001, 'min': 0.315, 'max': 0.316},
         'delta_pct': 0.0, 'inside_range': True, 'inside_spread': True,
         'reference_nm': 0.3050, 'delta_vs_reference_pct': 3.44},
        {'pair': [[2, 'A'], [2, 'B']], 'compared': True, 'unconstrained': False,
         'aa': {'mean': 0.3160, 'std': 0.0035, 'stderr': 0.0000, 'count': 20001, 'min': 0.30, 'max': 0.33},
         'cg': {'mean': 0.3160, 'std': 0.0004, 'stderr': 0.0, 'count': 20001, 'min': 0.315, 'max': 0.317},
         'delta_pct': 0.0, 'inside_range': True, 'inside_spread': True,
         'reference_nm': 0.3760, 'delta_vs_reference_pct': -15.96}]},
    'terms': [
        {'section': 'bonds', 'atoms': [0, 4], 'beads': '(1,A) - (2,A)', 'compared': True,
         'aa': {'mean': 0.30, 'std': 0.01, 'stderr': 0.0, 'count': 20001, 'min': 0.28, 'max': 0.32},
         'cg': {'mean': 0.30, 'std': 0.01, 'stderr': 0.0, 'count': 20001, 'min': 0.29, 'max': 0.31},
         'delta': -0.0, 'wasserstein': 0.002, 'overlap': 0.886, 'overlap_range': [0.2298, 0.3803]},
        {'section': 'angles', 'atoms': [0, 4, 5], 'beads': '(1,A) - (2,A) - (2,B)', 'compared': True,
         'aa': {'mean': 126.93, 'std': 5.09, 'stderr': 0.1, 'count': 20001, 'min': 100.0, 'max': 146.0},
         'cg': {'mean': 124.30, 'std': 10.46, 'stderr': 0.3, 'count': 20001, 'min': 92.0, 'max': 152.0},
         'delta': -2.63, 'wasserstein': 5.19, 'overlap': 0.622, 'overlap_range': [95.6513, 150.5906]}],
    'displacement': {'comparison': 'AA vs CG, rigid-body fitted on the beads that own atoms',
                     'rmsd_nm': 0.00431, 'max_nm': 0.00723, 'aa_frames': 20001, 'cg_frames': 20001,
                     'fit_beads': [[1, 'A'], [1, 'B']],
                     'per_bead': [{'bead': [1, 'A'], 'displacement_nm': 0.004},
                                  {'bead': [1, 'B'], 'displacement_nm': 0.019},
                                  {'bead': [1, 'VS'], 'displacement_nm': 0.001}]},
    'diagnostic_only': True, 'scientifically_validated': False,
    'interpretation': 'This compares our model with our own atomistic reference.',
}

def publish(dashboard, jid, comparison=None, analyses=None):
    """Leave behind what `analysis.worker` leaves behind for a completed comparison."""
    runs = dashboard.coordinator.RUNS; runs.mkdir(parents=True, exist_ok=True)
    record = {'id': jid, 'label': 'Sucrose CG consumer', 'detergent': 'Sucrose', 'method': 'fast_forward',
              'run_type': 'aa_cg', 'profile': 'draft-smoke-reference', 'reference_run_id': '03875cf39790',
              'molecule_id': 'Sucrose', 'status': 'completed', 'stage': 'complete',
              'created': dashboard.coordinator.now()}
    # Only when a test wants one: a record with no `analyses` is what most of these fixtures have always been, and
    # the panel reads absence and an empty list the same way.
    if analyses is not None:
        record['analyses'] = analyses
    dashboard.coordinator.database().replace([record])
    attempt = runs / jid / 'analyses/mapping-consistency/hash/attempt1'
    output = attempt / 'output/abc123/analysis'
    output.mkdir(parents=True)
    (output / 'mapping_consistency.json').write_text(json.dumps(comparison or COMPARISON))
    (attempt / 'result.json').write_text(json.dumps(
        {'result': {'artifact': 'analysis/mapping_consistency.json', 'comparison': 'AA vs CG'},
         'output_directory': 'output/abc123', 'wall_seconds': 13.3}))
    return attempt

CROSS_CHECK = {
    'molecule': 'DDM', 'temperature': 303.15,
    'temperature_source': "the analysis default; the run's own fit temperature was not staged",
    'threshold': 10000.0,
    'threshold_source': "this repository's Fast_Forward convention; shaker defaults to 25000",
    'frames_measured': 20001, 'frames_in_trajectory': 20001,
    'ours_from': '3_initial_CG/DDM_ff_inter.itp', 'ours_provenance': 'the Fast_Forward fit',
    'estimate_from': '2_mapping/mapped.xtc',
    'estimate_provenance': 'equipartition k = R T / sigma^2 per term, independently of the fit',
    'rows': [
        {'kind': 'bond', 'beads': ['B01', 'B11'],
         'ours': {'value': 0.431, 'force_constant': 2716.9, 'constraint': False},
         'estimate': {'value': 0.424, 'sigma': 0.03, 'force_constant': 2424.4, 'constraint': False},
         'delta_value': -0.007, 'ratio_force_constant': 0.892, 'verdicts_agree': True},
        {'kind': 'constraint', 'beads': ['B01', 'B02'],
         'ours': {'value': 0.298794, 'force_constant': None, 'constraint': True},
         'estimate': {'value': 0.260, 'sigma': 0.018, 'force_constant': 7878.5, 'constraint': False},
         'delta_value': -0.038794, 'ratio_force_constant': None, 'verdicts_agree': False},
    ],
    'unmeasured': [{'kind': 'bond', 'beads': ['B05', 'B06'], 'value': 0.316070, 'force_constant': None,
                    'reason': 'a spread of zero has no equipartition force constant; that term is a constraint'}],
    'disagreements': [['B01', 'B02']],
    'limitations': ['Bonds and constraints only: an angle is a triple measured as an angle, so it is not in this '
                    'report yet.'],
    'scientifically_validated': False,
}

def publish_cross_check(dashboard, jid):
    """Leave behind what `analysis.worker` leaves behind for a completed bonded cross-check."""
    attempt = dashboard.coordinator.RUNS / jid / 'analyses/bonded-cross-check/hash/attempt1'
    output = attempt / 'output/abc123'
    output.mkdir(parents=True)
    (output / 'bonded-cross-check.json').write_text(json.dumps(CROSS_CHECK))
    (attempt / 'result.json').write_text(json.dumps(
        {'result': CROSS_CHECK, 'output_directory': 'output/abc123', 'wall_seconds': 4.0}))
    return attempt
