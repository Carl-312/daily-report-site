# Tavily Gray Scorecard: 2026-05-12

## Source

- Run id: `25716080642`
- Command: `python3 main.py run --offline --enrichment on`
- Artifact path: `gray/tavily/2026-05-12/`
- Old commit: -
- New commit: `4cf4ce981a87f92eb7717a0575943f904cf1e505`
- Report JSON present: true
- Report Markdown present: true

## Core Metrics

| Metric | Value |
|---|---:|
| input_count | `14` |
| prefiltered_count | `14` |
| aggregate_title_count | `0` |
| verified_count | `3` |
| preserved_error_count | `0` |
| final_count | `8` |
| min_articles | `10` |
| refill_remaining_count | `2` |
| total_calls | `7` |
| stop_reason | `budget_exhausted_after_secondary_refill` |

## Stage Outcomes

| Stage | Calls | Results | Accepted | Missing Date Rate | Request Outcomes |
|---|---:|---:|---:|---:|---|
| verify | `5` | - | `3` | - | `{"success": 5}` |
| priority_refill | `1` | `8` | `0` | `1.0` | `{"success": 1}` |
| secondary_refill | `1` | `5` | `5` | `0.0` | `{"success": 1}` |
| official_fallback | `0` | `0` | `0` | - | `{}` |

## Budget

| Metric | Value |
|---|---:|
| reserved_refill_calls | `2` |
| verify_budget | `5` |
| verify_skipped_due_budget | `9` |
| max_total_calls | `7` |
| max_verify_calls | `6` |
| secondary_entered | true |

## Stage Preview

- Accepted: `{"official_fallback": [], "preserved_errors": [], "priority_refill": [], "secondary_refill": ["OpenAI creates new unit with $4 billion investment to aid corporate AI push - Reuters", "Former OpenAI executive Sutskever discloses nearly $7 billion stake in AI firm - Reuters", "EU Commission in talks with OpenAI and Anthropic over AI models - Reuters"], "verify": ["GM just laid off hundreds of IT workers to hire those with stronger AI skills", "Digg tries again, this time as an AI news aggregator", "Korea’s biggest manufacturers back Config, the TSMC of robot data"]}`
- Verify rejected: `["Riding an AI rally, Robinhood preps second retail venture IPO", "Thinking Machines wants to build an AI that actually listens while it talks"]`
- priority_refill rejected: `["Anthropic's $30B raise is about more than money - TNW", "Anthropic launches marketplace for Claude-powered software - TNW", "Anthropic says it hit a $30 billion revenue run rate after 'crazy' 80x ..."]`
- secondary_refill rejected: `[]`
- official_fallback rejected: `[]`

## Diagnosis

- Primary limiter: `budget_exhausted`
- Contributing factors: `["budget_exhausted", "published_date_missing"]`
- Fixture candidate: true
- Final count: 8 final articles = 0 preserved + 3 verify + 0 priority refill + 5 secondary refill + 0 official fallback; 2 below min_articles=10.

## Cannot Prove

- This artifact is a single live run, not evidence for default enablement.
- It does not prove Tavily result stability across days or runner environments.
- It does not prove broader domain, query, timeout, or official fallback changes are safe.
