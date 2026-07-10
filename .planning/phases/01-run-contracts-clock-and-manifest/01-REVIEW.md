---
phase: 01-run-contracts-clock-and-manifest
reviewed: 2026-07-10T00:00:00Z
depth: deep
files_reviewed: 22
files_reviewed_list:
  - .github/workflows/deploy.yml
  - build.py
  - config.py
  - config.yaml
  - main.py
  - sources/__init__.py
  - sources/aibase.py
  - sources/base.py
  - sources/syft.py
  - sources/techcrunch.py
  - sources/theverge.py
  - summarizer.py
  - tests/test_publication.py
  - tests/test_run_clock.py
  - tests/test_summarizer.py
  - utils/enrichment_policy.py
  - utils/enrichment_refill.py
  - utils/enrichment_transport.py
  - utils/enrichment_verification.py
  - utils/news_enrichment.py
  - utils/publication.py
  - utils/run_contracts.py
findings:
  critical: 1
  warning: 6
  info: 2
  total: 9
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-07-10T00:00:00Z  
**Depth:** deep  
**Files Reviewed:** 22  
**Status:** issues_found

## Summary

The review covered `04306f8..HEAD` plus the current uncommitted enrichment split, including the production path, publication pointer/reader contract, deadlines, summary provenance, source call chains, CI workflows, and reliability tests. The code imports cleanly and the full test suite passes (`73 passed`), but several failure-path contracts are not enforced in production. The most serious issue is that the standalone build command can delete the currently selected public edition before rebuilding it, exposing a partial or empty site despite the atomic pointer design.

## P0 — Critical Issues

### CR-01: `build` mutates the currently selected public edition in place

**File:** `build.py:150-156,245-266`; `main.py:461-468`

**Evidence:** When no paths are supplied, `resolve_paths()` uses `read_current_edition()` and returns the selected edition's `content_dir` and `site_dir`. `build_site()` then calls `prepare_output_dir(output_dir)`, which recursively removes that `site_dir` before writing new files. `cmd_build()` invokes `build_site()` with no staging or pointer promotion.

**Impact:** A reader resolving `public-version.json` continues to point at the same directory while it is deleted and rebuilt. Readers can observe a missing/partial site, and an interrupted build destroys the last-known-good selected site. This defeats the atomic public-version pointer and violates publication safety.

**Fix:** Never use a pointer-selected edition as a build output. Build into a run-scoped sibling directory, validate it, move it under `editions/`, and atomically replace the pointer. For a legacy-only rebuild, make the output explicitly `dist/` and do not resolve the selected edition's `site_dir` as a writable target.

## P1 — Warnings

### WR-01: Pre-publication failures leave the run manifest pending and non-actionable

**File:** `main.py:265-347`

**Issue:** `cmd_run()` only catches exceptions around `stage_and_publish_run()` at lines 325-347. Fetch deadline failures, source failures that propagate, enrichment exceptions, summary failures, and failures while persisting the summary occur before that `try` block. Those paths never update the manifest to `publication.status="blocked"` with a reason; the run is left as `pending` even though no publication occurred.

**Fix:** Wrap the entire run after manifest creation in one failure handler (or use a `try/finally` with an exception-specific update). On every failure, write a blocked manifest with a scrubbed reason and the stages/sources recorded so far; re-raise after the manifest write.

### WR-02: The run deadline does not bound the complete publication operation

**File:** `main.py:157-205`; `build.py:263-327`

**Issue:** The deadline is checked before staging and at the beginning/per-Markdown iteration of `build_site()`, but not during `copytree`, atomic JSON/Markdown writes, asset copying, final index/archive writes, `promote_staged_edition()`, or `mirror_public_edition()`. After the last build check, a slow filesystem operation or mirror can cross the deadline and the code can still replace the public pointer and legacy paths.

**Fix:** Thread a clock/deadline through every stage boundary, check it before each potentially blocking filesystem operation and immediately before pointer replacement, and refuse promotion once expired. Make mirror refresh either part of a recoverable operation or explicitly post-publication and bounded separately.

### WR-03: `RunDeadlineExceeded` is swallowed by enrichment's fail-open handler

**File:** `utils/news_enrichment.py:1053-1060,1106-1121,1145-1162,1197-1216,1279-1293`

**Issue:** The split verification/refill stages correctly re-raise `RunDeadlineExceeded`, but the outer `except Exception` catches it and converts it into `skip_reason="enrichment_error"`, returning the upstream articles. A deadline breach therefore becomes an ordinary enrichment fallback instead of propagating as a failed/blocked run. This also loses the precise deadline diagnostic.

**Fix:** Add `except RunDeadlineExceeded: raise` immediately before the broad exception handler. If a fail-open result is desired for ordinary Tavily errors, keep it limited to those ordinary errors and record deadline exhaustion as a distinct blocked stage outcome.

### WR-04: Legacy mirror updates are sequential and have no all-path rollback

**File:** `utils/publication.py:152-175`; `main.py:192-205`

**Issue:** The authoritative pointer is replaced first, then `data`, `content`, and `site` legacy directories are copied/replaced one at a time. A failure or interruption between replacements leaves legacy readers with a mixture of editions. The backup directories are overwritten on each individual path and there is no journal that can restore all three paths as one operation.

**Fix:** Either remove legacy paths from all cross-artifact readers and document them as best-effort compatibility mirrors, or make the mirror itself a journaled transaction with a complete old/new set and startup recovery. At minimum, do not let any reader use legacy paths as a fallback for a cross-path publication view without an explicit degraded status.

### WR-05: Summary provenance trusts model-generated URLs and renders unescaped model text

**File:** `summarizer.py:249-270`; `utils/summary_contracts.py:49-56`

**Issue:** `_parse_summary_result()` accepts any `http://` or `https://` URL emitted in a model Markdown item and stores it as the `SummaryItem.url`; only non-link items are associated positionally with input articles. The deterministic renderer then emits title, URL, summary, and discussion text without escaping or checking that the URL belongs to an input article. A successful model response can therefore carry fabricated article provenance and inject arbitrary markup into the generated static page.

**Fix:** Treat model text as untrusted: identify items by an input article ID or validated input URL, reject URLs not present in the input set, and escape title/summary/topic at the HTML/Markdown boundary. Keep the original article URL and title as the authoritative provenance fields.

### WR-06: External/news content can become stored-site HTML without an output sanitization boundary

**File:** `build.py:197-231,235-242,305-327`

**Issue:** Markdown is converted with raw HTML allowed, and article titles/dates are interpolated directly into HTML templates. The pipeline consumes source-derived text and model-derived summaries, so a malicious or malformed title/body can produce executable HTML/attributes in the published GitHub Pages site. The new staged publication path makes this content publishable as a complete edition but adds no sanitization.

**Fix:** Escape all template fields with `html.escape`, configure Markdown sanitization/HTML stripping, and validate generated links against `http`/`https` schemes before rendering. Add a regression test with HTML in a source title and summary.

### WR-07: Persisted enrichment diagnostics can contain unredacted exception text

**File:** `utils/news_enrichment.py:1279-1285`; `main.py:330-345`

**Issue:** The enrichment failure path stores `str(exc)` directly in the report, and publication failure stores `str(exc)` directly in `PublicationState.reason`. `scrub_diagnostic()` exists in `utils/run_contracts.py` but is not applied at either persistence boundary. Provider/client exceptions can include request details or configured credentials, causing secrets to enter JSON/manifests and gray artifacts.

**Fix:** Pass the settings/configuration into a single diagnostic-scrubbing helper before writing reports/manifests, redact known secret values and sensitive fields recursively, and use stable error kinds for public reasons rather than raw exception text.

## P2 — Informational Issues

### IN-01: The atomic pointer is not durable across a crash or workflow checkout

**File:** `utils/storage.py:40-55`; `.github/workflows/deploy.yml:168-181`

**Issue:** `atomic_write_bytes()` fsyncs the temporary file but does not fsync the parent directory after `os.replace()`. In addition, the deploy workflow commits only `content/` and `data/`, not `.publication/public-version.json` or the selected edition. The pointer is therefore atomic for live readers in one process/filesystem run, but not a durable persisted reader contract across power loss or a fresh runner.

**Fix:** Fsync the parent directory after replacement where supported, and choose/document a persistence strategy: commit the pointer/edition, or explicitly reconstruct the pointer from the committed legacy mirror before any reader uses it.

### IN-02: Run manifests are written non-atomically

**File:** `utils/run_contracts.py:320-325`

**Issue:** `write_manifest()` uses `Path.write_bytes()` directly even though the manifest is the recovery/observability record. An interruption can leave invalid JSON and prevent later recovery or diagnosis.

**Fix:** Reuse `atomic_write_bytes()` (or an equivalent temp-file-plus-replace helper) for every manifest update, and test an interrupted write/recovery path.

## Verification

- `pytest -q`: **73 passed** (one existing Pydantic deprecation warning).
- `python -m compileall -q main.py build.py config.py summarizer.py sources utils tests`: passed.
- Imported all changed enrichment/publication/contract modules and `main`: passed.
- `git diff --check`: only reports trailing blank lines at EOF in the current uncommitted `utils/enrichment_refill.py` and `utils/enrichment_verification.py`.

## Must-fix before merge

1. Fix CR-01 so no command can mutate the directory selected by the public pointer.
2. Propagate deadlines through the whole stage and re-raise `RunDeadlineExceeded` from enrichment (WR-02, WR-03).
3. Record every pre-publication failure as a blocked, actionable manifest (WR-01).
4. Establish a safe legacy-mirror transaction/reader policy (WR-04).
5. Enforce summary/source provenance and sanitize all published text/links (WR-05, WR-06).
6. Scrub exception diagnostics before persisting or uploading them (WR-07).

---

_Reviewed: 2026-07-10T00:00:00Z_  
_Reviewer: Claude (gsd-code-reviewer)_  
_Depth: deep_
