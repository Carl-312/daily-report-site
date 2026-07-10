# Daily News Reliability

## What This Is

This is a Python 3.12, file-backed daily AI and technology news pipeline. It collects news from configured sources, deduplicates and optionally enriches candidates, creates a Chinese daily summary, and builds a GitHub Pages static site. This milestone makes that pipeline safe to rerun and safe to publish without losing the last known-good edition.

## Core Value

Every scheduled or manual daily run must either atomically publish one complete, quality-gated edition or leave the previously published edition untouched with an actionable record of why it did not publish.

## Requirements

### Validated

- ✓ The CLI collects configured source articles and produces dated JSON, Markdown, and a static site — existing
- ✓ The pipeline supports optional Tavily enrichment with a bounded call budget and diagnostic report — existing
- ✓ AI summarization has provider/model fallback and a deterministic offline mode — existing
- ✓ GitHub Actions can run daily generation, preview non-main runs, and deploy main — existing

### Active

- [ ] Implement transaction-scoped staging, atomic promotion, run manifests, resumability, and last-known-good protection.
- [ ] Implement typed source outcomes, a single run clock/deadline, retry policy, and source-aware publication gates.
- [ ] Implement a shared typed quality pipeline with deterministic selection and a publication quality report.
- [ ] Implement structured, replayable summaries with explicit AI/offline policies and attempt metadata.
- [ ] Implement structured stage observability and split the enrichment/pipeline orchestration into maintainable modules.
- [ ] Validate normal, degraded, all-source failure, summary failure, build failure, and duplicate-run behavior in gray CI.
- [ ] Deliver every change through a gray branch and Draft PR, with passing GitHub Actions at P0, gray-chain, and final-regression checkpoints before merge.

### Out of Scope

- Database, queue, or microservice migration — a small once-daily file pipeline does not require that operational complexity.
- Direct changes to `main` before validation — all implementation and validation occurs from a gray branch and Draft PR.
- Unbounded external retries or hidden degradation — failure semantics must remain explicit and bounded.

## Context

The current pipeline is synchronous and writes date-named files directly. Source exceptions can be indistinguishable from a legitimate empty result, time semantics differ between sources, and the build resets `dist/` before all pages are rendered. Tavily already has useful budget and diagnostic behavior that should be preserved while the surrounding task receives the same explicit result semantics.

The authoritative design input is `docs/daily-news-task-improvement-analysis.md`; the existing `.planning/codebase/` map documents the actual architecture and test seams. The prior analysis document is committed locally as `3fe553a` and must be included in the gray branch/PR.

## Constraints

- **Publication safety**: Any failed or blocked run must retain the last known-good JSON, Markdown, and site output.
- **Compatibility**: Preserve existing CLI behavior where safe; add explicit exit codes and compatible staged recovery paths.
- **Delivery**: Make one independently verifiable commit at a time, push only a gray branch, open a Draft PR, and never directly modify `main`.
- **CI**: GitHub Actions must pass after P0, after gray validation, and after final regression; failures must be repaired and re-run before progressing.
- **Verification**: Gray validation covers normal, degraded, all-source failure, summary failure, build failure, and duplicate execution.
- **Documentation**: Update operation, rollback, architecture, and acceptance evidence as the implementation changes.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use a run-scoped file staging model instead of a database | Daily volume is small; atomic filesystem promotion gives the needed safety with less complexity | — Pending |
| Treat publication as a quality-gated promotion | A completed process is not necessarily a valid report | — Pending |
| Use a single immutable run clock and deadline | Avoid contradictory daily/recency behavior across sources and stages | — Pending |
| Use typed stage/source results and manifests | Operators need durable facts rather than console-only messages | — Pending |
| Deliver from `gsd/daily-news-reliability` via Draft PR | Prevent unvalidated work from touching main | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-10 after initialization*
