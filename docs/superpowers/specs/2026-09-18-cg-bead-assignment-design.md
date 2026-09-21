# Molecule-Scoped CG Bead Assignment Workspace

## Status

Design approved in review rounds on 2026-09-18. Implementation is not included
in this document. The accompanying HTML drafts are visual review artifacts.

## Problem

The dashboard's CG Bead Assignment workspace displays a DDM-specific atom graph,
candidate list, and overlay. The AA molecule catalogue already discovers valid
molecules under `molecules/`, but mapping context, depiction, validation, and
automatic generation still assume DDM. Manual mapping therefore cannot start
from an arbitrary validated AA molecule, and automatic suggestions have no
recorded chemistry reference or provenance.

## Approved decisions

- List every molecule that passes AA input validation. Manual mapping remains
  available even when automatic generation is unavailable.
- Generate one server-side deterministic automatic baseline as a preview. The
  preview never writes a candidate. The user explicitly saves it as a new
  immutable candidate.
- Grouping selected atoms moves them from previous beads after confirmation.
  Overlapping physical assignments are invalid.
- Show an editable bead suggestion before creating a bead. Suggestions include
  ranked size/type choices, reasons, confidence, and reference citations.
- Create a ring interaction site by selecting three existing beads. Suggest a
  massless `TC4` site and warn when the selected triangle is not ring-like.
- Save candidates as new immutable records. Keep unsaved edits in browser-local
  state.
- Prefer chemical structure sources (`MOL2`, `SDF`, or `SMILES`) for bond order
  and 2D layout. Fall back to the ITP atom/bond graph with single bonds and a
  visible bond-order warning.
- Bind candidate identity to molecule ID, canonical source hashes, atom order,
  bead assignments, ring definitions, and connections.
- Show all atoms in the 2D diagram. Only heavy atoms can be selected or assigned.
- Use click to toggle atom selection and Shift-click to add or remove atoms.
  Provide keyboard focus and activation, plus clear-selection controls. Do not
  add lasso selection in the first increment.
- Allow incomplete drafts to be saved. Missing, duplicate, hydrogen, size, and
  connectivity findings remain visible. Approval, export, and simulation reuse
  require complete structural validation.
- Automatic generation returns one baseline candidate. It records algorithm
  name, version, parameters, source snapshot hashes, and reference matches.
- Reference precedence is specialized sugar ITPs, then small-molecule examples,
  then general M3-Bible guidance. Conflicts become warnings; references are
  never silently merged.

## Goals

1. Select any validated AA molecule as mapping context.
2. Always show its 2D molecular structure and update overlays after every bead or
   ring-site edit.
3. Support manual atom grouping with clear assignment ownership.
4. Provide deterministic in-house automatic mapping preview with explainable
   bead suggestions.
5. Preserve molecule and reference provenance through candidate save, review,
   export, and later run snapshots.
6. Keep current DDM candidates and routes readable during migration.

## Non-goals

- No automatic scientific validation or force-field approval.
- No browser-side chemistry engine or new frontend framework.
- No long simulation runs during implementation.
- No mutation or cleanup of canonical molecule inputs or simulation outputs.
- No automatic promotion of a generated candidate to approved status.
- No lasso selection, ranked multi-candidate campaigns, or arbitrary custom bead
  types in the first increment.

## Invariants

1. A mapping candidate references exactly one molecule ID and one immutable
   molecule source snapshot.
2. Every physical atom assignment is a positive heavy-atom ID from that snapshot.
   A physical atom belongs to at most one bead.
3. Virtual sites own no AA atoms. Their parent bead names resolve to physical
   beads and remain explicit in the candidate.
4. Bead and ring-site edits update the same candidate state used by the diagram,
   validation, and save request.
5. Older automatic previews cannot replace a newer molecule or candidate choice.
6. A preview has no persistence side effect. A save creates a new candidate file.
7. Source changes invalidate reuse through snapshot hashes, even when atom count
   and atom names still match.
8. Incomplete drafts remain inspectable but cannot be approved, exported, or
   selected for simulation.
9. Reference data is read-only input. Candidate provenance stores references and
   hashes, not copied reference topology content.

## Architecture

### Molecule context

Extend `dashboard.models.aa_molecules` with a mapping-oriented context builder.
It reuses existing molecule discovery, topology include resolution, coordinate
validation, metadata, and source hashes. It adds:

- normalized atom records with ID, name, element, heavy-atom flag, coordinates,
  and optional charge;
- normalized bonds with endpoint IDs, optional bond order, and an order source;
- chemical-source metadata and fallback quality flags;
- deterministic 2D coordinates generated on the server;
- a stable snapshot containing every input file hash and atom order hash.

The context builder must accept all valid molecule folders. It must return an
explicit capability result when a chemical source is absent or a 2D graph cannot
be constructed. The ITP graph fallback remains usable for manual mapping.

### Mapping domain

Refactor `dashboard.models.mappings` so molecule context is an explicit input,
rather than a module-level DDM source. Keep DDM-specific sugar recognition in a
separate adapter selected by molecule capabilities. The generic domain owns
candidate schema, ownership checks, mapping identity, validation, save-as-new,
and export gates.

Candidate persistence remains JSON-backed in this increment. The repository
creates a new immutable `mapping_candidate_<uuid>.json` for every server save.
Browser-local drafts never become authoritative until that save succeeds.

### Reference registry

Add a read-only registry that indexes:

- `references/martini_v3.0.0_sugars_v2.itp` and matching
  `martini_*_sugars_*.itp` files;
- `references/M3-Small-Molecules`;
- `references/M3-Bible`.

The registry extracts functional-group and fragment assignments into searchable
records. It preserves source path, SHA256, fragment identifier, bead size/type,
and descriptive notes. It applies precedence in this order:

1. specialized sugar ITP definitions;
2. small-molecule fragment examples;
3. M3-Bible generic guidance.

The registry reports competing matches as warnings. It does not infer a validated
parameter set from a match.

### Suggestion service

The server-side suggestion service receives a molecule context and selected atom
IDs. It returns ranked bead size/type suggestions based on heavy-atom count,
elements, local bond graph, functional-group matches, and reference precedence.
Each result includes reason, confidence, matched fragments, and source hashes.
The service is deterministic for identical context, selection, reference files,
algorithm version, and parameters.

The automatic baseline service uses the same context and registry. It returns one
candidate preview with explicit provenance or an unavailable result with a reason.
It never writes a candidate and never marks a candidate approved.

### Web boundary

Add molecule-scoped mapping endpoints while retaining current DDM routes as
compatibility wrappers. Route handlers validate molecule IDs, source snapshots,
payload shape, atom ownership, and candidate compatibility before calling model
functions. No route accepts an arbitrary filesystem path.

## Data model

The mapping context response has this shape:

```json
{
  "molecule_id": "DDM",
  "snapshot": {
    "files": {"results/MMFF/lig1.itp": "sha256..."},
    "atom_order_sha256": "sha256..."
  },
  "atoms": [
    {"id": 1, "name": "C1", "element": "C", "heavy": true,
     "xyz": [0.0, 0.0, 0.0], "display_xy": [120.0, 180.0]}
  ],
  "bonds": [
    {"a": 1, "b": 2, "order": 1, "order_source": "chemical"}
  ],
  "source_quality": {"bond_order": "chemical"}
}
```

Candidate records add molecule identity and provenance to the existing bead,
ring, and connection fields:

```json
{
  "schema_version": 3,
  "molecule_id": "DDM",
  "molecule_snapshot": {"files": {"results/MMFF/lig1.itp": "sha256..."}},
  "name": "DDM manual draft",
  "beads": [],
  "rings": [],
  "connections": [],
  "provenance": {
    "origin": "manual",
    "algorithm": null,
    "references": []
  },
  "validation": {}
}
```

Automatic previews use the same shape in memory with `origin: automatic` and
algorithm/reference provenance. Preview responses are never written implicitly.

## API surface

- `GET /api/molecules` returns the validated molecule catalogue.
- `GET /api/mappings/context?molecule_id=<id>` returns canonical graph, 2D
  coordinates, bead catalog, source quality, and capability flags.
- `GET /api/mappings?molecule_id=<id>&view=summary` returns only candidates bound
  to the selected molecule and compatible snapshot.
- `GET /api/mappings/<name>` returns a candidate with its molecule snapshot and
  rejects incompatible reuse.
- `POST /api/mappings/automatic/preview` returns one deterministic candidate
  preview or an explicit unavailable result. It does not write files.
- `POST /api/mappings/suggest-bead` accepts selected heavy-atom IDs and returns
  ranked editable suggestions.
- `POST /api/mappings/ring-site/preview` accepts three bead names and returns a
  TC4 proposal plus ring-likeness findings.
- `POST /api/mappings/validate` validates partial candidates and returns issue
  severity plus approval/export gates.
- `POST /api/mappings/drafts` saves an immutable candidate after snapshot and
  payload validation.
- Existing DDM mapping routes remain available through adapters until callers
  migrate to molecule-scoped requests.

## UI behavior

The CG Bead Assignment tab starts with molecule selection. It then loads the
candidate selector filtered to that molecule and the canonical context. The page
always contains the interactive SVG diagram, even when no candidate exists.

The diagram shows all atoms and bonds. Heavy atoms are focusable and selectable;
hydrogens are visible but disabled for assignment. Known bond order uses the
chemical source. Fallback graphs use single bonds and show a persistent quality
notice.

Selecting atoms updates a count and enables grouping. Grouping opens an editable
preview containing the proposed name, size, type, reason, confidence, and source
references. Confirming a group moves selected atoms out of earlier beads after a
clear confirmation message.

Selecting three beads enables ring-site creation. The proposed massless TC4 site
shows parent names and a ring-likeness warning. Saving the site updates the SVG,
bead table, validation, and candidate state together.

Automatic generation displays a preview panel. The panel shows algorithm/version,
reference matches, warnings, and validation status. `Save as new candidate` is
the only persistence action. Existing unsaved work remains in browser-local
storage and is never replaced by the preview.

Desktop uses a diagram/inspector split. Mobile stacks molecule controls, diagram,
selection actions, bead inspector, and validation. SVG elements expose accessible
labels and keyboard activation; errors and asynchronous status use live regions.

## Validation and compatibility

Validation distinguishes errors from advisory warnings. Missing heavy atoms,
duplicate ownership, hydrogen assignment, unknown IDs, invalid bead sizes,
disconnected groups, missing parents, and invalid connections are errors. A
Non-ring-like TC4 selection is an advisory warning. It does not block saving,
but remains visible during review and approval.

Existing DDM records remain readable. Records without molecule snapshot metadata
are marked legacy and remain viewable, but cannot be selected for new
molecule-scoped reuse until saved as a new candidate with an explicit snapshot.
No simulation output or canonical molecule file is migrated in place.

## Test strategy

- Unit tests for context extraction, chemical-source precedence, ITP fallback,
  snapshot hashes, deterministic automatic output, reference conflicts, ranked
  suggestions, atom ownership, and ring warnings.
- API tests for molecule filtering, preview no-write behavior, snapshot mismatch,
  immutable saves, incomplete-draft gates, and cross-molecule rejection.
- Browser tests for molecule switching, filtered candidates, click and Shift
  selection, keyboard activation, grouping confirmation, live overlays, TC4
  warnings, automatic preview/save, stale response protection, responsive layout,
  and page-error absence.
- Node syntax checks for all dashboard JavaScript modules.
- No simulation execution is required for this refactor.

## Acceptance

1. Every valid molecule can open a manual mapping workspace.
2. Every workspace always shows a 2D structure from chemical input or explicit
   graph fallback.
3. Selected heavy atoms can form a bead after editable suggestion review.
4. Existing assignments move only after confirmation; overlaps never persist.
5. Three selected beads can create a TC4 preview with ring-likeness warning.
6. Automatic preview is deterministic, explainable, provenance-rich, and
   side-effect free until explicit save.
7. Candidates are molecule/source-bound immutable records.
8. Incomplete drafts remain saveable but cannot be approved, exported, or reused.
9. Existing DDM records and routes remain readable during migration.
