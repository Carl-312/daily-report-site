# 每日新闻可靠性验收记录

**生产分支：** `main`
**当前灰度分支：** `agent/gray-schedule-1405`
**PR：** [#15](https://github.com/Carl-312/daily-report-site/pull/15) 为当前 Draft
**状态：** 2026-07-23 多来源、历史去重、摘要修复和独立 Pages 正式灰度已通过；生产保持不变，待维护者决定是否合并

## 已验证能力

- 运行时钟、严格 manifest、来源状态与脱敏配置指纹。
- JSON/Markdown 原子单文件替换，run-scoped staging、journal、备份与中断恢复。
- staged 站点目录切换；摘要/建站失败和零文章门禁不会覆盖正式产物。
- 完整 `data/content/site` edition 与原子 `public-version.json` 指针；兼容路径只在指针成功后刷新，失败时不影响 pointer 选中的权威版本。
- AI provider 与离线摘要均生成 `SummaryResult`，记录 provider/model、attempt、输入与 prompt 指纹并可 replay。
- enrichment 的 transport、policy、verification、refill 已分别落在独立模块，主编排仍通过稳定边界调用。
- 部分来源降级、全源失败、重复等价输入 no-op、来源有限重试。
- 离线结构化摘要与 replay 元数据。
- 摘要来源契约：代码先以 `source_balanced_v2` 生成短名单；模型逐项覆盖且不得重复 `article_id`；源 URL、标题、摘要、来源分布与内部趋势信号均在发布前复核。
- 结构化选题目录：双语 AI 术语、中美公司、稳定模型家族、动作/对象和宽泛科技主体的上下文要求由同一目录驱动；未知数字版本可按家族识别。
- 深层去重与集中度：跨来源/跨语言同事件在摘要前聚类；来源、主要/被提及主体、模型家族、话题和地区分布写入可重放诊断，配额放宽必须可见。
- 输入 URL/故事去重：移除跟踪参数和片段，拦截明显跨来源标题改写，不依赖 LLM 扩展候选。
- 静态站点列表渲染：紧凑有序列表和无链接摘要均保留，不会因 HTML 转换正则过窄而生成空正文。

## 已通过的 GitHub Actions 检查点

以下为历史 CI 检查点；最新代码的本地回归和 preview 证据见下节。

- `p0-contract`
- `gray-scenarios`
- `final-regression`
- `quality`

这些检查只证明当前测试矩阵通过，不是 merge 授权。

## 最新验证证据（2026-07-23）

- 验证提交为 `b4ed875edeb2471836fd66341186bd0572f40f2c`；本地门禁为 `230 passed`，
  `ruff check .`、`ruff format --check .`、`git diff --check` 和 `compileall` 全绿，
  仅有已知 Pydantic V2 弃用 warning。
- [push CI `29996595082`](https://github.com/Carl-312/daily-report-site/actions/runs/29996595082)
  与 [PR CI `29996597916`](https://github.com/Carl-312/daily-report-site/actions/runs/29996597916)
  的 `p0-contract`、`quality`、`gray-scenarios`、`final-regression` 全部通过。
- [正式灰度源运行 `29996599026`](https://github.com/Carl-312/daily-report-site/actions/runs/29996599026)
  以 Tavily on、Trending on、`publish=false` 生成并通过完整灰度门禁。Tavily 首次请求返回
  `usage_limit_exceeded` 后立即停止；24 条直接 Story 继续进入选题，最终
  `source_balanced_v2` 发布 10 条，TechCrunch 6 条、The Verge 4 条。
- staged edition 同时保留 `data/2026-07-22.json` 与 `data/2026-07-23.json`；
  `recent_dedupe.checked_days` 包含 `2026-07-22`，移除 4 条昨日 URL，最终摘要与昨日 URL
  零重合。`formal-gray-health.json` 为 `healthy=true`，摘要、来源分布、历史数据和
  publication status 全部通过。
- [灰度 Pages 运行 `29997299864`](https://github.com/Carl-312/daily-report-site-gray/actions/runs/29997299864)
  发布到
  [2026-07-23 灰度页](https://carl-312.github.io/daily-report-site-gray/2026-07-23.html)。
  页面有 10 个编号段落、1 个互动区块和 1 个“入选来源”区块；线上 HTML 与 preview artifact
  SHA-256 均为 `286b8787fb1f5fe8aa99902f1429b4f31fcf0ee9c35c28aecfe28b22528bfdcf`。
- 灰度仓库提交 `2415ee5622f7ec01de1d13c7b2ffb659d3029202` 的 `gray-build.json`
  指向源提交、源运行 `29996599026`、`daily-report-preview-29996599026` 和
  `formal_gray` channel；生产 `deploy` 明确跳过。

## 历史验证证据（2026-07-21）

- 验证提交为 `0cbaef35569fcecf1620a0eae25379bf071f450e`；本地门禁为 `211 passed`，
  `ruff check .`、`ruff format --check .`、`git diff --check` 和 `compileall` 全绿，
  仅有已知 Pydantic V2 弃用 warning。
- [push CI `29818445035`](https://github.com/Carl-312/daily-report-site/actions/runs/29818445035)
  与 [PR CI `29818447823`](https://github.com/Carl-312/daily-report-site/actions/runs/29818447823)
  的 `p0-contract`、`quality`、`gray-scenarios`、`final-regression` 全部通过。
- [正式灰度源运行 `29818465019`](https://github.com/Carl-312/daily-report-site/actions/runs/29818465019)
  以 `publish=false`、Tavily on、Trending on 生成 10 条新闻，Trending health 为健康，生产
  `deploy` 明确跳过。
- [灰度 Pages 运行 `29818600100`](https://github.com/Carl-312/daily-report-site-gray/actions/runs/29818600100)
  将同一 preview artifact 发布到
  [`daily-report-site-gray`](https://carl-312.github.io/daily-report-site-gray/)。线上与下载产物 HTML
  SHA-256 一致；日报页有 10 个编号段落、1 个独立互动区块和 1 个以最终入选条目
  反查生成的来源区块。
- `gray-build.json` 指向源仓库、上述提交、源运行与
  `daily-report-preview-29818465019`，channel 为 `formal_gray`。
- 2026-07-21 清理后，GitHub 仅保留这一套正式灰度运行与 deployment；旧灰度运行证据
  已从 GitHub 删除，不再作为可点击验收依据。

## 历史验证证据（2026-07-19）

- 本地门禁：`ruff check .`、`ruff format --check .`、`git diff --check` 全绿，pytest
  `214 passed`（仅既有 Pydantic V2 弃用 warning）。
- 当时的 GitHub Actions preview（运行记录已于 2026-07-21 按灰度清理删除）在
  `publish=false` 下使用有效仓库 Secret 完成 10 次 Tavily advanced 调用：22 条输入分成
  4 条 Story / 18 条 lead，5 条不同主体 lead 各搜索 2 轮，直接 Story 的冗余 verify 为 0。
- 预览 artifact 的正式短名单为 6 个独立事件、4 个来源；未解析 lead 只出现在“观察信号（未证实）”，
  每条正文均显示“发生了什么 / 为什么重要 / 直接来源 / 发布时间 / 置信度”。
- AGI Hunt Trending 实际返回 13/15，health 检查留下非阻塞 `exit code 1` 注解；workflow 总结仍为
  success，日报页尾显示 `fetch.agihunt_trending / agihunt_trending_unexpected_count`，deploy 跳过。
- 预览发现的型号漂移、通用 `AI` 误匹配和跨事件误聚类已转成确定性回归；最终提交未执行生产发布。

## 历史验证证据（2026-07-18）

- 本地门禁：`ruff check .`、`ruff format --check .`、`git diff --check` 全绿，pytest
  `198 passed`（仅既有 Pydantic V2 弃用 warning）。
- 真实在线 run `45b9f28149ab4c3d915dfa98f6dcf03a`：36 条候选通过
  `source_balanced_v2` 选出 10 个独立事件，ModelScope `Qwen/Qwen3.5-35B-A3B` 在一次本地
  契约修复后发布成功；Tavily 依生产默认保持关闭。
- 入选来源为 AGI Hunt 6、TechCrunch 2、The Verge 2；事件聚类拒绝 Apple/OpenAI 诉讼和
  Zoox 召回的各一条跨源重复；8 个话题分类，Claude/Grok/Kimi/Gemini 各 1 条，无配额放宽。
- 新版最大被提及主体为 xAI/Anthropic 各 2 条；旧版 Anthropic 4 条、Claude 3 条的集中度已下降。
- `SummaryResult` 从落盘 JSON 重放校验通过；权威 edition 与 `data/content/dist` 镜像哈希一致；
  正式 Markdown/HTML 均无内部趋势信号。

## 历史验证证据（2026-07-13）

- 本地：`ruff check .`、`ruff format --check .`、`git diff --check` 全绿，pytest `86 passed`（仅既有 Pydantic 弃用 warning）。
- [GitHub Actions preview run `29238871654`](https://github.com/Carl-312/daily-report-site/actions/runs/29238871654)：提交 `adc9bf0`，输入 `skip_generate=false`、`enable_tavily=false`、`publish=false`；2 条候选生成 2 条摘要，`a1/a2` 映射通过，artifact 成功，deploy job 跳过，未发布 Pages。
- [生产 run `29242010254`](https://github.com/Carl-312/daily-report-site/actions/runs/29242010254)：修复摘要契约后将旧页面替换为 2 条 JSON/Markdown，但产物审查发现 HTML 列表渲染为空，未作为最终验收通过。
- [最终生产 run `29242308496`](https://github.com/Carl-312/daily-report-site/actions/runs/29242308496)：PR #9 合并后的构建修复版本，`generate-and-deploy` 与 `deploy` 均成功；2 条输入生成 2 条摘要，`a1/a2` 和源 URL 映射通过，线上 HTML 实际显示两条摘要且无 `<p>10.`。
- [最终线上页面](https://carl-312.github.io/daily-report-site/2026-07-13.html)：上述历史版本页面显示 2 条摘要；本轮重构后应以新的当天产物审查结果为准。
- 该验证覆盖默认关闭 Tavily 的生产路径，不等同于 Tavily 开启路径的质量结论。

## 历史交付门禁证据

- 历史本地基线：Ruff lint/format 全绿，pytest `75 passed`（仅既有 Pydantic 弃用 warning）。
- GitHub Actions push run `29073505317`：`p0-contract`、`quality`、`gray-scenarios`、`final-regression` 全部通过。
- GitHub Actions pull request run `29073506997`：`p0-contract`、`quality`、`gray-scenarios`、`final-regression` 全部通过。
- 深度代码审查：`01-REVIEW.md` 当前 verdict 为 `passed`，无 P0/P1/P2 finding。

PR #8、#9 已通过 CI 后合并；后续生产变更仍应先走灰度 PR 和 Action 产物审查，不直接绕过发布门禁修改 `main`。

## 已接纳提交（按主题）

- `eaa0c21`、`6b9d18c`：运行契约、时钟、来源结果。
- `7432f1f`、`fe52d6f`、`90b88d7`、`8efd588`：原子写入、staging、promotion、站点构建。
- `580cbe6`、`731e3b6`、`e2bb273`：P0、灰度、最终回归 CI 检查点。
- `c6b1542`、`fc97bf0`、`3cab692`、`ae6050b`：no-op、manifest 决策、中断恢复、站点目录切换。
- `f4bbdeb`、`b3fab5b`、`251db09`：来源重试、尝试次数、Syft 故障分类。
- `f617360`、`f04d091`、`bfa66b7`：结构化摘要与离线 replay 元数据。
- `adc9bf0`：摘要来源契约、输入 URL/故事去重，以及 2026-07-13 真实预览验证。
- `9f4ea07`：同步 CI 可靠性文档门禁到新的 handbook 分层。
- `0ee5ebe`：修复紧凑有序列表渲染丢失摘要条目的问题，并增加构建回归测试。

---
*最后更新：2026-07-23*
