# Tavily News Enrichment Dry Run

## Scope

- Experimental replay harness only; no production integration was performed.
- Exact verify uses the current experimental default depth.
- Refill uses staged priority + secondary domain paths; official fallback is optional and may be disabled.

## Run Summary

| Report Date | Raw | Deduped | Prefiltered | Verify Calls | Refill Calls | Fallback Calls | Verified | Media Refilled | Official Refilled | Final | Stop Reason |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2026-03-24 | 15 | 15 | 4 | 4 | 2 | 0 | 2 | 3 | 0 | 5 | official_fallback_disabled |
| 2026-03-25 | 14 | 14 | 9 | 6 | 1 | 0 | 4 | 4 | 0 | 8 | budget_exhausted_after_priority_refill |

## 2026-03-24

- Input date: `2026-03-24`
- raw_count / deduped_count / prefiltered_count: `15` / `15` / `4`
- cluster_count / clustered_prefilter_count / potential_verify_saved_calls / verify_saved_calls: `0` / `0` / `0` / `0`
- verify_calls / refill_calls / fallback_calls / total_calls: `4` / `2` / `0` / `6`
- near_duplicate_rejected_count / story_cluster_rejected_count: `0` / `1`
- priority_refilled_count / secondary_refilled_count / secondary_duplicate_slip_count: `1` / `2` / `0`
- verified_count / media_refilled_count / official_refilled_count / final_count: `2` / `3` / `0` / `5`
- stop_reason: `official_fallback_disabled`
- Verified samples: Bernie Sanders’ AI ‘gotcha’ video flops, but the memes are great; Sam Altman-backed fusion startup Helion in talks to sell power to OpenAI
- Priority refill samples: Meta’s CEO is developing a personal AI assistant to handle executive duties - The Next Web
- Secondary refill samples: Fusion developers go public as AI boom widens funding sources - Reuters; AI may boost euro area productivity growth by 4% in 10 years, ECB says - Reuters
- accepted_by_stage_preview: verify=Bernie Sanders’ AI ‘gotcha’ video flops, but the memes are great; Sam Altman-backed fusion startup Helion in talks to sell power to OpenAI | priority_refill=Meta’s CEO is developing a personal AI assistant to handle executive duties - The Next Web | secondary_refill=Fusion developers go public as AI boom widens funding sources - Reuters; AI may boost euro area productivity growth by 4% in 10 years, ECB says - Reuters | official_fallback=(none)
- Cluster diagnostics: none

## 2026-03-25

- Input date: `2026-03-25`
- raw_count / deduped_count / prefiltered_count: `14` / `14` / `9`
- cluster_count / clustered_prefilter_count / potential_verify_saved_calls / verify_saved_calls: `0` / `0` / `0` / `0`
- verify_calls / refill_calls / fallback_calls / total_calls: `6` / `1` / `0` / `7`
- near_duplicate_rejected_count / story_cluster_rejected_count: `0` / `1`
- priority_refilled_count / secondary_refilled_count / secondary_duplicate_slip_count: `4` / `0` / `0`
- verified_count / media_refilled_count / official_refilled_count / final_count: `4` / `4` / `0` / `8`
- stop_reason: `budget_exhausted_after_priority_refill`
- Verified samples: OpenAI’s Sora was the creepiest app on your phone — now it’s shutting down; Anthropic hands Claude Code more control, but keeps it on a leash; Spotify tests new tool to stop AI slop from being attributed to real artists
- Priority refill samples: OpenAI releases open-source teen safety tools for AI developers - The Next Web; Developer communities, AI, and the future of tech leadership - The Next Web; How BNESIM uses AI to reshape travel eSIM & global connectivity - The Next Web
- accepted_by_stage_preview: verify=OpenAI’s Sora was the creepiest app on your phone — now it’s shutting down; Anthropic hands Claude Code more control, but keeps it on a leash; Spotify tests new tool to stop AI slop from being attributed to real artists | priority_refill=OpenAI releases open-source teen safety tools for AI developers - The Next Web; Developer communities, AI, and the future of tech leadership - The Next Web; How BNESIM uses AI to reshape travel eSIM & global connectivity - The Next Web | secondary_refill=(none) | official_fallback=(none)
- Cluster diagnostics: none
