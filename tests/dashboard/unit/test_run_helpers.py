"""An AA run executes the repository's helper modules; it carries no Python of its own.

The run used to copy three modules into `stages/common/` and the generated stage scripts invoked
`../common/aa_references.py`. A copy drifts from the module it was made from, and the run could not say which code it
had actually run. The modules now run as package modules through the application interpreter
(`"$PYTHON" -m dashboard...`), and the manifest records each one's repository path and digest, so a changed helper
refuses the stage instead of silently running other code.
"""
import json

import pytest

from dashboard import files
from dashboard.execution import run_scripts
from dashboard.execution.adapters import aa
from dashboard.models.molecules import aa as aa_molecules
from tests.dashboard.support import PROJECT_ROOT

#: The code an AA stage executes, by the name the manifest gives it. Pinned here rather than read from the adapter,
#: because these paths are the run contract: a helper that moves without this list changing is a run that cannot say
#: what ran.
MODULES = {'aa_references': 'dashboard/analysis/runs/references.py',
           'aa_molecules': 'dashboard/models/molecules/aa.py',
           'files': 'dashboard/files.py'}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(aa, 'tool_metadata', lambda: {})
    monkeypatch.setattr(aa, 'gromacs_flavour', lambda *arguments, **keywords: 'mpi')
    molecules = PROJECT_ROOT/'molecules'
    selected = aa_molecules.selection(molecules, 'DDM', run_type='aa_only')
    aa.prepare_run(tmp_path, molecules, selected,
                   {'aa_nvt_ps': 1, 'aa_npt_ps': 1, 'aa_production_ps': 2, 'output_interval_ps': 1, 'box_nm': 4.0})
    return tmp_path


def test_a_prepared_run_holds_no_python_and_names_the_modules_it_executes(prepared):
    for tree in ('stages', 'inputs'):
        assert not [path for path in (prepared/tree).rglob('*.py')], f'{tree}/ carries a Python file'
    manifest = json.loads((prepared/'manifest.json').read_text())
    recorded = manifest['python_modules']
    assert {name: entry['path'] for name, entry in recorded.items()} == MODULES
    for name, entry in recorded.items():
        assert entry['sha256'] == files.sha256(PROJECT_ROOT/entry['path'])
        assert run_scripts.verify_one(name, entry, root=PROJECT_ROOT) == PROJECT_ROOT/entry['path']
    # The generated stage scripts execute the module where it lives rather than a copy beside them.
    text = '\n'.join(path.read_text() for path in (prepared/'stages').rglob('run.sh'))
    assert ' -m dashboard.analysis.runs.references ' in text
    assert 'common/aa_references.py' not in text


def test_a_module_changed_after_prepare_refuses_the_stage(tmp_path):
    module = tmp_path/'helper.py'
    module.write_text('x = 1\n')
    declared = {'path': 'helper.py', 'sha256': files.sha256(module)}
    assert run_scripts.verify_one('files', declared, root=tmp_path) == module

    module.write_text('x = 2\n')
    with pytest.raises(ValueError, match='the stage script for files changed since this run was prepared'):
        run_scripts.verify_one('files', declared, root=tmp_path)
