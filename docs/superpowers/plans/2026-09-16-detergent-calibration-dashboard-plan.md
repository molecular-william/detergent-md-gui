# Detergent calibration dashboard implementation plan

## Global constraints

- Original `references/` files remain canonical.
- Existing simulation directories, reports, manifests, and unique evidence remain immutable.
- Only artifacts marked obsolete by a reviewed migration report may be deleted.
- DDM is the first executable adapter; arbitrary-detergent execution is out of scope until an adapter and evidence profile exist.
- Every model and job records force-field/tool versions, hashes, commands, inputs, outputs, and evidence status.

## Phase 1: Skill and registry foundation

- Verify the hard-renamed `detergent-calibration` skill and update all callers/documentation.
- Add dashboard reference records with source path, hash, molecule identity, force-field/version, model kind, citation, license, and evidence status.
- Add a read-only reference browser and hash mismatch diagnostics.
- Add migration dry-run output and a database/export backup.
- Tests: reference import, duplicate detection, hash drift, path safety, skill validation.

## Phase 2: Fragment and composition domain

- Add immutable fragment records and content-addressed snapshots.
- Add attachment-map validation against atom bonds, bead ownership, charge, and force-field compatibility.
- Generate composite candidates with inherited/new interaction provenance.
- Add DDM maltose/headgroup plus alkyl-tail composition fixture without changing existing DDM outputs.
- Tests: fragment immutability, disconnected/ambiguous attachment rejection, virtual-site handling, topology round trip, provenance hashes.

## Phase 3: Review workspace

- Add reference, fragment, and composition views to the existing dashboard.
- Show COG versus optimized/fitted models and Martini 2 versus Martini 3 compatibility warnings.
- Add candidate comparison and explicit lifecycle states.
- Keep current mapping and bonded-state pages compatible during migration.
- Tests: API snapshots, browser navigation, keyboard/mobile behavior, stale async response handling.

## Phase 4: Validation and adapter boundary

- Add class-specific evidence profiles for carbohydrate headgroups, alkyl tails, charged groups, and complete detergents.
- Store property results with units, source hashes, sampling metadata, uncertainty, and metric direction.
- Connect the DDM adapter to compositions while preserving its existing stages and scientific gate.
- Prevent execution or validation promotion from incomplete, mismatched, or unsupported candidates.
- Tests: gate evaluation, missing-evidence behavior, DDM compatibility, fit/screen/reuse intent transitions.

## Phase 5: Legacy migration and cleanup

- Implement a report-only migration over jobs, runs, mappings, bonded states, reports, caches, and reference indexes.
- Classify duplicates by content hash and generated outputs by ownership/dependency.
- Require review metadata before deletion of obsolete artifacts.
- Delete only approved obsolete paths after lease, symlink, dependency, and containment checks.
- Record audit events and preserve export/rollback snapshots.
- Tests: idempotent reports, controlled deletion, partial failure retry, active-run protection, unchanged retained hashes.

## Phase 6: Future adapters

Add new detergent adapters only with a source reference, force-field compatibility record, mapping/bonded procedure, independent screening protocol, and class-specific evidence profile. Do not add a generic plugin layer before a second adapter demonstrates a real shared seam.

## Verification

Run the skill validator, focused registry/composition/migration tests, existing dashboard workflow tests, JavaScript syntax checks, and browser tests. Verify that old DDM runs and source hashes are unchanged and that approved obsolete deletion is the only filesystem mutation during cleanup tests.
