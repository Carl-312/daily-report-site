# 系统架构

本文是当前实现的架构基线，描述模块边界、数据流和发布安全约束。历史的早期架构草案保存在 [`../archive/plans/architecture-v1.md`](../archive/plans/architecture-v1.md)，不作为当前状态依据。

## 设计目标

日报是一个每天运行一次的文件型批处理，不需要数据库、队列或常驻服务。核心保证是：

> 每次运行要么生成一份完整、通过本地质量门禁的 edition 并原子发布，要么保留上一份已发布 edition，并留下可诊断的失败事实。

因此系统优先采用确定性的本地边界，而不是把正确性寄托在模型提示词、单次网络请求或人工检查上。

## 端到端数据流

```text
config.yaml + .env
        │
        ▼
  source registry ──► fetch_batch ──► SourceRunResult
        │
        ▼
  URL / story dedupe ──► canonical candidates
        │
        ▼
  optional Tavily enrichment (default off)
        │
        ▼
  staged JSON checkpoint + enrichment report
        │
        ▼
  SummaryResult (online provider or deterministic offline)
        │  article_id / count / URL / content contract
        ▼
  deterministic Markdown renderer
        │
        ▼
  staged static-site build
        │
        ▼
  publication policy ──► promote edition ──► compatibility mirror / Pages
```

`main.py` 负责编排，不应重新实现 source 解析、摘要解析或发布策略。每个阶段都应能在测试中独立替换和验证。

## 运行边界

### 1. 时钟与运行清单

`utils/run_contracts.py` 提供：

- `RunClock`：固定报告日期、时区、截止时间和剩余预算
- `DailyRunManifest`：记录 run、阶段、来源和发布状态
- `StageResult` / `SourceRunResult`：区分成功、降级、失败和可解释的空结果
- 脱敏配置快照和诊断文本清理

`create_run_observer()` 为每次运行创建 `.runs/<date>/<run_id>/` 工作区。运行失败时，`record_blocked_run()` 只更新清单，不触碰当前公开 edition。

### 2. 来源层

`sources/` 通过显式 registry 管理 source adapter；`fetch_batch()` 聚合来源结果，并将单源状态保留在 `SourceRunResult` 中。来源适配器负责 HTTP、解析、时间过滤和 `Article` 生成，不负责摘要或发布决策。

当前 source 包括关闭态的主候选 `agihunt`、`aibase`、`techcrunch`、`theverge` 和可选的 `syft`。`agihunt` 只经官方 Agent API 读取日报诊断和有限频道候选，默认保持关闭直到多日 shadow 通过；新增 source 的接口和验证见[扩展新闻源](../development/source-adapters.md)。

### 3. 输入去重层

`utils/dedupe.py` 是纯本地转换边界：

1. URL 统一 scheme、host、fragment、尾斜杠和查询参数；删除常见跟踪参数。
2. 相同 canonical URL 只保留一条。
3. 标题完全归一化相同，或跨来源明显改写且相似度达到阈值时合并。
4. 先按 source priority 排序，重复时保留优先级更高的候选。

这一步只减少重复输入，不负责判断新闻是否“值得报道”；更深的主体/主题配额仍属于后续质量策略。

### 4. 可选 enrichment 层

`utils/news_enrichment.py` 位于去重之后，不是 source registry 的替代品。Tavily 默认关闭；显式开启时按 verify、priority refill、secondary refill 和可选 official fallback 分阶段运行，并在 JSON 中写入预算、请求结果、接受/拒绝原因和 `stop_reason`。

enrichment 的失败语义是 fail-open：请求失败时尽可能保留已抓取的 deduped candidates，并记录诊断；它不能为了达到目标条数而绕过时间、相关性或去重门槛。当前开关、参数和灰度边界见[ Tavily 运行手册](../operations/tavily.md)。

### 5. 摘要边界

`summarizer.py` 负责 prompt、provider fallback、在线响应解析和离线结果生成；`utils/summary_contracts.py` 负责稳定数据模型与本地 renderer。

摘要输入会被注入稳定的 `a1`、`a2`… `article_id`。这里的 ID 是“来源引用”，不是新闻条目 ID：聚合日报、专题页等一个来源可以支撑多条独立新闻。发布前必须满足：

- 输出数量在独立日报上限 `max_summary_items` 内，不再与 `len(articles)` 绑定
- 每个 ID 来自输入；同一个 ID 可以重复引用，但每条必须是不同的可回溯事实
- 条目的 title、summary 非空
- 条目的 URL 与其来源候选 URL 一致
- Markdown 只由通过 `SummaryResult` 校验的结果渲染

输入去重与输出拆分是两个边界：`dedupe()` 仍然阻止同一抓取故事重复进入候选集，但不再阻止摘要器从一个合法的聚合来源拆出多条新闻。模型不能新增来源、URL 或事实；它只能重新组织输入来源中可支持的内容。

在线模型失败或质量校验失败时，生产路径拒绝用未经质量保证的离线文本替代；明确的 `--offline` 才使用确定性离线结果。

### 6. 文件和构建边界

`utils/storage.py` 以日期写入 JSON 和 Markdown，并使用原子单文件写入。`build.py` 只消费 staged `content/`，把结果写入 staged site 目录；它不应该直接改变当前公开目录。

单次完整发布由 `stage_and_publish_run()` 完成：

1. 在 run workspace 中准备完整 `data/content/site` edition。
2. 写入 JSON、Markdown 并构建静态站点。
3. 再次执行摘要契约和 publication policy。
4. 通过后调用 `promote_staged_edition()` 切换 `.publication/current.json` 指针。
5. 最后刷新 `data/`、`content/`、`dist/` 兼容镜像；镜像失败不回滚已选中的 edition。

等价 edition 会被识别为 no-op，不重复 promotion。构建或 promotion 前失败时，上一份公开 edition 保持不变。

## CLI 与重跑边界

```text
python main.py run       fetch → dedupe → enrich → summarize → stage/build/promote
python main.py fetch     fetch → dedupe → enrich → save JSON checkpoint
python main.py summarize 从当天 JSON checkpoint 重新生成并发布摘要/站点
python main.py build     从当前公开内容重新构建并发布站点 edition
python main.py test      provider 连接测试
```

`fetch` 的 JSON 是摘要阶段的检查点；`summarize` 可以在不重复抓取的情况下重跑。所有可发布路径都必须走同一套本地摘要契约和发布门禁。

## 部署边界

GitHub Actions 只在 `main` 的定时任务或明确 `publish=true` 时归档、提交保留窗口并发布 Pages。非 `main` 分支和 `publish=false` 只上传 preview artifact；不会修改生产 Pages。

仓库保留最近 7 天的 `data/` 与 `content/`，更早数据打包到 GitHub Release。运行与回滚细节见[运行与部署](../operations/README.md)。

## 未来演进的约束

优先级顺序保持：

1. 继续补强本地契约、运行清单和质量证据。
2. 在现有 `SummaryResult` 上逐步引入 provider 原生 JSON schema，不改变 renderer 的本地校验职责。
3. 拆分 enrichment 的策略、网络和报告模块，保持 `enrich_articles_with_tavily()` 边界稳定。
4. 只有多轮可解释证据证明收益后，才考虑扩大 enrichment 或引入更复杂的主题配额。

当前不引入数据库、消息队列或微服务；它们不能替代本项目需要的来源映射、失败保留和发布门禁。
