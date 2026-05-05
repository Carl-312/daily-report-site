# Tavily Trusted Domains Research

## Scope

- Focused on `trusted_domains` for Tavily refill, not production integration.
- Compared overlapping domains, non-overlapping media, and official vendor blogs under the same refill-style queries.

## Domain Summary

| Domain | Family | Configured Source | Observed Recent Articles | Avg Unique Valid / Run | Avg Published Date Availability | Avg AI Title Rate | Avg Duplicate Existing / Run |
|---|---|---:|---:|---:|---:|---:|---:|
| thenextweb.com | media | no | 0 | 3 | 1.0 | 0.6667 | 0 |
| techcrunch.com | media | yes | 71 | 2.6667 | 1.0 | 0.8667 | 1.6667 |
| venturebeat.com | media | no | 0 | 1.3333 | 1.0 | 1.0 | 0 |
| arstechnica.com | media | no | 0 | 1 | 1.0 | 0.2 | 0 |
| reuters.com | wire | no | 0 | 0.6667 | 1.0 | 0.2667 | 0 |
| anthropic.com | official | no | 0 | 0.6667 | 1.0 | 0.8333 | 0 |
| openai.com | official | no | 0 | 0.6667 | 0.6667 | 1.0 | 0 |
| news.aibase.com | aggregate | yes | 3 | 0 | 1.0 | 1.0 | 0 |
| www.theverge.com | media | yes | 0 | 0 | 0.0 | 1.0 | 0 |
| blog.google | official | no | 0 | 0 | 0.0 | 1.0 | 0 |

## Notes

- High overlap domains reduce refill value when the same source is already present in the current report.
- Official vendor blogs were sparse and often had missing or unstable published_date metadata in Tavily results.
- Aggregate digest domains may return on-topic items, but they are a weak fit for strict article-level verification.
- Non-overlap editorial tech media should be judged by unique valid candidates per run, not by raw result_count alone.
