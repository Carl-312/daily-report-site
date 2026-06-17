# Tavily Gray 下一轮实验矩阵

最后更新：2026-06-17

## 定位

本文用于决定下一轮 Tavily gray 该测试哪个变量，以及如何判断结果。它不是操作 runbook：重点不是如何触发 workflow，而是提升决策质量、实验归因和优先级排序。

核心原则：

- 一轮实验只改一个变量。
- 不在同一次 gray run 里同时调整预算、domain、query、fallback 或 freshness 规则。
- `config.yaml` 继续保持 `enrichment.enabled: false`。
- Tavily 仍是 post-fetch enrichment，不是默认新闻源。
- 不修改 workflow 或代码来证明策略假设。
- 不默认开启 Tavily。
- 不把单次 action 成功解释成可上线。

## 当前证据

### Key 修复前失败样本

| Field | Value |
|---|---|
| Run | `27637098323` |
| Event | `schedule` |
| Date | `2026-06-17` |
| Commit | `e568068939d0cc3b6987ffd81511baae4fb3f2d3` |
| Result | workflow success, Tavily API layer failed |

| Metric | Value |
|---|---:|
| final_count / min_articles | `5 / 10` |
| verified_count | `0` |
| preserved_error_count | `5` |
| total_calls | `7` |
| verify request outcome | `{"http_error": 5}` |
| priority refill request outcome | `{"http_error": 1}` |
| secondary refill request outcome | `{"http_error": 1}` |
| primary_limiter | `network_failure` |

Decision value: this run only proves API access was unavailable at the time. It must not be used as a strategy-quality sample.

### Key 修复后成功样本

| Field | Value |
|---|---|
| Run | `27664628428` |
| Event | `workflow_dispatch` |
| Date | `2026-06-17` |
| Commit | `e568068939d0cc3b6987ffd81511baae4fb3f2d3` |
| Artifact local path | `/tmp/daily-report-gray-manual-27664628428` |

| Metric | Value |
|---|---:|
| input_count | `14` |
| prefiltered_count | `14` |
| final_count / min_articles | `8 / 10` |
| strict_final_count | `8` |
| verified_count | `5` |
| preserved_error_count | `0` |
| priority_refilled_count | `3` |
| secondary_refilled_count | `0` |
| official_fallback_count | `0` |
| total_calls | `7` |
| stop_reason | `budget_exhausted_after_secondary_refill` |
| primary_limiter | `budget_exhausted` |

| Stage | Calls | Results | Accepted | Request Outcomes |
|---|---:|---:|---:|---|
| verify | `5` | - | `5` | `{"success": 5}` |
| priority_refill | `1` | `8` | `3` | `{"success": 1}` |
| secondary_refill | `1` | `1` | `0` | `{"success": 1}` |
| official_fallback | `0` | `0` | `0` | `{}` |

Decision value: the API key is usable, but the strategy is not proven. The best current baseline is `8/10` with `primary_limiter=budget_exhausted`.

## 优先级排序规则

The experiment queue is ranked by the variable most likely to clarify the next decision with the least interpretation risk:

1. Stability: prove the repaired API path is repeatable before strategy tuning.
2. Budget: test whether the current `8/10` result is simply capped by `max_total_calls=7`.
3. Domain: if budget is not sufficient, isolate priority/secondary domain yield.
4. Query: if domain yield remains weak, test narrower search intent groups.
5. Fallback: test official fallback only after media refill variables are understood.

Do not skip ahead because one manual action succeeded. A successful workflow run only proves the workflow can run; it does not prove the enrichment policy should be enabled by default.

## 实验矩阵

| Experiment | Hypothesis | Only change | Do not change | Metrics | Continue criteria | Stop criteria |
|---|---|---|---|---|---|---|
| Baseline repeat | The repaired key path is stable, and the current baseline can be measured without strategy noise. | No strategy change; repeat the current Tavily gray behavior. | Do not change budget, domain lists, query, fallback, strict/lenient rules, `config.yaml`, workflow, or code. | `request_outcomes`, `preserved_error_count`, `final_count / min_articles`, `strict_final_count`, stage accepted counts, `primary_limiter`, `stop_reason`. | At least 2 live samples have no `http_error`, `preserved_error_count=0`, and `primary_limiter` is not `network_failure`. Then move to budget-only. | Any `http_error`, auth/quota/network limiter, or preserved error means return to availability investigation before strategy experiments. |
| Budget-only: `max_total_calls` `7 -> 9` | The current `8/10` result is primarily caused by total-call exhaustion, not poor query/domain quality. | Increase only `max_total_calls` from `7` to `9` in the gray test context. | Do not change `refill_max_results`, priority/secondary domains, query, fallback, strict/lenient rules, production config, workflow, or code. | Additional verify coverage, priority/secondary accepted counts, accepted/result ratio, `final_count / min_articles`, duplicate/non-AI/expired rejections, `primary_limiter`, `stop_reason`. | `final_count` reaches or approaches `10` without lower-quality accepted items, and `primary_limiter` moves away from budget exhaustion or later-stage shortage. Run one more sample before keeping the budget change as a candidate. | Still around `8/10`, accepted/result below 25%, or added calls mostly produce duplicate, non-AI, expired, or marketing candidates. Move to domain-only. |
| Domain-only: priority/secondary 分层调整 | The current priority/secondary domain split is limiting useful refill yield. | Change only one domain layer or one domain group per run, such as priority media, TechCrunch overlap, or secondary recall. | Do not change budget, query, fallback, strict/lenient rules, production config, workflow, or code. Do not test multiple new domain groups in one run. | Results per domain group, accepted/result ratio, duplicate/cluster rejection, non-AI rejection, stage accepted counts, source distribution, `final_count / min_articles`. | One isolated domain group shows clearly better accepted/result quality than baseline and contributes strict, non-duplicate AI articles. Then test a second sample or a controlled combination. | No group clears 25% accepted/result, results cluster around duplicates, or source distribution remains dominated by a single low-yield source. Move to query-only. |
| Query-only: 窄 query 分组 | A broad query is mixing too many intents, reducing candidate quality and making rejections hard to interpret. | Replace only the query with one narrow intent group per run. Candidate groups: `AI model launch OpenAI Anthropic Google Meta`, `AI startup funding acquisition venture capital`, `AI policy regulation security model access`, `AI developer tools coding agents infrastructure`. | Do not change budget, domain lists, fallback, strict/lenient rules, production config, workflow, or code. Do not combine multiple new queries in one run. | Accepted/result by query, non-AI rejection, duplicate/cluster rejection, expired rejection, strict accepted count, `final_count / min_articles`, `primary_limiter`. | One query group improves strict accepted yield while reducing non-AI or duplicate rejection. Promote that query for another sample or combine only after separate evidence exists. | Narrow query lowers useful yield, only improves lenient candidates, or requires simultaneous domain/budget changes to look good. Move to another query group or fallback gate. |
| Official-fallback-only | Official sources can close a persistent 1-2 article gap after media refill has been understood. | Enable only official fallback in the gray test context. | Do not change budget, domains, query, strict/lenient rules, production config, workflow, or code. Do not mix official fallback accepted items into media refill conclusions. | `official_fallback_count`, official fallback accepted/result ratio, strict accepted count, duplicate/expired rejection, `final_count / min_articles`, `primary_limiter`, `stop_reason`. | Official fallback reliably adds strict, non-duplicate, date-relevant AI items and closes a small remaining gap without hiding media refill weakness. Keep it as a fallback candidate, not a default-on decision. | Official fallback mostly duplicates media results, produces stale/marketing items, or is needed to mask unresolved budget/domain/query weakness. Do not enable by default. |

## Domain-only candidate groups

Use these as separate experiments, not as one combined whitelist change:

| Candidate | Only change | Question |
|---|---|---|
| Priority media only | Priority domains focus on `reuters.com` and `arstechnica.com`. | Can high-signal media independently provide strict refill? |
| TechCrunch overlap check | Isolate `techcrunch.com` behavior. | Is TechCrunch still producing missed valid items, or mostly duplicates/clusters? |
| Secondary recall check | Isolate `thenextweb.com` and `venturebeat.com`. | Are historical secondary domains useful on current dates? |

## Query-only candidate groups

| Query group | Question |
|---|---|
| `AI model launch OpenAI Anthropic Google Meta` | Are model/product launches the strongest strict-yield intent? |
| `AI startup funding acquisition venture capital` | Does company/funding coverage improve refill diversity? |
| `AI policy regulation security model access` | Does policy/security coverage add useful non-product events? |
| `AI developer tools coding agents infrastructure` | Does developer-tooling intent improve relevance for this report? |

## Decision table

| Evidence from next run | Decision |
|---|---|
| Any `http_error`, auth/quota failure, or `primary_limiter=network_failure` | Stop strategy work and debug availability. |
| Baseline repeat remains stable but `final_count` stays near `8/10` with budget exhaustion | Run budget-only next. |
| Budget-only reaches `10/10` with strict, non-duplicate items | Repeat budget-only once before considering it a candidate setting. |
| Budget-only does not materially improve strict yield | Revert budget change and run domain-only. |
| One domain group has materially better accepted/result quality | Repeat that domain group or test a controlled domain combination. |
| Domain groups are weak or duplicate-heavy | Revert domain changes and run query-only. |
| One narrow query improves strict accepted yield | Repeat the query-only sample before combining it with any other change. |
| Media refill still misses only 1-2 strict items after budget/domain/query evidence | Test official-fallback-only. |
| Any single run succeeds once | Do not enable Tavily by default; require repeatability and explainable stage-level gains. |

## Required scorecard fields

Every analysis must record:

- run id, event, commit, artifact path
- changed variable and exact override
- whether the run is baseline repeat or a strategy sample
- `request_outcomes` by stage
- stage accepted counts
- stage rejected counts when available
- `final_count / min_articles`
- `strict_final_count`
- `preserved_error_count`
- `primary_limiter`
- `stop_reason`
- decision: keep sampling, revert, advance to next variable, or stop

## Current next recommendation

Run Baseline repeat first. The key has one successful manual sample, but strategy experiments should wait until API stability is confirmed with repeat evidence. If the next live sample again has no `http_error`, `preserved_error_count=0`, and `primary_limiter=budget_exhausted`, the next matrix item is Budget-only with `max_total_calls` moving from `7` to `9`.

## Current non-goals

- Do not enable Tavily by default.
- Do not change `enrichment.enabled` to `true`.
- Do not commit `.env` or any secret.
- Do not modify `config.yaml`, workflow files, or code as part of this document-only experiment.
- Do not count network-failure samples as strategy-quality evidence.
- Do not treat one successful action as launch readiness.
