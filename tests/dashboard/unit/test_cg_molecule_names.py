from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = PROJECT_ROOT / 'dashboard/execution/scripts'


def test_run_local_cg_helpers_use_molecule_naming_environment():
    refine = (SCRIPTS / 'refine_bonded.py').read_text()
    mapping = (SCRIPTS / 'sugar_mapping.py').read_text()
    diagnostics = (SCRIPTS / 'distance_diagnostics.py').read_text()

    assert "os.environ.get('FINAL_ITP', 'DDM.itp')" in refine
    assert "f'{path.stem}_ff_inter.itp'" in refine
    assert 'if not preserved.exists()' in refine
    assert "os.environ.get('MOLECULE_TYPE', 'DDM')" in mapping
    assert "os.environ.get('INITIAL_ITP', 'DDM_initial.itp')" in diagnostics
    assert "os.environ.get('MOLECULE_TYPE', 'DDM')" in diagnostics
