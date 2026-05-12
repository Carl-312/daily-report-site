# Tavily 后续优化与验证计划

## 文档定位

本文定义 Tavily enrichment 后续迭代的验证方向。它不是当前状态总览；当前实现、配置与历史结论仍以
`handbook/guides/tavily-integration.md` 为准。

当前基线：

- Tavily 仍默认关闭，只能通过 `--enrichment on` 或 GitHub Actions 手动灰度入口显式启用。
- `2026-05-11` 灰度 artifact 已暴露并回归覆盖默认预算冲突：verify 不能挤占全部补量预算。
- 当前优化重点不是“多拿几条新闻”，而是在可解释、可复现、可回滚的前提下逐步提高最终结果质量。

## 总体验证原则

每次 Tavily 迭代必须同时回答三个问题：

1. 是否可复现：同一输入和 mock Tavily 响应下，结果是否 deterministic。
2. 是否可解释：JSON `enrichment` 字段是否能说明每篇文章来自 verify、preserved、priority refill、secondary refill 或 official fallback。
3. 是否值得上线：live 灰度是否证明收益超过成本、误伤和不稳定性。

任何单次 live 成功都不能作为默认开启依据。默认开启必须依赖多日灰度样本、确定性 replay、质量抽查和成本边界共同通过。

## 方向一：确定性回放与回归测试

### 目标

把真实灰度中发现的问题压缩成小 fixture 和 mock Tavily 响应，保证预算、补量、fail-open、JSON 保存和 summary 输入链路不会再次退化。

重点覆盖：

- `dedupe -> enrich_articles_with_tavily -> save_json -> summarize/offline_summary -> build` 链路。
- `max_total_calls`、`max_verify_calls`、`reserved_refill_calls`、`verify_budget` 的边界组合。
- verify / preserved 已满足 `min_articles` 时不触发 refill。
- 不足 `min_articles` 时先 priority refill，再 secondary refill。
- Tavily 请求失败时保留原始候选，不把 transport error 误判为内容无效。
- refill candidates 必须进入 JSON，并被后续 summary 消费。

### 验证方法

- 从每个重要 gray artifact 生成最小 fixture，只保留输入文章、旧指标和必要诊断字段。
- 单元测试必须 monkeypatch `utils.news_enrichment.search_tavily`，禁止真实 Tavily 网络调用。
- 为每个 bug 写至少一个回归断言，断言字段必须落在可复盘诊断上，例如：
  - `reserved_refill_calls`
  - `verify_budget`
  - `verify_skipped_due_budget`
  - `priority_refill_runs`
  - `secondary_refill_runs`
  - `accepted_by_stage_preview`
  - `final_count`
  - `stop_reason`
- 对主流程写窄集成测试，mock fetch、enrich、summary 和 build，确认文章对象从 enrichment 结果一路传到 JSON 和 summary。
- 每次策略改动至少运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider
ruff check .
ruff format --check .
git diff --check
```

### 通过标准

- 所有测试 deterministic，不依赖 live Tavily、当前日期或外部网络。
- 任一预算策略调整都必须有默认配置和至少一个极端配置测试。
- 任一 stop reason 调整都必须有测试证明该原因可由诊断字段解释。

## 方向二：生产灰度观测与 artifact 评分

### 目标

把 GitHub Actions 手动灰度从“能跑”升级为“可比较”。每次灰度都应输出同一组指标，便于判断变化是代码改动、Tavily 返回波动、source 输入变化还是网络问题导致。

重点观测：

- 上游 source 输入质量：`input_count`、source 分布、聚合型标题数量。
- verify 效果：`verify_calls`、`verified_count`、`preserved_error_count`、`validation_outcome` 分布。
- refill 效果：priority / secondary 的 `result_count`、`accepted_count`、`published_date` 缺失率、重复拒绝数。
- 预算效果：`reserved_refill_calls`、`verify_budget`、`total_calls`、是否进入 secondary。
- 输出效果：`final_count`、`refill_remaining_count`、summary 中实际展示的条数。
- 失败效果：timeout、HTTP error、connection error、runner 代理环境影响。

### 验证方法

- 每次手动灰度保留 artifact，并生成一份标准评估 Markdown。
- 评估文档固定包含：
  - run id
  - command
  - artifact path
  - old/new commit
  - 核心指标表
  - accepted / rejected stage preview
  - 预算是否按预期生效
  - 是否值得转成 fixture
  - 不能证明什么
- 建议补一个轻量 artifact parser，把 `report.json` 和 `enrichment-summary.json` 规范化为 scorecard，避免人工抄指标。
- 连续灰度时使用同一张趋势表，至少跟踪：
  - `final_count`
  - `verified_count`
  - `priority_refilled_count`
  - `secondary_refilled_count`
  - `published_date_missing_rate`
  - `total_calls`
  - `stop_reason`

### 通过标准

- 每次 live 灰度都能在不看日志全文的情况下解释最终条数。
- 如果 `final_count < min_articles`，必须能区分是预算耗尽、metadata 缺失、候选质量差、source 为空还是网络失败。
- 至少连续多次灰度证明 Tavily 不会让已有有效 source 候选丢失，才考虑扩大调用预算或调整默认策略。

## 方向三：补量策略与质量门槛实验

### 目标

在不牺牲可解释性和成本边界的前提下，提高有效补量率。优化范围包括 budget 分配、domain 分层、query、时间窗、timeout、official fallback 和候选质量规则。

优先级建议：

1. metadata 稳定性：优先解决 `published_date` 缺失导致可用候选为 0 的问题。
2. stage 成本控制：确认 priority / secondary / official fallback 每一层的边际收益。
3. 质量门槛：避免为了凑满 10 条引入泛科技、融资噪音或同 story 近重复。

### 验证方法

- 对每个策略实验建立假设：
  - 例：扩大 secondary domain 能提升 `secondary_refilled_count`，但不会提高 duplicate slip。
  - 例：开启 official fallback 能增加可信候选，但不应成为默认主补量来源。
  - 例：调整 query 能提高 `published_date` 可用候选比例。
- 先在 replay / fixture 中验证机制，再用手动灰度验证 live 收益。
- 每个实验至少记录：
  - 参数变化
  - 调用成本变化
  - 接受数变化
  - 拒绝原因变化
  - final article 质量抽查结论
  - 是否需要新增诊断字段
- 对候选质量做人工抽查，至少检查标题是否 AI 相关、是否重复已有 story、是否在报告窗口内、是否来自可接受来源。
- 对 official fallback 单独统计，不和 media refill 混在同一个指标里判断。

### 通过标准

- 策略改动必须在确定性测试中证明不会破坏旧预算和 fail-open 行为。
- live 灰度必须显示可解释收益，而不是只显示 `final_count` 变高。
- 如果收益依赖 official fallback、更多调用预算或更宽时间窗，必须明确标注为灰度配置，不得直接改默认开启路径。

## 推荐迭代节奏

每一轮 Tavily 优化按这个顺序推进：

1. 从灰度或用户反馈定义一个具体问题。
2. 抽取最小 fixture 或新增 mock scenario。
3. 写失败测试或评估基线。
4. 修改策略或实现。
5. 跑确定性验证。
6. 手动灰度一次，生成标准评估文档。
7. 根据评估结果决定：固化为 fixture、继续实验、回滚或放弃。

## 不做事项

- 不因为单日 gray final_count 变高就默认开启 Tavily。
- 不把 Tavily 改成常驻 source。
- 不在单元测试中真实调用 Tavily 网络。
- 不用扩大 domain 白名单替代质量评估。
- 不把 `published_date` 缺失的候选静默当作有效 24 小时新闻。

## 下一步建议

优先补 artifact scorecard 工具或脚本，让每次 GitHub Actions 灰度 artifact 自动生成统一指标表。这个工具完成后，再开始对 secondary domains、query 和 official fallback 做小步实验。
