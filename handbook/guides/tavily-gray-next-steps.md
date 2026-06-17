# Tavily Gray 当前状态与下一轮测试策略

最后更新：2026-06-17

## 定位

本文记录 2026-06-17 更新 `TAVILY_API_KEY` 后的灰度现状，并规划下一轮 Tavily gray 测试策略。

核心原则：一轮实验只回答一个问题，一轮 API 调用不承担过多目标。不要在同一次 gray run 里同时调整预算、域名、query、fallback 和时间窗，否则结果无法归因。

## 当前状态

### 生产默认状态

- `config.yaml` 仍应保持 `enrichment.enabled: false`。
- Tavily 仍是 post-fetch enrichment，不是默认新闻源。
- 生产定时日报不应因为本次 key 修复而默认启用 Tavily。
- GitHub Actions 只保留 `Tavily Gray Daily` 作为 Tavily 灰度入口。
- `Daily Report Deploy` 不再提供 Tavily 灰度开关，不注入 `TAVILY_API_KEY`。
- gray workflow 继续只用于隔离验证，不提交、不发布、不部署。

### 最新失败样本：key 修复前

- Run: `27637098323`
- Event: `schedule`
- Date: `2026-06-17`
- Commit: `e568068939d0cc3b6987ffd81511baae4fb3f2d3`
- Result: workflow success, but Tavily API layer failed

关键指标：

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

结论：该 run 不能用于评估 Tavily 策略质量，只证明当时 GitHub Actions 中的 Tavily API 访问不可用。

### 最新成功样本：key 修复后

- Run: `27664628428`
- Event: `workflow_dispatch`
- Date: `2026-06-17`
- Commit: `e568068939d0cc3b6987ffd81511baae4fb3f2d3`
- Artifact local path: `/tmp/daily-report-gray-manual-27664628428`

关键指标：

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

Stage outcome:

| Stage | Calls | Results | Accepted | Request Outcomes |
|---|---:|---:|---:|---|
| verify | `5` | - | `5` | `{"success": 5}` |
| priority_refill | `1` | `8` | `3` | `{"success": 1}` |
| secondary_refill | `1` | `1` | `0` | `{"success": 1}` |
| official_fallback | `0` | `0` | `0` | `{}` |

结论：key 已恢复，Tavily API 可用；但灰度仍未达到 `min_articles=10`，不支持默认开启。

## 当前判断

本轮关键变化是问题类型变了：

- 之前是 `network_failure`：Tavily API 请求被 403 拒绝，策略质量不可评估。
- 现在是 `budget_exhausted` 加候选质量过滤：请求成功，但严格结果只有 8 条。

这说明下一步不应继续围绕 key 或 GitHub secret 排查，而应围绕“如何用更少、更清晰的 API 调用提高可解释 yield”做实验。

## 测试纪律

每个实验只改一个变量：

| 不要混合 | 原因 |
|---|---|
| 同时提高 `max_total_calls` 和 `refill_max_results` | 无法判断收益来自更多请求还是单次更多结果 |
| 同时调整 domain 和 query | 无法判断是域名质量变化还是搜索意图变化 |
| 同时启用 official fallback 和扩大媒体 refill | 无法判断补量来自媒体还是官方站点 |
| 同时放宽时间窗和改变 strict 规则 | 容易污染 `strict_final_count` |
| 把 key/network failure run 纳入质量样本 | 会把可用性故障误判成召回不足 |

每次 run 必须记录：

- run id、event、commit、artifact path
- changed variable
- exact override
- request outcomes
- stage accepted/rejected count
- `final_count / min_articles`
- `primary_limiter`
- decision: keep / revert / needs more samples

## Baseline repeat runbook

Baseline repeat 是下一轮 Tavily gray 的稳定性门禁，不是策略实验。它只回答一个问题：在不改任何变量的情况下，key 修复后的 gray workflow 是否能稳定访问 Tavily API，并产生可解释的 artifact。

### 运行条件

满足以下条件才允许启动 baseline repeat：

- `config.yaml` 不改，`enrichment.enabled` 继续保持 `false`。
- 不修改 `.github/workflows/tavily-gray.yml`、`.github/workflows/deploy.yml` 或代码。
- 不默认开启 Tavily，不把 Tavily 接入生产日报路径。
- 本轮 changed variable 记为 `none`，exact override 记为 `none`。
- 只使用 `Tavily Gray Daily` workflow，且 run 不提交、不发布、不部署。
- 每轮只产生一个样本；如果要进入变量实验，至少先收集 2 个通过门禁的 live 样本。

### Baseline repeat 操作步骤

1. 先确认本轮不包含配置、workflow 或代码变更；如果分支上已有其它改动，停止。
2. 优先等待 scheduled run；如果需要手动补一个样本，使用当前待验证 ref 触发：

   ```bash
   gh workflow run "Tavily Gray Daily" --repo Carl-312/daily-report-site --ref <ref>
   ```

3. 找到对应 run id，并等待完成：

   ```bash
   gh run list --repo Carl-312/daily-report-site --workflow "Tavily Gray Daily" --branch <ref> --limit 5
   gh run watch <run_id> --repo Carl-312/daily-report-site --exit-status
   ```

4. 下载 artifact 到独立目录：

   ```bash
   gh run download <run_id> --repo Carl-312/daily-report-site --dir /tmp/tavily-gray-baseline-<run_id>
   ```

5. 读取 artifact 中的 `scorecard.md`、`scorecard.json`、`enrichment-summary.json`。
6. 只判断 baseline 稳定性；不要因为单次 `final_count=10` 直接进入默认开启或生产路径。

### Action artifact 检查清单

每个 baseline sample 必须检查以下 artifact 和字段：

| Artifact | 必看字段 / 内容 | 用途 |
|---|---|---|
| `scorecard.md` | stage 表、accepted/rejected 摘要、人工可读结论 | 判断结果是否可解释 |
| `scorecard.json` | `final_count`、`min_articles`、`verified_count`、`primary_limiter`、`stop_reason`、`request_outcomes` | 判断是否达标、是否仍受限 |
| `enrichment-summary.json` | `priority_refilled_count`、`secondary_refilled_count`、`preserved_error_count`、各 stage request outcome | 判断 API 可用性和补量来源 |

记录时至少汇总：

- `final_count / min_articles`
- `verified_count`
- `priority_refilled_count`
- `secondary_refilled_count`
- `preserved_error_count`
- `request_outcomes`
- `primary_limiter`
- `stop_reason`

### Baseline repeat 通过/停止标准

通过 baseline 稳定性门禁需要同时满足：

- 至少 2 个 key 修复后的 live sample 完成并成功下载 artifact。
- `verify.request_outcomes.success >= 1`。
- priority / secondary refill request outcome 不出现 `http_error`、鉴权错误或网络失败。
- `preserved_error_count = 0`。
- `primary_limiter` 不再是 `network_failure`。
- 两个样本都能从 scorecard 解释 final count、补量来源和停止原因。

出现以下任一情况立即停止，不进入变量实验：

- request outcome 出现 `http_error`、403、鉴权错误、网络失败或 Tavily quota 异常。
- `preserved_error_count > 0`。
- artifact 缺失，或缺少 `scorecard.md`、`scorecard.json`、`enrichment-summary.json` 中任一关键文件。
- run 引入了配置、workflow 或代码变化，导致 baseline 不再是纯复测。
- 只有 1 个成功样本；它只能证明“这一次可用”，不能证明稳定。

### 记录模板

```markdown
### Baseline repeat: <run_id>

- Run URL:
- Event: scheduled / workflow_dispatch
- Ref / commit:
- Artifact path:
- Changed variable: none
- Exact override: none

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

- baseline gate: pass / stop / needs one more sample
- next action:
- notes:
```

### 进入下一轮实验的门槛

只有满足以下条件，才进入 budget/domain/query/official fallback 等变量实验：

- baseline repeat 已有至少 2 个通过样本。
- 两个样本都不含 `http_error`、鉴权错误、网络失败或 preserved error。
- 两个样本的 changed variable 都是 `none`，没有配置、workflow 或代码改动。
- 当前缺口可以从 artifact 中归因，例如 `budget_exhausted`、候选质量不足、domain 分层收益低或 query 意图过宽。
- 下一轮实验已经写明唯一变量、exact override、预期观察字段和停止条件。

如果 baseline 仍低于 `10`，但 API 可用性稳定，可以进入下一轮变量实验；如果 API 可用性不稳定，先排查 secret、账号、quota 或网络，不做策略实验。

## 下一轮优先方向

### 1. 先做稳定性复测

目标：执行上面的 baseline repeat runbook，确认 key 修复不是单次偶然成功。

做法：不改 workflow、不改配置、不改代码；收集 2 个通过门禁的 live sample，只判断 API 可用性和 current baseline 稳定性。

如果这里失败，先回到 secret / Tavily account / quota 排查，不进入策略实验。

### 2. 单独测试调用预算

目标：验证 `8/10` 是否主要由调用预算导致。

建议实验：

- 只提高 `max_total_calls`，例如从 `7` 提到 `9`。
- 不改 `refill_max_results`。
- 不改 domain。
- 不改 query。
- 不启用 official fallback。
- 不改变 strict/lenient 规则。

观察点：

- verify 是否能覆盖更多原始候选。
- priority / secondary 是否还有机会补足剩余 2 条。
- `final_count` 是否稳定达到 `10`。
- 新增结果是否仍为 AI 相关、非重复、严格时间窗内。

判断：

- 如果 `max_total_calls=9` 能稳定把 `final_count` 推到 `10`，预算是首要可尝试方向。
- 如果仍停在 `8` 左右，主要问题不是总预算，而是 refill 候选质量或 query/domain。

### 3. 单独测试 domain 分层

目标：判断当前 priority / secondary domain 分层是否合理。

本次成功样本中：

- priority refill 接受 `3/8`。
- secondary refill 接受 `0/1`。
- source distribution 是 `techcrunch: 14`，输入来源过于单一。

建议实验按 domain 分组独立观察，不要在同一 run 中混合多个新 domain 组合：

| 实验 | 只改变量 | 要回答的问题 |
|---|---|---|
| priority media only | priority 只保留 `reuters.com`、`arstechnica.com` | 高质量媒体是否能独立提供严格有效补量 |
| TechCrunch overlap check | priority 单独观察 `techcrunch.com` | TechCrunch 是否主要制造重复/cluster，还是仍有有效遗漏 |
| secondary recall check | secondary 单独观察 `thenextweb.com`、`venturebeat.com` | 历史 priority domain 在当前日期是否召回不足 |

判断：

- 如果某个 domain 组 accepted/result 明显高，可进入下一轮组合实验。
- 如果单独测试都低，不要扩大白名单；应先改 query 或补 source。

### 4. 单独测试 query 意图

目标：避免一个宽泛 query 同时承担模型、创业、融资、政策、开发者工具等所有意图。

当前 query：

```text
OpenAI Anthropic AI model launch startup funding developer tools
```

建议拆成窄 query，分多轮测试：

| Query 方向 | 适合验证 |
|---|---|
| `AI model launch OpenAI Anthropic Google Meta` | 模型发布和产品更新 |
| `AI startup funding acquisition venture capital` | 融资和公司动态 |
| `AI policy regulation security model access` | 政策、安全、合规事件 |
| `AI developer tools coding agents infrastructure` | 开发者工具和基础设施 |

每轮只替换 query，不改 budget/domain/fallback。观察 accepted/result、non-AI rejection、duplicate/cluster rejection。

### 5. 最后再测试 official fallback

目标：判断官方站点补量是否有必要。

不建议现在立刻启用，因为当前缺口是 `2`，且 media refill 已经成功补入 `3` 条。official fallback 应作为最后一层补救，而不是掩盖 media refill 的策略问题。

建议前置条件：

- API 可用性稳定。
- 调用预算或 domain/query 实验后仍稳定缺 1-2 条。
- scorecard 能清楚区分 official fallback accepted count。

实验约束：

- 只开启 `enable_official_fallback`。
- 不同时提高预算。
- 不同时改 query/domain。
- official fallback 的 accepted 结果必须单独标记，不能混入 media refill 结论。

## 推荐执行顺序

1. Baseline repeat：不改任何配置，收集 2 个成功 scheduled/manual 样本。
2. Budget-only run：只把 `max_total_calls` 从 `7` 提到 `9`。
3. Domain-only run：固定预算，只观察一个 domain 分层变化。
4. Query-only run：固定预算和 domain，只替换一个窄 query。
5. Official-fallback-only run：只有在仍缺 1-2 条时测试。

每一步都要先看 scorecard 再决定是否进入下一步。不要因为单次 `final_count=10` 直接默认开启 Tavily。

## 验收门槛

短期目标不是上线，而是找出最值得继续投入的变量。

一个方向值得继续，需要满足：

- 至少 2 次 live run 无 `http_error`。
- `final_count` 比当前 baseline `8` 明显提高，或稳定达到 `10`。
- `preserved_error_count = 0`。
- 新增 accepted candidate 不是明显重复、非 AI、过期或纯营销。
- scorecard 可以解释收益来自哪个 stage。

一个方向应停止，需要满足任一条件：

- request outcome 出现网络/鉴权错误。
- accepted/result 长期低于 `25%`。
- `final_count` 提升来自 lenient 候选污染 strict 输出。
- 需要同时改多个变量才能解释收益。

## 当前不做事项

- 不默认开启 Tavily。
- 不把 `enrichment.enabled` 改成 true。
- 不提交 `.env` 或任何 secret。
- 不把缺少 strict freshness 证明的候选写入正式 `final_count`。
- 不把单次手动成功 run 当作稳定性证据。
- 不在单轮 API 调用里塞入过宽 query 来同时解决召回、过滤、补量和域名评估。
