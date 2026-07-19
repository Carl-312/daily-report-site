# 每日新闻可靠性验收记录

**生产分支：** `main`
**PR：** #8、#9 已合并；#13 为本轮 draft
**状态：** 既有生产契约保持；Lead/Story 与多轮补证改造已完成非发布预览，待 #13 合并

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

## 最新验证证据（2026-07-19）

- 本地门禁：`ruff check .`、`ruff format --check .`、`git diff --check` 全绿，pytest
  `214 passed`（仅既有 Pydantic V2 弃用 warning）。
- [GitHub Actions preview run `29677644899`](https://github.com/Carl-312/daily-report-site/actions/runs/29677644899)
  在 `publish=false` 下使用有效仓库 Secret 完成 10 次 Tavily advanced 调用：22 条输入分成
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
*最后更新：2026-07-19*
