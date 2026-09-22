# Chemically Informed Bonded Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make bonded-function metadata accurate and make automatic bonded-state generation use chemically and topologically matched reference bonds, angles, and dihedrals with deterministic provenance.

**Architecture:** Keep the existing bonded model and generator boundaries. Add a structured function specification in `bonded.py`, extend the read-only reference index and deterministic matcher in `bonded_generation.py`, and expose additive metadata/provenance fields to the existing API/UI. Reference fitting remains outside automatic generation.

**Tech Stack:** Python 3, pytest, vanilla JavaScript frontend, GROMACS ITP text format, GitNexus CLI.

**Spec:** `docs/superpowers/specs/2026-09-22-chemically-informed-bonded-generation-design.md`

## Global Constraints

- Preserve `reference_bond_index(...)["bonds"]` compatibility and existing term fields.
- Do not mutate files under `references/`.
- Do not generate dihedrals without a matching reference term.
- Keep constraints, virtual sites, exclusions, and mapping persistence behavior unchanged.
- Keep automatic generation deterministic and local; do not invoke Fast Forward.
- Reject malformed/non-finite reference values with diagnostics instead of aborting indexing.
- Run GitNexus impact before symbol edits and `detect-changes` before committing.

---

### Task 1: Make bonded-function metadata authoritative and accurate

**Files:**
- Modify: `dashboard/models/bonded.py:13-35`
- Modify: `dashboard/web/static/js/bonded.js:1-20`
- Test: `tests/dashboard/unit/test_bonded_states.py`

**Interfaces:**
- Produces `FUNCTION_SPECS`, derived `FUNCTION_PARAMETER_LABELS`/`FUNCTIONS`, and `_function_options()` records with `description` and `parameter_labels`.
- Preserves existing `parse_interactions()` fields and validation behavior.

- [ ] **Step 1: Write failing metadata tests**

```python
def test_function_metadata_has_correct_units_and_descriptions():
    from dashboard.models.bonded import FUNCTION_SPECS, FUNCTION_PARAMETER_LABELS

    assert FUNCTION_SPECS['angles'][2]['description'] == 'GROMOS-96 cosine'
    assert FUNCTION_PARAMETER_LABELS['angles'][2][1] == 'force (kJ mol^-1)'
    assert FUNCTION_PARAMETER_LABELS['angles'][10][1] == 'force (kJ mol^-1)'
    assert FUNCTION_PARAMETER_LABELS['dihedrals'][1][1] == 'force (kJ mol^-1)'
    assert FUNCTION_PARAMETER_LABELS['dihedrals'][9][1] == 'force (kJ mol^-1)'
    assert FUNCTION_PARAMETER_LABELS['dihedrals'][2][1] == 'force (kJ mol^-1 rad^-2)'

    row = next(row for row in parse_interactions('[ angles ]\n1 2 3 2 150 50\n') if row['kind'] == 'angles')
    assert row['function_options'][1]['description'] == 'GROMOS-96 cosine'
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/dashboard/unit/test_bonded_states.py::test_function_metadata_has_correct_units_and_descriptions -q`

Expected: FAIL because function descriptions are absent and the current units are incorrect.

- [ ] **Step 3: Implement the shared specification**

Define each function once, for example:

```python
FUNCTION_SPECS = {
    'angles': {
        1: {'description': 'Harmonic', 'parameters': ['angle (deg)', 'force (kJ mol^-1 rad^-2)']},
        2: {'description': 'GROMOS-96 cosine', 'parameters': ['angle (deg)', 'force (kJ mol^-1)']},
        10: {'description': 'Restricted bending', 'parameters': ['angle (deg)', 'force (kJ mol^-1)']},
    },
}
FUNCTION_PARAMETER_LABELS = {kind: {fn: spec['parameters'] for fn, spec in choices.items()} for kind, choices in FUNCTION_SPECS.items()}
FUNCTIONS = {kind: {fn: len(spec['parameters']) for fn, spec in choices.items()} for kind, choices in FUNCTION_SPECS.items()}
```

Update `_function_options()` to return `description` and keep `parameter_labels`. Correct all units from the spec. Update the JavaScript fallback object and normalized options to carry `description` so legacy API responses render the same metadata.

- [ ] **Step 4: Run metadata and existing parser tests**

Run: `pytest tests/dashboard/unit/test_bonded_states.py -q`

Expected: PASS, including the existing parameter-label assertions updated only where the corrected units require it.

- [ ] **Step 5: Commit the metadata change**

```bash
git add dashboard/models/bonded.py dashboard/web/static/js/bonded.js tests/dashboard/unit/test_bonded_states.py
git commit -m "fix: centralize bonded function metadata"
```

### Task 2: Extend the reference index to all bonded terms

**Files:**
- Modify: `dashboard/models/bonded_generation.py:20-118`
- Test: `tests/dashboard/unit/test_bonded_generation.py`

**Interfaces:**
- `reference_bond_index(project_root)` returns version 2 with additive `angles` and `dihedrals` maps.
- `_parse_reference()` returns normalized records for all supported sections and diagnostics for malformed rows.

- [ ] **Step 1: Write failing parser/index tests**

```python
def test_reference_index_normalizes_angles_and_dihedrals(tmp_path):
    root = tmp_path / 'references'; root.mkdir()
    (root / 'ddm.itp').write_text(_itp_with_terms())
    index = bonded_generation.reference_bond_index(tmp_path)

    assert index['version'] == 2
    assert index['angles']['C1|C2|C1'][0]['parameters'] == [150.0, 50.0]
    assert index['dihedrals']['C1|C2|C3|C4'][0]['parameters'] == [110.0, 8.0, 1.0]
    assert index['angles']['C1|C2|C1'][0]['references'][0]['line'] > 0

def test_reference_index_reports_nonfinite_and_short_rows(tmp_path):
    root = tmp_path / 'references'; root.mkdir()
    (root / 'bad.itp').write_text('[ atoms ]\n1 C1\n2 C1\n[ angles ]\n1 2 3 2 nan 50\n')
    index = bonded_generation.reference_bond_index(tmp_path)
    assert index['diagnostics']
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/dashboard/unit/test_bonded_generation.py -q`

Expected: FAIL because only bonds are indexed and the payload is version 1.

- [ ] **Step 3: Implement normalized section parsing**

Add section widths and a shared numeric parser. Parse the first `width` atom indices, the function, and the exact function parameter count from `FUNCTIONS`. Resolve atom types from `[atoms]`; reject missing types, unsupported functions, short rows, and non-finite parameters with a diagnostic. Add canonical key helpers:

```python
def _sequence_key(types, kind):
    forward = tuple(str(value) for value in types)
    reverse = tuple(reversed(forward))
    if kind == 'bonds' or kind == 'angles':
        return '|'.join(min(forward, reverse))
    return '|'.join(min(forward, reverse))
```

Retain bond output shape and build the same signature records for angles and dihedrals. Set `version: 2`; include all source hashes and diagnostics in the index hash input.

- [ ] **Step 4: Implement deterministic source ranking and consensus ordering**

Rank paths using stable string rules (`MAD Database/<molecule>` or a path component equal to the molecule-specific stem before generic Martini paths), then sort candidates by descending rank/count and ascending source path/line. Keep all signatures in each keyed list so ambiguity is inspectable.

- [ ] **Step 5: Run parser/index tests and compatibility tests**

Run: `pytest tests/dashboard/unit/test_bonded_generation.py -q`

Expected: PASS, including the existing version/shape assertions updated to expect version 2 and legacy bond records unchanged.

- [ ] **Step 6: Commit the reference-index change**

```bash
git add dashboard/models/bonded_generation.py tests/dashboard/unit/test_bonded_generation.py
git commit -m "feat: index reference angles and dihedrals"
```

### Task 3: Generate reference-informed bonds, angles, dihedrals, and provenance

**Files:**
- Modify: `dashboard/models/bonded_generation.py:220-365`
- Test: `tests/dashboard/unit/test_bonded_generation.py`

**Interfaces:**
- `generate(mapping, structure, project_root)` keeps its return shape and adds reference-informed interactions and provenance fields.
- New private helpers select signatures by canonical key and add graph-derived angles/dihedrals deterministically.

- [ ] **Step 1: Write failing generation tests**

```python
def test_generate_uses_reference_angles_and_dihedrals(tmp_path):
    root = tmp_path / 'references'; root.mkdir()
    (root / 'ref.itp').write_text(_itp_with_terms())
    result = bonded_generation.generate(_mapping_four_beads(), _structure_four_beads(), tmp_path)

    angle = next(term for term in result['interactions'] if term['kind'] == 'angles')
    assert angle['function'] == '2'
    assert angle['parameters'] == ['150', '50']
    assert angle['provenance']['fallback'] is False
    assert any(term['kind'] == 'dihedrals' for term in result['interactions'])
    assert result['provenance']['algorithm']['version'] == '2'

def test_generate_does_not_invent_dihedrals_without_reference(tmp_path):
    (tmp_path / 'references').mkdir()
    result = bonded_generation.generate(_mapping_four_beads(), _structure_four_beads(), tmp_path)
    assert not any(term['kind'] == 'dihedrals' for term in result['interactions'])

def test_generate_records_ambiguous_reference_signatures(tmp_path):
    root = tmp_path / 'references'; root.mkdir()
    (root / 'a.itp').write_text(_itp_with_angle(150, 50))
    (root / 'b.itp').write_text(_itp_with_angle(140, 50))
    result = bonded_generation.generate(_mapping_three_beads(), _structure_three_beads(), tmp_path)
    angle = next(term for term in result['interactions'] if term['kind'] == 'angles')
    assert angle['provenance']['ambiguity']
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/dashboard/unit/test_bonded_generation.py -q`

Expected: FAIL because angles are always function 1 geometry terms and dihedrals are absent.

- [ ] **Step 3: Implement deterministic reference selection**

Add `_select_reference(index, kind, types, mapping_name)` that looks up the canonical key, ranks candidates by source rank/count/path/line, returns the selected record plus an ambiguity list when more than one signature exists, and never mutates the index. Use bead type and size in the generated context record; keep type-key lookup as the compatibility baseline when references lack size metadata.

- [ ] **Step 4: Implement graph term generation**

For each physical edge, select a reference bond or use the existing geometry/5000 fallback. For each sorted neighbor pair around a central bead, select a reference angle or use `_angle()` with function 1 and the existing fallback force. For every sorted length-three graph path, select a reference dihedral and append it only when present. Avoid duplicate terms using `_canonical_term_key()`.

- [ ] **Step 5: Add provenance and diagnostics**

Set per-term provenance to include `fallback`, `references`, `confidence`, `ambiguity`, and the matched canonical key. Set the overall algorithm name/version to `reference-bond-angle-dihedral-consensus`/`2`, retain the reference index hash, and list all selected reference paths. Add a diagnostic for each fallback and each ambiguous consensus.

- [ ] **Step 6: Run generator and topology tests**

Run: `pytest tests/dashboard/unit/test_bonded_generation.py -q`

Expected: PASS with reference terms preserved, fallback angles still generated, virtual sites and constraints retained, and no unsupported dihedral invented.

- [ ] **Step 7: Commit the generation change**

```bash
git add dashboard/models/bonded_generation.py tests/dashboard/unit/test_bonded_generation.py
git commit -m "feat: generate bonded terms from reference topology"
```

### Task 4: Verify API/UI compatibility and repository graph safety

**Files:**
- Modify: `dashboard/web/static/js/bonded.js` only if metadata rendering needs an additive description field.
- Test: `tests/dashboard/unit/test_bonded_states.py`, existing dashboard API/browser suites.

**Interfaces:**
- Existing bonded-state endpoints continue accepting and returning the same topology and interaction fields.
- Function options expose descriptions without changing existing selection values.

- [ ] **Step 1: Run focused backend and API tests**

Run: `pytest tests/dashboard/unit/test_bonded_states.py tests/dashboard/unit/test_bonded_generation.py tests/dashboard/integration -q`

Expected: PASS; unrelated legacy workflow failures remain separately identified if present.

- [ ] **Step 2: Run frontend/browser validation**

Run the repository’s bonded workspace browser command from `docs/PROJECT_GUIDE.md`; if no browser command is documented, run `npm test` from the dashboard frontend directory and record the exact command/output.

Expected: PASS with function descriptions rendered and no regression in interaction editing.

- [ ] **Step 3: Reindex and inspect GitNexus changes**

```bash
node .gitnexus/run.cjs analyze --index-only
node .gitnexus/run.cjs detect-changes --scope all --repo .
```

Expected: the change report is complete (`partial: false`, `truncated: false`) and has no unexpected high-risk caller/process changes. Re-run if the report is partial or truncated.

- [ ] **Step 4: Run final verification**

```bash
python -m compileall dashboard/models dashboard/web
git diff --check HEAD~3..HEAD
git status --short
```

Expected: compile succeeds, diff check is clean, and only the intended commits/files are present.

- [ ] **Step 5: Commit any final compatibility fix**

```bash
git add dashboard/web/static/js/bonded.js tests/dashboard/unit/test_bonded_states.py
git commit -m "test: verify bonded metadata compatibility"
```

