# Agent B: Test Contract

## Mission

你只负责把 Tavily 行为变成可回归测试。你的目标是让 A/C 的改动不能悄悄破坏 fail-open、24 小时时效、source 为空语义和 Actions 接线期望。

本 agent 不主导生产逻辑，不直接改 GitHub Actions。

## Owned Files

你可以修改：

- `tests/test_news_enrichment.py`
- `data/benchmarks/fixtures/*`

必要时可以新增测试辅助 fixture，但应保持在 `tests/` 或 `data/benchmarks/fixtures/` 内。

## Forbidden Files

不要修改：

- `utils/news_enrichment.py`
- `.github/workflows/*`
- `config.yaml`
- `sources/*`
- `summarizer.py`
- `build.py`
- handbook 文档

如果测试暴露生产代码 bug，把失败和期望交给 A 或 E，不要直接修生产逻辑。

## Read First

开始前阅读：

```bash
git status --short --branch
sed -n '1,260p' handbook/operations/tavily.md
sed -n '1,360p' AGENT_ITERATION_WORKFLOW.md
sed -n '1,360p' tests/test_news_enrichment.py
sed -n '1,260p' utils/news_enrichment.py
sed -n '1,220p' data/benchmarks/fixtures/tavily-replay-fixture-2026-04-29-curated.json
```

## Required Coverage

至少覆盖这些行为：

1. `enabled=False` 时 articles 原样返回，`skip_reason=disabled`。
2. 缺 `TAVILY_API_KEY` 时 articles 原样返回，`skip_reason=missing_api_key`。
3. verify timeout 时原始 article 被保留，`request_outcome=timeout`，`validation_outcome=not_evaluated`。
4. source 输入为 0 时，report notes 明确这是上游 source 空输入下的 Tavily 受控补量场景。
5. 24 小时之外的 matched article 被拒绝为 `outside_24h`。
6. 缺 `published_date` 的 matched article 被拒绝为 `missing_published_date`。
7. AI 邻近但标题不强命中的候选不会在 prefilter 阶段被硬拒绝，而是进入较低优先级 bucket。
8. verify 顺序优先 `core_ai`，再 `ai_neighbor`，最后 `generic_or_low_signal`。
9. aggregate-like article 仍被硬拒绝，不进入 verify。
10. refill 的 AI 标题相关性门槛没有被 A 的 verify 放宽误改。

## Testing Style

优先使用 monkeypatch 模拟 `news_enrichment.search_tavily`，不要依赖 live Tavily。

测试应直接断言 report 字段，例如：

- `prefilter_stats`
- `prefilter_bucket_counts`
- `verify_runs[*].request_outcome`
- `verify_runs[*].validation_outcome`
- `rejected_candidates[*].rejection_reason`
- `accepted_by_stage_preview`
- `final_count`
- `stop_reason`

不要只断言 article 数量；数量会掩盖错误语义。

## Fixture Rules

如果修改 `data/benchmarks/fixtures/tavily-replay-fixture-2026-04-29-curated.json`：

- 不要删除已有 stress/control 样本。
- 新增样本必须有 `scenario_tags`、`expected_flags`、`event_key` 和 `notes`。
- fixture 是 replay/regression 输入，不是生产日报数据。
- 不要把 live API response 原样大量塞进 fixture；只保留最小必要字段。

## Independent Acceptance

你必须自己跑：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider tests/test_news_enrichment.py
```

如果改了 fixture，再跑一次目标测试并说明 fixture 被哪个 case 使用。

如果你只写了预期测试且当前生产代码还没实现，可以交付“预期失败”状态，但必须给出失败测试名和期望 A 修复的行为。

## Required Self-Review

交付前检查：

- 测试不需要真实 `TAVILY_API_KEY`。
- 测试不访问外网。
- 测试没有依赖当天日期。
- 断言覆盖 fail-open，而不是只覆盖 happy path。
- 没有为了让测试通过而降低 24 小时约束。

## Handoff To E

按这个格式交付：

```text
Agent: B Test Contract
本轮唯一目标:
修改文件:
新增测试:
验收命令:
验收结果:
预期失败或阻塞:
需要 A/E 关注:
```
