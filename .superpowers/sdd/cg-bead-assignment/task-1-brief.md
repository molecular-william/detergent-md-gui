## Task 1: Read-only molecule context

**Files:** Modify `dashboard/models/aa_molecules.py`; create `dashboard/models/mapping_context.py`, `tests/dashboard/mapping_fixtures.py`, `tests/dashboard/unit/test_mapping_context.py`.

**Interfaces:** Produce `build_context(root, molecule_id)` with the shared contract. Extract common read/parse operations from AA inspection without changing AA launch eligibility or its existing metadata workflow.

- [ ] Add the fixture above and this failing regression:

```python
from dashboard.models.mapping_context import build_context
from tests.dashboard.mapping_fixtures import write_aa_fixture


def test_context_keeps_atom_ids_and_source_changes(tmp_path):
    folder = write_aa_fixture(tmp_path)
    before = build_context(tmp_path, "Fixture")
    assert [a["id"] for a in before["atoms"]] == [1, 2, 3, 4, 5]
    assert [a["id"] for a in before["atoms"] if a["heavy"]] == [1, 2, 3, 4]
    assert before["capabilities"]["manual"]["available"]
    topology = folder / "molecule.itp"
    topology.write_text(topology.read_text() + "; changed source\n")
    after = build_context(tmp_path, "Fixture")
    assert before["snapshot"] != after["snapshot"]
```

- [ ] Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_mapping_context.py -q`; confirm missing context behavior fails.
- [ ] Implement byte reads, topology/include validation, coordinate normalization and stable atom identity. Build connected/disconnected AA graph from recorded bonds/constraints without inventing geometry-based bonds. Keep isolated atoms visible.

```python
import hashlib
import json


def canonical_sha256(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()
```

  Define this helper in `mapping_context.py`; use it for snapshot and atom-order keys. Snapshot file hashes come from the same bytes parsed, not later rereads.
- [ ] Add cases for nested includes, PDB/GRO units, missing metadata with no write, halogens, hydrogen isotopes, unknown elements, missing masses, disconnected input, traversal, symlinks and ambiguous pairs. Unknown chemical identity keeps manual IDs available but disables chemical suggestions; invalid coordinate/topology correspondence fails context loading.
- [ ] Run context tests and existing `test_aa_molecules.py`, `test_molecule_discovery.py`, and `test_aa_dependencies.py`. Review source-write behavior before checkpointing.

