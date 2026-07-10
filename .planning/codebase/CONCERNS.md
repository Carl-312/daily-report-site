# Codebase Concerns: Stable Daily News Execution

## Scope

This assessment is intentionally limited to `README.md` and the selected core pipeline files. It focuses on operational stability and an elegant daily-news execution model, not UI or test coverage.

## P0 - A Run Can Publish Partial or Empty Input Without a Clear Failure Contract

**Evidence:** `sources/__init__.py:52-70` catches every source exception, prints it, and returns whatever other sources produced. `sources/aibase.py:91-125` and `sources/syft.py:25-64` additionally convert all detail/API failures into empty lists before the registry can observe them. `main.py:97-143` has no required-source policy, minimum candidate gate, or explicit zero-input decision before saving/building. In offline mode, `summarizer.py:227-243` can turn zero input into a superficially valid interaction-only report.

**Impact:** A DNS outage, parser regression, expired Syft credential, and a genuinely quiet news day are indistinguishable. The job may look successful while coverage is badly degraded, which conflicts with the zero-manual-intervention promise in `README.md:7-12`.

**Mitigation:** Make `fetch_all` return a typed `FetchBatch` containing articles plus per-source status (`success`, `empty`, `timeout`, `parse_error`, `auth_error`) and latency. Define an explicit publication policy: required-source quorum, minimum usable article count, and maximum tolerated source failure ratio. On failure, exit non-zero and retain yesterday's published site; optionally allow a separately labeled degraded edition only through an explicit policy flag.

## P0 - Outputs Are Mutated In Place Before the Whole Edition Is Valid

**Evidence:** `main.py:115-125` overwrites the day's JSON before summarization; `main.py:127-143` can then fail after that write. `utils/storage.py:34-40` and `utils/storage.py:52-65` write directly to final paths. `build.py:234-253` removes the complete output directory before rebuilding, then writes article pages, index, and archive incrementally at `build.py:266-314`.

**Impact:** A killed process, disk error, malformed Markdown, or provider failure can leave a mixed state: new JSON with old Markdown, a truncated final file, or a partially rebuilt/empty `dist`. Re-running is overwrite-based rather than transaction-like, and there is no durable marker identifying the last complete edition.

**Mitigation:** Introduce a run-scoped staging directory such as `.runs/<report-date>/<run-id>/`. Write JSON and Markdown through temp files plus `fsync`/`os.replace`; build the complete site into a sibling staging directory; validate expected files and counts; then atomically promote a small manifest or directory pointer. Preserve the previous known-good build until promotion succeeds. Record input/config hashes so a retry can reuse completed stages and produce the same edition.

## P0 - Retry and Recovery Are Not Bounded by a Job-Level Deadline

**Evidence:** `sources/base.py:50-61` creates a plain `requests.Session` and performs one GET with a fixed timeout but no retry/backoff. Syft similarly makes one 30-second request at `sources/syft.py:30-42`. Tavily makes one POST per call at `utils/news_enrichment.py:485-502`; verification is sequential at `utils/news_enrichment.py:984-1038`, and refill is sequential at `utils/news_enrichment.py:1160-1189`. The default call budget is seven (`config.py:113-120`) and each Tavily call can consume 45 seconds (`utils/news_enrichment.py:23-28`). LLM clients are created without an application deadline at `summarizer.py:19-21`, while fallback only happens after an attempt raises at `summarizer.py:168-201`.

**Impact:** Transient 429/5xx/network failures immediately reduce coverage, while the enrichment worst case can spend several minutes serially. Conversely, an SDK-level LLM wait is not constrained by the daily job's remaining time. A delayed scheduled run (`README.md:57-60`) has no way to shed optional work and finish before its publication objective.

**Mitigation:** Give the pipeline one monotonic deadline and pass remaining time into each stage. Add narrowly scoped retries for connect/read timeout, 429, and retryable 5xx with exponential backoff, jitter, and `Retry-After`; never retry auth and schema errors. Cap attempts per source/provider, run independent source fetches concurrently with bounded workers, and stop optional verification/refill when the publication reserve is reached. Persist stage results so a rerun resumes from successful fetches rather than refetching everything.

## P1 - Time Semantics Are Inconsistent and Some Freshness Checks Are Incorrect

**Evidence:** A configurable timezone exists at `config.py:50-51`, but storage hard-codes UTC+8 at `utils/storage.py:12-24`, sources define separate timezone objects (`sources/aibase.py:14-22`, `sources/techcrunch.py:13-14`, `sources/theverge.py:13`), and enrichment hard-codes `Asia/Shanghai` at `utils/news_enrichment.py:23`. `main.py:91-94` derives the report date independently from later date/title calls at `main.py:131-133`. TechCrunch and The Verge accept any future date because `(now - pub_date).days <= 1` at `sources/techcrunch.py:113-123` and `sources/theverge.py:101-109` has no lower bound. TechCrunch also hard-codes accepted URL years through 2026 at `sources/techcrunch.py:77-84`. AIBase only recognizes `...号` in content and slices publish timestamps before parsing at `sources/aibase.py:214-235`, making valid date variants fragile.

**Impact:** Runs around midnight or delayed schedules can mix report dates and rolling windows. Future-dated content can pass, valid current content can disappear, and TechCrunch ingestion is set to age out when 2027 URLs arrive.

**Mitigation:** Create one immutable `RunContext` at process start with `report_date`, timezone, `window_start`, `window_end`, run ID, and deadline. Pass it to every source and enrichment stage. Parse source timestamps into timezone-aware datetimes, use a half-open interval `[window_start, window_end)` plus a small explicit future-skew allowance, and derive URL years dynamically. Decide whether the product is a calendar-day edition or a rolling 24-hour edition and encode that single rule everywhere.

## P1 - CLI Exit Codes and Logs Cannot Reliably Drive Automation

**Evidence:** Source failures are reduced to unstructured prints at `sources/__init__.py:63-68`. `cmd_summarize` returns normally when data is missing at `main.py:184-203`, so automation receives success. `cmd_test` ignores the boolean returned by `test_connection` at `main.py:214-216`, while `summarizer.py:246-274` returns `False` after total provider failure. The main success banner at `main.py:145-150` reports only counts/paths; the richer enrichment report is printed only as a few counters at `main.py:37-64`.

**Impact:** GitHub Actions can distinguish uncaught exceptions, but not no-data, missing-input, all-source-empty, or failed connection-test outcomes. Historical diagnosis depends on ephemeral console text without a run ID, per-stage duration, source error class, freshness distribution, or publication state.

**Mitigation:** Define stable exit codes and terminal run states (`published`, `degraded`, `skipped`, `failed`). Emit one structured JSON event per stage and a final run manifest with source outcomes, durations, retry counts, article counts before/after each filter, oldest/newest timestamp, provider/model used, and promoted artifact hash. Keep human-readable console summaries, but derive them from the same typed result objects.

## P1 - Enrichment Fail-Open Logic Can Silently Change or Lose the Candidate Set

**Evidence:** Verification only processes `candidates[:verify_budget]` at `utils/news_enrichment.py:984-1038`; skipped candidates are counted at `utils/news_enrichment.py:1109-1118` but are not included in `verified_output_articles`, which contains only preserved transport errors and verified articles at `utils/news_enrichment.py:1473-1478`. A broad outer catch at `utils/news_enrichment.py:1653-1667` treats programming/invariant errors the same as recoverable service errors and falls back to all original deduped articles. Verification transport errors are preserved, while a successful response with no/missing-date match rejects the original at `utils/news_enrichment.py:1039-1107`.

**Impact:** Enabling enrichment can drop valid articles solely because of call-budget allocation, yet a code defect can abruptly restore the entire unverified set. These asymmetric semantics are difficult to explain, monitor, and replay.

**Mitigation:** Separate `transport_status` from `validation_status`, and make every input candidate end in exactly one explicit disposition. Keep budget-skipped candidates under a documented policy (preserve, quarantine, or reject), rather than omission. Catch only recoverable Tavily errors at stage boundaries; let invariant/programming errors fail the run. Persist the disposition ledger and make final selection a pure deterministic function over it.

## P1 - Configuration Accepts Invalid Operational Values and Is Not Snapshotted

**Evidence:** Numeric and path fields have defaults but no bounds at `config.py:48-67` and `config.py:108-133`; negative call budgets, zero article targets, or nonsensical hour windows are therefore representable. `MODELSCOPE_MAX_OUTPUT` is converted with raw `int(...)` before Pydantic validation at `config.py:142-162`. `.env` is loaded with `override=True` at `config.py:14-15`, which can unexpectedly replace process environment values. Configuration is cached globally at `config.py:194-203`, while paths are relative to the current working directory (`config.py:63-67`, `build.py:141-152`).

**Impact:** A typo can fail startup unclearly or produce a logically valid but unsafe run. Reproduction is weak because the exact effective non-secret configuration and config fingerprint are absent from the edition metadata.

**Mitigation:** Add Pydantic constraints and cross-field validation: positive timeouts/output size, `0 <= max_verify_calls <= max_total_calls`, sensible freshness windows, non-empty enabled sources, and paths resolved from the project/config location. Parse environment values through the settings layer, avoid overriding explicit process environment by default, and store a redacted effective-config snapshot/hash in the run manifest.

## P2 - Core Selection Logic Is Too Dict-Heavy and Monolithic to Evolve Safely

**Evidence:** `utils/news_enrichment.py` combines time parsing, relevance rules, clustering, HTTP transport, retry classification, budgeting, stage orchestration, diagnostics, and final selection across lines `117-1667`. The report is a large mutable dictionary initialized at `utils/news_enrichment.py:658-762` and then updated through the orchestration at `utils/news_enrichment.py:1397-1652`. `main.py:89-150` and `main.py:153-181` duplicate fetch/dedupe/enrich/save behavior. Deduplication itself only hashes normalized title plus domain at `utils/dedupe.py:31-41`, so cross-outlet coverage of the same story is left to the optional enrichment path.

**Impact:** Small policy changes require coordinated string-key mutations across distant blocks, making missing fields and inconsistent counters easy. The same story can be represented differently depending on whether enrichment is enabled, and fetch-only/full-run behavior can drift.

**Mitigation:** Extract a shared pipeline service used by `run` and `fetch`. Introduce typed immutable models for `Candidate`, `SourceResult`, `StageResult`, `Disposition`, and `RunManifest`; isolate transport adapters from pure selection policy; and decompose enrichment into verify/refill/finalize stages behind one interface. Make local story clustering/dedup deterministic and always-on, then let enrichment add evidence rather than redefine core identity.

## Recommended Order

1. Define `RunContext`, typed source/stage results, publication gates, and non-zero failure states.
2. Add atomic staging/promotion and a last-known-good manifest.
3. Add deadline-aware retries, bounded concurrency, and resumable stage artifacts.
4. Unify timestamp parsing and calendar/rolling-window policy; remove hard-coded years.
5. Refactor enrichment around a candidate disposition ledger and typed reports.
6. Add structured observability and strict configuration validation.
