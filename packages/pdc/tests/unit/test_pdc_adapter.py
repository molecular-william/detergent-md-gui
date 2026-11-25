"""The complex adapter's contract: what a build must carry, and the stages it will run.

These are the parts of the protocol that can be checked without a structure, a detergent or GROMACS, which is why
they are checked here rather than discovered halfway through a run.
"""
import json
from pathlib import Path

import pytest
from dashboard import paths
from detergent_pdc.execution.adapters import pdc


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
                'box_margin_nm', 'initial_z_nm', 'contact_nm', 'selection_threshold_fraction', 'belt_gap_nm'):
        label, low, high = pdc.SETTING_SPECS[key]
        assert label and low < high, (key, label, low, high)


def test_a_stated_initial_xy_is_advertised_bounded_and_has_no_default():
    """Advertised like the dt settings: a supplied value survives the route's filter, an absent one is not invented.

    The label states that the number is a dimension, not a margin, and a value outside the form's range is refused
    here exactly as a run would refuse it. No `DEFAULTS` entry is what makes a blank field mean the derived footprint
    rather than zero.
    """
    for key in ('initial_x_nm', 'initial_y_nm'):
        label, low, high = pdc.SETTING_SPECS[key]
        assert 'dimension' in label and (low, high) == (1.0, 50.0), (key, label, low, high)
        assert key not in pdc.DEFAULTS, f'{key} must stay absent from DEFAULTS: a blank field derives, it does not use 0'
        assert key not in pdc.normalize_settings({}), 'an absent x/y records no value at all'
        assert pdc.normalize_settings({key: 12.5})[key] == 12.5
        with pytest.raises(ValueError, match=key):
            pdc.normalize_settings({key: 0.5})
        with pytest.raises(ValueError, match=key):
            pdc.normalize_settings({key: 50.5})


def test_the_belt_gap_is_advertised_as_a_bounded_setting():
    """The belt's extra stand-off is a run setting like the radius: defaulted to today's geometry and bounded."""
    assert pdc.DEFAULTS['belt_gap_nm'] == 0.0
    assert pdc.SETTING_SPECS['belt_gap_nm'] == ('Belt-protein gap (nm)', 0.0, 5.0)
    assert pdc.normalize_settings({})['belt_gap_nm'] == 0.0
    assert pdc.normalize_settings({'belt_gap_nm': 2.5})['belt_gap_nm'] == 2.5
    assert pdc.normalize_settings({'belt_gap_nm': 5})['belt_gap_nm'] == 5.0
    for outside in (-0.1, 5.5):
        with pytest.raises(ValueError, match='belt_gap_nm'):
            pdc.normalize_settings({'belt_gap_nm': outside})


def test_the_belt_packing_settings_are_advertised_and_bounded():
    """The two belt-only packing settings: defaulted, advertised, and range-checked like every other number."""
    assert pdc.DEFAULTS['min_body_gap_nm'] == 0.3
    assert pdc.SETTING_SPECS['min_body_gap_nm'] == ('Minimum body-bead distance (nm)', 0.0, 2.0)
    assert pdc.DEFAULTS['belt_axial_window_nm'] == 0.75
    assert pdc.SETTING_SPECS['belt_axial_window_nm'] == ('Local surface axial window (nm)', 0.1, 5.0)
    assert pdc.normalize_settings({})['min_body_gap_nm'] == 0.3
    assert pdc.normalize_settings({})['belt_axial_window_nm'] == 0.75
    assert pdc.normalize_settings({'min_body_gap_nm': 0})['min_body_gap_nm'] == 0.0, '0 is the gate off'
    assert pdc.normalize_settings({'min_body_gap_nm': 2})['min_body_gap_nm'] == 2.0
    assert pdc.normalize_settings({'belt_axial_window_nm': 0.1})['belt_axial_window_nm'] == 0.1
    assert pdc.normalize_settings({'belt_axial_window_nm': 5})['belt_axial_window_nm'] == 5.0
    for outside in (-0.1, 2.1):
        with pytest.raises(ValueError, match='min_body_gap_nm'):
            pdc.normalize_settings({'min_body_gap_nm': outside})
    for outside in (0.0, 5.5):
        with pytest.raises(ValueError, match='belt_axial_window_nm'):
            pdc.normalize_settings({'belt_axial_window_nm': outside})


def test_the_vertical_spread_is_a_four_nanometre_total_and_the_old_spellings_still_win():
    """The band's total height is 4 nm unless a payload states a retired spelling instead.

    `belt_vertical_spread_nm` is the form's setting and the band's total height (4 nm = +/-2 nm about the mid-plane);
    the placement halves it. The half-height and the oldest multiple of the detergent length are still read for a run,
    clone or preset written before they were retired: such a payload states one of those and no total, and the
    injected 4.0 must not overwrite the band it was placed with.
    """
    assert pdc.DEFAULTS['belt_vertical_spread_nm'] == 4.0
    assert pdc.SETTING_SPECS['belt_vertical_spread_nm'] == ('Vertical spread (nm)', 1.0, 20.0)
    assert pdc.SETTING_SPECS['belt_vertical_half_nm'][0].startswith('Vertical spread')
    assert pdc.normalize_settings({})['belt_vertical_spread_nm'] == 4.0
    assert pdc.normalize_settings({'belt_vertical_spread_nm': 7.0})['belt_vertical_spread_nm'] == 7.0
    # An old payload states the half-height and no total: its half is kept, and no 4.0 total is invented beside it.
    old_half = pdc.normalize_settings({'belt_vertical_half_nm': 2.5})
    assert old_half['belt_vertical_half_nm'] == 2.5 and 'belt_vertical_spread_nm' not in old_half, old_half
    # The oldest payload states the multiple and neither nm key.
    old_multiple = pdc.normalize_settings({'belt_vertical_spread': 1.1})
    assert old_multiple['belt_vertical_spread'] == 1.1 and 'belt_vertical_spread_nm' not in old_multiple, old_multiple
    # A payload that states both is a new run: the total is what the build halves and the old key is only provenance.
    both = pdc.normalize_settings({'belt_vertical_spread': 1.1, 'belt_vertical_spread_nm': 3.0})
    assert both['belt_vertical_spread_nm'] == 3.0 and both['belt_vertical_spread'] == 1.1


def test_the_outlier_distance_is_advertised_defaulted_and_can_be_turned_off():
    """The far-head repair's trigger is a run setting: 0.75 nm by default, 0 = no repair, range-checked."""
    assert pdc.DEFAULTS['belt_outlier_distance_nm'] == 0.75
    assert pdc.SETTING_SPECS['belt_outlier_distance_nm'] == ('Outlier distance (nm)', 0.0, 5.0)
    assert pdc.normalize_settings({})['belt_outlier_distance_nm'] == 0.75
    assert pdc.normalize_settings({'belt_outlier_distance_nm': 1.5})['belt_outlier_distance_nm'] == 1.5
    assert pdc.normalize_settings({'belt_outlier_distance_nm': 0})['belt_outlier_distance_nm'] == 0.0
    for outside in (-0.1, 5.1):
        with pytest.raises(ValueError, match='belt_outlier_distance_nm'):
            pdc.normalize_settings({'belt_outlier_distance_nm': outside})


def test_the_generated_label_names_the_choices_it_was_built_from():
    """The panel's label field, filled from the same numbers the run is built with -- not a second vocabulary."""
    assert pdc.generated_label('DDM', {'aggregation_number': 192}) == 'DDM_micelle_192_1conf_1us'
    assert pdc.generated_label('DDM', {'aggregation_number': 192},
                               protein='molecules/DDM/4iar.pdb') == 'DDM_4iar_192_1conf_1us'
    # A library's bodies are drawn, so the conformation token says so; the form's own spelling of the durations
    # normalises like every other setting.
    library = {'runs': ['b920391735dd'], 'size': 8}
    assert pdc.generated_label('OG', {'aggregation_number': 80, 'conformation_library': library}) \
        == 'OG_micelle_80_libconf_1us'
    assert pdc.generated_label('DDM', {'aggregation_number': 192, 'conformation_library': library}) \
        == 'DDM_micelle_192_libconf_1us'
    assert pdc.generated_label('DDM', {'aggregation_number': 192, 'pdc_assessment_ns': 600,
                                       'extension_ns': 900}) == 'DDM_micelle_192_1conf_1.5us'
    assert pdc.generated_label('OG', {'aggregation_number': 80, 'pdc_assessment_ns': 201,
                                      'extension_ns': 1}) == 'OG_micelle_80_1conf_202ns'


def test_gpu_sharing_is_advertised_and_normalised_as_a_choice():
    """The coordinator reads the same two words for both run types, so the panel's choice must survive the filter."""
    label, options = pdc.CHOICE_SPECS['gpu_sharing']
    assert label == 'GPU sharing' and options == ('queue', 'share')
    assert pdc.normalize_settings({'gpu_sharing': 'queue'})['gpu_sharing'] == 'queue'
    assert pdc.normalize_settings({'gpu_sharing': 'share'})['gpu_sharing'] == 'share'
    with pytest.raises(ValueError, match='gpu_sharing must be one of queue, share'):
        pdc.normalize_settings({'gpu_sharing': 'later'})


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


# --- the detergent conformation library setting -------------------------------------------------------

def test_the_library_is_a_choice_the_job_settings_keep():
    """The panel's payload key must survive the settings filter, or the run is built with the template.

    `runs.py:queue` keeps only the keys an adapter advertises, and the settings normalizer copies only those, so an
    advertised choice with no enumerable options is the one way a spec reaches the build unflattened. This is the
    placement-mode defect's shape -- a control the panel draws and the server drops -- pinned for the library.
    """
    label, options = pdc.CHOICE_SPECS['conformation_library']
    assert label == 'Detergent conformation library'
    assert options == (), 'the spec is validated in validate_payload, not against a fixed list'
    assert pdc.DEFAULTS['conformation_library'] is None, 'the default is the one rigid conformation'
    assert 'conformation_library' in dict(pdc.PROTOCOL.choice_specs())

    spec = {'runs': ['b920391735dd'], 'size': 8, 'seed': 3}
    settings = pdc.settings_from({'seed': 1, 'conformation_library': spec})
    assert settings['conformation_library'] == spec


def test_the_payload_normalises_the_library_and_answers_none_when_absent():
    accepted = pdc.validate_payload({'seed': 1, 'conformation_library': {'runs': [' b920391735dd '], 'size': 4}})
    assert accepted['conformation_library'] == {'mode': 'build', 'runs': ['b920391735dd'], 'size': 4, 'seed': 0}
    assert pdc.validate_payload({'seed': 1})['conformation_library'] is None

    key, digest = 'a' * 16, 'b' * 64
    reference = pdc.validate_payload({'seed': 1, 'conformation_library': {'key': key, 'sha256': digest}})
    assert reference['conformation_library'] == {'mode': 'reference', 'key': key, 'sha256': digest}


def test_the_payload_refuses_a_library_spec_it_cannot_read():
    """A spec is one of two shapes, and every malformed one is named rather than silently defaulted.

    The old behaviour was the dangerous one: an unrecognised shape would have reached the settings as an opaque value
    the build then ignored, so a reader would get one rigid conformation while the panel said the library was chosen.
    """
    key, digest = 'a' * 16, 'b' * 64
    cases = [
        'not an object',
        {},
        {'runs': []},
        {'runs': ['b920391735dd'], 'size': 0},
        {'runs': ['b920391735dd'], 'size': 'lots'},
        {'runs': ['b920391735dd'], 'key': key, 'sha256': digest},
        {'key': 'not-hex', 'sha256': digest},
        {'sha256': digest},
        {'key': key},
    ]
    for spec in cases:
        with pytest.raises(ValueError):
            pdc.validate_payload({'seed': 1, 'conformation_library': spec})

