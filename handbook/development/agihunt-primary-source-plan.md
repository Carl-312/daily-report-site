# AGIHunt 作为每日 AI 新闻主来源的接入规划

- 状态：Phase 1 关闭态实现已完成本地验证；Phase 0 真实样本为 1/2 天，Phase 2
  GitHub shadow 为 1/7 天且健康；实现以 `sources.agihunt: false` 的关闭态合入，后续
  样本仍是生产启用的前置条件。
- 创建日期：2026-07-13
- 范围：设计与验证计划；本文件不授权、不写入密钥，也不改变生产抓取行为。

## 结论

AGIHunt 应接入为 `sources/` 中的**主候选来源**，而不是 Tavily 的替代品或网页爬虫。它提供面向 agent 的官方 API：每日结构化日报用于跨频道选题与覆盖校验，频道条目用于生成可追溯的候选新闻。现有 AIBase、TechCrunch、The Verge、Syft 先保留为次级来源；Tavily 仍位于去重后的可选验证/补量层。

不能只把 AGIHunt 日报 Markdown 作为唯一 `Article` 输入：当前摘要契约允许一个聚合来源派生多条事实，但每条发布链接必须等于该候选的 `link`。若所有条目都回链到同一个日报页面，读者无法追溯到原始信号。因此，默认方案优先使用频道接口返回的原帖 `url`；日报接口只有在授权样本证明 Markdown 中可稳定、安全地提取逐条原始链接后，才可参与候选构建。

```text
AGIHunt Agent API（日报 / 频道条目）
                │
                ▼
  串行客户端：鉴权、10 分钟缓存、限流/错误映射
                │
                ▼
       AgihuntSource：解析、时效过滤、频道内选题
                │
                ▼
  现有 fetch_batch → dedupe → 可选 Tavily → summary → staged publish
```

## 已核实的现状

当前日报是单进程、文件型批处理：`main.py` 调用 `fetch_batch()`，对所有候选执行 `dedupe()`，再进入默认关闭的 Tavily enrichment、摘要和原子 staged publication。`sources/__init__.py` 串行调用已启用的 source，并将每个结果记录为 `SourceRunResult`。

现有 source 的共同输出是 `Article(title, link, description, publish_time, content, priority, source)`。AIBase 实际返回一篇当日聚合日报；TechCrunch 与 The Verge 从页面和 URL 日期提取候选；Syft 是带密钥的 JSON 接口。全局 `limits.max_articles` 仍为每个非 AGIHunt source 的 14 条上限；AGIHunt 单独使用 `agihunt.max_articles=20`。全局去重会优先保留较高 `priority` 的候选；摘要最多发布 10 条，且每一条的 URL 必须来自输入候选。

这意味着接入点清晰，但 AGIHunt 的 top-100 频道数据不能原样送入摘要：适配器必须在返回 `Article` 前完成有界、可解释的“重要性”选择。当前全量回归基线为 `124 passed`（2026-07-14；另有一条既有 Pydantic 弃用警告）。

## AGIHunt API 约束与设计边界

依据 [AGIHunt Agent skill v1.2.2](https://agihunt.info/agent/v1/skill.md)：

- API 基址为 `https://agihunt.info/agent/v1`，使用 `Authorization: Bearer <key>`、`X-AgiHunt-Skill-Version: 1.2.2` 和版本化 User-Agent。
- `GET /report?day=YYYY-MM-DD` 返回 `{day, markdown, generated_at, html_url}`；北京时间每天 06:00 后生成，覆盖此前约 24 小时。
- `GET /channel/{slug}/items?day=...&sort=hot` 返回最多 100 个频道条目，包含 `title`、`text`、`url`、`author`、`hot`、`published_at` 等字段；`hot` 只可用于**同频道内排序**，没有跨频道绝对含义。
- 数据只保留近 3 个北京时间自然日。频道 slug 应在接入验证时从 `/channels` 核对，不能猜测后长期固化。
- 服务方要求一次任务通常仅 1–5 个请求、禁止并发、相同 URL 十分钟内必须命中本地缓存；不可用高频轮询或批量扫完所有频道。

因此本项目不得抓取 AGIHunt HTML、sitemap 或未公开接口；仅在用户完成授权后调用上述官方 API。每个公开日报和运行诊断都应标注来源为 `AGI HUNT · agihunt.info`，同时保留频道条目的原始链接。

## 推荐的获取策略

### 每日请求预算

初始生产策略的硬上限为 5 个串行请求：

1. 可选的当日 `/report` 请求，用于发现跨频道大主题、检查日报是否就绪，并保存可审计的覆盖信息。
2. 三个核心频道：`models`、`research`、`coding-agents`。
3. 一个由配置明确指定的补充频道；在 shadow 阶段轮换验证 `products`、`companies`、`funding`、`infra`、`hardware`、`policy`、`multimodal` 的收益。

如果日报 Markdown 尚不能稳定地解析为带原帖 URL 的条目，则日报请求只作诊断，频道请求数为 4；不得为了“全面”补扫所有频道。最终的核心/补充频道列表、每频道上限和轮换规则，应基于至少两天已授权样本的覆盖率与人工审阅冻结为 `config.yaml` 中的显式配置。

### 时间语义

`RunClock.report_date_ymd` 是唯一的 `day` 参数来源，并且运行、缓存、筛选和诊断都使用 `Asia/Shanghai` 日期。定时任务当前约在北京时间 08:36 运行，理论上可以读取当天 06:00 后的日报。

- 若 `/report` 返回 `report_not_ready`，将它记录为“日报未就绪”，而不是把旧日报伪装成当天新闻；继续使用频道候选与现有次级来源。
- 若请求日期超出 3 天窗口或格式错误，视为配置/代码错误，不重试。
- `published_at` 必须解析为带时区的时间，并通过与 `RunClock.cutoff_at` 对齐的时效检查；未来时间、无法解析时间和非 HTTP(S) 原帖 URL 都要以 reason code 拒绝。

### 从热门条目到重要候选

`AgihuntSource.fetch(max_articles=20, ...)` 的返回数量不得超过 AGIHunt 专属上限。四个已配置频道各自本地保留前 6 条，先构成 24 条候选缓冲，再在去重后至多保留 20 条；这不增加 API 请求数。其本地、确定性选择顺序为：

1. 校验 API 响应和必要字段，规范化 URL/标题，保留频道、作者、热度、频道内名次、API 日期和 AGIHunt 日报链接等 provenance。
2. 对每个频道只按返回顺序或 `hot` 排名选取有限前缀；绝不把不同频道的裸 `hot` 分数直接比较。
3. 先满足模型、研究、编程 Agent 的基础配额，再用补充频道填充；对同一主题/实体保留可配置的上限，防止一家公司的多条信号占满日报。
4. 用现有 canonical URL/标题去重规则做 source 内预去重，返回至多 `max_articles` 个候选；随后仍必须通过全局 `dedupe()`。
5. 只在候选本身确实支持的范围内填充 `description`/`content`，不得用 AGIHunt 热度推断事实。

初版不让 LLM 决定入选与否。频道配额、关键词/主题规则和拒绝 reason code 必须是配置或纯函数，以便用冻结样本回放、解释和调整。

## 代码与配置改动边界

| 位置 | 计划改动 | 目的 |
| --- | --- | --- |
| `config.py` | 添加 `agihunt_api_key` 与严格的 `AgihuntSettings` | 只从环境读取密钥，校验频道、预算、TTL 与上限。 |
| `config.yaml` | 增加 `sources.agihunt: false` 及 AGIHunt 的非密钥配置 | 先以关闭状态合入，避免未授权时改变生产。 |
| `.env.example` | 增加空的 `AGIHUNT_API_KEY=` | 明确本地配置入口，不提交真实凭据。 |
| `sources/agihunt.py` | 新建 API client、缓存、错误映射、响应验证和 `AgihuntSource` | 只使用官方 Agent API，输出标准 `Article`。 |
| `sources/__init__.py` | 注册 source，并以显式依赖传入 API key/settings | 让 source status、次数和失败语义进入现有 manifest。 |
| `sources/base.py` / `ArticleSnapshot` | 仅在 provenance 无法安全表达时做加性扩展 | 保住频道/排行/来源事实，不把它们塞成不可审计的自由文本。 |
| `tests/test_agihunt_*.py` | client、响应、缓存、筛选、source outcome 和回归测试 | 所有策略先以离线 fixture 覆盖。 |
| `handbook/` 与 Actions | 运行手册、source adapter 文档、CI secret 注入与灰度说明 | 让授权、回滚、归因和部署一致。 |

AGIHunt 适配器不复用 `BaseSource._get()` 的默认“三次重试”语义：服务方要求 429 或网络/5xx 最多受控重试一次，且禁止并发。应实现专用 client，在 `RunClock` 剩余时间允许时才按 `Retry-After` 或最多 30 秒等待一次。

密钥只允许来自运行环境中的 `AGIHUNT_API_KEY`（本地 `.env` 或 GitHub Actions Secret）；不得写进 YAML、缓存、manifest、日志、测试 fixture 或日报产物。设备授权是一次性的人机操作：只有用户明确同意后才发起，定时 runner 只消费已配置的 secret，绝不在 CI 中启动浏览器授权流程。

## 错误、缓存与发布语义

客户端缓存以“规范化完整 URL”的 SHA-256 为键，默认 TTL 为 600 秒，使用原子写入并放在未跟踪的临时目录。缓存命中不得发出网络请求，且请求严格串行。

| 外部结果 | 本地行为 |
| --- | --- |
| `401 missing_api_key` / `invalid_api_key` | 已启用 source 记为 configuration failure；不重试、不泄露 key。 |
| `426 skill_update_required` | 记为兼容性失败并阻止该 source；人工审查最新版 API 文档后再改代码，运行时不自动下载或执行更新。 |
| `429 rate_limited` | 读取 `Retry-After`，在 deadline 内最多等待并重试一次。 |
| `429 daily_quota_exceeded` | 不重试；使用本轮已有缓存/次级来源，明确记录配额耗尽。 |
| `400` 日期错误、`404 channel_not_found` | 配置或实现错误；不重试。 |
| `404 report_not_ready` | 仅日报辅助请求降级；频道 source 继续。 |
| 网络、超时、5xx | 最多一次有界重试；仍失败时返回可诊断的 source failure。 |

启用 AGIHunt 而缺少有效 key 不能伪装成空新闻。若其他 source 仍提供合格候选，现有发布策略可将运行标为 degraded；如果所有启用 source 都失败，必须保留上一版公开日报。AGIHunt 的失败绝不触发 Tavily 去无限补量。

在接入初期，Tavily 保持默认关闭。若后续需要验证 AGIHunt 信号，必须先用冻结样本确认 Tavily 对 X/微信公众号等原帖 URL 的验证不会系统性误拒绝；在此之前不允许它悄然削弱主来源的候选集。

## 分阶段实施与验收

### Phase 0：授权前的契约验证

1. 用户完成 AGIHunt 设备授权后，以 1 个 `/channels`、1 个 `/report`、1 个频道请求取得两天的最小化、去敏样本；不启动批量抓取。
2. 确认实际 JSON 字段、`published_at` 格式、`hot` 排序、重复形态、原帖 URL 类型，以及日报 Markdown 是否具备可安全提取的逐条链接。
3. 决定固定频道组、补充频道轮换、每频道候选上限和 provenance 最小 schema。

**通过条件：** API 响应能够用真实但去敏的 fixture 重放；所有待假设字段都已从样本验证，不以 skill 文档的省略号字段实现解析器。

### Phase 1：关闭状态下的适配器与确定性测试

1. 实现 client、缓存、认证 headers、严格响应解析、单次重试和 error mapping。
2. 实现 `AgihuntSource` 和配置接线，但默认 `sources.agihunt: false`。
3. 实现 source 内的频道配额/重要性选择，并记录候选、淘汰和缓存统计。

**通过条件：** 缺 key、401、426、429、5xx、无效 payload、缓存命中、时区边界、未来时间、频道配额、URL/标题重复均有离线测试；既有全量测试和 Ruff 均通过。

**2026-07-13 实施证据：** 已实现专用串行 client、10 分钟临时缓存、五次物理
请求上限、一次受控重试、严格错误映射、频道配额和 provenance；默认配置仍为
`sources.agihunt: false`，灰度只能用 `--agihunt on`。新增 GitHub shadow health
gate 会验证 manifest、请求预算、原帖 URL、摘要 URL、Markdown 归因和 staged
publication。Phase 0 另有 `scripts/agihunt_live_smoke.py`：用户显式确认后仅调用
`/channels`、日报和一个频道，物理请求硬上限为 3，并只写出去敏的 shape/传输
记录。离线 fixture 回归与全量测试已通过，Ruff lint/format 和
GitHub 的 P0、quality、gray-scenarios、final-regression 均通过。真实 API 字段和
日报链接形态尚未被视为已验证，必须继续完成 Phase 0。

**2026-07-14 Phase 0 第 1 天证据：** 用户已配置本地密钥后，受确认的 smoke
对 `/channels`、当日日报和 `models` 频道完成了 3 次串行物理请求，去敏记录健康。
已确认频道列表含 12 个 slug、频道条目含 `title` / `text` / `url` / `author` /
`hot` / `published_at` 等解析所需字段，`published_at` 为 ISO 8601 UTC 字符串，
`hot` 为数值。日报包含外部原帖链接，但仅凭一天样本不能批准其作为候选输入，故仍
仅作覆盖诊断。受控网络需要 HTTP(S) proxy 时，client 现在显式读取 proxy /
`NO_PROXY` 路由，同时保持 Requests 的环境默认认证关闭；该路由有离线测试。原始
响应缓存和去敏运行记录均保留在忽略目录，未进入仓库。首次 GitHub preview 还验证了
health gate，但发现 Actions 默认不上传隐藏 `.runs/`；已改为将单个去敏 health 记录
写到 artifact 根目录并以回归测试锁定。还需完成第 2 天样本和随后连续 7 天的 GitHub
shadow，才可考虑改变 `main` 的生产配置。

### Phase 2：Shadow 运行与质量比较

1. 在 `publish=false` 或本地 `fetch` 环境中连续运行至少 7 天；每天不超过服务方请求预算。
2. 比较 AGIHunt 候选、现有候选和最终去重集：独立故事数、AI 相关率、频道覆盖、实体集中度、原帖链接可用率、候选时效和人工“重要新闻命中率”。
3. 保存去敏的选择报告与 reason code，不把原始密钥、完整缓存或大量第三方内容提交到仓库。

**通过条件：** 人工审阅确认 AGIHunt 能稳定给出不少于当前主候选的有效重要新闻；没有单一频道/公司异常垄断；请求、缓存、错误和来源归因可从 run artifact 回答。

**2026-07-14 Shadow 第 1 天证据：** [非发布 GitHub 运行](https://github.com/Carl-312/daily-report-site/actions/runs/29301983421)
在 `enable_agihunt=true`、`enable_tavily=false`、`publish=false` 下成功完成。preview
artifact 根目录的去敏 health 记录为 `healthy: true`，AGIHunt source 为 `ok`，接受 13
个候选、使用 5 次物理请求，staged publication 为 `published`；workflow 没有提交内容、
部署 Pages 或运行发布 job。这是连续 7 天观察的第 1 天，不构成生产启用的豁免。该次
摘要 provenance 还表明 ModelScope Kimi 尝试被拒绝，随后回退到
SiliconFlow；[官方模型页](https://www.modelscope.cn/models/moonshotai/Kimi-K2.7-Code/summary)
列出的 `moonshotai/Kimi-K2.7-Code:Moonshot` 也被当前
ModelScope endpoint/token 以“无可用 provider”拒绝。维护者随后把第二候选切换为
`Tencent-Hunyuan/Hy3` 并完成[非发布 GitHub 运行 `29305758611`](https://github.com/Carl-312/daily-report-site/actions/runs/29305758611)：
AGIHunt health gate 通过，但主 ModelScope 与 Hunyuan 尝试均因空摘要触发
`SummaryQualityError`，最终回退到 SiliconFlow。因此 Hunyuan 尚未被账户验证，本次同日
模型试验不增加 7 天 shadow 的通过日。

### Phase 3：主来源启用与安全回滚

1. 在配置中把 `agihunt` 放在已启用来源的首位，保留其他 source 作为次级输入；先执行一次非发布预览。
2. `AGIHUNT_API_KEY` 已配置为 GitHub Actions Secret，且只在生成步骤注入环境变量；生产
   启用前仍须复核该 Secret 与 shadow 记录，绝不写入仓库或产物。
3. 在确认预览内容、manifest 和缓存/限额报告后，允许定时生产运行；持续审计前 7 天日报。

**通过条件：** 正式日报显示 AGI HUNT 来源归因；原帖 URL 与 `article_id` 仅保留在私有溯源记录中、不展示给读者；主来源短暂故障不会覆盖上一版；每日 API 调用数、缓存命中和配额状态均在可观察范围内。

## 最小测试清单

- API client：正确 header、无 key 不发请求、10 分钟缓存、禁止并发、一次受控重试、所有指定 HTTP/error code。
- schema：缺少 `items`、标题/URL/时间错误、未知频道、非 HTTP URL、意外字段和版本不兼容均有明确失败语义。
- selection：频道内 hot 排序、跨频道不直接比较热度、基础/补充配额、实体上限、相同故事、`max_articles` 截断和稳定排序。
- pipeline：启用/关闭 source、部分 source 失败、全 source 失败、Tavily off/on 下的候选不变量、摘要 URL 仍等于原帖 URL、staged publication 回滚。
- live smoke：经用户授权后仅做 1–3 个串行 API 请求，并人工检查结果；不可把 live 调用作为单元测试或 CI 的常规测试。

## 未决问题（实施前必须回答）

1. 日报 Markdown 中是否包含稳定、逐条的原始 URL；若没有，日报只保留为覆盖诊断而不直接生成多条新闻。
2. `published_at` 的真实格式与时区、频道数据的日期边界，以及当日 06:00–08:36 的补齐语义。
3. 哪些频道在 7 天 shadow 里能提升“重要性”而非增加重复；固定频道和轮换频道需要由数据决定。
4. AGIHunt 条目与直连媒体报道属于同一故事时，最终应保留哪个原帖 URL，以及如何同时保留 AGIHunt 的发现 provenance。
5. Tavily 对社交/公众号链接的验证误拒绝率是否可接受；没有回放证据前不调整其默认策略。
6. 2026-07-14 的 ModelScope endpoint/token 尚未启用 Kimi K2.7 Code provider；该路由已于
   2026-07-15 恢复并通过 buffered stream 完整日报验证，但目前只达到显式 shadow 准入，不改变
   默认 fallback。第二候选 `Tencent-Hunyuan/Hy3` 仍在真实 GitHub 灰度中返回空摘要并触发
   `SummaryQualityError`。AGIHunt 接入继续不与模型切换绑定成同一次发布。

## 相关资料

- [AGIHunt Agent API skill](https://agihunt.info/agent/v1/skill.md)
- [当前系统架构](../architecture/system.md)
- [现有 source 扩展约定](source-adapters.md)
- [Tavily 运行与灰度边界](../operations/tavily.md)
- [日报质量审计](../quality/daily-product-quality-audit.md)
