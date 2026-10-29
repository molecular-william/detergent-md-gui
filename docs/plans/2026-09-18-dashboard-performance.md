# Dashboard performance implementation

User approved the three-phase recommendation in chat. Preserve run admission,
scientific validation, immutable records, API compatibility and browser drafts.
No data migration or simulation execution. No Git metadata; source backup in /tmp.

1. Lazy tab activation, shared in-flight GET cache with invalidation, New run
   readiness debounce/cancellation, 10-second storage display cache.
2. Add opt-in mapping/bonded summaries; load selected records separately. Cache
   unchanged mapping validation by content/source identity and parsed static inputs.
3. Opt-in compact Runs polling; fetch full records only on expansion. Return all
   figure metadata from one indexed endpoint; stop sequential rescans per page.
4. Prove request counts, payload reductions, invalidation and existing workflows
   using backend and browser tests, plus timings on copied metadata.

Frontend contract: loadOnce(key, loader, {maxAge}), cachedApi(path, {maxAge}),
invalidateResource(prefix) in shared.js; invalidation emits dashboard:resources-changed.
Tabs dispatch dashboard:tab with detail.id for mouse/keyboard/hash/programmatic
navigation. Modules return mount() and retain edits across activation.
Mapping summary GET /api/mappings?view=summary returns candidates with file/name/
status/sha256/validation summary, no bead graph. GET /api/mappings/context returns
molecule and bead_types. Detail GET unchanged. Bonded summary GET
/api/bonded-states?view=summary omits topology/revisions; detail GET unchanged.

- [x] Tab/New run frontend
- [x] Mapping/bonded frontend
- [x] Backend summaries/caches and Runs integration
- [x] Regression/browser verification and measurements

Completed 2026-09-18. Full suite: 164 passed, 15 existing warnings (baseline:
155 passed, 15 warnings). Includes 12 browser tests using isolated stores and
loopback servers; no simulations were launched. All nine JavaScript modules
passed Node syntax checks. Browser plugin unavailable; used installed Python
Playwright with Chrome. Checked desktop/mobile interactions and screenshots.

Measured with a SQLite backup and copied mapping/bonded/manifest metadata in a
temporary workspace. Bytes below compare the existing full API with its summary
view on the same data. Warm times are medians of seven subsequent requests:

| API | Full bytes | Summary bytes | Warm summary time |
|---|---:|---:|---:|
| Mappings | 143183 | 6263 | 2.18 ms |
| Bonded states | 105040 | 5782 | 1.15 ms |
| Runs (page 1) | 63867 | 2712 | 4.46 ms |

The first mapping summary took 253 ms including cold scientific imports and
validation. These are local server timings, not end-to-end tab latency. Compact
Runs reduces transfer/rendering work, not measured server processing time.
Evidence: `/tmp/dashboard-performance-final.log`,
`/tmp/dashboard-performance-measurements.json`, `/tmp/ddm-dashboard-runs.png`,
and `/tmp/ddm-dashboard-mappings.png`. Runtime data and canonical inputs were
unchanged; no migration or cleanup was needed.
