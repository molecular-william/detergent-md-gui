# Molecule-Scoped CG Bead Assignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users select a valid AA molecule, group heavy atoms on an always-visible 2D structure, inspect reference-backed suggestions, preview one deterministic automatic candidate, and save immutable molecule-bound mappings.

**Architecture:** Reuse molecule discovery and the existing Python/Flask service. Make the molecule context explicit throughout mapping validation, depiction, persistence, and exports; extract reference matching and client editing into focused modules. Preserve legacy DDM reads and hashes while requiring explicit source binding for new molecule-scoped use.

**Tech Stack:** Python, Flask, JSON files, RDKit, installed openpyxl and CGsmiles, native JavaScript ES modules, SVG, pytest, Playwright/Chrome. No frontend framework or additional service.

**Spec:** [Approved design](../specs/2026-09-18-cg-bead-assignment-design.md).

## Global Constraints

- “No automatic scientific validation or force-field approval.”
- “No browser-side chemistry engine or new frontend framework.”
- “No long simulation runs during implementation.” No simulation launches are needed for this plan.
- “No mutation or cleanup of canonical molecule inputs or simulation outputs.”
- “No automatic promotion of a generated candidate to approved status.”
- “No lasso selection, ranked multi-candidate campaigns, or arbitrary custom bead types in the first increment.”
- “Virtual sites own no AA atoms.”
- “A preview has no persistence side effect. A save creates a new candidate file.”
- “Incomplete drafts remain inspectable but cannot be approved, exported, or selected for simulation.”
- Candidate identity includes molecule ID, source hashes, atom order, bead assignments, rings, and connections.
- Reference precedence: specialized sugar definitions, small-molecule examples, M3-Bible guidance. Apply precedence only to chemically applicable matches.
- Use the configured `dashboard.paths` project/workspace roots; never hard-code the active research workspace in tests.
- Run all commands from the repository root using `dashboard/.venv/bin/python`.
- No Git metadata exists at planning time. At execution, use an existing isolated checkout/worktree if available. Otherwise save a source-only rollback copy outside the repository before edits; do not initialize Git, move runtime stores, or copy/delete simulation data. Commit each verified task only if Git actually exists then.

## Evidence and design details resolved for implementation

Read `AGENTS.md`, `docs/PROJECT_GUIDE.md`, `docs/DDM_CALIBRATION.md`, and the spec before execution.

- `aa_molecules.discover()` already selects ITP/PDB or ITP/GRO pairs. `topology_tree()` resolves safe local includes. `inspect()` may create missing metadata: mapping context must reuse read/validation logic without that write side effect.
- `mappings.molecule()`, candidate validation, automatic generation, and exports currently default to DDM. `depiction._base()` reads DDM even though it accepts source text. Remove these hidden dependencies for schema 3 callers.
- `mappings.check_schema()` currently rejects zero beads. Empty manual drafts must become valid editor documents.
- `carbohydrates.py` already implements sugar recognition, canonical assignments, coordinates, and topology. Reuse it; do not create a second sugar algorithm.
- `coordinator.py` still computes a legacy mapping hash inline for bonded reuse. Replace that comparison with `mappings.mapping_identity()` when integrating schema 3.
- `model_registry.py` already stores reference metadata and hashes. Reuse its integrity conventions; the suggestion index is a read-only derived view, not a second writable registry.
- M3-Bible contains `src/MartiniCGSmilesDB_v6.xlsx`, sheet `All`, columns `Name`, `MOLTAG`, `SMILES`, `CGSmiles`. Its PDF is presentation output, not the parser input.
- M3-Small-Molecules contains `models/martini_v3.0.0_small_molecules_v1.itp`, `models/SMILES/`, AA ITP/PDB files, and `models/mapping-cgbuilder/oplsaa-LigParGen/<MOLTAG>/` NDX/MAP files. CG ITPs alone do not define AA fragment membership.
- `references/martini_v3.0.0_sugars_v2.itp` supplies sugar bead types, masses, constraints, exclusions, and virtual-site parents. Pair these definitions with recognized sugar mappings; never infer atom assignments from bead names alone.
- RDKit, openpyxl, pandas, and CGsmiles are installed in the dashboard interpreter at planning time. Use openpyxl directly for XLSX; avoid a new pandas dependency in application code.
- Approved HTML pages are layout references, not chemical fixtures. Their illustrative DDM graph, counts, types, and percentage confidence must not enter production. Render actual selected molecule data; confidence uses evidence categories, not uncalibrated percentages.

## Implementation decisions within approved scope

1. Use Å for context `xyz`, matching existing mapping helpers; export GRO in nm. `display_xy` is SVG space and never enters physical calculations.
2. Preserve legacy hashes exactly. Schema 3 uses a versioned identity payload including the full molecule snapshot and existing identity fields. Exclude validation results, timestamps, display coordinates, and suggestion explanations. Retain name sensitivity in this increment to avoid an unrelated identity migration.
3. Treat a safe partial document separately from a complete mapping. Zero beads, uncovered atoms, blank type, and disconnected unfinished groups are saveable with findings. Duplicate ownership, unknown/hydrogen atom IDs, malformed fields, duplicate names, dangling parents, and nonfinite numbers cannot be persisted. Validation can describe these errors while the user edits.
4. Click, Shift-click, Enter, and Space toggle membership without clearing other selected atoms. Keep atom selection and three-bead parent selection as separate modes. Hydrogens are display-only.
5. A generic three-parent TC4 site has mass zero, function 1, equal parent weights, and no owned atoms. It does **not** automatically impose the carbohydrate 1.15 scaling or sugar constraints. Preserve those only for verified sugar architecture. Ring-likeness is advisory; numerical/site construction errors remain blocking.
6. Incomplete drafts have no download/export actions, including client JSON and SVG download. Internal diagram rendering remains available. Browser-local recovery and server save remain available.
7. Source-stale candidates remain inspectable through detail reads with explicit status, but never selectable for current-context reuse. Legacy candidates open in a separate inspection/import action. Re-save requires explicit current molecule confirmation and revalidation; no automatic rebinding or bonded-state migration.
8. Mapping capability is separate from AA/CG execution capability. Non-DDM mapping does not enable a new CG execution adapter. Existing DDM scientific gates remain enforced.

## File ownership

| Files | Responsibility |
| --- | --- |
| `dashboard/models/aa_molecules.py` | Reusable read-only input inspection; retain existing AA behavior |
| New `dashboard/models/mapping_context.py` | Source snapshot, atom graph, chemical-source alignment, capability flags |
| `dashboard/models/depiction.py` | Stable RDKit 2D scene and export rendering from explicit context |
| `dashboard/models/mappings.py` | Candidate schema, versioned identity, validation, persistence, context-aware exports |
| New `dashboard/models/mapping_references.py` | Read-only source adapters, verified fragment records, hashes and diagnostics |
| New `dashboard/models/mapping_suggestions.py` | Ranked bead suggestions and deterministic baseline preview |
| `dashboard/models/carbohydrates.py` | Existing sugar behavior plus explicit generic-site separation |
| `dashboard/web/routes/models.py`, `molecules.py` | Mapping HTTP contracts, errors and capability presentation |
| `dashboard/web/static/js/mappings.js` | Workspace controller, scoped data loads, local draft/preview lifecycle |
| New `dashboard/web/static/js/mapping-state.js` | Pure selection, grouping and dependency-aware edit operations |
| New `dashboard/web/static/js/mapping-diagram.js` | Persistent base SVG, hit targets, bead/site overlays, keyboard selection |
| `dashboard/web/templates/dashboard.html`, new `dashboard/web/static/mappings.css` | Approved workspace layout and accessible controls |
| `dashboard/web/static/js/new-run.js`, `bonded.js` | Molecule/source filtering and execution compatibility |
| `dashboard/models/draft_model.py`, `bonded_states.py`, `dashboard/execution/coordinator.py`, `ddm.py` | Reuse, preparation and immutable snapshot guards |
| `tests/dashboard/{unit,integration,browser}/` | Isolated regression proof |

Do not add abstract provider interfaces, a new database, background index jobs, or separate suggestion servers. Use functions and bounded content-keyed caches.

## Shared contracts and fixtures

`mapping_context.build_context(root: Path, molecule_id: str) -> dict` returns:

- `molecule_id`, `name`, `molecule_type`, `atoms`, `bonds`, `source_quality`, `capabilities`, `snapshot`.
- Atoms: `id`, `name`, `element` (nullable if not defensibly known), `heavy`, `xyz`, `display_xy`; preserve canonical ITP IDs. Do not identify chlorine as carbon or massless particles as hydrogen.
- Bonds: `a`, `b`, `order` (1 for display fallback), `order_source`, optional stereo annotation.
- Snapshot: `files` (relative path to SHA256), `atom_order_sha256`, `snapshot_sha256`. Hash actual bytes read; hash optional chemical sources used, topology includes and existing metadata. Do not create metadata while building context.
- Capability keys: `manual`, `automatic`, each with `available` and `reasons`. Unknown chemical order disables chemistry-specific matching, not manual graph editing.

`mappings.new_draft(context: dict, name: str) -> dict` creates an unsaved schema 3 document. `mappings.validate(data, structure=None, *, context=None) -> dict` retains legacy output fields and adds `issues[].severity`, `can_save`, `can_approve`, `can_export`, `can_reuse`. `mappings.require_usable(data, context, *, operation: str) -> None` enforces the corresponding gate for `approve`, `export`, or `reuse`.

`mapping_references.load_index(project_root: Path) -> dict` returns `records`, `sources`, `diagnostics`, `index_sha256`. A record has `fragment_id`, `source_rank`, `type`, `size`, `charge`, a verified fragment graph and attachment context, plus source paths/hashes/locators. Runtime graphs stay server-side; candidate provenance stores citations only.

`mapping_suggestions.suggest_bead(context, atom_ids: list[int], index) -> dict` returns `suggestions`, `warnings`; entries have `size`, `type`, `reason`, `confidence` (`exact-context`, `fragment-match`, or `heuristic`), and `references`.

`mapping_suggestions.generate_baseline(context, index) -> dict` returns `available`, `candidate`, `reasons`. No timestamp, UUID, or file write appears in preview generation. `mappings.ring_site_preview(data, context, parents: list[str]) -> dict` returns `bead`, optional verified sugar `ring`, and `warnings`.

Task 1 creates `tests/dashboard/mapping_fixtures.py` with the concrete fixture below, used by subsequent tests. Existing browser isolation remains in `conftest.py`.

```python
import json
from pathlib import Path


def write_aa_fixture(root: Path, molecule_id="Fixture") -> Path:
    folder = root / molecule_id
    folder.mkdir(parents=True)
    rows = [
        "[ moleculetype ]", "LIG 1", "[ atoms ]",
        "1 CT 1 LIG C1 1 0 12.011", "2 CT 1 LIG C2 2 0 12.011",
        "3 CT 1 LIG C3 3 0 12.011", "4 CT 1 LIG C4 4 0 12.011",
        "5 HC 1 LIG H1 5 0 1.008", "[ bonds ]",
        "1 2 1 0.15 1000", "2 3 1 0.15 1000",
        "3 4 1 0.15 1000", "1 5 1 0.10 1000",
    ]
    (folder / "molecule.itp").write_text("\n".join(rows) + "\n")
    gro = ["Fixture", "5"]
    for i, name in enumerate(("C1", "C2", "C3", "C4", "H1"), 1):
        gro.append(f"{1:5d}{'LIG':<5}{name:>5}{i:5d}"
                   f"{i * .1:8.3f}{0.:8.3f}{0.:8.3f}")
    (folder / "molecule.gro").write_text("\n".join(gro + ["0 0 0", ""]))
    (folder / "metadata.json").write_text(json.dumps({
        "name": molecule_id, "molecule_type": "LIG", "net_charge": 0,
        "force_field": "charmm36-jul2022.ff", "water_model": "tip3p",
    }))
    return folder
```

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

## Task 2: Stable chemical depiction with safe graph fallback

**Files:** Modify `mapping_context.py`, `depiction.py`; create `tests/dashboard/unit/test_mapping_depiction.py`.

**Interfaces:** `depiction.build_scene(context: dict) -> dict` supplies `base_svg`, `view_box`, atom `positions`, bond/stereo data. `depiction.render(data, *, context=None)` uses that scene; no candidate required to obtain a base scene. The optional argument preserves legacy DDM callers.

Keep dependency direction explicit: `build_context` assembles raw atom/bond/source data, calls the pure scene builder, then attaches `display_xy`. `build_scene` never calls `build_context` or `mappings.molecule()`. Move legacy context resolution inside the legacy `render` branch to avoid circular module initialization.

- [ ] Write fallback/empty-draft proof:

```python
from dashboard.models import depiction
from dashboard.models.mapping_context import build_context
from tests.dashboard.mapping_fixtures import write_aa_fixture


def test_empty_mapping_does_not_remove_structure(tmp_path):
    write_aa_fixture(tmp_path)
    context = build_context(tmp_path, "Fixture")
    first = depiction.build_scene(context)
    assert set(map(int, first["positions"])) == {1, 2, 3, 4, 5}
    assert context["source_quality"]["bond_order"] == "fallback"
    assert first == depiction.build_scene(context)
```

- [ ] Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_mapping_depiction.py -q`; observe failure before implementation.
- [ ] Resolve optional chemical sources beside selected coordinates first: matching MOL2, then SDF, then mapped SMILES/verified graph correspondence. Parse without changing source files. Verify elements, atom bijection, connectivity and stereochemistry against AA evidence. A bare SMILES order is never an AA index map; ambiguous mappings produce a visible fallback diagnostic.
- [ ] Build RDKit 2D coordinates once per source snapshot. Keep explicit hydrogens and stable AA IDs. Fallback draws only known connectivity as single bonds and labels unknown elements by atom name. Preserve an always-renderable graph even when chemistry sanitization fails.

```python
# Inside depiction.build_scene after an RDKit molecule has verified AA IDs:
from rdkit.Chem import rdDepictor
rdDepictor.Compute2DCoords(mol, canonOrient=True, clearConfs=True)
# Use the same drawer coordinates for base_svg and interactive hit targets.
positions = {atom.GetIntProp("aa_id"): [
    drawer.GetDrawCoords(atom.GetIdx()).x,
    drawer.GetDrawCoords(atom.GetIdx()).y,
] for atom in mol.GetAtoms()}
```

- [ ] Test double/aromatic bonds and stereochemistry with generated SDF fixtures, reordered chemical atoms, inconsistent MOL2, ambiguous SMILES, explicit H, empty draft and invalid overlays. Cache keys include source content and layout version; no request per selection click.
- [ ] Compare browser overlays and downloaded SVG against the same scene coordinates and parent-centroid fixtures. Diagram extents must include all atoms and overlays; validation failures must not replace the base scene.
- [ ] Rerun context/depiction tests and existing depiction/export checks in `test_dashboard.py` and `test_mapping_exports.py`. Check that scene assembly has no DDM global reads for explicit contexts.

## Task 3: Schema 3, partial drafts and immutable identity

**Files:** Modify `mappings.py`; create `tests/dashboard/unit/test_mapping_documents.py`; extend `tests/dashboard/unit/test_bonded_states.py`.

**Interfaces:** Implement shared `new_draft`, `validate`, `require_usable`. Extend `save_draft(data, *, context=None)`, `get(name, *, context=None)`, `list_candidates(summary=False, *, context=None)`, and `mapping_identity(mapping)`.

- [ ] Write regression for empty draft saving and blocked export:

```python
import pytest
from dashboard.models import mappings
from dashboard.models.mapping_context import build_context
from tests.dashboard.mapping_fixtures import write_aa_fixture


def test_partial_draft_can_save_but_cannot_export(tmp_path):
    write_aa_fixture(tmp_path)
    context = build_context(tmp_path, "Fixture")
    draft = mappings.new_draft(context, "Manual start")
    result = mappings.validate(draft, context=context)
    assert result["can_save"] and not result["can_export"]
    first = mappings.save_draft(draft, context=context)
    second = mappings.save_draft(first, context=context)
    assert first["file"] != second["file"]
    assert first["mapping_hash"] == second["mapping_hash"]
    with pytest.raises(ValueError):
        mappings.require_usable(first, context, operation="export")
```

- [ ] Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_mapping_documents.py -q` and observe RED.
- [ ] Add schema-version branching. Keep legacy hash calculation byte-for-byte equivalent; schema 3 hashes molecule snapshot plus existing identity fields with an explicit version tag.

```python
# In mapping_identity, before canonical serialization:
payload = {key: mapping.get(key) for key in ("name", "beads", "rings", "connections")}
if mapping.get("schema_version") == 3:
    payload.update(identity_version=3, molecule_id=mapping["molecule_id"],
                   molecule_snapshot=mapping["molecule_snapshot"])
```

- [ ] Split document safety from structural readiness using the decisions above. Add type membership/size consistency and finite-number validation. Count only physical beads in nominal atom representation. Preserve warnings separately; warnings alone do not imply scientific approval.
- [ ] Publish complete JSON through a temporary file and atomic no-replace publication in `storage_root()`; concurrent readers never see partial JSON. Recompute validation/hash server-side. Recheck live source bytes before publication; do not trust client-supplied validation, capabilities or hash strings.
- [ ] Test forged hashes, changed optional chemical source, atom reorder, cross-molecule reuse, simultaneous saves, corrupt saved records, legacy reads with unchanged bytes/hash, and schema 3 bonded isolation. Confirm fresh save does not migrate existing bonded states.
- [ ] Run new document tests, `test_bonded_states.py`, `test_performance_api.py`, and candidate-selection tests. Record legacy byte/hash preservation evidence.

## Task 4: Read-only reference fragment index

**Files:** Create `mapping_references.py`, `tests/dashboard/unit/test_mapping_references.py`; reuse integrity conventions from `model_registry.py`. Read reference repositories without modifying them.

**Interfaces:** Produce `load_index(project_root)` contract. Parsers record diagnostics for unsupported/malformed entries, never fabricate an AA mapping from a CG ITP. Candidate provenance stores matched source locators and hashes, not an index copy.

- [ ] Add source-backed parser tests:

```python
from dashboard.models.mapping_references import load_index
from tests.dashboard.fixtures import PROJECT_ROOT


def test_real_reference_records_have_verifiable_origins():
    index = load_index(PROJECT_ROOT)
    assert {r["source_rank"] for r in index["records"]} == {1, 2, 3}
    assert all(r["fragment_id"] and r["references"] for r in index["records"])
    assert index["index_sha256"] == load_index(PROJECT_ROOT)["index_sha256"]
```

- [ ] Run `dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_mapping_references.py -q`; confirm RED.
- [ ] Parse sugar blocks into reference bead/site data. Join only recognized canonical sugar fragments from existing `carbohydrates.py` to compatible reference residues. DDM linkage substitutions retain provisional transfer notes.
- [ ] Parse small-molecule ITP blocks plus AA ITP/PDB and refined NDX when uniquely available; otherwise use the unique ordinary NDX. Validate atom correspondence against SMILES and topology before fragment extraction. Reject ambiguous alternatives with diagnostics. Preserve fragment attachment environment, charge and aromaticity.
- [ ] Read Bible workbook and resolve CGSmiles with the installed library, retaining row locators and all required attachment labels. Do not execute `make_table.py` or parse the PDF.

```python
from openpyxl import load_workbook


def bible_rows(path):
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        for row_number, row in enumerate(
            book["All"].iter_rows(min_row=2, values_only=True), 2
        ):
            name, tag, smiles, cgsmiles = row[:4]
            if tag and smiles and cgsmiles:
                yield row_number, name, tag, smiles, cgsmiles
    finally:
        book.close()
```

- [ ] Add small temporary reference fixtures for duplicate tags, conflicting types, invalid source hashes, stale cache invalidation, missing workbook/dependency and malformed mappings. Pin source paths under `references/`; skip symlinks and bounded-size invalid entries. Return partial capability diagnostics when a source fails.
- [ ] Run index tests. Confirm at least one independently verified match from each source class; count skipped records and reasons instead of claiming complete reference coverage.

## Task 5: Reference-backed suggestions and deterministic baseline

**Files:** Create `mapping_suggestions.py`, `tests/dashboard/unit/test_mapping_suggestions.py`; modify `mappings.automatic_candidate()` to retain a legacy adapter and use explicit context for schema 3 generation.

**Interfaces:** Produce `suggest_bead(context, atom_ids, index)` and `generate_baseline(context, index)` as defined above. Keep the automatic preview unsaved.

- [ ] Add deterministic/no-mutation proof:

```python
from copy import deepcopy
from dashboard.models.mapping_context import build_context
from dashboard.models.mapping_references import load_index
from dashboard.models.mapping_suggestions import generate_baseline
from tests.dashboard.fixtures import PROJECT_ROOT


def test_ddm_baseline_is_deterministic_and_keeps_inputs():
    context = build_context(PROJECT_ROOT / "molecules", "DDM")
    original = deepcopy(context)
    index = load_index(PROJECT_ROOT)
    first = generate_baseline(context, index)
    assert first["available"]
    assert first == generate_baseline(context, index)
    assert context == original
    assert "file" not in first["candidate"]
    assert first["candidate"]["provenance"]["references"]
```

- [ ] Run suggestion tests and confirm RED.
- [ ] Rank applicable fragment matches by source precedence, exact attachment/charge/stereo context, then stable fragment ID/type. Report alternatives and conflicting sources. Explain evidence class; do not display probability percentages. Catalog membership controls size/type compatibility.
- [ ] For unmatched selections, return size guidance from R/S/T count conventions with exception warnings and `type: null`; do not present an oxygen-count guess as reference evidence. Missing chemical bond order suppresses bond-order-dependent matches.
- [ ] Reuse sugar-first recognition, then the existing deterministic connected grouping algorithm for remaining atoms. Use canonical atom ordering/tie breaks and explicit algorithm parameters; type groups through the same suggestion function. Unsupported automatic input returns `available:false` with reasons; manual mapping remains usable. Safe partially typed output remains an incomplete preview.

```python
# Persist this in automatic preview provenance, without timestamp or random ID.
algorithm = {
    "name": "in-house-sugar-first-graph",
    "version": "1",
    "parameters": {"max_group_heavy_atoms": 4, "tie_break": "ascending-aa-id"},
    "reference_index_sha256": index["index_sha256"],
}
```

- [ ] Test sugar preference only for valid sugar matches, competing small-molecule/Bible matches, charge/stereo differences, no match, changed reference hash, fallback context and consistent manual/automatic suggestions. Record the algorithm implementation hash as additional provenance.
- [ ] Run suggestion/index tests plus existing `test_carbohydrates.py`; verify legacy sugar grouping/scaling is unchanged.

## Task 6: Ring-site proposal and dependent edits

**Files:** Modify `mappings.py`, `carbohydrates.py`; create `tests/dashboard/unit/test_mapping_sites.py`.

**Interfaces:** Implement `ring_site_preview(data, context, parents)`. Generic sites do not require a carbohydrate `rings` entry. Verified sugar rings retain the existing definitions and scale.

- [ ] Test valid generic parent selection and warning:

```python
from dashboard.models import mappings
from dashboard.models.mapping_context import build_context
from tests.dashboard.mapping_fixtures import write_aa_fixture


def test_nonring_site_is_advisory_not_automatic_sugar_scaling(tmp_path):
    write_aa_fixture(tmp_path)
    context = build_context(tmp_path, "Fixture")
    draft = mappings.new_draft(context, "Site experiment")
    draft["beads"] = [
        {"name": f"B{i}", "size": "T", "type": "TC1", "atoms": [i]}
        for i in (1, 2, 3)
    ]
    proposal = mappings.ring_site_preview(draft, context, ["B1", "B2", "B3"])
    assert proposal["bead"]["type"] == "TC4"
    assert proposal["bead"]["atoms"] == []
    assert proposal["ring"] is None
    assert any(w["code"] == "not_ring_like" for w in proposal["warnings"])
```

- [ ] Run site tests to confirm RED.
- [ ] Validate three unique nonempty massive parents, known names, finite positions and no parent-site recursion. Determine ring likeness from AA graph and mapped membership, never the 2D triangle shape. Return deterministic unused site name and reasoned warnings.

```python
proposal = {"name": site_name, "size": "T", "type": "TC4", "atoms": [],
            "virtual_site": {"function": 1, "parents": list(parents)}}
```

- [ ] Keep generic site mass/COG behavior separate from paper ring expansion. Rename updates all parents/connections/overrides/rings. Removal/regrouping that empties a parent must be blocked until its dependent site is explicitly removed or reassigned. Never silently delete a dependent scientific object.
- [ ] Test duplicate/virtual/missing parents, rename/remove safety, generic coordinate means, known sugar scale and site charge/mass. Run site/document/carbohydrate tests.

## Task 7: Molecule-scoped HTTP contracts

**Files:** Modify `dashboard/web/routes/models.py`, `molecules.py`; create `tests/dashboard/integration/test_mapping_workspace_api.py`.

**Interfaces:** GET context/list accept `molecule_id`; detail may also accept expected `snapshot_sha256`. POST preview/suggestion carry `molecule_id`, `molecule_snapshot`, and action data. Save/validate/review/export carry schema 3 candidate. Ring preview carries candidate plus `parents`.

- [ ] Add end-to-end no-write preview test:

```python
from dashboard.app import default_coordinator as web


def test_automatic_preview_has_no_saved_candidate(isolated_workspace):
    client = web.app.test_client()
    context = client.get("/api/mappings/context?molecule_id=DDM").json["context"]
    before = sorted(isolated_workspace.mapping_drafts.glob("*.json"))
    response = client.post("/api/mappings/automatic/preview", json={
        "molecule_id": "DDM", "molecule_snapshot": context["snapshot"],
    })
    assert response.status_code == 200
    assert response.json["available"]
    assert sorted(isolated_workspace.mapping_drafts.glob("*.json")) == before
```

- [ ] Run API test to establish RED.
- [ ] Implement the approved endpoint set. Context response adds `context` and `scene` while retaining legacy `molecule`/`bead_types`. Use 400 for malformed payloads/unsafe IDs, 404 for missing resources, 409 for stale/cross-molecule context or blocked operation. Valid unsupported generation returns 200 with `available:false` and reasons.

```python
@blueprint.post('/api/mappings/automatic/preview')
def automatic_mapping_preview():
    payload = request.get_json() or {}
    c = coordinator()
    context = mapping_context.build_context(c.ROOT / 'molecules', payload['molecule_id'])
    if payload.get('molecule_snapshot') != context['snapshot']:
        abort(409, 'Molecule sources changed; reload the mapping workspace')
    return jsonify(mapping_suggestions.generate_baseline(
        context, mapping_references.load_index(c.ROOT)))
```

  Wrap required-field/type/read errors with explicit API error handling; the snippet shows the successful path and stale guard.
- [ ] Preserve omitted-molecule legacy DDM endpoints as wrappers. No schema 3 request may silently default to DDM. Filter summary catalogs by molecule and source; return stale/legacy inspection notices separately. Handle invalid JSON, lists instead of objects, excessive IDs/beads, and forged reference provenance.
- [ ] Hash lookup only against the configured molecule/reference roots. Verify suggestion citations or mark them user-supplied; never accept client confidence as server evidence. Preview/reference requests must not register models or create metadata files.
- [ ] Run API tests, `test_performance_api.py`, `test_candidate_selection.py`, and `test_app_factory.py`. Exercise missing references without breaking the manual workspace.

## Task 8: Export and downstream compatibility

**Files:** Modify `mappings.py`, `draft_model.py`, `bonded_states.py`, `dashboard/execution/coordinator.py`, `ddm.py`, `dashboard/web/routes/molecules.py`, `dashboard/web/static/js/new-run.js`, `bonded.js`; extend mapping export, candidate-selection, bonded-state and API tests.

**Interfaces:** All new exports/review/reuse call `require_usable`. All bonded comparisons use `mapping_identity`. Source-bound context is passed into schema 3 exporters and preparation; existing captured run artifacts remain immutable.

Extend `mappings.export_files(data, *, context=None) -> dict[str, str]`; the optional context retains legacy DDM callers. Resolve schema 3 context by its molecule ID when omitted, then verify its snapshot before export. Add `molecule_id` and the full `molecule_snapshot` to exported `model.json` and run preparation metadata.

- [ ] Test independent molecule names and gates using the shared fixture:

```python
from dashboard.models import mappings
from dashboard.models.mapping_context import build_context
from tests.dashboard.mapping_fixtures import write_aa_fixture


def test_export_uses_selected_molecule_and_keeps_snapshot(tmp_path):
    write_aa_fixture(tmp_path, "Fixture")
    context = build_context(tmp_path, "Fixture")
    candidate = mappings.new_draft(context, "Complete fixture")
    candidate["beads"] = [
        {"name": "B1", "size": "R", "type": "C1", "atoms": [1, 2, 3, 4]}
    ]
    files = mappings.export_files(candidate, context=context)
    assert "LIG Fixture" in files["mapping.map"]
    assert "molecule_snapshot" in files["model.json"]
    assert "DDM" not in files["README.txt"]
```

- [ ] Run focused export/integration tests and establish RED for schema 3 behavior.
- [ ] Generate generic MAP molecule names from validated context, NDX from canonical atom IDs, GRO with deterministic five-character residue alias recorded in model.json, and complete source provenance. Distinct atom names remain a format-specific Fast_Forward requirement; reject unsupported MAP instead of corrupting it. Generic-site bundles include enough definitions to construct sites and explicitly label limitations; do not call sugar topology generation for unrecognized rings.
- [ ] Replace inline legacy bonded hash comparison:

```python
if bonded_snapshot.get('mapping_hash') != mappings.mapping_identity(mapping_snapshot):
    abort(409, 'Bonded state does not belong to the selected mapping')
```

- [ ] At new-run admission, verify source binding, complete mapping, saved candidate, and DDM adapter eligibility before any job write/worker launch. Recheck schema 3 input hashes in preparation. Retry/resume preserves immutable captured identity; do not rebind legacy history to current files. Legacy records stay readable but explicit import is required for new molecule-scoped use.
- [ ] Filter New run and bonded selectors by compatible molecule/snapshot. Preserve molecule-independent legacy state inspection. Non-DDM manual exports never imply CG execution support. Imported legacy mapping creates a new ID/hash and does not inherit approved reviews or bonded reuse eligibility.
- [ ] Run export/candidate-selection/bonded/performance tests with coordinator disabled. Assert rejected requests create neither jobs nor subprocesses.

## Task 9: Persistent 2D canvas and local editor state

**Files:** Create `mapping-state.js`, `mapping-diagram.js`, `mappings.css`; modify `mappings.js`, `dashboard.html`; create `tests/dashboard/browser/test_mapping_editor_browser.py`.

**Interfaces:** `createEditor(context, candidate)` returns `{context, candidate, selectedAtoms:Set, selectedBeads:Set, dirty:false}`. `toggleAtom(editor, id)` and `clearSelection(editor)` change selection only. `mountDiagram(host, scene, context, onAtom)` returns `{update(candidate, selectedAtoms, selectedBeads), destroy()}`. `createMappings({onFit}).mount(id)` remains the existing entry point.

- [ ] Add browser regression to the existing isolated Flask/Chrome fixture pattern: zero saved candidates must still render every atom; clicking/keyboard selection changes selection count without issuing depiction requests. Spy on network calls and assert base SVG survives validation errors.

```python
# In test_mapping_editor_browser.py, after opening the isolated workspace:
page.get_by_role('tab', name='CG mappings', exact=True).click()
page.locator('#mapping-molecule').select_option('DDM')
expect(page.locator('[data-atom-id]').first).to_be_visible()
atom = page.locator('[data-atom-id][data-heavy="true"]').first
atom.focus()
page.keyboard.press('Space')
expect(atom).to_have_attribute('aria-pressed', 'true')
page.get_by_role('button', name='Clear selection', exact=True).click()
expect(atom).to_have_attribute('aria-pressed', 'false')
```

- [ ] Run the new browser test and observe RED.
- [ ] Implement molecule selector and candidate filter above the approved diagram/inspector split. Separate persistent chemical base from interactive hit targets/overlays. Keep actual H visible with optional hide toggle; only heavy atoms receive selection actions. Escape all labels and render only server-generated SVG, never SVG from source files.

```javascript
export function toggleAtom(editor, id) {
  const atom = editor.context.atoms.find(item => item.id === id);
  if (!atom?.heavy) return;
  if (editor.selectedAtoms.has(id)) editor.selectedAtoms.delete(id);
  else editor.selectedAtoms.add(id);
}
export function clearSelection(editor) {
  editor.selectedAtoms.clear();
}
```

- [ ] Scope local keys to `mapping.v3.<molecule_id>.<snapshot_sha256>.<candidate-or-new>`. Never reuse old `mapping.0` state silently. Preserve previous molecule drafts on switch; source mismatch offers inspection/import rather than automatic reuse. Storage failure exposes an unsaved warning without losing in-memory edits.
- [ ] Guard context/candidate/validation/suggestion requests by molecule generation plus edit revision. Clear old molecule scene while loading; retain same-molecule scene during invalid edits/server errors. Destroy handlers on unmount and preserve existing lazy loading and optional 3D inspection.
- [ ] Run new browser tests plus `test_dashboard_browser.py`, `test_lazy_loading.py`, and figure-viewer mapping checks. Verify 390×844 and 1440×1000 layouts, visible focus and page-error absence.

## Task 10: Grouping, suggestions and ring interactions

**Files:** Extend `mapping-state.js`, `mapping-diagram.js`, `mappings.js`, `dashboard.html`, `mappings.css`, `test_mapping_editor_browser.py`.

**Interfaces:** Pure `groupAtoms(editor, atomIds, bead, {confirmed})` returns a new candidate or throws before mutation. `renameBead(editor, oldName, newName)` and `removeBead(editor, name)` update/reject dependent references atomically. Reuse server ring/suggestion proposals.

- [ ] Add browser tests for selecting assigned atoms, editable ranked suggestion, cancelled transfer with unchanged mapping, confirmed transfer with unique ownership, and dependent parent protection.

```python
# Given two fixture beads, with atom 1 owned by B1:
page.locator('[data-atom-id="1"]').click()
page.get_by_role('button', name='Group into bead', exact=True).click()
expect(page.get_by_role('dialog', name='Create bead')).to_be_visible()
page.get_by_label('Bead name', exact=True).fill('Moved')
page.get_by_role('button', name='Create bead', exact=True).click()
expect(page.get_by_role('dialog', name='Move assigned atoms')).to_be_visible()
page.get_by_role('button', name='Cancel move', exact=True).click()
expect(page.locator('[data-bead-name="B1"]')).to_be_visible()
```

- [ ] Run targeted grouping tests to observe RED.
- [ ] Show up to three ranked choices with source/fragment locator, evidence category and conflict reason. Suggestions may set size/type in the editor, but never auto-create a bead. Validate user-overridden catalog values; retain suggestion citation separately from accepted choice.
- [ ] Implement transfer preflight from current candidate state, not stale modal data. Remove selected IDs from old owners only after confirmation; delete emptied physical beads only when dependency-free. Preview all resulting removals. Preserve incomplete disconnected remnants with findings; never persist overlapping ownership.

```javascript
// Compute transfer from a clone, then publish it once validation succeeds.
const next = structuredClone(editor.candidate);
const moved = new Set(atomIds);
for (const existing of next.beads) {
  if (!existing.virtual_site) existing.atoms = existing.atoms.filter(id => !moved.has(id));
}
// Dependency checks and empty-owner handling precede assigning next to editor.
```

- [ ] Add bead-selection mode and three-parent TC4 preview. Confirmation inserts server proposal and draws parent links immediately. Update parents/connections/overrides on rename; block removal while dependencies exist. Generic site warning does not change sugar scaling or create independent site bonds.
- [ ] Add browser/API parity checks: invalid values remain visible, unknown IDs/H are blocked, rapid selection ignores stale suggestion, malformed edits never remove base chemistry, Escape cancels dialogs and focus returns to triggering control.
- [ ] Run browser editor tests and document/site unit tests. Validate both complete and unfinished grouping flows.

## Task 11: Automatic preview, explicit save and legacy import

**Files:** Extend `mappings.js`, `dashboard.html`, `mappings.css`, `test_mapping_editor_browser.py`, `test_mapping_workspace_api.py`; adjust `shared.js` only if existing cache invalidation cannot clear scoped mapping URLs.

**Interfaces:** Controller keeps separate `editor.candidate` and `automaticPreview`; preview generation never calls `/drafts`. Save response replaces only the document being saved after a matching request generation.

- [ ] Test preview/discard preserves manual work and only explicit save writes:

```python
# After opening the editor and making a named local draft:
page.get_by_label('Candidate name', exact=True).fill('Keep manual work')
page.get_by_role('button', name='Generate automatic preview', exact=True).click()
expect(page.get_by_role('region', name='Automatic preview')).to_be_visible()
page.get_by_role('button', name='Discard preview', exact=True).click()
expect(page.get_by_label('Candidate name', exact=True)).to_have_value('Keep manual work')
```

- [ ] Run preview browser/API tests and observe RED.
- [ ] Implement side-by-side or panel preview using actual algorithm/reference provenance and validation, with loading, unavailable, error, stale and successful states. `Open manual editor` explicitly adopts preview after preserving current local draft. Discard makes no writes. Save-as-new is explicit for both draft and preview.
- [ ] Keep one save request active per document to prevent double-click duplicates. Failure retains edits. Success invalidates scoped catalogs and selects new immutable candidate only if the user has not switched context. Concurrent saves to separate IDs remain safe.
- [ ] Add legacy inspection/import: show missing source binding, require molecule confirmation, validate old IDs against selected source, reset approval status and create a fresh candidate. Never manufacture old source hashes. Existing state history stays attached to its original identity.
- [ ] Test local reload recovery, molecule switching with draft/preview in progress, stale source 409, failed save, preview provenance preservation and immutable source bytes. Verify incomplete approval/export buttons and API gates agree.
- [ ] Run mapping browser/API tests and New run/bonded browser tests after catalog invalidation changes.

## Task 12: Final proof, documentation and rollback handoff

**Files:** Update `docs/PROJECT_GUIDE.md`, `docs/DDM_CALIBRATION.md`, `molecules/README.md`, `dashboard/README.md`, and this plan's completion checkboxes. Keep approved HTML drafts as design artifacts.

**Interfaces:** Document implemented source support, automatic coverage, reference evidence levels, legacy import, snapshot rejection, and remaining DDM-only CG execution.

- [ ] Confirm each spec acceptance item against the table below. Inspect maintained code for residual DDM defaults in explicit schema 3 paths and direct legacy hash expressions.

```bash
rg -n 'mappings\.SOURCE|mappings\.molecule\(|LIG1 DDM|DDM candidate|mapping_snapshot\.get' dashboard/models dashboard/execution dashboard/web
```

  Classify hits: legacy wrapper, explicit DDM adapter, or defect. Do not mass-replace historical scientific scripts.
- [ ] Run focused backend proof, then broaden once to all non-slow dashboard tests (includes browser tests). Tests requiring actual simulation remain excluded; use mocked job/command checks.

```bash
dashboard/.venv/bin/python -m pytest tests/dashboard/unit/test_mapping_context.py tests/dashboard/unit/test_mapping_depiction.py tests/dashboard/unit/test_mapping_documents.py tests/dashboard/unit/test_mapping_references.py tests/dashboard/unit/test_mapping_suggestions.py tests/dashboard/unit/test_mapping_sites.py tests/dashboard/integration/test_mapping_workspace_api.py -q
dashboard/.venv/bin/python -m pytest tests/dashboard -m 'not slow' -q
```

- [ ] Check every JavaScript module with a command that stops on the first failure:

```bash
for f in dashboard/web/static/js/*.js; do
  node --input-type=module --check < "$f" || exit 1
done
```

- [ ] Use an isolated Flask/Chrome workspace, coordinator disabled, for final manual-flow proof: DDM and Maltose selection; graph-only fixture; blank draft; atom/keyboard selection; suggestion confirmation; regroup cancel/confirm; generic/recognized TC4; automatic preview/discard/save; incomplete gates; stale-source rejection; legacy import; matching bonded selection; desktop/mobile; no page errors. Store screenshots under a unique `/tmp/cg-bead-assignment-*` directory. Never restart the live research dashboard for this test.
- [ ] Update docs with verified behavior and reference parser coverage. Record exact test counts, skips, warnings, browser version and source integrity checks. Treat HTML parsing as syntax evidence only, not browser verification.
- [ ] Check source-only rollback: reverting code must leave legacy files/hashes unchanged; schema 3 documents remain preserved separately and must not be opened by old code as DDM. If rolling back, preserve new documents and explicitly prevent old application discovery of schema 3 files; do not delete them or roll back runtime databases. No data cutover is part of this task.
- [ ] Mark tasks complete only after their proof passes. If Git exists at execution, commit each verified task's scoped files; otherwise record changed source paths and rollback-copy location. Stop after accepted behavior works; no simulation, extra framework, cleanup campaign or micelle-builder work.

## Spec coverage and execution order

| Acceptance / invariant | Tasks |
| --- | --- |
| All valid AA molecules; manual availability | 1, 2, 7, 9 |
| Always-visible correct 2D chemistry, fallback and H handling | 2, 9, 10 |
| Interactive grouping, editable ranked suggestions, transfer confirmation | 4, 5, 9, 10 |
| TC4 parents, massless behavior, warnings, dependency safety | 3, 6, 8, 10 |
| Deterministic preview, no write until explicit save | 4, 5, 7, 11 |
| Source-bound identity, immutable save, stale rejection | 1, 3, 7, 8, 11 |
| Incomplete save and approval/export/reuse gates | 3, 7, 8, 10, 11 |
| Legacy routes/hashes/records and explicit import | 3, 7, 8, 11, 12 |
| References and provenance through exports/run snapshots | 4, 5, 8, 11 |
| Accessibility, local recovery, async safety, responsive layout | 9, 10, 11, 12 |

Execute in numbered order for the simplest dependency chain. Task 4 can be developed after shared contracts are stable, independently of context depiction; no delegation is required. Each task ends with focused evidence and a reviewable checkpoint. Implementation has not started when this plan is written.
