"""The ring bundle's Python helpers must import where the bundle lands.

The export wrote the sugars facade into the bundle as `carbohydrates.py`: a file whose first
statements are relative imports naming modules the bundle did not carry, in a file with no
package around it. Anything that tried to use the bundled helper failed at import, and the
filename named a module that no longer exists.
"""
import subprocess
import sys

from dashboard.models import mappings
from dashboard.models.mappings import exports as mapping_exports


def bundle_files(tmp_path):
    """A ring mapping's export, written out the way a download lands it."""
    files = mapping_exports.export_files(mappings.automatic_candidate(mappings.molecule(), 'DDM'))
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return files


def test_the_bundle_ships_the_sugar_package_whole(tmp_path):
    files = bundle_files(tmp_path)
    assert set(files) >= {'sugar_mapping.py', 'prepare_ring_constraints.py', 'sugars/__init__.py'}
    assert not any('/' not in name and name == 'carbohydrates.py' for name in files), \
        'the facade is not shipped under a name that no longer exists'


def test_the_bundled_sugar_package_imports_where_it_lands(tmp_path):
    """A clean interpreter with only the bundle on the path, as the bundle ships it."""
    bundle_files(tmp_path)
    result = subprocess.run([sys.executable, '-c', 'import sugars; print(sugars.__name__)'], cwd=tmp_path,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr or result.stdout


def test_every_bundled_python_file_compiles(tmp_path):
    """The two scripts are run, not imported: they read a 1_AA-reference directory as they
    start, so compiling is what can be checked here -- and what the facade they replaced
    failed was importing at all, which the test above pins.
    """
    files = bundle_files(tmp_path)
    sources = [name for name in files if name.endswith('.py')]
    assert sources
    result = subprocess.run([sys.executable, '-m', 'py_compile', *sources], cwd=tmp_path,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr or result.stdout
