# CG Bond Interactions editor redesign

## Goal

Make the CG Bond Interactions workspace a direct editor for a selected bead
mapping and its saved bonded states. Users should be able to inspect existing
states, generate a provisional bonded draft, select two CG beads in a 3D
diagram, create an interaction, edit its function and parameters, and save a
new immutable state.

The workspace remains a review and preparation tool. Generated or manually
edited parameters are not scientific validation, and no action in this page
approves a model.

## Scope

The page keeps the mapping selector and filters the bonded-state selector by
the exact mapping identity. Its only action buttons are:

1. `Generate automatic bonded state`
2. `Create interaction`
3. `Run short CG validation`
4. `Save as new state`
5. `Delete state`

The old load, create-state, fit, and in-place revision controls are removed
from this workspace. Existing API consumers for state creation, revision, and
short runs remain compatible where they are used by the rest of the workflow.

All edits are local drafts until `Save as new state` is used. Saving always
creates a new state record and leaves the selected source state unchanged.
The current state name is editable as part of the draft. A save is rejected
when the resulting mapping identity does not match the selected mapping, when
the topology is malformed, or when a concurrent revision changed the source
state.

## Workspace layout and interaction model

The top of the workspace contains the mapping selector, the bonded-state
selector, a state summary, and the five actions. The editor body has two
columns on wide screens and one column on narrow screens:

- **Interactions** contains a table of topology terms. Ordinary bonds, angles,
  and dihedrals expose their bead list, interaction kind, function combobox,
  and parameter inputs. Labels explain each parameter's unit and meaning.
  Constraints and virtual-site parent definitions are displayed as read-only
  records because changing them requires rebuilding the mapping topology.
- **Molecular connectivity** contains a Plotly `scatter3d` view of physical CG
  beads and their connectivity. Bead positions are heavy-atom COGs in the
  mapping's molecule coordinate system; virtual sites are placed at the mean
  of their parent beads. Clicking a bead toggles its selection. The selection
  contains at most two beads; selecting a third bead drops the oldest
  selection and reports the two active names. Existing interaction traces and
  the selected table row share the same highlight state.

`Create interaction` requires exactly two selected physical beads. It adds a
new draft bond between them, with function 1 and an initial equilibrium
distance from the displayed COG positions. Duplicate bead pairs are rejected
in the draft. The new row becomes selected so the user can choose its
function and edit its parameters immediately.

The diagram must remain useful when Plotly cannot be loaded: the workspace
shows a bounded error message and leaves the table and API actions available.
The Plotly JavaScript bundle is served from the installed local Plotly package,
not a remote CDN.

## Interaction editing contract

The browser represents each editable term as `{id, kind, indices, beads,
function, parameters}`. Function choices are limited by the term kind and are
shown with plain-language labels. The exact allow-list is the existing bonded
validator contract:

- bonds: function 1 with two parameters
- angles: functions 1, 2, and 10, each with two parameters
- dihedrals: functions 1 and 9 with three parameters, or function 2 with two
  parameters

Changing a function updates the expected parameter count and the input labels.
The server validates the same allow-list and finite numeric ranges; browser
controls are convenience, not the trust boundary. A save sends interaction
updates keyed by parser IDs. The topology writer preserves comments and
unmodified sections while rewriting both function and numeric parameters.

The table explains that `kind` identifies the GROMACS topology section,
`function` selects its potential form, and `parameters` are the values for
that form. This removes the current ambiguity between a term's section,
function number, and numeric values.

## Automatic bonded-state generation

`Generate automatic bonded state` creates a local draft for the selected
mapping. It does not write a state file until the user saves it.

The server validates the submitted schema-3 mapping and its molecule snapshot,
then scans canonical reference `.itp` files under `references/`. It parses
atom bead types and `[ bonds ]` rows, records each source file's SHA-256, and
normalizes each pair as an unordered bead-type pair. For every mapping
connection:

1. Exact bead-type matches are collected from the reference index.
2. The most frequent `(function, length, force constant)` record is selected;
   ties are resolved by source rank, path, and line number.
3. The selected term records its reference paths, hashes, and locator in
   provenance.
4. If no exact pair exists, the generator uses the mapped COG distance in nm,
   function 1, and a bounded provisional force constant. The term is marked
   as a fallback and the draft provenance records the reason.

The generator also derives angle terms for connected triples using the current
mapping geometry, with the existing provisional angle convention. It does not
invent torsions or alter ring constraints and virtual sites. The result is a
complete topology suitable for a short execution check, while its status and
provenance continue to distinguish a generated hypothesis from a calibrated
model.

Reference parsing is read-only and deterministic. Missing or malformed files
are skipped with diagnostics; they cannot cause arbitrary paths to be read,
and an empty reference index does not block the geometry fallback.

## Persistence and API flow

The existing state store remains authoritative and immutable by default:

- `GET /api/bonded-states?mapping_hash=...` lists only compatible states.
- `GET /api/bonded-states/<id>/interactions` returns parser IDs, section kinds,
  bead labels, functions, parameters, and read-only parent data.
- A new automatic draft is produced by a bonded-generation endpoint that
  accepts the validated mapping snapshot and returns topology, parsed terms,
  and provenance without writing.
- `POST /api/bonded-states` accepts a validated mapping plus draft topology or
  interaction terms and creates a new state.
- `PATCH /api/bonded-states/<id>` accepts expected revision, a name, and
  function/parameter updates. The page always uses `in_place: false`, so the
  selected state is copied as a new state.
- `DELETE /api/bonded-states/<id>` keeps the existing confirmation and
  referenced-run guard.

The short validation action continues to submit the selected mapping and
state through the coordinator. It is disabled until a saved state exists and
uses the existing temporary-run lifecycle.

## Error handling and invariants

- Mapping and molecule snapshots are checked server-side before generation or
  save. Changed canonical sources require a reload.
- Interaction bead names must refer to distinct physical beads in the selected
  mapping. Virtual sites cannot receive independent bonds through this UI.
- Function numbers, parameter counts, finite values, and physical ranges are
  validated in the model layer.
- Duplicate terms and duplicate bead pairs are rejected with a user-visible
  message; no partial state is written.
- State saves use the expected revision and preserve source state files. A
  failed write leaves the source state and draft available.
- Plotly selection is capped at two beads and never changes the mapping itself.
- Automatic output carries algorithm version, reference-index hash, source
  file hashes, and fallback diagnostics so a later review can reproduce the
  suggestion.

## Testing and acceptance

Model tests cover reference parsing, deterministic pair selection, geometry
fallbacks, automatic topology generation, function edits, parameter validation,
duplicate-term rejection, and provenance hashes. API tests cover snapshot
validation, draft generation without persistence, save-as-new revision guards,
and mapping-filtered state lists. Browser tests cover the five-button toolbar,
mapping/state filtering, Plotly bead selection capped at two, creating a bond,
editing function and parameters, and saving a new state without mutating its
source.

Acceptance requires the existing non-browser suite and browser suite to pass,
JavaScript syntax checks to pass, `git diff --check` to pass, and GitNexus
`detect-changes --scope all` to report a clean graph after the implementation
commit.

## Non-goals

This change does not fit bonded parameters from trajectories, add scientific
approval, alter mapping assignments, replace the coordinator's validation
workflow, or infer torsions from unrelated reference molecules.
