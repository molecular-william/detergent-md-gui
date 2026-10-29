"""The composition: three sections in one result, the reference as context, and what it refuses.

The readings are injected here because a coarse-grained run with a real atomistic reference does not exist in
this workspace yet, and a test that needed one would be testing the developer's workspace. What is asserted
is the composition itself: the sections and their labels, the reference carried as context, the artifact it
publishes, and the two refusals — no mapping snapshot, and no atomistic side to read.
"""
import json

import numpy as np
import pytest
from detergent_validation.analysis.runs import mapping_consistency

from tests.dashboard import support

BEADS = {1: (1, 'A'), 2: (1, 'B'), 3: (1, 'C'), 4: (1, 'VS')}
PAIRS = {frozenset((1, 2)): [0.300, 0.310], frozenset((1, 3)): [0.400, 0.410], frozenset((2, 3)): [0.500, 0.510]}
MEANS = np.array([[0.0, 0.0, 0.0], [0.4, 0.0, 0.0], [0.0, 0.4, 0.0], [0.0, 0.0, 0.0]])

MAPPING = {
    'beads': [
        {'name': 'S1A', 'letter': 'A', 'residue': 1, 'size': 'S', 'type': 'SP1r', 'atoms': [1, 2]},
        {'name': 'S1B', 'letter': 'B', 'residue': 1, 'size': 'S', 'type': 'SP4r', 'atoms': [3, 4]},
        {'name': 'S1C', 'letter': 'C', 'residue': 1, 'size': 'S', 'type': 'SP1r', 'atoms': [5, 6]},
        {'name': 'S1VS', 'letter': 'VS', 'residue': 1, 'size': 'T', 'type': 'TC4', 'atoms': [],
         'virtual_site': {'parents': ['S1A', 'S1B', 'S1C'], 'function': 1}},
    ],
    'rings': [{'beads': ['S1A', 'S1B', 'S1C'], 'scale': 1.15}],
}
PAYLOAD = {'mapping_snapshot': MAPPING, 'molecule': 'Sucrose', 'entry_name': 'SUCR'}


def measured(values, means_shift=0.0):
    means = MEANS + means_shift
    return {'samples': {'run': 'fake', 'frames': 3, 'molecule': 'Sucrose', 'beads': BEADS,
                        'pairs': list(PAIRS), 'samples': dict(values), 'first': {}},
            'means': {'run': 'fake', 'frames': 3, 'beads': BEADS, 'mean': means},
            'terms': {'frames': 3, 'values': {'bonds': {(0, 1): [0.30, 0.31, 0.32]},
                                              'angles': {}, 'dihedrals': {}, 'proper-dihedrals': {}}}}


def readers():
    """The two readings, as the composition expects them, with a known difference between them."""
    aa = measured({pair: [value + 0.00 for value in values] for pair, values in PAIRS.items()})
    cg = measured({pair: [value + 0.01 for value in values] for pair, values in PAIRS.items()},
                  means_shift=0.05)
    return aa, cg


def coarse_grained_run(tmp_path):
    """A consumer layout the composition can read its terms out of, without any measurement."""
    support.cg_fixture_run(tmp_path, MEANS.tolist())
    return tmp_path


def test_a_mapping_snapshot_is_required_because_the_comparison_is_made_through_the_assignment():
    with pytest.raises(ValueError, match='mapping snapshot is required'):
        mapping_consistency.run('anything', {})


def test_the_result_carries_three_sections_each_naming_its_comparison(tmp_path):
    aa, cg = readers()
    result = mapping_consistency.run(coarse_grained_run(tmp_path), PAYLOAD,
                                     aa_measure=lambda *a: aa, cg_measure=lambda *a: cg)
    assert result['comparison'] == 'AA vs CG'
    assert set(result['sections']) == {'pairs', 'terms', 'displacement'}
    assert result['sections']['terms'] == 'AA-mapped vs CG-simulated'
    assert result['pairs']['comparison'] == 'AA vs CG'
    assert result['diagnostic_only'] is True and result['scientifically_validated'] is False


def test_the_reference_entry_is_wired_in_as_context(tmp_path):
    aa, cg = readers()
    result = mapping_consistency.run(coarse_grained_run(tmp_path), PAYLOAD,
                                     aa_measure=lambda *a: aa, cg_measure=lambda *a: cg)
    row = next(row for row in result['pairs']['rows'] if row['pair'] == [[1, 'A'], [1, 'B']])
    assert row['reference_nm'] == pytest.approx(0.305), "SUCR's own constraint for that pair"
    assert row['unconstrained'] is False


def test_the_terms_are_labelled_with_the_coarse_grained_currency(tmp_path):
    aa, cg = readers()
    result = mapping_consistency.run(coarse_grained_run(tmp_path), PAYLOAD,
                                     aa_measure=lambda *a: aa, cg_measure=lambda *a: cg)
    assert result['terms'][0]['beads'] == '(1,A) - (1,B)'
    assert result['terms'][0]['section'] == 'bonds'


def test_the_displacement_section_is_the_fitted_one(tmp_path):
    aa, cg = readers()
    result = mapping_consistency.run(coarse_grained_run(tmp_path), PAYLOAD,
                                     aa_measure=lambda *a: aa, cg_measure=lambda *a: cg)
    shape = result['displacement']
    assert 'rigid-body fitted' in shape['comparison']
    assert shape['fit_beads'] == [[1, 'A'], [1, 'B'], [1, 'C']]
    assert shape['aa_frames'] == 3 and shape['cg_frames'] == 3


def test_the_run_recorded_topology_is_what_the_reader_is_told_to_read(tmp_path):
    """A completed run leaves six `.itp` files in the stage directory; only one of them is the model.

    The mapping snapshot a run records carries the run's own molecule snapshot, so the composition can name
    the file the run simulated instead of taking the first `.itp` it finds — or refusing, once a run has
    completed and the fitted topology sits beside the seeded one.
    """
    support.cg_fixture_run(tmp_path, MEANS.tolist())
    (tmp_path / 'stages/3_initial_CG/SUCR.itp').write_text(
        (tmp_path / 'stages/3_initial_CG/SUCR_initial.itp').read_text())
    captured = {}

    def cg_reader(work_dir, mapping, terms, stride, limit, name=None):
        captured['name'] = name
        return measured(dict(PAIRS))

    aa, _ = readers()
    payload = {**PAYLOAD, 'mapping_snapshot': {**MAPPING,
                                               'molecule_snapshot': {'id': 'Sucrose',
                                                                     'metadata': {'molecule_type': 'SUCR'}}}}
    mapping_consistency.run(tmp_path, payload, aa_measure=lambda *a: aa, cg_measure=cg_reader)
    assert captured['name'] == 'SUCR.itp'
    assert mapping_consistency.topology_name(payload) == 'SUCR.itp'


def test_without_a_recorded_snapshot_a_caller_may_name_the_topology_directly():
    assert mapping_consistency.topology_name(PAYLOAD) is None
    assert mapping_consistency.topology_name({**PAYLOAD, 'cg_topology': 'LIG1.itp'}) == 'LIG1.itp'


def test_a_file_integrity_snapshot_is_not_read_as_a_molecule_record():
    """A candidate's `molecule_snapshot` records files and hashes, not an id, and `CGNames` needs one.

    This is the shape the run actually records: reading it as a molecule record raised `KeyError: 'id'` inside
    the analysis subprocess and failed the whole comparison.
    """
    integrity = {'files': {'molecule.itp': 'abc'}, 'atom_order_sha256': 'x', 'snapshot_sha256': 'y'}
    payload = {**PAYLOAD, 'mapping_snapshot': {**MAPPING, 'molecule_snapshot': integrity}}
    assert mapping_consistency.topology_name(payload) is None
    assert mapping_consistency.topology_name({**payload, 'cg_topology': 'LIG1.itp'}) == 'LIG1.itp'


def test_publish_writes_the_artifact_and_returns_a_small_summary(tmp_path):
    aa, cg = readers()
    summary = mapping_consistency.publish(coarse_grained_run(tmp_path), PAYLOAD,
                                          aa_measure=lambda *a: aa, cg_measure=lambda *a: cg)
    artifact = tmp_path / 'analysis/mapping_consistency.json'
    assert artifact.is_file() and summary['artifact'] == 'analysis/mapping_consistency.json'
    written = json.loads(artifact.read_text())
    assert written['comparison'] == 'AA vs CG' and len(written['pairs']['rows']) == 3
    assert summary['pairs'] == written['pairs']['counts']
    assert summary['terms']['rows'] == 1
    assert summary['displacement_rmsd_nm'] == pytest.approx(written['displacement']['rmsd_nm'])
    assert summary['scientifically_validated'] is False


def test_the_terms_are_read_from_the_run_own_topology_and_its_absence_is_named(tmp_path):
    with pytest.raises(ValueError, match='3_initial_CG'):
        mapping_consistency.run(tmp_path, PAYLOAD)


def test_without_an_atomistic_reference_the_reading_names_the_missing_file(tmp_path):
    """No injection: the real reader runs, finds the coarse-grained run but no atomistic side, and says so."""
    support.cg_fixture_run(tmp_path, MEANS.tolist())
    with pytest.raises(ValueError, match='1_AA-reference'):
        mapping_consistency.run(tmp_path, PAYLOAD)
