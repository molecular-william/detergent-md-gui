# 2026-10-21 — one digest, no bonded-state store, parameterizations owned by their mapping

Decision (user): migrate the stored data; delete `models/bonded/states.py` entirely; refactor so each
parameterization belongs to a bead mapping.

## T1 — one digest, and the stored hashes migrated

Two serializers hash JSON in this tree: `models/mappings/identity.canonical_json` (sorted keys, compact
separators, `allow_nan=False`) and `files.json_sha256` (sorted keys, **default** separators). They were documented as
deliberately separate because three stores already held the default-separator digests.

Which one is compared decides the direction: `mapping_content_hash` (compact) is compared at four sites in
`models/bonded/parameterization.py` and is how a saved revision is found; `snapshot_hash` (default separators) is
written into compositions, into registry fragments and copied into run records, and compared nowhere.

So: `files.json_sha256` becomes the compact serializer, `identity.canonical_json` delegates to it, and every stored
`snapshot_hash`/`composition_snapshot_sha256` is rewritten by a migration that **proves each rewrite** — it recomputes
the *old* digest first and only writes when that equals the stored value.

- [x] `files.canonical_json` is the one serializer; `json_sha256` uses it  (657489a)
- [x] `identity.canonical_json` delegates; a pinned literal proves mapping identities do not move  (657489a)
- [x] `dashboard/cli/migrate_digests.py`: dry run by default, `--apply`, JSON report, idempotent  (657489a)
- [x] tests: registry record, composition record, run copy, unreconstructible record, second run is a no-op  (657489a)
- [x] run it on this workspace: **0 records** carried an old digest (no compositions, no fragment body digests,
      no composition-bearing manifests or job rows), so nothing was rewritten here

## T2 — delete the bonded-state store and its routes

`models/bonded/states.py` (165 lines) is a store plus a façade re-exporting `parse_interactions` and the two
`apply_interaction_*` functions, which live in `models/bonded/__init__.py`. Its routes (`/api/bonded-states`,
`/automatic`, `/<id>`, `/<id>/interactions`, `PATCH`, `DELETE`, `import-legacy`) have no client: the panel talks to
`/api/bonded-parameterizations`, and a run reads a parameterization. The live store here is empty.

- [x] routes deleted (`routes/bonded.py`, `routes/maintenance.py`), tests repointed or deleted  (1667ff5)
- [x] `paths.bonded_states` and `cli/reset_workspace.py` entries gone  (1667ff5)
- [x] `states.py` deleted; `compositions.bonded_state()` and the co`state_id` field with it  (1667ff5)
- [x] AGENTS.md and PROJECT_GUIDE.md say there is no flat store  (1667ff5, corrected in place)

## T3 — a parameterization belongs to one mapping

Today the store is `parameterizations/records/<mapping content hash>.json`, and two saved mappings with identical
content share one record. Under the decision a parameterization belongs to *a* mapping: ownership has to be singular.

Recon (done): reads are already dual-keyed -- `_parameterization_record(content_hash, mapping_hash)` and
`parameterization.matches(record, candidate_hash=, content_hash=)` -- so the panel and the routes can address by mapping
identity without a new payload. What is content-keyed is the *write* path: `_path(mapping)` and `delete(content_hash)`,
and the run side (`readiness()['parameterization']`, `use_parameterization.sh`) resolves by content hash.

The fork, and its cost -- a decision, not work:

  A. address by the saved draft's file (owner).  Two drafts with identical content get separate records. A rename has
     to move the directory, or the revisions are orphaned; `save_draft` renames by writing a new file.
  B. keep content addressing, store `owner`, and give a second mapping with the same content an *empty* record of its
     own (a clone with no revisions), sharing only on an explicit "use this mapping's parameterization".
     Renames keep working; the invariant "one parameterization per mapping" holds by construction of the address.

**Decided: B.** Implementation note from doing it: B's "the second mapping gets its own empty record" is not reachable
while the address is the content hash and a copy is indistinguishable from a rename at the record's level. What B *can*
state is the ownership itself. -- a renamed candidate keeps its
revisions, and content-addressed revision data stays where it is -- while making ownership singular.

- [x] ownership on the record: `owners` claim list, `claim`, `release`, delete-by-claim  (this commit)
- [x] **closed by the owner's rule instead**: a second saved copy of one content is refused outright (`c8620be`),
      so there is no second mapping to inherit or to give an empty record to; a rename is an in-place save and keeps its
      revisions
- [x] delete-mapping cascade releases the claim, and the last claim takes revisions, fits and work  (this commit)
- [ ] runs consuming a parameterization record which mapping it belonged to
