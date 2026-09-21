# General detergent calibration and dashboard design

## Status

Approved for planning on 2026-09-16. The first executable adapter remains DDM; general registry and composition support must not imply arbitrary-detergent execution.

## Goals

- Generalize the calibration workflow from DDM to Martini 3 detergent building blocks.
- Preserve original references and simulation evidence while making provenance searchable.
- Represent composite detergents as immutable fragment graphs with explicit atom-level attachments.
- Keep validation molecule-class-specific and separate from topology execution.
- Provide a safe, reviewable path for legacy indexing and deletion of artifacts marked obsolete.

## Scientific model

A fragment is an immutable mapping/topology snapshot with force-field identity, source hashes, chemistry metadata, and evidence status. A composition references fragments and stores an attachment map: atom ownership, bead ownership, bond order, and newly generated linkage terms. Building a composition produces a new candidate snapshot; it never edits a fragment.

Imported Martini 2 MAD models are reference evidence. Martini 3 sugar and small-molecule models are current compatibility references. COG, optimized, inherited, fitted, screened, reviewed, and validated are distinct model states.

## Dashboard owners

- `reference_registry`: indexed metadata, hashes, citations, licenses, and compatibility.
- `fragment_models`: immutable fragment records and validation.
- `compositions`: attachment graph and generated candidate snapshots.
- `validation_profiles`: class-specific evidence requirements and results.
- Existing `mappings.py`, `bonded_states.py`, `workflow.py`, `analysis.py`, and `store.py` remain owners of their current responsibilities and are extended through explicit snapshots.

SQLite should own searchable identities and references; immutable JSON/topology artifacts remain in managed directories with manifests and hashes.

## Legacy migration and deletion

Migration first creates a report classifying files as retained source/evidence, indexed read-only legacy, duplicate, obsolete generated output, or unsafe/unclassifiable. The report records path, hash, owner, reason, and references. Existing runs and manifests are not rewritten. Only artifacts marked obsolete by the reviewed report may be deleted. Deletion requires path containment, symlink rejection, dependency/lease checks, an audit record, and retryable failure handling. The report and database snapshot remain available for rollback.

## Workflow

1. Import a canonical reference and verify its hash.
2. Register or create immutable fragments.
3. Define and validate an attachment map.
4. Generate a composite candidate snapshot.
5. Fit mapping, bonded, and property layers in separate attempts.
6. Run independent screening.
7. Evaluate the class-specific evidence profile.
8. Mark the candidate provisional, reviewed, validated, or rejected with explicit missing evidence.
9. Allow execution adapters only for profiles that declare them.

## Acceptance evidence

The first increment must demonstrate reference indexing, hash mismatch detection, fragment immutability, attachment validation, composite provenance, class-specific gate evaluation, legacy dry-run classification, approved obsolete deletion, and unchanged legacy runs. DDM must remain executable and produce the same existing run artifacts.
