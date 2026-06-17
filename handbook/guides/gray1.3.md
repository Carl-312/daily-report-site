# Tavily Gray 1.3 下一轮测试计划

最后更新：2026-06-17

## 定位

本文综合 `gray1.1.md`、`gray1.2.md` 和 2026-06-17 三次 Tavily Gray Actions artifact，重新判断下一轮应该如何测试。

Gray 1.3 只解决一个决策问题：现在应该继续开分支、合并已有分支，还是换一种受控实验方式。

结论先行：

- 当前两个文档分支的 Actions 结果不能视为 budget/domain 两个策略实验。
- 它们实际都是同一套 gray runtime override 的 baseline repeat。
- 可以合并文档改进，但不能合并任何策略变量，也不能把当前分支结果解释为上线证据。
- 下一步应先做真实的 Budget-only 单变量实验；如果 budget 不成立，再做 Domain-only。
- 实验承载推荐用临时实验分支或后续 workflow_dispatch input harness；测试分支跑完不合并。

## 输入证据

### 已有文档

| File | 作用 | 关键结论 |
|---|---|---|
| `handbook/guides/gray1.1.md` | key 修复后 baseline repeat 记录 | API 可用性通过，`final_count=8/10`，主限制从 network failure 转为 `budget_exhausted`。 |
| `handbook/guides/gray1.2.md` | Budget-only / Domain-only 测试设计 | 设计了两个独立方向，但文件仍是计划模板，不包含 A/B 实测结果。 |

### 2026-06-17 live runs

| Label | Run | Ref | Commit | 结果 |
|---|---|---|---|---|
| main manual baseline | `27664628428` | `main` | `e568068` | success |
| baseline runbook branch | `27666067059` | `docs/tavily-gray-baseline-runbook` | `390db51` | success |
| experiment matrix branch | `27666343322` | `docs/tavily-gray-experiment-matrix` | `cfed301` | success |

三次 scorecard 在忽略 `run_id` 和 `new_commit` 后完全一致。

| Metric | Value |
|---|---:|
| final_count / min_articles | `8 / 10` |
| strict_final_count | `8` |
| verified_count | `5` |
| priority_refilled_count | `3` |
| secondary_refilled_count | `0` |
| priority result_count | `8` |
| priority accepted/result | `3 / 8 = 37.5%` |
| secondary result_count | `1` |
| total_calls / max_total_calls | `7 / 7` |
| primary_limiter | `budget_exhausted` |
| stop_reason | `budget_exhausted_after_secondary_refill` |
| preserved_error_count | `0` |
| source_distribution | `{"techcrunch": 14}` |

Request outcomes:

| Stage | Outcome |
|---|---|
| verify | `{"success": 5}` |
| priority_refill | `{"success": 1}` |
| secondary_refill | `{"success": 1}` |
| official_fallback | `{}` |

Runtime overrides 也一致：

```json
{
  "experiment": "gray_3_lenient_3day_diagnostic",
  "enrichment": {
    "strict_hours": 24,
    "refill_max_results": 8,
    "refill_search_window_hours": 72,
    "lenient_refill_diagnostics_enabled": true,
    "lenient_refill_window_hours": 72,
    "trusted_domains": {
      "priority_refill_media_whitelist": [
        "reuters.com",
        "arstechnica.com",
        "techcrunch.com"
      ],
      "secondary_refill_candidate_domains": [
        "thenextweb.com",
        "venturebeat.com"
      ]
    }
  },
  "unchanged_safety_defaults": {
    "enabled": false,
    "enable_official_fallback": false
  }
}
```

## 证据重分类

当前三次成功 run 应归类为 baseline repeat，不是策略实验。

原因：

- `max_total_calls` 都是 `7`，没有执行 `7 -> 9` 的 Budget-only。
- priority domain 都是 `reuters.com`、`arstechnica.com`、`techcrunch.com`，没有执行移除 `techcrunch.com` 的 Domain-only。
- `gray-config-diff.patch` 一致，说明 runner 中的临时配置覆盖一致。
- scorecard 的 stage count、request outcome、accepted preview 和 limiter 一致。
- 两个文档分支只改变 handbook 内容，不改变灰度策略变量。

因此，Gray 1.2 的 A/B 设计还没有被真正执行。当前只能说明：

- key/API 修复后，在同一天同一输入条件下 Tavily 请求稳定成功。
- artifact 生成链路稳定。
- 当前 baseline 的数量问题可重复表现为 `8/10` 和 `budget_exhausted`。

但不能说明：

- 提高预算是否能补齐 2 条。
- 移除 TechCrunch 是否能提高 priority refill 质量。
- query 是否需要变窄。
- official fallback 是否应该启用。
- 生产默认是否可以打开 Tavily。

## 分支、合并、还是其他

### 对现有两个文档分支

可以合并文档价值，不能合并策略意义。

如果要合并：

- 只把它们当作 handbook 改进。
- 合并前应在文档里明确这些 run 是 baseline repeat，不是 A/B 策略结果。
- 不要把 `docs/tavily-gray-experiment-matrix` 的 run 当成 Domain-only 或 Budget-only 证据。

如果不合并：

- 也不会影响下一轮测试，因为它们没有产生策略变量证据。
- 可以直接以 `gray1.3.md` 作为新的决策依据。

### 对策略测试分支

推荐使用临时实验分支，但分支只作为运行载体，不作为待合并变更。

原因：

- 当前 `.github/workflows/tavily-gray.yml` 的 gray override 是硬编码的。
- 不改 workflow/config，就无法跑出真正的 Budget-only 或 Domain-only。
- Domain-only 尤其不能只改 `config.yaml`，因为 workflow 会在 runner 中重新覆盖 priority domain。

临时分支规则：

- 分支名必须带测试目的，例如 `test/tavily-gray-1.3-budget-9`。
- 每个分支只改一个变量的 runtime override。
- 跑完下载 artifact，记录 run id 和结论。
- 不把测试分支合并到 `main`。
- 如果需要保留知识，只合并文档记录，不合并实验 override。

### 对长期测试方式

如果 Gray 1.3 之后还要继续跑 query-only、fallback-only 或多日样本，应该做一个单独的 gray harness，而不是继续复制分支。

推荐 harness 形式：

- 给 `workflow_dispatch` 增加受控 input，例如 `experiment=baseline|budget_9|domain_priority_media|query_model_launch`。
- scheduled run 默认仍使用 baseline，不接受危险变量。
- workflow 根据 input 写出 `gray-experiment-overrides.json`，包含：
  - `experiment`
  - `changed_variable`
  - `exact_override`
  - `unchanged_safety_defaults`
- 每个 input 只能映射到预定义 override，不允许手填任意 YAML。

这个 harness 可以后续作为基础设施 PR 合并；但它本身不等于策略通过。

## Gray 1.3 推荐执行顺序

### Step 0: 冻结当前结论

先把当前三次 run 记录为 baseline repeat 样本：

| Sample | 用途 |
|---|---|
| `27664628428` | key 修复后 main baseline |
| `27666067059` | 文档分支 baseline repeat |
| `27666343322` | 文档分支 baseline repeat |

这一步的结论是：API 可用，baseline 可解释，但 `8/10` 未达标。

不要继续重复同样的文档分支 baseline，除非要验证跨天稳定性。跨天稳定性应优先等待 scheduled run，而不是同一天继续手动跑同配置。

### Step 1: Gray 1.3A Budget-only

优先测试预算，因为当前所有成功样本的主限制都是 `budget_exhausted`，并且只差 `2` 条达到 `min_articles=10`。

测试问题：

> 只把 `max_total_calls` 从 `7` 提到 `9`，是否能让 strict final count 从 `8` 接近或达到 `10`。

实验承载：

| Item | Value |
|---|---|
| Branch | `test/tavily-gray-1.3-budget-9` |
| Changed variable | `max_total_calls` |
| Exact override | `7 -> 9` |
| Must stay fixed | domain、query、fallback、strict/lenient、`refill_max_results` |
| Merge policy | 不合并测试分支 |

实现要求：

- 在 gray runtime override 中显式写入 `max_total_calls: 9`。
- `gray-experiment-overrides.json` 必须记录 `changed_variable=max_total_calls` 和 `exact_override=7 -> 9`。
- `scorecard.json` 必须显示 `budget.max_total_calls = 9`。
- priority domains 必须仍是 `reuters.com`、`arstechnica.com`、`techcrunch.com`。
- secondary domains 必须仍是 `thenextweb.com`、`venturebeat.com`。
- `enable_official_fallback` 必须仍为 `false`。
- `enrichment.enabled` 生产默认必须仍为 `false`。

必看指标：

| Metric | Why |
|---|---|
| `final_count / min_articles` | 判断是否补齐数量缺口。 |
| `strict_final_count` | 防止 lenient 候选冒充 strict 质量。 |
| `verified_count` | 判断新增预算是否让 verify 多接受。 |
| `priority_refilled_count` | 判断 priority refill 是否继续有效。 |
| `secondary_refilled_count` | 判断 secondary 是否只是低 yield。 |
| `total_calls / max_total_calls` | 判断是否仍被预算卡住。 |
| `primary_limiter` | 判断瓶颈是否从 budget 转移到 candidate quality。 |
| rejected counts | 判断新增调用是否被重复、过期、非 AI 或营销内容吞掉。 |

通过标准：

- request outcomes 无 `http_error`、鉴权错误、quota 错误或 network failure。
- `preserved_error_count = 0`。
- artifact 能证明唯一变化是 `max_total_calls: 7 -> 9`。
- `final_count` 高于 `8`，最好达到 `10`。
- 新增 accepted article 是 strict、非重复、AI 相关、非营销内容。

强通过：

- `final_count=10/10`。
- `strict_final_count=10`。
- `primary_limiter` 不再是单纯 `budget_exhausted`，或虽仍预算耗尽但新增预算带来明确严格收益。
- 下一步只允许 repeat budget-only，一次成功不能直接合并默认值。

弱通过：

- `final_count=9/10`。
- 新增 1 条 strict 高质量 article。
- 下一步继续 budget-only repeat，暂不进入组合实验。

失败：

- `final_count` 仍为 `8/10`。
- `total_calls=9` 但新增调用没有带来 strict accepted。
- 新增结果主要被 duplicate、outside window、non-AI 或低质量过滤吞掉。
- 进入 Domain-only 或 Query-only，不再继续堆预算。

### Step 2: Gray 1.3B Domain-only

只有在 Budget-only 没有清晰解决数量缺口时，才执行 Domain-only。

测试问题：

> 移除 `techcrunch.com` 后，priority refill 的 accepted/result 质量是否更清晰。

实验承载：

| Item | Value |
|---|---|
| Branch | `test/tavily-gray-1.3-domain-priority-media` |
| Changed variable | `priority_refill_media_whitelist` |
| Exact override | `["reuters.com", "arstechnica.com", "techcrunch.com"] -> ["reuters.com", "arstechnica.com"]` |
| Must stay fixed | budget、query、fallback、strict/lenient、`refill_max_results` |
| Merge policy | 不合并测试分支 |

实现要求：

- `max_total_calls` 必须保持 `7`。
- priority domains 只包含 `reuters.com`、`arstechnica.com`。
- secondary domains 仍保持 `thenextweb.com`、`venturebeat.com`。
- query 不变。
- official fallback 不启用。
- `refill_max_results` 不变。

Domain-only 的主指标不是 `final_count=10`，而是 priority refill 质量。

原因：

- 当前 baseline priority accepted/result 已经是 `3/8 = 37.5%`。
- `>25%` 只能作为最低门槛，不能作为成功标准。
- 移除 TechCrunch 可能降低 result_count，也可能减少 duplicate/cluster 噪音。
- 如果 accepted/result 变高但 final_count 下降，它仍可能是有价值的诊断结果。

通过标准：

- artifact 证明唯一变化是 priority domain。
- request outcomes 无错误。
- `preserved_error_count = 0`。
- priority accepted/result 高于或明显不低于 baseline `37.5%`。
- duplicate/cluster rejected 比例下降。
- accepted article 仍是 strict、非重复、AI 相关。

失败：

- priority result_count 太低，无法判断。
- accepted/result 低于 baseline 且没有解释价值。
- 移除 TechCrunch 同时减少 accepted count，又没有降低重复或低质量噪音。
- 结果必须依赖 budget 或 query 同时变化才能变好。

### Step 3: 不在 Gray 1.3 做组合实验

即使 Budget-only 和 Domain-only 都有正向信号，也不要在 Gray 1.3 直接合并成 `budget + domain`。

组合实验的条件：

- Budget-only 至少有 1 个强通过或 2 个弱通过样本。
- Domain-only 至少有 1 个质量改善样本。
- 两者都没有 request error。
- 两者的 artifact 都能证明唯一变量变化。

满足后，组合实验应进入 Gray 1.4，而不是混入 Gray 1.3。

## 决策矩阵

| 观察结果 | 下一步 |
|---|---|
| Budget-only 达到 `10/10` 且 strict 质量正常 | Repeat budget-only 一次；仍不合并测试分支。 |
| Budget-only 到 `9/10` 且新增 article 质量正常 | 再跑一个 budget-only 样本；不急着改 domain。 |
| Budget-only 仍为 `8/10` | 停止预算方向，执行 Domain-only。 |
| Budget-only 新增调用主要是重复/过期/非 AI | 停止预算方向，转 Query-only 或 Domain-only。 |
| Domain-only accepted/result 高于 baseline 且更少重复 | 保留为候选，后续 repeat 或 Gray 1.4 组合。 |
| Domain-only result_count 太低 | 不采用该 domain 切法，转 Query-only。 |
| 任一 run 出现 `http_error` 或 quota/auth 错误 | 停止策略判断，回到 API 可用性排查。 |
| 任一 run artifact 缺失关键字段 | 该 run 不进入样本池。 |

## 记录模板

```markdown
### Gray 1.3A Budget-only: <run_id>

- Run URL:
- Ref / commit:
- Artifact path:
- Changed variable: `max_total_calls`
- Exact override: `7 -> 9`
- Merge policy: do not merge test branch

| Metric | Value |
|---|---:|
| final_count / min_articles |  |
| strict_final_count |  |
| verified_count |  |
| priority_refilled_count |  |
| secondary_refilled_count |  |
| preserved_error_count |  |
| total_calls / max_total_calls |  |
| primary_limiter |  |
| stop_reason |  |

Decision:

- strong pass / weak pass / fail / invalid:
- next action:
```

```markdown
### Gray 1.3B Domain-only: <run_id>

- Run URL:
- Ref / commit:
- Artifact path:
- Changed variable: `priority_refill_media_whitelist`
- Exact override: remove `techcrunch.com` from priority
- Merge policy: do not merge test branch

| Metric | Value |
|---|---:|
| final_count / min_articles |  |
| strict_final_count |  |
| priority result_count |  |
| priority accepted_count |  |
| priority accepted/result |  |
| duplicate_or_cluster rejected |  |
| outside window rejected |  |
| non-AI rejected |  |
| preserved_error_count |  |
| primary_limiter |  |
| stop_reason |  |

Decision:

- pass / fail / invalid:
- next action:
```

## Gray 1.3 执行记录

### Gray 1.3A Budget-only: 27667942594

- Run URL: https://github.com/Carl-312/daily-report-site/actions/runs/27667942594
- Ref / commit: `test/tavily-gray-1.3-budget-9` / `69834beb3533d0c3e3f42e4f361afbe836eb5948`
- Artifact path: `gray/tavily/2026-06-17/`
- Downloaded artifact: `/tmp/tavily-gray-27667942594/tavily-gray-2026-06-17-27667942594/gray/tavily/2026-06-17/`
- Changed variable: `max_total_calls`
- Exact override: `7 -> 9`
- Merge policy: do not merge test branch

| Metric | Value |
|---|---:|
| final_count / min_articles | `9 / 10` |
| strict_final_count | `9` |
| verified_count | `6` |
| priority_refilled_count | `3` |
| secondary_refilled_count | `0` |
| preserved_error_count | `0` |
| total_calls / max_total_calls | `8 / 9` |
| primary_limiter | `candidate_quality` |
| stop_reason | `below_min_articles_after_secondary_refill_official_fallback_disabled` |

Decision:

- weak pass: budget-only improved from the baseline `8/10` to `9/10`, with strict quality preserved and no request errors.
- next action: repeat Budget-only once, per the decision matrix for a `9/10` result.

### Gray 1.3A Budget-only repeat: 27668011534

- Run URL: https://github.com/Carl-312/daily-report-site/actions/runs/27668011534
- Ref / commit: `test/tavily-gray-1.3-budget-9` / `69834beb3533d0c3e3f42e4f361afbe836eb5948`
- Artifact path: `gray/tavily/2026-06-17/`
- Downloaded artifact: `/tmp/tavily-gray-27668011534/tavily-gray-2026-06-17-27668011534/gray/tavily/2026-06-17/`
- Changed variable: `max_total_calls`
- Exact override: `7 -> 9`
- Merge policy: do not merge test branch

| Metric | Value |
|---|---:|
| final_count / min_articles | `9 / 10` |
| strict_final_count | `9` |
| verified_count | `6` |
| priority_refilled_count | `3` |
| secondary_refilled_count | `0` |
| preserved_error_count | `0` |
| total_calls / max_total_calls | `8 / 9` |
| primary_limiter | `candidate_quality` |
| stop_reason | `below_min_articles_after_secondary_refill_official_fallback_disabled` |

Decision:

- weak pass repeat: the repeat reproduced `9/10`, not `10/10` and not `8/10`.
- next action: do not merge the test branch. The Domain-only branch `test/tavily-gray-1.3-domain-priority-media` was not opened because the budget-only result did not remain at `8/10`.

## 当前不做事项

- 不默认开启 Tavily。
- 不把 `enrichment.enabled` 改成 `true`。
- 不合并任何测试分支中的 runtime override。
- 不把当前两个文档分支解释成 Budget-only 或 Domain-only 证据。
- 不同时测试 budget 和 domain。
- 不启用 official fallback。
- 不修改 query。
- 不把同一天重复 baseline 当成跨天稳定性证明。
- 不把单次成功 Action 当成上线证据。

## 可合并实验 Harness

Gray 1.3A 的两个 Budget-only 样本已经证明 `max_total_calls: 7 -> 9`
能把本日样本从 baseline `8/10` 推到 `9/10`，但它只是 weak pass
repeat，不是 `10/10`，也不是跨天稳定性证据。因此本轮不把
`budget_9` 设为 scheduled/default，而是把结果沉淀为可合并的受控
实验 harness。

Harness 只允许 `workflow_dispatch` 选择以下预定义实验：

| Experiment | 唯一变量 | 说明 |
|---|---|---|
| `baseline` | none | 保持现有 Gray 3 lenient 3-day diagnostic runtime override。 |
| `budget_9` | `max_total_calls` | 只把 `max_total_calls` 从 `7` 提到 `9`。 |
| `domain_priority_media` | `trusted_domains.priority_refill_media_whitelist` | 只把 priority domains 从 `["reuters.com","arstechnica.com","techcrunch.com"]` 改为 `["reuters.com","arstechnica.com"]`，并保持 `max_total_calls=7`。 |

手动运行命令：

```bash
gh workflow run tavily-gray.yml --ref infra/tavily-gray-experiment-harness -f experiment=baseline
gh workflow run tavily-gray.yml --ref infra/tavily-gray-experiment-harness -f experiment=budget_9
gh workflow run tavily-gray.yml --ref infra/tavily-gray-experiment-harness -f experiment=domain_priority_media
```

每次 run 都必须检查 artifact：

```text
gray/tavily/<date>/logs/gray-experiment-overrides.json
gray/tavily/<date>/scorecard.json
gray/tavily/<date>/logs/gray-config-diff.patch
```

`gray-experiment-overrides.json` 必须包含：

- `experiment`
- `changed_variable`
- `exact_override`
- `reason`
- `enrichment`
- `unchanged_safety_defaults`

安全边界：

- `schedule` 不读取危险变量，始终使用 `baseline`。
- `workflow_dispatch` 只有 `experiment` 一个 choice input，不提供任意
  YAML、domain、query 或 budget 输入。
- `config.yaml` 的生产默认保持不变，`enrichment.enabled=false`。
- official fallback 仍不启用。
- query 不修改。
- `test/tavily-gray-1.3-budget-9` 只作为实验载体，不合并到 `main`。
