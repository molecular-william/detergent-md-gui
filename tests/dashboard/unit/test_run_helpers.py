"""Modules copied into a run directory must keep the names that run uses.

Both failures this guards are silent until a real run reaches the stage, and
neither shows up in an import check or a unit test of the adapter:

- The adapter copied each helper under `Path(module.__file__).name`. After the
  layout move those names became `references.py` and `aa.py`, while the
  generated stage scripts invoke `../common/aa_references.py` and the copied
  publication helper imports `aa_molecules`. The AA neutralization and
  reference-publication stages would have failed on a missing file.
- A copied helper has no package beside it, so every package import it makes
  has to sit inside its own ImportError fallback.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

from dashboard.execution.adapters import aa


def test_every_helper_the_stage_scripts_invoke_is_copied_under_that_name():
    invoked = set(re.findall(r'common/([A-Za-z_][A-Za-z0-9_]*\.py)', Path(aa.__file__).read_text()))
    copied = {name for name, _ in aa.RUN_HELPERS}
    assert invoked, 'the stage scripts must invoke at least one run-local helper'
    missing = sorted(invoked - copied)
    assert not missing, f'the stage scripts invoke helpers the run directory never gets: {missing}'


def test_copied_helpers_import_standalone(tmp_path):
    """The run directory has no package, so the copies must not need one."""
    for name, module in aa.RUN_HELPERS:
        shutil.copy2(module.__file__, tmp_path / name)
    imports = '; '.join(f'import {name[:-3]}' for name, _ in aa.RUN_HELPERS)
    result = subprocess.run([sys.executable, '-c', imports], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
