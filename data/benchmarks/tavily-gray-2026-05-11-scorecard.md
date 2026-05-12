# Tavily Gray Scorecard: 2026-05-11

## Source

- Run id: `25680995172`
- Command: `python3 main.py run --offline --enrichment on`
- Artifact path: `gray/tavily/2026-05-11/`
- Old commit: -
- New commit: -
- Report JSON present: true
- Report Markdown present: true

## Core Metrics

| Metric | Value |
|---|---:|
| input_count | `13` |
| prefiltered_count | `12` |
| aggregate_title_count | `1` |
| verified_count | `3` |
| preserved_error_count | `0` |
| final_count | `3` |
| min_articles | `10` |
| refill_remaining_count | `7` |
| total_calls | `7` |
| stop_reason | `budget_exhausted_after_priority_refill` |

## Stage Outcomes

| Stage | Calls | Results | Accepted | Missing Date Rate | Request Outcomes |
|---|---:|---:|---:|---:|---|
| verify | `6` | - | `3` | - | `{"success": 6}` |
| priority_refill | `1` | `8` | `0` | `1.0` | `{"success": 1}` |
| secondary_refill | `0` | `0` | `0` | - | `{}` |
| official_fallback | `0` | `0` | `0` | - | `{}` |

## Budget

| Metric | Value |
|---|---:|
| reserved_refill_calls | - |
| verify_budget | `6` |
| verify_skipped_due_budget | `6` |
| max_total_calls | `7` |
| max_verify_calls | `6` |
| secondary_entered | false |

## Stage Preview

- Accepted: `{"official_fallback": [], "preserved_errors": [], "priority_refill": [], "secondary_refill": [], "verify": ["Anthropic says ‘evil’ portrayals of AI were responsible for Claude’s blackmail attempts", "Uber has always wanted to be more than a ride; now it has reason to hurry", "TechCrunch Mobility: Lime’s IPO gamble"]}`
- Verify rejected: `["Korea’s biggest manufacturers back Config, the TSMC of robot data", "We’re feeling cynical about xAI’s big deal with Anthropic", "The hottest place for startups to strike a deal? The F1 paddock"]`
- priority_refill rejected: `["Anthropic’s $30B raise is about more than money", "OpenAI turns its sold-out GPT-5.5 party into a monthlong Codex giveaway for 8,000 developers | VentureBeat", "Anthropic launches marketplace for Claude-powered software"]`
- secondary_refill rejected: `[]`
- official_fallback rejected: `[]`

## Diagnosis

- Primary limiter: `budget_exhausted`
- Contributing factors: `["budget_exhausted", "published_date_missing"]`
- Fixture candidate: true
- Final count: 3 final articles = 0 preserved + 3 verify + 0 priority refill + 0 secondary refill + 0 official fallback; 7 below min_articles=10.

## Cannot Prove

- This artifact is a single live run, not evidence for default enablement.
- It does not prove Tavily result stability across days or runner environments.
- It does not prove broader domain, query, timeout, or official fallback changes are safe.
