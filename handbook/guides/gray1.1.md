# Tavily Gray 1.1 分析记录

最后更新：2026-06-17

## 定位

本文记录 Tavily gray baseline repeat runbook 分支的文档改动和 GitHub Actions 实测结果。它是 Gray 1.1 的分析落盘，不改变生产默认配置，不修改 workflow，不默认开启 Tavily。

本轮只回答一个问题：在 key 修复后，不改策略变量的 baseline gray run 是否能稳定访问 Tavily API，并产出可解释 artifact。

## 本轮输入

| Item | Value |
|---|---|
| Branch | `docs/tavily-gray-baseline-runbook` |
| Commit | `390db515c9aa2fc980c623cc0342423ccc65af65` |
| Commit message | `docs: clarify Tavily gray baseline runbook` |
| GitHub run | `https://github.com/Carl-312/daily-report-site/actions/runs/27666067059` |
| Event | `workflow_dispatch` |
| Artifact local path | `/tmp/tavily-gray-baseline-runbook-27666067059` |
| Artifact internal path | `gray/tavily/2026-06-17/` |

本轮仓库变更范围只包含：

```text
handbook/guides/tavily-gray-next-steps.md
```

## 文档改动摘要

`handbook/guides/tavily-gray-next-steps.md` 增加了 baseline repeat runbook，重点补齐：

- Baseline repeat 运行条件。
- Baseline repeat 操作步骤。
- Action artifact 检查清单。
- 通过/停止标准。
- 记录模板。
- 进入下一轮变量实验的门槛。

这些内容把“先做 baseline 稳定性复测”从建议改成可执行门禁。文档继续保持以下约束：

- `config.yaml` 不改，`enrichment.enabled` 继续为 `false`。
- 不修改 `.github/workflows/tavily-gray.yml`、`.github/workflows/deploy.yml` 或代码。
- 不默认开启 Tavily。
- 一轮实验只改一个变量。

## Action artifact 结果

本次 run 下载并检查了以下关键 artifact：

```text
scorecard.md
scorecard.json
enrichment-summary.json
logs/gray-experiment-overrides.json
logs/gray-config-diff.patch
```

核心指标：

| Metric | Value |
|---|---:|
| final_count / min_articles | `8 / 10` |
| strict_final_count | `8` |
| verified_count | `5` |
| priority_refilled_count | `3` |
| secondary_refilled_count | `0` |
| official_refilled_count | `0` |
| preserved_error_count | `0` |
| total_calls | `7` |
| primary_limiter | `budget_exhausted` |
| stop_reason | `budget_exhausted_after_secondary_refill` |

Stage outcome：

| Stage | Accepted | Request Outcomes |
|---|---:|---|
| verify | `5` | `{"success": 5}` |
| priority_refill | `3` | `{"success": 1}` |
| secondary_refill | `0` | `{"success": 1}` |
| official_fallback | `0` | `{}` |

Artifact 解释：

- `8` 条 final article = `5` 条 verify + `3` 条 priority refill。
- 距离 `min_articles=10` 还缺 `2` 条。
- `primary_limiter` 是 `budget_exhausted`，不是 `network_failure`。
- request outcome 全部成功，没有 `http_error`。
- `preserved_error_count = 0`，说明本次没有把 API 错误保留下来污染结果。
- 输入来源仍高度集中：`source_distribution = {"techcrunch": 14}`。

## 安全默认确认

`gray-experiment-overrides.json` 显示本次仍保持安全默认：

```json
{
  "unchanged_safety_defaults": {
    "enabled": false,
    "enable_official_fallback": false
  }
}
```

这说明本次 gray run 仍是隔离验证，不是生产默认开启，也没有启用 official fallback。

## 判断

### 已证明

- Tavily key/API 在本次 GitHub Actions runner 中可用。
- 本次没有复现 key 修复前的 `network_failure` / `http_error`。
- 当前 artifact 能解释 final count、补量来源、停止原因和 limiter。
- baseline runbook 分支的文档变更没有触碰配置、workflow 或代码。

### 未证明

- 单次 run 不能证明 Tavily 结果跨天稳定。
- `final_count=8` 仍低于 `min_articles=10`，不支持默认开启 Tavily。
- 本次不能证明 official fallback、query、domain 或预算调整是安全的。
- 本次不能证明生产定时日报应该接入 Tavily。

## Gray 1.1 结论

本次 Gray 1.1 的结论是：key/API 可用性门禁通过，但内容数量门槛未通过。

从指标看，问题已经从 key/network failure 转为策略层面的 yield 问题：

- verify 阶段成功接受 `5` 条。
- priority refill 成功补入 `3` 条。
- secondary refill 没有补入结果。
- 总调用数用满后仍缺 `2` 条。

因此当前不应继续排查 secret 或 GitHub Actions 网络；下一步应在 baseline 稳定的前提下做单变量实验。

## 下一步建议

建议进入下一轮变量实验，优先做 budget-only run：

- 只把 `max_total_calls` 从 `7` 提到 `9`。
- 不改 `refill_max_results`。
- 不改 domain。
- 不改 query。
- 不启用 official fallback。
- 不改变 strict/lenient 规则。

观察字段：

- `final_count / min_articles`
- `verified_count`
- `priority_refilled_count`
- `secondary_refilled_count`
- `preserved_error_count`
- `request_outcomes`
- `primary_limiter`
- `stop_reason`

通过标准：

- request outcome 仍无 `http_error`。
- `preserved_error_count = 0`。
- `final_count` 稳定达到或接近 `10`。
- 新增 accepted candidate 不是重复、非 AI、过期或纯营销。

停止标准：

- 出现网络、鉴权或 quota 错误。
- 增加调用预算后 `final_count` 仍停在 `8` 左右。
- accepted/result 明显偏低，收益主要被重复或候选质量过滤吞掉。

## 记录模板

下一轮实验记录可按以下格式追加：

```markdown
### Gray 1.2 Budget-only Run: <run_id>

- Run URL:
- Ref / commit:
- Artifact path:
- Changed variable: `max_total_calls`
- Exact override: `7 -> 9`

| Metric | Value |
|---|---:|
| final_count / min_articles |  |
| verified_count |  |
| priority_refilled_count |  |
| secondary_refilled_count |  |
| preserved_error_count |  |
| primary_limiter |  |
| stop_reason |  |

Request outcomes:

- verify:
- priority_refill:
- secondary_refill:
- official_fallback:

Decision:

- keep / revert / needs more samples:
- next action:
```
