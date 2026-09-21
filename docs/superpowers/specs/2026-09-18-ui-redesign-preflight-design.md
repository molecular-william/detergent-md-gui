# UI Redesign Preflight Correctness Design

## Status

Approved scope on 2026-09-18. This increment prepares the existing dashboard for
visual redesign by fixing correctness boundaries first. It does not redesign
visual styling, add a frontend framework, or change scientific execution.

## Goals

- Make mapping identity explicit and use it when listing and selecting bonded states.
- Parse GROMACS bonded terms, including variable-length virtual-site parents, into
  records that preserve bead indices, display names, and parent links.
- Make bonded-state revision behavior explicit: save-as-new by default; confirmed
  in-place revision with optimistic concurrency.
- Finish the existing interaction workspace controls without changing stable routes.
- Prevent stale asynchronous mapping/state previews from overwriting newer choices.
- Preserve missing analysis values as missing, with captions based on recorded
  metric metadata rather than filenames alone.
- Remove documentation path drift from the maintained molecule workflow.

## Non-goals

- No new framework or service.
- No SQLite bonded-state migration in this increment; existing JSON records stay
  readable and new fields remain additive.
- No scientific validation promotion, production gate change, or long simulation.
- No deletion of simulation outputs or canonical references.
- No micelle-builder resume.

## Invariants

1. A bonded state belongs to one exact mapping identity. Name, bead order, atom
   assignment, ring definitions, virtual-site parents, and connections contribute
   to that identity using the existing canonical hash fields.
2. A state revision cannot change mapping identity. A stale expected revision is
   rejected before any file write.
3. Save-as-new never mutates the source state. In-place revision is explicit and
   requires the current revision number.
4. Complete reusable states require a complete ITP and a reusable status. Mapping-
   only and failed states remain visible for inspection but cannot be selected for
   reuse.
5. `[virtual_sitesn]` stores one site index, one function, and a variable count of
   parent indices. Parent indices are exposed separately from numeric parameters.
6. Every async load has a generation/token check. Older mapping, state, or preview
   responses cannot replace newer selection state.
7. Missing analysis values render as `n/a` or `—`; zero is shown only when the
   source explicitly records numeric zero.
8. Existing routes, storage paths, run snapshots, hashes, and HTTP response shapes
   stay compatible unless an additive field or query filter is required.

## Backend design

`dashboard/models/mappings.py` owns one canonical `mapping_identity(mapping)`
helper and includes `mapping_hash` in candidate summary/detail records. The helper
uses the current identity fields, preserving compatibility with existing saved
states. `dashboard/models/bonded_states.py` calls this helper instead of keeping
duplicate hash expressions.

`GET /api/bonded-states` accepts the existing optional `mapping_hash` filter. The
frontend sends the selected mapping hash, so state selectors show only compatible
states. Summary records retain status and origin; detail records retain full
topology and revisions.

`parse_interactions()` returns records with `indices`, display `beads`,
`function`, `parameters`, and for virtual sites a `parents` index list plus
`parent_beads`. Numeric parent indices do not enter ordinary parameter display.
The parser supports `[virtual_sitesn]` and `[virtual_sites3]` without changing
records for bonds, constraints, angles, or dihedrals.

`revise()` gets explicit modes. `in_place=False` creates a new state with a new
ID, revision 1, `parent_state_id`, and `parent_revision`; source state file and
revisions remain unchanged. `in_place=True` appends a revision to the same state
only when `expected_revision` matches. Both paths validate mapping identity and
payload shape before atomic write. The PATCH endpoint returns the created/current
record and maps stale revisions to HTTP 409.

## Frontend design

`bonded.js` derives the selected mapping hash from the loaded candidate, filters
state summaries server-side, and keeps a local generation token across mapping,
state, interaction, and preview requests. Mapping-only previews are labeled
provisional. Complete state previews show exact topology. Load failures clear the
old preview and expose an accessible status message.

The bonded panel adds structured parameter inputs for supported parsed terms and
two actions: “Save as new state” and “Revise selected state”. The default action
posts `in_place:false`; the revise action asks for confirmation and sends the
visible revision as `expected_revision` with `in_place:true`. Invalid values stay
client-visible and are rejected again by the API.

`runs.js` renders distance diagnostics through a numeric formatter that preserves
missing fields. `figures.js` uses indexed figure metadata when available and marks
filename-derived captions as legacy. Captions state metric direction and units
from metadata; no generic score wording is used for a Wasserstein or SASA figure.

## Documentation cleanup

Update maintained references that still use `detergents/DDM` to
`molecules/DDM` where the file is describing current workflow inputs. Preserve
historical reports and archived source text unchanged. Add a short note that the
micelle example path is experimental only when needed for clarity.

## Test strategy

- Unit tests for canonical mapping hashes, virtual-site parsing, save-as-new,
  in-place revision, stale revision rejection, and state payload validation.
- API tests for mapping-filtered state lists, additive mapping hash fields, and
  PATCH mode/concurrency responses.
- Browser tests for mapping changes, state filtering, preview stale-response
  protection, save-as-new, invalid parameter blocking, and missing diagnostic
  values.
- Node syntax checks for all ES modules.
- Full dashboard suite and a fresh isolated Chrome smoke flow. No simulation run.

## Acceptance

- Existing DDM mapping/state records load unchanged.
- Incompatible states never appear in a selected mapping's state list.
- Virtual-site parent links render with bead names and no fake numeric parameters.
- Save-as-new leaves source hash/revision unchanged; in-place requires matching
  revision and creates exactly one new revision.
- Rapid mapping/state changes leave only the newest preview visible.
- Missing diagnostic values show `n/a` or `—`, never `0.000`.
- Focused tests, full tests, JS syntax checks, and isolated browser checks pass.
