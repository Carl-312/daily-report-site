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
  Lead/Story gate + Tavily enrichment (default on, fail-open)
        │
        ▼
  editorial catalog + story clustering + v2 shortlist
        │  relevance / entity / model / topic / source diagnostics
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

当前 source 包括关闭态的主候选 `agihunt`、`aibase`、`techcrunch`、`theverge` 和可选的 `syft`。
`techcrunch` 与 `theverge` 分别读取官方 AI RSS/Atom feed，直接保存正文摘要和权威发布时间，
即使 Tavily 不可用也能形成独立 Story。`agihunt` 只经官方 Agent API 读取日报诊断和有限频道
候选，默认保持关闭直到多日 shadow 通过；新增 source 的接口和验证见
[扩展新闻源](../development/source-adapters.md)。

### 3. 输入去重层

`utils/dedupe.py` 是纯本地转换边界：

1. URL 统一 scheme、host、fragment、尾斜杠和查询参数；删除常见跟踪参数。
2. 相同 canonical URL 只保留一条。
3. 标题完全归一化相同，或跨来源明显改写且相似度达到阈值时合并。
4. 先按 source priority 排序，重复时保留优先级更高的候选。

这一步只处理 URL 和标题层面的明显重复；跨语言同事件、AI 相关性、主体和模型家族配额由后续
`source_balanced_v2` 选择层处理。

### 4. 可选 enrichment 层

`utils/news_enrichment.py` 位于去重之后，不是 source registry 的替代品。当前 Tavily 默认开启：
抓取后先形成确定性候选队列；队列内 Lead 和直接 Story 都进入最多两轮 Tavily，生产路径不再执行
独立 verify/refill。JSON 记录候选顺序、预算、请求结果、接受/拒绝原因和 `stop_reason`。

主新闻采用证据硬门禁。Lead 只有在 Tavily 找到同一主体、同一事件的直接来源、真实发布时间和
足够事实正文后，才能转换为 Story 并进入摘要候选。补证失败、证据不足或检索结果换题时，Lead
只保留为 observation signal；不得因候选不足、降低优先级、加上“据称”等保守措辞或放宽选择
配额进入主新闻。这一规则不删除抓取线索，只隔离未证实线索与可对读者负责的正式新闻。

Tavily 同样补充已有直接链接的 Story，并始终以原 URL、主要主体和事件身份为锚，不得替换选题；
补充失败时保留原 Story 的标题、URL、发布时间和正文。

Tavily 结果应保存为每条候选最多三份直接来源组成的结构化 evidence packet，至少保留标题、URL、
发布时间和正文片段。系统不增加逐条新闻的中间研究模型；同一个最终摘要模型直接消费原始元数据
和 evidence packet，生成受证据约束的事实句及允许有限推断的意义句。

Tavily 前的候选顺序由确定性元数据队列决定，不引入 AI 预选：先做同事件去重，再按 AI 相关性、
来源优先级、发布时间和趋势排名排序，并在队列前段做简单主体轮转。轮转只调整处理顺序，不禁止
同一主体的多个独立事件。每日最多执行 30 次 Tavily 请求；超出请求队列的直接 Story 仍保留原始
来源证据并可进入选题，只有未补证的 Lead 继续留在私有诊断。Tavily 不得从来源队列外引入选题。

enrichment 的失败语义是 fail-open：请求失败时保留已抓取的直接 Story，并记录诊断；Lead 补证失败
只保留为私有 observation signal。HTTP 432/433 统一归类为 `usage_limit_exceeded` 并立即停止后续
无效请求。生产路径不会为达到目标条数搜索来源队列外新闻。当前开关、参数和灰度边界见
[Tavily 运行手册](../operations/tavily.md)。

### 5. 摘要边界

`summarizer.py` 负责 prompt、provider fallback、在线响应解析和离线结果生成；`utils/summary_contracts.py` 负责稳定数据模型与本地 renderer。

摘要前先由 `utils/summary_selection.py` 执行确定性的 `source_balanced_v2` 策略。
`editorial_catalog.yaml` 集中维护双语 AI 术语、相邻领域词、事件动作、对象、公司别名和稳定模型家族；
未知数字版本可由家族前缀识别，不必每天硬编码。候选按 0–3 级相关性判断：直接模型/前沿 AI 为
3，明确 AI 上下文或机器人、自动驾驶、芯片、算力为 2，只有泛科技公司名为 1。Apple、Microsoft
等宽泛科技主体必须同时出现 AI、模型、芯片、算力、机器人或自动驾驶上下文，不能靠公司名入选。

选择层先用“共享两个主体与动作”或“共享主体、动作及对象/模型/数字”保守聚合同一事件，再为来源
预留席位，并依次约束单一来源 60%、主要主体最多 2 条、被提及主体最多 3 条、同一模型家族最多
1 条；候选不足时按模型家族、被提及主体、主要主体、来源上限的固定顺序放宽并写入诊断。话题计数
只做软排序，相关性和新闻优先级仍更强。`source_balanced_v1` 仅保留用于历史产物重放。

短名单保留原快照中稳定的 `a1`、`a2`… `article_id`，模型只逐条改写，不再选题。发布时本地
renderer 会隐藏 ID 和来源 URL；发布前仍必须满足：

- 输出 ID 与本地短名单逐项一致，不得遗漏、重复、替换或改序
- 每个 ID 来自输入，每日目标与上限均为 `max_summary_items=10`；证据不足时允许更少
- 模型只生成 summary；title 和 URL 均从本地候选绑定
- 条目的 URL 与其来源候选 URL 一致
- 多来源合格候选存在时，最终结果不得退化为单一来源
- `selection_diagnostics` 必须能由完整候选快照重算并逐字段一致
- rank、heat、state、delta 不得进入读者正文
- Markdown 只由通过 `SummaryResult` 校验的结果渲染

`dedupe()` 先阻止明显重复输入，v2 story cluster 再合并跨来源、跨语言的同一事件，selection 最后决定报道集合。一个候选固定对应一条摘要，避免弱模型靠重复引用同一 ID 扩写新闻。模型不能新增来源、URL 或事实；它只能重新组织对应候选中可支持的内容。

在线模型失败或质量校验失败时，生产路径拒绝用未经质量保证的离线文本替代；明确的 `--offline` 才使用确定性离线结果。
完整 JSON 若只违反句式或证据约束，最多执行两次聚焦修复；第二次覆盖第一次修好句式后仍引入
无证据数字或高风险措辞的情况。每次修复仍重新执行相同的中文、长度、顺序、数字和高风险事实
校验，重试不能替代证据门槛。

0 条合格 Story 是正常、可发布的空日报，不是运行失败。系统会生成当天 edition，并明确显示
“今日没有达到证据门槛的主新闻”；只有抓取、Tavily 编排、摘要契约、构建或发布阶段真正失败时，
才保留上一份 edition。

### 6. 文件和构建边界

`utils/storage.py` 以日期写入 JSON 和 Markdown，并使用原子单文件写入。`build.py` 只消费 staged `content/`，把结果写入 staged site 目录；它不应该直接改变当前公开目录。

单次完整发布由 `stage_and_publish_run()` 完成：

1. 把上一版 `data/content` 完整复制到 run workspace，再写入当天文件，准备完整
   `data/content/site` edition。
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
