# 每日新闻任务稳定性与架构改进分析

## 1. 结论摘要

当前项目已经具备一条完整、可拆分重跑的批处理链路：抓取、去重、可选 Tavily 增强、JSON 落盘、LLM 摘要、Markdown 落盘和静态站点构建。尤其是 Tavily 模块已经实现调用预算、分阶段验证/补充、失败回退和详细诊断，不需要推倒重来。

改进空间最大的地方，是把增强模块已有的“阶段结果和失败语义”扩展到整个每日任务。目前主流程仍以 `list`、普通 `dict`、直接文件覆盖和控制台输出串联各阶段，无法可靠区分“当天新闻确实很少”和“上游全部异常”，也无法保证一次失败运行不会破坏当天或上一版可发布产物。

建议按以下优先级推进：

| 优先级 | 改进方向 | 解决的核心问题 |
| --- | --- | --- |
| P0 | 事务式运行与发布门禁 | 防止失败或降级运行覆盖已发布的好版本 |
| P0 | 来源执行契约与统一时钟 | 区分空结果和故障，统一“每日/最近”的时间语义 |
| P0 | 摘要 `article_id` 契约与输入去重 | 阻止一篇输入被拆成多条、URL/明显故事重复和无依据扩展 |
| P1 | 统一文章模型与质量管线 | 消除宽松字典、重复归一化和隐式过滤 |
| P1 | 完整结构化、可重放的摘要阶段 | 在已落地最小契约上继续统一 provider 输出、策略和重放 |
| P1 | 全链路可观测性与模块拆分 | 让运维判断和代码演进建立在同一套运行事实之上 |

不建议现阶段引入数据库、消息队列或微服务。这个项目是每天一次、数据量很小的文件型批任务，使用“类型化阶段结果 + 原子文件发布 + 运行清单”就能获得大部分稳定性收益，同时保持架构轻量。

## 状态修订（2026-07-13）

本文是稳定性基线分析，不再把以下两项视为待实现建议：

- `summarizer.py` 已为候选注入短 `article_id`，`SummaryResult` 和本地 renderer 负责摘要来源、数量、唯一性与源 URL 校验。
- `utils/dedupe.py` 已做 canonical URL、跟踪参数/片段清理和明显跨来源故事去重，并按优先级保留候选。

提交 `adc9bf0` 的本地回归为 `85 passed`，2026-07-13 的 [Actions preview run 29238871654](https://github.com/Carl-312/daily-report-site/actions/runs/29238871654) 验证了 2 条输入只生成 2 条摘要。尚未解决的质量问题是不同输入之间的深层语义重复、主体/主题配额、AI 相关性门禁和更完整的来源可观测性；后续建议仍以本文的 P1 设计为准。

## 2. 分析范围

本文初版按本次要求，只查看了 `README.md` 和每日任务直接相关的核心功能代码；当时没有查看测试、工作流、历史数据、benchmark、handbook、prompt 内容或外围脚本。因此，下面的初始分析不应替代当前验收证据；最新实现和运行结果以本节状态修订及 `docs/daily-news-reliability-acceptance.md` 为准。

初版分析范围包括：

- `main.py`
- `config.py`
- `summarizer.py`
- `build.py`
- `sources/__init__.py`
- `sources/base.py`
- `sources/aibase.py`
- `sources/techcrunch.py`
- `sources/theverge.py`
- `sources/syft.py`
- `utils/dedupe.py`
- `utils/news_enrichment.py`
- `utils/storage.py`

没有查看测试文件、工作流文件、历史数据、benchmark、handbook、prompt 内容或外围脚本，也没有使用外部文档。因此，本文对测试覆盖和 CI 行为不作现状判断，只提出核心代码可见的风险与建议。

## 3. 当前主链路与已有优势

主入口 `cmd_run()` 串行执行以下步骤（`main.py:89-150`）：

```text
fetch_all
  -> dedupe
  -> enrich_articles_with_tavily
  -> save_json
  -> summarize_or_offline
  -> save_markdown
  -> build_site
```

值得保留的设计包括：

1. 来源通过 registry 和 `BaseSource` 扩展，边界清晰（`sources/base.py:37-67`、`sources/__init__.py:15-29`）。
2. JSON 在摘要前保存，摘要失败后可以用 `summarize` 子命令从数据检查点继续（`main.py:115-129`、`main.py:184-203`）。
3. LLM 有按模型/供应商顺序的回退，并对每次候选输出执行本地质量校验（`summarizer.py:97-140`、`summarizer.py:168-201`）。
4. Tavily 增强有总调用预算、验证预算、分阶段 refill、请求结果分类和完整报告（`utils/news_enrichment.py:658-762`、`utils/news_enrichment.py:940-1119`、`utils/news_enrichment.py:1349-1667`）。
5. 增强关闭、缺少 key 或顶层异常时会回退到去重后的原始文章（`utils/news_enrichment.py:1368-1392`、`utils/news_enrichment.py:1653-1667`）。

这些能力说明项目不缺“功能”，缺的是一个统一、明确、可恢复的任务执行协议。

## 4. P0：事务式运行与发布门禁

### 4.1 当前风险

目前日期文件既是中间检查点，也是最终产物：

- JSON 和 Markdown 都直接打开最终路径写入，不是临时文件完成后再原子替换（`utils/storage.py:34-40`、`utils/storage.py:52-65`）。进程中断可能留下截断文件。
- 同一天重跑会直接覆盖原文件，没有输入指纹、运行 ID、版本状态或 last-known-good 保护。
- JSON 在摘要前覆盖（`main.py:115-129`）。如果一次重跑抓取质量很差，新的差数据会先替换旧的好数据，随后摘要可能失败。
- 构建开始时会先递归删除整个输出目录（`build.py:234-253`）。任意一篇 Markdown 转换失败，都可能留下空或不完整的 `dist/`。
- `cmd_fetch()` 即使得到零篇文章也会写文件并正常结束（`main.py:153-181`）。`cmd_summarize()` 找不到数据时只打印并 `return`，CLI 仍可能以成功退出码结束（`main.py:184-192`、`main.py:267-273`）。

这使“程序执行完成”和“产生了可发布日报”成为两件不同的事，但代码没有表达这个差异。

### 4.2 建议设计

引入轻量的 `DailyRun` 状态机，不需要数据库：

```text
CREATED -> COLLECTED -> CURATED -> SUMMARIZED -> RENDERED -> PUBLISHED
               \           \             \          \
                FAILED      DEGRADED       FAILED     FAILED
```

每次运行创建：

```text
.runs/<report-date>/<run-id>/
  manifest.json
  articles.json
  summary.md
  site/
```

阶段产物先写到该 staging 目录。只有所有发布门禁通过，才把包含 `data/`、`content/` 和 `site/` 的完整 edition 放入版本目录，并原子替换唯一的 `public-version.json` 指针。读者先读取一次指针，再相对该 edition 解析三类产物；失败时保留正式版本和失败运行清单，便于复盘或从某阶段重跑。根目录下的旧 `data/`、`content/`、`dist/` 仅作为兼容镜像，不是跨路径一致性的读取边界。

统一发布政策建议如下：

| 场景 | 运行状态 | 是否替换正式版本 |
| --- | --- | --- |
| 全部启用来源失败 | failed | 否 |
| 部分来源失败，但数量、时效、来源多样性达标 | degraded | 可以，由策略明确决定 |
| Tavily 异常，但原始文章质量门禁达标 | degraded | 可以 |
| 文章数或时效门禁不达标 | failed/degraded | 默认否 |
| LLM 输出质量失败 | failed | 否 |
| 静态站点构建失败 | failed | 否 |
| 同日期、同输入指纹已成功发布 | no-op | 否 |

`manifest.json` 至少记录 `run_id`、`report_date`、`started_at`、阶段状态、输入指纹、配置摘要、产物哈希、错误类别和正式发布版本。这样 `fetch`、`summarize`、`build` 子命令可以变成对同一个 run 的恢复操作，而不是各自推断“今天”的隐式操作。

### 4.3 验收标准

- 任意存储或构建阶段被强制中断，正式 JSON、Markdown、`dist/` 均保持上一版完整状态。
- 同一输入和配置重跑是 no-op，或者生成内容相同且只更新运行元数据。
- 全源故障不会生成或覆盖当天日报，并以非零退出码结束。
- `fetch` 成功但 `summarize` 失败后，可以指定 `run_id` 继续，不需要重新抓取。

## 5. P0：来源执行契约与统一时钟

### 5.1 当前风险

`fetch_all()` 只返回合并后的文章列表。来源异常只打印一行并继续（`sources/__init__.py:52-70`），因此下游不知道哪些来源执行过、哪些失败、哪些确实返回零条。

部分适配器进一步吞掉了失败信息：

- AIBase 详情抓取和解析捕获所有异常并返回 `None`（`sources/aibase.py:91-125`）。
- Syft 将缺少配置、远端 `success=false`、解析失败和网络失败都表现为空列表（`sources/syft.py:25-64`）。
- 公共 GET 有超时但没有按错误类型控制的重试、退避或单来源总预算（`sources/base.py:59-61`）。
- 所有来源串行执行，一个来源慢或超时会累加到每日任务总耗时（`sources/__init__.py:52-69`）。

时间语义也不一致：

- 保存日期固定使用 UTC+8，而 `Settings.timezone` 没有被日期 helper 使用（`config.py:50-51`、`utils/storage.py:12-24`）。
- AIBase 要求“北京时间今天”，TechCrunch/The Verge 使用按日期差计算的“最近 48 小时”，Tavily 使用严格滚动小时窗口（`sources/aibase.py:214-236`、`sources/techcrunch.py:113-124`、`sources/theverge.py:101-110`、`utils/news_enrichment.py:169-179`）。
- TechCrunch/The Verge 的判断仅检查 `diff.days <= 1`，未来日期也会被接受。
- TechCrunch 选择器把 URL 年份写死为 2024/2025/2026（`sources/techcrunch.py:38-48`、`sources/techcrunch.py:77-84`），后续年份会自然失效。
- TechCrunch/The Verge 依赖 URL 提取发布日期，而不是优先读取页面结构化时间（`sources/techcrunch.py:89-122`、`sources/theverge.py:78-108`）。站点 URL 规则变化会表现为“没有近期新闻”，而不是解析器故障。

### 5.2 建议设计

把来源契约从 `list[Article]` 改为类型化结果：

```python
SourceRunResult(
    source: str,
    status: Literal["ok", "empty", "degraded", "failed"],
    fetched_count: int,
    accepted_count: int,
    attempts: int,
    duration_ms: int,
    articles: list[Article],
    error_kind: str | None,
    error_message: str | None,
)
```

其中 `empty` 只能表示请求和解析均成功但确实无合格内容；HTTP 200 但选择器未命中、历史上通常有数据却突然为零，应标为 `degraded` 或 `parser_drift`，不能等同于正常空结果。

网络策略应集中在 `BaseSource` 或单独的 transport：

- 只对连接错误、超时、429 和部分 5xx 做有限重试。
- 使用指数退避加 jitter，并设置“单次超时”和“单来源总时间预算”。
- 适配器仍可并发，但使用小型有界线程池；结果排序保持由配置或 source priority 决定，不依赖完成顺序。
- 不在适配器内部吞异常；适配器抛出分类异常，由来源执行器统一转成 `SourceRunResult`。

同时引入一个由入口创建并向下传递的 `RunClock`：

```python
RunClock(report_date, timezone, cutoff_at, recency_window, deadline_at)
```

所有来源、Tavily、LLM、文件命名和标题都使用同一个 cutoff 和运行级 deadline。发布日期解析顺序应为页面/响应结构化字段、标准 meta/time、RFC/ISO 文本、URL 日期兜底。统一拒绝超过 cutoff 的未来内容，并将未知时间保留为显式质量状态，而不是在不同来源中以不同方式静默删除。各阶段根据剩余时间设置请求超时；接近 deadline 时停止可选验证/refill，为摘要、构建和原子发布保留固定时间。

### 5.3 验收标准

- 日报运行清单能回答每个来源“是否执行、耗时、重试次数、原始数、入选数、失败类别”。
- 429/超时可重试，4xx 配置错误不盲目重试，总耗时受上限约束。
- 最慢外部依赖无法突破运行级 deadline，可选增强不会挤占发布保留时间。
- HTTP 200 但解析为零可以与“当天确实零条”区分并触发告警。
- 午夜边界、未来时间、无时区时间、ISO/RFC 时间在所有来源中得到一致结果。
- 进入新年份不需要修改选择器中的年份常量。

## 6. P1：统一文章模型与显式质量管线

### 6.1 当前风险

`Article` 在抓取阶段是 dataclass，进入主流程后转成无约束 `dict`（`sources/base.py:13-34`、`main.py:111-123`）。增强模块继续大量接收 `Any` 和字符串 key，报告本身也是一个大型字典（`utils/news_enrichment.py:658-762`、`utils/news_enrichment.py:1349-1357`）。字段缺失、状态含义和阶段修改无法由类型系统或配置校验提前发现。

去重语义仍有边界，但最小输入护栏已经落地：

- 初始 `dedupe()` 现在先规范化 URL、移除跟踪参数和片段，再拦截明显的跨来源标题改写（`utils/dedupe.py`），同一 URL 的常见变体不会产生第二候选。
- Tavily 模块又实现了更完整的标题归一化、canonical URL、近重复和故事聚类（`utils/news_enrichment.py:123-149`、`utils/news_enrichment.py:270-456`）。
- 同名的 `normalize_title()` 有两套实现，长期容易产生阶段间行为差异。
- 增强启用时，验证只处理预算内候选（`utils/news_enrichment.py:984-1119`）；预算外候选记录为 `verify_skipped_due_budget`，但不会自然进入 `verified_output_articles`（`utils/news_enrichment.py:1473-1478`）。这是可以接受的严格策略，但主流程没有把这种大量过滤纳入发布决策。

### 6.2 建议设计

建立一个贯穿管线的不可变或受控变更模型：

```text
Article
  identity: canonical_url, normalized_title, story_id
  content: title, description, body
  provenance: source, fetched_at, original_url
  time: published_at, time_confidence
  quality: relevance, verification, rejection_reasons
```

将处理顺序固定为：

```text
schema validation
  -> URL canonicalization
  -> exact duplicate collapse
  -> story clustering
  -> recency/relevance checks
  -> optional external verification/refill
  -> deterministic ranking
  -> publication quality gate
```

去重与故事聚类应成为共享模块，抓取和 Tavily 共同使用。每次过滤都返回 `accepted` 和带 reason code 的 `rejected`，不直接丢弃。`QualityReport` 统计输入、各理由淘汰数、最终数量、来源多样性、时间置信度和验证覆盖率，并由发布策略判断是否达标。

配置模型应补充约束：数量/小时/调用预算必须非负；`max_verify_calls <= max_total_calls` 等跨字段不变量要显式校验；输出目录必须互不覆盖，并禁止将项目根目录或内容目录作为可递归删除的站点目录（`config.py:48-79`、`config.py:108-133`、`build.py:234-238`）。

### 6.3 验收标准

- 从抓取到发布不再在 dataclass 和任意字典之间反复转换。
- 任意未入选文章都能追溯到明确 reason code。
- 去重、聚类、排序在 Tavily 开关前后使用同一套规则。
- 发布门禁至少包含文章数、来源多样性、近期文章比例和关键阶段降级状态。
- 危险或冲突的输出目录在启动时失败，而不是执行 `rmtree()` 后才暴露。

## 7. P1：摘要阶段的进一步结构化与可重放

### 7.1 当前风险

当前摘要已经有 `SummaryResult`、`article_id` 和确定性 Markdown renderer；仍需继续收紧 provider 输出和策略边界：

- 在线模型当前仍以 Markdown-ish 文本返回，再由正则提取编号条目并要求“互动话题”和中文比例（`summarizer.py:55-95`）。模型只要改变换行或列表样式，就可能被判失败；本地 `article_id` 校验只能保证来源和边界，不能替代 JSON schema。
- `summarize()` 已经校验一次，`summarize_or_offline()` 又校验一次（`summarizer.py:192-196`、`main.py:76-79`），职责重复。
- 没有文章时 `summarize()` 返回“暂无新闻”（`summarizer.py:154-155`），随后主流程仍要求至少一个编号条目，因此在线路径会失败；离线路径则可能生成只有互动话题的日报。零文章政策前后不一致。
- helper 名为 `summarize_or_offline`，docstring 声称失败时回退，但配置了 API key 后的任何在线失败都会拒绝 offline 并抛错（`main.py:67-86`）。这个 fail-closed 选择本身可以合理，但应成为显式策略而不是隐藏分支。
- 供应商请求未在本地代码中设置明确的任务级超时、重试预算和尝试记录（`summarizer.py:168-224`）。
- 旧实现的最终 JSON 只保存文章和 enrichment 报告；当前主流程已将 `SummaryResult` 一并写入 staged JSON，并在 run workspace 保存 `summary.json`，可精确重放或解释同一天两次摘要为何不同。

### 7.2 建议设计

保留现有“模型生成”和“Markdown 渲染”分离的边界。下一步将 provider 输出直接收敛到受约束的 JSON `SummaryResult`，并继续记录条目数组、互动话题、供应商、模型、尝试次数、输入哈希、prompt 哈希和验证结果；`article_id` 与本地确定性 renderer 已完成，不应再交给提示词单独保证。

如果所选供应商不能可靠提供结构化输出，也可以要求 JSON 文本并做严格 schema 校验；失败时进入下一个模型。关键是不要让 Markdown 排版本身承担业务协议。

摘要模式建议配置为显式枚举：

- `required_ai`：AI 摘要失败则整次运行失败，不替换正式版本。
- `allow_offline`：所有模型失败后生成确定性离线摘要，运行标为 degraded。
- `offline`：不调用模型，适合本地或应急运行。

任务级策略控制每个 provider 的超时、最大尝试次数和总摘要预算。每次尝试只记录脱敏后的错误分类，不把所有异常文本拼成唯一运行语义。

### 7.3 验收标准

- 模型更换列表符号、换行或 Markdown 风格不会导致业务字段丢失。
- 每条摘要都可追溯到输入文章，最终 Markdown 渲染可重复。
- 零文章在摘要前由发布门禁处理，线上和离线没有相互矛盾的结果。
- 同一 `articles + prompt + model parameters` 具有可比对的输入指纹和完整尝试记录。
- `required_ai`、`allow_offline`、`offline` 三种失败行为在 CLI 退出码和 manifest 中明确可见。

## 8. P1：全链路可观测性与增强模块拆分

### 8.1 当前风险

Tavily 报告已经记录调用数、延迟、验证结果、拒绝原因、停止原因和候选预览（`utils/news_enrichment.py:658-762`、`utils/news_enrichment.py:1051-1089`），但其他阶段主要依赖 `print`。因此最复杂的可选阶段可诊断，最关键的抓取、摘要、存储和发布阶段反而缺少统一事实模型。

`utils/news_enrichment.py` 同时包含：

- 领域常量与正则策略
- URL/标题/时间归一化
- 故事聚类
- Tavily HTTP transport
- verify/refill 执行
- 运行预算
- 1600 行级别的大型 orchestration 和 report schema

这使修改一个策略时需要理解大量无关状态，也增加报告 key 拼写或计数不一致的风险。主流程还在 `cmd_run()` 与 `cmd_fetch()` 中重复抓取、去重、增强和保存逻辑（`main.py:97-125`、`main.py:158-179`）。

### 8.2 建议设计

让所有阶段统一返回：

```python
StageResult[T](
    status: Literal["ok", "degraded", "failed", "skipped"],
    value: T | None,
    metrics: dict[str, int | float | str],
    diagnostics: list[Diagnostic],
)
```

`DailyRunManifest` 聚合这些结果并输出 JSON。控制台只负责渲染人类可读摘要，退出码和发布决策来自状态对象，不来自是否打印了错误。

增强模块可在不改变策略的前提下拆为：

```text
enrichment/
  models.py       # typed report/result/candidate
  normalize.py    # URL/title/time and story identity
  policy.py       # budgets, gates, trusted-domain policy
  transport.py    # Tavily request, timeout, retry, error mapping
  verify.py
  refill.py
  service.py      # thin orchestration
```

主流程则提取单一 `collect_and_curate(run_context)`，供 `run` 和 `fetch` 复用。依赖通过参数注入：`Settings`、clock、source runner、summarizer、storage 和 builder。`get_config()` 可以保留在 CLI composition root，但不再由每个核心模块自行读取（目前见 `summarizer.py:24-35`、`build.py:141-152`）。

建议先建立统一 result/manifest，再拆文件。仅按文件大小拆分而不先固定输入输出契约，会把一个大状态机变成多个相互传递松散字典的模块，优雅度不会真正提高。

### 8.3 最小可观测字段

每次运行至少记录：

- `run_id`、`report_date`、cutoff、配置和代码版本标识
- 每阶段状态、开始/结束时间、耗时、输入/输出数量
- 每来源状态、重试次数、失败类别、选择器/响应异常
- 去重、时效、相关性、验证各理由的淘汰数量
- LLM provider/model/attempt、质量验证结果、输入/prompt 哈希
- 产物路径、哈希、是否发布、未发布原因、上一正式版本

告警只围绕可行动事件：全源失败、来源连续 parser drift、质量门禁失败、摘要耗尽、构建/发布失败。单一可选来源短暂失败但整体质量达标，应记录 degraded 而不是制造无效告警。

## 9. 推荐实施顺序

### 第 1 阶段：先保护正式产物

1. 为 JSON、Markdown 增加临时文件加原子替换。
2. 让站点在 staging 目录完整构建后再整体切换。
3. 增加 `RunContext`、`DailyRunManifest`、明确退出码和发布门禁。
4. 补上输出目录安全校验。

这是最高收益阶段，因为它在不改变抓取/摘要算法的情况下，先消除“坏运行破坏好版本”的风险。

### 第 2 阶段：修正来源与时间语义

1. 引入 `SourceRunResult`，移除适配器内部宽泛异常吞噬。
2. 统一 clock、cutoff、时间解析和 recency policy。
3. 增加有限重试、总时间预算和有界并发。
4. 为 parser drift 和异常空结果提供状态与告警。

### 第 3 阶段：统一质量与摘要契约

1. 固定 Article/QualityReport/StageResult 类型。
2. 合并重复的标题、URL、故事归一化逻辑。
3. 在已落地的 `article_id` 契约和本地 renderer 之上，让 provider 返回严格结构化摘要，并统一重放入口。
4. 记录输入、prompt、模型和产物指纹，支持 run 级重放。

### 第 4 阶段：在契约稳定后拆分增强模块

1. 先用现有行为建立 characterize tests 和 report invariants。
2. 按 models/normalize/policy/transport/verify/refill/service 分解。
3. 让主流程使用同一套 report/diagnostic 约定。当前正式路径已将 transport、policy、verification、refill 置于独立模块边界，`news_enrichment.py` 保留归一化、聚类和总编排。

## 10. 最终目标形态

```text
CLI / Scheduler
    |
    v
DailyRunService(RunContext)
    |
    +--> SourceRunner[] --------> SourceRunResult[]
    |
    +--> CurationPipeline ------> ArticleSet + QualityReport
    |       \--> optional EnrichmentService
    |
    +--> SummaryService --------> SummaryResult
    |
    +--> SiteRenderer ----------> staged site
    |
    +--> PublishPolicy ---------> atomic promote or keep last-known-good
    |
    +--> DailyRunManifest
```

这个形态仍然是轻量的单进程 Python 批任务，但它具备稳定每日任务应有的关键性质：失败可分类、运行可恢复、重跑可判定、产物不可半发布、质量策略可解释、每条结论可追溯。它比继续在 `cmd_run()` 中增加 `try/except` 更稳定，也比直接引入重型基础设施更符合当前规模。
