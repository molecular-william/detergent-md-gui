"""What decides an analysis result is what its signature hashes.

A hand-written list of module files stood in the signature and had drifted: `bonded_terms`, `consistency`,
`mapping_consistency`, `layout` and `sugar_ensemble` were not in it, so fixing the overlap metric changed no
signature — re-queuing the same analysis returned the completed task, and the panel went on showing numbers the
code on disk would no longer produce. Walking the packages cannot drift from the code they describe.
"""
import hashlib
import json

from dashboard import files
from dashboard.execution.coordination.analysis_coordinator import code_fingerprint_files


def signature_hash(entries):
    """The coordinator's own construction, over a list of `(relative name, path)`."""
    return hashlib.sha256(json.dumps([(name, files.sha256(path)) for name, path in entries],
                                     sort_keys=True).encode()).hexdigest()


def test_every_module_an_analysis_reads_is_covered():
    names = {name for name, _ in code_fingerprint_files()}
    for expected in ('analysis/worker.py', 'analysis/runs/bonded_terms.py', 'analysis/runs/consistency.py',
                     'analysis/runs/mapping_consistency.py', 'analysis/runs/layout.py',
                     'analysis/sugar_ensemble.py', 'analysis/validation/geometry.py',
                     'models/sugars/topology.py', 'models/mappings/exports.py'):
        assert expected in names, expected


def test_the_names_are_unique_and_relative_to_the_dashboard_package():
    names = [name for name, _ in code_fingerprint_files()]
    assert len(names) == len(set(names)), 'two modules sharing a basename would collide'
    assert all(name.endswith('.py') and not name.startswith('/') for name in names)


def test_a_presentation_change_is_not_an_analysis_change():
    """Templates, client code and the run executor do not decide an analysis number."""
    names = {name for name, _ in code_fingerprint_files()}
    assert not any(name.startswith(('web/', 'static/', 'execution/')) for name in names)


def test_editing_a_covered_module_moves_the_signature(tmp_path):
    """The defect behaviourally: the overlap metric changed and the signature did not."""
    entries = code_fingerprint_files()
    before = signature_hash(entries)
    edited = []
    for name, path in entries:
        copy = tmp_path / name.replace('/', '__')
        copy.write_text(path.read_text() + ('\n# an edit\n' if name == 'analysis/runs/bonded_terms.py' else ''))
        edited.append((name, copy))
    assert signature_hash(edited) != before
