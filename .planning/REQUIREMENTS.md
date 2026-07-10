# Requirements: Daily News Reliability

**Defined:** 2026-07-10
**Core Value:** Every run either atomically publishes a complete quality-gated edition or leaves the last known-good edition untouched with an actionable record.

## v1 Requirements

### Run Safety

- [ ] **RUN-01**: An operator can identify every invocation by a persisted run ID, immutable run clock, redacted configuration fingerprint, stage states, diagnostics, and artifact hashes.
- [ ] **RUN-02**: A run writes JSON, Markdown, and site outputs into its own staging directory and does not alter public artifacts before all required stages pass.
- [ ] **RUN-03**: A successful run atomically promotes a coherent edition while retaining a readable last-known-good version for rollback and recovery.
- [ ] **RUN-04**: A failed, interrupted, summary-failed, or build-failed run exits non-zero and cannot overwrite the current published JSON, Markdown, or site.
- [ ] **RUN-05**: An operator can resume a staged run by run ID from a completed checkpoint without re-fetching already accepted input.
- [ ] **RUN-06**: Re-running an already published equivalent input/configuration is a no-op that preserves the published artifact hashes and version.

### Source and Time Contracts

- [ ] **SRC-01**: An operator can see each enabled source's status (`ok`, `empty`, `degraded`, or `failed`), attempts, duration, raw count, accepted count, and classified error in the run manifest.
- [ ] **SRC-02**: Source execution distinguishes a genuine empty response from network, HTTP, configuration, and parser failures.
- [ ] **SRC-03**: All dates, filenames, titles, source freshness checks, Tavily timestamps, and deadlines use one immutable run clock and configured timezone.
- [ ] **SRC-04**: Retryable source failures use bounded retries and cannot consume the run's publication reserve; non-retryable configuration errors are not retried.

### Publication Quality

- [ ] **QUAL-01**: The publication decision rejects all-source failure, zero accepted articles, failed required summary, failed render/build, and failed mandatory quality gates with a stable non-zero exit code.
- [ ] **QUAL-02**: A partial-source or optional-enrichment failure can publish only as an explicit degraded edition after article-count, recency, source-diversity, and degradation-policy gates pass.
- [ ] **QUAL-03**: Every accepted or rejected article has an explicit deterministic disposition/reason and shared identity/deduplication rules regardless of Tavily mode.

### Summary and Observability

- [ ] **SUM-01**: Each published summary is structured, links each item to an input article, and is rendered to Markdown deterministically.
- [ ] **SUM-02**: The manifest records summary provider/model, input and prompt fingerprints, attempt outcomes, validation result, and explicit `required_ai`, `allow_offline`, or `offline` policy.
- [ ] **OBS-01**: Every stage emits the same typed status, duration, metrics, and diagnostics model, which powers both JSON manifest and human-readable CLI output.
- [ ] **OBS-02**: Pipeline orchestration is shared by CLI commands and enrichment responsibilities are split into policy, transport, and orchestration boundaries.

### Delivery and Verification

- [ ] **DEL-01**: Changes are committed in independently testable units on a gray branch and delivered through Draft PR #8; `main` is not changed directly.
- [ ] **DEL-02**: GitHub Actions has passing, non-optional P0 contract, gray scenario, and final regression checkpoints before merge.
- [ ] **DEL-03**: Gray validation proves normal, degraded, all-source failure, summary failure, build failure, and duplicate-run/no-op behavior while preserving last-known-good artifacts.
- [ ] **DEL-04**: Documentation records architecture, operation, rollback procedure, validation evidence, review, and final accepted commit IDs.

## v2 Requirements

### Scalability

- **SCALE-01**: Source adapters execute concurrently with bounded worker pools after their typed contracts and timeout behavior have characterization coverage.
- **SCALE-02**: Additional external providers can add structured summary schemas without changing publication policy.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Database, message queue, or microservices | The once-daily, low-volume job gains sufficient safety from transactional filesystem state. |
| Direct production deployment from a pull request | Gray runs must only produce diagnostics/artifacts; deployment remains main-only. |
| Silent fallback from required AI summary | Publication quality policy must be explicit and auditable. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RUN-01 | Phase 1 | Pending |
| RUN-02 | Phase 2 | Pending |
| RUN-03 | Phase 2 | Pending |
| RUN-04 | Phase 2 | Pending |
| RUN-05 | Phase 3 | Pending |
| RUN-06 | Phase 3 | Pending |
| SRC-01 | Phase 1 | Pending |
| SRC-02 | Phase 3 | Pending |
| SRC-03 | Phase 1 | Pending |
| SRC-04 | Phase 3 | Pending |
| QUAL-01 | Phase 2 | Pending |
| QUAL-02 | Phase 3 | Pending |
| QUAL-03 | Phase 4 | Pending |
| SUM-01 | Phase 5 | Pending |
| SUM-02 | Phase 5 | Pending |
| OBS-01 | Phase 4 | Pending |
| OBS-02 | Phase 6 | Pending |
| DEL-01 | Phase 1 | Pending |
| DEL-02 | Phase 7 | Pending |
| DEL-03 | Phase 7 | Pending |
| DEL-04 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 21
- Unmapped: 0 ✓

---
*Requirements defined: 2026-07-10*
*Last updated: 2026-07-10 after initialization*
