# Tavily Gray Evaluation: 2026-05-11

## Source

- GitHub Actions run id: `25680995172`
- Local artifact:
  `tmp/github-artifacts/tavily-gray-2026-05-11-25680995172/gray/tavily/2026-05-11/`
- Files reviewed:
  - `report.json`
  - `enrichment-summary.json`
  - `report.md`
  - `logs/run.log`
- Minimal regression fixture:
  `tests/fixtures/tavily-gray-2026-05-11/report-minimal.json`

## Artifact Facts

The gray artifact produced `3` final articles, not `6`.

Key observed metrics from the old run:

| Metric | Value |
|---|---:|
| `input_count` | `13` |
| `prefiltered_count` | `12` |
| `verify_calls` | `6` |
| `refill_calls` | `1` |
| `fallback_calls` | `0` |
| `total_calls` | `7` |
| `final_count` | `3` |
| `stop_reason` | `budget_exhausted_after_priority_refill` |

The three final articles came from verify. Priority refill ran once but accepted
no candidates because returned candidates lacked usable `published_date` values.
Secondary refill did not run.

## Problem Found

The old default budget allowed verify to consume `6` calls while
`max_total_calls` was `7`. That left only one call for staged refill:

```text
max_total_calls=7
max_verify_calls=6
verify_calls=6
remaining_budget=1
priority_refill_calls=1
secondary_refill_calls=0
```

Because priority refill accepted `0`, the run stopped at `3` final articles and
never reached secondary refill.

## Current Fix

The current logic reserves refill budget before verify:

```text
reserved_refill_calls = priority_refill + secondary_refill = 2
verify_budget = min(max_verify_calls, max_total_calls - reserved_refill_calls)
```

With the default budget:

```text
max_total_calls=7
max_verify_calls=6
reserved_refill_calls=2
verify_budget=5
```

This preserves one priority refill call and one secondary refill call. It does
not guarantee `10` final articles; it guarantees the staged refill policy gets a
chance to run before the total budget is exhausted.

## Regression Coverage

Added deterministic tests in `tests/test_tavily_gray_regression.py`:

- Rebuilds the `2026-05-11` gray input from a minimal fixture.
- Mocks Tavily verify and refill responses; no unit test performs a live Tavily
  network call.
- Asserts the old artifact facts, including `final_count=3`,
  `verify_calls=6`, `refill_calls=1`, and no secondary refill.
- Asserts current defaults report `reserved_refill_calls=2`.
- Asserts current defaults cap `verify_budget` at `5`, not `6`.
- Asserts priority refill runs first and secondary refill runs when priority is
  still below `min_articles`.
- Asserts Tavily refill articles are passed through the production run path into
  JSON and then into `offline_summary`.
- Adds a preserved-error guard: if verify request errors preserve enough
  articles to satisfy `min_articles`, refill is skipped.

## Remaining Risks

- Real Tavily results may still omit `published_date`, which can leave the run
  below `min_articles` even when priority and secondary refill both execute.
- Official fallback remains disabled by default; this sample is not evidence to
  enable it.
- Live network behavior can vary by runner, timeout, proxy, and Tavily result
  quality; the gray path still needs continued observation.
- Reserving refill calls can reduce verify calls by one under the default
  budget. That is intentional, but it means this fix optimizes for staged refill
  opportunity rather than maximum verify coverage.

## Interpretation

This sample is suitable as a regression fixture for the budget conflict between
verify and staged refill. It is not suitable as proof that Tavily should be
enabled by default, that secondary domains are always productive, or that live
Tavily responses will reliably fill the report to `10` articles.
