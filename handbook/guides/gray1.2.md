# Tavily Gray 1.2 测试内容

最后更新：2026-06-17

## 定位

本文记录 Tavily Gray 1.2 的测试设计和落盘模板，格式风格延续 `gray1.1.md`。Gray 1.2 不再继续验证 key 是否可用，而是围绕 Gray 1.1 暴露出的 yield 问题做两个独立方向的单变量测试。

本轮只回答两个互不冲突的问题：

1. Budget-only：如果只增加 Tavily 总调用预算，`final_count` 是否能从 `8/10` 接近或达到 `10/10`。
2. Domain-only：如果只调整 priority domain 分层，priority refill 的 accepted/result 质量是否更清晰。

这两个方向必须独立执行、独立记录、独立判断。不要把两个方向放进同一个 branch、同一个 commit 或同一次 action run，否则无法判断收益来自预算还是 domain。

## Gray 1.1 基线

Gray 1.1 的结论是：key/API 可用性门禁通过，但内容数量门槛未通过。

基线指标：

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

Gray 1.2 的所有判断都以这组基线为对照。任何方向只要出现 `http_error`、鉴权错误、quota 错误或 `network_failure`，都先停止策略判断，回到可用性排查。

## 本轮输入

| Item | Direction A | Direction B |
|---|---|---|
| Name | Gray 1.2A Budget-only | Gray 1.2B Domain-only |
| Suggested branch | `docs/tavily-gray-1.2-budget-only` | `docs/tavily-gray-1.2-domain-only` |
| Test question | 总调用预算是不是首要瓶颈 | priority domain 分层是不是造成低质量 refill |
| Changed variable | `max_total_calls` | `priority_refill_media_whitelist` |
| Exact override | `7 -> 9` | `["reuters.com", "arstechnica.com", "techcrunch.com"] -> ["reuters.com", "arstechnica.com"]` |
| Must stay fixed | domain、query、fallback、strict/lenient、`refill_max_results` | budget、query、fallback、strict/lenient、`refill_max_results` |
| Expected classification | strategy sample: budget-only | strategy sample: domain-only |

本轮文档变更范围只应包含：

```text
handbook/guides/gray1.2.md
```

真正执行测试时，两个方向各自使用独立测试分支。不要在同一个测试分支里同时修改预算和 domain。

## 共同约束

两个方向都必须保持以下约束：

- `config.yaml` 的生产默认不变，`enrichment.enabled` 继续为 `false`。
- 不默认开启 Tavily。
- 不启用 official fallback。
- 不修改 query。
- 不修改 strict/lenient freshness 规则。
- 不修改 `refill_max_results`。
- 不把单次 action 成功解释成可上线。
- 不把 lenient candidate 当成 strict final 的质量证明。
- 不把两个方向的结果合并成同一个结论。

## Direction A: Gray 1.2A Budget-only

### 测试目标

验证 Gray 1.1 的 `8/10` 是否主要由 `max_total_calls=7` 导致。

### 假设

如果主要瓶颈是总调用预算，那么只把 `max_total_calls` 从 `7` 提到 `9`，应该让 verify 或 refill 阶段获得更多有效机会，并把 `final_count` 推近或推到 `10`。如果结果仍停在 `8` 左右，预算不是首要变量，应转向 domain 或 query 质量。

### 只改一项

```text
max_total_calls: 7 -> 9
```

### 不改内容

- 不改 `refill_max_results`。
- 不改 priority/secondary domain。
- 不改 query。
- 不启用 official fallback。
- 不改 strict/lenient freshness。
- 不改 workflow 或代码。
- 不改生产默认开关。

### Action artifact 结果

执行后检查以下 artifact：

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
| final_count / min_articles |  |
| strict_final_count |  |
| verified_count |  |
| priority_refilled_count |  |
| secondary_refilled_count |  |
| official_refilled_count |  |
| preserved_error_count |  |
| total_calls |  |
| max_total_calls |  |
| primary_limiter |  |
| stop_reason |  |

Stage outcome：

| Stage | Calls | Results | Accepted | Request Outcomes |
|---|---:|---:|---:|---|
| verify |  |  |  |  |
| priority_refill |  |  |  |  |
| secondary_refill |  |  |  |  |
| official_fallback |  |  |  |  |

### 通过标准

- request outcome 全部无 `http_error`。
- `preserved_error_count = 0`。
- `max_total_calls = 9` 在 artifact 中可见。
- `final_count` 明显高于 Gray 1.1 基线 `8`，最好达到 `10`。
- 新增 accepted candidate 不是明显重复、非 AI、过期或纯营销。
- scorecard 能解释新增收益来自 verify、priority refill 或 secondary refill 的哪一段。

### 停止标准

- 出现网络、鉴权或 quota 错误。
- `final_count` 仍停在 `8` 左右。
- 新增调用主要产生 duplicate、outside window、non-AI 或低质量候选。
- `primary_limiter` 仍是 budget，但多出来的调用没有带来严格结果。

### Direction A 判断

执行后填写：

- keep / revert / needs more samples:
- next action:
- 是否允许进入第二个 budget-only 样本:

## Direction B: Gray 1.2B Domain-only

### 测试目标

验证 priority domain 分层是否影响 refill 质量，尤其是 TechCrunch 是否主要带来重复/cluster，而 Reuters 与 Ars Technica 是否能提供更清晰的严格补量。

### 假设

如果当前 priority refill 的质量被 TechCrunch 重复项稀释，那么只把 priority domain 缩到 `reuters.com` 和 `arstechnica.com`，accepted/result 比例可能更清晰，即使 result_count 下降也更容易判断高质量媒体是否值得保留在 priority 层。

### 只改一项

```text
priority_refill_media_whitelist:
  - reuters.com
  - arstechnica.com
```

也就是从当前 priority 组中移除 `techcrunch.com`。secondary domain 保持不变。

### 不改内容

- 不改 `max_total_calls`，继续保持 Gray 1.1 基线 `7`。
- 不改 `refill_max_results`。
- 不改 query。
- 不启用 official fallback。
- 不改 strict/lenient freshness。
- 不改 workflow 或代码。
- 不改生产默认开关。

### Action artifact 结果

执行后检查以下 artifact：

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
| final_count / min_articles |  |
| strict_final_count |  |
| verified_count |  |
| priority_refilled_count |  |
| secondary_refilled_count |  |
| official_refilled_count |  |
| preserved_error_count |  |
| priority result_count |  |
| priority accepted/result |  |
| primary_limiter |  |
| stop_reason |  |

Stage outcome：

| Stage | Calls | Results | Accepted | Request Outcomes |
|---|---:|---:|---:|---|
| verify |  |  |  |  |
| priority_refill |  |  |  |  |
| secondary_refill |  |  |  |  |
| official_fallback |  |  |  |  |

Domain diagnostics：

| Metric | Value |
|---|---:|
| Reuters candidates |  |
| Reuters accepted |  |
| Ars Technica candidates |  |
| Ars Technica accepted |  |
| duplicate_or_cluster rejected |  |
| outside window rejected |  |
| non-AI rejected |  |

### 通过标准

- request outcome 全部无 `http_error`。
- `preserved_error_count = 0`。
- artifact 能确认 priority domain 只包含 `reuters.com` 和 `arstechnica.com`。
- priority accepted/result 比 Gray 1.1 更清晰，最好高于 `25%`。
- accepted candidate 具备 strict freshness，并且不是重复、非 AI 或营销内容。
- 即使 `final_count` 未达到 `10`，也能回答 high-signal domain 是否值得进入后续组合实验。

### 停止标准

- 出现网络、鉴权或 quota 错误。
- priority result_count 太低，无法评估 domain 质量。
- accepted/result 低于 `25%`。
- 移除 TechCrunch 后没有带来更清晰的严格补量。
- 结果只能靠同时增加 budget 或修改 query 才能解释。

### Direction B 判断

执行后填写：

- keep / revert / needs more samples:
- next action:
- 是否允许进入 domain 组合样本:

## 两个方向的关系

| Evidence | Decision |
|---|---|
| A 成功，B 未执行 | 先复测 A，不直接合并 domain 变更。 |
| A 成功，B 失败 | 预算更可能是首要变量，domain 方向暂缓。 |
| A 失败，B 成功 | domain 质量更可能是首要变量，预算方向暂缓。 |
| A 和 B 都成功 | 仍不能直接合并上线；下一轮 Gray 1.3 才能设计组合实验。 |
| A 和 B 都失败 | 不继续堆预算或 domain，转向 query-only。 |
| 任一方向出现 `http_error` | 停止策略判断，先查 API 可用性。 |

不要把 A 的 `final_count` 提升和 B 的 accepted/result 改善写成同一个因果结论。A 测的是预算，B 测的是 domain，二者只能在单独成立后再进入组合实验。

## 安全默认确认

两个方向都必须在 `gray-experiment-overrides.json` 或对应 artifact 中确认：

```json
{
  "unchanged_safety_defaults": {
    "enabled": false,
    "enable_official_fallback": false
  }
}
```

如果 artifact 显示 `enabled=true` 被写入生产配置，或 official fallback 被意外开启，本轮结果不进入策略判断。

## Gray 1.2 结论模板

执行后统一填写：

```markdown
## Gray 1.2 结论

### 已证明

-

### 未证明

-

### Direction A: Budget-only

- Run URL:
- Ref / commit:
- Artifact path:
- Changed variable: `max_total_calls`
- Exact override: `7 -> 9`
- Decision:

### Direction B: Domain-only

- Run URL:
- Ref / commit:
- Artifact path:
- Changed variable: `priority_refill_media_whitelist`
- Exact override: remove `techcrunch.com` from priority
- Decision:

### 下一步建议

-
```

## 当前不做事项

- 不默认开启 Tavily。
- 不修改 production deploy。
- 不把 `enrichment.enabled` 改成 true。
- 不提交 `.env` 或任何 secret。
- 不同时测试 budget 和 domain。
- 不在 Gray 1.2 中测试 query-only 或 official-fallback-only。
- 不把单次 action 成功当作稳定性或上线证据。
