# Phase 1: Run Contracts, Clock, and Manifest - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning
**Source:** Authoritative improvement analysis and project initialization

<domain>
## Phase Boundary

Add the immutable, typed facts required by later phases: a run context/clock, source and stage result schemas, diagnostics, deterministic redacted fingerprints, and a versioned run manifest. This phase deliberately does not change current CLI publication mechanics, promote artifacts, alter source adapters, or rewrite existing dated output paths.
</domain>

<decisions>
## Implementation Decisions

### Runtime contracts
- Define contracts with the existing Pydantic v2 dependency and reject unknown persisted-manifest fields.
- Use literal status values: stages use `ok`, `degraded`, `failed`, `skipped`; sources use `ok`, `empty`, `degraded`, `failed`.
- Record source attempts, duration, fetched/accepted counts, error kind/message, and articles in the source contract.
- Record run ID, report date, timezone, started/cutoff/deadline timestamps, configuration fingerprint, stage/source outcomes, artifact-hash slots, and publication slots in a versioned manifest.

### Clock and fingerprints
- Create a single immutable `RunClock` from the configured IANA timezone with injectable fixed time and deadline duration for tests.
- Derive report date and Chinese display date from that clock; do not make Phase 1 call it from existing sources or storage yet.
- Use deterministic SHA-256 fingerprints over canonical JSON and ensure redacted configuration snapshots exclude API keys, secret keys, and values whose key contains `key`, `secret`, `token`, or `password`.

### Compatibility and scope
- New contracts must be additive. Existing `Article`, `fetch_all`, `save_json`, `save_markdown`, CLI commands, and Tavily report keys remain compatible in this phase.
- Tests use no network, fixed clocks/IDs, and temporary paths only.
- One independent implementation commit follows the planning commit; push only `gsd/daily-news-reliability` to Draft PR #8.

### the agent's Discretion
- Exact module names, model field types, helper names, and test fixture layout, provided serialised output is deterministic and contracts stay immutable/strict.
</decisions>

<canonical_refs>
## Canonical References

### Product requirements
- `docs/daily-news-task-improvement-analysis.md` — source design and P0 acceptance criteria.
- `.planning/ROADMAP.md` — Phase 1 boundary, requirements, and success criteria.
- `.planning/REQUIREMENTS.md` — RUN-01, SRC-01, SRC-03, and DEL-01 definitions.

### Existing implementation and patterns
- `config.py` — current Pydantic v2 settings and configured timezone.
- `main.py` — current CLI orchestration and compatibility boundary.
- `sources/base.py` and `sources/__init__.py` — current `Article` and source collection interfaces.
- `utils/storage.py` — current date helper behavior to migrate in later phases.
- `tests/test_config.py` and `tests/test_main_summary.py` — existing fixture/testing conventions.
</canonical_refs>

<specifics>
## Specific Ideas

Persist all times as timezone-aware RFC 3339 strings. A manifest must be readable after a failed later phase and must not contain secrets. The same fixed clock must be usable by all future source, Tavily, title, and filename integration points.
</specifics>

<deferred>
## Deferred Ideas

- Atomic staging/promotion and last-known-good pointer — Phase 2.
- Source execution adapters, retries, recovery/no-op, and gate policy — Phase 3.
- Curation, structured summaries, observability wiring, and enrichment split — Phases 4–6.
</deferred>

---
*Phase: 01-run-contracts-clock-and-manifest*
*Context gathered: 2026-07-10*
