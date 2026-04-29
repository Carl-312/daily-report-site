# Tavily Phase 0 Benchmark Summary

## Scope

- Only Phase 0 benchmark was executed.
- No production `news_enrichment` integration was added.
- Historical replay used the report date plus the documented deploy time `21:19 Asia/Shanghai` as the 24-hour reference point.

## Measured Results

- `verify_exact` + `basic` + `max_results=3`: `3/4` matched, average latency `546 ms`, `published_date` availability `100%`.
- `verify_exact` + `advanced` + `max_results=3`: `3/4` matched, average latency `412 ms` on this sample, no match-rate gain over `basic`.
- `verify_fuzzy` + `advanced` + `max_results=5`: `2/4` matched, `0` rescue cases over exact verification.
- English refill query (`OpenAI Anthropic AI model launch startup funding developer tools`) + `advanced` + `max_results=8`: `4` new valid candidates, `0` duplicates.
- Chinese refill query (`人工智能 模型 发布 智能体 融资 开发者 工具 新闻`) + `advanced` + `max_results=8`: `0` new valid candidates, `0` duplicates in this replay window.

## Practical Takeaways

- Single-story TechCrunch titles matched cleanly with one exact Tavily query.
- Aggregate-style `AI日报...` titles from `aibase` did not match in `basic`, `advanced`, or fuzzy mode.
- `published_date` was present for every returned result in this run.
- Fuzzy second-pass verification did not improve recall and introduced more cross-domain near-matches.
- Refill quality depended heavily on query wording; the English topic query worked, the Chinese one did not.

## Recommended Initial Parameters

- `max_total_calls: 7`
- `max_verify_calls: 6`
- `max_refill_rounds: 1`
- `refill_max_results: 8`
- Verification default depth: `basic`
- Keep fuzzy second confirmation: `no`
- Initial `trusted_domains` shortlist:
  - `techcrunch.com`
  - `theverge.com`
  - `thenextweb.com`

## Notes

- Do not spend Tavily verification budget on multi-story aggregate titles until a better normalization/splitting strategy exists.
- Do not whitelist `advocate-news.com` or `letsdatascience.com` yet; they appeared in refill results, but the editorial fit looked weaker than the top tech outlets above.
