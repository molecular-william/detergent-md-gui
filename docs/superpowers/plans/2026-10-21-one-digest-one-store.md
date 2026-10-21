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

- [ ] `files.canonical_json` is the one serializer; `json_sha256` uses it
- [ ] `identity.canonical_json` delegates; a pinned literal proves mapping identities do not move
- [ ] `dashboard/cli/migrate_digests.py`: dry run by default, `--apply`, JSON report, idempotent
- [ ] tests: registry record, composition record, run copy, unreconstructible record, second run is a no-op
- [ ] run it on this workspace; record the counts

## T2 — delete the bonded-state store and its routes

`models/bonded/states.py` (165 lines) is a store plus a façade re-exporting `parse_interactions` and the two
`apply_interaction_*` functions, which live in `models/bonded/__init__.py`. Its routes (`/api/bonded-states`,
`/automatic`, `/<id>`, `/<id>/interactions`, `PATCH`, `DELETE`, `import-legacy`) have no client: the panel talks to
`/api/bonded-parameterizations`, and a run reads a parameterization. The live store here is empty.

- [ ] routes deleted (`routes/bonded.py`, `routes/maintenance.py`), tests repointed or deleted
- [ ] `paths.bonded_states` and `cli/reset_workspace.py` entries gone
- [ ] `states.py` deleted; importers use `models/bonded` directly
- [ ] AGENTS.md sentence corrected ("bonded states are its revisions" describes a concept, not a store)

## T3 — a parameterization belongs to one mapping

Today the store is `parameterizations/records/<mapping content hash>.json`, and two saved mappings with identical
content share one record. Under the decision a parameterization belongs to *a* mapping: ownership is by mapping
identity, not by content, and deleting the mapping must take its parameterizations with it.

- [ ] re-express ownership (mapping identity in the record, not only the content hash)
- [ ] a mapping whose content matches another's does not inherit its revisions
- [ ] delete-mapping cascade covers its own revisions, fits and work directories
- [ ] runs consuming a parameterization record which mapping it belonged to
