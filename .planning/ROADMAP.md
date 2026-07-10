# Roadmap: Daily News Reliability

## Milestone: v1 — Safe Daily Publication

Deliver a file-backed daily-news pipeline that atomically publishes only a complete, quality-gated edition, preserves the last known-good edition on every failed or blocked run, and provides durable, actionable run evidence.

**Delivery guardrails for every phase:** work only on `gsd/daily-news-reliability`; use one independently verifiable commit per change; push the gray branch and update Draft PR #8 only; never push or merge application changes directly to `main`. A failed required GitHub Actions check is repaired and re-run before any subsequent phase work.

### Phase 1: Run Contracts, Clock, and Manifest

**Goal:** Establish the typed, durable run facts that all later stages use, without changing publication mechanics.

**Depends on:** None

**Requirements:** RUN-01, SRC-01, SRC-03, DEL-01

**Success criteria:**

1. Every CLI invocation creates a run ID and immutable `RunClock` whose configured timezone and deadline are available to all pipeline stages.
2. A versioned, redacted `DailyRunManifest` persists the run clock, configuration fingerprint, stage states, source outcome schema, diagnostics, and artifact-hash slots.
3. Report dates, filenames, titles, source freshness inputs, and Tavily timestamps can consume the same run clock rather than creating their own current-time values.
4. The gray branch contains the committed analysis document and all Phase 1 changes are independently testable on Draft PR #8, with no direct `main` modification.

### Phase 2: Transactional Staging and Promotion

**Goal:** Make staged outputs and atomic promotion the only way a complete edition reaches public artifacts.

**Depends on:** Phase 1

**Requirements:** RUN-02, RUN-03, RUN-04, QUAL-01

**Success criteria:**

1. JSON, Markdown, and site files are written only under a run-scoped staging directory until required stages and publication gates pass.
2. Promotion atomically exposes one coherent edition and retains readable last-known-good metadata and artifacts for rollback/recovery.
3. Failed, interrupted, summary-failed, and build-failed runs return stable non-zero exit codes while preserving public artifact hashes.
4. Publication rejects all-source failure, zero accepted articles, required-summary failure, render/build failure, and mandatory gate failure before promotion.

### Phase 3: Source Execution, Recovery, and P0 Checkpoint

**Goal:** Turn source execution into bounded, source-aware results and finish the P0 reliability baseline before gray scenario validation.

**Depends on:** Phase 2

**Requirements:** RUN-05, RUN-06, SRC-02, SRC-04, QUAL-02

**Success criteria:**

1. Source runs distinguish legitimate empty responses from network, HTTP, configuration, and parser failures, with the manifest recording status, counts, attempts, duration, and classified error.
2. Retryable source failures use bounded retry/backoff and per-source time budgets; configuration errors are not retried and the publication reserve remains available.
3. A staged run resumes by run ID from a completed checkpoint without re-fetching accepted input, and an equivalent already-published run is a hash-preserving no-op.
4. A partial-source or optional-enrichment failure is published only as an explicit degraded edition after article-count, recency, diversity, and degradation-policy gates pass.
5. The P0 GitHub Actions checkpoint is green on Draft PR #8; any failure is fixed and re-run before Phase 4 begins.

### Phase 4: Deterministic Curation and Stage Observability

**Goal:** Apply one typed quality pipeline and one stage-result model to every accepted, rejected, degraded, and failed outcome.

**Depends on:** Phase 3

**Requirements:** QUAL-03, OBS-01

**Success criteria:**

1. Every article receives a deterministic accepted/rejected disposition and reason code using shared identity, URL normalization, deduplication, and ranking rules with or without Tavily.
2. The quality report records input/output counts, rejection reasons, source diversity, freshness, verification coverage, and gate decisions used for publication.
3. Every pipeline stage exposes the same typed status, duration, metrics, and diagnostics in both the manifest and human-readable CLI output.
4. Tests prove deterministic curation and that optional enrichment cannot silently bypass the shared quality policy.

### Phase 5: Structured, Replayable Summaries

**Goal:** Replace Markdown-shaped summary semantics with validated structured summaries and deterministic rendering.

**Depends on:** Phase 4

**Requirements:** SUM-01, SUM-02

**Success criteria:**

1. Every published summary item links to an input article and deterministic local rendering produces the published Markdown from the structured result.
2. The manifest records provider/model, redacted attempt outcomes, input and prompt fingerprints, validation result, and the selected summary policy.
3. `required_ai`, `allow_offline`, and `offline` yield explicit, tested manifest states and CLI exit behavior; zero articles are rejected before summary generation.
4. A saved structured summary can be replayed without another model call and renders the same Markdown artifact hash.

### Phase 6: Shared Orchestration and Enrichment Boundaries

**Goal:** Consolidate pipeline orchestration and split enrichment internals without changing established policy behavior.

**Depends on:** Phase 5

**Requirements:** OBS-02

**Success criteria:**

1. CLI commands share a single composition path for collection, curation, summary, rendering, manifesting, and publication decisions.
2. Enrichment has separate typed model, normalization, policy, transport, verification/refill, and thin orchestration boundaries.
3. Characterization tests preserve Tavily budgets, diagnostics, fallback behavior, and curation/report invariants through the split.

### Phase 7: Gray Validation, Final Regression, and Acceptance Evidence

**Goal:** Prove operational safety in gray CI, complete final review and rollback acceptance, and record merge-ready evidence.

**Depends on:** Phase 6

**Requirements:** DEL-02, DEL-03, DEL-04

**Success criteria:**

1. Draft PR #8 has a passing gray-scenario GitHub Actions checkpoint covering normal, degraded, all-source failure, summary failure, build failure, and duplicate-run/no-op, each proving last-known-good preservation where publication is blocked.
2. A final regression GitHub Actions checkpoint passes after the gray checkpoint and before any main merge; failed checks are repaired and re-run.
3. Full tests, code review, generated run artifacts, atomic-promotion behavior, and rollback/recovery procedure are accepted against the documented evidence.
4. Architecture, operations, rollback, validation evidence, review outcome, and accepted commit IDs are documented; only then may the Draft PR be made merge-ready and merged to `main`.

## Requirement Coverage

| Requirement | Phase |
|-------------|-------|
| RUN-01 | 1 |
| SRC-01 | 1 |
| SRC-03 | 1 |
| DEL-01 | 1 |
| RUN-02 | 2 |
| RUN-03 | 2 |
| RUN-04 | 2 |
| QUAL-01 | 2 |
| RUN-05 | 3 |
| RUN-06 | 3 |
| SRC-02 | 3 |
| SRC-04 | 3 |
| QUAL-02 | 3 |
| QUAL-03 | 4 |
| OBS-01 | 4 |
| SUM-01 | 5 |
| SUM-02 | 5 |
| OBS-02 | 6 |
| DEL-02 | 7 |
| DEL-03 | 7 |
| DEL-04 | 7 |

**Coverage:** 21/21 v1 requirements mapped exactly once; 0 unmapped; 0 duplicate mappings.

## Milestone-wide Acceptance Gates

1. The three non-optional GitHub Actions checkpoints are ordered: P0 baseline after Phase 3, gray scenarios in Phase 7, then final regression in Phase 7.
2. The gray branch and Draft PR remain the sole delivery path until all Phase 7 evidence is accepted.
3. Each implementation commit remains independently verifiable and rollback-safe; planning/documentation commits do not authorize application changes on `main`.

---
*Created: 2026-07-10*
