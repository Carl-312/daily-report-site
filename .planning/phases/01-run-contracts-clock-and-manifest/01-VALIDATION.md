---
phase: 1
slug: run-contracts-clock-and-manifest
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-10
---

# Phase 1 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | `pyproject.toml` absent; test discovery uses repository defaults |
| Quick run command | `PYTHONPATH=. pytest -q tests/test_run_clock.py tests/test_run_contracts.py tests/test_run_manifest.py` |
| Full suite command | `ruff check . && ruff format --check . && PYTHONPATH=. pytest` |
| Estimated runtime | ~30 seconds |

## Sampling Rate

- After every task commit: run the quick command.
- After every plan wave: run the full suite command.
- Before Phase 1 verification: full suite must be green.
- Max feedback latency: 30 seconds.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | RUN-01, SRC-03 | T-01-01 | Reject naive/invalid clocks and derive all display dates from one fixed aware instant | unit | `PYTHONPATH=. pytest -q tests/test_run_clock.py` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | RUN-01, SRC-01 | T-01-02 | Reject invalid manifest/source shapes and redact all secret-bearing persisted fields | unit | `PYTHONPATH=. pytest -q tests/test_run_contracts.py tests/test_run_manifest.py` | ❌ W0 | ⬜ pending |
| 01-01-03 | 01 | 2 | DEL-01 | T-01-03 | New contracts leave legacy summary and Tavily pipeline behavior unchanged | regression | `PYTHONPATH=. pytest -q tests/test_main_summary.py tests/test_tavily_gray_regression.py` | ✅ | ⬜ pending |

## Wave 0 Requirements

- [ ] `tests/test_run_clock.py` — fixed-clock, timezone, date-title, deadline tests.
- [ ] `tests/test_run_contracts.py` — strict source/stage/diagnostic model tests.
- [ ] `tests/test_run_manifest.py` — redaction, deterministic fingerprint, persistence tests.

## Manual-Only Verifications

All Phase 1 behaviors have automated verification. GitHub Actions confirmation remains an external delivery check after the implementation commit.

## Validation Sign-Off

- [x] All tasks have automated verification or Wave 0 dependencies.
- [x] Sampling continuity: no three consecutive tasks lack automated verification.
- [x] Wave 0 covers all new test references.
- [x] No watch-mode flags.
- [x] Feedback latency is under 30 seconds.
- [x] `nyquist_compliant: true` is set in frontmatter.

**Approval:** ready 2026-07-10
