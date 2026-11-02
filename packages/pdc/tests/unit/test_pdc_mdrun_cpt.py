"""`mdrun_cpt` is the pdc run's own checkpoint cadence: kept when named, absent when not.

The setting has no default on purpose. A run that names none must leave GROMACS' own 15 minutes in force and write no
flag, so `settings_from` keeps a supplied value and `DEFAULTS` does not invent one.
"""
import json

import pytest
from detergent_pdc.execution.adapters import pdc

from tests.harness.pdc_fixtures import prepared_run


def test_the_cadence_is_a_bounded_integer_with_no_default():
    assert pdc.SETTING_SPECS['mdrun_cpt'] == ('Checkpoint interval (minutes)', 1, 100000)
    assert 'mdrun_cpt' not in pdc.DEFAULTS
    assert 'mdrun_cpt' not in pdc.settings_from({'seed': 20261102})
    assert pdc.settings_from({'mdrun_cpt': '30'})['mdrun_cpt'] == 30
    with pytest.raises(ValueError, match='mdrun_cpt must be an integer'):
        pdc.normalize_settings({'mdrun_cpt': 1.5})
    with pytest.raises(ValueError, match='between 1 and 100000'):
        pdc.normalize_settings({'mdrun_cpt': 0})


def test_a_prepared_run_records_the_cadence_it_was_given(tmp_path):
    run = prepared_run(tmp_path, settings={'mdrun_cpt': 30})
    asserted = json.loads((run / 'manifest.json').read_text())['settings']
    assert asserted['mdrun_cpt'] == 30 and isinstance(asserted['mdrun_cpt'], int)
    without = prepared_run(tmp_path, directory='plain')
    assert 'mdrun_cpt' not in json.loads((without / 'manifest.json').read_text())['settings']
