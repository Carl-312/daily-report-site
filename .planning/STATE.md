# Project State: Daily News Reliability

## Current Position

**Milestone:** v1 — Safe Daily Publication
**Current Phase:** 1 — Run Contracts, Clock, and Manifest
**Status:** Ready to plan
**Current Plan:** Not started
**Branch:** `gsd/daily-news-reliability`
**Delivery Target:** Draft PR #8

## Milestone Progress

| Phase | Status | Plans | Progress |
|-------|--------|-------|----------|
| 1. Run Contracts, Clock, and Manifest | Ready to plan | 0 | 0% |
| 2. Transactional Staging and Promotion | Pending | 0 | 0% |
| 3. Source Execution, Recovery, and P0 Checkpoint | Pending | 0 | 0% |
| 4. Deterministic Curation and Stage Observability | Pending | 0 | 0% |
| 5. Structured, Replayable Summaries | Pending | 0 | 0% |
| 6. Shared Orchestration and Enrichment Boundaries | Pending | 0 | 0% |
| 7. Gray Validation, Final Regression, and Acceptance Evidence | Pending | 0 | 0% |

## Fixed Delivery Gates

- Work one independently verifiable commit at a time on the gray branch; only Draft PR #8 receives pushes.
- P0 GitHub Actions must pass after Phase 3 before proceeding to later phases.
- Gray scenarios and their GitHub Actions checkpoint must pass in Phase 7 before final regression begins.
- Final regression GitHub Actions must pass before the PR can leave draft status or merge to `main`.
- Failed or blocked runs must preserve the last known-good JSON, Markdown, and site artifacts throughout all phases.

## Current Focus

Define the Phase 1 implementation plan for typed run contracts, a single immutable clock, and manifest persistence. Do not introduce transactional promotion until Phase 2.

## Decisions

- Keep the pipeline file-backed and single-process; use run-scoped staging and atomic filesystem promotion rather than a database or queue.
- Treat publication as a quality-gated promotion, not as a side effect of a completed command.
- Use a configured-timezone immutable run clock as the sole source of report-date, cutoff, and deadline semantics.
- Preserve established Tavily policy behavior while surrounding it with typed contracts before modularizing it.

## Blockers

None identified. GitHub Actions checkpoint evidence is pending implementation and cannot be claimed before the required phases complete.

## Last Activity

2026-07-10: Created v1 roadmap, phase traceability, and delivery-gate state from the authoritative improvement analysis.

---
*Last updated: 2026-07-10*
