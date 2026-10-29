"""The complex adapter's contract: what a build must carry, and the stages it will run.

These are the parts of the protocol that can be checked without a structure, a detergent or GROMACS, which is why
they are checked here rather than discovered halfway through a run.
"""
import json
from pathlib import Path

import pytest
from dashboard import paths
from dashboard.execution.adapters import pdc


def test_a_build_requires_a_seed_and_a_positive_aggregation_number():
    """A missing seed is an error, not a default: two builds must not look comparable when they were not."""
    with pytest.raises(ValueError, match='seed'):
        pdc.validate_payload({'template': 'ddm', 'aggregation_number': 4})
    with pytest.raises(ValueError, match='aggregation'):
        pdc.validate_payload({'template': 'ddm', 'aggregation_number': 0, 'seed': 1})
    with pytest.raises(ValueError, match='aggregation'):
        pdc.validate_payload({'template': 'ddm', 'aggregation_number': 2.5, 'seed': 1})
    accepted = pdc.validate_payload({'template': 'ddm', 'aggregation_number': 4, 'seed': 1})
    assert accepted['salt_molar'] == 0.15          # the agreed default, in one place
    assert accepted['aggregation_number'] == 4 and accepted['seed'] == 1


def test_a_protein_free_build_is_expressible():
    """Empty micelles are in scope, so "no protein" must be a real value rather than an empty string."""
    accepted = pdc.validate_payload({'template': 'ddm', 'aggregation_number': 4, 'seed': 1, 'protein': ''})
    assert accepted['protein'] is None


def test_the_stage_list_is_the_protocol_in_order():
    assert [stage.name for stage in pdc.STAGES] == [
        'Protein preparation',
        'System preparation', 'Energy minimisation', 'NVT equilibration', 'NPT equilibration',
        'CG assessment MD', 'Micelle assessment', 'CG extension MD',
        'Final assessment', 'Back-mapping (CG2AT2)']


def test_the_settings_carry_every_protocol_number_with_bounds():
    for key in ('pdc_assessment_ns', 'pdc_extension_ns', 'pdc_seed', 'aggregation_number', 'salt_molar',
                'box_margin_nm', 'initial_z_nm', 'contact_nm', 'selection_threshold_fraction'):
        label, low, high = pdc.SETTING_SPECS[key]
        assert label and low < high, (key, label, low, high)


def _workspace(tmp_path, *, with_sidecar=True, pdbid='1qj8'):
    """An isolated workspace holding one imported structure, and a repository holding one packaged one."""
    workspace = tmp_path / 'workspace'
    imported = workspace / 'proteins'
    imported.mkdir(parents=True)
    (imported / f'{pdbid}.pdb').write_text('ATOM      1  N   ALA A   1       1.000   2.000   3.000\n')
    if with_sidecar:
        (imported / f'{pdbid}.json').write_text(json.dumps({'pdbid': pdbid, 'half_thickness_nm': 1.18}))
    packaged = tmp_path / 'molecules' / 'DDM'
    packaged.mkdir(parents=True)
    (packaged / 'protein.pdb').write_text('ATOM      1  N   ALA A   1       0.000   0.000   0.000\n')
    return workspace


def _catalogue(tmp_path, workspace, project_root=None):
    """The catalogue's protein entries, keyed by name, from this test's own roots."""
    with paths.use(paths.Paths(project_root=project_root or tmp_path, workspace=workspace)):
        entries = pdc.catalog(project_root or tmp_path)['proteins']
    return {entry['name']: entry for entry in entries}


def test_the_catalogue_lists_an_imported_structure_beside_the_packaged_ones(tmp_path):
    """A protein can come from two roots now, so an entry says which one answered."""
    catalogue = _catalogue(tmp_path, _workspace(tmp_path))

    assert catalogue['1qj8']['source'] == 'imported'
    assert catalogue['1qj8']['half_thickness_nm'] == 1.18
    assert catalogue['1qj8']['path'] == 'workspace/proteins/1qj8.pdb'
    assert catalogue['protein']['source'] == 'packaged'
    assert catalogue['protein']['half_thickness_nm'] is None
    # The spelling `prepare` resolves against project_root, unchanged for a packaged protein.
    assert catalogue['protein']['path'] == 'molecules/DDM/protein.pdb'


def test_an_import_placed_by_hand_is_listed_and_states_no_membrane(tmp_path):
    """Somebody will scp one in, so a file with no sidecar is an input rather than an error -- and it says so."""
    catalogue = _catalogue(tmp_path, _workspace(tmp_path, with_sidecar=False))

    assert catalogue['1qj8']['source'] == 'imported'
    assert catalogue['1qj8']['half_thickness_nm'] is None


def test_the_sidecar_is_found_beside_the_file_whatever_the_file_is_called(tmp_path):
    """A hand-placed structure need not be named after a PDB id, so the sidecar is looked for beside the *file*
    rather than derived from an id -- and a hand-written sidecar counts, because it says what the file says."""
    workspace = tmp_path / 'workspace'
    imported = workspace / 'proteins'
    imported.mkdir(parents=True)
    (imported / 'OmpX.pdb').write_text('ATOM      1  N   ALA A   1       1.000   2.000   3.000\n')
    (imported / 'OmpX.json').write_text(json.dumps({'half_thickness_nm': 2.4}))

    catalogue = _catalogue(tmp_path, workspace)

    assert catalogue['OmpX']['source'] == 'imported'
    assert catalogue['OmpX']['half_thickness_nm'] == 2.4


def test_a_workspace_outside_the_repository_is_listed_by_its_absolute_path(tmp_path):
    """A configured workspace can live anywhere, and `root / path` takes an absolute path unchanged -- so a path
    that has no project-relative spelling is reported as it is rather than dropped from the list."""
    repo = tmp_path / 'repo'
    elsewhere = tmp_path / 'elsewhere'
    (repo / 'molecules').mkdir(parents=True)
    imported = elsewhere / 'proteins'
    imported.mkdir(parents=True)
    (imported / '1qj8.pdb').write_text('ATOM      1  N   ALA A   1       1.000   2.000   3.000\n')

    catalogue = _catalogue(tmp_path, elsewhere, project_root=repo)

    assert Path(catalogue['1qj8']['path']).is_absolute()
    assert catalogue['1qj8']['path'] == str(imported / '1qj8.pdb')


def test_an_entry_that_states_its_membrane_becomes_a_frame_naming_the_file(tmp_path):
    """The catalogue carries the statement; this is the one place it turns into geometry a build can use."""
    catalogue = _catalogue(tmp_path, _workspace(tmp_path))

    built = pdc.protein_frame(catalogue['1qj8'])

    assert built.half_thickness_nm == 1.18
    assert built.axis == (0.0, 0.0, 1.0)
    assert (built.plane_low_nm, built.plane_high_nm) == (-1.18, 1.18)
    assert 'workspace/proteins/1qj8.pdb' in built.source      # traceable to the file that stated it


def test_an_entry_that_states_nothing_gives_no_frame_rather_than_a_guessed_one(tmp_path):
    """No frame means the caller keeps the box and the placement it had -- which is every packaged protein, every
    import whose file states nothing, and every protein-free build."""
    catalogue = _catalogue(tmp_path, _workspace(tmp_path, with_sidecar=False))

    assert pdc.protein_frame(catalogue['1qj8']) is None
    assert pdc.protein_frame(catalogue['protein']) is None
    assert pdc.protein_frame(None) is None


def test_the_catalogue_entry_carries_the_chains_the_sidecar_recorded(tmp_path):
    """The chain list is read where the half-thickness is -- at import -- and travels with it into the catalogue."""
    workspace = _workspace(tmp_path)
    (workspace / 'proteins' / '1qj8.json').write_text(
        json.dumps({'pdbid': '1qj8', 'half_thickness_nm': 1.18, 'chains': ['A', 'B']}))

    catalogue = _catalogue(tmp_path, workspace)

    assert catalogue['1qj8']['chains'] == ['A', 'B']
    assert catalogue['protein']['chains'] is None, \
        'a packaged protein has no sidecar, so its chains are unread rather than guessed'


def test_a_sidecar_that_recorded_no_chains_has_the_file_read_for_them(tmp_path):
    """An import written before chains were recorded, or a hand-made sidecar, would otherwise leave every existing
    entry without a chain list -- and a picker with nothing to offer. The file is read instead: not guessed, read."""
    catalogue = _catalogue(tmp_path, _workspace(tmp_path))

    assert catalogue['1qj8']['chains'] == ['A'], 'the fixture file names chain A'
    assert catalogue['protein']['chains'] is None, 'a packaged protein has no sidecar and stays unread'


def test_a_file_that_names_no_chain_says_so_rather_than_guessing_one(tmp_path):
    workspace = _workspace(tmp_path)
    (workspace / 'proteins' / '1qj8.pdb').write_text('ATOM      1  N   ALA     1       1.000   2.000   3.000\n')

    catalogue = _catalogue(tmp_path, workspace)

    assert catalogue['1qj8']['chains'] == []
