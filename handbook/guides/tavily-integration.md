# Tavily 接入总览与进度状态

## 文档定位

本文是日报项目 Tavily 接入工作的统一入口，合并并校准以下分散材料：

- `handbook/guides/history/tavily-news-enrichment.md`
- `handbook/guides/history/tavily-trusted-domains-draft.md`
- `handbook/guides/history/tavily-prefilter-relaxation-plan.md`
- `data/benchmarks/tavily-*.md`
- `data/2026-04-01.json`
- 当前代码中的 `main.py`、`config.py`、`config.yaml`、`utils/news_enrichment.py`
- 当前测试中的 `tests/test_news_enrichment.py`

旧文档仍作为历史设计和实验记录保留；后续判断当前状态时，以本文为准。

本文状态基准：`2026-06-17`，基于当前工作区代码、文档和
`2026-05-11` 以来的 Tavily GitHub Actions 灰度 artifact。

## 一句话结论

Tavily 已经完成 Phase 0 研究、trusted domains 实验、replay harness、正式模块第一版、`main.py` 接线、GitHub Actions 手动灰度入口和独立定时灰度日报；但 `config.yaml` 中仍默认关闭，生产发布 workflow 的定时任务仍不默认启用 Tavily，也还没有达到可长期默认开启的稳定度。

当前更准确的成熟度判断：

| 层级 | 状态 | 完成度判断 |
|---|---|---:|
| API 可用性验证 | 已验证 | 80% |
| Benchmark 与域名研究 | 已完成首轮收敛 | 85% |
| Replay / dry run harness | 已完成并产出结论 | 75% |
| 正式模块接入 | 第一版已落地 | 65% |
| 诊断与 fail-open | 已有基础，仍在加固 | 60% |
| 生产 GitHub Actions 接线 | 已有手动 `enable_tavily` 开关、独立 `tavily-gray` 定时灰度与 main 回写路径，仍需多日样本验证 | 65% |
| 默认开启 | 不建议开启 | 0% |

当前决策：继续保持 `enrichment.enabled: false`，用 `--enrichment on` 做本地或手动灰度验证。不要把 Tavily 改成常驻 source，也不要因为单日结果差就扩大白名单。

## 当前代码状态

### 已接入的正式链路

`main.py` 当前已经把 Tavily enrichment 放在 `dedupe` 之后、保存 JSON 之前：

```text
fetch_all
-> dedupe
-> enrich_articles_with_tavily
-> save_json
-> summarize
-> build
```

具体行为：

- `run` 会执行抓取、去重、Tavily 增强、保存 JSON、摘要、构建。
- `fetch` 会执行抓取、去重、Tavily 增强、保存 JSON。
- `summarize` 只读取既有 JSON，不会再次调用 Tavily。
- JSON 顶层会写入 `enrichment` 诊断字段。

入口函数：

- `main.py`: `resolve_enrichment_enabled()`
- `main.py`: `apply_enrichment()`
- `utils/news_enrichment.py`: `enrich_articles_with_tavily()`

### 正式模块职责

`utils/news_enrichment.py` 是当前正式模块。它不是新闻源适配器，而是 post-fetch enrichment layer。

已经具备：

- 输入 `Article` 或 `dict` 的统一转换。
- 本地 prefilter。
- exact verify。
- verify / preserved 后不足 `min_articles` 时触发 priority refill。
- priority 仍不足时触发 secondary refill。
- 默认从 `max_total_calls` 中为 priority + secondary refill 预留调用预算，避免 verify 消耗完补量空间。
- optional official fallback。
- 24 小时严格时间窗判断。
- exact URL / same-domain + title similarity 匹配。
- refill 合并阶段 near-duplicate / story-cluster 拦截，并按剩余缺口停止接收候选，避免补过量。
- request timeout / HTTP error / connection error 分类。
- `preserved_error_articles` fail-open 路径。
- `accepted_by_stage_preview`、`verify_runs`、`rejected_candidates` 等诊断字段。

当前仍没有：

- retry 策略。
- stage-specific timeout 配置。
- 生产 runner 下的 Tavily 手动灰度实跑验证。
- official fallback 默认启用依据。

### Tavily 调用方式

当前项目没有引入 Tavily Python SDK，直接使用 `requests.Session.post()` 调：

```text
https://api.tavily.com/search
```

请求体中包含 `api_key` 与搜索参数。

当前 Context7 对 Tavily 官方文档的校验结果显示，项目正在使用的这些能力仍是当前 Search API 支持的能力：

- `query`
- `topic: news`
- `search_depth`
- `max_results`
- `include_domains`
- `start_date`
- `end_date`
- `include_answer`
- `include_raw_content`
- 结果字段 `published_date`

注意：项目当前代码把 `auto_parameters` 固定为 `False`，目的是避免 Tavily 自动扩大搜索深度或改变成本特征。

## 配置状态

### 环境变量

代码已经读取：

```bash
TAVILY_API_KEY
```

位置：

- `config.py`: `tavily_api_key = os.getenv("TAVILY_API_KEY", "")`

当前状态：

- `.env.example` 已提供 `TAVILY_API_KEY=` 示例。
- `Daily Report Deploy` 只在手动触发且 `enable_tavily=true` 时注入 `TAVILY_API_KEY`。
- `Daily Report Deploy` 定时任务不显式启用 Tavily，仍跟随默认关闭配置。
- `Tavily Gray Daily` 定时任务显式注入 `TAVILY_API_KEY` 并运行 `--enrichment on`，用于独立灰度样本和 main 回写。

### `config.yaml`

当前默认配置：

```yaml
enrichment:
  enabled: false
  trust_env: true
  min_articles: 10
  strict_hours: 24
  max_total_calls: 7
  max_verify_calls: 6
  max_refill_rounds: 1
  refill_max_results: 8
  verify_search_depth: basic
  enable_fuzzy_second_pass: false
  enable_official_fallback: false
  priority_refill_query: "OpenAI Anthropic AI model launch startup funding developer tools"
  official_fallback_query: "OpenAI Anthropic AI model launch startup funding developer tools"
  trusted_domains:
    priority_refill_media_whitelist:
      - thenextweb.com
      - venturebeat.com
    secondary_refill_candidate_domains:
      - reuters.com
      - arstechnica.com
    official_fallback_domains:
      - openai.com
      - anthropic.com
```

含义：

- `enabled: false`: 日常默认不启用 Tavily。
- `trust_env: true`: `requests.Session` 继承系统代理环境。
- `min_articles: 10`: 目标新闻数，但不强行凑数。
- `strict_hours: 24`: 严格时间窗。
- `max_total_calls: 7`: 单次运行 Tavily 总预算。
- `max_verify_calls: 6`: exact verify 上限；实际 verify budget 会先从
  `max_total_calls` 扣除 priority + secondary refill 预留调用。
- `max_refill_rounds: 1`: 每个 refill stage 默认 1 轮；仅在最终候选仍不足 `min_articles` 时触发。
- `verify_search_depth: basic`: verify 用低成本路径。
- `enable_fuzzy_second_pass: false`: Phase 0 没证明 fuzzy 有收益。
- `enable_official_fallback: false`: 官方域名补充仍需显式开启。

### CLI 开关

当前支持：

```bash
python3 main.py run --enrichment auto
python3 main.py run --enrichment on
python3 main.py run --enrichment off
python3 main.py fetch --enrichment auto
python3 main.py fetch --enrichment on
python3 main.py fetch --enrichment off
```

开关语义：

- `auto`: 跟随 `config.yaml` 的 `enrichment.enabled`。
- `on`: 本次命令强制启用。
- `off`: 本次命令强制关闭。

## 实验与证据进度

### Phase 0 benchmark

产物：

- `scripts/benchmark_tavily.py`
- `data/benchmarks/tavily-baseline-2026-04-01.json`
- `data/benchmarks/tavily-baseline-2026-04-01.md`

已确认：

- `verify_exact` + `basic` + `max_results=3`: `3/4` 命中，平均延迟约 `546 ms`，`published_date` 可用率 `100%`。
- `verify_exact` + `advanced` 没有提升命中率。
- `verify_fuzzy` + `advanced` 没有 rescue case。
- 英文 refill query 有效，新增有效新闻 `4` 条。
- 中文泛 AI refill query 在该窗口新增有效新闻 `0` 条。

落地结论：

- verify 默认用 `basic`。
- 不保留 fuzzy second pass。
- 聚合标题不直接进入 article-level verify。
- refill query 优先使用英文主题 query。

### trusted domains 首轮研究

产物：

- `scripts/benchmark_tavily_whitelist.py`
- `data/benchmarks/tavily-whitelist-2026-04-01.json`
- `data/benchmarks/tavily-whitelist-2026-04-01.md`
- `handbook/guides/history/tavily-trusted-domains-draft.md`

首轮结论：

| Domain | 当前分层 | 核心理由 |
|---|---|---|
| `thenextweb.com` | priority refill | 非重合、平均新增有效候选 `3`、`published_date` 稳定 |
| `venturebeat.com` | priority refill | AI 相关性高、重复低、平均新增有效候选 `1.3333` |
| `techcrunch.com` | high-overlap 对照 | 已是 configured source，重复已有结果偏高 |
| `openai.com` | official fallback | 少量但可信，不适合主媒体 refill |
| `anthropic.com` | official fallback | 少量但可信，不适合主媒体 refill |
| `reuters.com` | secondary/deferred | metadata 稳定但 AI 主题拟合较弱 |
| `arstechnica.com` | secondary/deferred | metadata 稳定但 AI 主题拟合较弱 |
| `www.theverge.com` | excluded | `published_date` 不稳定 |
| `blog.google` | excluded | `published_date` 不稳定、有效新增不足 |
| `news.aibase.com` | excluded | 聚合源，不适合 article-level verify/refill |

### whitelist 保留性复测

产物：

- `data/benchmarks/tavily-whitelist-retention-2026-04-01-round12.json`
- `data/benchmarks/tavily-whitelist-retention-2026-04-01-round12.md`

已确认：

- `thenextweb.com` 继续满足 priority refill 保留条件。
- `venturebeat.com` 继续满足 priority refill 下界。
- `techcrunch.com` 继续只适合作为高重合对照。
- `openai.com`、`anthropic.com` 继续适合作为 official fallback。
- `blog.google` 继续不应进入默认名单。
- 本轮 18 个请求全部成功。

### deferred 池挑战赛

产物：

- `data/benchmarks/tavily-whitelist-deferred-2026-04-01-round3.json`
- `data/benchmarks/tavily-whitelist-deferred-2026-04-01-round3.md`

已确认：

- `reuters.com`: `published_date` 稳定、重复低，但平均新增有效候选 `1`，低于 `venturebeat.com` 下界。
- `arstechnica.com`: 与 `reuters.com` 类似，继续留在 deferred。
- `www.theverge.com`: 平均 `published_date` 可用率只有 `0.3333`，继续排除。
- 本轮 9 个请求全部成功。

当前决策：

- 不扩展 priority whitelist。
- `reuters.com` 与 `arstechnica.com` 只作为 secondary refill 候选。
- `www.theverge.com` 不进入默认路径。

### dry run / replay harness

产物：

- `scripts/experiment_news_enrichment.py`
- `data/benchmarks/tavily-enrichment-dryrun-2026-04-01.json`
- `data/benchmarks/tavily-enrichment-dryrun-2026-04-01.md`
- `data/benchmarks/tavily-enrichment-dryrun-2026-04-01-step*.json`
- `data/benchmarks/tavily-enrichment-dryrun-2026-04-01-step6.md`

最终 dry run 摘要：

| Report Date | Raw | Deduped | Prefiltered | Verify Calls | Refill Calls | Verified | Media Refilled | Final | Stop Reason |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2026-03-24 | 15 | 15 | 4 | 4 | 2 | 2 | 3 | 5 | `official_fallback_disabled` |
| 2026-03-25 | 14 | 14 | 9 | 6 | 1 | 4 | 4 | 8 | `budget_exhausted_after_priority_refill` |

已确认：

- default budget 下有机会接近 10 条，但不能稳定达到 10 条。
- cluster 在 refill 合并阶段有价值，至少拦住过同 story 不同 URL 的补全结果。
- prefilter 候选自身尚未形成可用 cluster，因此 verify 预算节省只有实现，没有实测收益。
- official fallback 可以手动开启并单独统计，但证据不足以默认开启。

### 2026-05-11 GitHub Actions Tavily 灰度样本

产物：

- 本地 artifact：
  `tmp/github-artifacts/tavily-gray-2026-05-11-25680995172/gray/tavily/2026-05-11/`
- 评估结论：`data/benchmarks/tavily-gray-2026-05-11-evaluation.md`
- 标准 scorecard：
  - `data/benchmarks/tavily-gray-2026-05-11-scorecard.json`
  - `data/benchmarks/tavily-gray-2026-05-11-scorecard.md`
- 最小回归 fixture：
  `tests/fixtures/tavily-gray-2026-05-11/report-minimal.json`
- 回归测试：`tests/test_tavily_gray_regression.py`

事实摘要：

| Metric | Old gray value |
|---|---:|
| `input_count` | `13` |
| `prefiltered_count` | `12` |
| `verify_calls` | `6` |
| `refill_calls` | `1` |
| `total_calls` | `7` |
| `final_count` | `3` |
| `stop_reason` | `budget_exhausted_after_priority_refill` |

scorecard 归一化结论：

- `primary_limiter`: `budget_exhausted`
- `contributing_factors`: `budget_exhausted`, `published_date_missing`
- `published_date_missing_rate`: `1.0`
- `secondary_entered`: `false`
- `refill_remaining_count`: `7`
- stage 分解：`3 final articles = 0 preserved + 3 verify + 0 priority refill + 0 secondary refill + 0 official fallback`

这个 artifact 的 `article_count` / `final_count` 实际是 `3`，不是 `6`。旧逻辑在
默认 `max_total_calls=7`、`max_verify_calls=6` 下让 verify 用掉 6 次预算，只剩
1 次 priority refill；priority 返回的候选缺少可用 `published_date`，因此接受数为
0，且没有预算进入 secondary refill。

当前修复：

- 默认会从 `max_total_calls` 中预留 priority + secondary refill 调用空间。
- 默认配置下 `reserved_refill_calls=2`，`verify_budget=5`，不再是 `6`。
- `reserved_refill_calls` 和 `verify_budget` 都写入 enrichment 诊断字段，便于复盘。
- priority refill 仍不足 `min_articles` 时，secondary refill 会有机会执行。

这不是 Tavily 默认开启的证据。它只能证明一个具体预算冲突已经被转成可回归的样本：
verify 不能再把全部默认预算挤占到 secondary refill 无法运行。真实 Tavily 返回仍可能因
`published_date` 缺失、网络波动或候选质量不足而补不满 `10` 条；official fallback
仍保持默认关闭。

### Tavily gray scorecard 工具

新增离线 parser：

- `scripts/tavily_gray_scorecard.py`
- 测试：`tests/test_tavily_gray_scorecard.py`

用途：

- 从灰度 artifact 目录读取 `report.json`、`enrichment-summary.json`、`manifest.json`
  和 `logs/run.log`。
- 输出 `scorecard.json` 与 `scorecard.md`。
- 固定归一化核心指标、stage accepted / rejected preview、预算字段、趋势字段和
  `final_count < min_articles` 的主因诊断。
- 不调用 Tavily，不依赖当前日期，不依赖外部网络。

本地复盘示例：

```bash
PYTHONPATH=. python3 scripts/tavily_gray_scorecard.py \
  tmp/github-artifacts/tavily-gray-2026-05-11-25680995172/gray/tavily/2026-05-11 \
  --output-json data/benchmarks/tavily-gray-2026-05-11-scorecard.json \
  --output-md data/benchmarks/tavily-gray-2026-05-11-scorecard.md
```

`.github/workflows/tavily-gray.yml` 现在会在收集灰度产物后自动调用该脚本，并把
`scorecard.json`、`scorecard.md` 一并上传到 Tavily gray artifact。后续连续灰度可直接
汇总这些 `trend_metrics` 字段：

- `final_count`
- `verified_count`
- `priority_refilled_count`
- `secondary_refilled_count`
- `published_date_missing_rate`
- `total_calls`
- `stop_reason`

## 正式真实运行结果

产物：

- `data/2026-04-01.json`
- `content/2026-04-01.md`

命令：

```bash
python3 main.py run --enrichment on
```

结果：

- 上游 `aibase`、`techcrunch`、`theverge` live 请求全部超时。
- `input_count = 0`。
- Tavily enrichment 被触发：`enabled = true`、`applied = true`。
- `verify_calls = 0`。
- `refill_calls = 2`。
- `fallback_calls = 0`。
- `total_calls = 2`。
- priority refill 与 secondary refill 都在 `45` 秒超时。
- `final_count = 0`。
- 主流程仍完成 JSON、Markdown、HTML 构建。

这个结果说明：

- 正式控制面已跑通。
- Tavily 请求失败不会中断主流程。
- 但在 source 为空且 Tavily 超时时，当前结果仍可能为 `0` 条。
- 这不是可以默认开启的状态。

## 当前诊断字段

JSON 的 `enrichment` 字段是复盘入口。

关键字段：

| 字段 | 含义 |
|---|---|
| `enabled` | 本次是否启用 Tavily 逻辑 |
| `applied` | 是否实际进入增强流程 |
| `skip_reason` | 未执行或降级原因 |
| `error` | 顶层异常 |
| `input_count` | dedupe 后输入文章数 |
| `prefiltered_count` | 进入 verify 的本地候选数 |
| `prefilter_stats` | 本地预筛统计 |
| `verify_calls` | exact verify 调用数 |
| `refill_calls` | media refill 调用数 |
| `fallback_calls` | official fallback 调用数 |
| `total_calls` | Tavily 总调用数 |
| `reserved_refill_calls` | 本轮从总预算中预留给 refill/fallback 的调用数 |
| `verified_count` | verify 接受数 |
| `preserved_error_count` | verify 请求失败但保留的原始文章数 |
| `priority_refilled_count` | priority refill 接受数 |
| `secondary_refilled_count` | secondary refill 接受数 |
| `official_refilled_count` | official fallback 接受数 |
| `refill_needed_count` | verify / preserved 后距离 `min_articles` 的初始缺口 |
| `refill_remaining_count` | 所有 refill / fallback 后仍缺的条数 |
| `near_duplicate_rejected_count` | 近重复拦截数 |
| `story_cluster_rejected_count` | 同 story 拦截数 |
| `final_count` | 最终进入 JSON / summary 的文章数 |
| `stop_reason` | 阶段停止原因 |
| `accepted_by_stage_preview` | 各阶段接受标题预览 |
| `verify_runs` | verify 请求与判定明细 |
| `rejected_candidates` | verify 拒绝或请求失败明细 |
| `priority_refill_runs` | priority refill 请求明细 |
| `secondary_refill_runs` | secondary refill 请求明细 |
| `official_fallback_runs` | official fallback 请求明细，仅启用时出现 |

当前仍需要加固：

- refill stage 的 `request_outcome` 已在单轮 run 里有返回，但历史 `data/2026-04-01.json` 中主要通过 `error` 字段体现 timeout，诊断语义仍可继续统一。
- source 为空时的 `stop_reason` 需要比旧的 `official_fallback_disabled` 更精确。当前工作区已有未提交修改，把它细化为 `below_min_articles_after_*_official_fallback_disabled`。

## 当前测试状态

`tests/test_news_enrichment.py` 当前覆盖：

- enrichment 关闭时直通。
- 启用但缺 `TAVILY_API_KEY` 时安全降级。
- `config.yaml` enrichment 配置解析。
- verify timeout 时保留原始文章。
- `session.trust_env` 跟随配置。
- source 为 0 且 official fallback 关闭时的 stop reason 语义。
- verify / preserved 已达到 `min_articles` 时不再触发 refill。
- priority refill 不足时继续调用 secondary refill，并只接收剩余缺口需要的候选。
- 默认预算会保留 secondary refill 机会，避免 verify 用满 `max_total_calls`。
- verify 命中但超出 24 小时或缺少 `published_date` 时拒绝。
- prefilter 分层为 `core_ai`、`ai_neighbor`、`generic_or_low_signal`，并按该顺序消耗 verify 预算。
- 聚合型标题在 verify 前硬拒绝。
- refill 仍保持严格 AI 标题相关性门禁。

`tests/test_tavily_gray_regression.py` 额外覆盖：

- 从 `2026-05-11` 灰度样本重建 13 条输入。
- mock verify / priority refill / secondary refill Tavily responses，单元测试不真实调用 Tavily 网络。
- 断言旧灰度事实：`final_count=3`、`verify_calls=6`、`refill_calls=1`、没有 secondary refill。
- 断言当前默认预算：`reserved_refill_calls=2`，`verify_budget=5`。
- 断言不足 `min_articles` 时 priority refill 之后继续 secondary refill。
- 断言 Tavily refill articles 会进入 JSON，并进入后续 `offline_summary` 输入。
- 断言 verify request error 被 preserved 后如果已满足 `min_articles`，不会触发 refill。

本轮集成验收使用的验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider
```

结果：

```text
22 passed, 1 warning
```

warning 是 Pydantic V2 class-based `Config` deprecation，与 Tavily 行为无直接关系。

## GitHub Actions 状态

当前 `.github/workflows/deploy.yml` 已提供 Tavily 手动灰度入口，但不会在该生产发布 workflow 的定时任务中默认开启 Tavily。

当前手动触发支持：

```text
enable_tavily=false: 维持默认路径，不显式启用 Tavily
enable_tavily=true: 注入 TAVILY_API_KEY，并向 main.py run 追加 --enrichment on
```

生成步骤会根据手动输入构造参数：

```bash
python main.py run "${ENRICHMENT_ARGS[@]}"
python main.py run --offline "${ENRICHMENT_ARGS[@]}"
```

当前边界：

- `Daily Report Deploy` 中，`TAVILY_API_KEY` 只在手动触发且 `enable_tavily=true` 时注入。
- `Daily Report Deploy` 的 `enable_tavily=false` 和 schedule 定时任务不会追加 `--enrichment on`。
- 手动启用但缺少 `TAVILY_API_KEY` 时，主流程应完成并由 enrichment 层安全降级。
- `.github/workflows/tavily-gray.yml` 的 schedule 会显式运行 `python3 main.py run --offline --enrichment on`，需要 `TAVILY_API_KEY`，并仅在 `main` 定时运行中把生成的 `data/` / `content/` 回写为最终报告。
- `tavily-gray` 手动实验只上传 7 天 artifact，不回写仓库。

因此，生产发布 workflow 仍保持默认关闭；独立 Tavily 灰度日报负责收集定时样本，并把 main 定时样本按 7 天窗口保存到仓库。

## 当前工作区状态说明

当前工作区存在 Tavily multi-agent PR 相关未提交改动：

- `.env.example`
- `.github/workflows/deploy.yml`
- `handbook/deployment/github-actions.md`
- `handbook/guides/tavily-integration.md`
- `tests/test_news_enrichment.py`
- `utils/news_enrichment.py`
- `content/2026-05-05.md` 当前为未跟踪生成产物，集成验收不依赖它

这些改动表示 Tavily 迭代正在继续，尤其集中在：

- verify prefilter 分层放宽。
- 更精确的 request / validation outcome 与 stop reason。
- source 为 0 条时的诊断说明。
- Actions 手动灰度入口和 `.env.example` key 示例。

本文不会把这些未提交改动视为已经合并到远端生产，只记录为当前工作区事实。

## 未完成事项与风险

### P0: 不适合默认开启

原因：

- 已有真实运行证明 source 超时 + Tavily 超时时可得到 0 条。
- GitHub Actions 已有手动 secret 注入路径，但还缺生产 runner 实跑样本。
- 还没有多日稳定样本证明默认路径可靠。

退出条件：

- 连续多日或多组 replay/live 样本证明 source 非空与 source 为空都可解释。
- request timeout 不会清空已有候选。
- GitHub Actions 手动启用路径可复盘。

### P1: prefilter 分层仍需样本验证

当前 `build_prefilter_summary()` 已把候选分为 `core_ai`、`ai_neighbor`、`generic_or_low_signal`，并让 verify 按这个顺序消耗预算；聚合型标题仍会在 verify 前硬拒绝。

风险：

- AI 邻近新闻已经能进入 verify，但仍需要多日样本确认不会浪费过多预算。
- `generic_or_low_signal` 也可能进入 verify 队列，必须依赖预算顺序和后续诊断判断收益。

计划：

- 保持 refill 严格 AI 标题门禁。
- 用 `prefilter_bucket_counts`、`neighbor_candidates_verified_count`、`neighbor_candidates_outside_24h_count`、`neighbor_candidates_no_match_count` 复盘收益。
- 不因单日样本直接扩大默认调用预算。

### P1: 生产手动灰度待实跑

当前 Actions 已提供 `enable_tavily` 手动开关、条件注入 `TAVILY_API_KEY`，并在手动启用时追加 `--enrichment on`。

计划：

- 在 GitHub Actions 手动触发一次 `enable_tavily=true`。
- 如果没有 secret，确认日志 warning 与 missing-key 安全降级成立。
- 如果有 secret，检查 `data/YYYY-MM-DD.json` 的 `enrichment` 字段能复盘 verify/refill/fallback。
- 每次手动验证后检查 JSON 的 `enrichment` 字段。

### P1: refill 超时策略不足

当前 timeout 是模块级常量：

```python
REQUEST_TIMEOUT_SECONDS = 45
```

风险：

- live 网络波动下，priority 和 secondary refill 都可能阻塞到 45 秒后失败。
- 不同 stage 没有差异化 timeout 或 retry。

计划：

- 先补更清晰的 stage-level `request_outcome` 和 `stop_reason`。
- 再决定是否加短 timeout、retry、或 stage-specific budget。

### P2: 旧文档分散且语义冲突

旧文档有些段落仍写着“只用于实验、不改正式链路”，但代码已经有正式模块第一版。

当前处理方式：

- 本文作为统一入口。
- 旧文档顶部加归档/来源说明。
- 后续若继续修改 Tavily 行为，优先更新本文。

## 下一步建议

### 下一步 1: 手动验证 Actions Tavily 灰度入口

只验证生产 runner 接线，不改每日默认。

验收：

- `enable_tavily=false` 时不追加 `--enrichment on`。
- `enable_tavily=true` 且无 secret 时，日志提示缺 key 并安全降级。
- `enable_tavily=true` 且有 secret 时，JSON `enrichment` 字段能复盘 Tavily 是否执行、失败在哪个阶段、保留了哪些原始文章。

### 下一步 2: 多日样本评估默认开启

只有在下面条件满足后，才考虑把 `config.yaml` 改成 `enabled: true`：

- source 非空时 verify 不误伤主要真值。
- source 为空时 refill 结果可解释。
- Tavily timeout 不会让已有文章丢失。
- Actions 手动路径至少多次成功。
- JSON 诊断足够支撑复盘。

## 操作速查

### 本地验证默认关闭路径

```bash
python3 main.py fetch --enrichment off
python3 main.py run --offline --enrichment off
```

看点：

- 主流程是否正常抓取和保存。
- JSON `enrichment.skip_reason` 是否为 `disabled`。
- 这是安全关闭命令，适合回滚到不依赖 Tavily 的路径。

### 本地显式启用 Tavily

```bash
TAVILY_API_KEY=... python3 main.py fetch --enrichment on
```

看点：

- `enrichment.enabled`
- `enrichment.applied`
- `verify_calls`
- `refill_calls`
- `fallback_calls`
- `total_calls`
- `final_count`
- `stop_reason`
- `verify_runs[*].request_outcome`
- `verify_runs[*].validation_outcome`

### 离线完整链路验证

```bash
TAVILY_API_KEY=... python3 main.py run --offline --enrichment on
```

用途：

- 隔离摘要模型 API 干扰。
- 验证抓取、Tavily、保存、Markdown、HTML 构建是否能串起来。

### source 为 0 条时如何解读

当 `input_count = 0` 时，Tavily 只能进入受控 refill 场景：

- `verify_calls = 0` 是正常现象，因为没有已有 source 候选可 verify。
- 最终文章只能来自 `priority_refill`、`secondary_refill` 或显式开启的 `official_fallback`。
- 如果 refill 请求 timeout 或失败，`final_count` 可能仍为 `0`。
- 这不能证明 verify 已经成熟，也不能证明 source 层可以废弃。

### Tavily 失败时的预期行为

Tavily 请求失败时必须保持 fail-open：

- 主流程继续完成 JSON 落盘、Markdown 生成和 HTML 构建。
- verify 请求失败时，已有 deduped articles 尽量通过 `preserved_error_articles` 保留。
- 顶层 `error`、`skip_reason`、`stop_reason` 或 stage run 中的 `request_outcome` 必须能复盘失败原因。
- 失败不能被写成“验证失败后丢弃文章”的正常结果。

### 单元测试

```bash
PYTHONPATH=. pytest -q tests/test_news_enrichment.py
```

### 当前推荐的文档更新规则

后续 Tavily 相关变更优先更新本文。

只有在需要保留原始实验过程时，才补充：

- `history/tavily-trusted-domains-draft.md`
- `history/tavily-prefilter-relaxation-plan.md`
- benchmark 结果文件

## 源材料索引

### 代码

- `main.py`
- `config.py`
- `config.yaml`
- `utils/news_enrichment.py`
- `utils/__init__.py`
- `tests/test_news_enrichment.py`

### 实验脚本

- `scripts/benchmark_tavily.py`
- `scripts/benchmark_tavily_whitelist.py`
- `scripts/experiment_news_enrichment.py`

### benchmark 产物

- `data/benchmarks/tavily-baseline-2026-04-01.json`
- `data/benchmarks/tavily-baseline-2026-04-01.md`
- `data/benchmarks/tavily-whitelist-2026-04-01.json`
- `data/benchmarks/tavily-whitelist-2026-04-01.md`
- `data/benchmarks/tavily-whitelist-retention-2026-04-01-round12.json`
- `data/benchmarks/tavily-whitelist-retention-2026-04-01-round12.md`
- `data/benchmarks/tavily-whitelist-deferred-2026-04-01-round3.json`
- `data/benchmarks/tavily-whitelist-deferred-2026-04-01-round3.md`
- `data/benchmarks/tavily-enrichment-dryrun-2026-04-01.json`
- `data/benchmarks/tavily-enrichment-dryrun-2026-04-01.md`
- `data/benchmarks/fixtures/tavily-replay-fixture-2026-04-29-curated.json`

### 旧文档

- `handbook/guides/history/tavily-news-enrichment.md`
- `handbook/guides/history/tavily-trusted-domains-draft.md`
- `handbook/guides/history/tavily-prefilter-relaxation-plan.md`
