# Agent A: Enrichment Logic

## Mission

你只负责 Tavily 正式 enrichment 逻辑，让 verify 阶段从“强 AI 标题门禁”升级为“时效优先、AI 相关性分层”，同时保持 refill 阶段严格、预算可控、fail-open 不退化。

本 agent 不负责测试主导、Actions、文档总整理或 PR 集成。

## Owned Files

你可以修改：

- `utils/news_enrichment.py`

只有在 B 明确要求你补一个最小断言时，才允许小范围修改：

- `tests/test_news_enrichment.py`

## Forbidden Files

不要修改：

- `.github/workflows/*`
- `config.yaml` 中的 `enrichment.enabled`
- `sources/*`
- `summarizer.py`
- `build.py`
- `handbook/**`
- benchmark 历史产物

## Read First

开始前阅读：

```bash
git status --short --branch
sed -n '1,260p' handbook/guides/tavily-integration.md
sed -n '1,360p' AGENT_ITERATION_WORKFLOW.md
sed -n '1,260p' config.py
sed -n '1,260p' main.py
sed -n '1,360p' utils/news_enrichment.py
sed -n '1,260p' tests/test_news_enrichment.py
```

## Scope

本轮只解决 verify 入口过窄的问题。

应做：

1. 把 `non_ai_relevant` 从硬拒绝改成软分层。
2. 为候选增加稳定 bucket，例如 `core_ai`、`ai_neighbor`、`generic_or_low_signal`。
3. verify 消费顺序改为 `core_ai -> ai_neighbor -> generic_or_low_signal`。
4. 增加最小诊断字段，例如 `prefilter_bucket_counts`、`neighbor_candidates_verified_count`、`neighbor_candidates_outside_24h_count`、`neighbor_candidates_no_match_count`。
5. 保留 `missing_title`、`missing_link`、`aggregate_like` 的硬拒绝。
6. 保持 `within_strict_hours()` 为最终硬门槛。
7. 保持 exact URL 或 same-domain + title similarity 的匹配门槛。
8. request timeout、HTTP error、connection error 仍必须走 preserve original article 的 fail-open 路径。

不应做：

1. 不放宽 refill 的 AI 标题相关性门槛。
2. 不扩大 trusted domains 默认名单。
3. 不增加默认 Tavily 调用预算。
4. 不把 `enable_official_fallback` 默认改成 true。
5. 不把 Tavily 结果直接绕过验证写入最终产物。
6. 不因为一次 live 请求成功就调整策略常量。

## Implementation Notes

优先在这些位置小范围修改：

- `build_prefilter_summary()`: 产出 bucket，而不是让非 AI 标题直接进入 `excluded_prefilter_candidates`。
- `run_verify_stage()`: 接收已经排序好的 candidates，并在 run/candidate summary 中记录 bucket。
- `enrich_articles_with_tavily()`: 把新的 bucket 统计写进 report。

推荐保持函数接口简单。如果需要新增 helper，优先放在 `build_prefilter_summary()` 附近。

## Independent Acceptance

你必须自己跑：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider tests/test_news_enrichment.py
```

如果你改了核心逻辑，再跑：

```bash
python3 main.py fetch --enrichment off
```

如果本地有 `TAVILY_API_KEY`，可以加跑：

```bash
python3 main.py run --offline --enrichment on
```

没有 key 时不要伪造 live 结论，只说明未跑 live。

## Required Self-Review

交付前检查：

- `enrichment.enabled: false` 没被改。
- `prefilter_stats` 仍能解释硬拒绝原因。
- 新增 bucket 不会让 aggregate source 进入 verify。
- verify timeout 仍保留原始 article。
- final articles 不会因为 Tavily request error 被清空。
- refill 接受条件仍包含 24h、AI 标题相关、去重和 story cluster 拦截。

## Handoff To E

按这个格式交付：

```text
Agent: A Enrichment Logic
本轮唯一目标:
修改文件:
新增/改变的 report 字段:
验收命令:
验收结果:
未处理风险:
需要 B/E 关注:
```
