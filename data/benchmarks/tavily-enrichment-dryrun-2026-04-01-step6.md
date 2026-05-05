# Tavily News Enrichment Dry Run

## Scope

- Experimental replay harness only; no production integration was performed.
- Exact verify uses the current experimental default depth.
- Media refill uses the current whitelist-only path; official fallback is optional and may be disabled.

## Run Summary

| Report Date | Raw | Deduped | Prefiltered | Verify Calls | Refill Calls | Fallback Calls | Verified | Media Refilled | Official Refilled | Final | Stop Reason |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2026-03-24 | 15 | 15 | 4 | 4 | 1 | 0 | 2 | 3 | 0 | 5 | official_fallback_disabled |

## 2026-03-24

- Input date: `2026-03-24`
- raw_count / deduped_count / prefiltered_count: `15` / `15` / `4`
- verify_calls / refill_calls / fallback_calls / total_calls: `4` / `1` / `0` / `5`
- verified_count / media_refilled_count / official_refilled_count / final_count: `2` / `3` / `0` / `5`
- stop_reason: `official_fallback_disabled`
- Verified samples: Bernie Sanders’ AI ‘gotcha’ video flops, but the memes are great; Sam Altman-backed fusion startup Helion in talks to sell power to OpenAI
- Media refill samples: OpenAI is in talks to buy fusion energy from Helion - The Next Web; Meta’s CEO is developing a personal AI assistant to handle executive duties - The Next Web; IRONSCALES brings AI email agents & threat intelligence to RSAC - The Next Web
