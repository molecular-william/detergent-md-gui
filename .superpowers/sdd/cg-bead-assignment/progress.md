# SDD ledger — plan: docs/superpowers/plans/2026-09-18-cg-bead-assignment.md

## Workspace ruling

Ruling: Git/worktree setup is unavailable because this checkout has no `.git`; use the shared workspace, avoid destructive operations, preserve canonical/runtime files, and review each task from scoped file lists plus fresh tests. Cost if wrong: parallel edits or rollback proof could be weaker than a committed worktree.

## Preflight scan

| Scope | Shared interface/files | Finding | Ruling |
|---|---|---|---|
| 1→2 | `mapping_context.py` → `depiction.py` | Context must expose verified atoms/bonds/snapshot before scene rendering. | Use explicit `build_context` and `build_scene(context)`; no reverse import. |
| 1→3 | context snapshot → mapping schema/identity | Candidate identity cannot be computed before source hashes exist. | Task 1 owns snapshot; Task 3 consumes exact snapshot fields. |
| 1→4 | context/source hashes → reference index | Suggestions need source integrity and molecule graph. | Reference index stays read-only; context carries source capability. |
| 3→5 | schema 3 candidate → automatic preview | Automatic preview must produce candidate data without file identity. | Preview has no `file`, UUID, timestamp, or write. |
| 3→6 | bead schema → TC4 ring site | Generic ring site must not trigger sugar scaling. | `ring_site_preview` separates generic TC4 from verified sugar entries. |
| 3→7 | identity/validation → HTTP routes | Routes must reject stale/cross-molecule payloads before writes. | Recompute context and hashes server-side. |
| 3→8 | identity → execution/bonded reuse | Existing inline legacy hash must not diverge. | Use `mappings.mapping_identity`; preserve legacy hashes for legacy records. |
| 7→9 | API context → browser scene | Browser needs canonical graph and stable display coordinates. | API returns context/scene additively; client never owns chemistry. |
| 9→10 | editor state → grouping/site controls | UI mutations must be atomic and dependency-aware. | Pure state helpers clone, preflight, then publish. |
| 7→11 | preview API → local editor | Preview must not overwrite manual edits or persist implicitly. | Separate preview document and generation token. |
| 8→12 | run compatibility → final proof | Non-DDM mapping must not imply CG execution. | Preserve DDM adapter gate; final tests assert rejection. |

## Task consistency scan

| Task | Self-consistency result |
|---|---|
| 1 | Context fixture IDs/units and output contract agree. |
| 2 | Scene fallback and explicit-context depiction contract agree. |
| 3 | Empty drafts are saveable, usable gates block exports; identity fields agree. |
| 4 | Source precedence and read-only provenance agree. |
| 5 | Deterministic baseline and no-write preview agree. |
| 6 | Generic TC4 warning and sugar-specific scaling agree. |
| 7 | Endpoint status codes and snapshot guard agree. |
| 8 | Export/reuse gates and DDM-only execution agree. |
| 9 | SVG scene and local state ownership agree. |
| 10 | Confirmed transfer and dependency safety agree. |
| 11 | Preview/discard/save lifecycle agrees with immutable persistence. |
| 12 | Verification and rollback constraints agree with no-Git workspace. |

Ruling: No load-bearing plan conflict found. Proceed in numbered order; task reviewers must flag any implementation conflict.

Task 1: dispatched to /root/task1_context; brief `.superpowers/sdd/cg-bead-assignment/task-1-brief.md`.

Inline completion ledger (2026-09-18):

- Tasks 1–7: context, depiction, schema 3 identity, references, suggestions,
  TC4 preview, scoped API and stale guards implemented and tested.
- Task 8: schema 3 export includes molecule snapshot; coordinator bonded checks
  use `mappings.mapping_identity`; DDM execution gate remains unchanged.
- Tasks 9–11: molecule selector, canonical interactive SVG, keyboard/heavy atom
  selection, local grouping confirmation, suggestions, TC4 preview, automatic
  no-write preview and explicit save controls added. Legacy DDM editor retained.
- Task 12: focused backend (18 passed), non-browser dashboard (178 passed),
  browser dashboard (13 passed), and JavaScript syntax checks passed. No
  simulation launched. No canonical input or runtime output changed.
