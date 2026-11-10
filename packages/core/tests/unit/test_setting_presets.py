"""Named stage-setting presets: the store refuses what the queue would drop, and keeps one default per type.

A preset is stored as the run type's own `normalize_settings` answer, so what it holds is what a run would
use rather than a second dialect. The refusal matters more than the storage: the queue keeps only advertised
keys, so a preset carrying anything else would be a value the run silently ignores.
"""
import json

import pytest
from dashboard.models import setting_presets


def saved(paths, **overrides):
    payload = {'name': 'Short AA', 'run_type': 'aa_only', 'settings': {'aa_production_ps': 500}}
    payload.update(overrides)
    return setting_presets.create(paths, **payload)


def test_a_preset_is_the_run_types_normalized_settings(isolated_workspace):
    """Values the adapter accepts are stored with the rest of that run type's vocabulary, and nothing else."""
    preset = saved(isolated_workspace, settings={'aa_production_ps': 500, 'temperature_k': 305})

    assert preset['settings']['aa_production_ps'] == 500
    assert preset['settings']['temperature_k'] == 305
    # Completed by the adapter, not restated here: a stored preset is the settings a run would record.
    assert preset['settings']['aa_nvt_ps'] > 0
    assert 'cg_production_ps' not in preset['settings']
    assert preset['id'] and preset['created_at']
    document = json.loads((isolated_workspace.workspace / 'setting-presets.json').read_text())
    assert document['presets'] == [preset] and document['defaults'] == {}


def test_a_setting_the_run_type_does_not_advertise_is_refused(isolated_workspace):
    """The queue would drop it without a word; a preset names it, so it is an error rather than a no-op."""
    with pytest.raises(ValueError, match='cg_production_ps'):
        saved(isolated_workspace, settings={'cg_production_ps': 10})
    with pytest.raises(ValueError, match='nonsense'):
        saved(isolated_workspace, settings={'nonsense': 1})


def test_an_out_of_range_value_is_refused(isolated_workspace):
    with pytest.raises(ValueError):
        saved(isolated_workspace, settings={'aa_production_ps': 0})


def test_a_duplicate_name_is_refused_within_a_run_type_only(isolated_workspace):
    first = saved(isolated_workspace)
    with pytest.raises(setting_presets.DuplicatePreset):
        saved(isolated_workspace, name='  short   aa ')  # names compare without case or extra space
    cg = saved(isolated_workspace, name='Short AA', run_type='cg',
               settings={'cg_production_ps': 10000})
    assert {first['id'], cg['id']} <= {preset['id'] for preset in setting_presets.load(isolated_workspace)['presets']}


def test_one_default_per_run_type_and_it_moves_with_the_marker(isolated_workspace):
    first = saved(isolated_workspace)
    second = saved(isolated_workspace, name='Long AA')

    assert setting_presets.for_run_type(isolated_workspace, 'aa_only')['default'] is None
    setting_presets.update(isolated_workspace, first['id'], is_default=True)
    listed = setting_presets.for_run_type(isolated_workspace, 'aa_only')
    assert listed['default'] == first['id']
    assert [preset['is_default'] for preset in listed['presets']] == [True, False]

    setting_presets.update(isolated_workspace, second['id'], is_default=True)
    listed = setting_presets.for_run_type(isolated_workspace, 'aa_only')
    assert listed['default'] == second['id']
    assert [preset['is_default'] for preset in listed['presets']] == [False, True]
    # A run type with no preset still answers with no default rather than borrowing another type's.
    assert setting_presets.for_run_type(isolated_workspace, 'pdc')['default'] is None


def test_deleting_the_default_clears_it_with_the_preset(isolated_workspace):
    preset = saved(isolated_workspace)
    setting_presets.update(isolated_workspace, preset['id'], is_default=True)

    assert setting_presets.delete(isolated_workspace, preset['id']) == preset['id']

    listed = setting_presets.for_run_type(isolated_workspace, 'aa_only')
    assert listed == {'presets': [], 'default': None}
    assert setting_presets.load(isolated_workspace)['defaults'] == {}


def test_a_rename_is_refused_when_it_would_duplicate_another_name(isolated_workspace):
    first = saved(isolated_workspace)
    second = saved(isolated_workspace, name='Long AA')

    with pytest.raises(setting_presets.DuplicatePreset):
        setting_presets.update(isolated_workspace, second['id'], name=first['name'])
    renamed = setting_presets.update(isolated_workspace, second['id'], name='Longer AA')[0]
    assert renamed['name'] == 'Longer AA'


def test_an_unknown_run_type_or_preset_is_refused_by_name(isolated_workspace):
    with pytest.raises(setting_presets.UnknownRunType):
        setting_presets.for_run_type(isolated_workspace, 'no-such-type')
    with pytest.raises(setting_presets.UnknownPreset):
        setting_presets.delete(isolated_workspace, 'nosuchpreset')
    with pytest.raises(ValueError):
        saved(isolated_workspace, name='   ')


def test_an_unreadable_store_reads_as_no_presets(isolated_workspace):
    """A broken preference file must not take the form down; the warning is why it is ignored, not replaced."""
    path = isolated_workspace.workspace / 'setting-presets.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{not json')

    assert setting_presets.for_run_type(isolated_workspace, 'aa_only') == {'presets': [], 'default': None}
