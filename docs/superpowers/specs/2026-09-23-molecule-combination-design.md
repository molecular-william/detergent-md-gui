# Molecule Combination Dashboard Panel

## Status

Design approved in conversation on 2026-09-23. Implementation is pending
written-spec review.

## Purpose

Add a fifth dashboard panel named **Molecule Combination**. The panel lets a
user compose an existing mapped and bonded sugar or other compatible headgroup
with a generated Martini carbon tail. The result is an immutable,
provenance-backed CG model that can be inspected in **CG Bond Interactions**
and screened through an explicit CG-only run path.

Composition is model construction, not scientific validation. A structurally
valid result is saved as `candidate-unvalidated`; execution and screening do
not promote it to a validated model.

## Decisions

- The panel consumes immutable mapped and bonded fragment snapshots. Raw
  molecule upload and atomistic preparation remain in the existing molecule
  workflow.
- The first generated fragment is a carbon tail recipe. The user supplies a
  carbon count, not a bead count.
- The initial recipe catalog contains two named recipes:
  `Linear C1` and `Linear C1/C2 terminal`.
- A generated tail is represented by CG beads, with carbon-range annotations
  in the UI. Synthetic carbon atoms are not shown as simulation particles.
- Linkage chemistry is selected from a small catalog of named,
  profile-declared profiles. The catalog ships every reference-backed profile
  available to the first implementation, including the DDM sugar-to-alkyl
  transfer profile; no free-form bond/angle/dihedral entry or invented
  placeholder profile is exposed in Molecule Combination.
- SDS contributes only its hydrocarbon tail in this feature. Sulfate is not
  silently fabricated or included in the tail fragment.
- All 15 residue models in `references/martini_v3.0.0_sugars_v2.itp` are
  visible: `GLC`, `MAN`, `GAL`, `FRUF`, `LFUC`, `LRHA`, `RIBF`, `XYL`, `INO`,
  `GLA`, `GYN`, `NMC`, `LAC`, `SUCR`, and `TREH`.
- Compatibility is declared by each linkage profile. Visible residues and
  endpoints can be unavailable for a particular profile, but the reason is
  shown rather than hidden.
- Endpoint selection is diagram-first with exact dropdown confirmation. The
  attachment contract stores bead endpoints and optional atom/carbon metadata
  when available.
- Tail coordinates are deterministic. The builder infers an outward
  direction from the selected head geometry, falls back to a documented axis
  when ambiguous, creates a zig-zag tail, and rejects severe overlaps.
- A saved composition is immediately selectable as an unvalidated model and
  can enter a separate CG-only run path. It is not passed through the
  atomistic AA-to-CG adapter.
- Every save creates a new immutable composition snapshot. Editing a choice
  creates another composition; existing records remain usable.

## Domain ownership

`dashboard/models/compositions.py` remains the persistence owner for
composition records and gains focused operations for catalog loading, preview,
validation, and immutable artifact storage. `dashboard/models/model_registry.py`
continues to own reference and fragment identities and source hashes.

A new focused module, `dashboard/models/composition_topology.py`, owns:

- Martini sugar-fragment parsing;
- tail recipe expansion;
- bead and term index renumbering;
- virtual-site and exclusion preservation;
- deterministic tail coordinate generation;
- linkage-profile compatibility and term generation;
- merged ITP/GRO construction; and
- topology round-trip checks.

The builder never mutates a source fragment. It produces a new composite
mapping and bonded-state snapshot.

The generated composite exposes a mapping-like descriptor and an initial
bonded-state descriptor to consumers. Ordinary mapping drafts and compositions
remain separate persistence types; a unified read-only CG model catalog is
used by the Bonded Interactions panel and run preparation.

## Composition data model

The submitted browser payload contains identifiers and choices only:

```json
{
  "head_fragment_id": "builtin:martini-sugars-v2:GLC",
  "tail_recipe_id": "linear-c1",
  "carbon_count": 12,
  "head_endpoint": {"bead": "A", "atom": null},
  "tail_endpoint": {"bead": "C1", "carbon": 1},
  "linkage_profile_id": "sugar-alkyl-ether-ddm-transfer",
  "display_name": "Glucose C12 composite",
  "residue_name": "GLCC1"
}
```

The server reconstructs the candidate from canonical source files and profile
definitions. It records:

- immutable head and tail fragment snapshots;
- source paths, SHA256 hashes, force-field and Martini versions;
- carbon count, recipe ID and recipe version;
- endpoint ownership and optional atom/carbon metadata;
- linkage profile ID, version, generated terms and exclusions;
- generated mapping snapshot and initial bonded-state snapshot;
- validation diagnostics and execution-readiness diagnostics;
- content identity, creation time and generation algorithm version.

The structural identity excludes the display name but includes all choices,
fragment hashes, generated mapping, coordinates and bonded terms. An identical
identity disables Save and points to the existing composition.

## Immutable artifact bundle

Each composition is written atomically under:

```text
workspace/compositions/<composition-id>/
  composition.json
  mapping.json
  initial-bonded-state.json
  <residue-name>.itp
  <residue-name>.gro
  validation.json
  manifest.json
```

The temporary build directory is validated before it is renamed into place.
The manifest hashes every artifact and records the exact source and generation
inputs. A failed preview or save leaves no final composition directory.

## Linkage profiles and recipes

Tail recipes are named, versioned definitions. `Linear C1` groups the
requested carbon count into the standard linear C1 representation. `Linear
C1/C2 terminal` uses the same interior grouping while permitting its declared
terminal bead rule. Recipe bounds, grouping, bead types, masses, spacing, and
coordinate rules are fixed by the recipe definition and stored in the
composition snapshot.

Linkage profiles declare compatible head endpoint roles and bead types, tail
endpoint roles, generated bonds, required angles and dihedrals, exclusions,
and reference provenance. Profiles are read-only in Molecule Combination.
The DDM sugar-to-alkyl ether transfer is the first required profile. Every
additional profile requires its own reference topology and provenance record;
the selector may contain several named profiles when those records exist.

The generated linkage terms appear in CG Bond Interactions as `generated`.
Inherited head and tail terms retain their source labels. Editing occurs only
through the existing bonded-state revision flow, which preserves the profile
and parent composition hashes.

## API

The following endpoints are added or extended:

- `GET /api/compositions/catalog` returns sugar fragments, tail recipes,
  linkage profiles, saved summaries and source-integrity diagnostics.
- `POST /api/compositions/preview` validates and builds an in-memory result.
- `POST /api/compositions` rebuilds and atomically persists a result.
- `GET /api/compositions/<id>` returns a saved composition and artifact
  metadata.
- `GET /api/cg-models?view=summary` lists ordinary mapping drafts and
  composition-backed models for CG consumers.
- `GET /api/cg-models/mapping/<mapping-file>` returns an ordinary mapping
  descriptor.
- `GET /api/cg-models/composition/<composition-id>` returns a composition
  mapping and initial-state descriptor.

Existing `/api/mappings` behavior remains unchanged for the bead editor.
Existing `/api/bonded-states` response fields remain compatible with
`bonded.js`; composition-backed states are exposed through the CG model
descriptor and revisions retain the existing state identity and revision
semantics.

The server rejects stale source hashes, unknown identifiers, invalid residue
names, invalid carbon counts, virtual-site endpoints, incompatible profiles,
duplicate content, and malformed payloads. Browser-generated topology is never
trusted.

## Validation

Validation is reported in three classes:

1. **Structural:** source integrity, bounds, endpoint ownership, index
   continuity, unique ownership, virtual-site parents, exclusions, finite
   values, graph connectivity, and topology round-trip preservation.
2. **Chemical:** profile compatibility, endpoint role requirements, supported
   residue chemistry, linkage provenance, and explicit provisional-transfer
   warnings.
3. **Execution:** GROMACS availability, force-field resolution, and a
   zero-step `grompp` preflight. A candidate may be saved without GROMACS, but
   CG-only execution remains disabled until this diagnostic passes.

Missing chemistry evidence is a visible blocker for Preview/Save where the
profile cannot define a valid linkage. It is never silently downgraded to a
generic bond.

## Dashboard workflow

The fifth tab is **Molecule Combination**. Its workspace has four regions:

- **Components:** sugar selector, carbon count, named tail recipe, display
  name and five-character GROMACS residue name.
- **Endpoint selection:** synchronized sugar and tail diagrams, exact endpoint
  dropdowns, selected endpoint summaries, and carbon-range annotations.
- **Attachment:** linkage-profile combobox, generated-term table, and grouped
  structural/chemical/execution diagnostics.
- **Preview and actions:** combined Plotly 3D view, inherited/generated term
  summary, provenance/source hashes, and actions in this order:
  `Preview composition`, `Save composition`, `Open CG Bond Interactions`, and
  `Start CG-only run`.

On narrow screens the regions become sequential. Unsaved state is retained
locally and keyed by the selected source hashes and recipe version. Stale
preview responses cannot overwrite newer selections.

Tail diagrams show CG beads, bead type/size colors, and represented carbon
ranges. They do not draw synthetic carbons as if they were simulation atoms.
Endpoint selections are highlighted in both diagrams and in the combined
preview.

## CG-only execution

New Run gains `cg_composition` as an explicit run type. It shows a saved
composition selector and hides ordinary molecule and AA-reference controls.
The run manifest records `composition_id`, composition snapshot hash, mapping
and bonded-state hashes, residue name, recipe/profile identifiers, force-field
metadata, exact commands and artifact hashes.

The stage contract is:

1. **CG simulation:** stage immutable composition GRO/ITP inputs, build the
   water box, run minimization/equilibration/production with the corrected GPU
   launcher flags, and publish `prod/lig_CG.{gro,tpr,xtc}`.
2. **CG assessment:** calculate interaction and distance diagnostics against
   the generated mapping/bonded snapshot. Results are screening evidence,
   not AA agreement or scientific validation.
3. **CG SASA:** calculate CG SASA only. AA comparison is marked unavailable.

The existing AA-only and AA-to-CG contracts remain unchanged. Passing a
composition together with AA-reference inputs is rejected.

The Bonded Interactions panel lists ordinary mappings and compositions with an
origin label. It loads a composition's generated initial state, labels
inherited versus generated terms, and sends composition IDs plus bonded-state
revisions to short validation runs.

Composition deletion is blocked while runs or bonded-state revisions reference
it. Obsolescence and cleanup are outside this feature.

## Testing and acceptance

Unit tests cover sugar catalog parsing, source-hash drift, recipe bounds and
deterministic grouping, coordinate determinism, linkage compatibility,
virtual-site/exclusion preservation, index renumbering, topology round trips,
duplicate identities, immutable revisions, stale-source rejection, and
atomic failure cleanup.

Integration tests cover the composition APIs, unified CG model catalog,
composition-backed Bonded Interactions loading, CG-only run preparation and
manifest contracts, GROMACS preflight behavior, and rejection of invalid
AA/reference combinations.

Browser tests cover endpoint selection, profile filtering, diagnostics,
disabled actions, preview generation, duplicate-save handling, tab persistence,
responsive layout, and stale asynchronous responses. JavaScript syntax checks,
the focused dashboard suite, and the existing browser suite remain required.

Before editing existing symbols, run GitNexus impact analysis. Before any
commit, run `node .gitnexus/run.cjs detect-changes --scope all --repo .`,
review affected processes, run `git diff --check`, and report any unresolved
high-risk or unknown graph findings.

## Scope boundary

This feature does not claim chemical validation for generated tails or new
linkage profiles. It does not add sulfate chemistry, arbitrary free-form
topology editing, atomistic references for synthetic tails, micelle assembly,
or a generic plugin system. New recipes and profiles require their own source,
compatibility, and evidence records.
